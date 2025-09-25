#!/usr/bin/env python3
"""Optimized ETL pipeline with batching, retry logic, and comprehensive metrics.

This script demonstrates the enhanced ETL capabilities using the executor framework
for improved performance, reliability, and observability.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import List

from .schema_apply import apply_schema
from .neo4j_client import neo4j_session
from .neo4j_utils import Neo4jUtils
from .etl_config import DEFAULT_CONFIG
from .executor import ETLExecutor, BatchConfig

# Import optimized loaders
from .load_financial_data_optimized import load_financial_data_nodes_optimized
from .load_financial_trends import load_financial_trends
from .period_column_detector import process_period_columns_for_timeseries
from .fs_type_preprocessor import process_fs_by_type


# Import regular loaders (to be optimized in future)
from .load_company_enhanced import load_enhanced_company_nodes
from .load_fs_sections import load_fs_section_nodes
from .load_fs_categories import load_fs_category_nodes
from .load_year_nodes import load_year_nodes_with_trends
from .load_audit_info import load_audit_info_nodes
from .load_notes import load_note_nodes
from .link_notes import load_fs_note_links, create_financial_data_note_links
from .load_search_docs import load_search_doc_nodes
from .link_trends import load_trend_relationships
from .load_financial_relationships import load_financial_relationship_edges
from .track_relationship_changes import load_relationship_changes


def run_optimized_etl(
    year_range: List[int] = None,
    test_mode: bool = False,
    batch_size: int = 500,
    max_retries: int = 3,
) -> None:
    """Run optimized ETL pipeline with enhanced performance and monitoring.

    Args:
        year_range: List of years to process. If None, processes all available years.
        test_mode: If True, use test mode for search docs (limited processing)
        batch_size: Batch size for processing
        max_retries: Maximum retry attempts for failed operations
    """
    etl_config = DEFAULT_CONFIG

    # Get files to process
    if year_range:
        files_to_process = etl_config.get_processed_files(year_range)
        print(f"🎯 Optimized ETL for years: {year_range}")
    else:
        files_to_process = etl_config.get_processed_files()
        print(f"🎯 Optimized ETL for ALL available years")

    if not files_to_process:
        print("❌ No processed files found")
        return

    print(
        f"📁 Processing {len(files_to_process)} files: {[f.name for f in files_to_process]}"
    )

    # Initialize performance monitoring
    overall_start_time = time.time()

    # Configure batch processing
    batch_config = BatchConfig(
        batch_size=batch_size,
        max_retries=max_retries,
        retry_delay=1.0,
        retry_backoff=2.0,
        max_retry_delay=30.0,
        timeout_seconds=600.0,  # 10 minutes
    )

    # Initialize Neo4j utilities
    with Neo4jUtils() as neo4j_utils:
        # Initial health check
        print("\n🏥 Initial health check...")
        health = neo4j_utils.health_check()
        print(f"Database status: {health['status']}")

        if health.get("stats", {}).get("total_nodes", 0) > 0:
            print(f"⚠️  Database contains {health['stats']['total_nodes']} nodes")
            print("Consider clearing database before ETL")

        driver = neo4j_utils.driver

    try:
        with neo4j_session(driver) as session:
            # 1) Apply schema
            print("\n🔧 Step 1: Applying schema...")
            apply_schema(session)
            print("✅ Schema applied")

            # 1.5) Process period columns for time series consistency
            # print(
            #     "\n📅 Step 1.5: Processing period columns for time series consistency..."
            # )
            # period_results = process_period_columns_for_timeseries(
            #     files_to_process, etl_config
            # )
            # print(
            #     f"✅ Period columns processed: {period_results['tables_processed']} tables"
            # )

            # 2) Load enhanced COMPANY and company relationship nodes
            print(
                "\n🏢 Step 2: Loading enhanced COMPANY and company relationship nodes..."
            )
            load_enhanced_company_nodes(session, files_to_process, etl_config)
            print("✅ Enhanced company nodes loaded")

            # 3) Load FS_SECTION nodes
            print("\n📊 Step 3: Loading FS_SECTION nodes...")
            load_fs_section_nodes(session, files_to_process, etl_config)
            print("✅ FS Section nodes loaded")

            # 4) Load FS_CATEGORY hierarchy
            print("\n🗂️  Step 4: Loading FS_CATEGORY hierarchy...")
            load_fs_category_nodes(session, files_to_process, etl_config)
            print("✅ FS Category nodes loaded")

            # 5) Load YEAR_NODE nodes with trends
            print("\n📅 Step 5: Loading YEAR_NODE nodes with trends...")
            load_year_nodes_with_trends(session, files_to_process, etl_config)
            print("✅ Year nodes loaded")

            # 6) Load FINANCIAL_DATA nodes (OPTIMIZED)
            print("\n💰 Step 6: Loading FINANCIAL_DATA nodes (OPTIMIZED)...")
            load_financial_data_nodes_optimized(session, files_to_process, etl_config)
            print("✅ Financial data nodes loaded (optimized)")

            # 6.5) Load FINANCIAL_TREND nodes (NEW)
            # print("\n📈 Step 6.5: Loading FINANCIAL_TREND nodes...")
            # load_financial_trends(session, files_to_process, etl_config)
            # print("✅ Financial trend nodes loaded")

            # 7) Load AUDIT_INFO and AUDITOR nodes
            print("\n🔍 Step 7: Loading AUDIT_INFO and AUDITOR nodes...")
            load_audit_info_nodes(session, files_to_process, etl_config)
            print("✅ Audit info nodes loaded")

            # 8) Load NOTE and NOTE_CATEGORY nodes
            print("\n📝 Step 8: Loading NOTE and NOTE_CATEGORY nodes...")
            load_note_nodes(session, files_to_process, etl_config)
            print("✅ Note nodes loaded")

            # 9) Link FS categories to notes
            print("\n🔗 Step 9: Linking FS categories to notes...")
            load_fs_note_links(session, files_to_process, etl_config)
            print("✅ FS-to-Notes links created")

            # 9.1) Link FINANCIAL_DATA to notes (based on stored notes array)
            print("\n🔗 Step 9.1: Linking FINANCIAL_DATA to notes...")
            fd_link_res = create_financial_data_note_links(session, etl_config)
            print(
                f"✅ FD-to-Notes links created: {fd_link_res['links_created']} (processed {fd_link_res['processed']})"
            )

            # 10) Create SEARCH_DOC nodes
            search_mode_text = "TEST MODE" if test_mode else "PRODUCTION MODE"
            print(f"\n🔍 Step 10: Creating SEARCH_DOC nodes ({search_mode_text})...")
            load_search_doc_nodes(
                session, files_to_process, etl_config, test_mode=test_mode
            )
            print("✅ Search document nodes created")

            # 11) Create TREND_TO relationships
            print("\n📈 Step 11: Creating TREND_TO relationships...")
            load_trend_relationships(session, files_to_process, etl_config)
            print("✅ Trend relationships created")

            # 12) Create financial relationship edges
            print("\n💰 Step 12: Creating financial relationship edges...")
            load_financial_relationship_edges(session, files_to_process, etl_config)
            print("✅ Financial relationship edges created")

            # 12.5) Track relationship changes (NEW)
            print("\n🔄 Step 12.5: Tracking relationship changes...")
            load_relationship_changes(session, files_to_process, etl_config)
            print("✅ Relationship changes tracked")

            # 13) Final verification and metrics
            print("\n📊 Step 13: Final verification and performance metrics...")

            # Get simplified counts to avoid timeout
            counts = {}
            counts["company"] = session.run(
                "MATCH (:company) RETURN count(*) AS count"
            ).single()["count"]
            counts["subsidiaries"] = session.run(
                "MATCH (:subsidiary) RETURN count(*) AS count"
            ).single()["count"]
            counts["affiliates"] = session.run(
                "MATCH (:affiliate) RETURN count(*) AS count"
            ).single()["count"]
            counts["joint_ventures"] = session.run(
                "MATCH (:joint_venture) RETURN count(*) AS count"
            ).single()["count"]
            counts["special_relations"] = session.run(
                "MATCH (:special_relation) RETURN count(*) AS count"
            ).single()["count"]
            counts["fs_sections"] = session.run(
                "MATCH (:financial_statement) RETURN count(*) AS count"
            ).single()["count"]
            counts["fs_categories"] = session.run(
                "MATCH (:fs_category) RETURN count(*) AS count"
            ).single()["count"]
            counts["year_nodes"] = session.run(
                "MATCH (:year_node) RETURN count(*) AS count"
            ).single()["count"]
            counts["financial_data"] = session.run(
                "MATCH (:financial_data) RETURN count(*) AS count"
            ).single()["count"]
            counts["financial_trends"] = session.run(
                "MATCH (:financial_trend) RETURN count(*) AS count"
            ).single()["count"]
            counts["auditors"] = session.run(
                "MATCH (:auditor) RETURN count(*) AS count"
            ).single()["count"]
            counts["audit_info"] = session.run(
                "MATCH (:audit_info) RETURN count(*) AS count"
            ).single()["count"]
            counts["notes"] = session.run(
                "MATCH (:note) RETURN count(*) AS count"
            ).single()["count"]
            counts["note_categories"] = session.run(
                "MATCH (:note_category) RETURN count(*) AS count"
            ).single()["count"]
            counts["fs_note_links"] = session.run(
                "MATCH ()-[:links_to_note]->() RETURN count(*) AS count"
            ).single()["count"]
            counts["search_docs"] = session.run(
                "MATCH (:search_doc) RETURN count(*) AS count"
            ).single()["count"]
            counts["trend_links"] = session.run(
                "MATCH ()-[:trend_to]->() RETURN count(*) AS count"
            ).single()["count"]
            counts["financial_relationships"] = session.run(
                "MATCH ()-[r:invests_in|trades_with|owes_to|guarantees_for]->() RETURN count(r) AS count"
            ).single()["count"]
            counts["company_relationships"] = session.run(
                "MATCH ()-[r:has_subsidiary|has_affiliate|has_joint_venture|has_special_relation]->() RETURN count(r) AS count"
            ).single()["count"]
            counts["relationship_changes"] = session.run(
                "MATCH (:relationship_change) RETURN count(*) AS count"
            ).single()["count"]

            # Calculate total execution time
            total_duration = time.time() - overall_start_time

            # Display comprehensive results
            print(f"\n🎉 OPTIMIZED ETL PIPELINE COMPLETED!")
            print(f"⏱️  Total execution time: {total_duration:.2f} seconds")
            print(f"📁 Files processed: {len(files_to_process)}")
            print(f"📊 Knowledge Graph Statistics:")
            print(f"   Companies: {counts['company']}")
            print(f"   Subsidiaries: {counts['subsidiaries']}")
            print(f"   Affiliates: {counts['affiliates']}")
            print(f"   Joint Ventures: {counts['joint_ventures']}")
            print(f"   Special Relations: {counts['special_relations']}")
            print(f"   FS Sections: {counts['fs_sections']}")
            print(f"   FS Categories: {counts['fs_categories']}")
            print(f"   Year Nodes: {counts['year_nodes']}")
            print(f"   Financial Data: {counts['financial_data']}")
            print(f"   Financial Trends: {counts['financial_trends']}")
            print(f"   Auditors: {counts['auditors']}")
            print(f"   Audit Info: {counts['audit_info']}")
            print(f"   Notes: {counts['notes']}")
            print(f"   Note Categories: {counts['note_categories']}")
            print(f"   FS-Note Links: {counts['fs_note_links']}")
            print(f"   Search Documents: {counts['search_docs']}")
            print(f"   Trend Links: {counts['trend_links']}")
            print(f"   Financial Relationships: {counts['financial_relationships']}")
            print(f"   Company Relationships: {counts['company_relationships']}")
            print(f"   Relationship Changes: {counts['relationship_changes']}")

            # Final optimization
            print("\n⚡ Optimizing database...")
            with Neo4jUtils() as final_utils:
                opt_result = final_utils.optimize_database()
                if opt_result["status"] == "success":
                    print(
                        f"✅ Database optimization completed ({opt_result['duration_seconds']}s)"
                    )

    except Exception as e:
        print(f"❌ ETL pipeline failed: {e}")
        raise
    finally:
        # Driver cleanup is handled by Neo4jUtils context manager
        pass


def main() -> None:
    """Main entry point for optimized ETL pipeline."""
    import time

    parser = argparse.ArgumentParser(
        description="Run optimized ETL pipeline for Samsung Financial Knowledge Graph"
    )
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        help="Specific years to process (e.g., --years 2022 2023 2024). If not specified, processes all years.",
    )
    parser.add_argument(
        "--test-mode",
        action="store_true",
        help="Use test mode for search documents (limited processing)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Batch size for processing (default: 500)",
    )
    parser.add_argument(
        "--max-retries", type=int, default=3, help="Maximum retry attempts (default: 3)"
    )

    args = parser.parse_args()

    print("🚀 Samsung Financial Knowledge Graph - Optimized ETL Pipeline")
    print("=" * 70)
    print(f"📊 Configuration:")
    print(f"   Years: {args.years or 'All available'}")
    print(f"   Test mode: {args.test_mode}")
    print(f"   Batch size: {args.batch_size}")
    print(f"   Max retries: {args.max_retries}")
    print("=" * 70)

    run_optimized_etl(
        year_range=args.years,
        test_mode=args.test_mode,
        batch_size=args.batch_size,
        max_retries=args.max_retries,
    )


if __name__ == "__main__":
    main()
