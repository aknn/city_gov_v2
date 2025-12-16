# -*- coding: utf-8 -*-
"""
Shared context for Municipal Value-Score System agents.

Provides database access, configuration, and utility methods
shared across Formation, Governance, and Scheduling agents.
"""

import sqlite3
import json
from typing import List, Dict, Optional, Any
from datetime import datetime, date, timedelta
from dataclasses import dataclass, field

from .config import (
    DB_PATH,
    CITY_PROFILE,
    CREW_MAPPING,
    GOVERNANCE_CONFIG,
    EQUITY_CONFIG,
)
from .database import get_connection
from .scoring import CompositeScorer, BenefitNormalizer, compute_district_service_ratios
from .models import (
    IssueWithSignal,
    ProjectCandidate,
    PortfolioDecision,
    ScheduleTask,
    ScoreComponents,
)


@dataclass
class MunicipalContext:
    """
    Shared context for all agents in the municipal pipeline.
    
    Provides:
    - Database access methods
    - City configuration
    - Scoring engine
    - Audit logging
    """
    
    db_path: str = DB_PATH
    city_name: str = field(default_factory=lambda: CITY_PROFILE["city_name"])
    city_population: int = field(default_factory=lambda: CITY_PROFILE["population"])
    quarterly_budget: float = field(default_factory=lambda: CITY_PROFILE["quarterly_budget"])
    planning_horizon_weeks: int = field(default_factory=lambda: CITY_PROFILE["planning_horizon_weeks"])
    
    # Lazy-loaded components
    _scorer: Optional[CompositeScorer] = field(default=None, repr=False)
    
    # =========================================================================
    # Scoring Engine
    # =========================================================================
    
    @property
    def scorer(self) -> CompositeScorer:
        """Get or create the composite scorer."""
        if self._scorer is None:
            # Load district service ratios for equity calculation
            district_ratios = self._load_district_service_ratios()
            self._scorer = CompositeScorer(
                benefit_normalizer=BenefitNormalizer.from_config(),
                district_service_ratios=district_ratios,
            )
        return self._scorer
    
    def _load_district_service_ratios(self) -> Dict[int, float]:
        """Load district service ratios from database."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        # Get district populations and project counts
        cursor.execute("""
            SELECT d.district_id, d.population, 
                   COALESCE(da.project_count, 0) as project_count
            FROM districts d
            LEFT JOIN district_allocations da 
                ON d.district_id = da.district_id
                AND da.year = strftime('%Y', 'now')
        """)
        
        districts = [dict(row) for row in cursor.fetchall()]
        
        # Get city totals
        cursor.execute("SELECT SUM(population) FROM districts")
        city_pop = cursor.fetchone()[0] or self.city_population
        
        cursor.execute("""
            SELECT COALESCE(SUM(project_count), 0) 
            FROM district_allocations 
            WHERE year = strftime('%Y', 'now')
        """)
        city_projects = cursor.fetchone()[0] or 1  # Avoid division by zero
        
        conn.close()
        
        return compute_district_service_ratios(districts, city_pop, city_projects)
    
    def compute_project_scores(self, signal: IssueWithSignal, feasibility: float = 1.0) -> ScoreComponents:
        """Compute composite score for an issue/signal."""
        return self.scorer.compute_composite(signal, feasibility, signal.district_id)
    
    # =========================================================================
    # Issue Retrieval
    # =========================================================================
    
    def get_open_issues(self) -> List[IssueWithSignal]:
        """Get all open issues with their signals."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                i.issue_id, i.title, i.category, i.description, i.source, 
                i.district_id, i.status,
                s.population_affected, s.complaint_count, s.safety_tier,
                s.mandate_tier, s.estimated_cost, s.urgency_days
            FROM issues i
            JOIN issue_signals s ON i.issue_id = s.issue_id
            WHERE i.status = 'OPEN'
            ORDER BY s.urgency_days ASC
        """)
        
        issues = []
        for row in cursor.fetchall():
            issues.append(IssueWithSignal(
                issue_id=row["issue_id"],
                title=row["title"],
                category=row["category"],
                description=row["description"],
                source=row["source"],
                district_id=row["district_id"],
                status=row["status"],
                population_affected=row["population_affected"],
                complaint_count=row["complaint_count"],
                safety_tier=row["safety_tier"],
                mandate_tier=row["mandate_tier"],
                estimated_cost=row["estimated_cost"],
                urgency_days=row["urgency_days"],
            ))
        
        conn.close()
        return issues
    
    def get_issue_by_id(self, issue_id: int) -> Optional[IssueWithSignal]:
        """Get a single issue with its signal."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                i.issue_id, i.title, i.category, i.description, i.source,
                i.district_id, i.status,
                s.population_affected, s.complaint_count, s.safety_tier,
                s.mandate_tier, s.estimated_cost, s.urgency_days
            FROM issues i
            JOIN issue_signals s ON i.issue_id = s.issue_id
            WHERE i.issue_id = ?
        """, (issue_id,))
        
        row = cursor.fetchone()
        conn.close()
        
        if not row:
            return None
        
        return IssueWithSignal(
            issue_id=row["issue_id"],
            title=row["title"],
            category=row["category"],
            description=row["description"],
            source=row["source"],
            district_id=row["district_id"],
            status=row["status"],
            population_affected=row["population_affected"],
            complaint_count=row["complaint_count"],
            safety_tier=row["safety_tier"],
            mandate_tier=row["mandate_tier"],
            estimated_cost=row["estimated_cost"],
            urgency_days=row["urgency_days"],
        )
    
    # =========================================================================
    # Project Candidates
    # =========================================================================
    
    def insert_project_candidate(self, project: ProjectCandidate) -> int:
        """Insert a project candidate and return its ID."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO project_candidates (
                issue_id, title, scope, estimated_cost, estimated_weeks,
                required_crew_type, crew_size,
                composite_score, safety_score, mandate_score, benefit_score,
                urgency_score, feasibility_estimate, feasibility_confirmed,
                feasibility_override, equity_tier, equity_multiplier, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            project.issue_id, project.title, project.scope,
            project.estimated_cost, project.estimated_weeks,
            project.required_crew_type, project.crew_size,
            project.composite_score, project.safety_score, project.mandate_score,
            project.benefit_score, project.urgency_score,
            project.feasibility_estimate, int(project.feasibility_confirmed),
            project.feasibility_override, project.equity_tier,
            project.equity_multiplier, project.created_by,
        ))
        
        project_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return project_id
    
    def get_project_candidates(self) -> List[Dict[str, Any]]:
        """Get all project candidates."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT * FROM project_candidates
            ORDER BY composite_score DESC
        """)
        
        candidates = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return candidates
    
    def get_project_by_id(self, project_id: int) -> Optional[Dict[str, Any]]:
        """Get a single project candidate."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM project_candidates WHERE project_id = ?", (project_id,))
        row = cursor.fetchone()
        conn.close()
        
        return dict(row) if row else None
    
    # =========================================================================
    # Portfolio Decisions
    # =========================================================================
    
    def insert_portfolio_decision(self, decision: PortfolioDecision) -> int:
        """Insert a portfolio decision and return its ID."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO portfolio_decisions (
                project_id, decision, allocated_budget, priority_rank, rationale,
                deadline_week, requires_confirmation, confirmation_deadline,
                confirmed_at, confirmed_by, decided_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            decision.project_id, decision.decision, decision.allocated_budget,
            decision.priority_rank, decision.rationale, decision.deadline_week,
            int(decision.requires_confirmation), decision.confirmation_deadline,
            decision.confirmed_at, decision.confirmed_by, decision.decided_by,
        ))
        
        decision_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        return decision_id
    
    def get_portfolio_decisions(self) -> List[Dict[str, Any]]:
        """Get all portfolio decisions."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM portfolio_decisions ORDER BY priority_rank")
        decisions = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return decisions
    
    def get_approved_projects(self) -> List[Dict[str, Any]]:
        """Get approved projects with their details for scheduling."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                p.project_id, p.title, p.estimated_cost, p.estimated_weeks,
                p.required_crew_type, p.crew_size, p.composite_score,
                p.urgency_score,
                d.allocated_budget, d.priority_rank, d.deadline_week,
                d.requires_confirmation, d.confirmed_at
            FROM project_candidates p
            JOIN portfolio_decisions d ON p.project_id = d.project_id
            WHERE d.decision IN ('APPROVED', 'APPROVED_WITH_CONDITIONS')
            ORDER BY d.priority_rank
        """)
        
        projects = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return projects
    
    # =========================================================================
    # Resource Calendar
    # =========================================================================
    
    def get_resource_calendar(self, resource_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get resource calendar, optionally filtered by type."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        if resource_type:
            cursor.execute(
                "SELECT * FROM resource_calendar WHERE resource_type = ? ORDER BY week_number",
                (resource_type,)
            )
        else:
            cursor.execute("SELECT * FROM resource_calendar ORDER BY resource_type, week_number")
        
        calendar = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return calendar
    
    def get_available_capacity(self, resource_type: str, week: int, year: int = 2025) -> int:
        """Get available capacity for a resource in a specific week."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT capacity - soft_allocated - hard_allocated as available
            FROM resource_calendar
            WHERE resource_type = ? AND week_number = ? AND year = ?
        """, (resource_type, week, year))
        
        row = cursor.fetchone()
        conn.close()
        
        return row["available"] if row else 0
    
    def allocate_resource(
        self, 
        resource_type: str, 
        week: int, 
        amount: int, 
        reservation_type: str = "soft",
        year: int = 2025
    ) -> bool:
        """Allocate resource capacity for a week."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        column = "soft_allocated" if reservation_type == "soft" else "hard_allocated"
        
        cursor.execute(f"""
            UPDATE resource_calendar
            SET {column} = {column} + ?
            WHERE resource_type = ? AND week_number = ? AND year = ?
        """, (amount, resource_type, week, year))
        
        success = cursor.rowcount > 0
        conn.commit()
        conn.close()
        return success
    
    def release_soft_reservations(self, project_id: int) -> None:
        """Release soft reservations for a project (on expiry)."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        # Get scheduled tasks for this project
        cursor.execute("""
            SELECT resource_type, start_week, end_week, crew_assigned
            FROM schedule_tasks
            WHERE project_id = ? AND reservation_type = 'soft'
        """, (project_id,))
        
        tasks = cursor.fetchall()
        
        for task in tasks:
            for week in range(task["start_week"], task["end_week"] + 1):
                cursor.execute("""
                    UPDATE resource_calendar
                    SET soft_allocated = soft_allocated - ?
                    WHERE resource_type = ? AND week_number = ?
                """, (task["crew_assigned"], task["resource_type"], week))
        
        # Mark tasks as expired
        cursor.execute("""
            UPDATE schedule_tasks
            SET status = 'EXPIRED'
            WHERE project_id = ? AND reservation_type = 'soft'
        """, (project_id,))
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # Schedule Tasks
    # =========================================================================
    
    def insert_schedule_task(self, task: ScheduleTask) -> int:
        """Insert a schedule task and return its ID."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO schedule_tasks (
                project_id, start_week, end_week, deadline_week, deadline_status,
                slack_days, resource_type, crew_assigned, reservation_type,
                status, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task.project_id, task.start_week, task.end_week, task.deadline_week,
            task.deadline_status, task.slack_days, task.resource_type,
            task.crew_assigned, task.reservation_type, task.status, task.created_by,
        ))
        
        task_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return task_id
    
    def get_schedule_tasks(self) -> List[Dict[str, Any]]:
        """Get all scheduled tasks."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM schedule_tasks ORDER BY start_week")
        tasks = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return tasks
    
    # =========================================================================
    # Crew Type Mapping
    # =========================================================================
    
    def get_crew_type(self, category: str) -> str:
        """Get required crew type for an issue category."""
        return CREW_MAPPING.get(category, "general_crew")
    
    # =========================================================================
    # Audit Logging
    # =========================================================================
    
    def log_audit(self, event_type: str, agent_name: str, payload: Dict[str, Any]) -> None:
        """Log an audit event."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO audit_log (event_type, agent_name, payload)
            VALUES (?, ?, ?)
        """, (event_type, agent_name, json.dumps(payload)))
        
        conn.commit()
        conn.close()
    
    def log_scoring_audit(
        self,
        project_id: int,
        score_type: str,
        source: str,
        actor_id: str,
        original_value: float,
        final_value: float,
        override_reason: Optional[str] = None,
    ) -> None:
        """Log a scoring audit entry for provenance."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO scoring_audit (
                project_id, score_type, source, actor_id,
                original_value, final_value, override_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            project_id, score_type, source, actor_id,
            original_value, final_value, override_reason,
        ))
        
        conn.commit()
        conn.close()
    
    # =========================================================================
    # Budget Tracking
    # =========================================================================
    
    def get_budget_status(self) -> Dict[str, float]:
        """Get current budget allocation status."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COALESCE(SUM(allocated_budget), 0) as allocated
            FROM portfolio_decisions
            WHERE decision IN ('APPROVED', 'APPROVED_WITH_CONDITIONS')
        """)
        
        allocated = cursor.fetchone()["allocated"]
        conn.close()
        
        return {
            "total_budget": self.quarterly_budget,
            "allocated": allocated,
            "remaining": self.quarterly_budget - allocated,
        }
    
    # =========================================================================
    # District Equity
    # =========================================================================
    
    def get_district_allocations(self) -> List[Dict[str, Any]]:
        """Get current district allocation status."""
        conn = get_connection(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT d.district_id, d.name, d.population,
                   COALESCE(da.allocated_budget, 0) as allocated_budget,
                   COALESCE(da.project_count, 0) as project_count,
                   (d.population * 1.0 / (SELECT SUM(population) FROM districts)) * ? as fair_share
            FROM districts d
            LEFT JOIN district_allocations da 
                ON d.district_id = da.district_id
                AND da.year = strftime('%Y', 'now')
        """, (self.quarterly_budget,))
        
        allocations = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return allocations
    
    def check_equity_constraint(self, district_id: int, additional_budget: float) -> Tuple[bool, str]:
        """Check if adding budget to a district would violate equity constraints."""
        allocations = self.get_district_allocations()
        
        district = next((a for a in allocations if a["district_id"] == district_id), None)
        if not district:
            return True, "District not found"
        
        fair_share = district["fair_share"]
        current = district["allocated_budget"]
        projected = current + additional_budget
        
        defer_threshold = EQUITY_CONFIG["defer_threshold"]
        
        if projected > fair_share * defer_threshold:
            return False, f"District would exceed {defer_threshold}× fair share (${fair_share:,.0f})"
        
        return True, "OK"


# Type alias for use in agent tools
from typing import Tuple
