# -*- coding: utf-8 -*-
"""
CLI tool for human confirmation of pending projects.

Usage:
    python -m municipal_agents.confirmation_cli
    python -m municipal_agents.confirmation_cli --project-id 2 --approve
"""

import argparse
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

from .config import DB_PATH


def get_pending_projects(db_path: str = DB_PATH) -> List[Dict]:
    """Fetch all projects requiring human confirmation."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT 
            pd.decision_id,
            pd.project_id,
            pc.title,
            pc.estimated_cost,
            pc.composite_score,
            iss.safety_tier,
            iss.mandate_tier,
            pc.feasibility_estimate,
            pd.allocated_budget,
            pd.confirmation_deadline,
            pd.rationale
        FROM portfolio_decisions pd
        JOIN project_candidates pc ON pd.project_id = pc.project_id
        JOIN issues i ON pc.issue_id = i.issue_id
        LEFT JOIN issue_signals iss ON i.issue_id = iss.issue_id
        WHERE pd.decision = 'APPROVED_WITH_CONDITIONS'
          AND pd.confirmed_at IS NULL
          AND (pd.confirmation_deadline IS NULL OR pd.confirmation_deadline >= DATE('now'))
        ORDER BY pd.confirmation_deadline ASC
    """)
    
    projects = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return projects


def display_pending_projects(projects: List[Dict]) -> None:
    """Display pending projects in a table."""
    if not projects:
        print("\n✅ No projects pending confirmation.\n")
        return
    
    print("\n" + "=" * 100)
    print("PROJECTS PENDING HUMAN CONFIRMATION")
    print("=" * 100)
    print(f"{'ID':<4} {'Title':<40} {'Cost':<14} {'Safety':<10} {'Mandate':<12} {'Feasibility':<12} {'Deadline':<12}")
    print("-" * 100)
    
    for p in projects:
        deadline = p["confirmation_deadline"] or "N/A"
        print(f"{p['project_id']:<4} {p['title'][:38]:<40} ${p['estimated_cost']:>11,.0f} {p['safety_tier'] or 'N/A':<10} {p['mandate_tier'] or 'N/A':<12} {p['feasibility_estimate']:<12.2f} {deadline:<12}")
    
    print("=" * 100 + "\n")


def display_project_details(project: Dict) -> None:
    """Display detailed information about a project."""
    print("\n" + "=" * 80)
    print(f"PROJECT #{project['project_id']}: {project['title']}")
    print("=" * 80)
    print(f"Estimated Cost:        ${project['estimated_cost']:,.0f}")
    print(f"Allocated Budget:      ${project['allocated_budget']:,.0f}")
    print(f"Composite Score:       {project['composite_score']:.3f}")
    print(f"Safety Tier:           {project['safety_tier'] or 'N/A'}")
    print(f"Mandate Tier:          {project['mandate_tier'] or 'N/A'}")
    print(f"Feasibility (Agent):   {project['feasibility_estimate']:.2f}")
    print(f"Confirmation Deadline: {project['confirmation_deadline'] or 'N/A'}")
    print(f"\nGovernance Rationale:\n{project['rationale']}")
    print("=" * 80 + "\n")


