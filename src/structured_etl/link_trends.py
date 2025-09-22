#!/usr/bin/env python3
"""Create TREND_TO relationships between consecutive YEAR_NODE nodes.

This module creates temporal relationships between year nodes to enable
time series analysis and trend tracking across financial statement sections.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_year_node_id, build_company_id
from .etl_config import ETLConfig, extract_company_info_from_data


def create_trend_relationships(
    session, processed_files: List[Path], config: ETLConfig
) -> Dict[str, Any]:
    """Create TREND_TO relationships between consecutive year nodes.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration

    Returns:
        Dictionary with operation results
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)

    print(f"Creating TREND_TO relationships for {len(processed_files)} files...")

    # Extract all available years from files
    years = []
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        company_info = extract_company_info_from_data(data)
        years.append(company_info["year"])

    # Sort years to ensure correct chronological order
    years = sorted(set(years))
    print(f"Available years: {years}")

    if len(years) < 2:
        print("⚠️  Need at least 2 years to create trend relationships")
        return {
            "status": "skipped",
            "message": "Insufficient years for trend creation",
            "years_available": len(years),
            "trend_links_created": 0,
        }

    # Get all financial statement sections with their section codes
    fs_sections = session.run(
        f"""
        MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
        -[:{RELATIONSHIP_TYPES['HAS_FINANCIAL_STATEMENT']}]->(fs:{NODE_TYPES['FS_SECTION']})
        RETURN fs.{PROPS['id']} AS section_id, 
               fs.{PROPS['name']} AS section_name,
               fs.{PROPS['section_code']} AS section_code
        """,
        {"company_id": company_id},
    ).data()

    print(f"Found {len(fs_sections)} financial statement sections")

    total_links_created = 0
    section_link_counts = {}

    # Create trend relationships for each section
    for section in fs_sections:
        section_name = section["section_name"]
        section_code = section["section_code"]

        print(f"  Creating trends for section: {section_name} ({section_code})")

        links_created = 0

        # Create consecutive year links for this section
        for i in range(len(years) - 1):
            current_year = years[i]
            next_year = years[i + 1]

            # Use section_code for consistent ID generation (matching load_year_nodes.py)
            current_year_id = build_year_node_id(
                company_name, section_code, current_year
            )
            next_year_id = build_year_node_id(company_name, section_code, next_year)

            # Verify nodes exist before creating relationship
            current_exists = session.run(
                f"""
                MATCH (yn:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $year_id }})
                RETURN yn.{PROPS['year']} as year, yn.{PROPS['section_code']} as section_code
                """,
                {"year_id": current_year_id},
            ).single()

            next_exists = session.run(
                f"""
                MATCH (yn:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $year_id }})
                RETURN yn.{PROPS['year']} as year, yn.{PROPS['section_code']} as section_code
                """,
                {"year_id": next_year_id},
            ).single()

            if not current_exists or not next_exists:
                print(
                    f"    ⚠️  Missing YEAR_NODE: {current_year} or {next_year} for {section_code}"
                )
                continue

            # Create TREND_TO relationship with proper attributes
            result = session.run(
                f"""
                MATCH (current:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $current_id }})
                MATCH (next:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $next_id }})
                MERGE (current)-[trend:{RELATIONSHIP_TYPES['TREND_TO']}]->(next)
                ON CREATE SET 
                    trend.year_from = $current_year,
                    trend.year_to = $next_year,
                    trend.section_name = $section_name,
                    trend.section_code = $section_code,
                    trend.created_at = datetime()
                ON MATCH SET
                    trend.year_from = $current_year,
                    trend.year_to = $next_year,
                    trend.section_name = $section_name,
                    trend.section_code = $section_code
                RETURN trend
                """,
                {
                    "current_id": current_year_id,
                    "next_id": next_year_id,
                    "current_year": current_year,
                    "next_year": next_year,
                    "section_name": section_name,
                    "section_code": section_code,
                },
            )

            if result.single():
                links_created += 1
                print(f"    ✓ {current_year} → {next_year}")

        section_link_counts[section_name] = links_created
        total_links_created += links_created

        print(f"    Created {links_created} trend links for {section_name}")

    # Summary
    result = {
        "status": "success",
        "years_processed": years,
        "sections_processed": len(fs_sections),
        "trend_links_created": total_links_created,
        "section_link_counts": section_link_counts,
        "expected_links_per_section": len(years) - 1,
    }

    print(f"\n📊 TREND_TO Creation Summary:")
    print(f"  Years processed: {years}")
    print(f"  Sections: {len(fs_sections)}")
    print(f"  Total trend links created: {total_links_created}")
    print(f"  Expected links per section: {len(years) - 1}")
    print(f"  Section breakdown:")
    for section_name, count in section_link_counts.items():
        print(f"    {section_name}: {count} links")

    return result


def validate_trend_relationships(session, config: ETLConfig) -> Dict[str, Any]:
    """Validate created TREND_TO relationships.

    Args:
        session: Neo4j session
        config: ETL configuration

    Returns:
        Dictionary with validation results
    """
    print("🔍 Validating TREND_TO relationships...")

    # Count total trend relationships
    total_trends = session.run(
        f"""
        MATCH ()-[trend:{RELATIONSHIP_TYPES['TREND_TO']}]->()
        RETURN count(trend) AS total_trends
        """
    ).single()["total_trends"]

    # Trends by section
    trends_by_section = session.run(
        f"""
        MATCH (from:year_node)-[trend:{RELATIONSHIP_TYPES['TREND_TO']}]->(to:year_node)
        RETURN from.section_code AS section_code, 
               from.section_name AS section_name,
               count(trend) AS trend_count
        ORDER BY trend_count DESC
        """
    ).data()

    print(f"  Total TREND_TO relationships: {total_trends}")

    if trends_by_section:
        print(f"  Trends by section:")
        for record in trends_by_section:
            section_name = record["section_name"] or record["section_code"]
            print(
                f"    {section_name} ({record['section_code']}): {record['trend_count']} links"
            )

    return {
        "total_trends": total_trends,
        "trends_by_section": {
            r["section_code"]: r["trend_count"] for r in trends_by_section
        },
    }


def load_trend_relationships(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Main function to create and validate TREND_TO relationships.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    try:
        # Create the trend relationships
        creation_result = create_trend_relationships(session, processed_files, config)

        # Validate the results
        validation_result = validate_trend_relationships(session, config)

        # Enhanced summary
        links_created = creation_result.get("trend_links_created", 0)
        sections_processed = creation_result.get("sections_processed", 0)
        total_trends = validation_result.get("total_trends", 0)

        print(f"\n✅ TREND_TO relationships completed!")
        print(f"   Links created: {links_created}")
        print(f"   Sections processed: {sections_processed}")
        print(f"   Total trends in DB: {total_trends}")

        # Check for discrepancies
        if links_created != total_trends:
            print(
                f"   ⚠️  Discrepancy: Created {links_created} but DB has {total_trends}"
            )
        else:
            print(f"   ✅ Consistency check passed")

    except Exception as e:
        print(f"⚠️ Error in trend relationships processing: {e}")
        import traceback

        traceback.print_exc()
        print(f"\n✅ TREND_TO relationships completed with errors!")
        print(f"   Links created: 0")
        print(f"   Sections processed: 0")
