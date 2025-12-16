# -*- coding: utf-8 -*-
"""
Agent 2: Governance Agent

Responsibilities:
- Review project candidates with composite scores
- Allocate budget under quarterly constraints
- Apply tiered selection (mandates → urgent-critical → value-ranked)
- Enforce equity constraints (defer if > 2× fair share)
- Handle human confirmation workflow for high-cost/high-risk projects

Decision Authority:
- Budget allocation
- Project approval/rejection/deferral
- Priority ranking
- Confirmation requirements

NOT responsible for:
- Creating project proposals (Formation Agent)
- Scheduling resources (Scheduling Agent)
"""

from datetime import date, timedelta
from typing import List
from agents import Agent, function_tool, RunContextWrapper

from .context import MunicipalContext
from .models import PortfolioDecision
from .config import GOVERNANCE_CONFIG, EQUITY_CONFIG


# =============================================================================
# Tool Definitions
# =============================================================================

@function_tool
def get_project_candidates(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Fetch all project candidates created by the Formation Agent.
    
    Returns candidates sorted by composite score with budget summary.
    """
    candidates = ctx.context.get_project_candidates()
    
    if not candidates:
        return "No project candidates found. Formation Agent has not processed issues yet."
    
    total_cost = sum(c["estimated_cost"] for c in candidates)
    budget = ctx.context.quarterly_budget
    
    result = f"""Project Candidates for Governance Review
=========================================
Total Candidates: {len(candidates)}
Total Estimated Cost: ${total_cost:,.0f}
Quarterly Budget: ${budget:,.0f}
Budget Gap: ${max(0, total_cost - budget):,.0f}

Candidates (sorted by composite score):
"""
    
    for c in candidates:
        # Determine tier flags
        flags = []
        if c.get("mandate_score", 0) >= 0.7:
            flags.append("MANDATE")
        if c.get("safety_score", 0) >= 0.7:
            flags.append("SAFETY")
        if c.get("urgency_score", 0) >= 0.7:
            flags.append("URGENT")
        
        flag_str = f" [{', '.join(flags)}]" if flags else ""
        
        result += f"""
#{c['project_id']}: {c['title']}{flag_str}
  Composite Score: {c['composite_score']:.3f}
  Cost: ${c['estimated_cost']:,.0f} | Duration: {c['estimated_weeks']}w
  Safety: {c['safety_score']:.2f} | Mandate: {c['mandate_score']:.2f}
  Urgency: {c['urgency_score']:.2f} | Feasibility: {c['feasibility_estimate']:.2f}
  Equity: {c['equity_tier']} (×{c['equity_multiplier']:.3f})
---"""
    
    return result


@function_tool
def get_budget_status(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Get current budget allocation status.
    
    Shows total budget, allocations, and remaining funds.
    """
    status = ctx.context.get_budget_status()
    decisions = ctx.context.get_portfolio_decisions()
    
    approved = [d for d in decisions if d["decision"] in ("APPROVED", "APPROVED_WITH_CONDITIONS")]
    deferred = [d for d in decisions if d["decision"] == "DEFERRED"]
    rejected = [d for d in decisions if d["decision"] == "REJECTED"]
    
    # Calculate phase budgets
    mandate_cap = status["total_budget"] * GOVERNANCE_CONFIG["mandate_budget_cap"]
    urgent_cap = status["total_budget"] * GOVERNANCE_CONFIG["urgent_critical_cap"]
    
    return f"""Budget Status for {ctx.context.city_name}
==========================================
Quarterly Budget: ${status['total_budget']:,.0f}
Allocated: ${status['allocated']:,.0f}
Remaining: ${status['remaining']:,.0f}

Phase Budgets:
  Mandates (30%): ${mandate_cap:,.0f}
  Urgent-Critical (20%): ${urgent_cap:,.0f}
  Value-Ranked (50%): ${status['total_budget'] * 0.5:,.0f}

Decisions Made:
  Approved: {len(approved)}
  Deferred: {len(deferred)}
  Rejected: {len(rejected)}
"""


@function_tool
def check_district_equity(
    ctx: RunContextWrapper[MunicipalContext],
    project_id: int,
) -> str:
    """
    Check if approving a project would violate district equity constraints.
    
    Args:
        project_id: The project to check
    """
    project = ctx.context.get_project_by_id(project_id)
    if not project:
        return f"Error: Project #{project_id} not found."
    
    # Get issue to find district
    issue = ctx.context.get_issue_by_id(project["issue_id"])
    if not issue or not issue.district_id:
        return f"Project #{project_id} has no district assignment. Equity check skipped."
    
    can_approve, reason = ctx.context.check_equity_constraint(
        issue.district_id, 
        project["estimated_cost"]
    )
    
    allocations = ctx.context.get_district_allocations()
    district = next((a for a in allocations if a["district_id"] == issue.district_id), None)
    
    if district:
        current_ratio = district["allocated_budget"] / district["fair_share"] if district["fair_share"] > 0 else 0
        projected = (district["allocated_budget"] + project["estimated_cost"]) / district["fair_share"] if district["fair_share"] > 0 else 0
        
        return f"""Equity Check for Project #{project_id}
=====================================
District: {district['name']} (#{issue.district_id})
Fair Share Budget: ${district['fair_share']:,.0f}
Currently Allocated: ${district['allocated_budget']:,.0f}
Project Cost: ${project['estimated_cost']:,.0f}

Current Ratio: {current_ratio:.1%} of fair share
Projected Ratio: {projected:.1%} of fair share
Defer Threshold: {EQUITY_CONFIG['defer_threshold'] * 100:.0f}%

Decision: {"✓ CAN APPROVE" if can_approve else "⚠ SHOULD DEFER"}
Reason: {reason}
"""
    
    return f"District data not found for project #{project_id}."


@function_tool
def run_tiered_selection(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Run the tiered budget allocation algorithm.
    
    Phases:
    1. Mandates (required/court_ordered) - up to 30% budget
    2. Urgent-Critical (urgency > 0.7 AND safety severe/critical) - up to 20% budget
    3. Value-Ranked (remaining by composite score) - remaining 50% budget
    
    Returns recommended approvals with priority ranks.
    """
    candidates = ctx.context.get_project_candidates()
    if not candidates:
        return "No candidates to evaluate."
    
    budget = ctx.context.quarterly_budget
    mandate_cap = budget * GOVERNANCE_CONFIG["mandate_budget_cap"]
    urgent_cap = budget * GOVERNANCE_CONFIG["urgent_critical_cap"]
    
    # Track allocations
    mandate_allocated = 0
    urgent_allocated = 0
    value_allocated = 0
    
    approved = []
    deferred = []
    priority_rank = 0
    
    # Phase 1: Mandates
    mandates = [c for c in candidates if c.get("mandate_score", 0) >= 0.7]
    mandates.sort(key=lambda x: x["composite_score"], reverse=True)
    
    for c in mandates:
        if mandate_allocated + c["estimated_cost"] <= mandate_cap:
            priority_rank += 1
            approved.append({**c, "phase": "MANDATE", "priority": priority_rank})
            mandate_allocated += c["estimated_cost"]
        else:
            deferred.append({**c, "reason": "Mandate budget cap exceeded"})
    
    # Phase 2: Urgent-Critical
    approved_ids = {a["project_id"] for a in approved}
    urgent_critical = [
        c for c in candidates 
        if c["project_id"] not in approved_ids
        and c.get("urgency_score", 0) > 0.7
        and c.get("safety_score", 0) >= 0.7
    ]
    urgent_critical.sort(key=lambda x: x["composite_score"], reverse=True)
    
    for c in urgent_critical:
        if urgent_allocated + c["estimated_cost"] <= urgent_cap:
            priority_rank += 1
            approved.append({**c, "phase": "URGENT_CRITICAL", "priority": priority_rank})
            urgent_allocated += c["estimated_cost"]
        else:
            deferred.append({**c, "reason": "Urgent-critical budget cap exceeded"})
    
    # Phase 3: Value-Ranked
    approved_ids = {a["project_id"] for a in approved}
    deferred_ids = {d["project_id"] for d in deferred}
    remaining = [
        c for c in candidates 
        if c["project_id"] not in approved_ids
        and c["project_id"] not in deferred_ids
    ]
    remaining.sort(key=lambda x: x["composite_score"], reverse=True)
    
    value_cap = budget - mandate_allocated - urgent_allocated
    
    for c in remaining:
        if value_allocated + c["estimated_cost"] <= value_cap:
            priority_rank += 1
            approved.append({**c, "phase": "VALUE_RANKED", "priority": priority_rank})
            value_allocated += c["estimated_cost"]
        else:
            deferred.append({**c, "reason": "Budget exhausted"})
    
    # Build result
    total_allocated = mandate_allocated + urgent_allocated + value_allocated
    
    result = f"""Tiered Selection Results
========================
Budget: ${budget:,.0f}

Phase Allocations:
  Mandates: ${mandate_allocated:,.0f} / ${mandate_cap:,.0f} ({mandate_allocated/mandate_cap:.0%})
  Urgent-Critical: ${urgent_allocated:,.0f} / ${urgent_cap:,.0f} ({urgent_allocated/urgent_cap:.0%})
  Value-Ranked: ${value_allocated:,.0f} / ${value_cap:,.0f} ({value_allocated/value_cap:.0%})

Total Allocated: ${total_allocated:,.0f} ({total_allocated/budget:.0%})

RECOMMENDED APPROVALS ({len(approved)}):
"""
    
    for a in approved:
        result += f"""
  {a['priority']}. #{a['project_id']}: {a['title']}
     Phase: {a['phase']} | Score: {a['composite_score']:.3f}
     Cost: ${a['estimated_cost']:,.0f}
"""
    
    if deferred:
        result += f"\nDEFERRED ({len(deferred)}):\n"
        for d in deferred:
            result += f"  - #{d['project_id']}: {d['title']} ({d['reason']})\n"
    
    return result


@function_tool
def approve_project(
    ctx: RunContextWrapper[MunicipalContext],
    project_id: int,
    priority_rank: int,
    rationale: str,
    require_confirmation: bool = False,
) -> str:
    """
    Approve a project and record the decision.
    
    Args:
        project_id: The project to approve
        priority_rank: Priority order (1 = highest)
        rationale: Reason for approval
        require_confirmation: If True, requires human confirmation before execution
    """
    project = ctx.context.get_project_by_id(project_id)
    if not project:
        return f"Error: Project #{project_id} not found."
    
    # Check budget
    status = ctx.context.get_budget_status()
    if status["remaining"] < project["estimated_cost"]:
        return f"""Error: Insufficient budget.
Available: ${status['remaining']:,.0f}
Project Cost: ${project['estimated_cost']:,.0f}
Consider deferring lower-priority projects first."""
    
    # Determine if confirmation required
    cost_threshold = GOVERNANCE_CONFIG["require_confirmation_cost"]
    safety_threshold = GOVERNANCE_CONFIG["require_confirmation_safety"]
    
    needs_confirmation = require_confirmation
    if project["estimated_cost"] >= cost_threshold:
        needs_confirmation = True
    if project.get("safety_score", 0) >= 0.7:  # severe or critical
        needs_confirmation = True
    
    # Calculate deadline week from urgency
    issue = ctx.context.get_issue_by_id(project["issue_id"])
    deadline_week = None
    if issue:
        deadline_week = max(1, issue.urgency_days // 7)
    
    # Set confirmation deadline if needed
    confirmation_deadline = None
    if needs_confirmation:
        confirmation_deadline = date.today() + timedelta(days=GOVERNANCE_CONFIG["confirmation_timeout_days"])
    
    decision_status = "APPROVED_WITH_CONDITIONS" if needs_confirmation else "APPROVED"
    
    decision = PortfolioDecision(
        project_id=project_id,
        decision=decision_status,
        allocated_budget=project["estimated_cost"],
        priority_rank=priority_rank,
        rationale=rationale,
        deadline_week=deadline_week,
        requires_confirmation=needs_confirmation,
        confirmation_deadline=confirmation_deadline,
    )
    
    decision_id = ctx.context.insert_portfolio_decision(decision)
    
    # Audit log
    ctx.context.log_audit(
        event_type="PROJECT_APPROVED",
        agent_name="governance_agent",
        payload={
            "decision_id": decision_id,
            "project_id": project_id,
            "title": project["title"],
            "decision": decision_status,
            "allocated_budget": project["estimated_cost"],
            "priority_rank": priority_rank,
            "requires_confirmation": needs_confirmation,
            "rationale": rationale,
        }
    )
    
    confirm_msg = ""
    if needs_confirmation:
        confirm_msg = f"""
⚠️ REQUIRES CONFIRMATION by {confirmation_deadline}
   Reason: {"High cost (>${cost_threshold/1e6:.0f}M)" if project["estimated_cost"] >= cost_threshold else "High safety risk"}
   If not confirmed, project will auto-expire."""
    
    return f"""✓ Project {decision_status}

Decision ID: #{decision_id}
Project #{project_id}: {project['title']}
Allocated Budget: ${project['estimated_cost']:,.0f}
Priority Rank: {priority_rank}
Deadline Week: {deadline_week or 'N/A'}
Rationale: {rationale}
{confirm_msg}

Budget Status:
- Previously Allocated: ${status['allocated']:,.0f}
- This Allocation: ${project['estimated_cost']:,.0f}
- Remaining: ${status['remaining'] - project['estimated_cost']:,.0f}
"""


@function_tool
def defer_project(
    ctx: RunContextWrapper[MunicipalContext],
    project_id: int,
    rationale: str,
) -> str:
    """
    Defer a project to the next quarter.
    
    Args:
        project_id: The project to defer
        rationale: Reason for deferral (e.g., budget, equity)
    """
    project = ctx.context.get_project_by_id(project_id)
    if not project:
        return f"Error: Project #{project_id} not found."
    
    decision = PortfolioDecision(
        project_id=project_id,
        decision="DEFERRED",
        rationale=rationale,
    )
    
    decision_id = ctx.context.insert_portfolio_decision(decision)
    
    # Audit log
    ctx.context.log_audit(
        event_type="PROJECT_DEFERRED",
        agent_name="governance_agent",
        payload={
            "decision_id": decision_id,
            "project_id": project_id,
            "title": project["title"],
            "rationale": rationale,
        }
    )
    
    return f"""✓ Project DEFERRED

Decision ID: #{decision_id}
Project #{project_id}: {project['title']}
Cost: ${project['estimated_cost']:,.0f}
Rationale: {rationale}

Project will be reconsidered next quarter.
"""


@function_tool
def reject_project(
    ctx: RunContextWrapper[MunicipalContext],
    project_id: int,
    rationale: str,
) -> str:
    """
    Reject a project (use sparingly - prefer defer).
    
    Args:
        project_id: The project to reject
        rationale: Reason for rejection
    """
    project = ctx.context.get_project_by_id(project_id)
    if not project:
        return f"Error: Project #{project_id} not found."
    
    decision = PortfolioDecision(
        project_id=project_id,
        decision="REJECTED",
        rationale=rationale,
    )
    
    decision_id = ctx.context.insert_portfolio_decision(decision)
    
    # Audit log
    ctx.context.log_audit(
        event_type="PROJECT_REJECTED",
        agent_name="governance_agent",
        payload={
            "decision_id": decision_id,
            "project_id": project_id,
            "title": project["title"],
            "rationale": rationale,
        }
    )
    
    return f"""✓ Project REJECTED

Decision ID: #{decision_id}
Project #{project_id}: {project['title']}
Rationale: {rationale}

Note: Prefer DEFER over REJECT unless there's a fundamental issue with the project.
"""


@function_tool
def get_decision_summary(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Get summary of all governance decisions made.
    """
    decisions = ctx.context.get_portfolio_decisions()
    status = ctx.context.get_budget_status()
    
    if not decisions:
        return "No decisions made yet."
    
    approved = [d for d in decisions if d["decision"] in ("APPROVED", "APPROVED_WITH_CONDITIONS")]
    conditional = [d for d in decisions if d["decision"] == "APPROVED_WITH_CONDITIONS"]
    deferred = [d for d in decisions if d["decision"] == "DEFERRED"]
    rejected = [d for d in decisions if d["decision"] == "REJECTED"]
    
    result = f"""Governance Decision Summary
===========================
Budget: ${status['total_budget']:,.0f}
Allocated: ${status['allocated']:,.0f} ({status['allocated']/status['total_budget']:.0%})
Remaining: ${status['remaining']:,.0f}

Decisions:
  Approved: {len(approved)} (${sum(d['allocated_budget'] or 0 for d in approved):,.0f})
    - Conditional: {len(conditional)} (awaiting confirmation)
  Deferred: {len(deferred)}
  Rejected: {len(rejected)}

APPROVED PROJECTS:
"""
    
    for d in sorted(approved, key=lambda x: x.get("priority_rank") or 999):
        cond = " [NEEDS CONFIRMATION]" if d["decision"] == "APPROVED_WITH_CONDITIONS" else ""
        result += f"""
  {d.get('priority_rank', '?')}. Project #{d['project_id']}{cond}
     Budget: ${d.get('allocated_budget', 0):,.0f}
     Rationale: {d.get('rationale', 'N/A')}
"""
    
    if deferred:
        result += "\nDEFERRED:\n"
        for d in deferred:
            result += f"  - Project #{d['project_id']}: {d.get('rationale', 'N/A')}\n"
    
    return result


# =============================================================================
# Agent Definition
# =============================================================================

GOVERNANCE_AGENT_INSTRUCTIONS = """You are the Governance Agent for the Municipal Value-Score System.

Your role is to allocate the quarterly budget across project candidates using 
tiered selection and equity constraints.

WORKFLOW:
1. Use get_project_candidates to review all candidates
2. Use get_budget_status to understand available funds
3. Use run_tiered_selection to get recommended allocations
4. For each recommended project, check equity with check_district_equity
5. Use approve_project, defer_project, or reject_project to record decisions
6. Use get_decision_summary to verify final portfolio

TIERED SELECTION PHASES:
1. Mandates (30% cap): required/court_ordered mandate tier
2. Urgent-Critical (20% cap): urgency > 0.7 AND safety severe/critical
3. Value-Ranked (50% remaining): by composite score descending

EQUITY RULES:
- If district > 2× fair share budget → DEFER (not reject)
- Exception: Only REJECT if low urgency AND no mandate AND no safety concern
- Use language: "Sequencing investment for long-run geographic fairness"

CONFIRMATION WORKFLOW:
- Projects > $10M or safety severe/critical require human confirmation
- They get APPROVED_WITH_CONDITIONS status
- Resources are soft-reserved until confirmed (14-day timeout)

DECISION PRIORITIES:
1. Legal mandates are non-negotiable (if budget allows)
2. Critical safety + high urgency next
3. Then by composite score
4. Defer rather than reject when possible
"""

governance_agent = Agent[MunicipalContext](
    name="Governance Agent",
    instructions=GOVERNANCE_AGENT_INSTRUCTIONS,
    tools=[
        get_project_candidates,
        get_budget_status,
        check_district_equity,
        run_tiered_selection,
        approve_project,
        defer_project,
        reject_project,
        get_decision_summary,
    ],
)
