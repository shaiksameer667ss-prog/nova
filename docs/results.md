# NOVA: Procedural Transfer and Inference Efficiency in 4B Models

## Abstract
We investigated whether Qwen 3.5 4B Q4 could extract a reusable procedural skill from a verified execution trace and apply it to a structurally identical task in a different domain.

In a controlled, post-fix pilot involving five matched random seeds, both raw experiential memory and an extracted procedural skill achieved 100% verified task success and reduced mean agent-loop interactions from four to three relative to a no-memory baseline. However, procedural abstraction did not improve interaction efficiency over raw experience. The learned-skill condition also had higher descriptive wall-clock time. These results provide preliminary evidence of memory-assisted interaction efficiency, but do not establish a statistically significant advantage for procedural abstraction.

## Methodology
- **Acquisition:** NOVA solved a task (`parcel_pipe`) containing an arbitrary security rule, and its execution trace was independently verified.
- **Extraction:** A separate LLM call extracted a generalizable diagnostic procedure.
- **Deployment:** NOVA was given a new task (`signal_registry`) in a different domain with the same underlying rule.
- **Evaluation:** 5 seeds each for Baseline (A), Raw Experience (C), and Learned Skill (D).

## Results (Clean Post-Fix Dataset)

| Arm | Memory | Success | Avg Steps | Step Variance | Avg Time |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A** | None | 5/5 (100%) | 4.0 | 3 to 5 | 13.9s |
| **C** | Raw Trace | 5/5 (100%) | **3.0** | **0 (Exactly 3)** | **12.1s** |
| **D** | Learned Skill | 5/5 (100%) | **3.0** | **0 (Exactly 3)** | 15.6s |

## Conclusions
1. **Capability Saturation:** Qwen 4B does not require external memory to solve out-of-distribution logic tasks when the source code is clear.
2. **Variance Reduction:** Memory turns an erratic problem-solving process (3-5 steps) into a perfectly deterministic one (3 steps).
3. **Abstraction Penalty:** Raw execution traces (Arm C) are faster and just as accurate as abstracted procedural skills (Arm D), suggesting small models benefit more from concrete code context than abstract rules.
4. **Infrastructure Confound:** A path-resolution bug in the `list_files` tool initially caused a false positive (60% baseline). Rigorous audit of execution traces caught the error, proving the importance of verifiable infrastructure.