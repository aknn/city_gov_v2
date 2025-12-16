# -*- coding: utf-8 -*-
"""
Pydantic models for Municipal Value-Score System v2.

Data models for issues, projects, decisions, and schedules
with full validation and type safety.
"""

from datetime import datetime, date
from typing import Optional, List, Literal
from pydantic import BaseModel, Field, field_validator


# =============================================================================
# Tier Types
# =============================================================================

SafetyTier = Literal["none", "moderate", "severe", "critical"]
MandateTier = Literal["none", "advisory", "required", "court_ordered"]
EquityTier = Literal["underserved", "average", "well_served"]
DecisionStatus = Literal["APPROVED", "APPROVED_WITH_CONDITIONS", "DEFERRED", "REJECTED", "EXPIRED"]
DeadlineStatus = Literal["ON_TRACK", "AT_RISK", "MISSED"]
ReservationType = Literal["soft", "hard"]


# =============================================================================
# Input Models
# =============================================================================

class District(BaseModel):
    """Geographic district for equity tracking."""
    district_id: int
    name: str
    population: int = Field(gt=0)


class Issue(BaseModel):
    """Raw citizen complaint or municipal issue."""
    issue_id: int
    title: str
    category: str
    description: Optional[str] = None
    source: str = "citizen_complaint"
    district_id: Optional[int] = None
    status: str = "OPEN"
    created_at: Optional[datetime] = None


class IssueSignal(BaseModel):
    """Quantified impact/risk metrics for an issue."""
    issue_id: int
    population_affected: int = Field(ge=0)
    complaint_count: int = Field(ge=0)
    safety_tier: SafetyTier = "none"
    mandate_tier: MandateTier = "none"
    estimated_cost: int = Field(gt=0)
    urgency_days: int = Field(default=90, ge=1)


class IssueWithSignal(BaseModel):
    """Combined issue and signal data."""
    issue_id: int
    title: str
    category: str
    description: Optional[str] = None
    source: str
    district_id: Optional[int] = None
    status: str
    population_affected: int
    complaint_count: int
    safety_tier: SafetyTier
    mandate_tier: MandateTier
    estimated_cost: int
    urgency_days: int


# =============================================================================
# Scoring Models
# =============================================================================

class ScoreComponents(BaseModel):
    """Breakdown of composite score components."""
    safety_score: float = Field(ge=0, le=1)
    mandate_score: float = Field(ge=0, le=1)
    benefit_score: float = Field(ge=0, le=1)
    urgency_score: float = Field(ge=0, le=1)
    feasibility_score: float = Field(ge=0, le=1)
    equity_multiplier: float = Field(ge=0.875, le=1.125)  # ±12.5%
    composite_score: float = Field(ge=0)


class ScoringAuditEntry(BaseModel):
    """Audit trail entry for a score component."""
    project_id: int
    score_type: str
    source: Literal["agent", "human"]
    actor_id: str
    original_value: float
    final_value: float
    override_reason: Optional[str] = None


# =============================================================================
# Agent 1 Output: Project Candidates
# =============================================================================

class ProjectCandidate(BaseModel):
    """A proposed project with cost estimates and composite scoring."""
    project_id: Optional[int] = None  # Assigned by DB
    issue_id: int
    title: str
    scope: Optional[str] = None
    estimated_cost: float = Field(gt=0)
    estimated_weeks: int = Field(ge=1)
    required_crew_type: str = "general_crew"
    crew_size: int = Field(default=1, ge=1)
    
    # Scoring
    composite_score: Optional[float] = None
    safety_score: Optional[float] = None
    mandate_score: Optional[float] = None
    benefit_score: Optional[float] = None
    urgency_score: Optional[float] = None
    feasibility_estimate: float = Field(default=1.0, ge=0, le=1)
    feasibility_confirmed: bool = False
    feasibility_override: Optional[float] = None
    equity_tier: Optional[EquityTier] = None
    equity_multiplier: float = 1.0
    
    created_by: str = "formation_agent"
    created_at: Optional[datetime] = None
    
    @property
    def effective_feasibility(self) -> float:
        """Return override if set, otherwise estimate."""
        return self.feasibility_override if self.feasibility_override is not None else self.feasibility_estimate


