# NOVA-Budget: The Economics of Procedural Memory in 4B Models

## Abstract

We investigate the economic viability of extracting procedural skills from verified agent experiences and reusing them on subsequent tasks.

Using a locally hosted Qwen 3.5 4B Q4 model, we compare three deployment conditions: no memory, raw experiential memory, and an extracted procedural skill.

In a five-seed experiment on a related but different target task, all three conditions achieved 100% independently verified success. Raw experience increased mean inference consumption by 137.0% relative to the no-memory baseline. Procedural abstraction reduced deployment consumption by 50.2% relative to raw experience, but still cost 18.1% more than using no memory.

All 15 deployment runs passed token-ledger reconciliation against their individual model-call records.

These findings suggest that procedural abstraction can substantially reduce the context overhead of experiential replay, but do not establish that procedural memory is economically preferable to ordinary reasoning.

## 1. Experimental Infrastructure

NOVA is a locally operated autonomous agent using Qwen 3.5 4B Q4 through Ollama.

The system includes:

- An agent controller supporting file listing, reading and writing.
- Independent verification through a separate pytest harness.
- SQLite-based storage of runs, episodes and extracted skills.
- Exact provenance linking source runs, episodes and learned skills.
- SHA-256 hashes identifying injected memory content.
- Per-request token accounting through a `model_calls` table.

### 1.1 Token Accounting

Every measured inference request records:

- Prompt tokens.
- Completion tokens.
- Total tokens.
- Request status.
- Usage completeness.
- Raw API usage metadata.

Missing token measurements are represented as SQL `NULL`, not fabricated zeroes.

For the AuthSystem experiment, all 15 deployment runs were audited individually. In every run, the aggregate token counts in the `runs` table exactly matched the sum of the associated `model_calls` records.

**Accounting validation: 15/15 runs reconciled successfully.**

### 1.2 Regression and Infrastructure Reliability

During the initial Protocol-X pilot, two baseline runs encountered a path-resolution defect in NOVA's `list_files` tool.

The tool attempted to calculate relative paths using an absolute file path and a relative workspace path. This generated repeated `ValueError` observations and consumed the agent's available interaction budget.

This was an infrastructure failure, not evidence of a reasoning limitation in the model.

The defect was corrected by resolving both paths against an absolute workspace root. A regression test was added.

The test suite subsequently passed 24 tests.

The initial pre-fix experimental results are preserved separately and are not pooled with the post-fix results.

## 2. Acquisition and Skill Extraction

The source experience was acquired through a successful SignalRegistry task.

| Operation | Total tokens |
|---|---:|
| Source agent execution | 2,490 |
| Successful skill extraction | 2,614 |
| Measured subtotal | 5,104 |
| Earlier extraction attempt | Unknown |

The successful extraction produced a procedural skill with the following diagnostic approach:

1. Trace the execution flow of a helper function.
2. Identify state-modifying operations.
3. Determine which internal validity flags are invalidated.
4. Locate the critical operation that checks validity.
5. Identify whether an intermediate restoration operation is missing.

The extracted skill was stored with its exact source run and episode identifiers.

The earlier extraction attempt encountered a caller-side Python unpacking error after the inference response had been returned. Its token usage was not retained. The attempt was recorded in the ledger with an unknown token cost.

Consequently, 5,104 tokens is a measured subtotal, not a complete lifecycle-cost measurement.

## 3. AuthSystem Deployment Experiment

### 3.1 Task Design

The source task was SignalRegistry. The deployment task was AuthSystem, which uses different class names, method names and application terminology.

Both tasks implement the same underlying ordering constraint:

A state mutation invalidates authorization, so authorization must be refreshed after the last mutation and before finalization.

The AuthSystem task was not used during the extraction that produced the SignalRegistry skill.

However, the protocol is explicitly described in the target task's docstring. This experiment therefore measures memory-assisted transfer across related interfaces, not discovery of an undisclosed rule or generalization across unrelated task families.

### 3.2 Experimental Conditions

| Arm | Condition | Injected memory |
|---|---|---|
| A | Baseline | None |
| C | Raw experience | Original SignalRegistry execution trace |
| D | Learned skill | Extracted SignalRegistry procedure |

Five matched seeds were evaluated per condition.

All memory injections were checked against their exact database identifiers.

### 3.3 Results

All 15 deployment runs achieved independently verified success.

| Metric | A: No memory | C: Raw experience | D: Learned skill |
|---|---:|---:|---:|
| Verified success | 5/5 (100%) | 5/5 (100%) | 5/5 (100%) |
| Mean steps | 3.0 | 3.2 | 3.0 |
| Mean prompt tokens | 1,600.0 | 4,973.4 | 1,957.6 |
| Mean completion tokens | 860.8 | 859.2 | 947.6 |
| **Mean total tokens** | **2,460.8** | **5,832.6** | **2,905.2** |
| Mean wall time | 15.20 s | 14.06 s | 15.38 s |

## 4. Economic Analysis

### 4.1 Raw Experience Overhead

Raw experience increased mean deployment consumption by:

