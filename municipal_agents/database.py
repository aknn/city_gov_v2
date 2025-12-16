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
        -- Optional hints for formation agent
        estimated_duration_weeks INTEGER,
        recommended_crew_size INTEGER,
        crew_type TEXT,
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


def seed_large_scenario(db_path: str = DB_PATH, num_issues: int = 30) -> None:
    """
    Seed a larger scenario with many overlapping issues to test CP-SAT solver.
    
    Creates 30 issues across different categories with varying:
    - Safety tiers (critical, severe, moderate, none)
    - Mandate tiers (court_ordered, required, advisory, none)
    - Costs ($100K - $50M)
    - Durations (2-20 weeks)
    - Resource types
    - Urgency levels
    """
    import random
    random.seed(42)  # Reproducible
    
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
    cursor.execute("UPDATE resource_calendar SET soft_allocated = 0, hard_allocated = 0")
    
    categories = ["Water", "Infrastructure", "Health", "Education", "Recreation", 
                  "Public Safety", "Transportation", "Environment", "Housing", "Utilities"]
    
    issue_templates = [
        # (title_template, category, safety_tier, mandate_tier, cost_range, duration_range, crew_type, urgency_range)
        ("Emergency Water Main Break - Sector {}", "Water", "critical", "court_ordered", (20_000_000, 50_000_000), (10, 20), "water_crew", (3, 14)),
        ("Hospital {} Equipment Failure", "Health", "critical", "required", (5_000_000, 15_000_000), (6, 12), "electrical_crew", (7, 21)),
        ("Bridge Inspection - {} Ave", "Infrastructure", "severe", "required", (3_000_000, 10_000_000), (4, 10), "construction_crew", (14, 30)),
        ("Fire Station {} Renovation", "Public Safety", "severe", "required", (2_000_000, 8_000_000), (8, 16), "construction_crew", (21, 45)),
        ("School {} Safety Upgrade", "Education", "moderate", "advisory", (200_000, 1_000_000), (3, 8), "general_crew", (30, 60)),
        ("Street Lighting - District {}", "Infrastructure", "moderate", "none", (300_000, 800_000), (4, 8), "electrical_crew", (30, 60)),
        ("Park Renovation - {} Park", "Recreation", "none", "none", (500_000, 3_000_000), (6, 14), "general_crew", (60, 120)),
        ("Pothole Repair Zone {}", "Transportation", "none", "none", (100_000, 500_000), (2, 6), "construction_crew", (45, 90)),
        ("Stormwater System - Sector {}", "Water", "moderate", "advisory", (1_000_000, 6_000_000), (5, 12), "water_crew", (30, 60)),
        ("Community Center {} Upgrade", "Recreation", "none", "none", (400_000, 1_500_000), (4, 10), "general_crew", (60, 120)),
        ("Traffic Signal Update - {} Intersection", "Transportation", "moderate", "none", (100_000, 400_000), (2, 4), "electrical_crew", (30, 60)),
        ("Sewer Line Replacement - {} St", "Utilities", "severe", "required", (2_000_000, 8_000_000), (8, 16), "water_crew", (14, 30)),
        ("Affordable Housing Block {}", "Housing", "none", "advisory", (5_000_000, 20_000_000), (16, 24), "construction_crew", (90, 180)),
        ("Emergency Shelter Upgrade - Site {}", "Housing", "moderate", "required", (1_000_000, 4_000_000), (6, 12), "construction_crew", (21, 45)),
        ("Green Space Development - Area {}", "Environment", "none", "none", (800_000, 3_000_000), (8, 16), "general_crew", (90, 180)),
    ]
    
    sector_names = ["Alpha", "Beta", "Gamma", "Delta", "Epsilon", "Zeta", "Omega", "North", "South", "Central"]
    street_names = ["Main", "Oak", "Elm", "Cedar", "Pine", "Maple", "First", "Second", "Third", "Park"]
    park_names = ["Central", "Riverside", "Memorial", "Liberty", "Heritage", "Sunset", "Valley", "Highland"]
    
    issues_data = []
    signals_data = []
    
    for i in range(1, num_issues + 1):
        template = random.choice(issue_templates)
        title_template, category, safety, mandate, cost_range, dur_range, crew, urg_range = template
        
        # Generate title
        if "{}" in title_template:
            if "Sector" in title_template or "Zone" in title_template or "District" in title_template:
                name = random.choice(sector_names)
            elif "St" in title_template or "Ave" in title_template or "Intersection" in title_template:
                name = random.choice(street_names)
            elif "Park" in title_template:
                name = random.choice(park_names)
            else:
                name = str(random.randint(1, 20))
            title = title_template.format(name)
        else:
            title = title_template
        
        # Generate values
        cost = random.randint(cost_range[0], cost_range[1])
        duration = random.randint(dur_range[0], dur_range[1])
        urgency = random.randint(urg_range[0], urg_range[1])
        population = random.randint(5000, 200000)
        complaints = random.randint(10, 500) if safety in ("critical", "severe") else random.randint(5, 100)
        district = random.randint(1, 8)
        
        issues_data.append((
            i, title, category, f"Description for {title}", 
            random.choice(["citizen_complaint", "facility_inspection", "emergency_report", "council_request"]),
            district, "OPEN"
        ))
        
        signals_data.append((
            i, population, complaints, safety, mandate, cost, urgency
        ))
    
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
    print(f"✓ Large scenario seeded ({num_issues} issues)")


