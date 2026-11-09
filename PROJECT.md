# NOVA — Complete Project, Research, Results, and GitHub Handover

**Repository:** https://github.com/shaiksameer667ss-prog/nova  
**Default branch:** `main`  
**Verified main HEAD:** `7453e7f` — `Publish Genesis 3 controller loop guard finding`  
**Last repository state checked:** 9 November 2026  
**Project description:** Local autonomous skill-learning and coding/research agent; research prototype, not a production-hardened service.

> This document is a handover record of the project and the work completed in the repository. It records positive results, negative results, failed hypotheses, limitations, missing evidence, branches, important commits, and file locations. It intentionally does not turn pilot observations into universal claims.

---

## 1. Executive summary

NOVA is a local agent research project focused on whether a small language model can use tools, retain experience, extract procedural skills, and apply structured execution policies. The experiments were run primarily with `qwen3.5:4b` through local Ollama on a Windows 10 laptop, with no paid model API budget.

The work produced seven research findings:

1. **Procedural memory economics are conditional, not universal.** Learned skills compressed raw experience, but were not consistently cheaper than ordinary no-memory execution once deployment and creation costs were considered.
2. **Prompt evolution did not generalize reliably.** A V1 prompt candidate helped on one task and regressed on a validation task; its generation cost also mattered.
3. **The tested retry wording/controller interventions did not reliably fix malformed JSON.** The tested no-echo and retry-message interventions reduced verified success and increased malformed responses.
4. **The tested JSON Schema `oneOf` structure was rejected by the tested Ollama 0.40.15 endpoint.** The work therefore used a flat schema and client-side action validation.
5. **Flat JSON Schema reduced a specific recovery-tail event, not typical happy-path cost.** The 14.5% aggregate token reduction came entirely from one matched seed; the median paired difference was zero.
6. **Infrastructure defects can masquerade as model limitations.** A `list_files` path-resolution defect plausibly explained earlier no-memory baseline failures; post-fix baseline success rose from 3/5 to 5/5. The before/after evidence is observational, not randomized causal proof.
7. **A deterministic controller guard contained persistent tool-failure loops better than a prompt-only instruction in the Genesis 3 pilot.** All tested transient runs recovered; the guard stopped all three persistent loops and reduced persistent-fault token usage substantially. This was a three-seed pilot using a separate diagnostic runner, not proof of generalization or autonomous model diagnosis.

The repository includes source code, benchmark tasks with separate hidden tests, experiment harnesses, raw JSON result artifacts, diagnostic reproductions, protocol documents, and research reports. The seven findings are not all separate `finding-N.md` documents: Findings 1–3 are primarily organized in `docs/results.md` and `docs/results_genesis.md`; Findings 4–5 are in `docs/results_json_schema.md`; Findings 6 and 7 have dedicated files.

---

## 2. Project goals and research questions

### 2.1 Core project question

The README frames NOVA's central question as:

> Does an AI extract a reusable skill from a verified task, remember it, and apply it to a related unseen task?

The broader work also asks:

- What is the token and execution cost of no memory, raw experience, and extracted procedural memory?
- Does prompt evolution improve task performance beyond the task used to create the prompt candidate?
- Can retry wording resolve recurring malformed structured output?
- Can structured output constraints reduce malformed actions and recovery overhead?
- Can tool/runtime defects create the appearance of a model reasoning failure?
- Can an enforceable controller policy prevent repeated tool-failure loops without blocking useful retries?

### 2.2 Intended research discipline

A recurring project principle is to preserve raw traces, token usage, prompt hashes, independent verification, and failed outcomes. Several early apparently positive claims were narrowed or corrected after deeper audits. Final reports deliberately distinguish:

- agent-reported success from independently verified success;
- deployment token cost from lifecycle cost, including skill creation;
- mean differences from median paired differences;
- related-task transfer from independent task-family generalization;
- observed correlation or before/after improvement from randomized causal evidence;
- model self-diagnosis from a deterministic controller intervention.

---

## 3. Runtime, hardware, and software environment

### 3.1 User's experimental machine

The environment used for this work was reported as:

- Operating system: Windows 10.
- Python: 3.14.2 locally.
- pytest: 9.2.0 locally.
- Ollama: 0.40.15.
- Model: `qwen3.5:4b`.
- Model metadata: 4.2B parameters, Q4_K_M quantization, context length 262,144, Qwen 3.5 architecture.
- GPU: NVIDIA RTX 3070 Laptop GPU, 8 GB VRAM.
- System RAM: approximately 15.7 GB.
- Model API: Ollama OpenAI-compatible endpoint at `http://localhost:11434/v1`.
- Temperature used for the main NOVA runs: 0.2.
- Budget: local inference; no paid API budget was used for the reported local experiments.

The repository's `pyproject.toml` declares Python `>=3.12`, not specifically 3.14.2. The environment above is the reported local execution setup, not a formal compatibility matrix.

### 3.2 Dependencies declared in `pyproject.toml`

Runtime dependencies include:

- FastAPI
- Pydantic
- HTTPX
- psycopg binary package
- SQLAlchemy
- pgvector
- python-dotenv
- PyYAML
- NumPy
- SciPy

Development extras include pytest, pytest-cov, and Ruff.

The project metadata currently declares version `0.4.0` and package name `nova`.

### 3.3 Model request and accounting behavior

`src/nova/client.py` sends chat-completion requests using HTTPX. The client validates that prompt, completion, and total token counts are non-negative integers and that prompt plus completion equals total. Incomplete or inconsistent usage is marked incomplete rather than silently treated as valid.

