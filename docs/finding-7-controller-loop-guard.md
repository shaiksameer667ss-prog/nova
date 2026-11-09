# NOVA Finding 7: Controller Guards Contain Persistent Tool-Failure Loops

**Protocol:** G3-PILOT-01
**Experiment:** Genesis 3 pilot
**Model:** qwen3.5:4b
**Runtime:** Ollama 0.40.15
**Date:** 9 November 2026
**Status:** 18/18 runs complete; token audit passed

## Research question

Does a controller-level loop guard produce better recovery-policy outcomes than a baseline policy or a prompt-level instruction to stop after repeated tool failures?

## Experimental design

Three policies were compared under two tool-failure conditions, using three matched seeds (0, 1, 2): 18 runs total.

- A — Baseline: original V0 system prompt, no loop guard.
- B — Prompt: V0 prompt plus an instruction to stop after the same error occurs twice consecutively.
- C — Controller: V0 prompt plus a deterministic guard that stops after three consecutive failed list_files calls.

The transient fixture failed on the first two list_files calls and succeeded on the third. The persistent fixture failed on every list_files call with the same legacy path-resolution ValueError.

All conditions used qwen3.5:4b, temperature 0.2, max_tokens 2048, reasoning_effort none, and a maximum of eight model-loop iterations per run.

The base V0 system-prompt SHA-256 was:
`cf433119e498f5e64ef33a2a4702d20ca63e0679f47f47b304b165d5f2b17a2f`

All 18 effective prompt hashes were independently checked. Arms A and C used the exact V0 prompt; Arm B used the expected appended instruction.

## Results

### Transient failures

| Policy | Correct manifests | Failed list_files calls | Total tokens |
|---|---:|---:|---:|
| A — Baseline | 3/3 | 6 | 6,256 |
| B — Prompt | 3/3 | 6 | 6,703 |
| C — Controller | 3/3 | 6 | 6,270 |

All three policies recovered from the transient fault. Each run experienced two identical failures and then succeeded on the third list_files call.

The controller guard did not prevent recovery because the successful third call reset the consecutive failure sequence before the guard threshold was reached.

The prompt-only instruction did not reduce transient task success in this pilot.

### Persistent failures

| Policy | Correct manifests | Final outcomes | Failed list_files calls | Total tokens |
|---|---:|---|---:|---:|
| A — Baseline | 0/3 | 3 max_steps_reached | 17 | 12,114 |
| B — Prompt | 0/3 | 3 max_steps_reached | 22 | 13,277 |
| C — Controller | 0/3 | 3 loop_detected | 9 | 3,203 |

The prompt-only policy did not stop the persistent retry loops. All three Arm B runs exhausted the eight-step limit. Their raw traces show repeated identical ValueError observations followed by further tool calls, rather than a final FAILED report.

The controller guard stopped all three persistent runs after exactly three failed list_files calls. It did not request another model response after the guard triggered.

The controller guard reduced persistent-fault token expenditure:

- 73.6% versus baseline (3,203 versus 12,114 tokens).
- 75.9% versus prompt-only (3,203 versus 13,277 tokens).

Average persistent-fault token use per run was:

- A: 4,038 tokens.
- B: 4,425.7 tokens.
- C: 1,067.7 tokens.

### Outcome classification

No false-success claims were recorded.

All nine transient runs produced correct manifests and explicit SUCCESS summaries.

No persistent run produced a correct manifest. Arms A and B reached their step limits without an explicit final FAILED summary. Arm C stopped through controller enforcement, not through model self-diagnosis.

The `loop_detected` outcome is therefore evidence of controller-enforced containment, not evidence that the model independently recognized the infrastructure failure.

## Measurement integrity

The execution and audit recorded:

- 18 of 18 planned conditions.
- 102 actual model requests.
- 47,823 total tokens.
- Complete usage records for all runs.
- Exact reconciliation between model-call token sums and run totals.
- No duplicate or missing experimental conditions.
- All starting workspace files preserved after each run.
- Complete traces for all recorded model steps.
- All 18 effective system-prompt hashes verified.
- No false-success claims.

The randomized schedule was generated and saved before experimental execution. The raw run records preserve model outputs, tool observations, usage, run identifiers, and timing.

## Interpretation

The pilot supports a narrow but useful engineering conclusion:

**A deterministic controller-level guard can contain persistent tool-failure retry loops without sacrificing recovery from the tested transient failure.**

The prompt-level stopping instruction did not reliably constrain the model's behavior after repeated identical errors. In contrast, the controller guard enforced the execution limit independently of the model's next action.

The guard did not repair the underlying tool failure or complete the persistent-failure task. It bounded resource expenditure and made the termination reason explicit.

This distinction matters: reliable execution constraints should be enforced by the controller rather than entrusted exclusively to natural-language instructions.

## Limitations

This was a three-seed directional pilot, not a statistically powered evaluation.

The evidence is limited to:

- One local model: qwen3.5:4b.
- One task: producing a workspace manifest.
- One transient fault pattern.
- One persistent deterministic path-resolution error.
- One controller guard threshold.
- One prompt-level stopping instruction.

The experiment does not establish generalization to other models, tools, tasks, or transient-failure patterns.

It does not demonstrate autonomous failure-source diagnosis. Arm C's stop decision was deterministic controller behavior.

The three-seed results should not be interpreted as a universal performance guarantee.

## Conclusion

The controller guard achieved 3/3 transient recovery and 3/3 persistent-loop containment. The baseline and prompt-only policies also achieved 3/3 transient recovery, but neither contained the persistent failure loops within the eight-step limit.

The observed reduction in persistent-fault token expenditure was substantial, while transient task correctness was preserved in all tested arms.

**Finding 7: For the tested NOVA workload, deterministic controller enforcement provided more reliable containment of persistent tool failures than a prompt-level instruction to stop retrying.**
