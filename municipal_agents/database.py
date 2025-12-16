# -*- coding: utf-8 -*-
"""
Database schema and initialization for Municipal Value-Score System v2.

Implements the full schema from SPECIFICATION_v1.md with:
- Enhanced issue_signals with tiered fields
- Composite scoring fields on project_candidates
- Soft/hard resource reservations
- Confirmation workflow fields
- Structured scoring audit trail
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
from typing import Optional

from .config import DB_PATH, RESOURCE_CAPACITIES


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Get a database connection with row factory enabled."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(db_path: str = DB_PATH) -> None:
    """
    Initialize the database with all required tables.
    
    Tables:
    - issues: Raw citizen complaints/demands (input)
    - issue_signals: Risk/impact signals with tiered fields
    - districts: Geographic districts for equity tracking
    - project_candidates: Agent 1 output with composite scoring
    - portfolio_decisions: Agent 2 output with confirmation workflow
    - resource_calendar: Resources with soft/hard allocations
    - schedule_tasks: Agent 3 output with deadline tracking
    - district_allocations: Quarterly equity tracking
    - scoring_audit: Provenance trail for score components
    - scoring_config: Tunable parameters storage
    - audit_log: General audit trail
    """
    os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # =========================================================================
    # 1. Districts (for equity tracking)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS districts (
        district_id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        population INTEGER NOT NULL CHECK(population > 0)
    )
    """)
    
    # =========================================================================
    # 2. Issues (input - citizen complaints, reports, mandates)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS issues (
        issue_id INTEGER PRIMARY KEY,
        title TEXT NOT NULL,
        category TEXT NOT NULL,
        description TEXT,
        source TEXT DEFAULT 'citizen_complaint',
        district_id INTEGER,
        status TEXT DEFAULT 'OPEN',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(district_id) REFERENCES districts(district_id)
    )
    """)
    
    # =========================================================================
    # 3. Issue Signals (input - quantified impact/risk metrics with tiers)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS issue_signals (
        issue_id INTEGER PRIMARY KEY,
        population_affected INTEGER CHECK(population_affected >= 0),
        complaint_count INTEGER CHECK(complaint_count >= 0),
        safety_tier TEXT DEFAULT 'none' 
            CHECK(safety_tier IN ('none', 'moderate', 'severe', 'critical')),
        mandate_tier TEXT DEFAULT 'none'
            CHECK(mandate_tier IN ('none', 'advisory', 'required', 'court_ordered')),
        estimated_cost INTEGER,
        urgency_days INTEGER DEFAULT 90,
        FOREIGN KEY(issue_id) REFERENCES issues(issue_id)
    )
    """)
    
    # =========================================================================
    # 4. Project Candidates (Agent 1 Output - with composite scoring)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS project_candidates (
        project_id INTEGER PRIMARY KEY AUTOINCREMENT,
        issue_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        scope TEXT,
        estimated_cost REAL NOT NULL,
        estimated_weeks INTEGER NOT NULL,
        required_crew_type TEXT DEFAULT 'general_crew',
        crew_size INTEGER DEFAULT 1,
        
        -- Composite scoring components
        composite_score REAL,
        safety_score REAL,
        mandate_score REAL,
        benefit_score REAL,
        urgency_score REAL,
        feasibility_estimate REAL DEFAULT 1.0,
        feasibility_confirmed INTEGER DEFAULT 0,
        feasibility_override REAL,
        equity_tier TEXT,
        equity_multiplier REAL DEFAULT 1.0,
        
        -- Metadata
        created_by TEXT DEFAULT 'formation_agent',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY(issue_id) REFERENCES issues(issue_id)
    )
    """)
    
    # =========================================================================
    # 5. Portfolio Decisions (Agent 2 Output - with confirmation workflow)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS portfolio_decisions (
        decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        decision TEXT CHECK(decision IN (
            'APPROVED', 'APPROVED_WITH_CONDITIONS', 'DEFERRED', 'REJECTED', 'EXPIRED'
        )),
        allocated_budget REAL,
        priority_rank INTEGER,
        rationale TEXT,
        deadline_week INTEGER,
        
        -- Confirmation workflow
        requires_confirmation INTEGER DEFAULT 0,
        confirmation_deadline DATE,
        confirmed_at TIMESTAMP,
        confirmed_by TEXT,
        
        -- Metadata
        decided_by TEXT DEFAULT 'governance_agent',
        decided_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        
        FOREIGN KEY(project_id) REFERENCES project_candidates(project_id)
    )
    """)
    
    # =========================================================================
    # 6. Resource Calendar (with soft/hard allocations)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS resource_calendar (
        resource_id INTEGER PRIMARY KEY AUTOINCREMENT,
        resource_type TEXT NOT NULL,
        week_number INTEGER NOT NULL,
        year INTEGER NOT NULL,
        capacity INTEGER NOT NULL,
        soft_allocated INTEGER DEFAULT 0,
        hard_allocated INTEGER DEFAULT 0,
        UNIQUE(resource_type, week_number, year),
        CHECK(soft_allocated + hard_allocated <= capacity)
    )
    """)
    
    # =========================================================================
    # 7. Schedule Tasks (Agent 3 Output - with deadline tracking)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS schedule_tasks (
        task_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        start_week INTEGER NOT NULL,
        end_week INTEGER NOT NULL,
        deadline_week INTEGER,
        deadline_status TEXT DEFAULT 'ON_TRACK'
            CHECK(deadline_status IN ('ON_TRACK', 'AT_RISK', 'MISSED')),
        slack_days INTEGER,
        resource_type TEXT NOT NULL,
        crew_assigned INTEGER DEFAULT 1,
        reservation_type TEXT DEFAULT 'soft'
            CHECK(reservation_type IN ('soft', 'hard')),
        status TEXT DEFAULT 'SCHEDULED',
        created_by TEXT DEFAULT 'scheduling_agent',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES project_candidates(project_id)
    )
    """)
    
    # =========================================================================
    # 8. District Allocations (quarterly equity tracking)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS district_allocations (
        district_id INTEGER NOT NULL,
        quarter TEXT NOT NULL,
        year INTEGER NOT NULL,
        population INTEGER,
        fair_share_budget REAL,
        allocated_budget REAL DEFAULT 0,
        project_count INTEGER DEFAULT 0,
        equity_ratio REAL,
        PRIMARY KEY(district_id, quarter, year),
        FOREIGN KEY(district_id) REFERENCES districts(district_id)
    )
    """)
    
    # =========================================================================
    # 9. Scoring Audit (provenance trail)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scoring_audit (
        audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id INTEGER NOT NULL,
        score_type TEXT NOT NULL,
        source TEXT CHECK(source IN ('agent', 'human')),
        actor_id TEXT,
        original_value REAL,
        final_value REAL,
        override_reason TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(project_id) REFERENCES project_candidates(project_id)
    )
    """)
    
    # =========================================================================
    # 10. Scoring Config (tunable parameters)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS scoring_config (
        config_key TEXT PRIMARY KEY,
        config_value TEXT,  -- JSON serialized
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    # =========================================================================
    # 11. Audit Log (general trail)
    # =========================================================================
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        log_id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_type TEXT NOT NULL,
        agent_name TEXT NOT NULL,
        payload TEXT,  -- JSON serialized
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)
    
    conn.commit()
    conn.close()
    print("✓ Database schema initialized")


