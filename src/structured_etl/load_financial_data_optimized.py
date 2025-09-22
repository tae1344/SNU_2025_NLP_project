#!/usr/bin/env python3
"""Optimized FINANCIAL_DATA loader using ETL executor with batching and retry logic.

This is an enhanced version of load_financial_data.py that uses the ETL executor
for improved performance, reliability, and metrics collection.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import (
    build_financial_data_id,
    build_year_node_id,
    build_category_id,
    build_company_id,
)
from .etl_config import ETLConfig, extract_company_info_from_data
from .executor import (
    ETLExecutor,
    BatchConfig,
    batch_upsert_nodes,
    batch_create_relationships,
)
from .note_utils import is_note_column, normalize_note_cell


def extract_financial_data_optimized(
    processed_files: List[Path], config: ETLConfig
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract financial data for optimized batch processing.

    Args:
        processed_files: List of processed JSON file paths
        config: ETL configuration

    Returns:
        Tuple of (node_data, relationship_data)
    """
    company_name = config.company_name

    all_nodes = []
    all_relationships = []

    print(f"🔍 Extracting financial data from {len(processed_files)} files...")

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        print(f"  Processing {file_path.name} (year: {year})...")

        sections = data.get("sections", [])
        file_nodes, file_relationships = _extract_from_sections(
            sections, year, company_name
        )

        all_nodes.extend(file_nodes)
        all_relationships.extend(file_relationships)

        print(
            f"    Extracted {len(file_nodes)} nodes, {len(file_relationships)} relationships"
        )

    print(
        f"📊 Total extracted: {len(all_nodes)} nodes, {len(all_relationships)} relationships"
    )
    return all_nodes, all_relationships


