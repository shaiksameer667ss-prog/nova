# NOVA-EVAL 0.1
## Autonomous Agent Evaluation Specification

Status: Draft
Version: 0.1
Date: 2026-11-10
Scope: Software-engineering agent evaluation

## 1. Mission

NOVA-EVAL measures whether an autonomous agent can understand,
plan, execute, verify, recover from errors, and complete unfamiliar
software-engineering tasks.

The benchmark must measure actual environment outcomes, not merely
the model's claims of success.

It is an evaluation framework, not a production controller feature.

## 2. Core principles

1. Ground truth must come from independent verification.
2. Every task must have a known-broken starter and a known-correct reference.
3. Actions are not proof of success. A write operation can be incorrect.
4. Absence of a write operation is not proof of failure. Read-only tasks
   must be represented.
5. Task families must be separated between development and held-out evaluation.
6. Hidden tests and verifier implementation must not be exposed to the agent.
7. Every result must preserve model, prompt, task, seed, environment,
   configuration, cost, and verification provenance.
8. LLM judges cannot be the sole source of benchmark ground truth.
9. Failed or incomplete predictions must be reported as unavailable,
   not silently counted as correct or incorrect.
10. Benchmark changes must be versioned and reproducible.

## 3. Initial task families

NOVA-EVAL 0.1 will cover at least these eight families:

| ID | Family | Required capability |
|---|---|---|
| E01 | Read-only success | Solve and report without modifying files |
| E02 | Failed write | Detect unsuccessful file operations |
| E03 | Incorrect write | Detect logically incorrect modifications |
| E04 | Wrong-file edit | Modify the correct target and preserve protected files |
| E05 | Multi-step completion | Satisfy every required postcondition |
| E06 | Tool failure and recovery | Diagnose, recover, or report inability |
| E07 | Infeasible task | Recognize missing prerequisites or impossibility |
| E08 | Safety constraints | Avoid prohibited actions and unintended side effects |

Initial target: at least two distinct task instances per family.
This produces at least 16 candidate task instances.

This is an initial pilot target, not sufficient evidence of general intelligence.

## 4. Standard task package

Each task must contain:

task.yaml
repo/
hidden_tests/
reference/
VALIDITY.md
manifest.json

### task.yaml

Required fields:

- id
- family
- description
- prompt
- language
- framework
- difficulty
- protected_paths
- success_criteria
- forbidden_actions
- task_timeout_seconds
- max_steps

### repo/

The exact starting workspace supplied to the agent.

### hidden_tests/

Independent tests unavailable to the agent.

### reference/

Known-correct reference implementation or patch.
Never copied into the agent workspace.

### VALIDITY.md

Records the task admission checks and their results.

### manifest.json

Records task ID, version, family, split, hashes of all source files,
verifier version, reference version, and task provenance.

## 5. Mandatory verifier validation

A task cannot enter the benchmark until all checks pass.

V01 - Starter rejection:
The original broken implementation must fail verification.

V02 - Reference acceptance:
The known-correct reference must pass verification.

V03 - Incorrect mutation rejection:
At least one deliberately incorrect implementation must fail.

V04 - Protected-file integrity:
Files listed in protected_paths must remain unchanged.

V05 - Hidden-test isolation:
The agent must not receive hidden-test source or output.

V06 - Repeatability:
The reference implementation must pass repeatedly in clean environments.

V07 - Deterministic scoring:
The same workspace state and verifier version must produce the same result.

V08 - Budget feasibility:
The task must be solvable within documented time, step, and token budgets.

V09 - No verifier leakage:
Prompts, tool outputs, and environment variables must not reveal hidden answers.

V10 - Provenance:
All task, test, reference, and verifier hashes must be recorded.

Any failed gate results in task rejection or revision.

## 6. Evaluation splits

Tasks are split by task family, not merely by random seed.

Development:
Used for prompt development, debugging, and agent improvements.

Validation:
Used to compare candidate implementations and choose configurations.

Held-out:
Never used to tune prompts, rules, or model behavior.

Near-duplicate tasks must never cross these boundaries.

The initial pilot must explicitly identify which families are development
and which are held out.

## 7. Evaluation baselines

Every benchmark report should compare:

B0: Existing unmodified NOVA agent.
B1: Deterministic action and environment checks.
B2: Independent completion verification.
B3: Planning or prediction treatment, where applicable.

An improvement is accepted only when it exceeds the relevant baseline
on held-out tasks without unacceptable cost or safety regressions.

## 8. Required metrics

Task completion:
- Verified success rate
- Verified failure rate
- False-success rate
- False-failure rate

Execution:
- Steps per task
- Tool success rate
- Tool failure recovery rate
- Unnecessary actions
- Unintended modifications

Reasoning and planning:
- Plan feasibility
- Constraint adherence
- Postcondition coverage
- Replanning effectiveness

Reliability:
- Success consistency across seeds
- Robustness to task variations
- Failure localization
- Recovery after incorrect actions

Efficiency:
- Prompt tokens
- Completion tokens
- Total tokens
- Wall-clock time
- Inference cost

All metrics must include denominators and unavailable observations.

## 9. Statistical requirements

Report results by task family and model.

Do not treat multiple seeds of the same task as independent task templates.

Do not claim generalization from one task family.

Report confidence intervals and sample counts.
For paired comparisons, preserve task and seed pairing.

Any benchmark change that affects labels or difficulty requires a new
benchmark version.

## 10. Safety and execution isolation

Agent workspaces must be separate from trusted verifier code.

Hidden tests, reference patches, and host files must never be writable
through ordinary agent tools.

Untrusted task execution must not have unrestricted access to host files,
credentials, or networks.

The initial pilot is limited to benign software-engineering tasks.
Adversarial host-security testing is prohibited until stronger sandboxing
has been independently validated.

## 11. Task admission decision

Every task receives one status:

CANDIDATE
VALIDATING
ACCEPTED
REJECTED
RETIRED

Only ACCEPTED tasks can contribute to official benchmark scores.

Every rejection must record a reason.

## 12. Initial implementation milestones

M1 - Task manifest and package format.
M2 - Independent verifier validation tool.
M3 - Validate existing task library and identify reusable tasks.
M4 - Build missing adversarial task instances.
M5 - Establish development, validation, and held-out splits.
M6 - Run baseline evaluations for Qwen3.5 4B and 9B.
M7 - Publish NOVA-EVAL 0.1 results and limitations.

## 13. Success condition

NOVA-EVAL 0.1 is complete when:

- All admitted tasks pass every verifier validation gate.
- Every task has a reproducible reference solution.
- Development and held-out families are separated.
- Baseline measurements exist for both candidate models.
- Results include reliability, failure, safety, and cost metrics.
- The complete evaluation can be reproduced from versioned artifacts.

Passing NOVA-EVAL does not establish artificial general intelligence
or superintelligence. It establishes measured capabilities on a
documented evaluation suite.

## 14. Guiding principle

NOVA must prove what it accomplished through independent evidence.

A convincing explanation is not task completion.
A tool call is not task completion.
A file modification is not task completion.

The verified achievement of the requested goal is task completion.
