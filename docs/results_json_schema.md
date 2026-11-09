# NOVA-Genesis 2: JSON Schema as Tail-Risk Mitigation

## Abstract

We tested whether JSON Schema-constrained generation reduces token consumption in NOVA's agent loop. The experiment compared unconstrained generation with a flat JSON Schema supplied through Ollama's `response_format` interface, using five matched seeds of `inventory_batch`.

All 10 runs passed independent hidden-test verification. Across all five seeds, the schema arm used 8,489 tokens versus 9,930 for the control (14.5% fewer in aggregate). That difference came entirely from Seed 0: the control produced two malformed JSON responses and required recovery calls, while the schema arm completed the task in three steps. In Seeds 1–4, both arms had identical step and token counts.

The median paired token difference was **zero**. These results do not demonstrate a typical happy-path efficiency improvement. They provide a small, task-specific observation that schema-constrained generation can avoid malformed-output recovery overhead when the unconstrained arm encounters that failure mode.

## Method

- **Model:** `qwen3.5:4b`, served locally through Ollama 0.40.15.
- **Task:** `inventory_batch`.
- **Design:** Five matched seeds (0–4), with one control and one treatment run per seed.
- **System prompt:** Frozen V0 prompt, SHA-256: `cf433119e498f5e64ef33a2a4702d20ca63e0679f47f47b304b165d5f2b17a2f`.
- **Generation settings:** `reasoning_effort=none` and `max_tokens=2048` in both arms.
- **Control:** `V0_NOECHO_THINK_OFF`, unconstrained generation without a JSON Schema response format.
- **Treatment:** `V0_JSON_SCHEMA`, JSON Schema supplied through `response_format`.
- **Schema SHA-256:** `50cf913f5d8105e6425ef97b434d753cda82e384e16a019a3b8a5f1fa786bc15`.
- **Validation:** Independent hidden tests, separate from the agent's own completion signal.

The treatment schema is flat. Action-specific required and allowed fields are checked by the controller's client-side validation.

## Results

| Seed | Control (steps / tokens) | JSON Schema (steps / tokens) | Paired token delta* |
|---:|---:|---:|---:|
| 0 | 5 / 3,126 | 3 / 1,685 | −1,441 |
| 1 | 3 / 1,686 | 3 / 1,686 | 0 |
| 2 | 3 / 1,687 | 3 / 1,687 | 0 |
| 3 | 3 / 1,725 | 3 / 1,725 | 0 |
| 4 | 3 / 1,706 | 3 / 1,706 | 0 |
| **Mean** | **3.4 / 1,986** | **3.0 / 1,698** | **−288.2 tokens/run** |
| **Median (per arm)** | **3.0 / 1,706** | **3.0 / 1,687** | — |

\* Paired token delta is treatment minus control for each seed. The median of the five paired deltas is **0 tokens**. The per-arm medians differ by 19 tokens because the Seed 0 treatment value changes the rank order; that difference is not a nonzero median paired effect.

Summary:

- **10/10 runs** passed independent hidden-test verification.
- Aggregate token use was 14.5% lower in the treatment arm (8,489 versus 9,930 tokens).
- **Four of five matched pairs were exact ties** in both steps and tokens.
- The entire aggregate difference came from Seed 0.
- In Seed 0, the control trace contained two malformed JSON responses before completing the task; the treatment completed in three steps.
- Seed 1's audit explicitly reported zero malformed JSON and zero invalid actions in both arms. For Seeds 2–4, the recorded step counts were three in both arms, but malformed-response counters were not explicitly included in those final audit outputs.

## Findings

1. **Observed recovery-risk reduction.** In Seed 0, schema-constrained generation avoided the malformed-JSON recovery sequence observed in the matched control run. This saved 1,441 tokens and two controller steps in that run.
2. **No observed happy-path efficiency gain.** Seeds 1–4 had identical token and step counts between arms. The experiment therefore does not show that schema constraints make clean executions faster or cheaper.
3. **The mean is outlier-driven.** The 14.5% aggregate token reduction is mathematically correct, but it is entirely attributable to one matched seed. The median paired token difference is zero.
4. **Reasoning quality was not isolated.** The experiment measured execution, formatting/recovery behavior, token use, and task success. It does not establish that constrained decoding leaves the model's reasoning or action-selection behavior unchanged.

## Limitations

- **Small sample:** Five matched seeds are insufficient to establish a stable failure rate or a general performance effect.
- **Single task family:** Only `inventory_batch` was tested. Other task structures and action distributions may behave differently.
- **Single local model/runtime setup:** Results are specific to `qwen3.5:4b` on the tested Ollama 0.40.15 setup.
- **Malformed-response counters:** Explicit malformed/invalid-action counts were reported in the Seed 0 trace and Seed 1 audit. For Seeds 2–4, the final audit verified call counts and token reconciliation but did not print those counters; the three-step runs are consistent with the expected clean execution path, but are not a substitute for explicit counter audits.
- **Schema compatibility:** In the tested Ollama 0.40.15 setup, a schema using `oneOf` was rejected with HTTP 400. The experiment therefore used a flat schema and controller-side per-action validation.
- **No causal claim about reasoning:** The experiment was not designed to measure reasoning quality independently of output formatting.

## Engineering Recommendation

Treat JSON Schema-constrained generation as a **format-reliability mechanism worth evaluating**, not as a demonstrated general token-optimization technique.

It may be useful when malformed structured output causes expensive retries or disrupts an agent loop. Retain strict client-side validation even when using constrained output. Before making it a default production policy, test additional task families, models, and seeds, and explicitly record malformed-response and invalid-action counters for every run.

Do not use the 14.5% aggregate reduction as a typical expected saving. In this experiment, four of five matched pairs showed no token or step difference.

## Artifacts

Run result files:

- `eval/results/nova_json_schema_control_seed0_20261109.json`
- `eval/results/nova_json_schema_treatment_seed0_20261109.json`
- `eval/results/nova_json_schema_control_seed1_20261109.json`
- `eval/results/nova_json_schema_treatment_seed1_20261109.json`
- `eval/results/nova_json_schema_control_seed2_20261109.json`
- `eval/results/nova_json_schema_treatment_seed2_20261109.json`
- `eval/results/nova_json_schema_control_seed3_20261109.json`
- `eval/results/nova_json_schema_treatment_seed3_20261109.json`
- `eval/results/nova_json_schema_control_seed4_20261109.json`
- `eval/results/nova_json_schema_treatment_seed4_20261109.json`

All ten runs passed the recorded integrity audits for model-call count, usage completeness, token reconciliation, independent verification, no memory injection, and V0 prompt provenance. The treatment audits also verified the expected schema hash.
