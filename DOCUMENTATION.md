# Municipal Value-Score System v2 — Complete Documentation

> **A Multi-Agent Pipeline for Municipal Project Prioritization**

---

## Table of Contents

1. [Introduction](#introduction)
2. [System Architecture](#system-architecture)
3. [Installation](#installation)
4. [Quick Start](#quick-start)
5. [Core Concepts](#core-concepts)
   - [Composite Value-Score](#composite-value-score)
   - [Agent Pipeline](#agent-pipeline)
   - [Human-in-the-Loop Workflow](#human-in-the-loop-workflow)
6. [Module Reference](#module-reference)
7. [Data Models](#data-models)
8. [Configuration](#configuration)
9. [Database Schema](#database-schema)
10. [API Reference](#api-reference)
11. [Examples](#examples)
12. [Troubleshooting](#troubleshooting)
13. [Contributing](#contributing)

---

## Introduction

The Municipal Value-Score System v2 is an AI-powered solution for municipal project prioritization. It builds on previous risk scoring with a **composite value-score** that balances multiple factors:

- **Risk Mitigation** — Safety and legal mandates
- **Citizen Benefit** — Population served per dollar
- **Urgency** — Time-sensitive exponential decay
- **Feasibility** — Agent-estimated, human-confirmable
- **Geographic Equity** — District fairness multiplier

The system uses a 3-agent pipeline built on the OpenAI Agents SDK to transform citizen issues into prioritized, scheduled municipal projects.

### Key Features

| Feature | Description |
|---------|-------------|
| **Composite Scoring** | 30% risk-compliance + 70% public value |
| **Hybrid Decisions** | Tiered for judgments, continuous for quantities |
| **Approve-with-Conditions** | Soft reservations with auto-expiry |
| **Equity Enforcement** | Soft defer, not hard block |
| **Smart Scheduling** | Greedy-first with CP-SAT escalation |
| **Audit Trail** | Agent vs. human provenance tracking |

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         INPUT LAYER                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Issues + Signals     Districts        Resources                     │
│  (citizen complaints)  (geographic)     (crews, budget)              │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      AGENT PIPELINE                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐  │
│  │   Formation     │    │   Governance    │    │   Scheduling    │  │
│  │     Agent       │───▶│     Agent       │───▶│     Agent       │  │
│  │                 │    │                 │    │                 │  │
│  │ Issues →        │    │ Budget          │    │ Resource        │  │
│  │ Project         │    │ Allocation      │    │ Assignment      │  │
│  │ Candidates      │    │                 │    │                 │  │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘  │
│                                                                      │
└────────────────────────────┬────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       OUTPUT LAYER                                   │
├─────────────────────────────────────────────────────────────────────┤
│  Project Candidates    Portfolio Decisions    Execution Schedule     │
│  (scored, ranked)      (approved/deferred)    (resource allocated)   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites

- Python 3.10 or higher
- OpenAI API key

### Steps

```bash
# 1. Clone the repository
git clone <repository-url>
cd city_gov_v2

# 2. Create virtual environment (recommended)
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Set up environment variables
echo "OPENAI_API_KEY=your-api-key-here" > .env
```

### Dependencies

| Package | Purpose |
|---------|---------|
| `openai-agents>=0.1.0` | OpenAI Agents SDK |
| `pydantic>=2.0.0` | Data validation |
| `ortools>=9.7.0` | CP-SAT constraint solver (optional) |
| `python-dotenv>=1.0.0` | Environment management |

---

## Quick Start

### Initialize and Run

```bash
# Initialize database with sample data and run pipeline
python run_pipeline.py --seed

# Run with existing data
python run_pipeline.py

# Reset outputs and re-run
python run_pipeline.py --reset

# Full reset with fresh sample data
python run_pipeline.py --seed --reset
```

### View Schedule

```bash
# Display the generated schedule
python show_schedule.py
```

---

## Core Concepts

### Composite Value-Score

The system uses a weighted composite score to rank projects:

```
composite_score = (
    0.15 × safety_tier_value
  + 0.15 × mandate_tier_value
  + 0.25 × benefit_score
  + 0.20 × urgency_score
  + 0.15 × feasibility_score
) × equity_multiplier
```

#### Component Breakdown

| Component | Weight | Type | Description |
|-----------|--------|------|-------------|
| **Safety** | 15% | Tiered | `{none: 0, moderate: 0.4, severe: 0.7, critical: 1.0}` |
| **Mandate** | 15% | Tiered | `{none: 0, advisory: 0.3, required: 0.7, court_ordered: 1.0}` |
| **Benefit** | 25% | Continuous | Population served per dollar, normalized |
| **Urgency** | 20% | Continuous | Exponential decay with floor |
| **Feasibility** | 15% | Hybrid | Agent-estimated, human-overridable |
| **Equity** | Multiplier | Continuous | ±12.5% based on district service ratio |

#### Urgency Decay Curve

The urgency score uses exponential decay (λ=0.02) with a floor of 0.1:

| Days Remaining | Urgency Score |
|----------------|---------------|
| 7 days | 0.87 |
| 30 days | 0.55 |
| 90 days | 0.17 |
| 180+ days | 0.10 (floor) |

*Half-life: ~35 days*

#### Equity Multiplier

Districts are classified by their service ratio relative to the city average:

| Service Ratio | Classification | Multiplier Effect |
|---------------|----------------|-------------------|
| < 0.6 | Underserved | Up to +12.5% |
| 0.6 – 1.4 | Average | Neutral |
| > 1.4 | Well-served | Up to −12.5% |

---

### Agent Pipeline

#### Agent 1: Formation Agent

**Purpose:** Transform raw citizen issues into scored project candidates.

**Inputs:**
- Open issues with signals (population affected, safety tier, etc.)
- District information for equity calculation

**Outputs:**
- Project candidates with:
  - Composite value-score
  - Individual score components
  - Feasibility estimates
  - Scope and resource requirements

**Tools Available:**
- `get_open_issues` — Fetch unprocessed issues
- `compute_value_score` — Calculate composite score
- `estimate_feasibility` — AI-powered feasibility assessment
- `create_project_candidate` — Save to database

---

#### Agent 2: Governance Agent

**Purpose:** Allocate quarterly budget across project candidates.

**Selection Phases:**

| Phase | Criteria | Budget Cap |
|-------|----------|------------|
| 1. Mandates | Required or court-ordered | 30% |
| 2. Urgent-Critical | High urgency + severe/critical safety | 20% |
| 3. Value-Ranked | Remaining by composite score | 50% |

**Decision Statuses:**

| Status | Meaning |
|--------|---------|
| `APPROVED` | Ready for scheduling |
| `APPROVED_WITH_CONDITIONS` | Needs human confirmation |
| `DEFERRED` | Pushed to next quarter |
| `REJECTED` | Not proceeding |
| `EXPIRED` | Auto-expired (14 days timeout) |

**Human Confirmation Triggers:**
- Estimated cost > $10M
- Safety tier is `severe` or `critical`

**Tools Available:**
- `get_project_candidates` — Fetch scored projects
- `get_remaining_budget` — Check available funds
- `check_equity_constraint` — Verify district fairness
- `make_decision` — Record approval/deferral

---

#### Agent 3: Scheduling Agent

**Purpose:** Assign resources and schedule approved projects.

**Solver Selection:**

| Condition | Solver |
|-----------|--------|
| ≤10 projects, ≤2 resource types | `GreedyScheduler` |
| ≤20 projects, loose deadlines | `GreedyWithRepairScheduler` |
| >20 projects or tight coupling | `CPSATScheduler` |

**Priority Calculation:**
```
effective_priority = priority_rank × (1 + 0.5 × urgency_score)
```

**Resource Reservation Types:**

| Type | Purpose |
|------|---------|
| `soft_allocated` | Tentative (unconfirmed projects) |
| `hard_allocated` | Confirmed projects |

**Tools Available:**
- `get_approved_projects` — Fetch projects to schedule
- `check_resource_availability` — Query resource calendar
- `run_scheduler` — Execute scheduling algorithm
- `save_schedule` — Persist task assignments

---

### Human-in-the-Loop Workflow

```
┌──────────────────────────┐
│  APPROVED_WITH_CONDITIONS │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│   SCHEDULED (tentative)   │
│   (soft reservations)     │
└────────────┬─────────────┘
             │
    ┌────────┴────────┐
    │                 │
    ▼                 ▼
┌─────────┐    ┌──────────┐
│CONFIRMED│    │ EXPIRED  │
│ (human) │    │(14 days) │
└────┬────┘    └────┬─────┘
     │              │
     ▼              ▼
┌─────────┐    ┌──────────┐
│ LOCKED  │    │ Released │
│(hard    │    │resources │
│reserve) │    │          │
└─────────┘    └──────────┘
```

Use the confirmation CLI to manage pending confirmations:

```bash
python -m municipal_agents.confirmation_cli
```

---

## Module Reference

### Project Structure

```
city_gov_v2/
├── SPECIFICATION_v1.md      # Full system specification
├── DOCUMENTATION.md         # This file
├── README.md                # Quick overview
├── requirements.txt         # Python dependencies
├── run_pipeline.py          # Main entry point
├── show_schedule.py         # Schedule viewer
├── database/                # SQLite database files
│   └── city_value.db
└── municipal_agents/        # Core package
    ├── __init__.py
    ├── config.py            # All configuration constants
    ├── database.py          # Schema and initialization
    ├── models.py            # Pydantic data models
    ├── scoring.py           # Composite value-score engine
    ├── context.py           # Shared agent context
    ├── formation_agent.py   # Agent 1: Issue → Project
    ├── governance_agent.py  # Agent 2: Budget allocation
    ├── scheduling_agent.py  # Agent 3: Resource scheduling
    ├── confirmation_cli.py  # Human confirmation interface
    └── pipeline.py          # Agent orchestration
```

### Module Descriptions

| Module | Purpose |
|--------|---------|
| `config.py` | Centralized configuration constants |
| `models.py` | Pydantic models for type-safe data handling |
| `scoring.py` | Composite value-score calculation engine |
| `database.py` | SQLite schema, initialization, CRUD operations |
| `context.py` | Shared context object passed to all agents |
| `formation_agent.py` | Formation Agent definition and tools |
| `governance_agent.py` | Governance Agent definition and tools |
| `scheduling_agent.py` | Scheduling Agent definition and tools |
| `pipeline.py` | Pipeline orchestration and execution |
| `confirmation_cli.py` | Command-line tool for human confirmations |

---

## Data Models

### Core Types

```python
# Tier types
SafetyTier = Literal["none", "moderate", "severe", "critical"]
MandateTier = Literal["none", "advisory", "required", "court_ordered"]
EquityTier = Literal["underserved", "average", "well_served"]
DecisionStatus = Literal["APPROVED", "APPROVED_WITH_CONDITIONS", "DEFERRED", "REJECTED", "EXPIRED"]
DeadlineStatus = Literal["ON_TRACK", "AT_RISK", "MISSED"]
```

### Input Models

```python
class Issue(BaseModel):
    """Raw citizen complaint or municipal issue."""
    issue_id: int
    title: str
    category: str
    description: Optional[str]
    source: str = "citizen_complaint"
    district_id: Optional[int]
    status: str = "OPEN"

class IssueSignal(BaseModel):
    """Quantified impact/risk metrics for an issue."""
    issue_id: int
    population_affected: int
    complaint_count: int
    safety_tier: SafetyTier
    mandate_tier: MandateTier
    estimated_cost: int
    urgency_days: int = 90
```

### Output Models

```python
class ScoreComponents(BaseModel):
    """Breakdown of composite score components."""
    safety_score: float        # [0, 1]
    mandate_score: float       # [0, 1]
    benefit_score: float       # [0, 1]
    urgency_score: float       # [0, 1]
    feasibility_score: float   # [0, 1]
    equity_multiplier: float   # [0.875, 1.125]
    composite_score: float
```

---

## Configuration

All configuration is centralized in `municipal_agents/config.py`:

### City Profile

```python
CITY_PROFILE = {
    "city_name": "Metroville",
    "population": 2_500_000,
    "quarterly_budget": 75_000_000,  # $75M
    "planning_horizon_weeks": 12,
}
```

### Scoring Weights

```python
SCORING_WEIGHTS = {
    "safety": 0.15,
    "mandate": 0.15,
    "benefit": 0.25,
    "urgency": 0.20,
    "feasibility": 0.15,
}
# Total: 1.0 (before equity multiplier)
```

### Tier Value Mappings

```python
TIER_VALUES = {
    "safety": {
        "none": 0.0,
        "moderate": 0.4,
        "severe": 0.7,
        "critical": 1.0,
    },
    "mandate": {
        "none": 0.0,
        "advisory": 0.3,
        "required": 0.7,
        "court_ordered": 1.0,
    },
}
```

### Urgency Configuration

```python
URGENCY_CONFIG = {
    "lambda": 0.02,      # Decay rate
    "floor": 0.1,        # Minimum score
}
```

### Equity Configuration

```python
EQUITY_CONFIG = {
    "bonus_cap": 0.125,           # Max +12.5% for underserved
    "penalty_cap": 0.125,         # Max -12.5% for well-served
    "underserved_threshold": 0.6, # Ratio < 0.6 = underserved
    "wellserved_threshold": 1.4,  # Ratio > 1.4 = well-served
}
```

---

## Database Schema

### Entity-Relationship Diagram

```
┌─────────────┐     ┌──────────────────┐     ┌────────────────────┐
│  districts  │     │     issues       │     │   issue_signals    │
├─────────────┤     ├──────────────────┤     ├────────────────────┤
│ district_id │◄────│ district_id (FK) │     │ issue_id (FK/PK)   │
│ name        │     │ issue_id (PK)    │◄────│ population_affected│
│ population  │     │ title            │     │ safety_tier        │
└─────────────┘     │ category         │     │ mandate_tier       │
                    │ status           │     │ estimated_cost     │
                    └────────┬─────────┘     │ urgency_days       │
                             │               └────────────────────┘
                             ▼
                    ┌──────────────────┐
                    │project_candidates│
                    ├──────────────────┤
                    │ project_id (PK)  │
                    │ issue_id (FK)    │
                    │ composite_score  │
                    │ feasibility_est  │
                    └────────┬─────────┘
                             │
                             ▼
                    ┌──────────────────┐     ┌────────────────────┐
                    │portfolio_decisions│    │ resource_calendar  │
                    ├──────────────────┤     ├────────────────────┤
                    │ decision_id (PK) │     │ resource_id (PK)   │
                    │ project_id (FK)  │     │ resource_type      │
                    │ decision         │     │ week_number        │
                    │ allocated_budget │     │ capacity           │
                    │ priority_rank    │     │ soft_allocated     │
                    └────────┬─────────┘     │ hard_allocated     │
                             │               └────────────────────┘
                             ▼
                    ┌──────────────────┐
                    │  schedule_tasks  │
                    ├──────────────────┤
                    │ task_id (PK)     │
                    │ project_id (FK)  │
                    │ start_week       │
                    │ end_week         │
                    │ deadline_status  │
                    │ resource_type    │
                    └──────────────────┘
```

### Core Tables SQL

```sql
-- Issues (input)
CREATE TABLE issues (
    issue_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    source TEXT DEFAULT 'citizen_complaint',
    district_id INTEGER REFERENCES districts(district_id),
    status TEXT DEFAULT 'OPEN',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Issue signals (input metrics)
CREATE TABLE issue_signals (
    issue_id INTEGER PRIMARY KEY REFERENCES issues(issue_id),
    population_affected INTEGER NOT NULL,
    complaint_count INTEGER DEFAULT 0,
    safety_tier TEXT CHECK(safety_tier IN ('none','moderate','severe','critical')),
    mandate_tier TEXT CHECK(mandate_tier IN ('none','advisory','required','court_ordered')),
    estimated_cost INTEGER NOT NULL,
    urgency_days INTEGER DEFAULT 90
);

-- Project candidates (Formation Agent output)
CREATE TABLE project_candidates (
    project_id INTEGER PRIMARY KEY,
    issue_id INTEGER REFERENCES issues(issue_id),
    title TEXT NOT NULL,
    scope TEXT,
    estimated_cost INTEGER,
    estimated_weeks INTEGER,
    required_crew_type TEXT,
    crew_size INTEGER,
    composite_score REAL,
    benefit_score REAL,
    urgency_score REAL,
    feasibility_estimate REAL,
    feasibility_confirmed BOOLEAN DEFAULT FALSE,
    feasibility_override REAL,
    equity_tier TEXT,
    created_by TEXT DEFAULT 'formation_agent',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Portfolio decisions (Governance Agent output)
CREATE TABLE portfolio_decisions (
    decision_id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project_candidates(project_id),
    decision TEXT CHECK(decision IN ('APPROVED','APPROVED_WITH_CONDITIONS','DEFERRED','REJECTED','EXPIRED')),
    allocated_budget INTEGER,
    priority_rank INTEGER,
    rationale TEXT,
    deadline_week INTEGER,
    requires_confirmation BOOLEAN DEFAULT FALSE,
    confirmation_deadline TIMESTAMP,
    confirmed_at TIMESTAMP,
    confirmed_by TEXT,
    decided_by TEXT DEFAULT 'governance_agent',
    decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Schedule tasks (Scheduling Agent output)
CREATE TABLE schedule_tasks (
    task_id INTEGER PRIMARY KEY,
    project_id INTEGER REFERENCES project_candidates(project_id),
    start_week INTEGER NOT NULL,
    end_week INTEGER NOT NULL,
    deadline_week INTEGER,
    deadline_status TEXT CHECK(deadline_status IN ('ON_TRACK','AT_RISK','MISSED')),
    slack_days INTEGER,
    resource_type TEXT,
    crew_assigned TEXT,
    status TEXT DEFAULT 'SCHEDULED',
    created_by TEXT DEFAULT 'scheduling_agent',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## API Reference

### Pipeline Functions

```python
from municipal_agents.pipeline import run_pipeline_sync, run_full_pipeline

# Synchronous execution
results = run_pipeline_sync(
    db_path="database/city_value.db",
    reset_data=False,
    seed_data=True,
)

# Async execution
import asyncio
results = asyncio.run(run_full_pipeline(
    db_path="database/city_value.db",
    reset_data=True,
    seed_data=True,
))
```

### Scoring API

```python
from municipal_agents.scoring import CompositeScorer, BenefitNormalizer

# Initialize scorer
normalizer = BenefitNormalizer.from_config()
scorer = CompositeScorer(benefit_normalizer=normalizer)

# Score individual components
safety = scorer.score_safety("critical")      # → 1.0
mandate = scorer.score_mandate("required")    # → 0.7
benefit = scorer.score_benefit(50000, 1000000)  # population/cost
urgency = scorer.score_urgency(30)            # → 0.55

# Compute composite score
components = scorer.compute_composite(issue_with_signal, feasibility=0.8)
print(f"Composite: {components.composite_score}")
```

### Database API

```python
from municipal_agents.database import (
    init_with_sample_data,
    get_open_issues,
    create_project_candidate,
    get_remaining_budget,
)

# Initialize database
init_with_sample_data("database/city_value.db")

# Query open issues
issues = get_open_issues(db_path)

# Create project
project_id = create_project_candidate(db_path, project_data)

# Check budget
remaining = get_remaining_budget(db_path)
```

---

## Examples

### Example 1: Running the Full Pipeline

```bash
# Start fresh with sample data
python run_pipeline.py --seed --reset

# Expected output:
# ============================================================
# PHASE 1: FORMATION AGENT
# ============================================================
# Processing 10 open issues...
# Created 10 project candidates with composite scores
#
# ============================================================
# PHASE 2: GOVERNANCE AGENT
# ============================================================
# Quarterly Budget: $75,000,000
# Phase 1 (Mandates): 2 projects approved ($8.5M)
# Phase 2 (Urgent-Critical): 1 project approved ($2.1M)
# Phase 3 (Value-Ranked): 5 projects approved ($42.3M)
# Deferred: 2 projects
#
# ============================================================
# PHASE 3: SCHEDULING AGENT
# ============================================================
# Scheduling 8 approved projects...
# Using GreedyScheduler (8 projects, 2 resource types)
# All projects scheduled within planning horizon
```

### Example 2: Adding a New Issue

```python
import sqlite3

# Connect to database
conn = sqlite3.connect("database/city_value.db")
cursor = conn.cursor()

# Insert new issue
cursor.execute("""
    INSERT INTO issues (title, category, description, district_id, status)
    VALUES (?, ?, ?, ?, 'OPEN')
""", (
    "Water main break on Oak Street",
    "infrastructure",
    "Major water main break causing flooding",
    3,
))
issue_id = cursor.lastrowid

# Add signals
cursor.execute("""
    INSERT INTO issue_signals 
    (issue_id, population_affected, complaint_count, safety_tier, mandate_tier, estimated_cost, urgency_days)
    VALUES (?, ?, ?, ?, ?, ?, ?)
""", (issue_id, 15000, 47, "critical", "required", 500000, 7))

conn.commit()
conn.close()

# Re-run pipeline to process new issue
# python run_pipeline.py
```

### Example 3: Custom Scoring Configuration

```python
# In config.py, adjust weights for different priorities:

# Risk-focused configuration
SCORING_WEIGHTS = {
    "safety": 0.30,      # Increased
    "mandate": 0.25,     # Increased
    "benefit": 0.15,     # Decreased
    "urgency": 0.20,     # Same
    "feasibility": 0.10, # Decreased
}

# Citizen-benefit focused configuration
SCORING_WEIGHTS = {
    "safety": 0.10,
    "mandate": 0.10,
    "benefit": 0.40,     # Heavily weighted
    "urgency": 0.25,
    "feasibility": 0.15,
}
```

---

## Troubleshooting

### Common Issues

#### 1. "OPENAI_API_KEY not found"

```bash
# Solution: Create .env file with your API key
echo "OPENAI_API_KEY=sk-..." > .env
```

#### 2. "No module named 'agents'"

```bash
# Solution: Install the OpenAI Agents SDK
pip install openai-agents
```

#### 3. Database locked error

```bash
# Solution: Close other connections or delete lock file
rm database/city_value.db-journal
```

#### 4. Scheduler infeasibility

If the scheduler reports infeasible projects:
- Check resource capacity in `resource_calendar` table
- Extend planning horizon in `config.py`
- Consider increasing crew capacity

#### 5. All projects deferred

Check the equity constraints:
```sql
SELECT d.name, COUNT(*) as projects_last_year
FROM portfolio_decisions pd
JOIN project_candidates pc ON pd.project_id = pc.project_id
JOIN issues i ON pc.issue_id = i.issue_id
JOIN districts d ON i.district_id = d.district_id
WHERE pd.decision = 'APPROVED'
GROUP BY d.district_id;
```

---

## Contributing

### Development Setup

```bash
# Clone and install in development mode
git clone <repository-url>
cd city_gov_v2
pip install -e ".[dev]"

# Run tests
pytest

# Format code
black municipal_agents/

# Type checking
mypy municipal_agents/
```

### Code Style

- Follow PEP 8 guidelines
- Use type hints for all function signatures
- Document all public functions with docstrings
- Keep modules focused and under 300 lines

### Pull Request Process

1. Create a feature branch from `main`
2. Make your changes with tests
3. Update documentation as needed
4. Submit PR with clear description
5. Address review feedback

---

## License

This project is licensed under the MIT License.

---

## Changelog

### v2.0.0 (Current)

- Complete rewrite with OpenAI Agents SDK
- Composite value-score replacing risk-only scoring
- 3-agent pipeline architecture
- Human-in-the-loop confirmation workflow
- Geographic equity enforcement
- Multiple scheduler strategies

### v1.0.0

- Initial risk-based prioritization system
- 3-agent pipeline architecture

---

*Documentation generated: December 2025*
*Municipal Value-Score System v2*
