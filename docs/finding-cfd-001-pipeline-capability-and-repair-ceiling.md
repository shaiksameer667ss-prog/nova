CFD-001 Finding: Pipeline Capability and Repair-Quality Ceiling
Date: 2026-11-11
Task: cross_file_dependency_001
Model: qwen3.5:9b-8k
Scope: One benchmark task, seed 0, two repair-producing runs (R1 and V3).
Executive Finding
The typed-probe design fixed the probe input-construction failure that had prevented earlier runs from executing behavioral probes.

V3 results:
- 3 hypothesis responses
- 0 malformed responses
- 0 probe contract rejections
- 3 accepted probe specifications
- 3 sandbox observations
- 3 completed function calls
- 3 prediction matches
- 0 prediction mismatches
- 3 causal reviews
- 1 source write to tokenizer.py
However, the resulting repair is not robustly correct.

The corrected four-case adversarial backslash-parity suite produced:
Candidate    Cases passed
Reference implementation    4/4
Starter implementation    3/4
R1 repair    1/4
V3 typed-probe repair    1/4


R1 and V3 use different source files but exhibit the same failure pattern. Both repairs handle an escaped quote preceded by an odd backslash run but break cases where an even run precedes the closing quote.

V3 did not complete an end-to-end successful agent run. Its budget guard stopped further model requests before the post-write completion gate was reached. Its result reports agent_success=false.

Conclusion: the typed-probe pipeline improvement is demonstrated; general repair correctness is not.
1. Task and Defect
CFD-001 is a cross-file dependency task involving:
- parser.py: parse_record()
- tokenizer.py: split_fields()
The parser imports and calls split_fields().

Required behavior includes:
- Preserving semicolons inside quoted values.
- Handling escaped quotes.
- Trimming whitespace appropriately.
- Handling empty and whitespace-only records.
A tokenizer defect can cause the parser's public function to produce incorrect results even though the parser is the apparent task entry point.
2. Pipeline Changes
The relevant pipeline components include:
- Repository dependency inspection.
- Hypothesis generation.
- Task-aware probe validation.
- Deterministic typed-probe serialization.
- Sandbox execution.
- Causal review.
- Source writing.
- Post-write task-contract completion gate.
Earlier runs using model-authored serialized probe input encountered repeated contract rejections. The experimental notes record five consecutive failures in this input-construction class before the typed-probe path was introduced.

The typed representation moves record construction out of free-form model escaping.

For CFD-001, the model supplies structured fields containing:
- A key.
- A value type: quoted or unquoted.
- A semantic value.
NOVA serializes that representation deterministically and applies the CFD-001-specific grammar validator.

This preserves the distinction between generic probe validation and task-specific input validation. The malformed v2 runtime input remains rejected by the task-aware parsing path. The typed design does not weaken that grammar check.
3. V3 Configuration
Run: cross-file-live-9b-8k-seed0-20261111-typed-probe-v3
- Model: qwen3.5:9b-8k
- Seed: 0
- Planning mode: enabled
- Model context limit: 8192
- Token limit: 50000
- External timeout: 300 seconds
- Reported token usage: 41981
- Usage accounting: complete
Probe Metrics
Metric    V3
Hypothesis responses    3
Malformed responses    0
Probe contract rejections    0
Accepted specifications    3
Sandbox observations    3
Completed function calls    3
Prediction matches    3
Prediction mismatches    0
Probe runner errors    0
Causal reviews    3
Causal review blocked    No
Probe contract blocked    No


All three V3 proposals targeted tokenizer.py::split_fields.

These results support the conclusion that the typed-probe input-construction path worked in V3.
4. Source Write and Completion
V3 changed tokenizer.py; parser.py remained unchanged.

Recorded hashes:
File    Initial hash    Final hash
parser.py    030e8b9b269de4df50a217926c189b61f4c9161e49e57a3737aa2565cf15c4a6    030e8b9b269de4df50a217926c189b61f4c9161e49e57a3737aa2565cf15c4a6
tokenizer.py    da9d632aa4f87b2c0bc27fd98677c3b9a0dcc04e18a04ba447de3e9e3a7d032f    06eb6cca8702ed6b5db6b499d77b00e5d6c7a73afb32f6c11ae6e66374e519af


The run reports:
- agent_success=false
- stop_reason=model_error
- budget_guard_stopped=true
- completion_gate=null
- completion_gate_blocked=false
- postwrite_behavior_check_passed=false
The budget metadata records that another model request could not be made while retaining the configured full 8192-token context reserve.

The run used 41981 reported tokens against a 50000-token limit. It did not exceed the token limit, and the external five-minute timeout did not fire.

The runner metadata records timed_out=false; stderr.txt is empty.

The model_error stop label should not be interpreted alone as proof of a provider/API failure. The accompanying budget-guard fields identify the recorded stopping condition.
5. Completion-Gate Distinction
The controller contains a CFD-001-specific postwrite_task_contract gate.

It creates probes for parser.py::parse_record from _CFD001_ACCEPTANCE_CASES and executes them against the post-write workspace before accepting completion.

That gate was not reached in V3.

Its absence from the result is not a passing gate:
- completion_gate is null.
- postwrite_behavior_check_passed is false.
The public controller acceptance cases are distinct from the benchmark's six hidden tests.

The supplied experiment notes report that both R1 and V3 workspaces passed those six hidden benchmark tests (6/6). That benchmark result must not be conflated with a completed V3 agent run or with adversarial correctness.
6. Adversarial Backslash-Parity Evaluation
The first five-case adversarial harness attempt was invalid. It used eval() on JSON output and its embedded case literals were mangled. Its results were discarded.

The subsequent corrected harness wrote inputs to a JSON file, read them with json.loads(), and compared the returned split_fields() values with explicit expected outputs.

The supplied results for that corrected four-case suite are:
Candidate    Passed    Failed
Reference    4    0
Starter    3    1
R1    1    3
V3    1    3


The four cases exercise:
1. An even run of two backslashes before a closing quote.
2. An even run of four backslashes before a closing quote.
3. An odd run where a backslash escapes an embedded quote, with semicolons remaining inside the quoted value.
4. Multiple fields, each containing an escaped backslash before the closing quote.
The starter passes the even-run cases but fails the odd-run escaped-quote case.

R1 and V3 fix that odd-run case but fail the even-run cases.

The supplied six hidden tests do not detect the even-backslash regression exposed by this adversarial suite.
7. Repair Implementation and Root Cause
The V3 tokenizer contains this logic:
if char == '"':
    if index > 0 and source[index - 1] == '\\':
        pass
    else:
        in_quotes = not in_quotes
The condition examines only the immediately preceding character. It does not count the consecutive run of backslashes before the quote.

Under conventional backslash escaping:
- An odd-length run means the quote is escaped.
- An even-length run means the quote is not escaped and can close the quoted value.
The previous-character check treats both cases as escaped whenever the prior character is a backslash.

In the even-run cases, the quote therefore fails to close the value, and later parsing can end in an unterminated-quote error or incorrect field segmentation.

The supplied adversarial results show R1 and V3 have the same functional failure pattern on all four cases, despite having different source files.

V3 source hash:
06eb6cca8702ed6b5db6b499d77b00e5d6c7a73afb32f6c11ae6e66374e519af

Supplied R1 hash prefix:
607a655d
8. What the Experiments Demonstrate
Supported Findings
1. Typed probe construction works on CFD-001 in V3. Three typed proposals were accepted, with zero contract rejections.
2. Sandbox execution works in this V3 run. All three accepted probes completed and matched their predictions.
3. The model repeatedly localized proposals to the tokenizer dependency. All three V3 proposals targeted tokenizer.py::split_fields.
4. The pipeline can produce a benchmark-passing workspace. The supplied experiment notes report 6/6 hidden benchmark tests for both R1 and V3 workspaces.
5. The benchmark pass does not establish robust correctness. Both repairs fail three of the four supplied adversarial cases, while the starter passes three.
6. V3 did not establish end-to-end autonomous completion. The token-budget guard stopped the run before the completion gate, and agent_success is false.
Claims Not Established
These experiments do not establish that:
- The model can reliably produce generally correct repairs for escaped-quote handling.
- The pipeline has broad generality across tasks, repositories, models, or seeds.
- The seven-case public post-write gate passed in V3.
- V3 completed a successful autonomous run.
- The same performance will hold across repeated independent samples or different model versions.
This is a narrow empirical result: one task, one model family/version, one seed, and two repair-producing runs.

The two runs provide repeatability evidence for this specific behavior, not a broad statistical guarantee.
9. Evidence Preservation
The original experiment directories were left untouched.

Copies were placed under:

C:\Users\Shahid\nova-eval-lab\successful-runs

Preserved directories:
- cross-file-live-9b-8k-seed0-20261111-probe-guard-v1
- cross-file-live-9b-8k-seed0-20261111-typed-probe-v3
Standalone tokenizer copies:
- r1-tokenizer.py
- v3-tokenizer.py
A subsequent SHA-256 verification checked every file path and hash in both copied run directories against its source directory:
- R1: 10 source files, 10 snapshot files; all paths and hashes matched.
- V3: 13 source files, 13 snapshot files; all paths and hashes matched.
- Standalone R1 and V3 tokenizer copies: both matched their preserved workspace copies.
10. Recommendations
1. Retain the typed-probe design. The V3 metrics directly show that it eliminated the observed probe input-construction rejection in this run without loosening the task-specific grammar check.
2. Strengthen the CFD-001 acceptance contract. Add adversarial cases that distinguish odd and even consecutive backslash runs before quotes. The completion gate should reject a repair that regresses on even-run cases.
3. Test the reference, starter, and candidate implementations side by side. Keep explicit expected outputs for each adversarial case so the test suite establishes both the intended semantics and the baseline behavior.
4. Do not treat hidden benchmark success as sufficient evidence of correctness. Report benchmark results and adversarial results separately.
5. Do not launch V4 yet. A larger token budget or smaller context reserve could test whether the pipeline reaches agent_success=true, but that would not address the demonstrated repair-quality regression. First strengthen the acceptance suite and verify that it rejects the current R1/V3 algorithm.
6. Do not silently patch the preserved experimental workspaces. Any future implementation change should be a separately identified candidate with its own tests and provenance.
Final Conclusion
The typed-probe change solved a concrete pipeline failure: NOVA could construct, validate, and execute behavioral probes that earlier runs failed to get past.

V3 provides direct evidence of that improvement.

But two separate repair attempts converged on the same flawed previous-character escape check, and both failed the same three adversarial backslash-parity cases that the starter passed.

The benchmark's hidden tests admitted those regressions.

The accurate finding is therefore: pipeline capability improved; repair quality remains the limiting factor; and CFD-001's acceptance tests need stronger adversarial coverage.

---

## Addendum (2026-11-12): CFD-001 acceptance contract hardened

**Repository file changed:** `src/nova/controller/loop.py` — `_CFD001_ACCEPTANCE_CASES` tuple only. No gate logic, no validators, no reviewer policy, no budget guard, and no `loop.py` control flow were modified. The completion gate is unchanged; only the case data it iterates was extended.

**Patch provenance**

| Field | Value |
|---|---|
| Pre-patch SHA-256 | `95677B42684961697573AFFD1A7505D75400D1E5BDFB3B4E59DF51526D603109` |
| Post-patch SHA-256 | `3854B8F59D461627F926342FECA8A108B80EC9D5E28AD6BE02583D46F3A14835` |
| Pre-patch lines | 1587 |
| Post-patch lines | 1611 |
| Lines added | 24 |
| Backup | `src/nova/controller/loop.py.bak.20261112-052058` |
| Backup SHA-256 | matched pre-patch hash |
| Newline style | LF, preserved |

**New cases added to `_CFD001_ACCEPTANCE_CASES`** (in insertion order):

1. `even_backslashes_before_closing_quote_2`
2. `even_backslashes_before_closing_quote_4`
3. `odd_backslashes_before_embedded_quote`
4. `multiple_fields_with_even_backslashes`

**Contract verification (real parser, three tokenizer variants, no Docker, no model)**

| Case | Reference (`tokenizer.py.manual-fixed`) | Starter (`source.split(';')`) | Buggy (R1/V3-style previous-character check) |
|---|---|---|---|
| `even_backslashes_before_closing_quote_2` | PASS | PASS | **FAIL** |
| `even_backslashes_before_closing_quote_4` | PASS | PASS | **FAIL** |
| `odd_backslashes_before_embedded_quote` | PASS | FAIL | PASS |
| `multiple_fields_with_even_backslashes` | PASS | PASS | **FAIL** |

Failure modes reproduced exactly as predicted: the buggy variant raises `ValueError: Unterminated quoted value` on the two even-run single-field cases, and `ValueError: Invalid quoted value for 'p'` on the multiple-even case. The starter fails only the odd-embedded case. The reference passes all four.

These results match the earlier corrected adversarial harness (reference 4/4, starter 3/4, R1 1/4, V3 1/4). The benchmark acceptance contract now reproduces that harness inside the actual post-write gate path.

**Consequence for the finding**

An R1/V3-style repair can no longer satisfy `postwrite_behavior_check_passed is True` on CFD-001 through the acceptance tuple alone. Passing the completion gate now requires handling both odd and even backslash runs, which is the algorithmic behavior both prior repair-producing runs got wrong.

