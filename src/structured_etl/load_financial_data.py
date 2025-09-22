from __future__ import annotations

"""Load FINANCIAL_DATA nodes and create CONTAINS_DATA relationships.

Extracts actual financial values from tables and creates data nodes
with proper relationships to YEAR_NODE and FS_CATEGORY nodes.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import (
    build_company_id,
    build_year_node_id,
    build_category_id,
    build_financial_data_id,
)
from .etl_config import ETLConfig, extract_company_info_from_data


def clean_financial_value(value: str) -> Optional[Dict[str, Any]]:
    """Clean and parse financial values from table cells.

    Args:
        value: Raw value from financial table

    Returns:
        Dict with parsed value info or None if not a valid number
    """
    if not isinstance(value, str) or not value.strip():
        return None

    # Remove common formatting
    cleaned = value.strip().replace(",", "").replace("(", "-").replace(")", "")

    # Check for negative indicators
    is_negative = cleaned.startswith("-") or "(" in value

    # Extract numeric part
    numeric_match = re.search(r"[\d,]+", cleaned.replace("-", ""))
    if not numeric_match:
        return None

    try:
        numeric_value = int(numeric_match.group().replace(",", ""))
        if is_negative:
            numeric_value = -numeric_value

        return {
            "value": numeric_value,
            "original_text": value.strip(),
            "unit": "KRW_MILLION",  # Assume millions of KRW for Samsung reports
            "is_negative": is_negative,
        }
    except (ValueError, AttributeError):
        return None


def determine_section_from_table_structure(
    table_data: List[Dict[str, Any]], columns: List[str]
) -> str:
    """Determine financial statement section from table structure.

    Args:
        table_data: Table data rows
        columns: Column names

    Returns:
        Section code (BS/PL/CF/EQ) or empty string
    """
    # Look at first few rows for section indicators
    for row in table_data[:10]:
        item_name = row.get("과 목", "").strip().lower()

        # Balance Sheet indicators
        if any(
            keyword in item_name
            for keyword in ["자 산", "유동자산", "비유동자산", "부 채", "자 본"]
        ):
            return "BS"

        # Income Statement indicators
        elif any(
            keyword in item_name
            for keyword in ["매 출", "영업이익", "당기순이익", "수익", "비용"]
        ):
            return "PL"

        # Cash Flow indicators
        elif any(
            keyword in item_name
            for keyword in ["영업활동", "투자활동", "재무활동", "현금흐름"]
        ):
            return "CF"

        # Equity Statement indicators
        elif any(
            keyword in item_name
            for keyword in ["자본금", "이익잉여금", "기타자본", "자본변동"]
        ):
            return "EQ"

    return ""


def extract_financial_data_from_table(
    table: Dict[str, Any], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract financial data points from a single table.

    Args:
        table: Table data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of financial data point dictionaries
    """
    data_points = []
    table_data = table.get("data", [])
    columns = table.get("columns", [])

    if not table_data or len(columns) < 2:
        return data_points

    # Determine section type
    section_code = determine_section_from_table_structure(table_data, columns)
    if not section_code:
        return data_points

    # Extract data from each row
    for row in table_data:
        item_name = row.get("과 목", "").strip()
        if not item_name or item_name in ["과 목", ""]:
            continue

        # Process each numeric column
        for column_name in columns[1:]:  # Skip first column (item names)
            if column_name == "주석":  # Skip notes column
                continue

            raw_value = row.get(column_name)
            if raw_value is None:
                continue

            # Parse financial value
            parsed_value = clean_financial_value(str(raw_value))
            if parsed_value is None:
                continue

            # Create data point
            data_point = {
                "item_name": item_name,
                "column_name": column_name,
                "section_code": section_code,
                "year": year,
                "company_name": company_name,
                "value": parsed_value["value"],
                "original_text": parsed_value["original_text"],
                "unit": parsed_value["unit"],
                "is_negative": parsed_value["is_negative"],
                "note_references": (
                    row.get("주석", {}).get("note_numbers", [])
                    if isinstance(row.get("주석"), dict)
                    else []
                ),
            }

            data_points.append(data_point)

    return data_points


