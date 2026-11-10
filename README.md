# NOVA

**NOVA — Local Autonomous Coding and Research Agent**

NOVA is an experimental local autonomous agent focused on reliable task execution, structured planning, tool use, failure recovery, memory research, and measurable improvement.

It runs locally using Ollama-compatible language models.

## Core Capabilities

### Runtime Reliability
- Declarative action contracts and input validation.
- Structured model responses.
- Durable action execution journal.
- Execution identifiers and idempotency keys.
- Failure fingerprints and repeated-failure detection.
- Runtime locking and interrupted-run recovery.
- Atomic file operations.

### Structured and Adaptive Planning
- Structured initial execution plans.
- Observable completion criteria.
- Failure-informed plan revisions.
- Bounded replanning.
- Persistent plan history.
- Tool-aware planning using actual controller capabilities.

Current controller actions:
- `write_file`
- `read_file`
- `list_files`
- `done`

Planning is optional. A plan or completion message is not proof of success.

## NOVA-EVAL 0.1

NOVA-EVAL is an experimental benchmark for measuring autonomous software-task performance.

It includes:
- Versioned task packages and manifests.
- Known starter implementations and reference solutions.
- Independent hidden-test verification.
- File integrity and provenance checks.
- Repeatability and deterministic scoring.
- Evaluation isolation and resource controls.

Initial task families cover read-only tasks, failed writes, incorrect writes,
wrong-file edits, multi-step completion, tool recovery, infeasible tasks,
and safety constraints.

Not all proposed validity gates have been completed.

## Docker Sandbox

The evaluation sandbox implements:
- Network isolation.
- Read-only container filesystem.
- Non-root execution.
- Dropped Linux capabilities.
- Resource and execution-time limits.
- Bounded output and container cleanup.

Host isolation and hidden-test confidentiality are separate requirements.
Running hidden tests beside untrusted candidate code does not keep their
source confidential.

## Experimental Findings

### Qwen 3.5
The repository contains Qwen 3.5 4B and 9B comparisons and earlier
controller-reliability experiments. Results are task-specific.

### Adaptive Planning Pilot
Controlled 4B experiments tested recovery from an injected transient
write failure.

The tool-aware planning treatment successfully generated an accepted
revision in the later pilot. NOVA retried the supported write action,
read the file, and passed independent verification.

### Missing-Path Recovery
Both baseline and planning-enabled NOVA recovered from missing file paths
using `list_files` and `read_file`.

Planning did not improve success on these tasks and consumed substantially
more model tokens.

These experiments have small samples and do not establish general
intelligence or broad performance gains.

### Research Interpretation
- A successful model API call is not necessarily a valid plan revision.
- A valid plan is not proof that the agent followed it.
- Repeating an action can be correct after a transient failure.
- Baseline agents can already recover effectively.
- Independent verification is essential.
- Token cost and task success must be measured together.