**Regression evidence**

- `tests/test_causal_review_controller.py`: 12 passed in 3.67s.
- Full suite (`& .venv\Scripts\python.exe -m pytest -q`): **326 passed in 31.21s**.
- Test count is unchanged from the pre-patch baseline; the fixture `fixed_tokenizer` at `tests/test_causal_review_controller.py` (lines 862–888) uses a `backslashes % 2 == 1` parity check and passes all 11 acceptance cases without modification.

**Scope caveat**

The benchmark's six hidden tests remain unchanged and still do not exercise even-backslash runs. The strengthened coverage lives in the controller acceptance cases, which is where the post-write gate evaluates repairs. Any future claim that a live model run has produced a correct repair on CFD-001 must now show both the benchmark result and the extended acceptance-gate result separately.

**No V4 run has been performed.** Per the parent finding document, no further live run is scheduled until a stronger model is available or the benchmark decision changes.

---
## V4 Re-evaluation: Correct Repair Candidate Blocked by Causal Review

**Experiment:** cross-file-live-9b-8k-seed0-20261112-055257-strengthened-gate-v4-cap1200
**Date:** 2026-11-12
**Model:** qwen3.5:9b-8k
**Completion cap:** 1200 tokens
**Overall agent result:** agent_success=false
**Stop reason:** causal_review_blocked

### 1. V4 Execution Integrity

The V4 launch completed normally:

- External timeout: not reached
- Worker exit code: 0
- Result file: present and parseable
- Configuration integrity: passed
- Experiment validity according to the launch protocol: true
- Reported token usage: 39,326 of 70,000
- Budget guard stopped: false
- Behavioral probes attempted: 3
- Behavioral probes completed: 3
- Completion gate: not reached
- Final workspace: unchanged from starter files

The launch was valid as an experiment execution. This does not mean the agent completed the task successfully.

### 2. Correct Repair Candidate Recovered from the Trace

The V4 episode database records the proposed tokenizer.py content at step 4. The proposal uses a scanning index and consumes a backslash together with the following character:

    if char == '\\' and i + 1 < len(source):
        i += 2
    elif char == '"':
        in_quotes = not in_quotes
        i += 1

The complete proposed file was 824 UTF-8 bytes and 29 lines. Its final line was `return fields`; it was not truncated.

An independent local `ast.parse()` check reported: COMPILES OK (syntactically valid Python).

### 3. Offline Acceptance Results

The exact step-4 proposed tokenizer was extracted from the episode database and evaluated against `_CFD001_ACCEPTANCE_CASES`, using the task's real parser.py with the proposed tokenizer imported in an isolated temporary directory.

| Acceptance case | Result |
|---|---|
| plain_fields | PASS |
| semicolon_inside_quoted_value | PASS |
| escaped_quote_and_embedded_semicolon | PASS |
| whitespace_rules | PASS |
| trim_unquoted_values | PASS |
| empty_record | PASS |
| whitespace_only_record | PASS |
| even_backslashes_before_closing_quote_2 | PASS |
| even_backslashes_before_closing_quote_4 | PASS |
| odd_backslashes_before_embedded_quote | PASS |
| multiple_fields_with_even_backslashes | PASS |

**Total: 11 passed, 0 failed.**

This is materially different from the R1 and V3 repair results, which passed only 1/4 of the separate adversarial backslash-parity tests reported in the earlier experiment notes.

**Important scope qualification:** This proves the candidate passes the 11 cases offline. It does **not** prove that the live syntax-validation path or the live post-write completion gate were exercised against this candidate — the causal reviewer blocked the write before dispatch, so neither gate was reached.

### 4. What Actually Blocked V4

The episode trace records:

- Causal review decision: REVISE
- Repair target: tokenizer.py
- Execution status for subsequent write attempts: blocked_by_causal_review
- Final causal review error: Maximum causal review count reached.

Across the repeated reviews, the reviewer continued to describe the *original* tokenizer defect: quote state was toggled without handling backslash escapes. That diagnosis described the starter implementation. It did not accurately evaluate the proposed replacement.

The reviewer's guidance also recommended consuming a backslash and the next character without toggling quote state. That guidance did not explicitly reason about odd/even backslash parity and risks reproducing the R1/V3 failure pattern if followed. The model, in this instance, produced the correct parity-aware algorithm anyway.

The model repeatedly proposed its candidate after receiving substantially the same review feedback. The evidence does not establish that these repeated proposals represented failure to learn; the reviewer did not supply a materially different evaluation of the proposed change.

### 5. Corrected Failure Decomposition

| Layer | V4 evidence |
|---|---|
| Defect localization | Demonstrated |
| Typed behavioral probes | 3 completed |
| Probe predictions | 3 completed; typed probes matched |
| Reviewer target redirection | Demonstrated (parser.py to tokenizer.py at step 2 to 3) |
| Repair candidate generation | Demonstrated |
| Candidate syntax | Independently verified (offline ast.parse) |
| Candidate acceptance cases | 11/11 passed offline |
| Causal review of proposed change | Failed: repeatedly re-diagnosed the original |
| Write dispatch | Blocked by causal review |
| Live syntax validation on this candidate | Not exercised (blocked before dispatch) |
| Live post-write completion gate | Not reached |
| End-to-end agent success | Not demonstrated |

**Primary observed blocker:** causal review evaluated the original defect instead of evaluating the proposed repair.

### 6. Revised Engineering Finding

The earlier claim that V4 failed because the model could not produce a correct repair is withdrawn.

V4 recovered a syntactically valid candidate that passed all 11 current acceptance cases offline. The controller did not dispatch that candidate because causal review repeatedly returned REVISE based on a diagnosis of the original implementation.

The next engineering target is therefore **reviewer fix-evaluation**, not model repair capability.

The reviewer should receive the proposed change, preferably as an old-versus-new diff, and answer a narrow question: does this proposed change address the identified defect without introducing a regression?

The reviewer should verify the candidate rather than prescribe an implementation algorithm. In particular, it should not recommend the previous-character or unconditional pair-skipping behavior without reasoning about backslash parity.

### 7. Next Controlled Change

**Do not launch V5 yet.**

The next change should be limited to reviewer fix-evaluation:

1. Include the proposed diff or proposed new content in the review input.
2. Ask the reviewer to assess the proposed change against the identified root cause and relevant evidence.
3. Avoid prescribing a specific implementation algorithm.
4. Add a regression test using the actual V4 step-4 candidate. A correct proposal that differs from the original implementation must not be rejected merely because the original defect description remains true of the old file.
5. Test the reviewer behavior with both a correct candidate and a deliberately incorrect candidate.

Do not change the token cap, behavioral probe contract, completion-gate cases, or benchmark task as part of this isolated reviewer experiment.

### 8. Final V4 Conclusion

V4 did not achieve end-to-end autonomous success, but it produced a repair candidate that passed all 11 current acceptance cases in an independent offline evaluation.

The candidate was blocked before dispatch by repeated causal-review rejections that did not adequately evaluate the proposed change.

**The revised finding is:** NOVA demonstrated the ability to produce a candidate that passes the current CFD-001 acceptance contract. The remaining observed blocker is causal-review evaluation of proposed repairs, not demonstrated inability of the model to write this particular repair. The live completion gate remains untested on that candidate.


---
## Reviewer Fix: Proposed-Diff Evaluation (2026-11-12)

Implements the isolated reviewer change identified as the sole remaining blocker in V4.

### Source change

File: `src/nova/controller/causal_review.py`

Pre-patch SHA-256: `9261497941DE6D8CF213DD6E2E94E7BF6798D41DE7F00AD06B33E8C8BC737914`
Post-patch SHA-256: `A883418E674B218E202711025BCFE559832CC46338CBAC06E219ECC1ED505C93`
Lines: 665 to 697 (+32)
Backup: `src/nova/controller/causal_review.py.bak.20261112-062552`

Two edits, both additive:

1. `build_prewrite_review_messages` now constructs `context["proposed_diff"]` with `path`, `before_write` (from `observed_files[path]`), `after_write` (the proposed content), `change_kind` (one of `new_file` / `no_op` / `modification`), and an `evaluate_rule` instructing the reviewer to evaluate the delta.

2. `CAUSAL_REVIEW_SYSTEM_PROMPT` gains a `Primary evaluation (perform this before any other reasoning):` block above `Reasoning requirements:`. The block states that `successful_file_observations` for the proposed path reflect the pre-write state, and directs the reviewer to evaluate `after_write` against the diagnosed defect rather than describing the pre-write state again.

No behavioral gate, completion gate, token cap, or prompt-approval rule was modified. `_IMPLEMENTATION_RECIPE_PATTERNS` was left unchanged.

### Regression tests

File: `tests/test_causal_review.py`

Pre-append SHA-256: `E1B921159E5E0D685CB8D4DB86E4FF834649D379AA8F7DA55F1EE967709C0ECB`
Post-fix SHA-256: `869F0FD654E4EE73B0F335E56FF5AE67FD806EE31F5B4D690F405E2CC4643F0F`
Lines: 383 to 451 (+68; +66 for tests, +2 for a Ruff import-order fix)

Two tests added:

- `test_build_review_includes_proposed_diff` — asserts the review context contains `proposed_diff` with correct `before_write` / `after_write` / `change_kind` / `evaluate_rule`, and that the prompt contains a `Primary evaluation` block positioned before `Reasoning requirements:`.
- `test_build_review_proposed_diff_change_kinds` — asserts `change_kind` correctly distinguishes `new_file`, `no_op`, and `modification`.

Ruff on the two edited files: `All checks passed!`

### Verification status

- Causal review suites: 32 passed in 2.61 s.
- Full suite: 328 passed in 11.40 s.
- No regressions in any other module.

### What is verified and what is not

**Verified offline:** the reviewer is now supplied a structurally labeled `before_write` / `after_write` pair, and the system prompt directs the reviewer to evaluate the delta rather than the pre-write file. Both properties are asserted by unit test.

**Not verified:** whether the live model, receiving this new context, will now APPROVE the V4 step-4 candidate. That requires a live run (V5) with the same model, seed, cap, and task as V4. The fix is a necessary structural change; it is not a guarantee that the model will follow the instruction.

**Deliberately not changed:** token cap (1200), behavioral probe contract, completion gate acceptance cases, benchmark task package, `loop.py`, `worker.py`. No consecutive-write-rejection counter was added; V4's repeated identical writes were a consequence of the reviewer giving identical feedback, not of model stubbornness, and stopping on that signal would not improve outcomes.

### Next step

A live confirmation run (V5) with the fixed reviewer, same configuration as V4, would establish whether the pipeline now reaches `postwrite_behavior_check_passed: true` on the V4 candidate. That run is not part of this addendum.


---
## V5 Result: Reviewer Fix Confirmed; Model Instability and Reviewer Limit Exposed

**Experiment:** cross-file-live-9b-8k-seed0-20261112-063424-reviewer-diff-v5
**Date:** 2026-11-12
**Model:** qwen3.5:9b-8k
**Change under test:** reviewer receives `proposed_diff`; `CAUSAL_REVIEW_SYSTEM_PROMPT` leads with `Primary evaluation`
**Pre-registration:** `predictions.md` SHA-256 `3C9DAE02F0A769849CD16EB1E0018124701410F647A3ADE647D44D7B6A92A37D`, recorded in `runner.json` before launch
**Overall agent result:** `agent_success=false`
**Stop reason:** `causal_review_blocked`
**Experiment validity:** true (clean exit, `return_code=0`, config matches, capture complete)

### 1. What V5 confirmed

The reviewer fix worked structurally. The trace shows a different trajectory than V4:

- **Step 2:** model proposed `write_file parser.py` → reviewer **REVISE**, correct (parser is the wrong target)
- **Step 3:** model read `tokenizer.py` (correct pivot)
- **Step 4:** model proposed `write_file tokenizer.py` → reviewer **APPROVE**

V4 (pre-fix) blocked a *correct* proposal three times. V5 (post-fix) approved a proposal on first attempt. The change in reviewer behavior is real and attributable to the `proposed_diff` context and `Primary evaluation` block.

### 2. What V5 exposed

**Model repair instability at cap1200.** V5's step-4 tokenizer.py used the previous-character check:

    if index > 0 and source[index - 1] == '\\':
        continue

This is the R1/V3 algorithm. The exact 702-byte, 21-line content was extracted from the episode database and evaluated offline against `_CFD001_ACCEPTANCE_CASES`:

| Case | Result |
|---|---|
| plain_fields | PASS |
| semicolon_inside_quoted_value | PASS |
| escaped_quote_and_embedded_semicolon | PASS |
| whitespace_rules | PASS |
| trim_unquoted_values | PASS |
| empty_record | PASS |
| whitespace_only_record | PASS |
| even_backslashes_before_closing_quote_2 | **FAIL** (Unterminated quoted value) |
| even_backslashes_before_closing_quote_4 | **FAIL** (Unterminated quoted value) |
| odd_backslashes_before_embedded_quote | PASS |
| multiple_fields_with_even_backslashes | **FAIL** (Invalid quoted value for 'p') |

**V5 step-4 candidate: 8/11 passed, 3 failed.**

