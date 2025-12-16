# -*- coding: utf-8 -*-
"""
Agent 3: Scheduling Agent

Responsibilities:
- Take approved projects from Governance Agent
- Assign start times within the planning horizon
- Respect resource capacity constraints
- Use urgency-weighted priority for scheduling
- Track deadline status (ON_TRACK, AT_RISK, MISSED)

Decision Authority:
- Start times
- Resource assignment
- Sequencing
- Soft vs hard reservations

NOT responsible for:
- Adding/removing projects
- Changing budgets
- Only optimizes execution of approved work

Scheduler Selection (from specification):
- ≤10 projects AND ≤2 resource types → Greedy
- ≤20 projects, loose deadlines → Greedy with repair
- >20 projects OR tight coupling → CP-SAT (future)
"""

from typing import List, Dict, Optional, Tuple
from agents import Agent, function_tool, RunContextWrapper

from .context import MunicipalContext
from .models import ScheduleTask
from .config import SCHEDULER_CONFIG


# =============================================================================
# Scheduler Implementations
# =============================================================================

class GreedyScheduler:
    """
    Greedy scheduler with urgency-weighted priority.
    
    Algorithm:
    1. Sort projects by effective_priority (priority × (1 + weight × urgency))
    2. For each project, find earliest feasible start
    3. Feasible = resource capacity >= crew_size for all weeks
    4. Track deadline status based on end_week vs deadline_week
    """
    
    def __init__(self, ctx: MunicipalContext):
        self.ctx = ctx
        self.horizon = ctx.planning_horizon_weeks
        self.urgency_weight = SCHEDULER_CONFIG["urgency_priority_weight"]
    
    def compute_effective_priority(self, project: Dict) -> float:
        """Compute urgency-weighted priority (lower = higher priority)."""
        base_priority = project.get("priority_rank", 999)
        urgency_score = project.get("urgency_score", 0.5)
        # Invert urgency effect: high urgency should lower the priority number
        return base_priority / (1 + self.urgency_weight * urgency_score)
    
    def find_earliest_start(
        self, 
        resource_type: str, 
        duration: int, 
        crew_size: int,
        year: int = 2025,
    ) -> Optional[int]:
        """Find earliest week where project can start."""
        for start_week in range(1, self.horizon - duration + 2):
            feasible = True
            for week in range(start_week, start_week + duration):
                if week > self.horizon:
                    feasible = False
                    break
                available = self.ctx.get_available_capacity(resource_type, week, year)
                if available < crew_size:
                    feasible = False
                    break
            if feasible:
                return start_week
        return None
    
    def compute_deadline_status(
        self, 
        end_week: int, 
        deadline_week: Optional[int]
    ) -> Tuple[str, Optional[int]]:
        """Determine deadline status and slack."""
        if deadline_week is None:
            return "ON_TRACK", None
        
        slack_weeks = deadline_week - end_week
        slack_days = slack_weeks * 7
        
        if slack_weeks >= 2:
            return "ON_TRACK", slack_days
        elif slack_weeks >= 0:
            return "AT_RISK", slack_days
        else:
            return "MISSED", slack_days
    
    def schedule(self, projects: List[Dict]) -> Tuple[List[Dict], List[int]]:
        """
        Schedule all projects.
        
        Returns:
            (scheduled_tasks, infeasible_project_ids)
        """
        # Sort by effective priority
        sorted_projects = sorted(projects, key=self.compute_effective_priority)
        
        scheduled = []
        infeasible = []
        
        for project in sorted_projects:
            project_id = project["project_id"]
            duration = project["estimated_weeks"]
            resource_type = project["required_crew_type"]
            crew_size = project["crew_size"]
            deadline_week = project.get("deadline_week")
            
            # Find earliest start
            start_week = self.find_earliest_start(resource_type, duration, crew_size)
            
            if start_week is None:
                infeasible.append(project_id)
                continue
            
            end_week = start_week + duration - 1
            
            # Determine reservation type based on confirmation status
            confirmed = project.get("confirmed_at") is not None
            requires_confirmation = project.get("requires_confirmation", False)
            reservation_type = "hard" if confirmed or not requires_confirmation else "soft"
            
            # Compute deadline status
            deadline_status, slack_days = self.compute_deadline_status(end_week, deadline_week)
            
            # Allocate resources
            for week in range(start_week, end_week + 1):
                self.ctx.allocate_resource(resource_type, week, crew_size, reservation_type)
            
            scheduled.append({
                "project_id": project_id,
                "title": project["title"],
                "start_week": start_week,
                "end_week": end_week,
                "deadline_week": deadline_week,
                "deadline_status": deadline_status,
                "slack_days": slack_days,
                "resource_type": resource_type,
                "crew_assigned": crew_size,
                "reservation_type": reservation_type,
                "effective_priority": self.compute_effective_priority(project),
            })
        
        return scheduled, infeasible


