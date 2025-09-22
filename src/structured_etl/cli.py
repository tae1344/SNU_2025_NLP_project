#!/usr/bin/env python3
"""Samsung Financial Knowledge Graph ETL Command Line Interface.

This CLI provides comprehensive control over the ETL pipeline with options for
schema management, year-specific processing, dry-run capabilities, and more.
"""

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .schema_apply import apply_schema
from .neo4j_client import neo4j_session, load_config, create_driver
from .neo4j_utils import Neo4jUtils
from .etl_config import DEFAULT_CONFIG
from .validate_graph import generate_validation_report, print_validation_summary

# Import optimized modules
from .etl_optimized import run_optimized_etl


def apply_schema_command(args) -> int:
    """Apply Neo4j schema constraints and indexes.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        print("🔧 Applying Neo4j schema...")

        neo4j_config = load_config()
        driver = create_driver(neo4j_config)

        with neo4j_session(driver) as session:
            apply_schema(session)
            print("✅ Schema applied successfully!")

            # Show applied constraints and indexes
            if args.verbose:
                print("\n📋 Applied constraints:")
                result = session.run("SHOW CONSTRAINTS")
                for record in result:
                    print(f"   - {record}")

                print("\n📋 Applied indexes:")
                result = session.run("SHOW INDEXES")
                for record in result:
                    print(f"   - {record}")

        driver.close()
        return 0

    except Exception as e:
        print(f"❌ Failed to apply schema: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


def run_etl_command(args) -> int:
    """Run the complete ETL pipeline.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        config = DEFAULT_CONFIG

        # Determine which years to process
        if args.year:
            years_to_process = [args.year]
            print(f"🎯 Processing single year: {args.year}")
        elif args.years:
            years_to_process = args.years
            print(f"🎯 Processing multiple years: {years_to_process}")
        elif args.all:
            years_to_process = None  # Process all available years
            print(f"🎯 Processing ALL available years")
        else:
            # Default to recent years for safety
            years_to_process = [2022, 2023, 2024]
            print(f"🎯 Processing recent years (default): {years_to_process}")

        # Get files to process
        if years_to_process:
            processed_files = config.get_processed_files(years_to_process)
        else:
            processed_files = config.get_processed_files()

        if not processed_files:
            print("❌ No processed files found for the specified years")
            return 1

        print(f"📁 Found {len(processed_files)} files to process:")
        for f in processed_files:
            print(f"   - {f.name}")

        # Dry run: show planned operations without executing
        if args.dry_run:
            return run_dry_run(processed_files, config, args)

        # Connect to Neo4j
        neo4j_config = load_config()
        driver = create_driver(neo4j_config)

        # Initialize Neo4j utilities for health checks and optimization
        with Neo4jUtils() as neo4j_utils:
            # Pre-ETL health check
            print("\n🏥 Pre-ETL health check...")
            health = neo4j_utils.health_check()
            if health["status"] != "healthy":
                print(f"⚠️  Database health issue: {health.get('message', 'Unknown')}")
                if not args.force:
                    print("Use --force to proceed anyway")
                    return 1

            # Warn about existing data
            if health.get("stats", {}).get("total_nodes", 0) > 0:
                existing_nodes = health["stats"]["total_nodes"]
                print(f"⚠️  Database contains {existing_nodes} existing nodes")

                if args.clear_existing:
                    print("🧹 Clearing existing data...")
                    clear_result = neo4j_utils.clear_database(confirm=True)
                    if clear_result["status"] == "success":
                        nodes_deleted = (
                            clear_result["initial_nodes"] - clear_result["final_nodes"]
                        )
                        relationships_deleted = (
                            clear_result["initial_relationships"]
                            - clear_result["final_relationships"]
                        )
                        print(
                            f"✅ Cleared {nodes_deleted} nodes and {relationships_deleted} relationships"
                        )
                    else:
                        print(
                            f"❌ Failed to clear database: {clear_result.get('message')}"
                        )
                        return 1
                elif not args.force:
                    print("Use --clear-existing to clear data or --force to proceed")
                    return 1

        # Use optimized ETL pipeline
        return run_optimized_pipeline(driver, years_to_process, args)

    except Exception as e:
        print(f"❌ ETL pipeline failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


def run_dry_run(processed_files: List[Path], config, args) -> int:
    """Execute dry run - show planned operations without making changes.

    Args:
        processed_files: List of files to process
        config: ETL configuration
        args: Command line arguments

    Returns:
        Exit code (0 for success)
    """
    print(f"\n🔍 DRY RUN - Planned ETL Operations")
    print(f"=" * 50)
    print(f"📁 Files to process: {len(processed_files)}")

    # Estimate counts based on file analysis
    total_estimated_nodes = 0
    total_estimated_relationships = 0

    print(f"\n📊 Estimated operations per file:")
    for file_path in processed_files:
        try:
            import json

            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Extract basic stats
            sections = data.get("sections", [])

            # Estimate nodes
            estimated_nodes = {
                "company": 1,
                "subsidiary": 1,
                "fs_sections": 4,  # BS, PL, CF, EQ
                "year_nodes": 4,  # One per section
                "notes": len([s for s in sections if "주석" in s.get("title", "")]),
                "categories": 20,  # Rough estimate
                "search_docs": 10,  # Rough estimate
            }

            file_nodes = sum(estimated_nodes.values())
            file_relationships = file_nodes * 2  # Rough estimate

            total_estimated_nodes += file_nodes
            total_estimated_relationships += file_relationships

            print(f"   📄 {file_path.name}:")
            print(f"      Estimated nodes: {file_nodes}")
            print(f"      Estimated relationships: {file_relationships}")

        except Exception as e:
            print(f"   📄 {file_path.name}: Analysis failed - {e}")

    print(f"\n📈 Total estimated operations:")
    print(f"   Total nodes: ~{total_estimated_nodes}")
    print(f"   Total relationships: ~{total_estimated_relationships}")
    print(f"   Estimated duration: ~{total_estimated_nodes / 100:.1f} seconds")

    print(f"\n🔧 Planned ETL steps:")
    steps = [
        "1. Apply schema constraints and indexes",
        "2. Load COMPANY and SUBSIDIARY nodes",
        "3. Load FS_SECTION nodes",
        "4. Load FS_CATEGORY hierarchy",
        "5. Load YEAR_NODE nodes",
        "6. Load FINANCIAL_DATA nodes",
        "7. Load AUDIT_INFO and AUDITOR nodes",
        "8. Load NOTE and NOTE_CATEGORY nodes",
        "9. Create FS-to-Notes links",
        "10. Create SEARCH_DOC nodes",
        "11. Create TREND_TO relationships",
        "12. Create financial relationship edges (INVESTS_IN, TRADES_WITH, OWES_TO, GUARANTEES_FOR)",
        "13. Run validation checks",
    ]

    for step in steps:
        print(f"   {step}")

    print(f"\n💡 To execute this plan, run without --dry-run")
    return 0


def run_optimized_pipeline(driver, years_to_process: Optional[List[int]], args) -> int:
    """Run the optimized ETL pipeline.

    Args:
        driver: Neo4j driver
        years_to_process: List of years to process or None for all
        args: Command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    print(f"\n🚀 Starting Optimized ETL Pipeline")
    print(f"=" * 50)

    try:
        # Use the optimized ETL runner
        run_optimized_etl(
            year_range=years_to_process,
            test_mode=args.test_mode,
            batch_size=args.batch_size,
            max_retries=args.max_retries,
        )

        driver.close()
        return 0

    except Exception as e:
        print(f"❌ Optimized ETL pipeline failed: {e}")
        if args.verbose:
            import traceback

            traceback.print_exc()
        return 1


def status_command(args) -> int:
    """Show ETL system status.

    Args:
        args: Parsed command line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        print("📊 Samsung Financial Knowledge Graph - ETL Status")
        print("=" * 60)

        # Check available processed files
        config = DEFAULT_CONFIG
        all_files = config.get_processed_files()

        print(f"📁 Available processed files: {len(all_files)}")

        # Group by year
        files_by_year = {}
        for file_path in all_files:
            import re

            year_match = re.search(r"(\d{4})", file_path.name)
            if year_match:
                year = int(year_match.group(1))
                files_by_year[year] = files_by_year.get(year, 0) + 1

        print("   Files by year:")
        for year in sorted(files_by_year.keys()):
            print(f"     {year}: {files_by_year[year]} file(s)")

        # Check Neo4j status
        try:
            with Neo4jUtils() as neo4j_utils:
                health = neo4j_utils.health_check()

                print(f"\n🔌 Neo4j Status: {health['status']}")
                if health["status"] == "healthy":
                    stats = health.get("stats", {})
                    print(f"   Total nodes: {stats.get('total_nodes', 0)}")
                    print(
                        f"   Total relationships: {stats.get('total_relationships', 0)}"
                    )

                    if stats.get("total_nodes", 0) > 0:
                        print("   ✅ Knowledge graph contains data")
                    else:
                        print("   📭 Knowledge graph is empty")
                else:
                    print(f"   ❌ Issue: {health.get('message', 'Unknown')}")

        except Exception as e:
            print(f"\n❌ Neo4j connection failed: {e}")
            return 1

        return 0

    except Exception as e:
        print(f"❌ Status check failed: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Samsung Financial Knowledge Graph ETL CLI",
        formatter_class=argparse.RawTextHelpFormatter,
        epilog="""
Examples:
  %(prog)s apply-schema                          # Apply Neo4j schema
  %(prog)s run --year 2024                      # Process single year
  %(prog)s run --years 2022 2023 2024           # Process multiple years
  %(prog)s run --all                            # Process all available years
  %(prog)s run --dry-run --all                  # Show planned operations
  %(prog)s status                               # Show system status
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Apply schema command
    schema_parser = subparsers.add_parser(
        "apply-schema", help="Apply Neo4j schema constraints and indexes"
    )
    schema_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output"
    )
    schema_parser.set_defaults(func=apply_schema_command)

    # Run ETL command
    run_parser = subparsers.add_parser("run", help="Run the ETL pipeline")

    # Year selection (mutually exclusive)
    year_group = run_parser.add_mutually_exclusive_group()
    year_group.add_argument(
        "--year", type=int, help="Process single year (e.g., --year 2024)"
    )
    year_group.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Process multiple years (e.g., --years 2022 2023 2024)",
    )
    year_group.add_argument(
        "--all", action="store_true", help="Process all available years"
    )

    # Execution options
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned operations without executing",
    )
    run_parser.add_argument(
        "--test-mode", action="store_true", help="Use test mode for search documents"
    )

    # Data management
    run_parser.add_argument(
        "--clear-existing", action="store_true", help="Clear existing data before ETL"
    )
    run_parser.add_argument(
        "--force", action="store_true", help="Force execution despite warnings"
    )

    # Processing options
    run_parser.add_argument(
        "--skip-schema", action="store_true", help="Skip schema application"
    )
    run_parser.add_argument(
        "--skip-optimization",
        action="store_true",
        help="Skip final database optimization",
    )
    run_parser.add_argument(
        "--validate", action="store_true", help="Run validation after ETL"
    )

    # Performance tuning (for optimized mode)
    run_parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for optimized processing",
    )
    run_parser.add_argument(
        "--max-retries", type=int, default=3, help="Maximum retry attempts"
    )

    # Output options
    run_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output"
    )
    run_parser.set_defaults(func=run_etl_command)

    # Status command
    status_parser = subparsers.add_parser("status", help="Show ETL system status")
    status_parser.set_defaults(func=status_command)

    # Parse arguments
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute command
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
