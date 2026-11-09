# NOVA Reproducibility and Artifact Status

**Audit date:** 9 November 2026

This document records the state of the experiment artifacts, database
recovery, and known provenance limitations. Missing measurements are
reported as unavailable, not treated as zero.

## 1. NOVA-Genesis 2: JSON Schema

The report is committed at `docs/results_json_schema.md`.

The ten run-level JSON artifacts are now committed under
`eval/results/nova_json_schema_*_seed*_20261109.json`.

They contain five matched seeds for each arm:

- `V0_NOECHO_THINK_OFF`: unconstrained generation.
- `V0_JSON_SCHEMA`: flat JSON Schema constrained generation.

The five-seed comparison and its limitations are described in the
experiment report. The archived artifacts include run IDs, token totals,
step counts, verification results, and generation provenance fields.

The reported local audits passed for all ten runs. Seed 0 and seed 1
malformed-response counts were explicitly inspected; the final audit
outputs for seeds 2-4 did not explicitly print malformed-response counts.

**Code limitation:** the experimental controller and harness changes
(`src/nova/controller/loop.py`, `eval/harness/runner.py`, and
`tests/test_controller.py`) were still uncommitted on the local
`experiment/json-schema-actions` branch at the time of this audit.
The raw results are archived on `main`, but the exact experimental code
patch is not yet part of the `main` branch.

## 2. AuthSystem: recovered complete five-seed export

The original committed file
`eval/results/auth_system_replication_20261108.json` contains 12 records.
It omits the three seed-0 records.

The local SQLite database contains all 15 original AuthSystem runs:
five seeds for each of arms A, C, and D.

The supplementary file
`eval/results/auth_system_replication_20261108_complete15.json`
contains the reconstructed 15-run dataset and 46 individual model-call
records. Each run passed independent verification. All model-call usage
records were complete, and per-run prompt, completion, and total token
sums reconciled with the database run totals.

Recovered five-seed summaries:

| Arm | Verified | Mean steps | Mean tokens |
|---|---:|---:|---:|
| A ? No memory | 5/5 | 3.0 | 2,460.8 |
| C ? Raw experience | 5/5 | 3.2 | 5,832.6 |
| D ? Learned skill | 5/5 | 3.0 | 2,905.2 |

**Prompt provenance limitation:** the database does not contain the
original system-prompt hash for these 15 records. The recovered export
therefore leaves `system_prompt_sha256` unavailable rather than
reconstructing it from an assumption.

## 3. Protocol-X: pre-fix and post-fix comparisons

The following two files each contain 15 run summaries:

- `eval/results/protocol_x_signal_registry_20261108.json`
- `eval/results/protocol_x_signal_registry_postfix_20261108.json`

The pre-fix no-memory arm passed 3/5 runs; raw experience and learned
skill each passed 5/5. After the `list_files` path-resolution fix, all
three arms passed 5/5.

This pattern is consistent with the tool defect contributing to the
earlier no-memory failures. It does not prove that memory had no effect:
the before/after runs were sequential rather than a randomized,
concurrent causal comparison.

The Protocol-X comparison files record success, steps, and wall time.
They do not contain per-run token counts.

The database confirms that all 30 comparison run records have NULL
run-level prompt, completion, and total token fields, with
`usage_complete = 0`. No `model_calls` rows are linked to those 30 runs.
Their comparison-arm token usage is therefore unavailable and cannot
be reconstructed from the current database.

A separate source acquisition run
`5a8ac88a-c895-4c7a-acba-c0d255c5f053` has six linked model-call rows
summing to 5,104 tokens, while its run-level total is 2,490 tokens.
The research report separately records 2,490 tokens for acquisition
and 2,614 for successful skill extraction. The database association
does not cleanly distinguish those costs. These six calls must not be
assigned to the 30 comparison runs.

## 4. Interpretation boundaries

The available evidence supports the following statements:

- The Protocol-X baseline success rate improved after the tool fix.
- The earlier difference between memory and no-memory arms is
  consistent with infrastructure masking.
- The observations do not prove that memory had no causal effect.
- Protocol-X comparison-arm token efficiency cannot be evaluated from
  the archived records.
- AuthSystem run and call accounting can be reconstructed, but the
  original prompt hashes are not present in the database.
- JSON Schema raw results are archived, but the exact experimental
  controller patch still needs a reviewed, versioned commit.

No missing token values, prompt hashes, or model-call records have
been fabricated or imputed.

## 5. Reproduction status

The recovered AuthSystem export and the ten JSON Schema artifacts
preserve run-level evidence. The Protocol-X files preserve outcomes
and execution metadata but not token accounting.

For full code-level reproduction, the exact JSON Schema controller
and harness changes must also be reviewed and committed as a versioned
source change, with a Git SHA recorded in a subsequent experiment.