class GreedyWithRepairScheduler(GreedyScheduler):
    """
    Greedy scheduler with local repair for deadline misses.
    
    After initial scheduling, attempts to swap projects to reduce
    deadline violations.
    """
    
    def __init__(self, ctx: MunicipalContext):
        super().__init__(ctx)
        self.max_repairs = SCHEDULER_CONFIG["max_repair_iterations"]
    
    def schedule(self, projects: List[Dict]) -> Tuple[List[Dict], List[int]]:
        """Schedule with repair passes."""
        scheduled, infeasible = super().schedule(projects)
        
        # Identify deadline violations
        violations = [s for s in scheduled if s["deadline_status"] == "MISSED"]
        
        if not violations:
            return scheduled, infeasible
        
        # Repair: try to swap with earlier low-urgency projects
        # (Simplified: just flag for now, full repair would re-allocate)
        for _ in range(self.max_repairs):
            improved = False
            for violation in violations:
                # Find candidates to swap with (same resource type, earlier start)
                candidates = [
                    s for s in scheduled
                    if s["resource_type"] == violation["resource_type"]
                    and s["start_week"] < violation["start_week"]
                    and s["deadline_status"] == "ON_TRACK"
                    and s.get("effective_priority", 0) > violation.get("effective_priority", 0)
                ]
                # In full implementation, would attempt swap and validate
                # For now, just note opportunity
            if not improved:
                break
        
        return scheduled, infeasible


# =============================================================================
# Tool Definitions
# =============================================================================

