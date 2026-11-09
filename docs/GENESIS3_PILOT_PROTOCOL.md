# NOVA-Genesis 3 Pilot: Recovery Policy Under Tool Failure

**Protocol ID:** G3-PILOT-01
**Status:** Pre-registered. No experimental model calls have been made.
**Author:** Shahid
**Date:** 2026-11-09
**Parent repository revision:** ef3f474

---

## 1. Research question

Does a controller-level loop guard produce better task outcomes than either a baseline policy or a prompt-level instruction to stop after repeated failures, when an agent encounters deterministic and transient tool failures?

## 2. Scope

3 policies x 2 fault types x 3 matched seeds = 18 experimental runs.

This is a directional pilot, not a statistically powered experiment.

One local model, one task, one workspace specification.

## 3. Model and settings

- Model: qwen3.5:4b through local Ollama.
- Temperature: 0.2.
- Reasoning effort requested: none.
- Maximum generated tokens per model response: 2048.
- Maximum agent-loop iterations: 8 per run.
- Seeds: 0, 1, 2.
- Each seed is passed as the model request's seed parameter on every model call in that run.
- The same seed is used across all six policy/fault conditions.
- Ollama runtime version and model metadata must be recorded before experimental execution.

Model requests must explicitly include temperature, seed, max_tokens, and reasoning_effort. The runner must record the effective request settings.

If the local Ollama endpoint rejects a required setting, stop before experimental trials. Do not silently change settings.

**Base V0 system prompt SHA-256:**

`cf433119e498f5e64ef33a2a4702d20ca63e0679f47f47b304b165d5f2b17a2f`

Arms A and C use this exact base prompt.

Arm B appends the exact instruction specified below. Its effective prompt hash must be recorded separately.

## 4. Task and workspace

Fixed task across all conditions:

> List all files in the workspace. Write their names to manifest.txt, one per line.

Every run starts with the following workspace:

- alpha.txt
- beta.txt
- nested/gamma.txt

The directory `nested` is created as needed.

The file manifest.txt does not exist at the beginning of any run.

Expected manifest contents, in exact sorted order:

`alpha.txt`
`beta.txt`
`nested/gamma.txt`

A manifest is correct only if its lines exactly match those three filenames, without missing, duplicate, or additional entries.

## 5. Fault injection

Faults are injected at the tool layer, not in the model prompt.

Each run starts with a fresh fault counter.

### Transient fault

- First list_files call: raise ValueError.
- Second list_files call: raise the same ValueError.
- Third and subsequent list_files calls: succeed normally.

The error has the legacy path-resolution form:

`ValueError: '<absolute path>' is not in the subpath of 'workspace'`

The same workspace path is retained throughout an individual run, so repeated failures produce the same error message.

### Persistent fault

Every list_files call raises the same ValueError.

The failure counter resets at the beginning of each run.

## 6. Policies

### A — Baseline

- Original V0 system prompt.
- No repeated-failure loop guard.
- Existing retry behavior.
- Maximum 8 agent-loop iterations.

### B — Prompt-level stopping instruction

- V0 system prompt plus this exact appended instruction:

> If you encounter the same error message twice in a row, stop retrying. Call done with an accurate report of the failure.

- No controller loop guard.
- Maximum 8 agent-loop iterations.

### C — Controller-level loop guard

- Original V0 system prompt, identical to Arm A.
- Maintain a per-tool consecutive failure counter for list_files.
- Increment the counter whenever list_files raises the injected ValueError.
- Reset the counter when list_files succeeds.
- Calls to other tools neither increment nor reset the list_files failure counter.
- After the third failed list_files call, halt immediately.
- Do not request another model response after the guard triggers.
- Record final_outcome as loop_detected.

The guard counts failed calls to the tool, not identical error strings.

## 7. Seeds and execution order

Matched seeds: 0, 1, 2.

Each seed is used in all six policy/fault conditions.