Genesis 3 additionally sent `seed`, `temperature`, `max_tokens`, and `reasoning_effort="none"` on each model request. The local Ollama 0.40.15 source/API behavior was checked for compatibility before the experiment. The reported Genesis 3 requests used temperature 0.2 and max_tokens 2048.

---

## 4. System architecture and implementation

### 4.1 High-level loop

The main agent loop is implemented in `src/nova/controller/loop.py`:

1. Load the system prompt and task.
2. Send the conversation to the local model through `ModelClient`.
3. Parse one JSON action per response.
4. Dispatch the action to a local tool.
5. Append the tool observation to the conversation.
6. Continue until `done`, a model/API problem, or the configured step limit.
7. Record run, episode, and model-call information in SQLite.

### 4.2 Supported actions in the main controller

The current standard controller prompt describes these actions:

- `write_file(path, content)`
- `read_file(path)`
- `list_files(subdir)`
- `done(summary)`

The tools are local workspace operations. Path safety is implemented in `src/nova/tools/file_ops.py` using `_safe_path` to reject paths escaping the workspace.

### 4.3 Memory and provenance

`src/nova/memory/db.py` defines SQLite tables for:

- `runs`
- `model_calls`
- `episodes`
- `skills`
- `retrieval_log`

The run and model-call tables record token counts and usage completeness. Episodes and skills include source identifiers, allowing skill and raw-trace provenance to be traced to a source run/episode. The schema is created and incrementally extended by the SQLite connection helper.

### 4.4 Evaluation and hidden-test separation

Benchmark tasks live under `eval/tasks/`. Each task directory generally contains:

- `task.yaml` — task prompt and metadata;
- `repo/` — starting code or workspace files;
- `hidden_tests/` — independent verification tests not supplied to the agent.

`eval/harness/runner.py` prepares the task workspace, runs the agent, invokes hidden tests in a separate temporary directory, and records verified outcome and memory provenance. Agent self-reported success is explicitly not treated as equivalent to hidden-test verification.

### 4.5 Prompt evolution

`src/nova/evolve.py` is the prompt-evolution component. The prompt experiments kept the model weights frozen and evaluated a generated candidate prompt against baseline and validation tasks.

### 4.6 Important distinction: Genesis 3 guard versus production controller

Genesis 3 tested a deterministic loop guard in a **standalone experimental runner** at `eval/diagnostics/genesis3_pilot_runner.py`. The experimental result demonstrates the behavior of that tested runner and injected fault conditions. It does **not** mean the three-failure guard was merged into or enabled in the standard production agent loop at `src/nova/controller/loop.py`.

That distinction must be retained in future descriptions of Finding 7.

---

## 5. The seven research findings

## Finding 1 — Procedural memory economics are conditional, not universal

**Primary report:** `docs/results.md`  
**Related artifacts:** AuthSystem and HiddenAuth JSON files in `eval/results/`.

### AuthSystem matched-seed experiment

Five seeds were evaluated in each of three deployment conditions:

| Arm | Condition | Mean tokens | Mean steps | Verified success |
|---|---|---:|---:|---:|
| A | No memory | 2,460.8 | 3.0 | 5/5 |
| C | Raw experience | 5,832.6 | 3.2 | 5/5 |
| D | Learned skill | 2,905.2 | 3.0 | 5/5 |

Interpretation:

- The learned skill used approximately 50.2% fewer deployment tokens than the raw trace.
- The learned skill still used approximately 18.1% more deployment tokens than no memory.
- All three arms achieved 5/5 verified success in this five-seed set.
- The result supports compression of raw experience into a more compact procedure; it does not prove that memory is cheaper than ordinary reasoning.
- The AuthSystem target task contained the relevant protocol in its docstring. The source and target tasks were related. This is not independent generalization to an unrelated task family.

### HiddenAuth matched-seed experiment

A no-memory arm (A) and learned-skill arm (D) were evaluated using five matched seeds. All ten final runs passed independent verification.

- A token counts: `[2665, 2598, 4991, 2685, 2538]`; mean 3,095.4 tokens.
- D token counts: `[2943, 2689, 2781, 2832, 2904]`; mean 2,829.8 tokens.
- Mean steps: A 4.4, D 3.0.
- D used fewer steps on every seed.
- D used more tokens on four of the five seeds; the mean token advantage was driven by one expensive A seed.
- The median paired token difference was approximately +147 tokens for D relative to A, so the median did not show a token saving for the skill.

Known skill creation cost:

- Source acquisition: 2,490 tokens.
- Successful extraction: 2,614 tokens.
- Known total: 5,104 tokens.
- An earlier failed extraction attempt had an unknown cost and is not included in that known total.

The lifecycle cost of acquiring/extracting the skill and then deploying it was higher than the no-memory alternative over the observed five deployments. Do not use the deployment-only mean to claim lifecycle savings.

### Negative results and limitations

- Skills were cheaper than raw experience in AuthSystem deployment, but not cheaper than no memory.
- HiddenAuth showed fewer steps, but not a consistent per-seed token saving.
- Skill creation has an upfront cost.
- One earlier HiddenAuth attempt had empty hidden tests and was invalid; it was excluded and the five valid matched seeds were rerun.
- This is related-task transfer, not proof of broad out-of-distribution generalization.
- The reconstructed detailed AuthSystem export contains all 15 runs and model-call details, but `system_prompt_sha256` was unavailable/null for those recovered records. This limitation is documented in `docs/REPRODUCIBILITY.md`.

**Defensible conclusion:** Procedural abstraction can reduce the context overhead of raw replay. Whether it is economically worthwhile depends on baseline cost, deployment count, reliability benefit, and skill-creation cost.

---

