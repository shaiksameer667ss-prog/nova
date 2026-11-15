# NOVA Intelligence Benchmark

Programme: NOVA Intelligence Lab
Initial benchmark version: 0.1
Status: Specification draft

## 1. Objective

Measure NOVA's capabilities across diverse cognitive tasks and determine whether architectural or learning changes produce genuine, reproducible improvements.

This benchmark supplements NOVA-EVAL. It does not replace the existing software-engineering benchmark.

Passing this benchmark does not establish AGI or superintelligence.

## 2. Benchmark principles

1. Use independently established task ground truth.
2. Evaluate unfamiliar problems.
3. Separate development, validation and held-out evaluation.
4. Keep task families separated across splits where feasible.
5. Preserve task, model, prompt, configuration, seed and environment provenance.
6. Report failures and unavailable observations.
7. Do not rely exclusively on an LLM judge.
8. Measure cost, time and compute as well as answer quality.
9. Version tasks, verifiers and scoring rules.
10. Prevent the evaluated agent from modifying trusted evaluation code.

## 3. Capability families

### INT01 — Logical and abstract reasoning

Evaluate:
- Deduction.
- Constraint satisfaction.
- Pattern abstraction.
- Multi-step inference.
- Identification of invalid assumptions.

### INT02 — Mathematical reasoning

Evaluate:
- Arithmetic and symbolic reasoning.
- Multi-step mathematical problems.
- Proof construction where independently checkable.
- Error detection.
- Generalization across problem variations.

### INT03 — Planning and decision-making

Evaluate:
- Multi-step goals.
- Resource constraints.
- Dependency ordering.
- Changing task conditions.
- Recovery after failed actions.

### INT04 — Causal and predictive reasoning

Evaluate:
- Cause versus correlation.
- State transition prediction.
- Counterfactual outcomes.
- Dependency analysis.
- Calibration under uncertainty.

### INT05 — Learning and adaptation

Evaluate:
- Improvement after feedback.
- Correcting previously observed mistakes.
- Adaptation to changed rules.
- Avoiding repeated failure patterns.
- Knowledge retention.

### INT06 — Transfer and generalization

Evaluate:
- Applying learned methods to unfamiliar tasks.
- Transfer across different task families.
- Transfer across representations.
- Robustness to irrelevant surface changes.

### INT07 — Memory and long-horizon continuity

Evaluate:
- Retrieval of relevant past experience.
- Retention across context resets.
- Long task chains.
- Interrupted-task recovery.
- Avoiding stale or contradictory memories.

### INT08 — Tool use and environmental interaction

Evaluate:
- Selecting appropriate tools.
- Observing tool results.
- Handling failures.
- Avoiding unintended modifications.
- Verifying final environment state.

### INT09 — Scientific reasoning and discovery

Evaluate:
- Question formulation.
- Hypothesis quality.
- Experimental design.
- Prediction accuracy.
- Analysis of observations.
- Reproducibility.

### INT10 — Software engineering

Use NOVA-EVAL task packages and results for coding, repair, regression prevention and software verification.

Do not count NOVA-EVAL and its tasks as independent evidence when aggregating overlapping results.

## 4. Task package conventions

Reuse established NOVA-EVAL task package conventions where possible:

- task.yaml
- repo/
- hidden_tests/
- reference/
- VALIDITY.md
- manifest.json

New capabilities may require domain-specific task data and independent oracles.

Do not create a competing manifest format without documenting and validating the need.

Every task must record:
- Unique task ID and version.
- Capability family.
- Difficulty and prerequisites.
- Prompt and permitted tools.
- Success criteria.
- Forbidden actions.
- Resource budgets.
- Verifier identity and version.
- Source and artifact hashes.
- Evaluation split.

## 5. Evaluation splits

Development:
Used for debugging, architecture construction and prompt development.

Validation:
Used to choose between candidate configurations.

Held-out:
Reserved for final generalization evaluation.

Do not use held-out results to tune prompts, rules, model parameters or architecture choices.

Task families and near-duplicates should not cross splits in ways that reveal the evaluation distribution.

## 6. Measurement

Report at least:

Reasoning:
- Verified accuracy.
- Partial correctness where objectively measurable.
- Invalid inference rate.
- Calibration and uncertainty.

Planning:
- Goal completion.
- Constraint violations.
- Unnecessary actions.
- Recovery effectiveness.

Learning:
- Pre-learning performance.
- Post-learning performance.
- Retention.
- Transfer.
- Negative interference.

Generalization:
- Performance on unfamiliar tasks.
- Performance by family.
- Robustness to task variation.

Reliability:
- False success.
- False failure.
- Incomplete execution.
- Reproducibility across seeds.

Efficiency:
- Input and output tokens.
- Model calls.
- Wall-clock time.
- Compute where measurable.
- Inference cost.

Safety:
- Policy violations.
- Unauthorized actions.
- Protected-state modifications.
- Sandbox escapes or isolation failures.

Always report denominators, sample counts and unavailable data.

## 7. Scoring

Publish domain-level results first.

Do not create a single NOVA Intelligence Score until:
- Task validity is established.
- Scoring scales are justified.
- Domain weights are pre-registered.
- Aggregation behavior is tested.
- Uncertainty and missing data are reported.

A composite score must never conceal a severe capability or safety failure.

## 8. Baselines

At minimum compare:
- B0: Existing NOVA configuration.
- B1: Candidate reasoning treatment.
- B2: Candidate learning treatment when applicable.

Keep model identity, task, seed, prompt, environment and budgets matched wherever possible.

Additional treatments must have explicit hypotheses and ablations.

## 9. Benchmark integrity

The evaluated agent must not access:
- Held-out labels.
- Hidden verifier source.
- Reference answers.
- Evaluator credentials.
- Trusted evaluation-policy files.

The benchmark controller and candidate agent must have separate permissions.

A task's acceptance status must be based on executable evidence, not merely a declaration that validation passed.

## 10. Interpretation

A benchmark score establishes performance only on the documented tasks, models, environments and evaluation conditions.

Improvement on this benchmark is evidence of progress, not proof of general intelligence.

Claims must state the tested conditions, sample size, uncertainty, failures and known limitations.