def seed_districts(db_path: str = DB_PATH) -> None:
    """Seed sample districts for equity tracking."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    districts = [
        (1, "Downtown", 450000),
        (2, "Northside", 380000),
        (3, "Eastborough", 320000),
        (4, "Riverside", 280000),
        (5, "Westend", 420000),
        (6, "Southgate", 350000),
        (7, "Industrial", 150000),
        (8, "University", 150000),
    ]
    
    cursor.executemany(
        "INSERT OR REPLACE INTO districts (district_id, name, population) VALUES (?, ?, ?)",
        districts
    )
    
    conn.commit()
    conn.close()
    print("✓ Districts seeded")


def seed_resource_calendar(db_path: str = DB_PATH, weeks: int = 12, year: int = 2025) -> None:
    """Seed resource calendar with default capacities."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clear existing calendar for this year
    cursor.execute("DELETE FROM resource_calendar WHERE year = ?", (year,))
    
    for week in range(1, weeks + 1):
        for resource_type, capacity in RESOURCE_CAPACITIES.items():
            cursor.execute(
                """INSERT INTO resource_calendar 
                   (resource_type, week_number, year, capacity, soft_allocated, hard_allocated) 
                   VALUES (?, ?, ?, ?, 0, 0)""",
                (resource_type, week, year, capacity)
            )
    
    conn.commit()
    conn.close()
    print(f"✓ Resource calendar seeded ({weeks} weeks)")