## Finding 2 — Prompt evolution showed task-specific improvement, not reliable generalization

**Primary report:** `docs/results_genesis.md`  
**Key hashes:**

- V0 prompt: `cf433119e498f5e64ef33a2a4702d20ca63e0679f47f47b304b165d5f2b17a2f`
- V1 candidate: `eec3dc8b282e5b57c5e8a341904621cec6b60642ad89c041f130226d0c6c3f74`

### Positive result on the training task

InventoryBatch:

| Version | Verified success | Mean steps | Mean tokens | Malformed JSON responses |
|---|---:|---:|---:|---:|
| V0 | 5/5 | 5.0 | 4,758 | 10 |
| V1 | 5/5 | 4.4 | 4,273 | 7 |

V1 reduced mean InventoryBatch deployment tokens by about 10.2% and steps by 12% in this five-seed evaluation. Malformed responses fell from 10 to 7.

### Negative validation result

ScanConfig:

| Version | Verified success | Mean steps | Mean tokens |
|---|---:|---:|---:|
| V0 | 5/5 | 3.8 | 1,854.4 |
| V1 | 5/5 | 4.0 | 2,245 |

V1 increased ScanConfig mean deployment tokens by approximately 21.1% and did not improve success.

Across the two task deployments, tokens changed from 33,062 to 32,590, a reduction of about 1.43% before including candidate-generation cost.

V1 generation attempts consumed 7,051 tokens:

- First failed generation: 4,096 tokens.
- Second failed generation: 1,689 tokens.
- Successful candidate generation: 1,266 tokens.

Including those attempts, V1's experiment cost was 39,641 tokens versus 33,062 for the corresponding V0 deployments — 6,579 tokens more.

### Failure-diagnosis mismatch

The candidate prompt focused on escaping quotes/backslashes and JSON validity. The recurring observed malformed response instead lacked the final outer JSON closing brace. The proposed correction did not accurately target the actual defect.

### Decision

V1 was not promoted. It showed a task-specific improvement and a validation regression; its generation cost erased the small aggregate deployment-only saving.

**Defensible conclusion:** The one candidate did not establish reliable prompt generalization or a net token benefit.

---

## Finding 3 — Tested retry-policy changes did not reliably fix malformed JSON

**Primary report:** `docs/results_genesis.md`.

The original V0 baseline on InventoryBatch achieved 5/5 verified success, 5.0 mean steps, 4,758 mean tokens, and 10 malformed JSON responses.

### V0_CORRECTED — bundled intervention

This condition combined:

1. Not echoing malformed assistant output back into the model history.
2. Stronger retry wording asking for one complete valid JSON object.

Results:

| Metric | V0 | V0_CORRECTED |
|---|---:|---:|
| Verified success | 5/5 | 4/5 |
| Mean steps | 5.0 | 6.0 |
| Mean tokens | 4,758 | 4,710.2 |
| Malformed responses | 10 | 17 |

The token reduction was only about 1%, while success declined and malformed responses rose. Because two changes were bundled, this test does not isolate their individual effects.

### V0_NOECHO_ORIGINAL — no-echo with original wording

| Metric | V0 | No-echo + original wording |
|---|---:|---:|
| Verified success | 5/5 | 4/5 |
| Mean steps | 5.0 | 6.6 |
| Mean tokens | 4,758 | 5,159.2 |
| Malformed responses | 10 | 20 |

This isolated no-echo from the stronger retry wording. It used approximately 8.4% more tokens, 32% more steps, twice as many malformed responses, and had one failed verification.

Within the two no-echo conditions, stronger retry wording performed better than original wording on steps, tokens, and malformed-response count, but both still achieved only 4/5 success. Neither intervention was promoted.

**Defensible conclusion:** These specific wording/no-echo interventions did not reliably fix the malformed-output failure. This is not proof that every possible retry strategy is ineffective.

---

## Finding 4 — Tested JSON Schema `oneOf` structure was rejected by Ollama 0.40.15

**Primary report:** `docs/results_json_schema.md`, Compatibility limitations section.

During the tested Ollama 0.40.15 work, a JSON Schema using `oneOf` was rejected with HTTP 400. The JSON Schema experiment therefore used a flat schema for the actions and controller-side per-action validation.

**Evidence limitation:** The rejection is recorded in the research report, but a separate raw HTTP 400 response artifact was not found in the committed `eval/results/` inventory when this handover was prepared. Do not claim that a standalone raw error response is archived.

**Defensible conclusion:** The tested schema shape was incompatible with the tested Ollama 0.40.15 path. This does not prove that all Ollama versions, all schemas, or all `oneOf` use are unsupported.

---

## Finding 5 — Flat JSON Schema mitigated one recovery-tail event; it did not show typical efficiency improvement

**Primary report:** `docs/results_json_schema.md`.  
**Schema SHA-256:** `50cf913f5d8105e6425ef97b434d753cda82e384e16a019a3b8a5f1fa786bc15`.

### Matched-seed results

| Seed | Control steps/tokens | Schema steps/tokens | Paired token delta (schema − control) |
|---:|---:|---:|---:|
| 0 | 5 / 3,126 | 3 / 1,685 | −1,441 |
| 1 | 3 / 1,686 | 3 / 1,686 | 0 |
| 2 | 3 / 1,687 | 3 / 1,687 | 0 |
| 3 | 3 / 1,725 | 3 / 1,725 | 0 |
| 4 | 3 / 1,706 | 3 / 1,706 | 0 |
| **Total** | **9,930** | **8,489** | **−1,441** |

