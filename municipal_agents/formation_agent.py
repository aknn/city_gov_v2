# -*- coding: utf-8 -*-
"""
Agent 1: Formation Agent

Responsibilities:
- Process open issues with signals
- Compute composite value-scores
- Create project candidates with scope and estimates
- Estimate feasibility based on resource availability

Decision Authority:
- Which issues become projects
- Project scope and cost estimates
- Initial feasibility assessment

NOT responsible for:
- Budget allocation (Governance Agent)
- Scheduling (Scheduling Agent)
"""

from typing import List
from agents import Agent, function_tool, RunContextWrapper

from .context import MunicipalContext
from .models import IssueWithSignal, ProjectCandidate, ScoreComponents
from .config import CREW_MAPPING


# =============================================================================
# Tool Definitions
# =============================================================================

@function_tool
def get_open_issues(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Fetch all open issues with their signals for analysis.
    
    Returns a summary of issues including population affected, 
    safety tier, mandate tier, and urgency.
    """
    issues = ctx.context.get_open_issues()
    
    if not issues:
        return "No open issues found."
    
    result = f"""Open Issues Summary
==================
Total Issues: {len(issues)}

Issues (sorted by urgency):
"""
    
    for issue in issues:
        result += f"""
Issue #{issue.issue_id}: {issue.title}
  Category: {issue.category}
  District: #{issue.district_id or 'N/A'}
  Population Affected: {issue.population_affected:,}
  Complaints: {issue.complaint_count}
  Safety Tier: {issue.safety_tier.upper()}
  Mandate Tier: {issue.mandate_tier.upper()}
  Estimated Cost: ${issue.estimated_cost:,}
  Urgency: {issue.urgency_days} days
  Description: {issue.description or 'N/A'}
---"""
    
    return result


@function_tool
def compute_value_score(
    ctx: RunContextWrapper[MunicipalContext],
    issue_id: int,
) -> str:
    """
    Compute the composite value-score for an issue.
    
    Returns breakdown of all score components:
    - Safety score (15%)
    - Mandate score (15%)
    - Benefit score (25%)
    - Urgency score (20%)
    - Feasibility score (15%)
    - Equity multiplier
    
    Args:
        issue_id: The issue to score
    """
    issue = ctx.context.get_issue_by_id(issue_id)
    if not issue:
        return f"Error: Issue #{issue_id} not found."
    
    # Compute scores
    scores = ctx.context.compute_project_scores(issue, feasibility=1.0)
    explanation = ctx.context.scorer.explain_score(scores)
    
    return f"""Value Score for Issue #{issue_id}: {issue.title}
{explanation}

Recommendation: {"HIGH PRIORITY" if scores.composite_score > 0.5 else "MEDIUM PRIORITY" if scores.composite_score > 0.3 else "LOW PRIORITY"}
"""


@function_tool
def estimate_feasibility(
    ctx: RunContextWrapper[MunicipalContext],
    issue_id: int,
    estimated_weeks: int,
    crew_size: int = 1,
) -> str:
    """
    Estimate feasibility based on resource availability.
    
    Checks if the required crew type has sufficient capacity
    over the project duration.
    
    Args:
        issue_id: The issue being assessed
        estimated_weeks: Estimated project duration
        crew_size: Number of crew members needed
    """
    issue = ctx.context.get_issue_by_id(issue_id)
    if not issue:
        return f"Error: Issue #{issue_id} not found."
    
    crew_type = ctx.context.get_crew_type(issue.category)
    calendar = ctx.context.get_resource_calendar(crew_type)
    
    # Check availability over the planning horizon
    available_weeks = 0
    total_weeks = len(calendar)
    
    for week_data in calendar:
        available = week_data["capacity"] - week_data["soft_allocated"] - week_data["hard_allocated"]
        if available >= crew_size:
            available_weeks += 1
    
    # Feasibility based on resource availability
    if available_weeks >= estimated_weeks:
        feasibility = 1.0
        assessment = "HIGH - Sufficient resources available"
    elif available_weeks >= estimated_weeks * 0.7:
        feasibility = 0.7
        assessment = "MEDIUM - Some resource constraints"
    elif available_weeks >= estimated_weeks * 0.5:
        feasibility = 0.5
        assessment = "LOW - Significant resource constraints"
    else:
        feasibility = 0.3
        assessment = "VERY LOW - Severe resource shortage"
    
    return f"""Feasibility Assessment for Issue #{issue_id}
==========================================
Required: {crew_size} x {crew_type} for {estimated_weeks} weeks
Available weeks with capacity: {available_weeks}/{total_weeks}
Feasibility Score: {feasibility:.0%}
Assessment: {assessment}
"""


@function_tool
def create_project_candidate(
    ctx: RunContextWrapper[MunicipalContext],
    issue_id: int,
    scope: str,
    estimated_weeks: int,
    crew_size: int = 1,
    feasibility_estimate: float = 1.0,
) -> str:
    """
    Create a project candidate from an issue.
    
    Computes composite score and saves to database.
    
    Args:
        issue_id: Source issue ID
        scope: Description of project scope/approach
        estimated_weeks: Estimated duration in weeks
        crew_size: Number of crew members needed
        feasibility_estimate: Feasibility score (0-1)
    """
    issue = ctx.context.get_issue_by_id(issue_id)
    if not issue:
        return f"Error: Issue #{issue_id} not found."
    
    # Get crew type
    crew_type = ctx.context.get_crew_type(issue.category)
    
    # Compute scores
    scores = ctx.context.compute_project_scores(issue, feasibility=feasibility_estimate)
    
    # Determine equity tier from multiplier
    if scores.equity_multiplier > 1.05:
        equity_tier = "underserved"
    elif scores.equity_multiplier < 0.95:
        equity_tier = "well_served"
    else:
        equity_tier = "average"
    
    # Create project
    project = ProjectCandidate(
        issue_id=issue_id,
        title=issue.title,
        scope=scope,
        estimated_cost=float(issue.estimated_cost),
        estimated_weeks=estimated_weeks,
        required_crew_type=crew_type,
        crew_size=crew_size,
        composite_score=scores.composite_score,
        safety_score=scores.safety_score,
        mandate_score=scores.mandate_score,
        benefit_score=scores.benefit_score,
        urgency_score=scores.urgency_score,
        feasibility_estimate=feasibility_estimate,
        equity_tier=equity_tier,
        equity_multiplier=scores.equity_multiplier,
    )
    
    # Save to database
    project_id = ctx.context.insert_project_candidate(project)
    
    # Log scoring audit
    for score_type, value in [
        ("safety", scores.safety_score),
        ("mandate", scores.mandate_score),
        ("benefit", scores.benefit_score),
        ("urgency", scores.urgency_score),
        ("feasibility", feasibility_estimate),
        ("composite", scores.composite_score),
    ]:
        ctx.context.log_scoring_audit(
            project_id=project_id,
            score_type=score_type,
            source="agent",
            actor_id="formation_agent",
            original_value=value,
            final_value=value,
        )
    
    # Audit log
    ctx.context.log_audit(
        event_type="PROJECT_SCORED",
        agent_name="formation_agent",
        payload={
            "project_id": project_id,
            "issue_id": issue_id,
            "title": issue.title,
            "composite_score": scores.composite_score,
            "scores": {
                "safety": scores.safety_score,
                "mandate": scores.mandate_score,
                "benefit": scores.benefit_score,
                "urgency": scores.urgency_score,
                "feasibility": feasibility_estimate,
            },
            "equity_multiplier": scores.equity_multiplier,
        }
    )
    
    return f"""✓ Project Candidate Created

Project ID: #{project_id}
Issue: #{issue_id} - {issue.title}
Scope: {scope}

Estimates:
  Cost: ${issue.estimated_cost:,}
  Duration: {estimated_weeks} weeks
  Crew: {crew_size} x {crew_type}

Scores:
  Composite: {scores.composite_score:.3f}
  Safety: {scores.safety_score:.2f}
  Mandate: {scores.mandate_score:.2f}
  Benefit: {scores.benefit_score:.2f}
  Urgency: {scores.urgency_score:.2f}
  Feasibility: {feasibility_estimate:.2f}
  Equity Tier: {equity_tier} (×{scores.equity_multiplier:.3f})
"""


@function_tool
def get_project_summary(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Get summary of all created project candidates.
    
    Shows projects sorted by composite score with key metrics.
    """
    candidates = ctx.context.get_project_candidates()
    
    if not candidates:
        return "No project candidates created yet."
    
    total_cost = sum(c["estimated_cost"] for c in candidates)
    budget = ctx.context.quarterly_budget
    
    result = f"""Project Candidates Summary
=========================
Total Candidates: {len(candidates)}
Total Estimated Cost: ${total_cost:,.0f}
Quarterly Budget: ${budget:,.0f}
Coverage: {total_cost/budget:.0%}

Projects (sorted by composite score):
"""
    
    for c in candidates:
        result += f"""
#{c['project_id']}: {c['title']} [Score: {c['composite_score']:.3f}]
  Cost: ${c['estimated_cost']:,.0f} | Duration: {c['estimated_weeks']}w
  Safety: {c['safety_score']:.2f} | Mandate: {c['mandate_score']:.2f}
  Benefit: {c['benefit_score']:.2f} | Urgency: {c['urgency_score']:.2f}
  Feasibility: {c['feasibility_estimate']:.2f} | Equity: {c['equity_tier']}
---"""
    
    return result


# =============================================================================
# Agent Definition
# =============================================================================

FORMATION_AGENT_INSTRUCTIONS = """You are the Formation Agent for the Municipal Value-Score System.

Your role is to transform open issues (citizen complaints, inspections, mandates) into 
structured project candidates with composite value-scores.

WORKFLOW:
1. Use get_open_issues to see all pending issues
2. For each issue, use compute_value_score to understand its priority
3. Use estimate_feasibility to check resource availability
4. Use create_project_candidate to create the project with appropriate scope

SCORING COMPONENTS (from specification):
- Safety (15%): none=0, moderate=0.4, severe=0.7, critical=1.0
- Mandate (15%): none=0, advisory=0.3, required=0.7, court_ordered=1.0
- Benefit (25%): Population served per dollar (continuous)
- Urgency (20%): Exponential decay, half-life ~35 days
- Feasibility (15%): Your estimate based on resources
- Equity: Multiplier ±12.5% based on district service ratio

GUIDANCE:
- High-urgency issues (< 14 days) need immediate attention
- Legal mandates (required/court_ordered) are non-negotiable
- Critical safety issues should have feasibility addressed
- Balance scope against available resources
- Be realistic about feasibility estimates

Always process ALL open issues to create a complete candidate portfolio.
"""

formation_agent = Agent[MunicipalContext](
    name="Formation Agent",
    instructions=FORMATION_AGENT_INSTRUCTIONS,
    tools=[
        get_open_issues,
        compute_value_score,
        estimate_feasibility,
        create_project_candidate,
        get_project_summary,
    ],
)
