# Task task_001 — DISCARDED

- [x] Bug reproduces on baseline (3 failed)
- [x] Hidden tests pass after human patch
- [x] GOLD arm passes (11.1s, 4 steps)
- [x] **arm A passes WITHOUT skill** (16.1s, 7 steps) → task too easy

Reason: Qwen 4B Q4 knows range(n)→range(1,n+1) from training. Skill
contributes nothing. Additional flaw: original "gold skill" dictated
the code change instead of a diagnostic method.

Replaced by: task_002