5,832.6 − 2,460.8 = 3,371.8 tokens.

Relative to the baseline, this represents approximately **137.0% additional inference consumption**.

The result is consistent with the cost of repeatedly processing a large execution trace as part of the conversation context.

### 4.2 Procedural Abstraction

The learned skill consumed:

5,832.6 − 2,905.2 = 2,927.4 fewer tokens per deployment than raw experience.

This represents a **50.2% reduction** in mean deployment token consumption relative to raw replay.

This is the strongest positive finding of the experiment: abstract procedural memory substantially reduced the context overhead of retaining the original experience.

### 4.3 The Memory Tax

The learned-skill condition consumed:

2,905.2 − 2,460.8 = 444.4 additional tokens per deployment.

This is approximately **18.1% more than the no-memory baseline**.

All conditions achieved the same verified success rate.

For this relatively simple, explicitly documented task, neither raw experience nor procedural memory demonstrated a token-efficiency advantage over ordinary reasoning without memory.

### 4.4 Provisional Break-Even Analysis

The measured successful extraction cost was 2,614 tokens.

The mean deployment saving of procedural memory compared with raw experience was 2,927.4 tokens.

Using only the measured extraction cost:

2,614 / 2,927.4 = approximately 0.89 deployments.

This is a provisional measured-cost-only ratio.

The actual break-even point remains unknown because the earlier extraction request incurred an unmeasured inference cost.

The source acquisition run is common to the raw-experience and learned-skill conditions when comparing their incremental costs. It is not common to the no-memory baseline.

Against the no-memory baseline, the learned skill consumed more tokens per deployment. Therefore, this experiment does not demonstrate a token-based economic advantage for skills over no memory.

A skill could still be worthwhile on tasks where memory improves reliability or enables solutions that the baseline cannot produce. That possibility was not established here.

## 5. Statistical and Methodological Limitations

1. **Small sample:** Each condition was evaluated on five seeds. The results are descriptive pilot findings, not definitive statistical evidence.

2. **One target task:** Five repetitions of AuthSystem do not establish generalization across multiple independent task families.

3. **Related protocol:** SignalRegistry and AuthSystem share the same underlying state-ordering invariant.

4. **Documented rule:** The target explicitly describes the protocol, allowing the baseline model to infer the required behavior.

5. **Incomplete extraction cost:** One earlier extraction request has unknown token consumption.

6. **No budget-matched baseline:** An agent receiving additional reasoning tokens without memory has not yet been compared against the memory-augmented conditions under an equal cumulative inference budget.

7. **Hardware and latency:** Wall-clock measurements come from local execution and should not be generalized to other hardware or serving configurations.

## 6. Future Work

The next experiment should evaluate multiple independent task families with different interfaces and varying difficulty.

It should include:

- A no-memory baseline.
- A baseline receiving additional reasoning under a matched token budget.
- Raw experience replay.
- One-shot procedural extraction.
- Validation-optimized procedural skills.

All arms should be compared using cumulative inference consumption, including acquisition, extraction, validation and deployment costs.

Evaluation should use held-out deployment tasks, exact provenance tracking, independent verification and complete token-ledger reconciliation.

A central research question is whether NOVA can determine when to retain raw experience, when to compress it into a procedural skill, and when memory is not worth its cost.

## Conclusion

The present experiment demonstrates that procedural abstraction can substantially reduce the inference cost of raw experiential replay.

However, procedural memory remained more expensive than using no memory on the evaluated AuthSystem task.

The evidence does not establish that procedural skills are universally beneficial or that they improve performance over ordinary reasoning.

The more precise research question for NOVA-Budget is:

**Under what task conditions and reuse horizons does the cost of acquiring, extracting and deploying procedural memory become economically worthwhile for a small local language model?**

The current results provide a reproducible starting point for investigating that question.

---

**Reproducibility artifacts**

- Source task: `signal_registry`
- Target task: `auth_system`
- Source run: `5a8ac88a-c895-4c7a-acba-c0d255c5f053`
- Extracted skill: `4fa3d101-7609-4fd0-9381-042983f966e3`
- Target experiment: five seeds across Arms A, C and D
- Token audit: 15/15 runs reconciled
- Post-fix dataset: `eval/results/auth_system_replication_20261108.json`
- Earlier Protocol-X dataset: `eval/results/protocol_x_signal_registry_postfix_20261108.json`
## HiddenAuth: Five-Seed Matched Procedural Transfer Experiment

- **Date:** 2026-11-08
- **Model:** Local Qwen3.5-4B Q4 through Ollama
- **Task:** `hidden_auth`
- **Arms:** A (no memory), D (learned procedural skill)
**Seeds:** 0–4

### Experimental design

HiddenAuth removes the explanatory protocol documentation from a stateful
Vault implementation. The agent receives a failing `store_items` function
and must diagnose the PermissionError and repair the implementation.

The underlying state-transition pattern is related to the SignalRegistry
source task used to acquire the procedural skill. This is a related-task
transfer experiment, not an independent task-family generalization test.

