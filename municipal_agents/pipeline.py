# -*- coding: utf-8 -*-
"""
Pipeline orchestration for Municipal Value-Score System v2.

Coordinates the three-agent pipeline:
1. Formation Agent: Issues → Project Candidates
2. Governance Agent: Budget Allocation
3. Scheduling Agent: Resource Scheduling
"""

import asyncio
from typing import Optional
from agents import Runner

from .context import MunicipalContext
from .formation_agent import formation_agent
from .governance_agent import governance_agent
from .scheduling_agent import scheduling_agent
from .database import init_with_sample_data, clear_agent_outputs
from .config import DB_PATH

# Max turns for agents (more issues = more tool calls needed)
MAX_AGENT_TURNS = 50


async def run_formation_phase(ctx: MunicipalContext) -> str:
    """Run the Formation Agent to create project candidates."""
    print("\n" + "=" * 60)
    print("PHASE 1: FORMATION AGENT")
    print("=" * 60)
    
    result = await Runner.run(
        formation_agent,
        context=ctx,
        input="Process all open issues and create project candidates with composite value-scores. "
              "For each issue: compute value score, estimate feasibility, and create the project candidate. "
              "Then provide a summary of all created projects.",
        max_turns=MAX_AGENT_TURNS,
    )
    
    return result.final_output


async def run_governance_phase(ctx: MunicipalContext) -> str:
    """Run the Governance Agent to allocate budget."""
    print("\n" + "=" * 60)
    print("PHASE 2: GOVERNANCE AGENT")
    print("=" * 60)
    
    result = await Runner.run(
        governance_agent,
        context=ctx,
        input="Review all project candidates and allocate the quarterly budget. "
              "Use tiered selection (mandates first, then urgent-critical, then value-ranked). "
              "Check equity constraints before approving each project. "
              "Provide a summary of all decisions made.",
        max_turns=MAX_AGENT_TURNS,
    )
    
    return result.final_output


async def run_scheduling_phase(ctx: MunicipalContext) -> str:
    """Run the Scheduling Agent to create execution schedule."""
    print("\n" + "=" * 60)
    print("PHASE 3: SCHEDULING AGENT")
    print("=" * 60)
    
    result = await Runner.run(
        scheduling_agent,
        context=ctx,
        input="Schedule all approved projects within the planning horizon. "
              "Check resource availability, run the scheduler, and save the schedule. "
              "Report on deadline status and any infeasible projects.",
        max_turns=MAX_AGENT_TURNS,
    )
    
    return result.final_output


async def run_full_pipeline(
    db_path: str = DB_PATH,
    reset_data: bool = False,
    seed_data: bool = False,
) -> dict:
    """
    Run the complete 3-agent pipeline.
    
    Args:
        db_path: Path to database
        reset_data: If True, clear agent outputs before running
        seed_data: If True, initialize database with sample data
    
    Returns:
        Dict with results from each phase
    """
    # Initialize database if needed
    if seed_data:
        print("Initializing database with sample data...")
        init_with_sample_data(db_path)
    
    # Clear previous agent outputs if requested
    if reset_data:
        print("Clearing previous agent outputs...")
        clear_agent_outputs(db_path)
    
    # Create shared context
    ctx = MunicipalContext(db_path=db_path)
    
    print(f"\n{'#' * 60}")
    print(f"# MUNICIPAL VALUE-SCORE PIPELINE")
    print(f"# City: {ctx.city_name}")
    print(f"# Budget: ${ctx.quarterly_budget:,.0f}")
    print(f"# Horizon: {ctx.planning_horizon_weeks} weeks")
    print(f"{'#' * 60}")
    
    results = {}
    
    # Phase 1: Formation
    results["formation"] = await run_formation_phase(ctx)
    print("\nFormation Agent Output:")
    print("-" * 40)
    print(results["formation"])
    
    # Phase 2: Governance
    results["governance"] = await run_governance_phase(ctx)
    print("\nGovernance Agent Output:")
    print("-" * 40)
    print(results["governance"])
    
    # Phase 3: Scheduling
    results["scheduling"] = await run_scheduling_phase(ctx)
    print("\nScheduling Agent Output:")
    print("-" * 40)
    print(results["scheduling"])
    
    print(f"\n{'#' * 60}")
    print("# PIPELINE COMPLETE")
    print(f"{'#' * 60}")
    
    return results


def run_pipeline_sync(
    db_path: str = DB_PATH,
    reset_data: bool = False,
    seed_data: bool = False,
) -> dict:
    """Synchronous wrapper for run_full_pipeline."""
    return asyncio.run(run_full_pipeline(db_path, reset_data, seed_data))


# =============================================================================
# Individual Agent Runners (for interactive use)
# =============================================================================

async def run_agent_interactive(
    agent_name: str,
    prompt: str,
    db_path: str = DB_PATH,
) -> str:
    """
    Run a single agent with a custom prompt.
    
    Args:
        agent_name: "formation", "governance", or "scheduling"
        prompt: Custom instruction for the agent
        db_path: Path to database
    
    Returns:
        Agent's final output
    """
    ctx = MunicipalContext(db_path=db_path)
    
    agents = {
        "formation": formation_agent,
        "governance": governance_agent,
        "scheduling": scheduling_agent,
    }
    
    agent = agents.get(agent_name.lower())
    if not agent:
        raise ValueError(f"Unknown agent: {agent_name}. Use 'formation', 'governance', or 'scheduling'.")
    
    result = await Runner.run(agent, context=ctx, input=prompt)
    return result.final_output