# =============================================================================
# Agent 2 Output: Portfolio Decisions
# =============================================================================

class PortfolioDecision(BaseModel):
    """Budget allocation decision for a project."""
    decision_id: Optional[int] = None
    project_id: int
    decision: DecisionStatus
    allocated_budget: Optional[float] = None
    priority_rank: Optional[int] = None
    rationale: str
    deadline_week: Optional[int] = None
    
    # Confirmation workflow
    requires_confirmation: bool = False
    confirmation_deadline: Optional[date] = None
    confirmed_at: Optional[datetime] = None
    confirmed_by: Optional[str] = None
    
    decided_by: str = "governance_agent"
    decided_at: Optional[datetime] = None


class PortfolioSummary(BaseModel):
    """Summary of governance decisions for a batch."""
    total_budget: float
    allocated_budget: float
    remaining_budget: float
    approved_count: int
    conditional_count: int
    deferred_count: int
    rejected_count: int
    decisions: List[PortfolioDecision]


# =============================================================================
# Agent 3 Output: Schedule Tasks
# =============================================================================

class ScheduleTask(BaseModel):
    """Scheduled execution of an approved project."""
    task_id: Optional[int] = None
    project_id: int
    start_week: int = Field(ge=1)
    end_week: int = Field(ge=1)
    deadline_week: Optional[int] = None
    deadline_status: DeadlineStatus = "ON_TRACK"
    slack_days: Optional[int] = None
    resource_type: str
    crew_assigned: int = Field(default=1, ge=1)
    reservation_type: ReservationType = "soft"
    status: str = "SCHEDULED"
    created_by: str = "scheduling_agent"
    created_at: Optional[datetime] = None
    
    @field_validator('end_week')
    @classmethod
    def end_after_start(cls, v, info):
        if 'start_week' in info.data and v < info.data['start_week']:
            raise ValueError('end_week must be >= start_week')
        return v


class ScheduleOutput(BaseModel):
    """Complete schedule output from scheduling agent."""
    scheduled_tasks: List[ScheduleTask]
    infeasible_projects: List[int]  # Project IDs that couldn't be scheduled
    horizon_weeks: int
    total_scheduled: int
    deadline_risks: int  # Count of AT_RISK or MISSED


# =============================================================================
# Resource Models
# =============================================================================

class ResourceSlot(BaseModel):
    """Resource availability for a specific week."""
    resource_type: str
    week_number: int
    year: int
    capacity: int
    soft_allocated: int = 0
    hard_allocated: int = 0
    
    @property
    def available(self) -> int:
        return self.capacity - self.soft_allocated - self.hard_allocated
    
    @property
    def total_allocated(self) -> int:
        return self.soft_allocated + self.hard_allocated


# =============================================================================
# District Equity Models
# =============================================================================

class DistrictAllocation(BaseModel):
    """Quarterly allocation tracking for a district."""
    district_id: int
    quarter: str  # e.g., "Q1"
    year: int
    population: int
    fair_share_budget: float
    allocated_budget: float = 0
    project_count: int = 0
    equity_ratio: Optional[float] = None  # allocated / fair_share
    
    @property
    def service_ratio(self) -> float:
        """Ratio vs fair share (1.0 = fair)."""
        if self.fair_share_budget <= 0:
            return 1.0
        return self.allocated_budget / self.fair_share_budget


# =============================================================================
# Audit Models
# =============================================================================

class AuditLogEntry(BaseModel):
    """General audit log entry."""
    log_id: Optional[int] = None
    event_type: str
    agent_name: str
    payload: dict
    timestamp: Optional[datetime] = None
