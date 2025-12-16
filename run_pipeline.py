#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Municipal Value-Score System v2 - Pipeline Runner

Run the complete 3-agent pipeline for municipal project prioritization.

Usage:
    python run_pipeline.py              # Run with existing data
    python run_pipeline.py --seed       # Initialize with sample data
    python run_pipeline.py --reset      # Clear outputs and re-run
    python run_pipeline.py --seed --reset  # Full reset with sample data
"""

import argparse
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Verify API key
if not os.getenv("OPENAI_API_KEY"):
    print("Error: OPENAI_API_KEY not found in environment.")
    print("Please set it in .env file or environment variable.")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Run the Municipal Value-Score Pipeline"
    )
    parser.add_argument(
        "--seed",
        action="store_true",
        help="Initialize database with sample data",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Clear agent outputs before running",
    )
    parser.add_argument(
        "--db",
        type=str,
        default="database/city_value.db",
        help="Path to database file",
    )
    
    args = parser.parse_args()
    
    # Import here to avoid issues if dependencies aren't installed
    from municipal_agents.pipeline import run_pipeline_sync
    
    try:
        results = run_pipeline_sync(
            db_path=args.db,
            reset_data=args.reset,
            seed_data=args.seed,
        )
        
        print("\n" + "=" * 60)
        print("PIPELINE EXECUTION COMPLETE")
        print("=" * 60)
        
    except KeyboardInterrupt:
        print("\nPipeline interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\nError running pipeline: {e}")
        raise


if __name__ == "__main__":
    main()