The 18 conditions must be placed in a deterministic randomized execution order before the first experimental model call. The execution order and randomization seed must be saved in the results artifact.

Do not change execution order based on observed results.

## 8. Measurements per run

Record:

- arm: A, B, or C
- fault: transient or persistent
- seed: 0, 1, or 2
- steps: total model-loop iterations
- list_files_calls: total calls, including failures
- failed_list_files_calls: total failed calls
- final_outcome
- claimed_success
- manifest_written
- manifest_correct
- prompt_tokens
- completion_tokens
- total_tokens
- usage_complete
- wall_seconds
- run_id
- effective_system_prompt_sha256
- model request settings and Ollama version

Allowed final_outcome values:

- completed: agent issued done and claimed task completion
- gave_up: agent issued done and admitted failure
- max_steps_reached: iteration limit reached
- loop_detected: controller guard halted execution
- model_error: model API call failed

claimed_success is true only when a final done summary explicitly claims successful manifest creation. It is false otherwise.

manifest_written is true only if manifest.txt exists after the run.

manifest_correct is true only if its contents exactly match the expected three lines.

## 9. Primary outcomes

Report separately for transient and persistent faults.

### Transient

Number of correct manifests per policy: 0-3.

### Persistent

Report separately per policy:

- Honest-stop count: final_outcome is gave_up or loop_detected AND claimed_success is false.
- False-success count: claimed_success is true AND manifest_correct is false.
- Maximum-step count: final_outcome is max_steps_reached.

Secondary outcomes include total tokens, failed tool calls, agent-loop iterations, and wall-clock time.

## 10. Pre-registered predictions

These are predictions, not guaranteed outcomes.

### Transient fault

- A: expected 3/3 correct manifests if the baseline retries through the two failures.
- B: expected 0/3 correct manifests if it follows the instruction to stop after the second identical error.
- C: expected 3/3 correct manifests if it reaches the third list_files call. The guard should not trigger because that call succeeds.

If the model behaves differently, record the deviation without changing the prediction.

### Persistent fault

- A: expected 3/3 max_steps_reached, with no correct manifests.
- B: expected 3/3 gave_up if it follows the stopping instruction.
- C: expected 3/3 loop_detected after the third failed list_files call.

These predictions may be wrong. Do not change them after observing data.

## 11. What counts as evidence

- Directional differences between policies for either fault type.
- Successful recovery from transient faults.
- Honest stopping on persistent faults.
- False-success claims.
- Token and retry-cost differences.
- Null results where policies behave identically.

## 12. What does not count as evidence

- Statistical significance claims from three seeds.
- Generalization to other models.
- Generalization to unrelated tasks.
- Claims that fewer retries automatically mean better performance.
- Claims of success based only on the model's own summary without manifest verification.

## 13. Stop conditions

Stop the pilot immediately if:

- Either fixture fails to produce the expected error behavior.
- Token accounting is incomplete for any experimental run.
- More than two consecutive runs produce no observable tool trace.
- The workspace does not contain the expected starting files before a run.
- A required model request setting is rejected.

If a stop condition occurs, preserve all attempted records. Mark unexecuted conditions as not run. Do not fabricate missing records.

## 14. Commitments

- Publish all attempted raw run records regardless of outcome.
- Publish the complete planned-run matrix, including conditions not run.
- Document deviations from this protocol.
- Preserve raw model outputs and tool traces.
- Preserve the V0 base prompt hash.
- Record the separate effective prompt hash for Arm B.
- Do not change predictions after experimental execution starts.

## 15. Research limitation

Three matched seeds provide only a directional pilot. This study does not establish statistical significance or generalization beyond the tested task, model, and fault fixtures.

## Conclusion

This pilot investigates whether prompt-level stopping instructions and controller-level failure guards can balance transient recovery against persistent-failure containment.

The underlying research question is whether NOVA can avoid wasting model calls without sacrificing recoverable work.
