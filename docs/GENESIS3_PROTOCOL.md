# NOVA-Genesis 3: Failure Attribution and Remediation Selection

**Protocol:** G3-FA-01
**Status:** Pre-registered; no model trials run yet
**Date:** 9 November 2026

## Research question

Does adding trusted source-attribution metadata to a tool exception change
the remediation target selected by a small local model?

## Hypothesis

When given the same tool failure, a model that receives explicit,
trusted metadata identifying the failure as originating in the tool
runtime will more often select TOOL_REPAIR than a model receiving only
the ordinary error observation.

## Scope

This is a narrow test of the effect of source-attribution metadata on
downstream remediation selection. It is not a test of whether the model
can independently discover the failure source, and it is not a test of
automatic tool repair.

## Fault fixture

Use a test-only reproduction of the historical list_files path bug:
an absolute file path is made relative to a relative workspace path.
The fixture must raise ValueError before any model trial starts.

Production file_ops.py must not be modified or regressed.

## Conditions

A — CONTROL:
The model receives the ordinary error observation, including the
requested list_files action and ValueError message.

B — ATTRIBUTION:
The model receives the identical observation plus trusted metadata:
failure_origin=tool_runtime
component=nova.tools.file_ops.list_files

The metadata is the only intended difference between arms.

## Model decision

The model must return exactly one label:

- TOOL_REPAIR
- TASK_CODE_REPAIR
- PROMPT_CHANGE
- RETRY_ACTION
- UNSURE

The pre-registered correct decision for this injected fault is
TOOL_REPAIR.

The model is asked to select a remediation target only. It must not
write files, execute repairs, or modify the NOVA installation.

## Trial design

- Model: qwen3.5:4b through the local Ollama endpoint.
- Runtime: record the exact installed Ollama version at execution.
- Temperature: use the configured NOVA temperature and record it.
- Seeds: 0, 1, 2, 3, 4 in both arms.
- Total: 10 one-shot model calls.
- No memory injection.
- No JSON Schema constraint.
- No retries, prompt tuning, or manual intervention between calls.
- Alternate arm order by seed to reduce order effects.
- Preserve raw outputs and complete token usage for every call.

A seed is a repeated trial setting, not a guarantee of deterministic
generation across every runtime configuration.

## Outcomes

Primary endpoint:
- Number of runs selecting TOOL_REPAIR in each arm, out of five.

Secondary endpoints:
- Exact output validity.
- Other remediation labels selected.
- Prompt, completion, and total tokens.
- Wall-clock duration.
- Whether model usage accounting is complete.

Report all ten raw outputs. Do not exclude inconvenient responses.

## Interpretation

If B selects TOOL_REPAIR more often than A, the result supports the
limited claim that trusted source-attribution metadata can influence
remediation selection in this setup.

It does not establish that a general-purpose failure classifier is
accurate, that the model learned a new capability, or that the selected
repair will succeed.

If both arms behave identically, the metadata showed no observed
decision benefit in this small pilot.

Five trials per arm are exploratory. Do not claim statistical
significance or generalization from this sample.

## Stop conditions

- If the test fixture does not reproduce the intended ValueError,
  do not run model trials.
- If any model call has incomplete token usage, preserve the run and
  mark its accounting incomplete.
- Do not modify production tools until the ten diagnostic responses
  have been recorded and reviewed.
