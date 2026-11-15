# NOVA Intelligence Experiment Protocol

Programme: NOVA Intelligence Lab
Protocol version: 0.1
Status: Draft

## 1. Purpose

Establish a reproducible method for evaluating changes to NOVA's reasoning, planning, memory, learning and architecture.

Experiments must distinguish genuine improvement from prompt familiarity, task leakage, increased resource consumption and random variation.

## 2. Preregistration

Before running an experiment, record:

- Experiment ID and version.
- Research question.
- Hypothesis.
- Primary outcome.
- Secondary outcomes.
- Incumbent baseline.
- Candidate treatment.
- Task IDs and benchmark version.
- Development, validation and held-out split.
- Model name and exact version or digest where available.
- Provider and endpoint.
- System prompt and task prompt hashes.
- Temperature and inference parameters.
- Tool permissions.
- Random seeds.
- Maximum steps and resource limits.
- Planned sample size.
- Exclusion rules.
- Statistical analysis.
- Safety constraints.
- Stop and rollback conditions.

Do not change the primary hypothesis or outcome after seeing results without recording a new protocol version.

## 3. Matched comparisons

Compare baseline and candidate using the same:
- Model.
- Task.
- Seed.
- Prompt.
- Environment.
- Available tools.
- Resource limits.

Randomize or block execution order where practical.

If a model, prompt, task or environment changes, record it as a separate experimental condition.

## 4. Resource accounting

Record:
- Prompt tokens.
- Completion tokens.
- Total tokens.
- Model calls.
- Tool calls.
- Wall-clock time.
- Compute or GPU time where measurable.
- Monetary inference cost where available.

Set comparable resource ceilings for baseline and treatment.

If a budget cannot be enforced, identify that limitation and classify the experiment as exploratory.

Report quality-versus-cost trade-offs. More compute must not be mistaken for better architecture.

## 5. Initial experiment: NOVA-IL-001

Research question:

Does adaptive planning improve NOVA's verified performance on unfamiliar multi-step tasks compared with its existing controller?

Provisional conditions:

A0 — Existing controller without the planning treatment.

A1 — Existing controller with adaptive planning enabled, after confirming the exact implementation and behavior in the source code.

Both conditions must use matched models, task instances, seeds, tools and resource ceilings.

Use independent task oracles.

The initial pilot is exploratory. It must not be presented as proof of general intelligence or broad reasoning superiority.

Before execution:
- Inspect the controller's planning implementation.
- Confirm that the two conditions are meaningfully different.
- Confirm that task runs use isolated workspaces and databases.
- Confirm that no production workspace or database can be deleted.
- Validate that the verifier is outside the agent workspace.
- Verify model and inference configuration.

## 6. Statistical treatment

Preserve paired task and seed observations.

Report:
- Number of distinct task templates.
- Number of task instances.
- Number of seeds.
- Per-family results.
- Paired differences.
- Confidence intervals where appropriate.
- Effect sizes.
- Missing and excluded observations.

Do not treat repeated seeds of one task as independent task templates.

A small pilot is used to estimate feasibility and variability. Confirmatory sample sizes should be justified by a power analysis or an explicitly documented precision target.

## 7. Failure handling

Preserve failed runs and raw traces.

Do not silently:
- Remove unfavorable observations.
- Replace failed runs.
- Change scoring rules.
- Exclude difficult tasks after observing results.
- Convert missing observations into successes.

Record infrastructure failures separately from model or reasoning failures.

Any re-run must have a recorded reason and identity.

## 8. Independent verification

The candidate must not determine its own score.

Prefer deterministic verifiers, exact state comparisons, executable tests and domain-specific oracles.

LLM judges may provide supplementary assessment but must not be the sole source of ground truth for primary outcomes.

Verify the evaluator independently before admitting tasks.

## 9. Self-evolution safety

Candidate-generated changes must run in isolated workspaces or disposable branches.

The candidate must not modify:
- Trusted verifier source.
- Hidden evaluation tasks.
- Acceptance thresholds.
- Security policies.
- Authorization settings.
- Its own audit records.

Require independent review and approval before consequential deployment.

Retain the incumbent and support rollback.

## 10. Promotion criteria

A candidate may be considered for promotion only if it:
- Improves the pre-registered primary outcome on held-out tasks.
- Does not introduce unacceptable regression in other capability families.
- Remains within approved resource budgets or has a justified trade-off.
- Passes reliability and safety checks.
- Reproduces its improvement in additional runs.
- Preserves complete provenance.

Do not promote a candidate solely because it performs better on development tasks.

## 11. Required artifacts

Every experiment should preserve:
- Protocol.
- Source commit.
- Model and provider identity.
- Configuration.
- Dataset and task hashes.
- Raw run records.
- Verifier version.
- Result summaries.
- Statistical analysis.
- Failure analysis.
- Promotion decision.

## 12. Claim discipline

Report exactly what was tested.

Do not describe a narrow task improvement as general intelligence.

Do not describe agent self-modification as recursive self-improvement without evidence that the improvement process itself became more effective under matched conditions.

No experiment in this protocol, by itself, establishes AGI or superintelligence.