def _extract_from_sections(
    sections: List[Dict[str, Any]], year: int, company_name: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract financial data from sections recursively."""
    nodes = []
    relationships = []

    for section in sections:
        section_nodes, section_rels = _process_section_tables(
            section, year, company_name
        )
        nodes.extend(section_nodes)
        relationships.extend(section_rels)

        # Process subsections recursively
        if "subsections" in section:
            sub_nodes, sub_rels = _extract_from_sections(
                section["subsections"], year, company_name
            )
            nodes.extend(sub_nodes)
            relationships.extend(sub_rels)

    return nodes, relationships


def _process_section_tables(
    section: Dict[str, Any], year: int, company_name: str
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Process tables within a section to extract financial data."""
    nodes = []
    relationships = []

    section_title = section.get("title", "")
    tables = section.get("tables", [])

    for table_idx, table in enumerate(tables):
        table_data = table.get("data", [])
        columns = table.get("columns", [])

        if len(table_data) < 2 or len(columns) < 2:
            continue

        # Determine section code from table content
        section_code = _determine_section_code_from_table(table_data, section_title)
        if not section_code:
            continue

        table_nodes, table_rels = _extract_table_data(
            table_data, columns, section_code, year, company_name, table_idx
        )
        nodes.extend(table_nodes)
        relationships.extend(table_rels)

    return nodes, relationships


def _get_section_code(section_title: str) -> Optional[str]:
    """Map section title to standardized section code."""
    section_title_lower = section_title.lower()

    if "재무상태표" in section_title or "대차대조표" in section_title:
        return "BS"
    elif "손익계산서" in section_title or "포괄손익계산서" in section_title:
        return "PL"
    elif "현금흐름표" in section_title or "현금흐름" in section_title:
        return "CF"
    elif "자본변동표" in section_title or "자본변동" in section_title:
        return "EQ"

    return None


def _determine_section_code_from_table(
    table_data: List[Dict[str, Any]], section_title: str
) -> Optional[str]:
    """Determine section code from table content using improved logic."""
    # First try section title
    section_code = _get_section_code(section_title)
    if section_code:
        return section_code

    # Collect all category names for comprehensive analysis
    all_categories = []
    for row in table_data[:15]:  # Check more rows for better accuracy
        # Check "과 목" column first (most reliable)
        category = row.get("과 목", "")
        if category:
            all_categories.append(str(category).strip().lower())

        # Also check first column as backup
        first_col = row.get("0", "")
        if first_col:
            all_categories.append(str(first_col).strip().lower())

    all_text = " ".join(all_categories)

    # Use hierarchical classification with exclusion rules (same as load_fs_categories)

    # 1. Balance Sheet - very distinctive asset/liability structure
    bs_indicators = ["자 산", "부 채"]
    bs_structure = ["유동자산", "비유동자산", "유동부채", "비유동부채"]

    if any(indicator in all_text for indicator in bs_indicators):
        # Strong BS indicators present
        if any(struct in all_text for struct in bs_structure):
            return "BS"
        elif all_text.count("자 산") > 1 or all_text.count("부 채") > 1:
            return "BS"

    # 2. Cash Flow - highly distinctive activity-based structure
    cf_activities = ["영업활동", "투자활동", "재무활동"]
    if sum(1 for activity in cf_activities if activity in all_text) >= 2:
        return "CF"
    elif "현금흐름" in all_text:
        return "CF"

    # 3. Equity - specific equity terms
    eq_core = ["자본금", "이익잉여금"]
    eq_indicators = ["자본에 직접 인식", "주주와의 거래", "자본변동"]

    if any(core in all_text for core in eq_core):
        return "EQ"
    elif any(indicator in all_text for indicator in eq_indicators):
        return "EQ"

    # 4. Comprehensive Income - specific comprehensive income terms
    ci_core = ["포괄손익", "기타포괄손익", "총포괄손익"]
    ci_count = sum(1 for term in ci_core if term in all_text)

    if ci_count >= 2:  # Multiple CI terms
        return "CI"
    elif "포괄손익" in all_text and "자 산" not in all_text and "부 채" not in all_text:
        return "CI"

    # 5. Profit & Loss - general income statement (fallback for income-related)
    pl_indicators = ["매 출", "영업이익", "매출액", "매출원가"]
    if any(indicator in all_text for indicator in pl_indicators):
        # Only classify as PL if not clearly another type
        if not any(
            term in all_text for term in ["자 산", "부 채", "영업활동", "자본금"]
        ):
            return "PL"

    return None


def _extract_table_data(
    table_data: List[Dict[str, Any]],
    columns: List[str],
    section_code: str,
    year: int,
    company_name: str,
    table_idx: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract financial data from a single table with improved logic."""
    nodes = []
    relationships = []

    if len(table_data) < 2 or len(columns) < 2:
        return nodes, relationships

    # Process each row
    for row_idx, row in enumerate(table_data):
        # Try multiple columns for item name
        item_name = None
        for key in ["과 목", "0"]:  # Try "과 목" first, then "0"
            item_candidate = row.get(key, "")
            if (
                item_candidate
                and isinstance(item_candidate, str)
                and len(item_candidate.strip()) >= 2
            ):
                item_name = item_candidate.strip()
                break

        if not item_name:
            continue

        # Skip header rows
        if _is_header_row(item_name):
            continue

        # Process each column (skip first column which is item name)
        for col_idx, col_key in enumerate(columns[1:], 1):
            value_raw = row.get(col_key, "")

            # Skip empty values
            if not value_raw and value_raw != 0:
                continue

            # If this is a note reference column, keep as string to avoid 21,22 -> 2122 numeric merge
            is_note_col = is_note_column(col_key)
            if is_note_col:
                # Render structured note objects or plain strings consistently
                value_to_store = normalize_note_cell(value_raw)
                is_negative = False
            else:
                # Parse numerical value
                parsed_value = _parse_financial_value(value_raw)
                if parsed_value is None:
                    continue
                value_to_store = parsed_value["value"]
                is_negative = parsed_value["is_negative"]

            # Create node data
            node_id = build_financial_data_id(company_name, year, item_name, col_key)

            node_data = {
                "id": node_id,
                "item_name": item_name,
                "column_name": col_key,
                "original_text": str(value_raw),
                "value": value_to_store,
                "is_negative": is_negative,
                "year": year,
                "section_code": section_code,
                "table_index": table_idx,
                "row_index": row_idx,
                "column_index": col_idx,
            }
            nodes.append(node_data)

            # Create relationship to YEAR_NODE
            year_node_id = build_year_node_id(company_name, section_code, year)
            rel_data = {
                "from_id": year_node_id,
                "to_id": node_id,
                "relationship_type": RELATIONSHIP_TYPES["CONTAINS_DATA"],
            }
            relationships.append(rel_data)

    return nodes, relationships


def _is_header_row(item_name: str) -> bool:
    """Check if a row is a header row that should be skipped."""
    header_patterns = [
        "항목",
        "구분",
        "계정",
        "단위",
        "백만원",
        "천원",
        "원",
        "당기",
        "전기",
        "기말",
        "기초",
        "증감",
        "합계",
        "소계",
    ]

    item_lower = item_name.lower()

    # "과목" 패턴은 더 정확하게 매칭
    if "과목" in item_lower:
        # "과목"이 단독으로 나타나거나 "항목"과 함께 나타날 때만 헤더로 인식
        if item_lower.strip() == "과목" or "항목" in item_lower:
            return True
        # "매출원가" 같은 실제 재무 항목은 헤더가 아님
        if any(
            term in item_lower
            for term in ["매출", "자산", "부채", "수익", "비용", "이익"]
        ):
            return False

    # 로마숫자로 시작하는 항목들은 실제 재무 항목 (헤더가 아님)
    if item_name.strip().startswith(("Ⅰ", "Ⅱ", "Ⅲ", "Ⅳ", "Ⅴ", "Ⅵ", "Ⅶ", "Ⅷ", "Ⅸ", "Ⅹ")):
        return False

    return (
        any(pattern in item_lower for pattern in header_patterns) or len(item_name) < 3
    )


def _parse_financial_value(value_str: str) -> Optional[Dict[str, Any]]:
    """Parse financial value from string with improved logic."""
    if not value_str:
        return None

    # Handle different data types
    if isinstance(value_str, (int, float)):
        return {"value": float(value_str), "is_negative": value_str < 0}

    if not isinstance(value_str, str):
        return None

    # Clean the value string
    cleaned = re.sub(r"[,\s]", "", value_str.strip())

    # Handle empty or non-numeric strings
    if not cleaned or cleaned in ["-", "None", "null", ""]:
        return None

    # Check for negative indicators
    is_negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        is_negative = True
        cleaned = cleaned[1:-1]
    elif cleaned.startswith("-"):
        is_negative = True
        cleaned = cleaned[1:]

    # Remove any remaining non-numeric characters except decimal point
    cleaned = re.sub(r"[^\d.-]", "", cleaned)

    # Handle empty after cleaning
    if not cleaned or cleaned in ["-", "."]:
        return None

    # Try to parse as number
    try:
        if "." in cleaned:
            value = float(cleaned)
        else:
            value = int(cleaned)

        if is_negative:
            value = -abs(value)

        return {"value": value, "is_negative": is_negative}
    except (ValueError, TypeError):
        return None


def batch_process_financial_nodes(session, batch: List[Dict[str, Any]]) -> int:
    """Batch processor for FINANCIAL_DATA nodes."""
    return batch_upsert_nodes(
        session=session,
        batch=batch,
        node_label=NODE_TYPES["FINANCIAL_DATA"],
        id_property="id",
        properties=[
            "item_name",
            "column_name",
            "original_text",
            "value",
            "is_negative",
            "year",
            "section_code",
            "table_index",
            "row_index",
            "column_index",
        ],
    )


def batch_process_financial_relationships(session, batch: List[Dict[str, Any]]) -> int:
    """Batch processor for CONTAINS_DATA relationships."""
    return batch_create_relationships(
        session=session,
        batch=batch,
        from_label=NODE_TYPES["YEAR_NODE"],
        to_label=NODE_TYPES["FINANCIAL_DATA"],
        relationship_type=RELATIONSHIP_TYPES["CONTAINS_DATA"],
        from_id_property="from_id",
        to_id_property="to_id",
    )


def load_financial_data_nodes_optimized(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load FINANCIAL_DATA nodes using optimized executor.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    # Extract all data first
    node_data, relationship_data = extract_financial_data_optimized(
        processed_files, config
    )

    # Initialize executor with optimized configuration
    batch_config = BatchConfig(
        batch_size=500,  # Larger batches for better performance
        max_retries=3,
        retry_delay=1.0,
        retry_backoff=2.0,
    )
    executor = ETLExecutor(batch_config)

    # Process nodes
    node_metrics = executor.execute_batch_operation(
        session=session,
        operation_name="FINANCIAL_DATA Nodes",
        data_items=node_data,
        batch_processor=batch_process_financial_nodes,
    )

    # Process relationships
    rel_metrics = executor.execute_batch_operation(
        session=session,
        operation_name="CONTAINS_DATA Relationships",
        data_items=relationship_data,
        batch_processor=batch_process_financial_relationships,
    )

    # Summary
    print(f"\n✅ Optimized FINANCIAL_DATA loading completed!")
    print(
        f"   Nodes: {node_metrics.processed_items}/{node_metrics.total_items} "
        f"({node_metrics.success_rate:.1f}% success)"
    )
    print(
        f"   Relationships: {rel_metrics.processed_items}/{rel_metrics.total_items} "
        f"({rel_metrics.success_rate:.1f}% success)"
    )
    print(
        f"   Total time: {node_metrics.duration_seconds + rel_metrics.duration_seconds:.2f}s"
    )

    # Save metrics
    metrics_path = Path("results") / "financial_data_metrics.json"
    metrics_path.parent.mkdir(exist_ok=True)
    executor.save_metrics(metrics_path)


if __name__ == "__main__":
    # Test optimized financial data loading
    from .etl_config import DEFAULT_CONFIG
    from .neo4j_client import load_config, create_driver, neo4j_session

    config = DEFAULT_CONFIG
    recent_years = [2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        print(
            f"Testing optimized FINANCIAL_DATA loading with {len(available_files)} files"
        )

        # Extract data without Neo4j connection for testing
        node_data, rel_data = extract_financial_data_optimized(available_files, config)

        print(f"\n📊 Extraction Results:")
        print(f"  Financial data nodes: {len(node_data)}")
        print(f"  Relationships: {len(rel_data)}")

        if node_data:
            sample_node = node_data[0]
            print(f"\n📄 Sample node:")
            for key, value in sample_node.items():
                print(f"    {key}: {value}")

    else:
        print("No processed files found for testing")