- All 10 runs passed independent hidden-test verification.
- Aggregate treatment use was 14.5% lower.
- The entire aggregate difference came from Seed 0, where control encountered two malformed JSON responses and required recovery.
- Seeds 1–4 were exact ties in both steps and tokens.
- The median paired token difference was zero.
- The experiment did not isolate reasoning quality from output-format/recovery effects.
- Final audit output explicitly printed malformed/invalid counters for Seed 0 and Seed 1. For Seeds 2–4, the three-step paths were consistent with clean runs, but final audit output did not explicitly print malformed-response counters for those seeds.

**Engineering recommendation in report:** Treat constrained output as a format-reliability mechanism worth evaluating; retain strict client-side validation. Do not treat 14.5% as a typical expected saving or a general token-optimization result.

---

## Finding 6 — Infrastructure failures can masquerade as model limitations

**Primary report:** `docs/finding-infrastructure-masking.md`.

### What happened

In Protocol-X, the pre-fix no-memory baseline achieved 3/5 independently verified success, while raw-experience and learned-skill arms each achieved 5/5. Investigation identified a path-resolution defect in `list_files`: absolute discovered file paths were passed to `relative_to()` with a relative workspace path, producing `ValueError`.

The legacy faulty expression was independently reproduced in a test-only diagnostic at `eval/diagnostics/reproduce_list_files_failure.py`. The production fix resolved both paths against an absolute workspace root before computing relative paths. A regression test exists at `tests/test_file_ops.py::test_list_files_relative_path`.

After the production correction, all Protocol-X arms A/C/D achieved 5/5.

### Positive engineering result

- The tool defect was reproduced.
- The production path handling was corrected.
- A regression test was added.
- The pre/post-fix result is consistent with the earlier apparent no-memory disadvantage being caused, at least in part, by infrastructure failure.

### Important limitations

- The pre-fix and post-fix comparisons were sequential, not a randomized paired causal experiment.
- The evidence does not prove that the tool defect was the only cause of earlier failures.
- It does not prove that memory had no effect.
- Protocol-X comparison-arm token usage is unavailable: 30 comparison run rows had NULL usage fields and no associated model-call rows. Six calls belonged to a source acquisition run, but those counts do not belong to the comparison runs and must not be assigned to them.
- The original acquisition task explicitly exposed the Protocol-X rule in its docstring; the study did not prove autonomous discovery of a hidden rule.

### Historical claim correction

An early repository commit used the title “BREAKTHROUGH: Proven procedural transfer. Arm D 100% vs Arm A 60% on arbitrary OOD task.” That early claim was not retained as the final conclusion. Subsequent verification, the infrastructure defect investigation, and final reports narrowed the interpretation. The final defensible report is `docs/finding-infrastructure-masking.md` plus `docs/REPRODUCIBILITY.md`, not the early commit title.

**Defensible conclusion:** Tool correctness and runtime reliability must be established before attributing agent failures to model reasoning or memory.

---

## Finding 7 — Deterministic controller guards contained persistent tool-failure loops

**Primary report:** `docs/finding-7-controller-loop-guard.md`.  
**Protocol:** `docs/GENESIS3_PILOT_PROTOCOL.md`, with Amendment 1 and outcome clarification.  
**Raw records:** `eval/results/genesis3_pilot_results_20261109.json`.

### Design

Three policies × two fault conditions × three matched seeds = 18 runs:

- A — Baseline: V0 system prompt, no loop guard.
- B — Prompt: V0 plus instruction to stop after the same error twice.
- C — Controller: V0 plus deterministic guard after three consecutive failed `list_files` calls.

Fault fixtures:

- Transient: first two `list_files` calls fail with the same legacy `ValueError`; third and subsequent calls work.
- Persistent: every `list_files` call fails with the same `ValueError`.

The amended task explicitly excluded `manifest.txt` from the source listing and required exact sorted forward-slash paths. The manifest was checked independently. The model was instructed to use `SUCCESS:` or `FAILED:` summary prefixes; ambiguous summaries were classified separately.

### Transient-fault results

| Policy | Correct manifests | Failed `list_files` calls | Tokens over 3 runs |
|---|---:|---:|---:|
| A — Baseline | 3/3 | 6 | 6,256 |
| B — Prompt | 3/3 | 6 | 6,703 |
| C — Controller | 3/3 | 6 | 6,270 |

All nine transient runs recovered. Each had two failed list calls followed by a successful third call. The controller guard did not block the third call because the failure counter was reset by success.

### Persistent-fault results

| Policy | Correct manifests | Outcomes | Failed `list_files` calls | Tokens over 3 runs | Mean tokens/run |
|---|---:|---|---:|---:|---:|
| A — Baseline | 0/3 | 3 max_steps_reached | 17 | 12,114 | 4,038.0 |
| B — Prompt | 0/3 | 3 max_steps_reached | 22 | 13,277 | 4,425.7 |
| C — Controller | 0/3 | 3 loop_detected | 9 | 3,203 | 1,067.7 |

Arm B's three persistent traces showed repeated identical `ValueError` observations and continued tool calls rather than an explicit `FAILED:` completion. Seed 0 briefly tried `read_file` actions but returned to the same failing `list_files` operation.

Arm C stopped all three persistent runs after exactly three failed `list_files` calls and did not request another model response after guard activation.

Persistent-fault token use for C was:

- 73.6% lower than A (3,203 vs 12,114 tokens).
- 75.9% lower than B (3,203 vs 13,277 tokens).

### Integrity and volume

- 18/18 planned conditions recorded; no duplicate condition.
- 102 actual model requests.
- 47,823 total tokens.
- All per-call usage complete and reconciled to run totals.
- All starting workspace files preserved after runs.
- All traces accounted for the recorded model steps.
- All 18 effective prompt hashes verified: A/C matched V0; B matched V0 plus the stopping instruction.
- No false-success claims recorded.
- Run order and randomization seed were saved in the plan before execution.

