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
    build_note_id,
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
from .note_utils import (
    is_note_column,
    normalize_note_cell,
    normalize_notes_array,
    extract_note_numbers,
)
from .load_fs_categories import (
    determine_hierarchy_level,
    clean_category_name,
)


# --- Column normalization helpers -------------------------------------------------
def _normalize_period_column_name(column_name: str) -> Optional[str]:
    """Normalize period-related column names to stable keys.

    Examples:
        "제 56 (당) 기" -> "당기"
        "제 56 (당) 기.1" -> "당기"
        "제55(전)기" -> "전기"
        "당기" -> "당기"
        "전기" -> "전기"

    Returns normalized key ("당기"/"전기") or None if not a period column.
    """
    key = re.sub(r"\s+", "", column_name)
    # Strip trailing .N suffixes (e.g., ".1")
    key = re.sub(r"\.\d+$", "", key)
    # Direct matches
    if re.search(r"당기|\(당\)기", key):
        return "당기"
    if re.search(r"전기|\(전\)기", key):
        return "전기"
    return None


def _disambiguate_key(base_key: str, existing: Dict[str, Any]) -> str:
    """Ensure no overwrites when duplicate normalized period columns exist.

    Produces base_key, base_key_2, base_key_3, ...
    """
    if base_key not in existing:
        return base_key
    index = 2
    while f"{base_key}_{index}" in existing:
        index += 1
    return f"{base_key}_{index}"


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
                section["subsections"], year, company_name, cache_entry
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


# TODO: =============
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

    # Process each row with category context tracking (row-level node)
    last_path_by_level: Dict[int, str] = {0: section_code}
    current_category_path: Optional[str] = None
    current_level: int = 1

    # Build a per-table normalized columns map for period-like keys
    normalized_columns_map: Dict[str, str] = {}
    normalized_columns_list: List[str] = []

    if columns:
        # preserve first column (category key)
        first_col = columns[0]
        normalized_columns_list.append(first_col)
        for col_key in columns[1:]:
            norm_key = _normalize_period_column_name(col_key) or col_key
            normalized_columns_map[col_key] = norm_key
            # keep unique order for normalized columns
            if norm_key not in normalized_columns_list:
                normalized_columns_list.append(norm_key)

    for row_idx, row in enumerate(table_data):
        # Source cell for both category context and item naming
        raw_cell = None
        for key in ["과 목", "0"]:
            v = row.get(key, "")
            if isinstance(v, str) and v.strip():
                raw_cell = v.strip()
                break

        # Update category context if present
        if raw_cell:
            lvl = determine_hierarchy_level(raw_cell, section_code)
            cleaned_title = clean_category_name(raw_cell)
            parent_level = max(0, lvl - 1)
            parent_path = last_path_by_level.get(parent_level, section_code)
            cat_path = f"{parent_path}>{cleaned_title}"
            last_path_by_level[lvl] = cat_path
            # prune deeper levels
            for lv in list(last_path_by_level.keys()):
                if lv > lvl:
                    last_path_by_level.pop(lv, None)
            current_category_path = cat_path
            current_level = lvl

        item_name = cleaned_title

        if not item_name:
            continue

        # Build row-level values and notes
        values: Dict[str, Any] = {}
        notes_normalized: Optional[Any] = None
        unit_label = None
        unit_multiplier = None
        unit_source = None
        column_units: Dict[str, Any] = {}

        for col_idx, col_key in enumerate(columns[1:], 1):
            cell = row.get(col_key, "")
            if not cell and cell != 0:
                continue
            if is_note_column(col_key):
                notes_normalized = normalize_note_cell(cell)
                continue
            parsed = _parse_financial_value(cell)
            if parsed is None:
                continue
            # Use table-level normalized column key
            normalized_key = normalized_columns_map.get(col_key, col_key)
            # Resolve unit info for context (optional, non-blocking)
            unit_info = (
                _resolve_cell_unit(
                    row_index=row_idx,
                    column_name=col_key,
                    table_metadata=table_metadata,
                )
                or {}
            )
            if not unit_label and unit_info:
                unit_label = unit_info.get("unit")
                unit_multiplier = unit_info.get("multiplier")
                unit_source = unit_info.get("source")
            if unit_info.get("column_unit"):
                column_units[normalized_key] = unit_info.get("column_unit")
            value_to_store = parsed["value"]
            # Apply scaling if needed
            if (
                isinstance(value_to_store, (int, float))
                and unit_info.get("type") == "money"
            ):
                try:
                    mult = float(unit_info.get("multiplier") or 1)
                    value_to_store = float(value_to_store) * mult
                except Exception:
                    pass
            # Ensure integer consistency for numeric values
            if isinstance(value_to_store, (int, float)):
                try:
                    value_to_store = int(round(float(value_to_store)))
                except Exception:
                    value_to_store = (
                        int(value_to_store)
                        if not isinstance(value_to_store, int)
                        else value_to_store
                    )
            values[normalized_key] = value_to_store

        # If row has no numeric values and no notes, skip
        if not values and notes_normalized is None:
            continue
        # Create a single row-level node
        node_id = build_financial_data_id(company_name, year, item_name, section_code)
        # Extract primitive period values for indexing/queries
        values_current = values.get("당기") if values else None
        values_previous = values.get("전기") if values else None
        # Normalize notes to array of strings
        notes_array = normalize_notes_array(notes_normalized)
        node_data = {
            "id": node_id,
            "item_name": item_name,
            "year": year,
            "section_code": section_code,
            "table_index": table_idx,
            "row_index": row_idx,
            "category_path": current_category_path,
            "hierarchy_level": current_level,
            # row-level aggregates
            "columns": normalized_columns_list or columns,
            "values_json": json.dumps(values, ensure_ascii=False) if values else None,
            "notes": notes_array,
            # flattened primitives for fast queries/indexing
            "values_current": values_current,
            "values_previous": values_previous,
            # unit metadata (best-effort)
            "unit": unit_label,
            "unit_multiplier": unit_multiplier,
            "unit_source": unit_source,
            "column_units_json": (
                json.dumps(column_units, ensure_ascii=False) if column_units else None
            ),
        }
        nodes.append(node_data)

        # Relationships
        year_node_id = build_year_node_id(company_name, section_code, year)
        relationships.append(
            {
                "from_id": year_node_id,
                "to_id": node_id,
                "relationship_type": RELATIONSHIP_TYPES["CONTAINS_DATA"],
            }
        )
        if current_category_path:
            category_id = build_category_id(
                company_name, section_code, current_category_path
            )
            relationships.append(
                {
                    "from_id": category_id,
                    "to_id": node_id,
                    "relationship_type": RELATIONSHIP_TYPES["RELATED_TO"],
                }
            )

        # Link notes: financial_data -> note
        if notes_array:
            note_nums: set[str] = set()
            for entry in notes_array:
                for n in extract_note_numbers(entry):
                    note_nums.add(str(n))
            for n in sorted(note_nums):
                note_id = build_note_id(company_name, year, n)
                relationships.append(
                    {
                        "from_id": node_id,
                        "to_id": note_id,
                        "relationship_type": RELATIONSHIP_TYPES["LINKS_TO_NOTE"],
                    }
                )

    # for node in nodes:
    return nodes, relationships


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
            "year",
            "section_code",
            "table_index",
            "row_index",
            "category_path",
            "hierarchy_level",
            "columns",
            "values_json",
            "notes",
            "values_current",
            "values_previous",
            "unit",
            "unit_multiplier",
            "unit_source",
            "column_units_json",
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