Compare to V4 (same model, same seed, same task, same cap): 11/11 passed. The model produced the correct parity-aware algorithm in V4 and the wrong previous-character algorithm in V5. Same seed does not mean same output. Ollama at temperature 0.2 is not fully deterministic.

**Reviewer cannot distinguish correct from incorrect algorithms.** The reviewer approved V5's wrong algorithm. Its own `guidance` described the previous-character check as the correct fix: *"The proposed modification correctly addresses the root cause by inserting a check at line 8-9 to verify if the preceding character is a backslash."* That is not parity-aware. The reviewer's understanding of what constitutes a correct repair is wrong for this defect.

### 3. Why the write was nonetheless blocked

The reviewer's `guidance` field prescribed a specific algorithm, which violates `_IMPLEMENTATION_RECIPE_PATTERNS`. The review-response parser rejected the entire review:

    causal_review_error: invalid_causal_review: guidance must be diagnostic-only and must not prescribe an implementation.

The write was blocked because the *review was invalid*, not because the *decision was REVISE*. This is an accidental safety path: the prescriptive-guidance validator caught a wrong repair for a style reason, not a correctness reason. If the reviewer had returned APPROVE with diagnostic-only guidance describing the wrong algorithm, the write would have dispatched.

### 4. The safety architecture, honestly decomposed

| Layer | V5 outcome | Reliability |
|---|---|---|
| Reviewer target redirect | Caught wrong target at step 2 | Robust (structural) |
| Reviewer fix-evaluation | Approved the wrong algorithm | **Failed** (algorithmic understanding) |
| Prescriptive-guidance validator | Caught the write accidentally | Fragile (fires only on style violation) |
| Post-write acceptance gate | Would have caught 3 failures | **Robust (the actual safety boundary)** |

The only reliable safety layer is the post-write acceptance gate. The prescriptive-guidance validator is not a correctness check.

### 5. Arc conclusion

The arc's original question was whether NOVA can autonomously perform cross-file repair. The answer, after V1 through V5:

- Pipeline is structurally complete: localization, typed probe, reviewer target redirect, reviewer diff-evaluation, prescriptive-guidance check, syntax check, acceptance gate. All seven gates are implemented and unit-tested.
- Reviewer fix works at the structural level: it now evaluates the diff (proven by V4-to-V5 behavior change).
- Model repair quality is unstable at cap1200 on this task: V4 correct, V5 wrong, same seed.
- Reviewer cannot judge algorithmic correctness on this task: it approved both a correct and an incorrect proposal in the same config.
- Post-write acceptance gate is the robust safety boundary.

**End-to-end autonomous repair on CFD-001 was not demonstrated.** The pipeline came within one layer of success in V4; V5 shows the reviewer layer is now passable but the model layer is unstable.

### 6. What would change this outcome

Three things could change it, all of which belong to subsequent arcs, not this one:

1. A stronger model whose repair quality is not seed-labile.
2. A reviewer component whose algorithmic judgments are independently measured and grounded in the required behavior, not just structural evaluation of the diff.
3. A benchmark with more tasks across more defect families, so single-seed variance is not the dominant signal.

None of those are pipeline fixes. They are research directions.

### 7. Prediction comparison

`predictions.md` was pre-registered with the file hash recorded in `runner.json` before launch.

| Prediction | Recorded | Observed |
|---|---|---|
| Reviewer returns APPROVE on first write attempt | 50% | **Yes at step 4** (parser step correctly REVISEd) |
| If APPROVE, write dispatches cleanly | 90% | **No** — invalidated by guidance-style check |
| If dispatched, post-write acceptance passes 11/11 | 70% | **Would have failed** — 8/11 offline |
| `agent_success: true` end-to-end | 30% | **No** |

The first prediction matched; the second failed for a reason not anticipated (guidance-style check, not reviewer decision); the third was exceeded in the wrong direction (the model itself was the failure, not the gate). Honest scoring: the pre-registration held up on the coarse question ("will it succeed") and missed on the specific failure mode.

### 8. Arc status

**Closed.** No V6 is planned. The remaining questions (model stability, reviewer algorithmic understanding, benchmark breadth) each belong to a separate arc.


---
## Pre-Gate Iteration: Implementation Note (2026-11-12)

Implements the acceptance-feedback loop identified as the next hypothesis after V5 (see "V5 Result" section). This is not a pipeline gate. It is a reasoning-loop change: the model receives concrete failing-case feedback between attempts.

### Source changes

File: `src/nova/controller/loop.py`

Pre-implementation SHA-256: `3854B8F59D461627F926342FECA8A108B80EC9D5E28AD6BE02583D46F3A14835`
Post-implementation SHA-256: `28813C8B3FF8D3E0CA1491D532214FF55198005A86179ADAD46927DB34336E18`
Lines: 1611 to 1772 (+161)
Backups: `.bak.20261112-*` files alongside `loop.py`

Changes:

1. `MAX_PRE_GATE_ITERATIONS = 3` constant.
2. `_cfd001_evaluate_candidate(tokenizer_source, parser_source)` — runs the 11 CFD-001 acceptance cases against a proposed tokenizer in an isolated tempdir with the real task parser. No Docker, no sandbox, no model call. Returns structured failures.
3. `_format_pre_gate_feedback(result)` — builds a user message listing each failing case with Input / Expected / Actual. No algorithmic prescription.
4. Pre-gate block inserted between `target_key` computation and the causal-review gate, scoped to `benchmark_task_id == "cross_file_dependency_001"` AND `target_key == "tokenizer.py"` AND `"parser.py" in observed_files`.
5. `consecutive_pre_gate_failures` counter and `pre_gate_blocked` flag. Reset on pass. Break on `>= MAX_PRE_GATE_ITERATIONS`.
6. `stop_reason` chain extended: `pre_gate_blocked` fires before `causal_review_blocked`.
7. `pre_gate_blocked` added to run result dict.

The reviewer, causal-review gate, behavioral-probe sandbox, syntax validation, and post-write completion gate are all unchanged. Only the write-to-tokenizer path is affected, and only for CFD-001.

### Test changes

New file: `tests/test_cfd001_pre_gate.py` (7 tests). Existing file `tests/test_causal_review_controller.py` has `PARSER_SOURCE` fixture replaced with the real task parser, plus a `_bypass_pre_gate` autouse fixture that stubs the evaluator to pass so downstream tests continue to measure what they intended to measure.

### Test evidence

- `tests/test_cfd001_pre_gate.py`: **7 passed**
- Full suite: **335 passed in 11.33 s**
- Ruff: `All checks passed!`

The pre-gate evaluator distinguishes correct from incorrect tokenizer implementations using the real parser and the 11 acceptance cases:

| Input candidate | Result |
|---|---|
| V4 step-4 content (parity-aware) | 11/11 pass |
| V5 step-4 content (previous-character check) | 8/11 pass; fails all three even-backslash cases |
| Syntactically broken content | 0/11 pass; import_error |

`test_pre_gate_fail_then_pass_feeds_feedback_and_proceeds` confirms the fail-feedback-retry-pass path end-to-end, including counter reset. `test_pre_gate_blocks_after_max_iterations` confirms the block-after-3 path with `stop_reason = "pre_gate_blocked"`.

### What this is and is not

**Is:** the standard coding-agent loop — write, run tests, read failures, fix — implemented for one specific task under one specific benchmark id.

**Is not:** a pipeline gate, a reviewer change, a cap change. It affects no path other than `write_file tokenizer.py` under `benchmark_task_id == "cross_file_dependency_001"`.

### Status: implemented and unit-tested; not yet live-measured

Baseline: 1/5 full-pass at cap1200 (see `nova-eval-lab/base-rate-9b-cfd001-20261112/`). The pre-gate is the next experiment: does feedback-driven iteration raise the rate above baseline?

Pre-registered predictions for the iteration measurement are in `cross-file-iteration-9b-cfd001-20261112/predictions.md`, written before any live run.

### Pre-measurement sentinel hashes

For the launch script to anchor against (recheck before launch — hash drift aborts):

| File | SHA-256 |
|---|---|
| `src/nova/controller/loop.py` | `28813C8B3FF8D3E0CA1491D532214FF55198005A86179ADAD46927DB34336E18` |
| `tests/test_cfd001_pre_gate.py` | `99BB701B0C4920119883E2C37DC433E7064848399E05D615CAE3F1245FB2B868` |
| `tests/test_causal_review_controller.py` | `3D66BCF3599DC0F8F988F24F3AD5E4B9CDF1535C92889541E63F31417D839D4E` |


---
## Iteration Result: Feedback Does Not Rescue the Model (2026-11-12)

**Experiment:** cross-file-iteration-9b-cfd001-20261112
**Pre-registration:** `predictions.md` SHA-256 `923E77EBA44C841ADD5D864792858FD4266BB6AEA28260747F357E2AF14F30A0`, recorded before launch
**Baseline:** 1/5 full-pass at cap1200 (`base-rate-9b-cfd001-20261112`)
**Change under test:** pre-gate acceptance-feedback iteration (MAX_PRE_GATE_ITERATIONS=3)
**Result:** **0/5 full-pass.** Iteration does not rescue the model.

### Per-seed progression

| Seed | Attempt 1 | Attempt 2 | Attempt 3 | Effect of feedback |
|---|---|---|---|---|
| 0 | 9/11 | 8/11 | 8/11 | **Got worse** |
| 1 | 8/11 | 8/11 | 8/11 | Stuck |
| 2 | (never reached pre-gate; reviewer blocked) | — | — | — |
| 3 | 9/11 | 8/11 | 8/11 | **Got worse** |
| 4 | 8/11 | 8/11 | 8/11 | Stuck |

Total pre-gate consultations across the 5 seeds: 14. Improvements attributable to feedback: **0**. Regressions (a seed starting higher and ending lower): **2**.

### What the model received and could not use

For every blocked attempt, the model received a structured user message listing:

- The exact failing case name (e.g. `even_backslashes_before_closing_quote_2`)
- The exact input string
- The exact expected output
- The exact actual output or exception

This is the highest-information failure feedback a coding agent can receive. The model responded with worse or equal code every time.

### What this closes

The pre-gate fix is correctly implemented and correctly distinguishes correct from incorrect candidates (7 unit tests; live evidence from seeds 0 and 3 reaching 9/11 on attempt 1 before pre-gate blocked dispatch). The pipeline is not the bottleneck.

The model is the bottleneck. qwen3.5:9b-8k at cap 1200 cannot produce a correct parity-aware tokenizer on CFD-001 with or without failure feedback. It produced 1/5 correct blind, and 0/5 correct with feedback.

### Pre-registered prediction check

`predictions.md` recorded: `1/5 → no change from baseline. Model is the ceiling on this task at cap1200. Different model, different task, or stop.` Observed 0/5, which is at or below baseline. Interpretation holds.

The recorded prediction for `3+/5 → iteration works` was 40%. It did not fire.

### Arc status

**The cross-file repair arc is closed.** The pipeline catches wrong repairs reliably. It cannot cause correct repairs with this model at this cap on this task. Five prior runs plus the two measurement rounds establish this. No V6, no cap tuning, no further reviewer or prompt iteration on this task.

The remaining open questions (stronger model, different task family, reviewer algorithmic grounding) each belong to a separate arc.


---
## Iteration Mechanism: Algorithm Swap Without Parity (2026-11-12)

Refines the previous section ("Iteration Result"). The earlier entry stated the outcome. This entry states the mechanism, recovered from per-attempt failure-set deltas in the four attempting seeds.

### Per-seed failure progression

| Seed | Attempt 1 | Attempt 2 | Attempt 3 |
|---|---|---|---|
| 0 | 9/11: fails `escaped_quote_and_embedded_semicolon`, `odd_backslashes_before_embedded_quote` | 8/11: **fixed both** above; **broke** `even_backslashes_before_closing_quote_2`, `even_backslashes_before_closing_quote_4`, `multiple_fields_with_even_backslashes` | 8/11: identical to attempt 2 |
| 1 | 8/11: fails three even-backslash cases | 8/11: same set | 8/11: same set |
| 2 | (no tokenizer.py candidate; causal review blocked) | — | — |
| 3 | 9/11: fails `escaped_quote_and_embedded_semicolon`, `odd_backslashes_before_embedded_quote` | 8/11: **fixed both** above; **broke** three even-backslash cases | 8/11: identical to attempt 2 |
| 4 | 8/11: fails three even-backslash cases | 8/11: same set | 8/11: same set |

### The mechanism

The model's reachable escape-handling algorithms on this problem appear to be exactly two:

1. **Skip-single-backslash** (`i += 1` on `\`). Passes all even-backslash cases; fails both odd-backslash cases. Observed as attempt 1 of seeds 0 and 3.
2. **Previous-character check** (`if source[i-1] == "\\": skip`). Passes odd-backslash cases; fails all three even-backslash cases. Observed as attempt 2–3 of seeds 0 and 3, and all attempts of seeds 1 and 4. This is the R1/V3 algorithm from the earlier arc.

The third algorithm — **parity-aware** (`i += 2` on backslash, or an escaped-state flag) — is the one that passes all 11 cases. It was produced spontaneously by V4 in the baseline run (1/5 rate) but was not produced by any seed under feedback-driven iteration.

### What iteration actually did

Feedback caused exactly one algorithm swap:

- Seeds 0/3: skip-single-backslash → previous-character check (fixing the reported failures, introducing new ones)
- Seeds 1/4: no swap (previous-character check throughout)

Feedback did **not** cause a swap to the parity-aware algorithm. The model appears to treat the problem as a binary choice between the two visible alternatives. When told "you fail the odd cases," it switches to the other algorithm. When told "you fail the even cases," it does not switch back to a third option — it produces byte-identical output to the previous attempt.

**This is a representation limit, not an effort limit.** The model can use concrete failure specifications to change behavior. It cannot use them to reach an algorithm outside its current reachable set.

### Correcting the earlier framing

The previous section stated "iteration does not rescue the model." That is true but imprecise. The more accurate statement is:

> Feedback-driven iteration caused exactly one algorithm swap in the model's escape-handling approach. That swap traded one failure mode for another (odd-backslash failures became even-backslash failures) rather than reaching the parity-aware solution. When given feedback about the new failure mode, the model did not switch back or reach a third algorithm — it produced identical output to its previous attempt.

### Noise caveat

The baseline achieved 1/5 full-pass; iteration achieved 0/5. Both are single 5-seed samples from a model whose output at fixed seed is documented as non-deterministic (V4 vs V5 demonstrated this). **These two rates are not a regression claim.** The robust finding is not "iteration is worse than baseline" — it is "iteration produces an algorithm swap that overfits, then stops."

The robust claims, from 14 total pre-gate attempts across 4 seeds:

- Zero candidates reached 11/11 under iteration
- Two of four attempting seeds changed algorithm exactly once, in response to feedback, in a way that fixed the reported failures and introduced new ones
- Two of four attempting seeds produced byte-identical output across all three attempts regardless of feedback
- No seed produced the parity-aware algorithm under iteration, though the baseline produced it once (1/5)

### Known limitations of the pre-gate implementation

Recorded for any future arc that reuses or extends this component. These did not affect the iteration measurement (the evaluator returned correct pass/fail for every attempt; the bypass did not trigger in any seed), but they are real design gaps:

1. **In-process execution.** `_cfd001_evaluate_candidate` imports and executes model-generated tokenizer code with `importlib` in NOVA's own Python process. Temporary directory isolates files, not execution. A malicious or accidentally-destructive candidate could affect the host. Any production or future-arc use of the pre-gate should route execution through the Docker sandbox that `behavioral_probe` already uses.

2. **Bypass when parser.py absent.** The pre-gate condition requires `"parser.py" in observed_files`. If the model writes `tokenizer.py` without reading `parser.py` first, the pre-gate is skipped. No seed hit this path, but it is a fail-open corner. A future implementation should either (a) load the trusted parser source directly from the task package when the benchmark id is known, or (b) block tokenizer writes with `pre_gate_skipped = True` when the guard cannot run.

Neither concern changes the measurement or the finding. Both are engineering debt for the next arc, not defects in this result.

### Arc close

The cross-file repair arc is closed with two appendices on iteration: one for the outcome, one for the mechanism. The pipeline reliably catches wrong repairs. The 9B model at cap1200 cannot reliably produce correct ones, and does not reach the correct algorithm from failure feedback. The next hypotheses (stronger model, different task family, reviewer algorithmic grounding) each require a separate arc.


---
## Small Test: Invariant-Guided Repair — Comprehension Works, Sequencing Fails (2026-11-12)

**Experiment:** small-test-20261112
**Manifest:** `small-test-manifest-20261112.json` SHA-256 `cc5ec917c166766a298c6dfc97ee19c2eefce3dd47e3fc340c07b1a22e67a9a1`
**Predictions:** `small-test-predictions-20261112.md` SHA-256 `d0a34b6d3cb0c472e83df62de2d9574a34b89eddbbb664105a9d97a7ed0afad7`, recorded before any model call
**Results:** `small-test-results-20261112.json`
**Model:** qwen3.5:9b-8k, temperature 0.2, seed 0, **max_tokens=3000**, `reasoning_effort=none`
**Evaluator:** `_cfd001_evaluate_candidate` (in-process; trusted candidates only)
**Scope:** 5 selected starting candidates, single attempt each. **Not** 5 independent seeds. **Not** a cap-1200 configuration.

### Result

**0/5 reached 11/11.** Average score dropped from 8.8/11 to 6.4/11.

| # | Source | Baseline | Result | Change | Size (baseline → result) |
|---|---|---|---|---|---|
| 1 | BASELINE-seed0 | 8/11 | 8/11 | 0 | 848b → 1225b |
| 2 | BASELINE-seed1 | 9/11 | 8/11 | −1 | 682b → 1823b |
| 3 | BASELINE-seed3 | 9/11 | 8/11 | −1 | 749b → 749b |
| 4 | ITERATION-seed0 | 9/11 | 6/11 | −3 | 848b → 1226b |
| 5 | ITERATION-seed3 | 9/11 | 2/11 | −7 | 682b → 9215b |

### The mechanism — recovered by inspecting the produced code

**Four of five candidates attempted parity.** They contain `backslash_count`, `% 2`, and explicit "odd/even" comments. The model **comprehended the invariant**. The failures are specific implementation bugs, not comprehension failures:

**Control-flow bug (candidates 1, 4 — identical).** The model placed the "skip single backslash" check before the parity check:

    if char == '\\' and in_quotes:
        i += 1              # consumes every single backslash
        continue
    elif char == '"' and in_quotes:
        j = i - 1
        while j >= 0 and source[j] == '\\':
            backslash_count += 1    # always 0 — backslash already skipped

The parity block is **dead code** because Block 1 consumes the backslashes before Block 2 can count them. Two candidates produced this identical bug.

**Semantic bug (candidate 2).** Counting consecutive backslashes **forward** from the current position (`i = index; while source[i] == '\\': count += 1`) re-processes overlapping runs on subsequent iterations, double-counting.

**No parity attempt (candidate 3).** Wrote skip-single (the R1/V3 algorithm from earlier in the arc). This is the one candidate that did not attempt parity — baseline 9/11, output 8/11.

**Corruption via rewrite (candidate 5).** 9215 bytes / 150 lines, collapsed to 2/11. Attempted parity but produced a function too large to be correct.

### What this establishes

Not "the model cannot implement the invariant." Not "the model ignored the invariant." The correct claim:

> **qwen3.5:9b-8k at cap3000 comprehends the parity rule and attempts to implement it in 4 of 5 candidates. The failures are specific sequencing and semantic bugs — chiefly, placing a "skip single backslash" block before the parity check, which makes the parity check unreachable. The model can produce the concepts but not the correct sequencing.**

Comprehension: demonstrated. Attempt: 4/5. Correct sequencing of primitives: 0/5.

### Limitations of this measurement

1. **Config is `max_tokens=3000`, not cap1200.** Not comparable to the base-rate (1/5) and iteration (0/5) experiments on the cap dimension.
2. **5 candidates, one seed.** Measures "can the model improve these five specific starting implementations" — not "what is the model's base rate at this prompt class."
3. **The prompt self-contradicted.** It said both "modify only quote-state handling; do not replace the whole function" and "return the complete new content of tokenizer.py." Compliance with the minimal-patch instruction **cannot be inferred** — the model followed the last instruction. Every candidate rewrote the file (749–9215 bytes, all ≥ baseline) but this is a prompt defect, not a model non-compliance finding.
4. **Evaluator is in-process.** `_cfd001_evaluate_candidate` runs generated code with `importlib` in NOVA's Python process. Appropriate for trusted candidates from a controlled prompt; not appropriate for adversarial code. Future uses of the pre-gate on untrusted input must route execution through the Docker sandbox.

### Prediction check

Pre-registered: 4–5/5 at 30%, 2–3/5 at 40%, 1/5 at 20%, 0/5 at 10%. Observed: **0/5** — the 10% bucket. Falsification confirmed.

### Combined three-prompt-class evidence

| Prompt class | Full-pass rate | Failure mechanism |
|---|---|---|
| Blind generation (base rate) | 1/5 | Stochastic draw occasionally hits parity-aware |
| Failure-only iteration | 0/5 | Algorithm swap between two wrong attractors |
| Invariant-guided repair | 0/5 | 4/5 attempted parity; sequencing bugs; 1/5 no parity attempt |

**1/15 across three prompt classes.** The small test adds the mechanism: the model reaches the parity concept but cannot sequence the primitives correctly.

### Production bug discovered

`_cfd001_postwrite_acceptance_probes()` in `loop.py` produces probes with `symbol: ""` and `expected_present: False`, which `validate_behavioral_probe` in `behavioral_probe.py` rejects at line 118. Never surfaced in the CFD-001 arc because V4 and V5 never reached the post-write completion gate. Masked in `tests/test_causal_review_controller.py` by the `stub_behavioral_probe` autouse fixture, which returns `PREDICTION_MATCHED` unconditionally. **If any future arc reaches the post-write gate on CFD-001, the gate will fail before it can validate any repair.** Two-field deletion plus a real-validator integration test. Engineering debt for the next arc.

### Recommended next-arc experiment (not run in this arc)

**Reference-guided repair.** Hypothesis: if the model is shown a near-correct reference implementation with one specific bug (rather than a wrong implementation and a description of the correct rule), it can repair it. This tests whether the sequencing bug is fixable when the search space is narrowed to "locate the sequencing bug in this working parity implementation" rather than "produce a working parity implementation."

Not run here. Belongs to the next arc, with its own pre-registration.

### Arc status

**Closed.** Three prompt classes, three distinct failure mechanisms, one confirmed production bug, one comprehension success and one sequencing failure. The pipeline is functional. The model reaches the correct concept but cannot sequence the primitives. Next arc is reference-guided repair, a larger model, or a different task family.


---
## Small Test: Invariant-Guided Repair — Comprehension Works, Implementation Fails (2026-11-12)

**Experiment:** small-test-20261112
**Manifest:** `small-test-manifest-20261112.json` SHA-256 `cc5ec917c166766a298c6dfc97ee19c2eefce3dd47e3fc340c07b1a22e67a9a1`
**Predictions:** `small-test-predictions-20261112.md` SHA-256 `d0a34b6d3cb0c472e83df62de2d9574a34b89eddbbb664105a9d97a7ed0afad7`, recorded before any model call
**Results:** `small-test-results-20261112.json`
**Model:** qwen3.5:9b-8k, temperature 0.2, seed 0, **max_tokens=3000**, `reasoning_effort=none`
**Evaluator:** `_cfd001_evaluate_candidate` (in-process; trusted candidates only)
**Scope:** 5 selected starting candidates, single attempt each. **Not** 5 independent seeds. **Not** a cap-1200 configuration.

### Result

**0/5 reached 11/11.** Average score dropped from 8.8/11 to 6.4/11.

| # | Source | Baseline | Result | Change | Size (baseline → result) |
|---|---|---|---|---|---|
| 1 | BASELINE-seed0 | 8/11 | 8/11 | 0 | 848b → 1225b |
| 2 | BASELINE-seed1 | 9/11 | 8/11 | −1 | 682b → 1823b |
| 3 | BASELINE-seed3 | 9/11 | 8/11 | −1 | 749b → 749b |
| 4 | ITERATION-seed0 | 9/11 | 6/11 | −3 | 848b → 1226b |
| 5 | ITERATION-seed3 | 9/11 | 2/11 | −7 | 682b → 9215b |

### What the produced code shows

**Four of five candidates attempted parity.** They contain `backslash_count`, `% 2`, and explicit "odd/even" comments. The model comprehended the invariant. This is not a comprehension failure and not a failure to attempt the implementation.

The failures are **diverse**, not a single mechanism:

- **Candidates 1 and 4** share a "skip single backslash, then count preceding backslashes" structure. Both attempted the correct primitives. Failure modes differ: candidate 1 stayed at 8/11 (same score as baseline, different wrong cases), candidate 4 dropped to 6/11. Full control-flow tracing of each failing case was not completed in this arc; the specific defect is deferred to the next arc's diagnostic work.
- **Candidate 2** used a forward-counting approach (`i = index; while source[i] == '\\': count += 1`) that re-processes overlapping runs on subsequent iterations. Conceptually close but semantically wrong.
- **Candidate 3** did not attempt parity. Wrote skip-single, the R1/V3 algorithm from the earlier arc. Baseline 9/11, output 8/11 — this is the one MECHANISM_5 case (no parity attempt).
- **Candidate 5** produced a 9215-byte / 150-line rewrite, 13x its 682-byte baseline. Attempted parity but the function is too large and broken to be correct.

### What this establishes

Three verifiable claims:

1. **Comprehension works.** 4/5 candidates contain parity constructs.
2. **Attempt works.** 4/5 candidates tried to implement the invariant.
3. **Correct implementation does not work at this prompt class.** 0/5 produced a passing function, and 4/5 regressed.

The failures are diverse implementation bugs across multiple mechanisms, not a single recurring defect. **Naming a specific "the model always does X wrong" mechanism is not supported by this data** — the two most similar candidates (1 and 4) share structure but have different failure profiles, and the other three each fail differently.

### Limitations of this measurement

1. **Config was `max_tokens=3000`, not cap1200.** Not comparable to base-rate (1/5) and iteration (0/5) on the cap dimension.
2. **5 candidates, one seed.** Measures "can the model improve these five specific starting implementations at this prompt class," not "what is the model's base rate."
3. **The prompt self-contradicted.** It said both "modify only quote-state handling; do not replace the whole function" and "return the complete new content of tokenizer.py." Every candidate rewrote the file. Compliance with the minimal-patch instruction **cannot be inferred** — this is a prompt defect, not a model-compliance finding.
4. **Evaluator is in-process.** `_cfd001_evaluate_candidate` runs generated code with `importlib` in NOVA's Python process. Appropriate for trusted candidates; not appropriate for adversarial code. Future use must route execution through the Docker sandbox.
5. **Mechanism is not fully traced.** The output files are preserved and the specific defect in each candidate can be recovered by tracing the failing cases. That work belongs to the next arc, not this one.

### Prediction check

Pre-registered: 4-5/5 at 30%, 2-3/5 at 40%, 1/5 at 20%, 0/5 at 10%. Observed: **0/5** — the 10% bucket. Falsification confirmed.

### Combined three-prompt-class evidence

| Prompt class | Full-pass rate | Failure mechanism |
|---|---|---|
| Blind generation (base rate) | 1/5 | Stochastic draw occasionally hits parity-aware |
| Failure-only iteration | 0/5 | Algorithm swap between two wrong attractors |
| Invariant-guided repair | 0/5 | 4/5 attempted parity; diverse implementation bugs; 1/5 no attempt |

**1/15 across three prompt classes.**

### Production bug discovered

`_cfd001_postwrite_acceptance_probes()` in `loop.py` produces probes with `symbol: ""` and `expected_present: False`, which `validate_behavioral_probe` in `behavioral_probe.py` rejects at line 118 with `BehavioralProbeError("Invalid behavioral probe fields.")`.

Never surfaced in the CFD-001 arc because V4 and V5 never reached the post-write completion gate. Masked in `tests/test_causal_review_controller.py` by the `stub_behavioral_probe` autouse fixture, which returns `PREDICTION_MATCHED` unconditionally and never invokes the real validator.

**If any future arc reaches the post-write gate on CFD-001, the gate will fail on this bug before it can validate any repair.** The fix is a two-field deletion in `_cfd001_postwrite_acceptance_probes()` plus a new test that exercises the real `run_behavioral_probe` instead of the stub. Engineering debt for the next arc.

### Recommended next-arc experiment (not run in this arc)

**Mechanism tracing + reference-guided repair.** Two steps, done in order:

1. **Trace each of the five produced files against its failing cases.** Recover the specific defect (control-flow, off-by-one, semantic mismatch). Preserve the tracing as evidence. This is a read-only analysis of existing artifacts — no new model calls.
2. **If the traced defects cluster into a small number of fixable patterns, run a reference-guided repair experiment.** Show the model a working parity implementation with a single inserted bug of the traced kind, ask it to locate and repair the injected defect. Tests whether narrowed search space resolves the sequencing issues. **Do not run this without first doing step 1.**

Step 1 belongs to the next arc. Step 2 is a hypothesis, not yet supported by tracing, and should not be pre-registered until the tracing work is done.

### Arc status

**Closed.** Three prompt classes, three distinct failure profiles, one confirmed production bug, one comprehension success with implementation failure. The pipeline is functional. The model reaches the correct concept and can attempt the implementation, but does not produce a correct one under any tested prompt class at cap1200-3000.

The next arc is either (a) mechanism tracing of the five produced files, (b) a different model, or (c) a different task family. Each is a separate arc with its own pre-registration.


---
## Small Test: Reference Verified; Five Candidates, Five Distinct Bugs (2026-11-12)

**Preceding verification step.** Before evaluating any model-generated candidate, the reference implementation (927 bytes, 30 lines) was tested against:

- **11 acceptance cases via `_cfd001_evaluate_candidate`:** 11/11 passed
- **Extended backslash-run parity (N = 0..12):** all 13 runs behave correctly. Even N toggles quote state; odd N raises `Unterminated quoted value`.
- **Cross-check against `tokenizer.py.manual-fixed`:** 11/11 passed

The reference is a valid control. The evaluator is healthy. Any candidate failure can now be compared against a known-correct implementation.

**Result of the model test:** 0/5 candidates reach 11/11. All 5 preserved. Each has a distinct implementation bug, traced against the code:

| Candidate | Bytes | Score | Bug (traced) |
|---|---|---|---|
| BASELINE-seed0 | 1225 | 8/11 | Unreachable state machine. Both branches guard on `in_quotes == True`; `in_quotes` is never set True. Effectively naive split-on-semicolon. Even-backslash cases pass incidentally via `ast.literal_eval`. |
| BASELINE-seed1 | 1823 | 8/11 | Double transitions. Backslash block forward-counts from each backslash position (overlapping runs); quote's `elif` toggles unconditionally regardless of what the block decided. Same quote toggles twice. |
| BASELINE-seed3 | 749 | 8/11 | No parity attempt. Skip-single algorithm (R1/V3 lineage). Fails all even-backslash cases. |
| ITERATION-seed0 | 1226 | 6/11 | Off-by-one parity. Backward count excludes the current backslash at index i; run length N is counted as N−1. Even treated as odd, odd as even. |
| ITERATION-seed3 | 9215 | 2/11 | Corrupted 150-line rewrite. 13x baseline size. Not traceable to a single bug. |

**What this establishes.** Four of five candidates contain parity concepts (`backslash_count`, `% 2`, "odd/even" comments). The model produces the concept. It does not produce a correct implementation in any of the five. The failures are five distinct bugs: unreachable state, double transition, no attempt, off-by-one count, corrupted rewrite.

**What this does not establish.** A single recurring failure mechanism. Naming any one bug as "the model's failure mode" would be inaccurate — the five candidates fail five different ways. The model's capability is not "does X wrong every time." It is "produces the concept but does not consistently implement it correctly."

**Config caveats.**
- `max_tokens=3000`, not cap1200. Not directly comparable to base-rate (1/5) and iteration (0/5) on the cap dimension.
- 5 selected starting candidates, one seed. Not 5 independent model seeds.
- Prompt self-contradicted: asked for minimal patch AND complete file content. Every candidate rewrote the file (749–9215 bytes). Compliance with the minimal-patch instruction cannot be inferred.

**Combined evidence across three prompt classes:**

| Prompt class | Full-pass | Failure pattern |
|---|---|---|
| Blind (base rate) | 1/5 | Stochastic — occasionally hits parity-aware |
| Failure-only iteration | 0/5 | Algorithm swap between two wrong attractors |
| Invariant-guided (max_tokens=3000) | 0/5 | Five distinct implementation bugs |

**1/15 across three prompt classes.** The reference is now established as a control for any future comparison.

**Recommended next-arc experiment (not run).** Reference-guided repair: present the model with the verified reference implementation plus a single injected bug (e.g., the off-by-one parity count), ask it to locate and repair. Tests whether a narrowed search space resolves implementation bugs that a from-scratch prompt does not. Requires its own pre-registration; not part of this arc.

**Production bug still outstanding.** `_cfd001_postwrite_acceptance_probes()` produces probes with `symbol: ""` and `expected_present: False`, rejected by `validate_behavioral_probe` at line 118. Masked by `stub_behavioral_probe` autouse fixture. Must be fixed before any post-write gate is trusted on CFD-001.

**Arc status.** Closed. Reference verified. Evaluator healthy. Five model-generated candidates traced to five distinct bugs. Three prompt classes, 1/15 full-pass. The pipeline is functional. The model reaches the parity concept but does not produce a correct implementation under any tested condition.


---
## AST Function Replacement: Fifth Prompt Class — One Genuine Repair (2026-11-12)

**Experiment:** ast-edit-20261112
**Predictions:** `ast-edit-predictions-20261112.md` SHA-256 `8228b5cbef3a297f...`, recorded before the run
**Results:** `ast-edit-results-20261112.json` SHA-256 `f3f50d57a196424d...`
**Interface:** model returns only a replacement `split_fields` function body; NOVA extracts it and applies it via stdlib `ast` (no LibCST).
**Model:** qwen3.5:9b-8k, temperature 0.2, seed 0, max_tokens 2000, reasoning_effort=none.
**Inputs:** same 5 preserved candidates from `small-test-manifest-20261112.json`.

### Result: 1/5 reach 11/11

| # | Candidate | Baseline | Result | What happened |
|---|---|---|---|---|
| 1 | BASELINE-seed0 | 8/11 | 8/11 | returned a replacement; no score change |
| 2 | BASELINE-seed1 | 9/11 | **11/11** | **returned a correct replacement** |
| 3 | BASELINE-seed3 | 9/11 | 8/11 | broke previously-passing case |
| 4 | ITERATION-seed0 | 9/11 | 9/11 | returned a replacement; no score change |
| 5 | ITERATION-seed3 | — | syntax error | `else` with no block (incomplete, not truncated) |

One genuine repair. Four failures for four different reasons.

### What this establishes

**The interface matters, partially.** The structured-patch interface (previous class) produced 0/5, with all failures attributed to source hallucination — the model reconstructed a prior-memory source fragment instead of copying the actual text. This interface removes that requirement: NOVA provides the extracted function, model returns only the replacement, NOVA applies it via AST. With this change, one candidate that was previously blocked (BASELINE-seed1) reached 11/11.

**The interface is not the whole story.** Three of four remaining candidates still failed after removing the source-copy requirement. Their failure mechanisms are algorithmic, not interface-related:

- **Candidate 1:** replacement produced same score (8/11). Likely a re-expressed version of the same bug.
- **Candidate 3:** regression (9/11 → 8/11). The model broke previously-passing behavior while attempting the fix — the same over-write pattern observed in the earlier iteration experiment.
- **Candidate 4:** replacement produced same score (9/11). Likely a re-expressed version of the same bug.
- **Candidate 5:** syntax error in returned function (`else` with no block). The response was incomplete — not from max_tokens truncation (`max_tokens=2000`, output fell short), but from the model producing a syntactically malformed replacement.

Candidate 2's success is the first genuine repair observed in this arc: a candidate that started broken (9/11) and ended fixed (11/11) through a single model call, without source-copy friction, without iteration, without preservation failures. That outcome was not observed in any prior prompt class.

### Combined five-class record

| Class | Full-pass | Failure mechanisms observed |
|---|---|---|
| Blind generation | 1/5 | Rare parity-aware draw |
| Failure-only iteration | 0/5 | Algorithm swap |
| Invariant-guided rewrite | 0/5 | Five distinct bugs |
| Structured patch (`old`/`new`) | 0/5 | Source hallucination |
| AST function replacement | **1/5** | Mixed: one repair, three algorithm failures, one syntax |

**2/25 across five prompt classes.** But the two successes are of different kinds: the blind success was a lucky draw; the AST success was a *repair* — a candidate that was broken and became correct through the interface.

### Interpretation

The AST result is a partial confirmation of the CODESTRUCT-adjacent hypothesis ("interface design matters"), but at a much smaller magnitude than the research would suggest. Removing the source-copy failure mode recovered exactly one of five candidates. The remaining four failed for non-interface reasons. The algorithmic ceiling survives.

This also means the correct framing of the arc's finding is not "the model cannot repair code." It is:

> **qwen3.5:9b-8k can produce one correct repair in five candidates when the interface removes source-copy friction. It produces algorithmically-wrong, unchanged, or syntax-broken replacements on the remaining four. The interface change recovered one candidate; it did not overcome the underlying capability limit.**

### Limitations

- 5 candidates, one seed. Not five independent model seeds.
- `max_tokens=2000` (not cap1200).
- In-process evaluator.
- No held-out verification of candidate 2's repair on adversarial inputs beyond the 11 acceptance cases.

### Production bug still outstanding

`_cfd001_postwrite_acceptance_probes()` produces probes with `symbol: ""` and `expected_present: False`, rejected by `validate_behavioral_probe`. Masked by `stub_behavioral_probe` autouse fixture. Fix required before any post-write gate is trusted on CFD-001.

### Arc status

**Closed.** Five prompt classes tested. 2/25 total success rate, with one genuinely repaired candidate. The pipeline is functional. The model is capable of one correct repair, not of reliable repair.

The next variable to test is model scale. The next alternative is a different task family. Neither requires another interface iteration on this task.


---
## LoRA Pilot: Reliable Implementation Generation, Generalization Untested (2026-11-12)

**Model:** Qwen/Qwen2.5-Coder-7B-Instruct (base + LoRA adapter)
**Adapter:** `lora-adapter-qwen25-coder-7b/adapter` (92 MB, rank 16, 3 epochs, 164s train on RTX 3070 Laptop)
**Dataset:** 9 training examples (5 real failures + 4 synthetic mutations), 4 held-out mutants
**Decoding:** greedy (do_sample=False, max_new_tokens=600)
**Evaluator:** 11-case acceptance contract via `_cfd001_evaluate_candidate`

### Matched greedy comparison

| Split | Base | Adapted | Δ |
|---|---|---|---|
| seed | 0/5 | 4/5 | +4 |
| train_mut | 1/4 | 3/4 | +3 |
| held_out | 1/4 | 4/4 | +3 |
| **TOTAL** | **2/13** | **11/13** | **+9** |

Deterministic under greedy decoding. Reproducible.

### Target-overlap audit: held-out is leaky

Training golds: **3 distinct exact SHAs**, 3 distinct structural (AST-normalized) SHAs:
- `reference` / `reference_run_consuming`: 6 examples
- `manual_fixed_escaped_flag`: 2 examples
- `ast_patched_baseline_seed1`: 1 example

Held-out golds: **all 4 examples use `manual_fixed_escaped_flag`** as gold. That gold appears in training as gold for `CFD001-REAL-0002` and `CFD001-REAL-0005`, both exact and structurally identical.

**The 4/4 held-out result therefore measured recovery of a known training target on new mutant inputs, not generalization to unseen implementations.**

### Output analysis: three dominant templates, plus one novel implementation

Under greedy decoding, the adapted model produces distinct output SHAs:

| Template SHA | Structural match to training gold? | Used for | Score |
|---|---|---|---|
| `77d426e4` | None (novel) | 4 seed passes | 11/11 |
| `ea3b4f2b` | Structurally identical to `reference_run_consuming` | 3 train_mut passes | 11/11 |
| `9ffcfc59` | None (novel) | 4 held-out passes | 11/11 |

Two of the three emitted templates (`77d426e4`, `9ffcfc59`) are neither exact nor structural matches to any training gold. **The adapter generated correct tokenizer implementations that were not in its training data.** `9ffcfc59` in particular was produced on all four held-out examples despite four different broken inputs.

This establishes that the adapter is not reproducing training strings verbatim. It is generating valid implementations beyond its training targets.

### What the emitted templates do and do not tell us

**Establishes:**
- The adapter learned a general pattern of correct tokenizer structure (three working implementations, two novel)
- The adapter reliably produces these implementations under greedy decoding (11/13)
- The base model could occasionally match a template (2/13, both via structural match to a training gold), but not reliably; the adapter made template emission consistent

**Does not establish:**
- That the adapter reasons about the specific defect (four different held-out defects → same output `9ffcfc59`)
- That identical output means "ignored input." NOVA requests complete function replacement, and a single correct implementation can legitimately repair multiple broken ones. The distinction that matters is whether the emitted implementation would be correct for a *structurally unfamiliar* broken input
- That the adapter generalizes to implementation styles it has never seen (held-out golds all leaked from training)

### Honest claim

**LoRA fine-tuning on 9 audited examples shifted Qwen2.5-Coder-7B from unreliable (2/13) to reliable (11/13) generation of correct tokenizer implementations under greedy decoding. The adapted model produces at least three distinct correct implementations, two of which do not appear in training by exact or normalized-AST hash. This is evidence of canonical implementation generation beyond memorization of training targets. It is not evidence of generalization to unfamiliar implementation styles, because all four held-out gold targets appeared in training. It is not evidence of per-defect reasoning, because different defects within the same family produce the same output.**

### Limitations

1. **Held-out golds overlapped with training golds** (all 4 held-out = `manual_fixed`, which was 2 training golds).
2. **Dataset size (9 examples)** — pilot-scale. Not sufficient for capability claims beyond this task.
3. **In-process evaluator** (trusted inputs only).
4. **One training run, one seed** — no variance estimate.

### Preserved artifacts

- `nova-eval-lab/repair-dataset-20261112/` — seed.jsonl, train_mutations.jsonl, held_out_mutations.jsonl, schema.md
- `nova-eval-lab/lora-adapter-qwen25-coder-7b/adapter/` — 92 MB adapter
- `baseline-Qwen-Qwen2.5-Coder-7B-Instruct.json`
- `adapted-Qwen2.5-Coder-7B-LoRA.json`
- `deterministic-audit-20261112.json`

### Next experiment (defined, not run)

**Novel-gold generalization test.** Construct 3+ independently structured correct tokenizer implementations, none appearing in training by exact or normalized-AST hash. For each: introduce a controlled defect, confirm it is detected, run base and adapter with identical greedy decoding, evaluate the actual generated output against the full 11-case contract.

Three possible outcomes:
- Adapter passes with a novel correct implementation → learned solution generalizes beyond training structure
- Adapter passes with a training-derived implementation → canonical-template reproduction, not flexible generation
- Adapter fails → current improvement is limited to familiar implementation families

Requires additional behavioral tests beyond the 11-case contract for the new golds (to prevent the adapter passing via a narrow-contract win). No retraining required.

### Arc status

The LoRA pilot is a positive pilot result with a clear next-step question. It demonstrates reliable implementation generation on this specific task and preserves one novel output. It does not establish repair reasoning or generalization to unfamiliar implementation styles. The adapter is preserved as the first NOVA-trained artifact.


---
## LoRA Pilot: Novel Implementation Generation with a Recursive-Case Regression (2026-11-12)

**Model:** Qwen/Qwen2.5-Coder-7B-Instruct (base + LoRA adapter)
**Adapter:** `lora-adapter-qwen25-coder-7b/adapter` (92 MB, rank 16, 3 epochs, 164s train on RTX 3070 Laptop)
**Training data:** 9 audited examples — 5 real model failures + 4 synthetic mutations across 3 structurally distinct golds
**Evaluation:** 11-case acceptance contract + extended parity sweep (N=0..12)
**Decoding:** greedy (do_sample=False, max_new_tokens=600)
**Evaluator:** `_cfd001_evaluate_candidate` (in-process; trusted inputs)

### Matched greedy comparison (in-distribution)

| Split | Base | Adapted | Δ |
|---|---|---|---|
| seed | 0/5 | 4/5 | +4 |
| train_mut | 1/4 | 3/4 | +2 |
| held_out | 1/4 | 4/4 | +3 |
| **TOTAL** | **2/13** | **11/13** | **+9** |

Deterministic under greedy decoding, reproducible.

**Held-out caveat:** all 4 held-out examples used `manual_fixed` as gold, which appeared as gold for 2 training examples (`CFD001-REAL-0002`, `-0005`), both exact and structurally identical. The 4/4 held-out result measured recovery of a known training target on new mutant inputs, not generalization to unseen implementation styles.

### Novel-gold generalization test

Three independently structured correct tokenizer implementations were authored for this test. Each was:
- Verified 11/11 on the acceptance contract
- Verified pass on extended parity sweep (N=0..12)
- Confirmed novel: exact and AST-normalized SHA both differ from all training golds

| Gold | Structure | Verified | In training? |
|---|---|---|---|
| Novel A | Two-pass scanner (locate structural quotes, then split) | 11/11 + parity | No (exact and struct) |
| Novel B | Chunk-based streaming with explicit run counter | 11/11 + parity | No (exact and struct) |
| Novel C | Recursive descent (split on first unquoted ;, recurse) | 11/11 + parity | No (exact and struct) |

Each gold was then broken with a controlled defect that failed 1–2 acceptance cases. Base and adapted model were run on identical broken inputs under greedy decoding.

### Novel-gold results

| Test | Base | Adapted | Adapted output SHA | Classification |
|---|---|---|---|---|
| Novel A (two-pass) | 9/11 FAIL | **11/11 PASS** | `610d701d75aa` | NOVEL_OUTPUT |
| Novel B (chunk) | 9/11 FAIL | **11/11 PASS** | `f555c4139786` | NOVEL_OUTPUT |
| Novel C (recursive) | **11/11 PASS** (≈gold struct) | SYNTAX ERROR | — | invalid output |
| **TOTAL** | **1/3** | **2/3** | | |

### Three findings

**Finding 1: Genuine novel implementation generation.** Two of three adapted outputs (`610d701d`, `f555c413`) match no training gold, no known adapter template, and no structurally similar past output. Both pass 11/11. **The adapter generated correct tokenizer implementations for unfamiliar broken inputs.**

This refutes an earlier hypothesis ("adapter emits one memorized template per input family") that was based on identical SHAs in prior runs. Identical SHAs do not imply template reproduction — a canonical solution can be correct for many inputs, and the novel-gold test shows the adapter also produces genuinely new implementations when the input structure demands it.

**Finding 2: A specific regression on recursive structures.** Novel C — a recursive-descent implementation with helper function `_first_split` — was correctly handled by the base model (produced structurally similar code, 11/11). The adapter produced invalid Python (syntax error). Fine-tuning on 9 iterative-loop implementations overwrote the base model's ability to handle recursive structures, even though the base model had demonstrated it.

**Finding 3: Net capability shift, not strictly positive.** Base: 1/3 on novel golds. Adapted: 2/3. The adapter gained 2 cases (A, B) and lost 1 case (C). The gains are on structural styles close to its training distributions; the loss is on a style (recursion) that was already present in the base model but is absent from the 9-example training set.

### What the LoRA pilot establishes

1. **9 audited examples meaningfully shifted generation behavior.** In-distribution acceptance went from 2/13 to 11/13 under matched decoding.
2. **The adapter generates correct implementations that are not in training data.** Two novel golds passed with output SHAs matching nothing prior.
3. **Fine-tuning is not strictly additive.** Training on 9 examples traded the base model's recursive-implementation capability for reliable iterative-implementation generation.
4. **The adapter is not a template-reproduction machine.** Its outputs vary by input structure when the input requires novel structure.

### What the LoRA pilot does not establish

1. **Reliable repair reasoning.** Two of three novel golds passed, one failed. Directionally better than base (1/3) but with a specific blind spot (recursion).
2. **Generalization to implementation styles outside the tested set.** Three novel styles tested; two passed. A broader test set (5–10 novel styles) would give a more stable rate.
3. **That the improvement is safe.** The recursive regression shows that adding a specific capability can cost a different one. A production system would need to preserve the base model's capabilities alongside the adapter's.
4. **That 9 examples is a sufficient dataset.** Held-out leakage and single-seed training prevent the 11/13 figure from being a capability estimate.

### The complete arc claim

**A pipeline that catches wrong repairs, five documented prompt-class failures, and a fine-tuned LoRA adapter that generates correct implementations beyond its training distribution — with a specific regression on recursive structures that identifies the tradeoff.**

The adapter is a validated first artifact. Not a solution, not a proof of general repair capability, but a demonstrated capability shift with quantified bounds.

### Preserved artifacts

- `nova-eval-lab/repair-dataset-20261112/` — seed.jsonl, train_mutations.jsonl, held_out_mutations.jsonl, schema.md, novel-gold-audit-20261112.json
- `nova-eval-lab/lora-adapter-qwen25-coder-7b/adapter/` — 92 MB adapter
- `baseline-Qwen-Qwen2.5-Coder-7B-Instruct.json`, `adapted-Qwen2.5-Coder-7B-LoRA.json`, `deterministic-audit-20261112.json`
- Novel golds A, B, C preserved in `novel-gold-audit-20261112.json` with exact SHAs

### Next experiment (defined, not run)

The recursive regression suggests a specific follow-up: **"training-set diversity for capability preservation."** Train a second adapter on a dataset that includes recursive-style implementations. Measure whether it (a) preserves the base model's recursive capability AND (b) retains the novel-gold gains on iterative styles. If yes → capability preservation is achievable via data diversity. If no → fine-tuning fundamentally trades capability and needs multi-adapter or merge strategies.

That is a separate arc. It requires generating recursive-style training examples, retraining, and re-running the three novel golds plus additional recursive-style novel golds.


---
## LoRA Pilot: Implementation-Level Generalization with a Recursive Regression (2026-11-12)

**Model:** Qwen/Qwen2.5-Coder-7B-Instruct (base + LoRA adapter)
**Adapter:** `lora-adapter-qwen25-coder-7b/adapter` (92 MB, rank 16, 3 epochs, 164s train on RTX 3070 Laptop)
**Training data:** 9 audited examples (5 real model failures + 4 synthetic mutations across 3 structurally distinct golds)
**Evaluation:** 11-case acceptance contract + extended parity sweep (N=0..12)
**Decoding:** greedy (do_sample=False, max_new_tokens=600)
**Evaluator:** `_cfd001_evaluate_candidate` (in-process; trusted inputs)

### In-distribution result

| Split | Base | Adapted | Δ |
|---|---|---|---|
| seed | 0/5 | 4/5 | +4 |
| train_mut | 1/4 | 3/4 | +2 |
| held_out | 1/4 | 4/4 | +3 |
| **TOTAL** | **2/13** | **11/13** | **+9** |

Deterministic under greedy decoding, reproducible.

**Held-out caveat:** all 4 held-out examples used `manual_fixed` as gold, which appeared as gold for 2 training examples (`CFD001-REAL-0002`, `-0005`). The 4/4 held-out result measured recovery of a known training target, not generalization to unseen implementation styles.

### Novel-gold generalization test

Three independently structured correct tokenizer implementations were authored, each verified 11/11 and extended parity N=0–12, and each confirmed to not appear in training (exact or AST-normalized). Each was then broken with a controlled defect (broken score 9/11) and the base and adapted models were run on identical broken inputs under greedy decoding.

| Test | Structure | Base | Adapted | Adapted output | Acceptance | Parity N=0–12 |
|---|---|---|---|---|---|---|
| A | Two-pass scanner (locate structural quotes, then split) | 9/11 | **11/11 PASS** | `610d701d75aa` | 11/11 | **PASS** |
| B | Chunk-based streaming with explicit run counter | 9/11 | **11/11 PASS** | `f555c41397868d` | 11/11 | **PASS** |
| C | Recursive descent (split on first unquoted ;, recurse) | **11/11 PASS** | SYNTAX ERROR | `01d3911d2c91` (invalid) | 0/11 | n/a |
| | | **1/3** | **2/3** | | | |

### Validated properties of the two successful outputs

Both successful adapted outputs were:

- **Deterministic.** Greedy decoding produced the same output SHA across two independent runs.
- **Fully novel.** Neither matched any training gold, any of the three novel golds, or each other under exact-hash or AST-normalized structural comparison.
- **Fully correct.** Both passed all 11 acceptance cases and the extended backslash-parity sweep N=0–12.
- **Distinct.** Novel A output (`610d701d`) and Novel B output (`f555c413`) are different implementations.

### What this establishes

**Implementation-level generalization.** The adapter produced two correct tokenizer implementations for broken inputs it had never seen, in structures not present in training, with the same acceptance and parity behavior as a verified reference. Its output varies by input structure rather than collapsing to a single template. The two successful outputs differed from each other, and both are novel.

**Measured capability shift, not a solution.** Base model scored 1/3 on novel golds; adapted scored 2/3. The adapter improved two partially successful generations (both started at 9/11). It did not create working implementations from scratch — it produced the two missing acceptance cases for each. Fine-tuning improved completeness or correctness of already-broadly-working generations.

**A specific, measured regression.** The base model handled the recursive-descent case (Novel C) by producing structurally-similar correct code. The adapter produced invalid Python. This is one measured test with one recursive structure; it is not sufficient evidence of a general recursive-code weakness, but it is a real observed regression on a specific capability the base model had.

### What this does not establish

- **General repair reasoning across task families.** All three novel golds are variants of the same tokenizer problem and the same backslash-parity rule. They test variation in implementation structure, not three independent cross-file defect families.
- **That the adapter preserves all base capabilities.** One observed regression (recursion) suggests it may not. A systematic preservation test was not run.
- **Reliable per-defect repair reasoning.** Different defects within the same implementation family (tested earlier) produced identical outputs. The novel-gold test shows the adapter can produce different outputs when structural style varies; it does not show defect-conditioned fix design within a single style.
- **That 9 examples is a sufficient dataset.** Single-seed training, held-out leakage, and observed regression all indicate this is a pilot.

### Preserved artifacts

- `nova-eval-lab/repair-dataset-20261112/` — seed.jsonl, train_mutations.jsonl, held_out_mutations.jsonl, schema.md, novel-gold-audit-20261112.json, novel-gold-validation-20261112.json
- `nova-eval-lab/lora-adapter-qwen25-coder-7b/adapter/` — 92 MB adapter
- `baseline-Qwen-Qwen2.5-Coder-7B-Instruct.json`, `adapted-Qwen2.5-Coder-7B-LoRA.json`, `deterministic-audit-20261112.json`
- `novel-gold-validation-20261112.json` — full source, hashes, acceptance results, parity sweep results, and model config for all three novel golds, all three broken inputs, and all three generated outputs (including the preserved syntax-invalid recursive response)

### The arc's finding

NOVA has a task-specific cross-file repair pipeline, an adversarial acceptance contract with independently verified reference behavior, five documented repair-prompt failure classes each traced to distinct mechanisms, a nine-example failure-derived training pilot with an audited quality contract, a 92 MB QLoRA adapter, a deterministic base-versus-adapted improvement from 2/13 to 11/13 on the pilot, and two novel implementation-generation cases that pass both the acceptance contract and extended parity sweep and do not match any training or prior output structure. The adapter shows a specific regression on a recursive structure that the base model handled. Implementation-level generalization is demonstrated on this task; general repair reasoning across task families is not.

### The next research question

**Can NOVA preserve the base model's existing capabilities while improving its ability to generate and repair unfamiliar implementations?** The recursive regression is the concrete case that defines this question. A follow-up training run that includes recursive-style examples in the dataset, evaluated against held-out novel golds spanning both iterative and recursive structures, would test whether capability preservation is achievable via data diversity or whether fine-tuning fundamentally trades capability.

That is a separate arc. It requires generating recursive-style training examples, retraining, and re-running the three novel golds plus additional recursive-style novel golds. It does not require changes to the pipeline, the acceptance contract, or the existing adapter.


---

## Corrections and Consolidated Findings (2026-11-13)

This section supersedes earlier claims where they conflict. It applies corrections identified during critical review, adds a consolidated evaluation manifest, and states the current defensible findings with sample-size and scope qualifications.

### Corrections applied to earlier findings

**Retracted: "Adding data trades capabilities, doesn't accumulate."**

The stronger claim is not supported. What the v5 → v6 experiment demonstrated: under one specific training configuration with one small dataset, adding three recursive examples recovered recursive behavior (Novel C: syntax error → 11/11) while degrading chunk-based behavior (Novel B: 11/11 → 5/11) and two in-distribution seed cases.

The following alternative explanations for the observed tradeoff have not been separated: catastrophic forgetting, sensitivity to training order, learning-rate or optimization instability, insufficient representation of the chunk-based pattern, sampling variability in evaluation.

The defensible claim is: **preliminary empirical evidence of capability interference during small-dataset adapter expansion.** Not a universal property of fine-tuning.

**Retracted: "1/5 base rate" as a stable estimate.**

The base rate was measured once, across 5 seeds. It is an observation about those 5 seeds, not a reliable estimate of the model's success probability. The correct phrasing is: *"Observed 1/5 successful repairs under the tested configuration."*

Same qualification for "2/3 novel-gold" — that is 2 out of 3 specific examples, not a general generalization rate.

**Reclassified: reviewer fix is component-level, not end-to-end.**

The reviewer correctly evaluates proposed diffs (demonstrated at component level in V5). It has not been shown that this reviewer makes an entire repair task succeed, because no candidate has reached the post-write gate through the full pipeline. The reviewer fix is necessary but not sufficient for end-to-end autonomous repair.

**Reclassified: "The model is the ceiling" (from the earlier arc).**

Precision: the 9B model at cap-1200 does not reliably produce correct repairs under any of the five tested prompt classes. Whether a stronger model, different training data, or different architecture would succeed remains untested within the current pipeline.

### Production bug fixed during this correction pass

`_cfd001_postwrite_acceptance_probes()` in `src/nova/controller/loop.py` was producing probes with extra fields (`symbol`, `expected_present`) that `validate_behavioral_probe` rejects. This blocked the post-write gate from ever running, which is why no candidate had reached it in any prior live run.

Fixed 2026-11-13:
- `loop.py` pre-patch SHA: `28813c8b3ff8d3e0ca1491d532214ff55198005a86179adad46927db34336e18`
- `loop.py` post-patch SHA: `8c5471a06e9d86df13c4afd0792ef2e57e2ddb0aebe00e86085101f082ff8008`
- Two new tests in `tests/test_behavioral_probe.py` verify: (a) current probes match validator schema, (b) drifted probes are rejected before sandbox execution
- Full suite: 337 passed (was 335 + 2 new)
- Ruff: clean

End-to-end post-write verification is now reachable in principle. It has not yet been demonstrated live.

### Evaluation manifest

### Evaluation manifest

**Training set (v5: 9 examples; v6: 12 examples)**

| example_id | split | gold implementation | mechanism | used in v5 | used in v6 |
|---|---|---|---|---|---|
| CFD001-REAL-0001 | seed | reference_run_consuming | unreachable_state | ✓ | ✓ |
| CFD001-REAL-0002 | seed | manual_fixed_escaped_flag | double_transition | ✓ | ✓ |
| CFD001-REAL-0003 | seed | ast_patched_baseline_seed1 | no_parity_attempt | ✓ | ✓ |
| CFD001-REAL-0004 | seed | reference_run_consuming | off_by_one_parity | ✓ | ✓ |
| CFD001-REAL-0005 | seed | manual_fixed_escaped_flag | corrupted_rewrite | ✓ | ✓ |
| CFD001-MUT-0100 | train_mut | reference | unreachable_state | ✓ | ✓ |
| CFD001-MUT-0101 | train_mut | reference | no_parity_check | ✓ | ✓ |
| CFD001-MUT-0102 | train_mut | reference | inverted_parity | ✓ | ✓ |
| CFD001-MUT-0103 | train_mut | reference | off_by_one_parity | ✓ | ✓ |
| CFD001-REC-0001 | train_mut | recursive_A_recursive_descent | recursive_parity | — | ✓ |
| CFD001-REC-0002 | train_mut | recursive_B_acc_recursion | recursive_parity | — | ✓ |
| CFD001-REC-0003 | train_mut | recursive_C_iterative_helper | recursive_parity | — | ✓ |

**Held-out set (used for in-distribution evaluation only)**

| example_id | split | gold implementation | mechanism | in training? |
|---|---|---|---|---|
| CFD001-MUT-0104 | held_out | manual_fixed | escaped_never_reset | no |
| CFD001-MUT-0105 | held_out | manual_fixed | escaped_never_set | no |
| CFD001-MUT-0106 | held_out | manual_fixed | close_quote_ignored | no |
| CFD001-MUT-0107 | held_out | manual_fixed | open_quote_ignored | no |

**Novel-gold test set (never in training, exact or structural)**

| name | structural style | verified 11/11 | parity sweep N=0–12 | in training? |
|---|---|---|---|---|
| novel_A_two_pass | two-pass scanner (locate structural quotes then split) | ✓ | ✓ | no (confirmed by SHA + AST) |
| novel_B_chunk | chunk-based streaming with explicit run counter | ✓ | ✓ | no (confirmed by SHA + AST) |
| novel_C_recursive | recursive descent (split first unquoted ;, recurse) | ✓ | ✓ | no (confirmed by SHA + AST) |

### Consolidated findings with hedged claims

**Finding A — Benchmark hardening (strong).**
The original 7-case benchmark accepted repairs that failed 3/4 adversarial backslash-parity cases. Extending to 11 cases rejects both R1 and V3 algorithms. *What this establishes:* the prior performance measurements were not trustworthy at the original measurement boundary. *What it does not establish:* that the 11-case suite is sufficient for all possible tokenizer defects.

**Finding B — Candidate generation is uncorrelated with candidate evaluation (strong).**
V4 produced a correct repair that a reviewer blocked. V5's reviewer approved on first attempt, but the candidate was algorithmically wrong. *What this establishes:* generation and evaluation are independently fallible components; neither implies the other. *What it does not establish:* that fixing both will produce reliable end-to-end success.

**Finding C — Small fine-tuning improves in-distribution reliability (moderate evidence, small sample).**
LoRA fine-tuning on 9 audited examples improved observed in-distribution acceptance from 2/13 (base) to 11/13 (adapted), reproduced under deterministic greedy decoding. *What this establishes:* fine-tuning on a small, curated dataset produces a substantial behavioral shift on a bounded task. *What it does not establish:* stable expected improvement across seeds, training runs, or task variations.

**Finding D — The adapter generates novel correct implementations (moderate evidence, 2/3 novel golds).**
On three structurally distinct tokenizer implementations not present in training, the adapted model passed 2/3 (Novel A, Novel B) with outputs that were not exact or structural matches to any training or novel gold output. *What this establishes:* the adapter is not merely reproducing training templates. It can produce correct implementations for structurally unfamiliar inputs. *What it does not establish:* generalization across task families or defect types.

**Finding E — Capability preservation is a real problem (preliminary evidence).**
v5 → v6 experiment produced a capability interference pattern: adding recursive examples recovered Novel C while degrading Novel B and two seed cases. *What this establishes:* naive dataset expansion under one training configuration can trade capabilities rather than accumulate them. *What it does not establish:* the mechanism, whether it is universal, or that all small-data fine-tuning will exhibit it.

### Open questions the current evidence does not answer

1. Whether a stronger model (larger, or same family larger) would close the base-rate gap.
2. Whether multi-adapter selection — retaining v5 and v6 as parallel alternatives and choosing among them — achieves higher coverage than either adapter alone.
3. Whether curriculum training (staged dataset additions) avoids capability interference.
4. Whether the post-write gate can validate a correct candidate end-to-end in a live run.
5. Whether any of the above generalizes beyond escaped-quote-parity defects.

### The experiment now pending

**Multi-adapter selection pilot (frozen v5 + v6, sealed novel golds).**

Proposed design:
- Author 4-5 sealed novel golds with structurally distinct implementations not in training or prior novel tests
- Run base + v5 on each sealed gold under greedy decoding
- Selection rule: accept a candidate only if it passes 11/11 + parity sweep
- Success thresholds (engineering decision, not statistical): 5/5 strong pilot / 4/5 promising / 2-3/5 inconclusive / 0-1/5 hypothesis not supported
- Keep v6 frozen as reserve
- Do not respond to a failed selection experiment by training v7

**The eventual goal is one successful end-to-end autonomous repair.** That means: cross-file repair task → candidate generation across adapters → deterministic selection → reviewer evaluates selected candidate → write into isolated worktree → post-write verification passes. That has not been demonstrated. It is the criterion that would most substantively advance the NOVA research.

### What the arc has produced

Across the full session arc:
- Benchmark hardening with adversarial cases
- Reviewer fix that evaluates proposed diffs (component-verified)
- Five documented prompt-class failure mechanisms, each traced
- A quality-audited repair dataset with schema and mutation contract
- Two trained adapters (v5, v6), 92 MB each, preserved with configuration
- Novel-gold evidence that fine-tuning produces genuinely novel correct implementations (2/3, verified by SHA + AST + parity sweep)
- A capability-interference finding (v5 vs v6 tradeoff) that motivates the next architecture question
- A production bug fixed (post-write probe schema) that unblocks end-to-end testing
- A version tree structure (`evolver/version-tree-v1.json`) recording all candidates, changes, regressions, and acceptance policy

The single most defensible claim: **NOVA has a documented, reproducible capability of generating correct tokenizer-implementation repairs after minimal fine-tuning, with a known recursive-style regression and a known capability-interference pattern under dataset expansion. End-to-end autonomous repair is the next milestone and is now reachable but not yet demonstrated.**

### Status

Corrections applied 2026-11-13. Multi-adapter selection experiment is pending. Finding document is at post-correction SHA below.
---

**Correction: evaluation manifest leakage column (2026-11-13)**

The `in training?` column of the held-out-set manifest above reports `no` for all four examples (`CFD001-MUT-0104` through `-0107`). **This is incorrect.**

All four held-out examples use `manual_fixed` as their gold implementation. That implementation appears in the training set as gold for `CFD001-REAL-0002` and `CFD001-REAL-0005` (labels `manual_fixed_escaped_flag`). The audit confirmed exact-hash equality (`178707fe91827c44...`) and structural equality (`ab9fe2f9e4b01f49...`) between the held-out golds and the training golds.

The generator that produced the manifest compared `gold_name` string labels. The label `manual_fixed` differs from `manual_fixed_escaped_flag` as a string, so the check returned "no match." The underlying source text is identical.

**Correct disclosure:** all four held-out examples share their gold implementation with training. The held-out evaluation was **not a clean generalization test** — it measured recovery of a known training target on new broken inputs. This is the leakage that the surrounding correction sections and the earlier novel-gold analysis both describe. The manifest column should read `YES — leakage` for all four rows.

The four novel golds (`novel_A_two_pass`, `novel_B_chunk`, `novel_C_recursive`) are not affected — they were verified against training golds by exact SHA and AST-normalized SHA, and no matches were found. The novel-gold generalization result (2/3 adapted, verified novel outputs) stands unaffected by this manifest error.

The in-distribution and held-out comparison (2/13 → 11/13) remains valid as a measurement of adapter behavior on specific inputs. It does not, however, support generalization claims to unseen gold implementations. That limitation was already disclosed in the Finding C and Finding E hedged claims above; this correction restores consistency between those claims and the manifest table.

---

## Finding F: Complementary Candidate Coverage Through Specialized Adapter Selection (2026-11-13)

**Experiment:** three-adapter sealed selection, exploratory extension
**Sealed set SHA:** `133035b3ea2125cc43cc4be9816bea30da2c2dc259b24d8a045299a55285deb7`
**Three-adapter results SHA:** `795574e2e479039687c9053201185cbc5866992ab88c254e297eb59477777a0f`
**Full preservation SHA:** `9795cebbf0750587786bb8e6fb2fad4ca318f616397a3c3763d01fb458b7cd28`
**Method:** single PeftModel instance with v5 and v6 loaded as named adapters; `disable_adapter()` for baseline; `set_adapter()` to switch; canonical `_cfd001_evaluate_candidate`; greedy decoding.
**Caveat:** the five sealed examples were already inspected during the BASE+V5 experiment. This is an exploratory extension, not independent sealed confirmation.

### Results

| Case | BASE | V5 | V6 | Selected |
|---|---|---|---|---|
| S1 generator | 2/11 | 9/11 | **11/11** ✓ | V6 |
| S2 regex | 5/11 | 2/11 | **11/11** ✓ | V6 |
| S3 class | **11/11** ✓ | 2/11 | 2/11 | BASE |
| S4 quote-prepass | 2/11 | 2/11 | **11/11** ✓ | V6 |
| S5 rejoin | **11/11** ✓ | **11/11** ✓ | **11/11** ✓ | BASE |

**Base: 2/5. V5: 1/5. V6: 4/5. V6-exclusive: 3/5. Three-way union: 5/5. BASE+V6 (dropping V5): 5/5.**

V5 contributes zero unique coverage on this set. The minimum viable portfolio is BASE + V6, not three adapters.

### Finding

**Complementary candidate coverage through specialized adapter selection (exploratory evidence).**

On five structurally distinct examples previously inspected during the BASE+V5 experiment, BASE achieved 2/5 acceptance, V5 achieved 1/5, and V6 achieved 4/5. The three-configuration union achieved 5/5 coverage, with V6 providing three uniquely passing candidates (S1, S2, S4). BASE + V6 alone also achieved 5/5, demonstrating that V5 contributed no additional acceptance coverage on this test set.

This provides preliminary empirical evidence that maintaining specialized adapters as alternative candidate generators can increase combined repair coverage relative to individual configurations. The result is exploratory rather than independent confirmation because the examples had already been inspected, the sample comprises five cases, and evaluation was limited to candidate generation, the canonical 11-case acceptance suite, and the N=0–12 parity sweep.

### Qualifications

1. **S4 is not a wholly independent algorithm family.** The quote-preprocessing approach resembles the earlier two-pass novel implementation. It counts as a different implementation, not a fundamentally new control-flow pattern.
2. **V6's 4/5 is an observed result on five examples, not an estimated 80% success rate.** Small-sample results do not generalize.
3. **End-to-end autonomous repository repair remains unproven.** All portfolio results were obtained through offline candidate generation and executable validation. The NOVA controller has not yet demonstrated a complete repair through writing, reviewer approval, and post-write verification.

### Minimum integration configuration

BASE + V6. V5 is preserved as a research comparator but excluded from the live pipeline until new evidence justifies its inference cost. Model boundary constraint: V6 is a Qwen2.5-Coder-7B adapter. It must remain attached to its compatible 7B base and cannot be attached to the 9B planning/reviewer model.

### The next experiment

Integrate BASE + V6 candidate generation into NOVA's repair pipeline and verify a successful repository modification through the post-write gate. The end-to-end success criterion:

1. Intended repository source actually changes (tokenizer.py, not parser.py)
2. Selected candidate passes the canonical 11-case acceptance gate
3. Reviewer approves the actual proposed diff (not re-diagnosis of the original)
4. Post-write behavioral gate passes
5. Repository regression and independently maintained hidden tests pass
6. Isolated worktree and all evidence preserved

A candidate passing offline is not sufficient. The end-to-end milestone is the one that changes NOVA from a model-training experiment into a systems-engineering demonstration.

---

## Finding G: First End-to-End Autonomous Repair (2026-11-13)

**Trial:** end-to-end-20261113-141001
**Result SHA:** `3605f0fc0738a2bc7a2178da49336a864d196789a68e5bbbc1205713b1787a10`
**Completed at (UTC):** 2026-11-13T08:44:43.680177+00:00

### The artifact

One complete autonomous repair of the CFD-001 cross-file defect. Verified:

- `stop_reason`: **`completed`**
- `agent_success`: **`True`**
- `postwrite_behavior_check_passed`: **`True`**
- `completion_gate`: **`postwrite_task_contract`**
- `changed_source_files`: `['tokenizer.py']` (correct file; `parser.py` unchanged)
- `probes_attempted` / `probes_completed`: **12 / 12** (1 hypothesis probe + 11 acceptance probes)
- Final workspace acceptance: **11/11 + parity PASS**
- Independent hidden tests: **6/6 passed**

The workspace contains the correct repaired `tokenizer.py`, verified independently of the pipeline that produced it. Full evidence in `C:\Users\Shahid\nova-eval-lab\end-to-end-20261113-141001\result.json`.

### Architecture

**Two-stage, two-model-role architecture:**

**Stage 1 — Candidate generation and selection (external to the pipeline).**
Base Qwen2.5-Coder-7B-Instruct, with LoRA v6 adapter available via `disable_adapter()` / `set_adapter()`. Both base and v6 generated 11/11 + parity candidates from the 9/11 starter. Selection rule: prefer v6 when it passes. V6 selected (SHA `59366286026e…`). This is a 7B model and its adapter — one model role, two inference modes.

**Stage 2 — NOVA controller pipeline.**
Qwen3.5-9B (the second model role). Planning, hypothesis test, causal review, dispatch, post-write gate. The candidate was supplied via the `pre_selected_candidate` parameter added to `run_task`, which substitutes the model's write proposal with the pre-selected content. Every subsequent pipeline gate — syntax check, hypothesis test, causal review, dispatch, post-write acceptance gate — remained fully active.

**Stage 3 — Independent verification (external).**
11-case acceptance contract + 6 hidden tests + parity sweep N=0–12. Run by the orchestration script after the pipeline finished, using the final workspace files.

The two model roles are separate components with separate responsibilities. The candidate was **not** generated by the 9B controller. The 9B controller's contribution was: hypothesis testing, reviewer approval, dispatch, post-write verification, and completion recognition.

### What the pipeline autonomously handled

Given only the task and a correct pre-selected candidate:
- `list_files` → `read_file` exploration (steps 0–1)
- Substituted write dispatch (step 2)
- Hypothesis test: **PREDICTION_MATCHED**
- Causal review: **APPROVE** with `repair_target: tokenizer.py`
- Post-write gate: 11 acceptance probes executed, all passed
- Forced completion recognition after dispatch
- `stop_reason: completed`

### What enabled the success

Three infrastructure fixes made this run possible:

1. **Probe-schema fix.** `_cfd001_postwrite_acceptance_probes()` carried two extra fields (`symbol`, `expected_present`) rejected by `validate_behavioral_probe`. This bug had blocked the post-write gate since the original arc. With the schema corrected and two regression tests added, the gate fires live.
2. **WSL timeout + prewarm.** Cold WSL `wslpath` calls took ~10s; a 45s timeout plus one prewarm call before the pipeline kept the behavioral probe sandbox responsive.
3. **Forced done after dispatch.** After successful pre-selected write dispatch, the model kept proposing additional writes, causing `causal_review_blocked` on subsequent attempts. A 20-line fix forces the next action to `done` after dispatch, so the post-write gate runs and the pipeline terminates cleanly.

### What this establishes

1. **Composite autonomous repair works.** When the pipeline is supplied with a candidate that passes the pre-gate, NOVA completes the full task end-to-end: exploration, hypothesis, review, dispatch, post-write verification, and completion — with no human intervention after the candidate is injected.
2. **The hardened 11-case acceptance gate works live.** All 11 acceptance probes ran against the final workspace and passed. This closes Finding A at the live-pipeline level, not only at the offline level.
3. **The probe-schema fix was decisive.** The gate now executes; prior attempts blocked at the probe-schema step.
4. **The forced-done exit condition was the last missing piece.** The pipeline can now complete after successful dispatch.

### What this does not establish

1. **9B from-scratch candidate generation.** Base rate remains 1/5. The candidate came from stage 1 (base 7B + v6 selection), not from the 9B controller.
2. **From-scratch end-to-end autonomy.** This is a composite architecture with two stages: candidate generation (external) and pipeline execution (9B). Both are autonomous within their stage, but the pipeline does not yet generate its own candidate.
3. **General reliability.** One task, one seed, one candidate. Small-sample demonstration.
4. **That V5 or v6 alone would suffice.** The success is from a specific candidate produced by stage 1 on the specific starter. Whether this candidate selection process works on unseen starters remains the portfolio hypothesis from Finding F (exploratory).

### Every pipeline layer fired correctly

For the first time in the arc, every layer fired correctly in a single run:

| Layer | Status |
|---|---|
| Planning / exploration | read_file / list_files succeeded |
| Pre-selected substitution | step 2 |
| Hypothesis test | PREDICTION_MATCHED |
| Causal review | APPROVE on correct target |
| Syntax gate | implicit in dispatch |
| Write dispatch | 922 chars written |
| Post-write gate | 11/11 probes passed |
| Forced done | after dispatch |
| Stop reason | completed |
| Independent 11-case gate | 11/11 |
| Parity N=0–12 | PASS |
| Hidden tests | 6/6 |

### Arc status

**The CFD-001 arc is closed with a bounded positive end-to-end result.**

The pipeline is functional, the hardened gate works live, and composite autonomous repair has been demonstrated once, on one task, with an externally supplied candidate.

The two capabilities the pipeline now has:
- **Composite autonomous repair** given a correct candidate (this finding)
- **Candidate generation** via the base 7B + v6 portfolio, performed in a separate stage (Finding F, exploratory)

What remains untested for future arcs:
- Moving candidate generation inside the pipeline so the 9B controller can invoke the 7B portfolio as a tool, closing the last human-in-the-loop step
- End-to-end without pre-selection
- Multiple seeds / tasks to establish reliability
- Capability preservation across portfolio expansion

The immediate next milestone for a future arc: end-to-end with the pipeline generating its own candidate via the base+v6 portfolio internally, rather than requiring pre-selection injection.

### Preservation

All artifacts preserved:
- Trial directory: `end-to-end-20261113-141001` (in `nova-eval-lab/`)
- Workspace with repaired `tokenizer.py` and unchanged `parser.py`
- `memory.sqlite3` with full transcript
- `result.json` with all hashes, outcome, loop.py SHA at run time
- Adapter SHA: `59366286026e…` (v6 candidate)
- `loop.py` SHA at run time: `86b71324fa1913870aec4f0a0567ecdb51b5e59708bdec429a7e251b6e1c7f59`