### Pre-registered predictions versus observed results

| Arm / condition | Pre-registered prediction | Observed result | Assessment |
|---|---|---|---|
| A — transient | 3/3 correct manifests | 3/3 | Matched |
| A — persistent | 3/3 max-step outcomes | 3/3 | Matched |
| B — transient | 0/3 if the model obeyed the stop instruction after two errors | 3/3 correct manifests; model made the third call and recovered | Prediction conditional was not realized; the prompt did not force a stop |
| B — persistent | 3/3 explicit gave-up outcomes if the instruction was followed | 0/3 gave-up; 3/3 max-step outcomes | Did not match; repeated identical failures were followed by further tool calls |
| C — transient | 3/3 correct manifests; guard should not fire before the successful third call | 3/3 | Matched |
| C — persistent | 3/3 loop-detected outcomes after the third failed call | 3/3 | Matched |

The unexpected Arm B outcomes are central evidence, not failed runs to discard. In transient conditions the model continued and recovered despite the prompt instruction. In persistent conditions it continued retrying and exhausted the step limit rather than reporting `FAILED:`. The controller guard behaved exactly as predicted in both fault conditions.

### Per-arm model-request totals

The raw result artifact records 102 model requests overall. The run-level step counts and traces are authoritative for per-run request counts. The primary report tables above aggregate failed `list_files` calls and token totals; they should not be confused with total model requests.

### Interpretation and limitations

- The controller guard contained persistent retry loops while preserving recovery for the tested transient pattern.
- It did not repair the underlying persistent tool defect or complete the persistent task; all persistent manifests were incorrect/absent.
- `loop_detected` is deterministic controller-enforced termination, not model self-diagnosis or model honesty.
- This was a three-seed directional pilot, one model, one task, two injected failure patterns, and one threshold. It is not statistically powered and does not establish broad generalization.
- The guard was implemented in the separate experimental runner `eval/diagnostics/genesis3_pilot_runner.py`; it was not merged into the standard controller implementation in `src/nova/controller/loop.py` as part of this finding.

**Defensible conclusion:** For this tested NOVA workload, deterministic controller enforcement contained persistent tool-failure loops more reliably than a prompt-level stopping instruction, without sacrificing recovery from the tested transient failure.

---

## 6. Overall research conclusions

Taken together, the seven findings support several project-level lessons:

1. Memory is not automatically an efficiency gain. Measure creation costs, deployment costs, task success, and paired-seed variation.
2. Prompt evolution can overfit to a diagnosed failure or a task family. Validation tasks and prompt provenance are essential.
3. Retry wording is not an enforceable safety boundary. Models can continue taking the same failing action despite instructions to stop.
4. Structured output constraints can help avoid formatting/recovery tail events, but one outlier should not be represented as a typical efficiency improvement.
5. Infrastructure defects can masquerade as limitations of model reasoning. Tool correctness and regression tests matter.
6. A controller can enforce a hard bound on repeated actions, but stopping a loop is not the same as repairing the tool or diagnosing the cause.
7. Raw artifacts, independent verification, exact prompt hashes, and complete token accounting are core research infrastructure, not optional documentation.

No result establishes that NOVA autonomously discovers hidden procedures, generalizes across arbitrary task families, or self-improves its model weights. Model weights were kept frozen in the prompt-evolution experiments.

---

## 7. Complete repository layout and file locations

The following is the file inventory verified on GitHub `main` at commit `7453e7f` (recursive Git tree returned 144 entries, including directories). It is grouped by purpose.

### 7.1 Root files

- `.env.example` — example environment variables.
- `.gitignore` — ignored local files and environment artifacts.
- `README.md` — short project description, setup, and source map.
- `pyproject.toml` — package metadata, dependencies, and pytest/Ruff configuration.
- `code` — a root-level preliminary Protocol-X transfer note. This is a legacy note, not the canonical final finding.
- `preregistration.md` — currently empty in the repository tree checked.
- `research_protocol.md` — currently empty in the repository tree checked.
- `references.md` — currently empty in the repository tree checked.
- `hidden_tests/test_calc.py` — legacy/root-level hidden test file, separate from task-specific hidden tests under `eval/tasks/`.

### 7.2 `docs/`

- `GENESIS3_PILOT_PROTOCOL.md` — canonical pre-registration for the executed 18-run Genesis 3 pilot.
- `GENESIS3_PILOT_AMENDMENT_1.md` — prospective clarification of task wording and exact manifest/success-claim scoring.
- `GENESIS3_PILOT_OUTCOME_CLARIFICATION.md` — explicit `SUCCESS:` / `FAILED:` / unclassified outcome mapping.
- `REPRODUCIBILITY.md` — recovered exports, provenance limitations, Protocol-X token-data gaps, and interpretation boundaries.
- `finding-infrastructure-masking.md` — Finding 6.
- `finding-7-controller-loop-guard.md` — Finding 7.
- `results.md` — NOVA-Budget memory economics, AuthSystem, and HiddenAuth report.
- `results_genesis.md` — Genesis prompt-evolution and retry experiments report.
- `results_json_schema.md` — Genesis 2 JSON Schema report.
- `threat_model.md` — currently empty in the repository tree checked; not a completed threat-model document.

### 7.3 `src/nova/`