def confirm_project(
    project_id: int,
    approved: bool,
    confirmed_by: str,
    feasibility_override: Optional[float] = None,
    override_reason: Optional[str] = None,
    db_path: str = DB_PATH,
) -> bool:
    """
    Confirm or reject a project pending approval.
    
    Args:
        project_id: Project to confirm
        approved: True to approve, False to reject
        confirmed_by: User/official name
        feasibility_override: Optional override of agent's feasibility estimate
        override_reason: Reason for override (required if override provided)
        db_path: Database path
    
    Returns:
        True if successful
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        if approved:
            # Update portfolio decision
            cursor.execute("""
                UPDATE portfolio_decisions
                SET decision = 'APPROVED',
                    confirmed_at = ?,
                    confirmed_by = ?
                WHERE project_id = ?
                  AND decision = 'APPROVED_WITH_CONDITIONS'
            """, (datetime.now().isoformat(), confirmed_by, project_id))
            
            # If feasibility override provided, record it
            if feasibility_override is not None:
                cursor.execute("""
                    SELECT feasibility_estimate FROM project_candidates WHERE project_id = ?
                """, (project_id,))
                row = cursor.fetchone()
                original = row[0] if row else None
                
                cursor.execute("""
                    UPDATE project_candidates
                    SET feasibility_estimate = ?
                    WHERE project_id = ?
                """, (feasibility_override, project_id))
                
                # Log the override in audit_log
                cursor.execute("""
                    INSERT INTO audit_log (
                        table_name, record_id, action, actor_id, details
                    ) VALUES (?, ?, ?, ?, ?)
                """, (
                    'project_candidates', 
                    project_id, 
                    'feasibility_override', 
                    confirmed_by,
                    f"Original: {original}, New: {feasibility_override}, Reason: {override_reason}"
                ))
            
            print(f"\n✅ Project #{project_id} APPROVED by {confirmed_by}")
            if feasibility_override:
                print(f"   Feasibility overridden: {feasibility_override:.2f}")
        
        else:
            # Reject the project
            cursor.execute("""
                UPDATE portfolio_decisions
                SET decision = 'REJECTED',
                    rationale = rationale || ' [HUMAN REJECTED: ' || ? || ']',
                    confirmed_at = ?,
                    confirmed_by = ?
                WHERE project_id = ?
                  AND decision = 'APPROVED_WITH_CONDITIONS'
            """, (override_reason or "No reason provided", 
                  datetime.now().isoformat(), confirmed_by, project_id))
            
            # Delete schedule tasks for rejected project
            cursor.execute("DELETE FROM schedule_tasks WHERE project_id = ?", (project_id,))
            
            print(f"\n❌ Project #{project_id} REJECTED by {confirmed_by}")
            if override_reason:
                print(f"   Reason: {override_reason}")
        
        conn.commit()
        return True
    
    except Exception as e:
        conn.rollback()
        print(f"\n⚠️  Error confirming project: {e}")
        return False
    
    finally:
        conn.close()


def interactive_confirmation_session(db_path: str = DB_PATH) -> None:
    """Run an interactive confirmation session."""
    projects = get_pending_projects(db_path)
    
    if not projects:
        print("\n✅ No projects pending confirmation.\n")
        return
    
    display_pending_projects(projects)
    
    while projects:
        print("\nOptions:")
        print("  [number]  - Review project details")
        print("  a [id]    - Approve project")
        print("  r [id]    - Reject project")
        print("  q         - Quit")
        
        choice = input("\nYour choice: ").strip().lower()
        
        if choice == 'q':
            break
        
        elif choice.startswith('a '):
            try:
                pid = int(choice.split()[1])
                project = next((p for p in projects if p["project_id"] == pid), None)
                
                if not project:
                    print(f"⚠️  Project #{pid} not found in pending list.")
                    continue
                
                display_project_details(project)
                
                # Ask for feasibility override
                override_input = input("Override feasibility estimate? (y/N): ").strip().lower()
                feasibility_override = None
                override_reason = None
                
                if override_input == 'y':
                    try:
                        feasibility_override = float(input("New feasibility (0-1): ").strip())
                        override_reason = input("Reason for override: ").strip()
                    except ValueError:
                        print("Invalid feasibility value. Using agent estimate.")
                
                confirmed_by = input("Your name/ID: ").strip() or "admin"
                
                if confirm_project(pid, True, confirmed_by, feasibility_override, override_reason, db_path):
                    projects = [p for p in projects if p["project_id"] != pid]
                    display_pending_projects(projects)
            
            except (ValueError, IndexError):
                print("Invalid input. Use: a [project_id]")
        
        elif choice.startswith('r '):
            try:
                pid = int(choice.split()[1])
                project = next((p for p in projects if p["project_id"] == pid), None)
                
                if not project:
                    print(f"⚠️  Project #{pid} not found in pending list.")
                    continue
                
                display_project_details(project)
                reason = input("Reason for rejection: ").strip() or "Not approved"
                confirmed_by = input("Your name/ID: ").strip() or "admin"
                
                if confirm_project(pid, False, confirmed_by, override_reason=reason, db_path=db_path):
                    projects = [p for p in projects if p["project_id"] != pid]
                    display_pending_projects(projects)
            
            except (ValueError, IndexError):
                print("Invalid input. Use: r [project_id]")
        
        elif choice.isdigit():
            pid = int(choice)
            project = next((p for p in projects if p["project_id"] == pid), None)
            if project:
                display_project_details(project)
            else:
                print(f"⚠️  Project #{pid} not found.")
        
        else:
            print("Invalid choice.")


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Human confirmation tool for municipal projects")
    parser.add_argument("--db", default=DB_PATH, help="Database path")
    parser.add_argument("--list", action="store_true", help="List pending projects and exit")
    parser.add_argument("--project-id", type=int, help="Project ID to confirm")
    parser.add_argument("--approve", action="store_true", help="Approve the project")
    parser.add_argument("--reject", action="store_true", help="Reject the project")
    parser.add_argument("--confirmed-by", default="admin", help="User name")
    parser.add_argument("--feasibility-override", type=float, help="Override feasibility (0-1)")
    parser.add_argument("--reason", help="Reason for override/rejection")
    
    args = parser.parse_args()
    
    if args.list:
        projects = get_pending_projects(args.db)
        display_pending_projects(projects)
        return
    
    if args.project_id:
        if not (args.approve or args.reject):
            print("Error: Must specify --approve or --reject")
            return
        
        confirm_project(
            args.project_id,
            approved=args.approve,
            confirmed_by=args.confirmed_by,
            feasibility_override=args.feasibility_override,
            override_reason=args.reason,
            db_path=args.db,
        )
        return
    
    # Interactive mode
    interactive_confirmation_session(args.db)


if __name__ == "__main__":
    main()
