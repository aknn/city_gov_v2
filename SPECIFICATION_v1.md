# Municipal Value-Score System — Consolidated Specification

---

## 1. System Overview

A 3-agent pipeline for municipal project prioritization that replaces risk-only scoring with a **composite value-score** balancing risk mitigation, citizen benefit, urgency, feasibility, and geographic equity.

**Agent Pipeline:**
```
Issues + Signals → [Formation Agent] → Project Candidates
                         ↓
                   [Governance Agent] → Portfolio Decisions
                         ↓
                   [Scheduling Agent] → Execution Schedule
```

---

## 2. Composite Value-Score

### 2.1 Formula
```
composite_score = (
    0.15 × safety_tier_value
  + 0.15 × mandate_tier_value
  + 0.25 × benefit_score
  + 0.20 × urgency_score
  + 0.15 × feasibility_score
) × equity_multiplier
```

### 2.2 Component Definitions

| Component | Type | Calculation |
|-----------|------|-------------|
| **Safety** (15%) | Tiered | `{none: 0, moderate: 0.4, severe: 0.7, critical: 1.0}` |
| **Mandate** (15%) | Tiered | `{none: 0, advisory: 0.3, required: 0.7, court_ordered: 1.0}` |
| **Benefit** (25%) | Continuous | `clamp((pop_affected / cost) / blended_median, 0, 1)` |
| **Urgency** (20%) | Continuous | `max(0.1, e^(-0.02 × days_remaining))` |
| **Feasibility** (15%) | Hybrid | Agent-estimated (0–1), human-confirmable |
| **Equity** | Multiplier | `1 + 0.25 × clamp(1 - service_ratio, -0.5, 0.5)` |

### 2.3 Urgency Decay Curve (λ=0.02, floor=0.1)

| Days Remaining | Score |
|----------------|-------|
| 7 | 0.87 |
| 30 | 0.55 |
| 90 | 0.17 |
| 180 | 0.10 (floor) |

Half-life ≈ 35 days.

### 2.4 Benefit Normalization (Bayesian Bootstrap)

**Phase 0 (Cold Start):**
```python
prior_median = city_population / (quarterly_budget / avg_project_count)
prior_strength = 20  # pseudo-observations
winsorize_bounds = (0.10, 0.90)
```

**Phase 1 (Quarterly Recalibration):**
```
shrinkage_weight = n_projects / (n_projects + prior_strength)
blended_median = shrinkage_weight × empirical_median + (1 - shrinkage_weight) × prior_median
```

### 2.5 Equity Calculation

**Service ratio per district:**
```
service_ratio_d = (projects_last_year_d / pop_d) / (projects_city / pop_city)
```

| Tier | Condition | Multiplier Effect |
|------|-----------|-------------------|
| Underserved | ratio < 0.6 | Up to +12.5% |
| Average | 0.6 ≤ ratio ≤ 1.4 | Neutral |
| Well-served | ratio > 1.4 | Up to −12.5% |

---

## 3. Governance Agent

### 3.1 Selection Phases

| Phase | Criteria | Budget Cap |
|-------|----------|------------|
| 1. Mandates | `mandate_tier IN ('required', 'court_ordered')` | 30% |
| 2. Urgent-Critical | `urgency_score > 0.7 AND safety_tier IN ('severe','critical')` | 20% |
| 3. Value-Ranked | Remaining by `composite_score DESC` | 50% |

### 3.2 Decision Statuses

| Status | Meaning |
|--------|---------|
| `APPROVED` | Ready for scheduling and execution |
| `APPROVED_WITH_CONDITIONS` | Needs human confirmation before execution |
| `DEFERRED` | Pushed to next quarter |
| `REJECTED` | Not proceeding (rare) |
| `EXPIRED` | Auto-expired after confirmation timeout |

### 3.3 Human Confirmation Workflow

**Triggers (require confirmation):**
- `estimated_cost > $10M` OR
- `safety_tier IN ('severe', 'critical')`

**Flow:**
```
APPROVED_WITH_CONDITIONS → SCHEDULED (tentative, soft reservations)
                         → CONFIRMED (human signs off) → LOCKED
                         → EXPIRED (auto after 14 days, releases reservations)
```

### 3.4 Equity Enforcement

| Condition | Action | Rationale Language |
|-----------|--------|-------------------|
| District > 2× fair share | DEFER | "Sequencing investment for long-run fairness" |
| All 3: >2× share + low urgency + no mandate/safety | REJECT | "Low-priority in over-allocated district" |

---

## 4. Scheduling Agent

### 4.1 Solver Selection

| Condition | Solver |
|-----------|--------|
| ≤10 projects AND ≤2 resource types | `GreedyScheduler` |
| ≤20 projects, loose deadlines | `GreedyWithRepairScheduler` |
| >20 projects OR tight coupling ≥3 resource types | `CPSATScheduler` |

### 4.2 Urgency-Weighted Priority
```
effective_priority = priority_rank × (1 + 0.5 × urgency_score)
```

### 4.3 Deadline Tracking

| Field | Calculation |
|-------|-------------|
| `deadline_week` | `current_week + urgency_days / 7` |
| `slack_days` | `(deadline_week - end_week) × 7` |
| `deadline_status` | `ON_TRACK` / `AT_RISK` / `MISSED` |

### 4.4 Resource Reservations

