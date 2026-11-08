# NOVA-Budget: The Economics of Procedural Memory in 4B Models

## Abstract
We investigated the economic viability of extracting procedural skills from verified experiences and injecting them into future tasks. While procedural abstraction is significantly more token-efficient than raw experience replay, it is still more expensive than using no memory at all. For highly capable small models on explicitly documented tasks, memory injection is a net-negative for token consumption.

## 1. Experimental Infrastructure and Token-Accounting Validation
We built an autonomous agent with strict SQLite provenance tracking. 
- **Ledger Integrity:** Every model request (including failed requests) is logged in a `model_calls` table. 
- **Reconciliation:** Aggregate run tokens perfectly match the sum of individual `model_calls` (15/15 runs reconciled).
- **Error Handling:** Missing token usage is recorded as `NULL`, never fabricated zeroes.

## 2. Protocol-X Pilot and Infrastructure Fix
During initial testing, a baseline failure was traced to a bug in the agent's `list_files` path resolution, not a model capability issue. This tool bug caused the model to enter an infinite loop. 
- **Fix:** The tool was updated to resolve absolute paths correctly, and a regression test was added.
- **Lesson:** Rigorous trace auditing prevented the publication of a false "breakthrough" result.

## 3. AuthSystem Lifecycle Economics (Post-Fix)
- **Acquisition:** Qwen 3.5 4B Q4 solved a Protocol-X task (2,490 tokens).
- **Extraction:** A separate LLM call extracted a generalizable diagnostic procedure (2,614 measured tokens, plus one unmeasured `client_unpack_error` attempt).
- **Deployment:** 5 seeds evaluated on a held-out task (`auth_system`).

### Results (5 Matched Seeds)

| Arm | Condition | Success | Mean Steps | Mean Total Tokens | Overhead |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A** | No Memory | 5/5 (100%) | 3.0 | **2,460.8** | Baseline |
| **C** | Raw Experience | 5/5 (100%) | 3.2 | **5,832.6** | +137.0% |
| **D** | Learned Skill | 5/5 (100%) | 3.0 | **2,905.2** | +18.1% |

## 4. Economic Analysis
- **Abstraction is essential:** Raw traces add ~3,372 tokens per deployment. The model repeatedly processes the massive context window. The abstracted skill saves ~2,927 tokens compared to raw replay (a 50.2% reduction).
- **The Memory Tax:** Even with perfect abstraction, memory adds ~444 tokens of prompt overhead per deployment compared to no memory.
- **Break-Even:** Against raw experience, the extraction cost (2,614) is recovered in **0.89 deployments**. However, against the no-memory baseline, the skill cannot recover its cost via token savings because it costs more per run.

## 5. Limitations and Future Work
1.  **Capability Saturation:** Qwen 4B does not require memory to solve explicitly documented tasks.
2.  **Task Generalization:** AuthSystem and SignalRegistry share structural similarities. Future work requires genuinely novel task families.
3.  **Budget-Matched Baseline:** Future experiments must introduce an Arm B (extra reasoning time) with the exact same cumulative token budget as the memory conditions.
4.  **Ledger Correction:** The earlier `client_unpack_error` was a caller-side Python unpacking failure after an inference response was returned. The token cost of that specific request remains unknown and is recorded as `NULL`.

## Conclusions
The research contribution is no longer "can an agent extract a skill?" It is "when is a memory representation economically worth paying for?" For capable small models, memory is a tax that only pays off if it solves an otherwise unsolvable problem.