def batch_process_category_relationships(session, batch: List[Dict[str, Any]]) -> int:
    """Batch processor for FS_CATEGORY -> FINANCIAL_DATA RELATED_TO relationships."""
    return batch_create_relationships(
        session=session,
        batch=batch,
        from_label=NODE_TYPES["FS_CATEGORY"],
        to_label=NODE_TYPES["FINANCIAL_DATA"],
        relationship_type=RELATIONSHIP_TYPES["RELATED_TO"],
        from_id_property="from_id",
        to_id_property="to_id",
    )


def batch_process_note_relationships(session, batch: List[Dict[str, Any]]) -> int:
    """Batch processor for FINANCIAL_DATA -> NOTE LINKS_TO_NOTE relationships."""
    return batch_create_relationships(
        session=session,
        batch=batch,
        from_label=NODE_TYPES["FINANCIAL_DATA"],
        to_label=NODE_TYPES["NOTE"],
        relationship_type=RELATIONSHIP_TYPES["LINKS_TO_NOTE"],
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

    # Split and process relationships by type
    contains_rels = [
        r
        for r in relationship_data
        if r.get("relationship_type") == RELATIONSHIP_TYPES["CONTAINS_DATA"]
    ]
    category_rels = [
        r
        for r in relationship_data
        if r.get("relationship_type") == RELATIONSHIP_TYPES["RELATED_TO"]
    ]
    note_rels = [
        r
        for r in relationship_data
        if r.get("relationship_type") == RELATIONSHIP_TYPES["LINKS_TO_NOTE"]
    ]

    rel_metrics = executor.execute_batch_operation(
        session=session,
        operation_name="CONTAINS_DATA Relationships",
        data_items=contains_rels,
        batch_processor=batch_process_financial_relationships,
    )

    cat_rel_metrics = executor.execute_batch_operation(
        session=session,
        operation_name="RELATED_TO Relationships",
        data_items=category_rels,
        batch_processor=batch_process_category_relationships,
    )

    note_rel_metrics = executor.execute_batch_operation(
        session=session,
        operation_name="LINKS_TO_NOTE Relationships",
        data_items=note_rels,
        batch_processor=batch_process_note_relationships,
    )

    # Summary
    print(f"\n✅ Optimized FINANCIAL_DATA loading completed!")
    print(
        f"   Nodes: {node_metrics.processed_items}/{node_metrics.total_items} "
        f"({node_metrics.success_rate:.1f}% success)"
    )
    print(
        f"   Relationships: {rel_metrics.processed_items + cat_rel_metrics.processed_items + note_rel_metrics.processed_items}/"
        f"{rel_metrics.total_items + cat_rel_metrics.total_items + note_rel_metrics.total_items} "
        f"(contains: {rel_metrics.processed_items}, related_to: {cat_rel_metrics.processed_items}, notes: {note_rel_metrics.processed_items})"
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
