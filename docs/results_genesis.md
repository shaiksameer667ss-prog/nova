# NOVA-Genesis: Experimental Results

**Date:** 8 November 2026
**Model:** `qwen3.5:4b` via local Ollama
**Project:** NOVA
**Status:** Initial prompt-evolution and retry-policy experiments complete

## Executive summary

NOVA-Genesis investigated whether a local coding agent could improve its task performance through controlled system-prompt evolution while keeping model weights frozen.

The experiments tested one generated prompt candidate and two controller retry-policy interventions against a five-seed V0 baseline on the `inventory_batch` task.

The principal finding is negative: **none of the tested prompt-level or retry-policy interventions reliably eliminated malformed JSON or improved overall task success.**

The V1 candidate showed a modest improvement on its training task but regressed on validation. The combined retry-policy change and the isolated no-echo change both reduced verified success from 5/5 to 4/5.

No candidate or retry-policy intervention is promoted.

The experiments also demonstrated that NOVA's measurement infrastructure can preserve run provenance, reconcile model-call token usage, record malformed responses, and independently verify task outcomes.

## 1. Experimental design

The model weights remained frozen throughout these experiments. The system prompt was the evolved variable; Python controller modifications were tested separately as retry-policy interventions.

The independent evaluation harness:
- Reset the task workspace for each run.
- Executed benchmark tasks using the local model.
- Applied independent hidden-test verification.
- Recorded model-call token usage and run metadata.
- Recorded the effective system-prompt SHA-256 hash.
- Preserved malformed assistant outputs and parsing diagnostics.

The primary comparison used five seeds: 0–4.

**V0 system prompt SHA-256:**

`cf433119e498f5e64ef33a2a4702d20ca63e0679f47f47b304b165d5f2b17a2f`

No memory was injected into the runs reported below.

## 2. V0 baseline

The original V0 InventoryBatch experiment achieved:

| Metric | Result |
|---|---:|
| Verified success | 5/5 |
| Mean steps | 5.0 |
| Mean tokens | 4,758 |
| Total tokens | 23,790 |
| Malformed JSON responses | 10 |

All five runs passed independent verification.

The recurring malformed action response was 770 characters long and lacked the final outer JSON closing brace. The recorded finish reason was `stop`, rather than `length`.

This established a reproducible failure pattern despite successful task completion in the baseline runs: the controller sometimes had to recover from malformed actions before the task could finish.

## 3. V1: prompt evolution

The Evolver used successful, memory-free State Management task traces to generate a small reusable system-prompt addendum.

The candidate was generated locally and was not manually edited.

**V1 candidate SHA-256:**

`eec3dc8b282e5b57c5e8a341904621cec6b60642ad89c041f130226d0c6c3f74`

The generated addendum emphasized escaping backslashes and double quotes in JSON string values and checking JSON validity before responding.

The observed defect, however, was a missing outer closing brace—not incorrectly escaped inner quotes or backslashes. The proposed correction therefore did not accurately diagnose the recurring malformed response.

### V1 results

| Task | Version | Success | Mean steps | Mean tokens |
|---|---|---:|---:|---:|
| InventoryBatch | V0 | 5/5 | 5.0 | 4,758 |
| InventoryBatch | V1 | 5/5 | 4.4 | 4,273 |
| ScanConfig | V0 | 5/5 | 3.8 | 1,854.4 |
| ScanConfig | V1 | 5/5 | 4.0 | 2,245 |

On InventoryBatch, V1 reduced mean deployment tokens by approximately 10.2% and mean steps by 12%. Malformed responses decreased from 10 to 7.

However, all five V1 InventoryBatch runs still experienced at least one malformed JSON response.

On ScanConfig, V1 increased mean deployment tokens by approximately 21.1%, with no corresponding success improvement.

Across the two tasks, deployment tokens fell from 33,062 to 32,590, a reduction of approximately 1.43%.

The three generation attempts consumed 7,051 tokens in total:
- First failed generation: 4,096 tokens.
- Second failed generation: 1,689 tokens.
- Successful candidate generation: 1,266 tokens.

Including candidate-generation expenditure, the V1 experiment consumed 39,641 tokens compared with 33,062 for the corresponding V0 deployments.

**Decision:** V1 was not promoted. The results suggest task-specific improvement rather than reliable generalization, and the malformed JSON issue remained.

## 4. V0_CORRECTED: combined retry-policy change

The next experiment changed two controller behaviors together:

1. Stopped appending malformed assistant output back into the conversation history.
2. Replaced the original correction message with stronger instructions requiring one complete valid JSON object.

