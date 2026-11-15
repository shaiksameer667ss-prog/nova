# NOVA Research Roadmap

Programme: NOVA Intelligence Lab
Status: Proposed research roadmap

## Guiding objective

Move NOVA towards increasingly general intelligence by conducting controlled research into reasoning, learning, world models, autonomous discovery and validated self-improvement.

Progress is determined by demonstrated capability, not by completion of a feature list.

## Stage 0 — Research foundation

Objectives:
- Record current architecture and limitations.
- Preserve existing NOVA-EVAL work.
- Inventory model, controller and evaluation capabilities.
- Establish reproducible experiment provenance.
- Separate development, validation and held-out data.

Exit criteria:
- Current baseline can be identified and reproduced.
- Experiment configurations and artifacts are versioned.
- Evaluation limitations are documented.
- Existing regression tests remain passing.

## Stage 1 — Intelligence Evaluation Lab

Research:
- General reasoning.
- Multi-step planning.
- Causal prediction.
- Learning from feedback.
- Transfer to unfamiliar tasks.
- Memory and retention.
- Tool use and recovery.
- Scientific problem-solving.

Deliverables:
- Versioned intelligence benchmark.
- Independent task verifiers.
- Experimental protocol.
- Baseline capability report.
- Domain-level scorecard.

Exit criteria:
- Tasks have independent ground truth.
- Development and held-out evaluation are separated.
- Baseline results are reproducible.
- Metrics include accuracy, cost, time and failures.

## Stage 2 — Advanced reasoning and search

Research:
- Structured decomposition.
- Adaptive planning.
- Multiple candidate generation.
- Search over alternative solutions.
- Independent verification.
- Uncertainty estimation.
- Adaptive test-time computation.

Experiments must compare each treatment against the existing controller under matched tasks, models and budgets.

Exit criteria:
- Improvements on held-out tasks.
- No unacceptable regression in existing capabilities.
- Cost and latency trade-offs reported.
- Results reproduced.

## Stage 3 — Continual learning and transfer

Research:
- Episodic memory.
- Semantic consolidation.
- Procedural skill acquisition.
- Learning from successful and failed attempts.
- Retrieval and relevance.
- Knowledge transfer.
- Continual adaptation.
- Forgetting and capability interference.

Exit criteria:
- Learned knowledge improves future tasks.
- Transfer is measured on unfamiliar tasks.
- Retention and negative interference are reported.
- Baseline capabilities are preserved within defined tolerances.

## Stage 4 — World models and causal reasoning

Research:
- Predictive environment representations.
- Causal dependency models.
- State transition prediction.
- Counterfactual reasoning.
- Simulation and planning under uncertainty.
- Model calibration and prediction error.

Exit criteria:
- Predictions are compared against observed outcomes.
- Causal claims have appropriate experimental evidence.
- Uncertainty and model failure are measured.

## Stage 5 — Controlled self-evolution

Research:
- Candidate architecture generation.
- Prompt and policy evolution.
- Algorithm improvement.
- Search over reasoning strategies.
- Automated experiment selection.
- Regression-aware version retention.

Every candidate must run in an isolated environment.

The candidate must not modify trusted evaluators, hidden tests, access policies or the acceptance criteria used to evaluate it.

Exit criteria:
- Improvements beat the incumbent on held-out tasks.
- Comparisons use matched resource budgets.
- Multiple independent reruns are completed.
- Regressions and rejected candidates are preserved.
- Rollback is possible.

## Stage 6 — Scientific discovery

Research:
- Research question generation.
- Literature-grounded hypotheses.
- Experiment design.
- Automated analysis.
- Independent replication.
- Discovery validation.
- Knowledge publication and provenance.

Exit criteria:
- Results are reproducible.
- Hypotheses are distinguished from findings.
- Independent verification supports published claims.

## Stage 7 — Multimodal and interactive intelligence

Research:
- Vision and document understanding.
- Audio and language.
- Interactive environments.
- Spatial and temporal reasoning.
- Tool and computer interaction.
- Robotics research where appropriate.

Exit criteria:
- Capabilities are independently evaluated in each environment.
- Safety and authorization are validated for the relevant action space.

## Stage 8 — Original model research

Research:
- Open-weight model adaptation.
- Fine-tuning.
- Distillation.
- Reinforcement learning.
- Continual model adaptation.
- Original foundation-model research.

Decisions must consider compute, data, expertise, reproducibility and expected research value.

No assumption is made that current resources are sufficient for frontier-scale model training.

## Promotion rules

A candidate is not promoted because it:
- Produces more reasoning tokens.
- Uses more agents.
- Sounds more confident.
- Performs better on development examples only.
- Passes a benchmark it has seen during tuning.

Promotion requires independently verified held-out improvement with acceptable safety, reliability and resource trade-offs.

No stage completion establishes AGI or superintelligence.
