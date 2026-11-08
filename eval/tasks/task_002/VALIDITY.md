# Task task_002 — validity gate

- [ ] Baseline agent (arm A) fails — verified_success = false
- [ ] Reference human patch passes hidden tests
- [ ] Hidden tests fail on pre-patch code, pass on post-patch code
- [ ] Task solvable within budget (record wall time)
- [ ] Hidden tests inaccessible to agent (harness-only)
- [ ] **Capability floor:** GOLD arm passes ≥40% of seeds

family: stability_violation
repo:   task_002
transfer_bucket: near
discard_if_failed_gate: yes

## Run log
A:    verified_success=____ steps=____ wall=____
GOLD: verified_success=____ steps=____ wall=____