Arm A receives no memory. Arm D receives the exact previously extracted
skill:

- Source run: `5a8ac88a-c895-4c7a-acba-c0d255c5f053`
- Skill ID: `4fa3d101-7609-4fd0-9381-042983f966e3`

Each execution uses a reset workspace. Hidden tests are copied into a
separate temporary verification directory and are not exposed to the agent.

### Verifier correction and excluded attempts

The first Arm A and Arm D seed-0 executions were made while the
`hidden_tests` directory was empty. Pytest reported `no tests ran`.
Those executions are excluded from performance analysis and must not be
treated as verified failures.

The missing `test_vault.py` file was subsequently created. The verifier was
tested against the repaired workspace and returned:

- `VERIFIED: True`
- `1 passed`

Both arms were then rerun from the original task repository with the
functioning verifier. Those reruns, together with seeds 1–4, form the
valid five-seed matched dataset.

### Five-seed results

| Seed | A steps | A tokens | D steps | D tokens | D minus A tokens |
|---:|---:|---:|---:|---:|---:|
| 0 | 4 | 2,665 | 3 | 2,943 | +278 |
| 1 | 4 | 2,598 | 3 | 2,689 | +91 |
| 2 | 6 | 4,991 | 3 | 2,781 | -2,210 |
| 3 | 4 | 2,685 | 3 | 2,832 | +147 |
| 4 | 4 | 2,538 | 3 | 2,904 | +366 |
| **Mean** | **4.4** | **3,095.4** | **3.0** | **2,829.8** | **-265.6** |
| **Median tokens** | | **2,665** | | **2,832** | **+147 median paired difference** |

All five Arm A executions and all five Arm D executions passed independent
verification (10/10 total).

Descriptive findings:

- Arm D used 1.4 fewer agent steps on average.
- Arm D used 265.6 fewer deployment tokens on average, an 8.58% reduction
  relative to Arm A.
- However, Arm D consumed more tokens in four of the five matched seeds.
- The apparent mean token advantage is driven by seed 2, where Arm A used
  4,991 tokens and Arm D used 2,781.
- The median paired token difference was +147 tokens, meaning the typical
  matched seed used more tokens with memory.

The mean token reduction is therefore sensitive to run variability and
does not establish a consistent deployment-token advantage.

### Accounting and provenance audit

All ten selected runs passed the read-only database audit:

- All ten runs have `verified_success = 1`.
- Every model call has complete prompt, completion and total-token usage.
- Each model-call total equals prompt tokens plus completion tokens.
- The sum of model-call token usage reconciles exactly with its run-level
  token totals.
- All five D runs injected the exact expected skill ID.
- The D memory source run and skill provenance match the recorded source.
- All five A runs report no memory injection.

The complete run records, full run IDs, individual model-call records,
memory provenance and audit results are saved in:

`eval/results/hidden_auth_matched_5seeds_20261108.json`

### Deployment economics versus lifecycle economics

The five target deployments cost:

- Arm A: 15,477 total tokens, or 3,095.4 per verified target completion.
- Arm D: 14,149 total deployment tokens, or 2,829.8 per verified target
  completion.

The skill has additional creation costs:

| Lifecycle component | Measured tokens |
|---|---:|
| Source-task acquisition | 2,490 |
| Successful skill extraction | 2,614 |
| **Known skill creation cost** | **5,104** |

One earlier skill-extraction attempt ended in a client unpacking error.
Its token usage is unknown and is not counted as zero.

Including the known source acquisition and successful extraction costs,
the five-deployment Arm D workload consumed:

`14,149 + 2,490 + 2,614 = 19,253 tokens`

That equals 3,850.6 known lifecycle tokens per verified target completion
over five deployments, before adding the unknown failed-attempt cost.

For comparison, the no-memory Arm A target workload averaged 3,095.4
tokens per verified target completion.

A descriptive break-even extrapolation can be calculated from the observed
mean deployment difference:

`5,104 / (3,095.4 - 2,829.8) = approximately 19.2 deployments`

This suggests approximately 20 deployments to recover the known creation
cost if the observed mean deployment-token saving persists. This is only
a projection from five seeds, not an experimentally demonstrated
break-even point. The unknown failed extraction cost would increase it.

### Interpretation and limitations

The current experiment supports the following limited conclusion:

The learned procedural skill was associated with fewer agent steps in
all five matched seeds and achieved the same 5/5 verified success rate
as the no-memory baseline. Its deployment-token mean was lower, but four
of five paired runs consumed more tokens with memory. The mean advantage
was driven by one unusually expensive baseline execution.

After including the known acquisition and extraction costs, the learned
skill had higher lifecycle token cost over the five observed deployments.

This experiment does not establish generalization across independent
task families. HiddenAuth is related to the source Protocol-X task.
The sample comprises five seeds per arm on one target task. The results
are descriptive, not conclusive evidence of a general memory-efficiency
advantage.

The appropriate next step is replication across independent task
families and longer reuse horizons, while retaining complete lifecycle
accounting and independent verification.
