# NOVA Stage 3 — Predictive Completion Research Report

**Date:** 2026-11-10
**Branch:** research/stage-3-predictive-completion
**Task:** hidden_auth
**Models:** qwen3.5:4b and qwen3.5:9b
**Mode:** Shadow prediction; no execution intervention

## 1. Research question

Can a separate model inference predict whether an agent's proposed first `done` action will pass independent verification, using only evidence available before that proposal?

## 2. Dataset and ground truth

The canonical dataset contains 20 run records: five seeds for each model under control and treatment conditions.

Control and treatment histories were identical for every model/seed pair. The effective dataset therefore contains 10 distinct histories, not 20 independent observations.

Ground-truth labels were assigned to the first `done` proposal:
- 4B: five PASS histories.
- 9B: five FAIL histories.
- A rejected first `done` remains FAIL even when the treatment run later repairs the workspace and passes final verification.

The five 9B treatment runs eventually repaired the implementation, but their first completion proposals were rejected. The experiment predicts the first proposal, not the final run outcome.

## 3. V1 — Limited evidence

V1 exposed action names, paths, write lengths, and truncated observations, but deliberately withheld actual write content.

The initial predictor produced many false alarms on successful 4B histories. Cross-model predictions also showed that 4B could accept some incomplete 9B histories when it reasoned from the proposed fix rather than evidence of implementation.

V1 therefore exposed an important measurement problem: a predictor cannot reliably assess implementation when relevant implementation evidence is withheld.

## 4. V2 — Evidence-rich cross-model prediction

V2 exposed:
- Original source observations before the first `done`.
- Actual write operations and their content, when they occurred before `done`.
- Tool observations.
- The proposed completion summary.

V2 did not expose hidden-test source, hidden-test output, verifier results, or any action after the first `done`.

The same 10 unique histories were evaluated by both predictor models, producing a 2 × 2 cross-model design.

Prompt SHA-256:

`82c6d88e96986195f4bd29cbfe731ba99a67b7e08d4d609cc6c6d6c271488357`

### Results

| Execution history | 4B predictor | 9B predictor |
|---|---:|---:|
| 4B — PASS | 4/4 usable | 5/5 |
| 9B — FAIL | 5/5 | 5/5 |
| Total | 9/9 usable | 10/10 |

Overall:
- 19 usable predictions out of 20.
- 19 of 19 usable predictions were correct.
- 4B predictor: 9/9 correct, one incomplete generation.
- 9B predictor: 10/10 correct.
- 4B predictor tokens: 10,474.
- 9B predictor tokens: 11,640.

### Incomplete prediction

The 4B self-prediction for seed 1 did not produce a usable response. A retry with a 4,096-token budget also ended with `finish_reason=length` and empty content.

This is recorded as unavailable, not counted as correct or incorrect. No further retry was performed.

## 5. Interpretation

On this narrow task, both models correctly distinguished implementations that included the required `refresh()` call from implementations that did not.

The v2 results suggest that access to actual implementation evidence is important for completion prediction. V1 often rejected successful work because the predictor could not inspect the write content. V2 supplied that content and produced 19 correct predictions from 19 usable responses.

The five 9B failure histories showed a particularly clear signal: the agent had read and analyzed the source but had not written the required correction before proposing completion. Both predictors recognized this pattern in all five histories.

## 6. Limitations

1. Only 10 unique histories were evaluated.
2. All examples come from one task template.
3. Execution model and outcome are confounded: all 4B histories passed and all 9B histories failed.
4. The control/treatment rows are duplicate histories, not independent replications.
5. The v1-to-v2 change modified both the evidence supplied and the predictor instructions; this was not a controlled single-variable ablation.
6. The observed signal may be a task-specific missing-write heuristic rather than general completion reasoning.
7. Confidence scores are model-reported and are not calibrated probabilities.
8. No predictor output influenced execution. This was a shadow-mode diagnostic, not a production safety mechanism.

## 7. Conclusion

Stage 3 produced a promising narrow result:

**When provided with the actual pre-completion implementation evidence, both Qwen3.5 4B and 9B correctly classified all usable examples in this hidden_auth dataset.**

This demonstrates a useful diagnostic signal, not general self-monitoring capability. It does not prove that a model consciously knew its original completion proposal was wrong.

## 8. Recommended next research

Before integrating prediction into NOVA:
- Collect varied tasks with both successful and failed histories from each model.
- Include different failure modes, not only a missing write operation.
- Split evaluation by task template to prevent leakage between near-identical examples.
- Establish held-out failure recall, false-alarm rate, and inference-cost requirements.
- Test whether predictions remain useful when task-specific action heuristics are unavailable.

No production controller changes are part of this experiment.


## 9. Deterministic baseline comparison

A deterministic baseline was evaluated on the canonical 40-run model comparison dataset.

Rule:
Predict PASS when a `write_file` action occurs before the first `done` action; otherwise predict FAIL.

Results:

| Metric | Result |
|---|---:|
| Total records | 40 |
| True positives | 35 |
| True negatives | 5 |
| False positives | 0 |
| False negatives | 0 |
| Accuracy | 100% |
| Balanced accuracy | 100% |

All eight task/model groups achieved 5/5 accuracy.

### Comparison with the LLM predictor

The v2 LLM predictor achieved 19/19 correct predictions among usable responses on the ten unique hidden_auth histories. The deterministic baseline also achieved 10/10 on those histories and 40/40 on the broader benchmark.

No incremental predictive value from the LLM has been demonstrated on the available evidence.

### Important limitations

- Ten records overlap with the Stage 3 hidden_auth experiment.
- All five negative outcomes came from qwen3.5:9b on hidden_auth.
- The rule may simply identify this specific missing-write failure pattern.
- It may incorrectly reject valid read-only tasks.
- It may accept a failed implementation that performed a write but wrote incorrect content.
- The four task families and five failures are insufficient to establish generalization.

The rule is an evaluation baseline, not a production completion policy.

## 10. Stage 3 decision

Do not integrate the LLM predictor or the write-before-done heuristic into the production controller.

The next research phase should deliberately collect counterexamples:
1. Successful tasks that require no write operation.
2. Failed tasks that perform one or more write operations.
3. Incorrect writes, wrong-file writes, and incomplete multi-step changes.
4. Tasks with different verification criteria and action sequences.

The objective is to establish whether a predictor adds value beyond simple observable-action rules on held-out task families.
