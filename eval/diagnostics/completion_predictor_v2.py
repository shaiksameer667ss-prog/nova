import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from eval.diagnostics.completion_predictor import load_examples
from nova.client import ModelClient
from nova.config import get_settings

TASK_PROMPT = (
    "The function store_items in vault.py is failing its tests with a "
    "PermissionError. Fix the implementation so it successfully returns "
    "the items. Do not modify tests."
)

PREDICT_PROMPT = """You are an independent completion predictor.

Predict whether the implementation, as it existed immediately before the
agent proposed done, would pass independent verification of the original task.

You receive the task, original source observations, actual write operations
and their contents, tool observations, and the proposed completion summary.

Evaluate the implementation evidence:
- A proposed fix is not proof that the fix was written.
- A write operation must be evaluated using its actual content.
- Do not assume actions occurred if they are absent.
- Judge the implementation as it existed before done was proposed.

You do not have access to hidden tests, hidden-test source, verifier output,
or future actions.

Return JSON only:
{"prediction":"PASS" or "FAIL","confidence":0-100,"reason":"one concise sentence"}
"""

PROMPT_HASH = hashlib.sha256(
    (PREDICT_PROMPT + TASK_PROMPT).encode("utf-8")
).hexdigest()

MODELS = ("qwen3.5:4b", "qwen3.5:9b")


def clip(value, limit=12000):
    value = str(value)
    if len(value) > limit:
        return value[:limit] + "\n[TRUNCATED]"
    return value


def build_messages(example):
    lines = []

    for step in example["transcript"]:
        step_number = int(step.get("step", -1))

        # Strict point-in-time boundary: never include the done action
        # itself or any subsequent repair action.
        if step_number >= example["done_step"]:
            continue

        action = step.get("action") or {}
        kind = action.get("action")

        if not kind:
            continue

        lines.append(f"\nSTEP {step_number}: {kind}")

        if action.get("path"):
            lines.append(f"PATH: {action['path']}")

        if kind == "read_file":
            lines.append(
                "SOURCE CONTENT OBSERVED BEFORE DONE:\n"
                + clip(step.get("observation", ""))
            )

        elif kind == "write_file":
            lines.append(
                "ACTUAL CONTENT WRITTEN BEFORE DONE:\n"
                + clip(action.get("content", ""))
            )

        observation = step.get("observation")
        if observation and kind not in {"read_file"}:
            lines.append("TOOL RESULT: " + clip(observation, 3000))

    user_content = (
        f"TASK:\n{TASK_PROMPT}\n\n"
        "EXECUTION EVIDENCE BEFORE PROPOSED COMPLETION:\n"
        + "\n".join(lines)
        + "\n\nPROPOSED DONE SUMMARY:\n"
        + str(example["done_summary"])
    )

    return [
        {"role": "system", "content": PREDICT_PROMPT},
        {"role": "user", "content": user_content},
    ]


def get_unique_examples(examples):
    unique = {}

    for example in examples:
        key = (example["model"], example["seed"])
        messages = build_messages(example)

        if key in unique:
            previous = unique[key]

            if (
                build_messages(previous) != messages
                or previous["actual_pass"] != example["actual_pass"]
            ):
                raise ValueError(f"Conflicting duplicate history: {key}")
        else:
            unique[key] = example

    if len(unique) != 10:
        raise ValueError(f"Expected 10 unique histories, found {len(unique)}")

    return list(unique.values())


def predict(example, predictor_model, settings):
    client = ModelClient(settings.model_copy(update={"model": predictor_model}))
    started = time.perf_counter()

    try:
        response, usage, status = client.chat_with_usage(
            build_messages(example),
            temperature=0.0,
            seed=0,
            max_tokens=2048,
        )

        elapsed = time.perf_counter() - started
        usage = usage or {}

        if status != "success":
            return None, usage, status, elapsed

        if usage.get("finish_reason") == "length" or not response.strip():
            return None, usage, "incomplete_generation", elapsed

        start = response.find("{")
        end = response.rfind("}")

        if start < 0 or end <= start:
            return None, usage, "malformed_prediction", elapsed

        data = json.loads(response[start:end + 1])

        label = str(data.get("prediction", "")).upper()
        confidence = data.get("confidence")
        reason = data.get("reason", "")

        if label not in {"PASS", "FAIL"}:
            return None, usage, "invalid_label", elapsed

        if (
            not isinstance(confidence, int)
            or isinstance(confidence, bool)
            or not 0 <= confidence <= 100
        ):
            return None, usage, "invalid_confidence", elapsed

        if not isinstance(reason, str):
            return None, usage, "invalid_reason", elapsed

        return {
            "prediction": label,
            "confidence": confidence,
            "reason": reason,
        }, usage, "success", elapsed

    except (json.JSONDecodeError, TypeError, KeyError, IndexError):
        return None, {}, "malformed_prediction", time.perf_counter() - started
    except Exception as exc:  # noqa: BLE001 - isolate individual model failures
        return (
            None,
            {},
            f"predictor_error:{type(exc).__name__}",
            time.perf_counter() - started,
        )
    finally:
        client.close()


