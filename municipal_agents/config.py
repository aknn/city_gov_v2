# -*- coding: utf-8 -*-
"""
Configuration constants for Municipal Value-Score System.

All tunable parameters are centralized here for easy adjustment.
These can be overridden via environment variables or a config file.
"""

from typing import Dict, List, Tuple

# =============================================================================
# City Profile
# =============================================================================

CITY_PROFILE = {
    "city_name": "Metroville",
    "population": 2_500_000,
    "quarterly_budget": 75_000_000,  # $75M quarterly budget
    "planning_horizon_weeks": 12,
}


# =============================================================================
# Composite Scoring Weights (must sum to 1.0 before equity multiplier)
# =============================================================================

SCORING_WEIGHTS = {
    "safety": 0.15,
    "mandate": 0.15,
    "benefit": 0.25,
    "urgency": 0.20,
    "feasibility": 0.15,
}


# =============================================================================
# Tier Value Mappings
# =============================================================================

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


# =============================================================================
# Urgency Configuration (Exponential Decay)
# =============================================================================

URGENCY_CONFIG = {
    "lambda": 0.02,      # Decay rate (half-life ≈ 35 days)
    "floor": 0.10,       # Minimum urgency score
}

# Reference table:
# Days Remaining | Score
# 7              | 0.87
# 30             | 0.55
# 90             | 0.17
# 180            | 0.10 (floor)


# =============================================================================
# Benefit Normalization (Bayesian Bootstrap)
# =============================================================================

BOOTSTRAP_CONFIG = {
    "prior_strength": 20,                    # Pseudo-observations for shrinkage
    "winsorize_percentiles": (0.10, 0.90),   # Cap extremes at P10/P90
    "recalibration_cadence": "quarterly",
}


# =============================================================================
# Equity Configuration
# =============================================================================

EQUITY_CONFIG = {
    "underserved_threshold": 0.6,    # ratio < 0.6 → underserved
    "overserved_threshold": 1.4,     # ratio > 1.4 → well-served
    "multiplier_strength": 0.25,     # Max ±12.5% impact
    "clamp_bounds": (-0.5, 0.5),     # Equity score clamping
    "defer_threshold": 2.0,          # > 2× fair share → defer
}


# =============================================================================
# Governance Configuration
# =============================================================================

GOVERNANCE_CONFIG = {
    # Budget allocation phases
    "mandate_budget_cap": 0.30,           # Max 30% for mandates
    "urgent_critical_cap": 0.20,          # Next 20% for urgent+critical
    
    # Human confirmation triggers
    "require_confirmation_cost": 10_000_000,  # $10M+
    "require_confirmation_safety": ["severe", "critical"],
    
    # Confirmation workflow
    "confirmation_timeout_days": 14,
    "auto_expiry_enabled": True,
}

# Decision statuses
DECISION_STATUSES = [
    "APPROVED",
    "APPROVED_WITH_CONDITIONS",
    "DEFERRED",
    "REJECTED",
    "EXPIRED",
]


# =============================================================================
# Scheduler Configuration
# =============================================================================

SCHEDULER_CONFIG = {
    # Solver selection thresholds
    "greedy_threshold_projects": 10,
    "greedy_threshold_resource_types": 2,
    "repair_threshold_projects": 20,
    
    # Urgency-weighted priority
    "urgency_priority_weight": 0.5,
    
    # Greedy with repair
    "max_repair_iterations": 3,
    
    # CP-SAT solver settings
    "cpsat_timeout_seconds": 60,
}


# =============================================================================
# Crew Type Mapping
# =============================================================================

CREW_MAPPING = {
    "Water": "water_crew",
    "Health": "electrical_crew",
    "Disaster Management": "construction_crew",
    "Infrastructure": "construction_crew",
    "Recreation": "general_crew",
    "Education": "general_crew",
}

# Default resource capacities per week
RESOURCE_CAPACITIES = {
    "water_crew": 3,
    "electrical_crew": 2,
    "construction_crew": 5,
    "general_crew": 4,
}


# =============================================================================
# Audit Event Types
# =============================================================================

AUDIT_EVENTS = {
    "PROJECT_SCORED": "formation",
    "PROJECT_APPROVED": "governance",
    "PROJECT_DEFERRED": "governance",
    "PROJECT_REJECTED": "governance",
    "FEASIBILITY_OVERRIDDEN": "governance",
    "TASK_SCHEDULED": "scheduling",
    "APPROVAL_EXPIRED": "system",
    "RESERVATION_RELEASED": "system",
}


# =============================================================================
# Database Configuration
# =============================================================================

DB_PATH = "database/city_value.db"
