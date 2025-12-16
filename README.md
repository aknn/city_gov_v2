# Municipal Value-Score System v2

A multi-agent pipeline for municipal project prioritization using composite value-scoring.

## Overview

This system replaces risk-only scoring with a **composite value-score** that balances:
- Risk mitigation (safety, legal mandates)
- Citizen benefit (population served per dollar)
- Urgency (exponential time decay)
- Feasibility (agent-estimated, human-confirmable)
- Geographic equity (district fairness multiplier)

## Architecture

```
Issues + Signals → [Formation Agent] → Project Candidates
                         ↓
                   [Governance Agent] → Portfolio Decisions
                         ↓
                   [Scheduling Agent] → Execution Schedule
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Initialize database with sample data
python -m municipal_agents.database

# Run the full pipeline
python run_pipeline.py
```

## Project Structure

```
city_gov_v2/
├── SPECIFICATION_v1.md      # Full system specification
├── README.md
├── requirements.txt
├── run_pipeline.py          # Pipeline entry point
├── database/                # SQLite database
└── municipal_agents/
    ├── __init__.py
    ├── config.py            # All configuration constants
    ├── database.py          # Schema and initialization
    ├── models.py            # Pydantic data models
    ├── scoring.py           # Composite value-score engine
    ├── context.py           # Shared agent context
    ├── formation_agent.py   # Agent 1: Issue → Project
    ├── governance_agent.py  # Agent 2: Budget allocation
    ├── scheduling_agent.py  # Agent 3: Resource scheduling
    └── pipeline.py          # Agent orchestration
```

## Key Features

- **Composite scoring**: 30% risk-compliance, 70% public value
- **Hybrid scoring**: Continuous for quantities, tiered for judgments
- **Approve-with-conditions**: Soft reservations, auto-expiry
- **Equity enforcement**: Soft defer, not hard block
- **Greedy-first scheduling**: CP-SAT as escalation path
- **Structured audit trail**: Agent vs. human provenance

## Documentation

See [SPECIFICATION_v1.md](SPECIFICATION_v1.md) for complete system design.

## License

MIT