def load_financial_data_nodes(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load FINANCIAL_DATA nodes and CONTAINS_DATA relationships.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    all_data_points: List[Dict[str, Any]] = []

    # Process all files to collect financial data
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        # Extract financial data from tables
        sections = data.get("sections", [])
        for section in sections:
            tables = section.get("tables", [])

            for table in tables:
                if not table.get("metadata", {}).get("is_financial_table", False):
                    continue

                table_data_points = extract_financial_data_from_table(
                    table, year, company_name
                )
                all_data_points.extend(table_data_points)

    print(f"Extracted {len(all_data_points)} financial data points")

    # Create FINANCIAL_DATA nodes and relationships
    for data_point in all_data_points:
        financial_data_id = build_financial_data_id(
            data_point["company_name"],
            data_point["year"],
            data_point["item_name"],
            data_point["column_name"],
        )

        # Create FINANCIAL_DATA node
        session.run(
            f"""
            MERGE (fd:{NODE_TYPES['FINANCIAL_DATA']} {{ {PROPS['id']}: $financial_data_id }})
            ON CREATE SET 
                fd.{PROPS['item_name']} = $item_name,
                fd.{PROPS['column_name']} = $column_name,
                fd.{PROPS['section_code']} = $section_code,
                fd.{PROPS['year']} = $year,
                fd.{PROPS['company']} = $company_name,
                fd.{PROPS['value']} = $value,
                fd.{PROPS['original_text']} = $original_text,
                fd.{PROPS['unit']} = $unit,
                fd.{PROPS['is_negative']} = $is_negative,
                fd.{PROPS['note_references']} = $note_references
            ON MATCH SET
                fd.{PROPS['value']} = coalesce(fd.{PROPS['value']}, $value),
                fd.{PROPS['original_text']} = coalesce(fd.{PROPS['original_text']}, $original_text),
                fd.{PROPS['unit']} = coalesce(fd.{PROPS['unit']}, $unit),
                fd.{PROPS['is_negative']} = coalesce(fd.{PROPS['is_negative']}, $is_negative),
                fd.{PROPS['note_references']} = coalesce(fd.{PROPS['note_references']}, $note_references)
            """,
            {
                "financial_data_id": financial_data_id,
                "item_name": data_point["item_name"],
                "column_name": data_point["column_name"],
                "section_code": data_point["section_code"],
                "year": data_point["year"],
                "company_name": data_point["company_name"],
                "value": data_point["value"],
                "original_text": data_point["original_text"],
                "unit": data_point["unit"],
                "is_negative": data_point["is_negative"],
                "note_references": data_point["note_references"],
            },
        )

        # Create CONTAINS_DATA relationship from YEAR_NODE to FINANCIAL_DATA
        year_node_id = build_year_node_id(
            company_name, data_point["section_code"], data_point["year"]
        )

        session.run(
            f"""
            MATCH (yn:{NODE_TYPES['YEAR_NODE']} {{ {PROPS['id']}: $year_node_id }})
            MATCH (fd:{NODE_TYPES['FINANCIAL_DATA']} {{ {PROPS['id']}: $financial_data_id }})
            MERGE (yn)-[:{RELATIONSHIP_TYPES['CONTAINS_DATA']}]->(fd)
            """,
            {"year_node_id": year_node_id, "financial_data_id": financial_data_id},
        )


if __name__ == "__main__":
    # Test financial data extraction
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        # Test with the most recent file
        test_file = available_files[-1]
        print(f"Testing financial data extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]
        company_name = company_info["name"]

        print(f"Company: {company_name}, Year: {year}")

        # Extract from all financial tables
        sections = data.get("sections", [])
        total_data_points = 0
        tables_processed = 0

        for section in sections:
            tables = section.get("tables", [])

            for table in tables:
                if table.get("metadata", {}).get("is_financial_table", False):
                    data_points = extract_financial_data_from_table(
                        table, year, company_name
                    )
                    total_data_points += len(data_points)
                    tables_processed += 1

                    if tables_processed <= 2:  # Show details for first 2 tables
                        print(
                            f"\nTable {tables_processed}: {len(data_points)} data points"
                        )
                        for i, dp in enumerate(data_points[:3]):  # Show first 3
                            print(
                                f"  {dp['item_name']}: {dp['value']:,} {dp['unit']} ({dp['column_name']})"
                            )
                        if len(data_points) > 3:
                            print(f"  ... and {len(data_points) - 3} more")

        print(
            f"\nTotal: {total_data_points} data points from {tables_processed} financial tables"
        )
    else:
        print("No processed files found for testing")