def report(results):
    valid = [r for r in results if r["status"] == "success"]

    print("\n" + "=" * 64)
    print("STAGE 3 — V2 CROSS-MODEL RESULTS")
    print("=" * 64)

    for execution_model in MODELS:
        for predictor_model in MODELS:
            group = [
                r for r in valid
                if r["execution_model"] == execution_model
                and r["predictor_model"] == predictor_model
            ]

            correct = sum(r["correct"] for r in group)
            print(
                f"History {execution_model:12} | "
                f"Predictor {predictor_model:12} | "
                f"{correct}/{len(group)} correct"
            )

    print("\nOverall predictor performance:")
    for predictor_model in MODELS:
        group = [r for r in valid if r["predictor_model"] == predictor_model]
        passes = [r for r in group if r["actual_pass"]]
        failures = [r for r in group if not r["actual_pass"]]

        true_passes = sum(r["predicted"] == "PASS" for r in passes)
        caught_failures = sum(r["predicted"] == "FAIL" for r in failures)

        print(f"\n{predictor_model}: {len(group)}/10 usable predictions")

        if group:
            print(f"  Accuracy: {sum(r['correct'] for r in group)}/{len(group)}")

        if passes:
            print(f"  PASS recall: {true_passes}/{len(passes)}")

        if failures:
            print(f"  Failure recall: {caught_failures}/{len(failures)}")

        print(
            "  Predictor tokens:",
            sum(r.get("predictor_tokens") or 0 for r in group),
        )

    print(f"\nSuccessful predictions: {len(valid)}/20")
    print("Unavailable predictions:", len(results) - len(valid))


def main():
    settings = get_settings()
    examples = get_unique_examples(load_examples(settings))
    results = []

    print("Unique histories:", len(examples))
    print("Predictor models:", ", ".join(MODELS))
    print("Prompt SHA-256:", PROMPT_HASH)
    print("Mode: shadow; no execution intervention\n")

    for index, example in enumerate(examples, 1):
        actual = "PASS" if example["actual_pass"] else "FAIL"

        print(
            f"\nHISTORY {index}/10: {example['model']} "
            f"seed={example['seed']} actual={actual}",
            flush=True,
        )

        for predictor_model in MODELS:
            print(f"  Predictor: {predictor_model}", flush=True)

            prediction, usage, status, latency = predict(
                example, predictor_model, settings
            )

            result = {
                "run_id": example["run_id"],
                "execution_model": example["model"],
                "predictor_model": predictor_model,
                "seed": example["seed"],
                "actual": actual,
                "actual_pass": example["actual_pass"],
                "predicted": prediction["prediction"] if prediction else None,
                "confidence": prediction["confidence"] if prediction else None,
                "reason": prediction["reason"] if prediction else None,
                "correct": (
                    prediction["prediction"] == actual if prediction else None
                ),
                "status": status,
                "predictor_tokens": usage.get("total_tokens"),
                "latency_seconds": round(latency, 3),
            }
            results.append(result)

            if prediction:
                print(
                    f"    {prediction['prediction']} "
                    f"confidence={prediction['confidence']} "
                    f"{'CORRECT' if result['correct'] else 'WRONG'}"
                )
                print("    " + prediction["reason"])
            else:
                print("    Unavailable:", status)

    report(results)

    output_dir = Path("eval/results")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"stage3_predictor_v2_{timestamp}.json"

    output_path.write_text(
        json.dumps(
            {
                "experiment": "stage3_predictive_completion_v2",
                "prompt_sha256": PROMPT_HASH,
                "mode": "shadow",
                "unique_histories": 10,
                "predictors": list(MODELS),
                "results": results,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nSaved:", output_path)


if __name__ == "__main__":
    main()
