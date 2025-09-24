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
from .etl_config import (
    ETLConfig,
    DEFAULT_CONFIG,
    extract_company_info_from_data,
    read_fs_tables_cache,
    build_cached_indices_map,
)
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

    # Load FS tables cache once to avoid repeated reads
    fs_tables_cache = read_fs_tables_cache()

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        print(f"  Processing {file_path.name} (year: {year})...")

        sections = data.get("sections", [])

        # Per-file cache entry (best-effort)
        cache_entry = fs_tables_cache.get("files", {}).get(file_path.name, {})

        file_nodes, file_relationships = _extract_from_sections(
            sections, year, company_name, cache_entry
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
    sections: List[Dict[str, Any]],
    year: int,
    company_name: str,
    cache_entry: Dict[str, Any] | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Extract financial data from sections recursively."""
    nodes = []
    relationships = []

    for section in sections:
        section_nodes, section_rels = _process_section_tables(
            section, year, company_name, cache_entry
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
    section: Dict[str, Any],
    year: int,
    company_name: str,
    cache_entry: Dict[str, Any] | None = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Process tables within a section to extract financial data."""
    nodes = []
    relationships = []

    section_title = section.get("title", "")
    tables = section.get("tables", [])

    # Assume cache exists: Only process Financial Statements section using cached indices
    cached_fs_sections = (cache_entry or {}).get("fs_sections", {})
    if "재 무 제 표" not in section_title or not cached_fs_sections:
        return nodes, relationships

    allowed_indices, index_to_code = build_cached_indices_map(cache_entry)

    for table_idx, table in enumerate(tables):
        if table_idx not in allowed_indices:
            continue
        table_data = table.get("data", [])
        columns = table.get("columns", [])

        if len(table_data) < 2 or len(columns) < 2:
            continue

        # Section code from cache mapping
        section_code = index_to_code.get(table_idx)
        if not section_code:
            continue

        table_nodes, table_rels = _extract_table_data(
            table_data,
            columns,
            section_code,
            year,
            company_name,
            table_idx,
            table.get("metadata", {}),
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


def _extract_table_data(
    table_data: List[Dict[str, Any]],
    columns: List[str],
    section_code: str,
    year: int,
    company_name: str,
    table_idx: int,
    table_metadata: Dict[str, Any],
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

            # Resolve unit for this cell
            unit_info = _resolve_cell_unit(
                row_index=row_idx,
                column_name=col_key,
                table_metadata=table_metadata,
            )

            value_raw = value_to_store if is_note_col else value_to_store
            value_scaled = value_to_store
            unit_label = None
            unit_multiplier = None
            unit_source = None
            column_unit = None
            row_override = False

            if not is_note_col and unit_info:
                unit_label = unit_info.get("unit")
                unit_multiplier = unit_info.get("multiplier")
                unit_source = unit_info.get("source")
                column_unit = unit_info.get("column_unit")
                row_override = bool(unit_info.get("row_override"))

                # Scale only for money units with a multiplier
                if (
                    isinstance(value_to_store, (int, float))
                    and unit_info.get("type") == "money"
                ):
                    mult = unit_multiplier or 1
                    try:
                        value_scaled = float(value_to_store) * float(mult)
                    except Exception:
                        value_scaled = float(value_to_store)

            # Create node data
            node_id = build_financial_data_id(company_name, year, item_name, col_key)

            node_data = {
                "id": node_id,
                "item_name": item_name,
                "column_name": col_key,
                "original_text": str(value_raw),
                "value": value_scaled,
                "value_raw": value_to_store if not is_note_col else None,
                "is_negative": is_negative,
                "year": year,
                "section_code": section_code,
                "table_index": table_idx,
                "row_index": row_idx,
                "column_index": col_idx,
                # unit metadata
                "unit": unit_label,
                "unit_multiplier": unit_multiplier,
                "unit_source": unit_source,
                "column_unit": column_unit,
                "row_override": row_override,
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


def _resolve_cell_unit(
    row_index: int,
    column_name: str,
    table_metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Determine the effective unit for a given cell with precedence:
    row override > column hint > table base unit.

    Returns a dict including unit info and context flags.
    """
    if not table_metadata:
        return None

    # 1) Row-level override
    overrides = table_metadata.get("override_units") or {}
    row_unit = overrides.get(str(row_index)) or overrides.get(row_index)
    if isinstance(row_unit, dict):
        info = dict(row_unit)
        # row overrides apply only to that row
        info["row_override"] = True
        # propagate parsed units array if present
        return info

    # 2) Column-level hint (e.g., shares/percent). Treat as unit source 'column'
    col_units = table_metadata.get("column_units") or {}
    col_unit = col_units.get(column_name)
    if col_unit:
        # normalize simple hints
        if col_unit in ("주", "천주"):
            return {
                "unit": col_unit,
                "type": "shares",
                "multiplier": 1000 if col_unit == "천주" else 1,
                "source": "column",
                "column_unit": col_unit,
                "row_override": False,
            }
        if col_unit == "%":
            return {
                "unit": "%",
                "type": "percent",
                "multiplier": None,
                "source": "column",
                "column_unit": "%",
                "row_override": False,
            }

    # 3) Table base unit
    base_unit = table_metadata.get("unit")
    if isinstance(base_unit, dict):
        info = dict(base_unit)
        # Normalize type for downstream logic
        unit_label = info.get("unit")
        if unit_label in ("원", "천원", "백만원", "억원"):
            info["type"] = "money"
        info["row_override"] = False
        return info

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
            "value_raw",
            "is_negative",
            "year",
            "section_code",
            "table_index",
            "row_index",
            "column_index",
            "unit",
            "unit_multiplier",
            "unit_source",
            "column_unit",
            "row_override",
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