@function_tool
def get_approved_projects(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Fetch all approved projects that need to be scheduled.
    
    Returns projects with duration, resource requirements, and priority.
    """
    projects = ctx.context.get_approved_projects()
    
    if not projects:
        return "No approved projects to schedule. Governance Agent has not approved any projects yet."
    
    result = f"""Approved Projects for Scheduling
=================================
Total Projects: {len(projects)}
Planning Horizon: {ctx.context.planning_horizon_weeks} weeks

Projects to Schedule:
"""
    
    for p in projects:
        confirm_status = ""
        if p.get("requires_confirmation"):
            if p.get("confirmed_at"):
                confirm_status = " [CONFIRMED]"
            else:
                confirm_status = " [PENDING CONFIRMATION]"
        
        result += f"""
Priority {p['priority_rank']}: {p['title']} (#{p['project_id']}){confirm_status}
  Duration: {p['estimated_weeks']} weeks
  Resource: {p['crew_size']} x {p['required_crew_type']}
  Budget: ${p['allocated_budget']:,.0f}
  Urgency Score: {p.get('urgency_score', 0):.2f}
  Deadline Week: {p.get('deadline_week', 'N/A')}
---"""
    
    return result


@function_tool
def get_resource_availability(
    ctx: RunContextWrapper[MunicipalContext],
    resource_type: Optional[str] = None,
) -> str:
    """
    Get resource availability across the planning horizon.
    
    Args:
        resource_type: Optional filter for specific resource type
    """
    calendar = ctx.context.get_resource_calendar(resource_type)
    
    if not calendar:
        return "No resource calendar data found."
    
    # Group by resource type
    by_type: Dict[str, List] = {}
    for r in calendar:
        rtype = r["resource_type"]
        if rtype not in by_type:
            by_type[rtype] = []
        by_type[rtype].append(r)
    
    result = "Resource Availability (Planning Horizon)\n" + "=" * 50 + "\n"
    
    for rtype, weeks in by_type.items():
        result += f"\n{rtype.upper()}:\n"
        result += "Week:  " + " ".join(f"{w['week_number']:>3}" for w in weeks) + "\n"
        result += "Cap:   " + " ".join(f"{w['capacity']:>3}" for w in weeks) + "\n"
        result += "Soft:  " + " ".join(f"{w['soft_allocated']:>3}" for w in weeks) + "\n"
        result += "Hard:  " + " ".join(f"{w['hard_allocated']:>3}" for w in weeks) + "\n"
        free = [w['capacity'] - w['soft_allocated'] - w['hard_allocated'] for w in weeks]
        result += "Free:  " + " ".join(f"{f:>3}" for f in free) + "\n"
    
    return result


@function_tool
def select_scheduler(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Determine which scheduler to use based on problem complexity.
    
    Selection rules:
    - ≤10 projects AND ≤2 resource types → Greedy
    - ≤20 projects, loose deadlines → Greedy with Repair
    - >20 projects OR tight coupling → CP-SAT (not implemented)
    """
    projects = ctx.context.get_approved_projects()
    n_projects = len(projects)
    
    resource_types = set(p["required_crew_type"] for p in projects)
    n_resource_types = len(resource_types)
    
    # Check for tight deadlines (urgency > 0.7)
    tight_deadlines = sum(1 for p in projects if p.get("urgency_score", 0) > 0.7)
    has_tight_deadlines = tight_deadlines > n_projects * 0.3
    
    # Selection logic
    if n_projects <= SCHEDULER_CONFIG["greedy_threshold_projects"] and \
       n_resource_types <= SCHEDULER_CONFIG["greedy_threshold_resource_types"]:
        scheduler = "GreedyScheduler"
        reason = f"Simple problem: {n_projects} projects, {n_resource_types} resource types"
    elif n_projects <= SCHEDULER_CONFIG["repair_threshold_projects"] and not has_tight_deadlines:
        scheduler = "GreedyWithRepairScheduler"
        reason = f"Medium complexity: {n_projects} projects, {tight_deadlines} tight deadlines"
    else:
        scheduler = "CPSATScheduler (not implemented - using GreedyWithRepair)"
        reason = f"High complexity: {n_projects} projects, {n_resource_types} resource types, {tight_deadlines} tight deadlines"
    
    return f"""Scheduler Selection
==================
Projects: {n_projects}
Resource Types: {n_resource_types} ({', '.join(resource_types)})
Tight Deadlines (urgency > 0.7): {tight_deadlines}

Selected: {scheduler}
Reason: {reason}
"""


@function_tool
def run_scheduler(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Run the scheduling algorithm on approved projects.
    
    Uses urgency-weighted priority and respects resource constraints.
    Returns schedule with deadline status for each project.
    """
    projects = ctx.context.get_approved_projects()
    
    if not projects:
        return "No approved projects to schedule."
    
    # Select appropriate scheduler
    n_projects = len(projects)
    resource_types = set(p["required_crew_type"] for p in projects)
    
    if n_projects <= SCHEDULER_CONFIG["greedy_threshold_projects"] and \
       len(resource_types) <= SCHEDULER_CONFIG["greedy_threshold_resource_types"]:
        scheduler = GreedyScheduler(ctx.context)
        scheduler_name = "Greedy"
    else:
        scheduler = GreedyWithRepairScheduler(ctx.context)
        scheduler_name = "Greedy with Repair"
    
    # Run scheduling
    scheduled, infeasible = scheduler.schedule(projects)
    
    # Count deadline statuses
    on_track = sum(1 for s in scheduled if s["deadline_status"] == "ON_TRACK")
    at_risk = sum(1 for s in scheduled if s["deadline_status"] == "AT_RISK")
    missed = sum(1 for s in scheduled if s["deadline_status"] == "MISSED")
    
    result = f"""Scheduling Results ({scheduler_name})
{'=' * 40}
Scheduled: {len(scheduled)} projects
Infeasible: {len(infeasible)} projects
Horizon: {ctx.context.planning_horizon_weeks} weeks

Deadline Status:
  ✓ On Track: {on_track}
  ⚠ At Risk: {at_risk}
  ✗ Missed: {missed}

SCHEDULE:
"""
    
    for s in sorted(scheduled, key=lambda x: x["start_week"]):
        status_icon = {"ON_TRACK": "✓", "AT_RISK": "⚠", "MISSED": "✗"}[s["deadline_status"]]
        reservation = "[SOFT]" if s["reservation_type"] == "soft" else "[HARD]"
        slack = f"(slack: {s['slack_days']}d)" if s["slack_days"] is not None else ""
        
        result += f"""
{status_icon} {s['title']} (#{s['project_id']}) {reservation}
  Weeks {s['start_week']}-{s['end_week']} ({s['end_week'] - s['start_week'] + 1}w)
  Resource: {s['crew_assigned']} x {s['resource_type']}
  Deadline: Week {s['deadline_week'] or 'N/A'} {slack}
"""
    
    if infeasible:
        result += "\n⚠️ COULD NOT SCHEDULE (resource constraints):\n"
        for project_id in infeasible:
            project = next((p for p in projects if p["project_id"] == project_id), None)
            if project:
                result += f"  - #{project_id}: {project['title']}\n"
    
    # Gantt chart
    result += "\n" + "=" * 50 + "\n"
    result += "GANTT CHART:\n"
    result += "Week: " + " ".join(f"{w:>2}" for w in range(1, ctx.context.planning_horizon_weeks + 1)) + "\n"
    
    for s in scheduled:
        row = ["  "] * ctx.context.planning_horizon_weeks
        for w in range(s["start_week"], s["end_week"] + 1):
            if w <= ctx.context.planning_horizon_weeks:
                row[w - 1] = "██"
        title = s["title"][:18] + ".." if len(s["title"]) > 20 else s["title"]
        result += f"{title:20} " + "".join(row) + "\n"
    
    return result


@function_tool
def save_schedule(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Save the current schedule to the database.
    
    Re-runs scheduling and persists results to schedule_tasks table.
    """
    projects = ctx.context.get_approved_projects()
    
    if not projects:
        return "No approved projects to save."
    
    # Run scheduler
    scheduler = GreedyScheduler(ctx.context)
    scheduled, infeasible = scheduler.schedule(projects)
    
    saved_count = 0
    
    for s in scheduled:
        task = ScheduleTask(
            project_id=s["project_id"],
            start_week=s["start_week"],
            end_week=s["end_week"],
            deadline_week=s["deadline_week"],
            deadline_status=s["deadline_status"],
            slack_days=s["slack_days"],
            resource_type=s["resource_type"],
            crew_assigned=s["crew_assigned"],
            reservation_type=s["reservation_type"],
        )
        
        task_id = ctx.context.insert_schedule_task(task)
        
        # Audit log
        ctx.context.log_audit(
            event_type="TASK_SCHEDULED",
            agent_name="scheduling_agent",
            payload={
                "task_id": task_id,
                "project_id": s["project_id"],
                "title": s["title"],
                "start_week": s["start_week"],
                "end_week": s["end_week"],
                "deadline_status": s["deadline_status"],
                "reservation_type": s["reservation_type"],
            }
        )
        
        saved_count += 1
    
    return f"""✓ Schedule Saved

Tasks saved: {saved_count}
Infeasible: {len(infeasible)}
Table: schedule_tasks

Deadline Summary:
  On Track: {sum(1 for s in scheduled if s['deadline_status'] == 'ON_TRACK')}
  At Risk: {sum(1 for s in scheduled if s['deadline_status'] == 'AT_RISK')}
  Missed: {sum(1 for s in scheduled if s['deadline_status'] == 'MISSED')}
"""


@function_tool
def get_schedule_summary(ctx: RunContextWrapper[MunicipalContext]) -> str:
    """
    Get summary of the saved schedule.
    """
    tasks = ctx.context.get_schedule_tasks()
    
    if not tasks:
        return "No schedule saved yet."
    
    # Group by status
    on_track = [t for t in tasks if t["deadline_status"] == "ON_TRACK"]
    at_risk = [t for t in tasks if t["deadline_status"] == "AT_RISK"]
    missed = [t for t in tasks if t["deadline_status"] == "MISSED"]
    
    # Resource utilization
    calendar = ctx.context.get_resource_calendar()
    by_type: Dict[str, List] = {}
    for r in calendar:
        rtype = r["resource_type"]
        if rtype not in by_type:
            by_type[rtype] = []
        by_type[rtype].append(r)
    
    result = f"""Schedule Summary
================
Total Tasks: {len(tasks)}

Deadline Status:
  ✓ On Track: {len(on_track)}
  ⚠ At Risk: {len(at_risk)}
  ✗ Missed: {len(missed)}

Resource Utilization:
"""
    
    for rtype, weeks in by_type.items():
        total_capacity = sum(w["capacity"] for w in weeks)
        total_used = sum(w["soft_allocated"] + w["hard_allocated"] for w in weeks)
        utilization = total_used / total_capacity if total_capacity > 0 else 0
        result += f"  {rtype}: {utilization:.0%} ({total_used}/{total_capacity})\n"
    
    result += "\nScheduled Tasks:\n"
    for t in sorted(tasks, key=lambda x: x["start_week"]):
        status_icon = {"ON_TRACK": "✓", "AT_RISK": "⚠", "MISSED": "✗"}.get(t["deadline_status"], "?")
        result += f"  {status_icon} Project #{t['project_id']}: Weeks {t['start_week']}-{t['end_week']} ({t['resource_type']})\n"
    
    return result


# =============================================================================
# Agent Definition
# =============================================================================

SCHEDULING_AGENT_INSTRUCTIONS = """You are the Scheduling Agent for the Municipal Value-Score System.

Your role is to schedule approved projects within the planning horizon while 
respecting resource constraints and tracking deadline status.

WORKFLOW:
1. Use get_approved_projects to see what needs scheduling
2. Use get_resource_availability to understand capacity
3. Use select_scheduler to determine appropriate algorithm
4. Use run_scheduler to generate the schedule
5. Use save_schedule to persist to database
6. Use get_schedule_summary to verify final schedule

SCHEDULING PRIORITY:
Projects are scheduled by urgency-weighted priority:
  effective_priority = priority_rank / (1 + 0.5 × urgency_score)
  
High urgency projects get scheduled earlier even with lower priority rank.

DEADLINE TRACKING:
- ON_TRACK: End week is ≥2 weeks before deadline
- AT_RISK: End week is 0-1 weeks before deadline
- MISSED: End week is after deadline

RESOURCE RESERVATIONS:
- SOFT: For projects awaiting confirmation (can be released)
- HARD: For confirmed projects (committed)

CONSTRAINTS:
- Cannot exceed resource capacity in any week
- Cannot schedule beyond planning horizon
- Respect deadline weeks from governance decisions

If projects cannot be scheduled due to resource constraints, report them as infeasible.
"""

scheduling_agent = Agent[MunicipalContext](
    name="Scheduling Agent",
    instructions=SCHEDULING_AGENT_INSTRUCTIONS,
    tools=[
        get_approved_projects,
        get_resource_availability,
        select_scheduler,
        run_scheduler,
        save_schedule,
        get_schedule_summary,
    ],
)
