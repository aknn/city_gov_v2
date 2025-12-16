#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Display the current schedule and resource utilization."""

import sqlite3
from municipal_agents.config import DB_PATH


def show_schedule(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Check if schedule_tasks exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='schedule_tasks'")
    if not cursor.fetchone():
        print("No schedule_tasks table found. Run the pipeline first.")
        return
    
    # Get scheduled tasks
    cursor.execute('''
        SELECT st.*, pc.title 
        FROM schedule_tasks st
        JOIN project_candidates pc ON st.project_id = pc.project_id
        ORDER BY st.start_week
    ''')
    tasks = cursor.fetchall()
    
    if not tasks:
        print("\nNo scheduled tasks found.\n")
    else:
        print("\n" + "=" * 100)
        print("SCHEDULED TASKS")
        print("=" * 100)
        print(f"{'ID':<4} {'Project':<45} {'Weeks':<12} {'Resource':<20} {'Deadline':<10} {'Status'}")
        print("-" * 100)
        for t in tasks:
            weeks = f"W{t['start_week']}-W{t['end_week']}"
            status = t['deadline_status'] or 'N/A'
            deadline = f"W{t['deadline_week']}" if t['deadline_week'] else "N/A"
            print(f"{t['project_id']:<4} {t['title'][:43]:<45} {weeks:<12} {t['resource_type']:<20} {deadline:<10} {status}")
        print("=" * 100)
    
    # Show portfolio decisions
    cursor.execute('''
        SELECT pd.*, pc.title, pc.estimated_cost
        FROM portfolio_decisions pd
        JOIN project_candidates pc ON pd.project_id = pc.project_id
        ORDER BY pd.decision, pc.composite_score DESC
    ''')
    decisions = cursor.fetchall()
    
    if decisions:
        print("\n" + "=" * 100)
        print("PORTFOLIO DECISIONS")
        print("=" * 100)
        print(f"{'ID':<4} {'Project':<40} {'Decision':<25} {'Budget':<15}")
        print("-" * 100)
        for d in decisions:
            budget = d['allocated_budget'] or 0
            print(f"{d['project_id']:<4} {d['title'][:38]:<40} {d['decision']:<25} ${budget:>12,.0f}")
        print("=" * 100)
    
    # Show resource utilization
    cursor.execute('''
        SELECT resource_type, 
               SUM(hard_allocated) as hard,
               SUM(soft_allocated) as soft,
               SUM(capacity) as total_cap
        FROM resource_calendar
        GROUP BY resource_type
    ''')
    resources = cursor.fetchall()
    
    if resources:
        print("\nRESOURCE UTILIZATION (12 weeks)")
        print("-" * 60)
        for r in resources:
            used = r['hard'] + r['soft']
            pct = (used / r['total_cap'] * 100) if r['total_cap'] else 0
            print(f"{r['resource_type']:<20} {used:>4}/{r['total_cap']:>4} units ({pct:.0f}%)")
    
    conn.close()


if __name__ == "__main__":
    show_schedule()
