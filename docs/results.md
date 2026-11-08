# NOVA Capability Screen — Final Report

**Date:** 2026-11-08
**Model:** Qwen 3.5 4B Q4_K_M (Ollama 0.40.15)
**Hardware:** RTX 3070 Laptop GPU (8 GB VRAM), 15.7 GB RAM, Windows 10 Home
**Temperature:** 0.2
**Seed propagation:** verified via `test_chat_sends_seed`

## Research question

Does procedural skill injection (retrieval of previously learned
procedures) improve task success on software bug-fixing tasks, for a
4B-parameter code model?

## Method

Four synthetic Python bug-fixing tasks. Each task:

- has a buggy repo with a documented contract
- has hidden pytest tests that verify the contract
- runs through the NOVA agent (plan → act → observe → done)
- is verified independently by a harness that runs pytest in a clean
  temp directory (agent never sees hidden tests)

Arm A (no skill) is the baseline. GOLD (gold skill injected) is the
capability floor check.

## Results

| Task | Bug class | Pre-run | Arm A | Notes |
|---|---|---|---|---|
| task_001 | off-by-one loop bound | 3 failed | 1/1 passed (7 steps, 16s) | discarded |
| task_002 | merge-sort stability | 2 failed | 1/1 passed (3 steps, 43s) | discarded |
| scan_config | multi-file config | 2 failed | 7/7 passed (5 seeds + 2 reruns) | discarded |
| scan_state | state management | 3 failed | 5/5 passed (3 steps, avg 15s) | discarded |

All tasks reproduced their bugs on baseline code. Arm A never failed.

## Interpretation

Qwen 3.5 4B Q4 solved every tested bug class without any skill
injection. Standard single-file, multi-file, and stateful Python
bug fixes appear to be within this model's existing capability.

We cannot measure skill-transfer effects on tasks where the baseline
already succeeds at 100%. There is no capability gap to close and no
reliability gap to exploit.

**Important distinction:** we have not shown that skills do not help.
We have shown that these specific tasks provide insufficient baseline
headroom for measuring an improvement. The finding is about the
benchmark, not about the mechanism.

## What this rules out

- Skill injection as a mechanism to improve success rate on standard
  Python bugs, for this model on these task classes.
- Reliability-improvement framing on tasks where baseline is already 5/5.

## What this does not rule out

- Harder bug classes (async/concurrency, regex edge cases, domain-
  specific parsers, multi-file with misleading error locations).
- Larger models where capability may not be saturated.
- Skills as a mechanism for cost reduction (fewer steps, fewer tokens)
  even when success rate is unchanged.
- Transfer effects in non-coding domains.
- Cross-domain procedural transfer.

## Artifacts produced

- **Agent:** plan → act → observe → done loop, sandboxed file ops,
  seed propagation end-to-end.
- **Harness:** independent verification via temp-dir pytest; agent
  never sees hidden tests.
- **Memory schema:** SQLite (episodes, skills, runs, retrieval_log).
- **Benchmark tasks:** 4 tasks with validity gates.
- **Tests:** 22 passing unit tests.
- **Protocol:** 6-arm design specified (A/B′/C′/D/E/F) with pre-
  registration parameters, held in `research_protocol.md`.

## Recommendation

Before continuing, the research question needs an environment where
learning can demonstrably matter. Options:

**Option A — Cross-domain transfer.** Learn a procedure in one
environment (e.g., CSV parsing) and test whether it helps in a
structurally different environment (e.g., log parsing). Requires a new
benchmark and a literature review.

**Option B — Evidence-based transfer.** Test whether learned procedures
improve decisions when task descriptions are incomplete, environment
assumptions change, or multiple procedures compete. Requires new task
design.

**Option C — Accept and archive.** Record the negative result.
Contribute the harness and benchmark design to open source. Return to
the project when a stronger research question is identified.

Do not continue scanning Python bug classes. The signal is clear.