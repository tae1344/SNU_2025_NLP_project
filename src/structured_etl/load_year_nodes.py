from __future__ import annotations

"""Load YEAR_NODE and create HAS_YEAR_DATA and TREND_TO relationships.

Creates year nodes for each financial statement section and links them
in temporal order to enable time-series analysis.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_fs_section_id, build_year_node_id
from .etl_config import (
    ETLConfig,
    extract_company_info_from_data,
    read_fs_tables_cache,
)


def detect_actual_sections_in_data(file_key: str) -> Set[str]:
    """Detect which financial statement sections actually have data using cache.

    This refactoring uses fs_tables_index.json to determine the sections with
    identified tables for the given file, avoiding ad-hoc re-parsing.
    """
    actual_sections: Set[str] = set()

    # Identify file key (processed JSON filename)
    if not file_key:
        # Fallback: cannot map to cache without filename
        return actual_sections

    # Read cache and get per-file entry
    cache = read_fs_tables_cache()
    entry = (cache or {}).get("files", {}).get(file_key, {})
    fs_sections = entry.get("fs_sections", {})

    # Sections present in cache have data
    for code in fs_sections.keys():
        actual_sections.add(code)

    return actual_sections


def load_year_nodes(session, processed_files: List[Path], config: ETLConfig) -> None:
    """Load YEAR_NODE nodes and HAS_YEAR_DATA relationships with data validation.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)

    # Collect year-section pairs with data availability info
    year_section_data = {}  # (year, section_code) -> has_data

    # Process all files to collect year-section pairs and check data availability
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        # Detect which sections actually have data (via cache)
        actual_sections = detect_actual_sections_in_data(file_path.name)

        # Create entries for all configured sections
        for section_code in config.fs_sections:
            has_data = section_code in actual_sections
            year_section_data[(year, section_code)] = has_data

    print(f"Detected year-section combinations: {len(year_section_data)}")

    # Count data availability
    with_data = sum(1 for has_data in year_section_data.values() if has_data)
    without_data = len(year_section_data) - with_data
    print(f"  - With data: {with_data}")
    print(f"  - Without data: {without_data}")

    # Create YEAR_NODE nodes and HAS_YEAR_DATA relationships
    created_count = 0
    for (year, section_code), has_data in year_section_data.items():
        year_node_id = build_year_node_id(company_name, section_code, year)
        fs_section_id = build_fs_section_id(company_name, section_code)

        # Get section name from section code
        section_names = {
            "BS": "재무상태표",
            "PL": "손익계산서",
            "CI": "포괄손익계산서",
            "CF": "현금흐름표",
            "EQ": "자본변동표",
        }
        section_name = section_names.get(section_code, section_code)

        # Create YEAR_NODE with data availability metadata
        session.run(
            f"""
            MERGE (yn:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $year_node_id }})
            ON CREATE SET 
                yn.{PROPS['year']} = $year,
                yn.{PROPS['section_code']} = $section_code,
                yn.section_name = $section_name,
                yn.{PROPS['company']} = $company_name,
                yn.has_data = $has_data,
                yn.data_source_validated = true
            ON MATCH SET
                yn.{PROPS['year']} = coalesce(yn.{PROPS['year']}, $year),
                yn.{PROPS['section_code']} = coalesce(yn.{PROPS['section_code']}, $section_code),
                yn.section_name = coalesce(yn.section_name, $section_name),
                yn.{PROPS['company']} = coalesce(yn.{PROPS['company']}, $company_name),
                yn.has_data = coalesce(yn.has_data, $has_data),
                yn.data_source_validated = true
            """,
            {
                "year_node_id": year_node_id,
                "year": year,
                "section_code": section_code,
                "section_name": section_name,
                "company_name": company_name,
                "has_data": has_data,
            },
        )

        # Create HAS_YEAR_DATA relationship from FS_SECTION to YEAR_NODE
        session.run(
            f"""
            MATCH (fs:{NODE_TYPES['FS_SECTION']} {{ {PROPS['id']}: $fs_section_id }})
            MATCH (yn:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $year_node_id }})
            MERGE (fs)-[r:{RELATIONSHIP_TYPES['HAS_YEAR_DATA']}]->(yn)
            ON CREATE SET r.has_actual_data = $has_data
            ON MATCH SET r.has_actual_data = coalesce(r.has_actual_data, $has_data)
            """,
            {
                "fs_section_id": fs_section_id,
                "year_node_id": year_node_id,
                "has_data": has_data,
            },
        )

        created_count += 1

    print(f"✅ Created/updated {created_count} year nodes and relationships")


def create_trend_relationships(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Create TREND_TO relationships between consecutive YEAR_NODEs.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name

    # Collect all years from processed files
    years = set()
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        years.add(company_info["year"])

    # Sort years for consecutive linking
    sorted_years = sorted(years)

    # Create TREND_TO relationships for each section
    for section_code in config.fs_sections:
        for i in range(len(sorted_years) - 1):
            current_year = sorted_years[i]
            next_year = sorted_years[i + 1]

            current_year_node_id = build_year_node_id(
                company_name, section_code, current_year
            )
            next_year_node_id = build_year_node_id(
                company_name, section_code, next_year
            )

            # Create TREND_TO relationship
            session.run(
                f"""
                MATCH (current:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $current_id }})
                MATCH (next:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $next_id }})
                MERGE (current)-[:{RELATIONSHIP_TYPES['TREND_TO']}]->(next)
                """,
                {"current_id": current_year_node_id, "next_id": next_year_node_id},
            )


def load_year_nodes_with_trends(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load YEAR_NODEs and create both HAS_YEAR_DATA and TREND_TO relationships.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    # First load year nodes and HAS_YEAR_DATA relationships
    load_year_nodes(session, processed_files, config)

    # Then create TREND_TO relationships between consecutive years
    create_trend_relationships(session, processed_files, config)


if __name__ == "__main__":
    # Test extraction with available files
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        print(f"Testing year nodes with {len(available_files)} files")

        # Test with all recent files
        test_files = available_files

        for test_file in test_files:
            with open(test_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            company_info = extract_company_info_from_data(data)
            print(
                f"\n{test_file.name}: {company_info['name']} ({company_info['year']})"
            )

            # Show what year nodes would be created
            print("  Year nodes that would be created:")
            for section_code in config.fs_sections:
                year_node_id = build_year_node_id(
                    company_info["name"], section_code, company_info["year"]
                )
                print(
                    f"    {section_code}-{company_info['year']}: {year_node_id[:20]}..."
                )
    else:
        print("No processed files found for testing")
