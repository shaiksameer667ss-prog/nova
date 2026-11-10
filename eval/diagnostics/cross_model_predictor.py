import json
from datetime import UTC, datetime
from pathlib import Path

from eval.diagnostics.completion_predictor import (
    PROMPT_HASH,
    build_messages,
    load_examples,
    predict_completion,
)
from nova.config import get_settings

MODELS = {"qwen3.5:4b", "qwen3.5:9b"}

def unique_examples(examples):
    unique = {}

    for item in examples:
        key = (item["model"], item["seed"])
        if key in unique:
            previous = unique[key]
            old_messages = build_messages(
                previous["transcript"], previous["done_step"],
                previous["done_summary"]
            )
            new_messages = build_messages(
                item["transcript"], item["done_step"], item["done_summary"]
            )
            if old_messages != new_messages or previous["actual_pass"] != item["actual_pass"]:
                raise ValueError(f"Conflicting duplicate history: {key}")
        else:
            unique[key] = item

    if len(unique) != 10:
        raise ValueError(f"Expected 10 unique histories, found {len(unique)}")

    return list(unique.values())


def main():
    settings = get_settings()
    examples = unique_examples(load_examples(settings))
    results = []

    for index, example in enumerate(examples, 1):
        execution_model = example["model"]
        predictor_model = (
            "qwen3.5:9b" if execution_model == "qwen3.5:4b"
            else "qwen3.5:4b"
        )

        predictor_example = {**example, "model": predictor_model}
        actual = "PASS" if example["actual_pass"] else "FAIL"

        print(
            f"\n[{index}/10] history={execution_model} seed={example['seed']} "
            f"predictor={predictor_model} actual={actual}",
            flush=True,
        )

        prediction, usage, status, latency = predict_completion(
            predictor_example, settings
        )

        result = {
            "run_id": example["run_id"],
            "execution_model": execution_model,
            "predictor_model": predictor_model,
            "seed": example["seed"],
            "actual": actual,
            "actual_pass": example["actual_pass"],
            "predicted": prediction["prediction"] if prediction else None,
            "confidence": prediction["confidence"] if prediction else None,
            "reason": prediction["reason"] if prediction else None,
            "correct": prediction["prediction"] == actual if prediction else None,
            "status": status,
            "predictor_tokens": usage.get("total_tokens"),
            "latency_seconds": round(latency, 3),
        }
        results.append(result)

        if prediction:
            print(
                f"  Predicted: {prediction['prediction']} "
                f"confidence={prediction['confidence']} "
                f"{'CORRECT' if result['correct'] else 'WRONG'}"
            )
            print(f"  Reason: {prediction['reason']}")
        else:
            print(f"  Prediction unavailable: {status}")

    output_dir = Path("eval/results")
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    output_path = output_dir / f"stage3_cross_predictor_{timestamp}.json"

    output_path.write_text(
        json.dumps({
            "experiment": "stage3_cross_model_prediction_v1",
            "prompt_sha256": PROMPT_HASH,
            "mode": "shadow",
            "results": results,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"\nSaved: {output_path}")


if __name__ == "__main__":
    main()