- `__init__.py`
- `cli.py` — command-line entry point.
- `client.py` — HTTPX model client and strict usage validation.
- `config.py` — environment-based configuration.
- `evolve.py` — prompt evolution component.
- `controller/__init__.py`
- `controller/loop.py` — standard agent loop, JSON action parsing, tool dispatch, SQLite run/episode/model-call recording.
- `eval/__init__.py`
- `memory/__init__.py`
- `memory/db.py` — SQLite schema and connection/migration helpers.
- `memory/extract.py` — skill extraction.
- `tools/__init__.py`
- `tools/exec.py` — execution tool.
- `tools/file_ops.py` — safe file operations and corrected `list_files` path handling.
- `tools/registry.py` — tool registry.

### 7.4 `tests/`

- `test_client.py`
- `test_config.py`
- `test_db.py`
- `test_exec.py`
- `test_file_ops.py`

`test_file_ops.py` includes the `test_list_files_relative_path` regression test for the earlier path-resolution defect. A historical 42-test pass was reported on the separate Genesis 2 JSON Schema experimental branch; do not treat that historical figure as a fresh test run of the current `main` HEAD.

### 7.5 `eval/harness/`

- `runner.py` — task preparation, agent execution, independent hidden-test verification, memory provenance, and result assembly.

### 7.6 `eval/diagnostics/`

- `genesis3_pilot_runner.py` — standalone, checkpoint-enabled 18-run Genesis 3 experimental runner.
- `transient_failure.py` — first two calls fail; third and subsequent calls succeed.
- `persistent_failure.py` — repeated legacy `ValueError` fixture.
- `verify_genesis3_fixtures.py` — offline validation of exact fixture behavior and expected filenames.
- `reproduce_list_files_failure.py` — test-only reproduction of the legacy production path-resolution expression.

### 7.7 `eval/tasks/`

Task directories (each generally contains `task.yaml`, starting repository files, and hidden tests):

- `auth_system/` — `task.yaml`, `repo/auth.py`, `hidden_tests/test_auth.py`.
- `hidden_auth/` — `task.yaml`, `repo/vault.py`, `hidden_tests/test_vault.py`.
- `inventory_batch/` — `task.yaml`, `repo/ledger.py`, `hidden_tests/test_ledger.py`.
- `parcel_pipe/` — `task.yaml`, `repo/parcel.py`, `hidden_tests/test_parcel.py`.
- `scan_config/` — `task.yaml`, `repo/client.py`, `repo/config.py`, `hidden_tests/test_client.py`.
- `scan_state/` — `task.yaml`, `repo/counter.py`, `hidden_tests/test_counter.py`.
- `signal_registry/` — `task.yaml`, `repo/registry.py`, `hidden_tests/test_registry.py`.
- `task_001/` — `VALIDITY.md`, `task.yaml`, `repo/calc.py`, `hidden_tests/test_calc.py`.
- `task_002/` — `VALIDITY.md`, `task.yaml`, `repo/sort_items.py`, `hidden_tests/test_sort.py`.

### 7.8 `eval/results/`

#### Memory and transfer

- `auth_system_replication_20261108.json` — earlier 12-record export.
- `auth_system_replication_20261108_complete15.json` — reconstructed detailed 15-run AuthSystem export.
- `hidden_auth_matched_5seeds_20261108.json` — final matched HiddenAuth dataset.
- `protocol_x_signal_registry_20261108.json` — pre-fix Protocol-X comparisons.
- `protocol_x_signal_registry_postfix_20261108.json` — post-fix Protocol-X comparisons.

#### Genesis prompt evolution and retry

- `nova_genesis_v0_corrected_retry_partial_after_seed3_20261108.json`
- `nova_genesis_v0_corrected_retry_seed4_20261108.json`
- `nova_genesis_v0_heldout_20261108.json`
- `nova_genesis_v0_noecho_original_5seeds.json`
- `nova_genesis_v0_seeds_1_4_20261108.json`
- `nova_genesis_v0_state_management_5seeds_20261108.json`
- `nova_genesis_v0_validation_scan_config_5seeds_20261108.json`
- `nova_genesis_v1_candidate_scan_config_and_inventory_5seeds_20261108.json`
- `nova_genesis_v1_generation_20261108.json`
- `nova_genesis_v1_generation_attempt2_20261108.json`
- `nova_genesis_v1_generation_attempt3_20261108.json`

#### Genesis 2 JSON Schema

- `nova_json_schema_control_seed0_20261109.json`
- `nova_json_schema_control_seed1_20261109.json`
- `nova_json_schema_control_seed2_20261109.json`
- `nova_json_schema_control_seed3_20261109.json`
- `nova_json_schema_control_seed4_20261109.json`
- `nova_json_schema_treatment_seed0_20261109.json`
- `nova_json_schema_treatment_seed1_20261109.json`
- `nova_json_schema_treatment_seed2_20261109.json`
- `nova_json_schema_treatment_seed3_20261109.json`
- `nova_json_schema_treatment_seed4_20261109.json`

#### Genesis 3

- `genesis3_pilot_plan_20261109.json` — fixed randomized schedule and environment metadata.
- `genesis3_pilot_results_20261109.json` — all 18 run records, traces, usage, and outcomes.

### 7.9 Directories referenced by README but absent from the verified current tree

The README mentions `eval/analysis/` and `migrations/` as intended structure, but those directories were not present in the recursive file listing checked. Do not assume there is an implemented analysis package or SQL migration directory in the current `main` tree.

---

## 8. Raw data, provenance, and measurement integrity

### 8.1 AuthSystem recovery

The original committed AuthSystem export held 12 records (seeds 1–4). The local SQLite database retained all 15 original final runs and 46 model-call rows. A reconstructed full 15-run export was created and committed as `auth_system_replication_20261108_complete15.json`.