The two changes were bundled, so their individual effects could not be distinguished in this experiment.

### Results

| Metric | Original V0 | V0_CORRECTED |
|---|---:|---:|
| Verified success | 5/5 | 4/5 |
| Mean steps | 5.0 | 6.0 |
| Mean tokens | 4,758 | 4,710.2 |
| Total tokens | 23,790 | 23,551 |
| Malformed JSON responses | 10 | 17 |

The corrected condition used 239 fewer total tokens, approximately 1% less than baseline. However, it increased mean steps by 20%, increased malformed responses by 70%, and had one verification failure.

Seed 3 produced seven malformed responses with the same 770-character response hash and did not execute a valid action.

**Decision:** V0_CORRECTED was not promoted. The marginal token reduction does not compensate for lower verified success and more malformed responses.

## 5. V0_NOECHO_ORIGINAL: isolated retry-policy experiment

The final experiment retained the no-echo behavior but restored the original correction wording:

`Your last message was not valid JSON. Reply with JSON only.`

This isolated the no-echo mechanism from the stronger retry wording.

### Results

| Metric | Original V0 | No-echo + original wording |
|---|---:|---:|
| Verified success | 5/5 | 4/5 |
| Mean steps | 5.0 | 6.6 |
| Mean tokens | 4,758 | 5,159.2 |
| Total tokens | 23,790 | 25,796 |
| Malformed JSON responses | 10 | 20 |

The no-echo/original-wording condition used approximately 8.4% more tokens than baseline and 32% more steps. It produced twice as many malformed responses and one verification failure.

Comparing the two no-echo conditions:

- Stronger retry wording: 4/5 success, 6.0 mean steps, 4,710.2 mean tokens, 17 malformed responses.
- Original retry wording: 4/5 success, 6.6 mean steps, 5,159.2 mean tokens, 20 malformed responses.

Within these five-seed experiments, stronger wording performed better on token usage, steps, and malformed-response frequency when no-echo was held constant. Both conditions nevertheless had one failed run.

**Decision:** The no-echo/original-wording intervention was not promoted.

## 6. Measurement integrity

The measurement apparatus passed the audits conducted for these experiments.

For the five final no-echo/original-wording runs:
- Five of five run records were present.
- All 33 model calls had complete usage records.
- Model-call token sums reconciled exactly with runner totals.
- All five runs used the expected V0 prompt hash.
- No run injected memory.
- All 20 malformed-response hashes matched hashes recomputed from the recorded raw outputs.
- All five run audits passed.

The V0_CORRECTED runs also passed token-accounting reconciliation. The seed 3 diagnostic trace preserved the repeated malformed responses and parsing errors.

These checks support the integrity of the reported measurements. They do not establish that every possible source of experimental bias has been eliminated.

## 7. Overall findings

The three tested interventions were:

| Experiment | Result | Decision |
|---|---|---|
| V1 prompt evolution | Training-task improvement; validation regression; malformed JSON remained | Not promoted |
| V0_CORRECTED | Lower tokens by approximately 1%, but lower success and more malformed responses | Not promoted |
| V0_NOECHO_ORIGINAL | Higher token use, more steps, more malformed responses, lower success | Not promoted |

The experiments do not show a reliable prompt-level or retry-policy solution to the InventoryBatch malformed JSON failure.

They also do not prove that no prompt or controller design can fix the problem. The evidence is limited to this model, the tested task, the V0 prompt, the specific retry-policy variants, and five-seed evaluations.

## 8. Engineering implications

The repeated malformed response suggests that relying exclusively on free-form model-generated JSON is a fragile action interface for this workload.

A future engineering investigation should consider:
- Constrained decoding or grammar-based JSON generation.
- A structured-output interface with schema validation.
- Separating action metadata from large code-content strings.
- Controller-side validation and bounded recovery mechanisms.
- Further tests across task families and model configurations.

These are proposed future directions, not fixes demonstrated by the current experiments.

## 9. Final decision

NOVA-Genesis' initial prompt-evolution and retry-policy experiments are complete.

- Keep the original V0 prompt as the reference baseline.
- Do not promote V1.
- Do not promote V0_CORRECTED.
- Do not promote V0_NOECHO_ORIGINAL.
- Preserve all failed runs and diagnostic artifacts.
- Keep model weights frozen.
- Treat structured-output enforcement as a separate future engineering experiment.

**Final conclusion:** The tested prompt-evolution and retry-policy interventions did not reliably eliminate malformed JSON or improve overall verified performance. The measurement infrastructure produced auditable results, and the next meaningful step is to investigate structural enforcement of the action protocol rather than continue changing retry wording without stronger evidence.