| Type | Purpose |
|------|---------|
| `soft_allocated` | Tentative (unconfirmed projects) |
| `hard_allocated` | Confirmed projects |

Constraint: `soft_allocated + hard_allocated ≤ capacity`

---

## 5. Database Schema

### 5.1 Core Tables

```sql
-- Issues (input)
issues (issue_id PK, title, category, description, source, district_id, status, created_at)

-- Signals (input) 
issue_signals (issue_id PK FK, population_affected, complaint_count, 
               safety_tier, mandate_tier, estimated_cost, urgency_days)

-- Project Candidates (Agent 1 output)
project_candidates (project_id PK, issue_id FK, title, scope, 
                    estimated_cost, estimated_weeks, required_crew_type, crew_size,
                    composite_score, benefit_score, urgency_score,
                    feasibility_estimate, feasibility_confirmed, feasibility_override,
                    equity_tier, created_by, created_at)

-- Portfolio Decisions (Agent 2 output)
portfolio_decisions (decision_id PK, project_id FK, decision, allocated_budget,
                     priority_rank, rationale, deadline_week,
                     requires_confirmation, confirmation_deadline, 
                     confirmed_at, confirmed_by, decided_by, decided_at)

-- Resource Calendar
resource_calendar (resource_id PK, resource_type, week_number, year,
                   capacity, soft_allocated, hard_allocated,
                   UNIQUE(resource_type, week_number, year))

-- Schedule Tasks (Agent 3 output)
schedule_tasks (task_id PK, project_id FK, start_week, end_week,
                deadline_week, deadline_status, slack_days,
                resource_type, crew_assigned, status, created_by, created_at)
```

### 5.2 Supporting Tables

```sql
-- Districts (for equity)
districts (district_id PK, name, population)

-- District Allocations (quarterly tracking)
district_allocations (district_id, quarter, year, population,
                      fair_share_budget, allocated_budget, project_count, equity_ratio,
                      PRIMARY KEY(district_id, quarter))

-- Scoring Audit (provenance)
scoring_audit (audit_id PK, project_id FK, score_type, source, actor_id,
               original_value, final_value, override_reason, created_at)

-- Scoring Config (tunable parameters)
scoring_config (config_key PK, config_value JSON, updated_at)

-- Audit Log (general)
audit_log (log_id PK, event_type, agent_name, payload JSON, timestamp)
```

---

## 6. Configuration Constants

```python
# Scoring weights (must sum to 1.0 before equity multiplier)
SCORING_WEIGHTS = {
    "safety": 0.15,
    "mandate": 0.15,
    "benefit": 0.25,
    "urgency": 0.20,
    "feasibility": 0.15,
}

# Tier mappings
TIER_VALUES = {
    "safety": {"none": 0, "moderate": 0.4, "severe": 0.7, "critical": 1.0},
    "mandate": {"none": 0, "advisory": 0.3, "required": 0.7, "court_ordered": 1.0},
}

# Urgency decay
URGENCY_CONFIG = {
    "lambda": 0.02,
    "floor": 0.10,
}

# Benefit normalization
BOOTSTRAP_CONFIG = {
    "prior_strength": 20,
    "winsorize_percentiles": (0.10, 0.90),
    "recalibration_cadence": "quarterly",
}

# Equity
EQUITY_CONFIG = {
    "underserved_threshold": 0.6,
    "overserved_threshold": 1.4,
    "multiplier_strength": 0.25,
    "clamp_bounds": (-0.5, 0.5),
    "defer_threshold": 2.0,
}

# Governance
GOVERNANCE_CONFIG = {
    "mandate_budget_cap": 0.30,
    "urgent_critical_cap": 0.20,
    "require_confirmation_cost": 10_000_000,
    "require_confirmation_safety": ["severe", "critical"],
    "confirmation_timeout_days": 14,
}

# Scheduling
SCHEDULER_CONFIG = {
    "greedy_threshold_projects": 10,
    "greedy_threshold_resource_types": 2,
    "repair_threshold_projects": 20,
    "urgency_priority_weight": 0.5,
    "max_repair_iterations": 3,
}
```

---

## 7. Audit & Accountability

### 7.1 Scoring Audit Trail

Every score component records:
- `source`: `'agent'` or `'human'`
- `original_value`: What agent computed
- `final_value`: What was actually used
- `override_reason`: Why human changed it (if applicable)

### 7.2 Key Audit Events

| Event Type | Agent | Payload |
|------------|-------|---------|
| `PROJECT_SCORED` | formation | All sub-scores + composite |
| `PROJECT_APPROVED` | governance | Budget, priority, rationale |
| `PROJECT_DEFERRED` | governance | Reason (budget/equity) |
| `FEASIBILITY_OVERRIDDEN` | governance | Original, override, reason |
| `TASK_SCHEDULED` | scheduling | Start/end weeks, resources |
| `APPROVAL_EXPIRED` | system | Project ID, timeout date |

---

## 8. Key Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Greedy-first** | CP-SAT only when complexity demands |
| **Approve-with-conditions** | Keeps pipeline moving; soft reservations |
| **Equity-as-defer** | Nudges fairness without hard blocks |
| **Hybrid scoring** | Continuous for quantities, tiered for judgments |
| **Structured provenance** | Agent vs. human decisions always distinguishable |
| **Bootstrap + shrinkage** | Graceful cold-start, converges to empirical |

---

*Specification version: 1.0 — December 2025*