def seed_sample_issues(db_path: str = DB_PATH) -> None:
    """Seed sample issues with the new tiered signal schema."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Clear existing data
    cursor.execute("DELETE FROM schedule_tasks")
    cursor.execute("DELETE FROM portfolio_decisions")
    cursor.execute("DELETE FROM project_candidates")
    cursor.execute("DELETE FROM scoring_audit")
    cursor.execute("DELETE FROM issue_signals")
    cursor.execute("DELETE FROM issues")
    cursor.execute("DELETE FROM audit_log")
    
    # Sample Issues with district assignments
    issues_data = [
        (1, "Major Water Pipeline Rupture", "Water",
         "Critical water main break affecting downtown area", "emergency_report", 1, "OPEN"),
        (2, "Hospital Power Backup Failure", "Health",
         "Primary backup generator at City Hospital non-functional", "facility_inspection", 2, "OPEN"),
        (3, "Urban Flooding in Low-Lying Areas", "Disaster Management",
         "Recurring flooding in Districts 4 and 7 during monsoon", "citizen_complaint", 4, "OPEN"),
        (4, "Pothole Complaints in Residential Zones", "Infrastructure",
         "Multiple potholes reported on Main St and Oak Ave", "citizen_complaint", 5, "OPEN"),
        (5, "Public Park Renovation", "Recreation",
         "Central Park playground equipment outdated", "council_request", 3, "OPEN"),
        (6, "Street Light Outages", "Infrastructure",
         "Multiple street lights non-functional in Sector 12", "citizen_complaint", 6, "OPEN"),
        (7, "School Zone Safety Improvements", "Education",
         "Need for crosswalks and speed bumps near Lincoln Elementary", "citizen_complaint", 8, "OPEN"),
        (8, "Bridge Structural Assessment", "Infrastructure",
         "Main Street bridge showing signs of deterioration", "facility_inspection", 1, "OPEN"),
        (9, "Community Center HVAC Replacement", "Recreation",
         "Aging HVAC system in Southgate Community Center", "facility_inspection", 6, "OPEN"),
        (10, "Stormwater Drain Capacity Upgrade", "Water",
         "Drains overflow during heavy rain in Eastborough", "citizen_complaint", 3, "OPEN"),
    ]
    
    # Signals with tiered safety and mandate fields
    # (issue_id, population, complaints, safety_tier, mandate_tier, est_cost, urgency_days)
    signals_data = [
        (1, 450000, 1200, "critical", "court_ordered", 45000000, 7),
        (2, 180000, 300, "critical", "required", 12000000, 14),
        (3, 280000, 900, "severe", "none", 60000000, 30),
        (4, 80000, 40, "none", "none", 4000000, 60),
        (5, 15000, 12, "none", "none", 2500000, 180),
        (6, 25000, 85, "moderate", "none", 800000, 45),
        (7, 5000, 150, "moderate", "advisory", 500000, 30),
        (8, 120000, 50, "severe", "required", 8000000, 21),
        (9, 8000, 25, "none", "none", 1200000, 90),
        (10, 95000, 180, "moderate", "advisory", 5500000, 45),
    ]
    
    cursor.executemany(
        """INSERT INTO issues 
           (issue_id, title, category, description, source, district_id, status) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        issues_data
    )
    
    cursor.executemany(
        """INSERT INTO issue_signals 
           (issue_id, population_affected, complaint_count, safety_tier, mandate_tier, 
            estimated_cost, urgency_days) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        signals_data
    )
    
    conn.commit()
    conn.close()
    print("✓ Sample issues seeded")


def clear_agent_outputs(db_path: str = DB_PATH) -> None:
    """Clear all agent-generated data for re-running pipeline."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM schedule_tasks")
    cursor.execute("DELETE FROM portfolio_decisions")
    cursor.execute("DELETE FROM project_candidates")
    cursor.execute("DELETE FROM scoring_audit")
    cursor.execute("DELETE FROM district_allocations")
    cursor.execute("UPDATE resource_calendar SET soft_allocated = 0, hard_allocated = 0")
    cursor.execute("DELETE FROM audit_log")
    
    conn.commit()
    conn.close()
    print("✓ Agent outputs cleared")


def init_with_sample_data(db_path: str = DB_PATH) -> None:
    """Initialize database with full sample data."""
    init_database(db_path)
    seed_districts(db_path)
    seed_resource_calendar(db_path)
    seed_sample_issues(db_path)


if __name__ == "__main__":
    init_with_sample_data()
