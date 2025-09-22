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
from .etl_config import ETLConfig, extract_company_info_from_data


def detect_actual_sections_in_data(data: Dict[str, Any]) -> Set[str]:
    """Detect which financial statement sections actually have data.

    Args:
        data: Processed JSON data from audit report

    Returns:
        Set of section codes that have actual data
    """
    sections = data.get("sections", [])
    actual_sections = set()

    # Find the financial statements section
    fs_section = None
    for section in sections:
        if "재 무 제 표" in section.get("title", ""):
            fs_section = section
            break

    if not fs_section:
        return actual_sections

    tables = fs_section.get("tables", [])
    financial_tables = [
        table
        for table in tables
        if table.get("metadata", {}).get("is_financial_table", False)
    ]

    # Analyze each financial table to determine section type
    for table in financial_tables:
        table_data = table.get("data", [])
        if not table_data or "과 목" not in table_data[0]:
            continue

        # Collect category names for section classification
        all_categories = []
        for row in table_data[:15]:
            category = row.get("과 목", "").strip()
            if category:
                all_categories.append(category.lower())

        all_text = " ".join(all_categories)

        # Use hierarchical classification with proper exclusion rules
        # (Same logic as improved load_fs_categories.py)

        # 1. Balance Sheet - very distinctive asset/liability structure
        bs_indicators = ["자 산", "부 채"]
        bs_structure = ["유동자산", "비유동자산", "유동부채", "비유동부채"]

        if any(indicator in all_text for indicator in bs_indicators):
            # Strong BS indicators present
            if any(struct in all_text for struct in bs_structure):
                actual_sections.add("BS")
                continue
            elif all_text.count("자 산") > 1 or all_text.count("부 채") > 1:
                actual_sections.add("BS")
                continue

        # 2. Cash Flow - highly distinctive activity-based structure
        cf_activities = ["영업활동", "투자활동", "재무활동"]
        if sum(1 for activity in cf_activities if activity in all_text) >= 2:
            actual_sections.add("CF")
            continue
        elif "현금흐름" in all_text:
            actual_sections.add("CF")
            continue

        # 3. Equity - specific equity terms
        eq_core = ["자본금", "이익잉여금"]
        eq_indicators = ["자본에 직접 인식", "주주와의 거래", "자본변동"]

        if any(core in all_text for core in eq_core):
            actual_sections.add("EQ")
            continue
        elif any(indicator in all_text for indicator in eq_indicators):
            actual_sections.add("EQ")
            continue

        # 4. Comprehensive Income - specific comprehensive income terms
        # Must be dominant theme, not just mentioned
        ci_core = ["포괄손익", "기타포괄손익", "총포괄손익"]
        ci_count = sum(1 for term in ci_core if term in all_text)

        # Check if CI is the main theme (not just mentioned in BS context)
        if ci_count >= 2:  # Multiple CI terms
            actual_sections.add("CI")
            continue
        elif (
            "포괄손익" in all_text
            and "자 산" not in all_text
            and "부 채" not in all_text
        ):
            actual_sections.add("CI")
            continue

        # 5. Profit & Loss - general income statement (fallback for income-related)
        pl_indicators = ["매 출", "영업이익", "매출액", "매출원가"]
        if any(indicator in all_text for indicator in pl_indicators):
            # Only classify as PL if not clearly another type
            if not any(
                term in all_text for term in ["자 산", "부 채", "영업활동", "자본금"]
            ):
                actual_sections.add("PL")
                continue

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

        # Detect which sections actually have data
        actual_sections = detect_actual_sections_in_data(data)

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

        # Create YEAR_NODE with data availability metadata
        session.run(
            f"""
            MERGE (yn:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $year_node_id }})
            ON CREATE SET 
                yn.{PROPS['year']} = $year,
                yn.{PROPS['section_code']} = $section_code,
                yn.{PROPS['company']} = $company_name,
                yn.has_data = $has_data,
                yn.data_source_validated = true
            ON MATCH SET
                yn.{PROPS['year']} = coalesce(yn.{PROPS['year']}, $year),
                yn.{PROPS['section_code']} = coalesce(yn.{PROPS['section_code']}, $section_code),
                yn.{PROPS['company']} = coalesce(yn.{PROPS['company']}, $company_name),
                yn.has_data = coalesce(yn.has_data, $has_data),
                yn.data_source_validated = true
            """,
            {
                "year_node_id": year_node_id,
                "year": year,
                "section_code": section_code,
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
