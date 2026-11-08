# NOVA

Autonomous skill-learning research agent.

## Research question
Does an AI extract a reusable skill from a verified task, remember it, and apply it to a related unseen task?

## Setup
1. `python -m venv .venv`
2. `.venv\Scripts\Activate.ps1`
3. `pip install -e ".[dev]"`
4. `Copy-Item .env.example .env`
5. Start Ollama: `ollama serve`
6. Run tests: `pytest`

## Structure
- `src/nova/` — agent source
- `eval/tasks/` — benchmark tasks
- `eval/harness/` — experiment runner
- `eval/analysis/` — statistical analysis
- `migrations/` — SQL schema
- `docs/` — protocol, threat model, references