def seed_balanced_scenario(db_path: str = DB_PATH, num_issues: int = 25) -> None:
    """
    Seed a balanced scenario with more schedulable projects.
    
    Key differences from seed_large_scenario:
    - Smaller crew requirements (1-4 instead of 3-10)
    - Shorter durations (2-8 weeks instead of 6-24)
    - More realistic urgency spread
    - Better mix of priorities
    """
    import random
    random.seed(123)  # Different seed for variety
    
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
    cursor.execute("UPDATE resource_calendar SET soft_allocated = 0, hard_allocated = 0")
    
    # Balanced issue templates with smaller resource requirements
    issue_templates = [
        # (title_template, category, safety_tier, mandate_tier, cost_range, duration_range, crew_size_range, crew_type, urgency_range)
        # Critical/Mandated - still high priority but feasible
        ("Water Main Repair - Sector {}", "Water", "critical", "court_ordered", (2_000_000, 5_000_000), (3, 6), (2, 4), "water_crew", (7, 14)),
        ("Hospital Generator Check - {}", "Health", "critical", "required", (500_000, 2_000_000), (2, 4), (2, 3), "electrical_crew", (7, 14)),
        ("Bridge Safety Fix - {} St", "Infrastructure", "severe", "required", (1_000_000, 3_000_000), (3, 5), (3, 5), "construction_crew", (14, 21)),
        
        # Moderate priority - good balance
        ("Fire Alarm Upgrade - Station {}", "Public Safety", "moderate", "required", (200_000, 600_000), (2, 4), (1, 2), "electrical_crew", (21, 30)),
        ("School Crossing Safety - {}", "Education", "moderate", "advisory", (100_000, 300_000), (2, 3), (1, 2), "general_crew", (14, 30)),
        ("Street Light Repair - Zone {}", "Infrastructure", "moderate", "none", (50_000, 150_000), (1, 2), (1, 2), "electrical_crew", (21, 45)),
        ("Sidewalk Repair - {} Ave", "Transportation", "moderate", "none", (80_000, 200_000), (2, 3), (2, 3), "construction_crew", (30, 45)),
        
        # Lower priority but quick wins
        ("Park Bench Install - {} Park", "Recreation", "none", "none", (20_000, 80_000), (1, 2), (1, 2), "general_crew", (45, 90)),
        ("Pothole Patch - Sector {}", "Transportation", "none", "none", (30_000, 100_000), (1, 2), (1, 2), "construction_crew", (30, 60)),
        ("Playground Equipment - {} Park", "Recreation", "none", "none", (50_000, 150_000), (2, 3), (1, 2), "general_crew", (60, 90)),
        ("Tree Planting - Area {}", "Environment", "none", "none", (15_000, 50_000), (1, 2), (1, 2), "general_crew", (60, 120)),
        ("Drainage Clear - Sector {}", "Water", "none", "advisory", (40_000, 120_000), (1, 2), (1, 2), "water_crew", (30, 60)),
        ("Bus Stop Shelter - Stop {}", "Transportation", "none", "none", (25_000, 75_000), (1, 2), (1, 2), "construction_crew", (45, 90)),
        ("Community Garden - Site {}", "Environment", "none", "none", (30_000, 100_000), (2, 3), (1, 2), "general_crew", (60, 120)),
        ("Bike Lane Marking - {} Rd", "Transportation", "none", "none", (20_000, 60_000), (1, 2), (1, 2), "construction_crew", (45, 90)),
    ]
    
    sector_names = ["Alpha", "Beta", "Gamma", "Delta", "North", "South", "East", "West", "Central"]
    street_names = ["Main", "Oak", "Elm", "Cedar", "Pine", "Maple", "First", "Second", "Third"]
    park_names = ["Central", "Riverside", "Memorial", "Liberty", "Heritage", "Sunset", "Valley"]
    
    issues_data = []
    signals_data = []
    
    for i in range(1, num_issues + 1):
        template = random.choice(issue_templates)
        title_template, category, safety, mandate, cost_range, dur_range, crew_range, crew_type, urg_range = template
        
        # Generate title
        if "{}" in title_template:
            if "Sector" in title_template or "Zone" in title_template or "Area" in title_template:
                name = random.choice(sector_names)
            elif "St" in title_template or "Ave" in title_template or "Rd" in title_template:
                name = random.choice(street_names)
            elif "Park" in title_template:
                name = random.choice(park_names)
            elif "Stop" in title_template or "Site" in title_template or "Station" in title_template:
                name = str(random.randint(1, 20))
            else:
                name = random.choice(sector_names)
            title = title_template.format(name)
        else:
            title = title_template
        
        # Generate values
        cost = random.randint(cost_range[0], cost_range[1])
        duration = random.randint(dur_range[0], dur_range[1])
        crew_size = random.randint(crew_range[0], crew_range[1])
        urgency = random.randint(urg_range[0], urg_range[1])
        population = random.randint(5000, 150000)
        complaints = random.randint(20, 300) if safety in ("critical", "severe") else random.randint(5, 80)
        district = random.randint(1, 8)
        
        issues_data.append((
            i, title, category, f"Description for {title}", 
            random.choice(["citizen_complaint", "facility_inspection", "emergency_report", "council_request"]),
            district, "OPEN"
        ))
        
        # Store crew_size in description for formation agent to extract
        # Actually, let's store it in a way the agent can use - we'll add estimated_duration to signals
        signals_data.append((
            i, population, complaints, safety, mandate, cost, urgency, duration, crew_size, crew_type
        ))
    
    cursor.executemany(
        """INSERT INTO issues 
           (issue_id, title, category, description, source, district_id, status) 
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        issues_data
    )
    
    # Extended signals with duration and crew hints
    for signal in signals_data:
        cursor.execute(
            """INSERT INTO issue_signals 
               (issue_id, population_affected, complaint_count, safety_tier, mandate_tier, 
                estimated_cost, urgency_days, estimated_duration_weeks, recommended_crew_size, crew_type) 
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            signal
        )
    
    conn.commit()
    conn.close()
    print(f"✓ Balanced scenario seeded ({num_issues} issues)")


def init_large_scenario(db_path: str = DB_PATH, num_issues: int = 30) -> None:
    """Initialize database with large scenario for CP-SAT testing."""
    init_database(db_path)
    seed_districts(db_path)
    seed_resource_calendar(db_path, weeks=16)  # Extended horizon for more projects
    seed_large_scenario(db_path, num_issues)


def init_balanced_scenario(db_path: str = DB_PATH, num_issues: int = 25) -> None:
    """Initialize database with balanced scenario - more schedulable projects."""
    init_database(db_path)
    seed_districts(db_path)
    seed_resource_calendar(db_path, weeks=12)
    seed_balanced_scenario(db_path, num_issues)


if __name__ == "__main__":
    init_with_sample_data()
