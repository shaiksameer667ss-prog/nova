# NOVA Finding 6: Infrastructure Failures Can Masquerade as Model Limitations

## Observation

During NOVA's Protocol-X experiments, the pre-fix no-memory baseline achieved 3/5 independently verified successes. The raw-experience and learned-skill arms each achieved 5/5.

Investigation identified a path-resolution defect in NOVA's `list_files` tool. The defect caused `ValueError` exceptions when absolute file paths were evaluated relative to a relative workspace path.

A test-only diagnostic fixture reproducing the legacy path-resolution logic successfully reproduces the same `ValueError`.

After correcting the path handling, the no-memory baseline achieved 5/5 success. Both memory arms also achieved 5/5.

## Interpretation

The earlier difference between memory and no-memory performance was consistent with an infrastructure failure affecting the baseline agent.

These results demonstrate why tool correctness must be established before attributing agent failures to model reasoning or evaluating memory-based improvements.

They do not establish that memory had no effect. The pre-fix and post-fix experiments were sequential, and the comparison does not isolate the tool correction through randomized causal controls.

## Engineering Implication

NOVA should validate tool behavior and distinguish tool/runtime failures from model-output and task-reasoning failures before attempting prompt modification, memory extraction, or model retries.

A failed agent execution is not necessarily evidence of a failed reasoning process.

## Evidence

- `eval/results/protocol_x_signal_registry_20261108.json`
- `eval/results/protocol_x_signal_registry_postfix_20261108.json`
- `eval/diagnostics/reproduce_list_files_failure.py`
- `tests/test_file_ops.py`
- `docs/REPRODUCIBILITY.md`

Pre-fix and post-fix comparison-arm token usage is unavailable and is not used in this finding.

## Limitation

The before/after comparison is observational rather than a randomized causal experiment. It supports infrastructure masking as a plausible explanation for the earlier performance difference, but does not prove that the tool defect was the only contributing factor.

## Conclusion

**Agent performance is a property of the model-controller-tool system, not the model alone.**

Infrastructure validation is a prerequisite for credible claims about agent intelligence, memory, and self-improvement.