All 15 records had missing `system_prompt_sha256` (null/unavailable); this is documented in `REPRODUCIBILITY.md`. Do not claim prompt-hash provenance for those recovered rows.

### 8.2 HiddenAuth correction

An initial set of runs was invalidated because the hidden-tests directory was empty. Those attempts were excluded; the valid five matched seeds were rerun and saved in `hidden_auth_matched_5seeds_20261108.json`.

### 8.3 Protocol-X token accounting gap

The 30 pre-fix/post-fix comparison run rows lacked prompt/completion/total tokens and had incomplete usage. They had no associated model-call records. Six calls found for a source-acquisition run were not comparison-arm calls and were not reassigned. Therefore, Protocol-X token comparisons are unavailable.

### 8.4 Genesis 3 accounting

Genesis 3 produced 18 complete records with 102 actual requests and 47,823 tokens. Each call's token usage reconciled to the run total. Raw assistant output and tool observations were retained. The run artifact includes `active_run: null` at completion.

### 8.5 Interpretation rule

When an artifact is missing, token data is absent, prompt hash is unavailable, or a claim is only observational, preserve the gap. Do not fill it by inference.

---

## 9. GitHub repository management and history

### 9.1 Repository

- URL: https://github.com/shaiksameer667ss-prog/nova
- Public repository.
- Default branch: `main`.
- Main is the canonical branch for published reports and results.

### 9.2 Verified branches at last GitHub check

| Branch | Head | Purpose/status |
|---|---|---|
| `main` | `7453e7f` | Canonical published project; includes Findings 6 and 7 and Genesis 3 raw data. |
| `experiment/json-schema-actions` | `6ef6cc1` | Preserved Genesis 2 controller/schema experiment branch; includes the experimental controller implementation and additional tests. |
| `experiment/genesis3-failure-attribution` | `0091fb1` | Historical Finding 6 branch, merged through PR #1. |

The experimental branches were retained rather than deleted after the work was merged or reported.

### 9.3 Pull request #1

- PR: https://github.com/shaiksameer667ss-prog/nova/pull/1
- Title: `Document infrastructure masking finding`.
- Head: `experiment/genesis3-failure-attribution`.
- Base: `main`.
- Merged: 9 November 2026 at 04:37:59 UTC.
- Merge commit: `ef3f474`.
- Included Finding 6 and the test-only legacy bug reproducer, followed by a wording/evidence correction.

The PR interface showed zero automated checks at the time of review. A local diagnostic was run successfully. GitHub Actions returned no workflow runs in the repository check made for this handover.

### 9.4 Selected commit history

The following selected commits document major milestones. This is not the complete Git history.

| Commit | Message / milestone |
|---|---|
| `e1f4805` | Capability screen: four tasks, four baseline passes; no measurable skill effect. |
| `2442634` | Early overstrong “breakthrough” claim; superseded by later verification and narrowed conclusions. |
| `917cf60` | Preliminary Protocol-X transfer pilot, 3/5 baseline vs 5/5 skill, with small-sample caveat. |
| `5bb4470` | Earlier NOVA-Budget report snapshot; later strict accounting clarified the economics. |
| `d199776` | NOVA-Budget lifecycle economics and AuthSystem results. |
| `8c5efbc` | Audited HiddenAuth procedural-memory experiment. |
| `fb3b78c` | NOVA Genesis prompt/retry experiments and results. |
| `c761119` | Genesis 2 JSON Schema results report. |
| `ab675e8` | Genesis 2 raw JSON Schema run artifacts. |
| `be48241` | Recovered AuthSystem records and reproducibility audit. |
| `1e34a89` | Initial Finding 6 report and reproducer on experiment branch. |
| `0091fb1` | Clarification to Finding 6 evidence wording; PR branch head. |
| `ef3f474` | Merge of PR #1 into main. |
| `aac9988` | Genesis 3 pilot preregistration. |
| `cc431a6` | Genesis 3 transient/persistent fixtures and offline verification. |
| `e971c57` | Genesis 3 Protocol Amendment 1. |
| `0d53d32` | Genesis 3 runner and randomized schedule. |
| `daf4a03` | Per-call checkpointing added to the Genesis 3 runner. |
| `7453e7f` | Finding 7 and all 18 Genesis 3 raw records published. |

The early commit title `BREAKTHROUGH: Proven procedural transfer...` is part of history, not the final scientific conclusion. Final reports and reproducibility notes supersede that early interpretation.

### 9.5 Git workflow used

The project used a conservative, auditable Git workflow:

1. Research or code work was placed on a purpose-specific branch when appropriate.
2. Files were staged explicitly by path; `git add .` was avoided to prevent accidental inclusion of local drafts.
3. `git diff --cached --check` was run before commits.
4. Diffs and status were reviewed before committing.
5. Experimental branches were pushed to `origin` and merged through a pull request when applicable.
6. Local `main` was synchronized using `git pull --ff-only origin main` after the PR merge.
7. The abandoned `docs/GENESIS3_PROTOCOL.md` was deliberately left untracked and not committed.

### 9.6 Latest local state reported by user

After the final Finding 7 push, the user's PowerShell status was:

```text
## main...origin/main
?? docs/GENESIS3_PROTOCOL.md
```

That means local `main` and `origin/main` were synchronized at `7453e7f`, with only the abandoned protocol draft untracked. It was preserved locally and excluded from GitHub `main`.

---

## 10. Reproduction and setup

The README's basic setup is:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
ollama serve
pytest
```

The local environment used `NOVA_MODEL=qwen3.5:4b`, base URL `http://localhost:11434/v1`, and temperature 0.2. `src/nova/config.py` reads environment variables for model, base URL, API key, workspace, database, maximum steps, and temperature.

