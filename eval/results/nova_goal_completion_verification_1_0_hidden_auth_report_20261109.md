# NOVA Goal Completion Verification 1.0
## Hidden Auth matched experiment

- **Date:** 2026-11-09
- **Branch:** research/goal-completion-verification-1.0
- **Task:** hidden_auth
- **Models:** qwen3.5:4b and qwen3.5:9b
- **Seeds:** 0?4
- **Memory:** Disabled
- **Arm:** A
**System prompt:** Unchanged across runs

## Hypothesis

Independent completion verification with sanitized feedback will prevent premature termination when the model proposes `done` before completing the task.

## Experimental conditions

- Control: existing controller behaviour; `done` is accepted without an in-loop verifier.
- Treatment: independent hidden-test verification on each proposed `done`.
- Treatment permits at most two verification attempts, providing one repair opportunity.
- Failed completion proposals are journaled as failed.
- The model receives generic feedback only. Hidden test output and source are not provided.
- The harness performs final independent verification after the agent terminates.

## Results

| Model | Condition | Verified success | Mean steps | Mean tokens | Median seconds |
|---|---|---:|---:|---:|---:|
| 4B | Control | 5/5 | 3.00 | 1665.0 | 18.28 |
| 4B | Treatment | 5/5 | 3.00 | 1665.0 | 7.52 |
| 9B | Control | 0/5 | 2.00 | 820.6 | 20.37 |
| 9B | Treatment | 5/5 | 4.00 | 2607.8 | 14.00 |

## Journal findings

- 4B control: read_file -> write_file -> done on all five seeds.
- 4B treatment: same three-action sequence; no rejected completion proposals.
- 9B control: read_file -> done on all five seeds; all five failed independent verification.
- 9B treatment: read_file -> done (failed) -> write_file -> done (succeeded) on all five seeds.

The rejected completion feedback recorded in the transcript was the generic message:
`Completion verification failed.`

## Interpretation

The treatment changed 9B's verified success on this task from 0/5 to 5/5. All five treatment runs exhibited the intended repair sequence.

4B remained at 5/5 and did not require a repair cycle.

For 9B, mean token use increased from 820.6 to 2607.8, approximately 3.18 times the control value. The extra inference and verification work is a measurable cost of recovery.

## Limitations

- This is a five-seed, single-task experiment; it does not establish generalization to other tasks.
- The treatment uses an oracle verifier supplied by the evaluation harness.
- It demonstrates recovery when an independent verifier exists, not automatic derivation of reliable completion criteria for arbitrary tasks.
- Wall-clock measurements are descriptive and may be affected by model warm-up and run order.
- The same hidden-test suite is used for in-loop treatment verification and final evaluation.

## Conclusion

The experiment supports the task-specific hypothesis that sanitized independent verification feedback can correct premature termination by qwen3.5:9b on hidden_auth.

Further testing across other task families is required before promoting this mechanism beyond experimental use.

## Canonical data

`qwen35_hidden_auth_completion_verification_20runs_20261109.csv`
