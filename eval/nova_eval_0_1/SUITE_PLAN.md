# NOVA-EVAL 0.1 — Benchmark Expansion Plan

Status: Proposed
Benchmark version: 0.1
Baseline commit: 9091b61
Date: 2026-11-10

## 1. Objective

Expand the initial NOVA-EVAL task package into a repeatable
software-engineering benchmark covering eight task families.

Target: 16 new candidate tasks, at least two per family.

The existing inventory_batch task remains an additional
development task in the state_management family.

## 2. Family assignments and splits

### Development

E02 — failed_write
- failed_write_transient
- failed_write_persistent

E06 — tool_failure_recovery
- transient_read_recovery
- persistent_list_recovery

E07 — infeasible_task
- missing_prerequisite
- conflicting_requirements

### Validation

E01 — read_only_success
- readonly_config_audit
- readonly_source_trace

E03 — incorrect_write
- incorrect_calculation_write
- incorrect_state_transition

### Held-out

E04 — wrong_file_edit
- nested_config_target
- duplicate_module_target

E05 — multi_step_completion
- schema_serializer_migration
- cross_module_validation

E08 — safety_constraints
- protected_config_preservation
- safe_cleanup

## 3. Split integrity

Each task family belongs to exactly one evaluation split.

Near-duplicate tasks must not cross split boundaries.

Development tasks may be used for debugging and planning
configuration.

Validation tasks may be used for choosing configurations.

Held-out tasks must not be used to tune prompts, policies,
planning rules, or model behavior.

## 4. Task package requirements

Every task must include:

- task.yaml
- repo/
- hidden_tests/
- reference/
- VALIDITY.md
- manifest.json

All package files must be included in the SHA-256 inventory.

New tasks start with status CANDIDATE.

No task may be marked ACCEPTED until V01-V10 have passed.

## 5. Validation requirements

V01: Reject the original starter.
V02: Accept the known-correct reference.
V03: Reject at least one incorrect mutation.
V04: Verify protected-file integrity.
V05: Verify hidden-test isolation.
V06: Verify repeatability.
V07: Verify deterministic scoring.
V08: Establish budget feasibility.
V09: Check for verifier leakage.
V10: Verify artifact provenance.

V05 remains unresolved until a separate verifier boundary
and adversarial tests are implemented.

## 6. Evaluation methodology

Compare:

B0: Existing NOVA baseline.
B1: Deterministic checks and recovery.
B2: Independent completion verification.
B3: Adaptive planning and bounded replanning.

Keep control and treatment runs matched by task and seed.

Initial planning comparison:
- Model: Qwen 3.5 4B.
- Target: five matched seeds per task.
- Conditions: baseline and planning.
- Same task prompt and environment configuration.
- Planning mode is the experimental treatment.

Qwen 3.5 9B comparison follows after the task suite
and initial evaluation procedure are stable.

## 7. Required measurements

- Verified success and failure.
- False-success and false-failure claims.
- Tool failures and recovery outcomes.
- Action count and agent steps.
- Planning and replanning calls.
- Prompt, completion and total tokens.
- Wall-clock execution time.
- Unnecessary actions.
- Unintended workspace modifications.

Report task-family results separately, with denominators,
sample counts, confidence intervals and missing observations.

Preserve raw run records and exact configuration provenance.

## 8. Research decisions

Adaptive planning remains opt-in.

A reduction in failure rate must be evaluated against
token overhead, latency and unintended side effects.

Read-only tasks provide negative controls for unnecessary
planning overhead.

Deterministic recovery must be compared against model-based
replanning where appropriate.

No production promotion is justified by pilot results alone.

## 9. Completion criteria

- At least 16 new candidate tasks.
- All eight required families represented.
- Family-level splits documented.
- Reproducible task packages and reference solutions.
- Independent scoring procedure established.
- V01-V10 evidence recorded for each task.
- Baseline and planning comparisons completed.
- Held-out results preserved without tuning leakage.

Tasks remain candidates until all mandatory gates pass.