The CLI entry point is:

```powershell
python -m nova.cli "<task description>"
```

The CLI explicitly warns that `agent_success` is not independent verification; benchmark use should go through the evaluation harness and hidden-test verifier.

To run unit tests:

```powershell
pytest
```

Historical validation notes:

- 42 tests passed on the separate Genesis 2 JSON Schema experiment branch at the time that branch was evaluated.
- The current `main` tree has five test modules: `test_client.py`, `test_config.py`, `test_db.py`, `test_exec.py`, and `test_file_ops.py`.
- A fresh full `pytest` run on `7453e7f` was not part of the final Genesis 3 publication sequence; run it before claiming the current checkout has a fresh full-suite pass.
- Genesis 3 fixture validation and seven offline mock tests passed during preparation; those were separate from the 102 actual Ollama requests in the 18-run experiment.

---

## 11. Known gaps, unfinished work, and do-not-overclaim list

1. **Small samples:** Most comparisons use five seeds; Genesis 3 uses three. These are pilot/descriptive results, not statistically definitive evaluations.
2. **Limited task generalization:** Several memory tasks are related or disclose the rule in a docstring. They do not prove broad autonomous transfer.
3. **Memory economics:** Skill creation cost and unmeasured failed extraction costs complicate lifecycle break-even.
4. **Prompt evolution:** V1 validation regressed, and candidate-generation cost erased the small deployment-only aggregate reduction.
5. **Retry interventions:** The specific tested interventions did not solve malformed JSON. This does not establish that every retry strategy is ineffective.
6. **`oneOf` raw record:** The compatibility rejection is described in the report; no standalone raw HTTP 400 response file was found in the result inventory.
7. **AuthSystem prompt hashes:** Reconstructed 15-run records do not have the original prompt hash values.
8. **Protocol-X token data:** Comparison-arm token usage is unavailable and cannot be reconstructed from unrelated source-acquisition calls.
9. **Protocol-X causal interpretation:** Before/after comparison was sequential and observational.
10. **Genesis 3 pilot size:** Three matched seeds, one model, one task, and two injected failure patterns are insufficient for broad generalization.
11. **Genesis 3 controller integration:** The loop guard was implemented in the standalone diagnostic runner, not automatically promoted into the standard production controller loop.
12. **No autonomous failure-source learning claim:** Arm C's termination was controller-enforced. The agent did not have to discover the failure source.
13. **CI:** No automated workflow runs were returned in the GitHub Actions check. Do not claim CI validation unless workflows are added and run.
14. **Empty/stale files:** `docs/threat_model.md`, root `preregistration.md`, root `research_protocol.md`, and root `references.md` were empty in the checked tree. `README.md` references `eval/analysis/` and `migrations/`, but those directories were not present in the checked recursive file tree.
15. **Legacy protocol draft:** Local-only `docs/GENESIS3_PROTOCOL.md` is an abandoned earlier design (failure-source attribution) and must not be confused with the canonical executed pilot protocol.

---

## 12. Practical next steps

Priority order:

1. Keep `PROJECT.md` and the seven finding/source documents synchronized whenever new experiments are added.
2. Run `pytest` on current `main` and record the exact test count and commit SHA.
3. Decide whether the Genesis 3 three-failure guard should be integrated into `src/nova/controller/loop.py`. If integrated, treat that as a new engineering change and add regression tests; do not rewrite the historical experimental record.
4. Add a dedicated raw compatibility probe artifact if the `oneOf` behavior is retested on a future Ollama version.
5. Expand memory and recovery experiments only with new preregistered task families and enough seeds to answer the intended question.
6. Fill or remove stale empty placeholder docs and reconcile the README directory map with the actual tree.
7. Consider adding GitHub Actions for pytest, linting, and artifact validation; the repository currently has no workflow runs in the checked status.

---

## 13. Canonical links

- Repository: https://github.com/shaiksameer667ss-prog/nova
- Main branch: https://github.com/shaiksameer667ss-prog/nova/tree/main
- All docs: https://github.com/shaiksameer667ss-prog/nova/tree/main/docs
- All results: https://github.com/shaiksameer667ss-prog/nova/tree/main/eval/results
- Diagnostics: https://github.com/shaiksameer667ss-prog/nova/tree/main/eval/diagnostics
- Finding 6: https://github.com/shaiksameer667ss-prog/nova/blob/main/docs/finding-infrastructure-masking.md
- Finding 7: https://github.com/shaiksameer667ss-prog/nova/blob/main/docs/finding-7-controller-loop-guard.md
- Genesis 3 protocol: https://github.com/shaiksameer667ss-prog/nova/blob/main/docs/GENESIS3_PILOT_PROTOCOL.md
- Genesis 3 plan: https://github.com/shaiksameer667ss-prog/nova/blob/main/eval/results/genesis3_pilot_plan_20261109.json
- Genesis 3 raw results: https://github.com/shaiksameer667ss-prog/nova/blob/main/eval/results/genesis3_pilot_results_20261109.json
- PR #1 (merged): https://github.com/shaiksameer667ss-prog/nova/pull/1

---

## Final project statement

NOVA produced seven documented, bounded research findings across memory economics, prompt evolution, retry behavior, structured output, infrastructure reliability, and controller-enforced failure containment. The most important methodological contribution is not a universal claim that memory or prompting improves agents; it is the accumulated evidence that agent behavior must be evaluated as a model-controller-tool system, with independent verification, preserved traces, exact provenance where available, token reconciliation, explicit limitations, and reproducible artifacts.
