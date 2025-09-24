from __future__ import annotations

"""Load FS_SECTION nodes and HAS_FINANCIAL_STATEMENT relationships.

Creates nodes for the four main financial statement sections:
- BS (재무상태표) - Balance Sheet
- PL (손익계산서) - Profit & Loss Statement
- CI (포괄손익계산서) - Comprehensive Income Statement
- CF (현금흐름표) - Cash Flow Statement
- EQ (자본변동표) - Equity Statement
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Final, Set

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_fs_section_id
from .etl_config import (
    ETLConfig,
    extract_company_info_from_data,
    save_fs_tables_cache,
    DEFAULT_CONFIG,
)
from .taxonomy_config import FS_KEYWORDS


# Default financial statement section mappings
DEFAULT_SECTION_NAMES: Final[Dict[str, str]] = {
    "BS": "재무상태표",
    "PL": "손익계산서",
    "CI": "포괄손익계산서",
    "CF": "현금흐름표",
    "EQ": "자본변동표",
}


def extract_fs_sections(
    processed_data: Dict[str, Any], config: ETLConfig
) -> List[Dict[str, Any]]:
    """Extract financial statement sections from processed JSON by analyzing tables.

    Args:
        processed_data: Parsed JSON data from audit report
        config: ETL configuration

    Returns:
        List of FS section info dicts with actual data presence
    """
    company_info = extract_company_info_from_data(processed_data)
    sections = []

    # Find the financial statements section (contains tables)
    fs_section = None
    for section in processed_data.get("sections", []):
        if "재 무 제 표" in section.get("title", ""):
            fs_section = section
            break

    if not fs_section:
        # Fallback: create default sections without data validation
        for section_code in config.fs_sections:
            section_name = DEFAULT_SECTION_NAMES.get(section_code, section_code)
            sections.append(
                {
                    "code": section_code,
                    "name": section_name,
                    "year": company_info["year"],
                    "company": company_info["name"],
                    "has_data": False,
                    "table_count": 0,
                }
            )
        return sections

    # Analyze tables to identify actual financial statement types
    found_fs_types = _identify_fs_types_from_tables(fs_section.get("tables", []))

    # Create sections for found types
    for fs_type, type_info in found_fs_types.items():
        section_name = DEFAULT_SECTION_NAMES.get(fs_type, fs_type)
        sections.append(
            {
                "code": fs_type,
                "name": section_name,
                "year": company_info["year"],
                "company": company_info["name"],
                "has_data": True,
                "table_count": type_info["count"],
                "table_indices": type_info["indices"],
                "title": type_info["title"],
            }
        )

    # Add missing types from config (without data)
    found_codes = set(found_fs_types.keys())
    for section_code in config.fs_sections:
        if section_code not in found_codes:
            section_name = DEFAULT_SECTION_NAMES.get(section_code, section_code)
            sections.append(
                {
                    "code": section_code,
                    "name": section_name,
                    "year": company_info["year"],
                    "company": company_info["name"],
                    "has_data": False,
                    "table_count": 0,
                }
            )

    return sections


def _identify_fs_types_from_tables(
    tables: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Identify financial statement types from table content.

    Args:
        tables: List of table dictionaries

    Returns:
        Dict mapping FS type codes to type info
    """
    # Keywords for each financial statement type (with variations)
    fs_keywords = FS_KEYWORDS

    found_types = {}

    for i, table in enumerate(tables):
        # Extract all text from table (HTML + data)
        all_text = ""

        # HTML text
        table_html = table.get("table_html", "")
        if table_html:
            html_text = re.sub(r"<[^>]+>", " ", table_html)
            all_text += html_text

        # Data text
        table_data = table.get("data", [])
        for row in table_data:
            for value in row.values():
                if value:
                    all_text += " " + str(value)

        # Check for FS type keywords
        for fs_type, keywords in fs_keywords.items():
            for keyword in keywords:
                # Check both original and space-normalized versions
                if keyword in all_text or re.sub(r"\s+", "", keyword) in re.sub(
                    r"\s+", "", all_text
                ):
                    if fs_type not in found_types:
                        found_types[fs_type] = {
                            "count": 0,
                            "indices": [],
                            "title": re.sub(r"\s+", "", keyword).strip(),
                        }

                    found_types[fs_type]["count"] += 1
                    found_types[fs_type]["indices"].append(
                        i + 1
                    )  # 실제 재무제표의 데이터 table은 타이틀 정보가 있는 그 다음 table에 있음!
            # Special handling for CI (포괄손익계산서) - distinguish from PL
            if fs_type == "CI" and any(
                keyword in all_text for keyword in fs_keywords["CI"]
            ):
                # Remove from PL if it was incorrectly classified
                if "PL" in found_types:
                    pl_indices = found_types["PL"]["indices"]
                    if i in pl_indices:
                        pl_indices.remove(i)
                        found_types["PL"]["count"] -= 1
                        if found_types["PL"]["count"] == 0:
                            del found_types["PL"]

    # Post-processing: deduplicate indices and normalize counts
    for fs_type, info in list(found_types.items()):
        unique_indices = sorted(set(info.get("indices", [])))
        info["indices"] = unique_indices
        info["count"] = len(unique_indices)

    # Ensure PL excludes any indices that are classified as CI
    if "PL" in found_types and "CI" in found_types:
        ci_set = set(found_types["CI"].get("indices", []))
        pl_indices = [
            idx for idx in found_types["PL"].get("indices", []) if idx not in ci_set
        ]
        found_types["PL"]["indices"] = pl_indices
        found_types["PL"]["count"] = len(pl_indices)
        if found_types["PL"]["count"] == 0:
            del found_types["PL"]

    return found_types


def load_fs_section_nodes(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load FS_SECTION nodes and HAS_FINANCIAL_STATEMENT relationships with deduplication.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)  # TODO : 회사 id가 중복 생성되는지 체크

    # Ensure COMPANY node exists
    session.run(
        f"""
        MERGE (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $id }})
        ON CREATE SET c.{PROPS['name']} = $name
        """,
        {"id": company_id, "name": company_name},
    )

    # Track processed sections to avoid duplicates
    processed_sections: Set[str] = set()
    all_fs_sections = []

    # Collect all FS sections from all files
    cache_payload: Dict[str, Any] = {"metadata": {"version": 1}, "files": {}}
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        fs_sections = extract_fs_sections(data, config)
        all_fs_sections.extend(fs_sections)

        # Build per-file cache entry (best-effort)
        try:
            company_info = extract_company_info_from_data(data)
            file_key = file_path.name
            fs_map: Dict[str, Any] = {}
            for s in fs_sections:
                if s.get("has_data"):
                    fs_map[s["code"]] = {
                        "title": s.get("title", ""),
                        "table_indices": s.get("table_indices", []),
                    }
            cache_payload["files"][file_key] = {
                "year": company_info.get("year"),
                "company": company_info.get("name"),
                "fs_sections": fs_map,
            }
        except Exception:
            pass

    print(
        f"Extracted {len(all_fs_sections)} FS sections from {len(processed_files)} files"
    )

    # Persist cache to disk
    save_fs_tables_cache(cache_payload)

    # Deduplicate by section code (same FS type should have one node)
    unique_sections = {}
    for fs_section in all_fs_sections:
        section_code = fs_section["code"]

        if section_code not in unique_sections:
            unique_sections[section_code] = fs_section
        else:
            # Merge information: prefer sections with data
            existing = unique_sections[section_code]
            if fs_section.get("has_data", False) and not existing.get(
                "has_data", False
            ):
                unique_sections[section_code] = fs_section
            elif fs_section.get("table_count", 0) > existing.get("table_count", 0):
                unique_sections[section_code] = fs_section

    print(f"After deduplication: {len(unique_sections)} unique FS sections")

    # Create nodes and relationships for unique sections
    created_count = 0
    for fs_section in unique_sections.values():
        section_id = build_fs_section_id(company_name, fs_section["code"])

        # Skip if already processed
        if section_id in processed_sections:
            continue

        # Create FS_SECTION node with enhanced properties
        session.run(
            f"""
            MERGE (s:{NODE_TYPES['FS_SECTION']} {{ {PROPS['id']}: $section_id }})
            ON CREATE SET 
                s.{PROPS['section_code']} = $code,
                s.{PROPS['name']} = $name,
                s.{PROPS['company']} = $company_name,
                s.has_data = $has_data,
                s.table_count = $table_count,
                s.title = $title
            ON MATCH SET
                s.{PROPS['section_code']} = coalesce(s.{PROPS['section_code']}, $code),
                s.{PROPS['name']} = coalesce(s.{PROPS['name']}, $name),
                s.{PROPS['company']} = coalesce(s.{PROPS['company']}, $company_name),
                s.has_data = coalesce(s.has_data, $has_data),
                s.table_count = coalesce(s.table_count, $table_count),
                s.title = coalesce(s.title, $title)
            """,
            {
                "section_id": section_id,
                "code": fs_section["code"],
                "name": fs_section["name"],
                "company_name": company_name,
                "has_data": fs_section.get("has_data", False),
                "table_count": fs_section.get("table_count", 0),
                "title": fs_section.get("title", ""),
            },
        )

        # Create HAS_FINANCIAL_STATEMENT relationship (idempotent)
        session.run(
            f"""
            MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
            MATCH (s:{NODE_TYPES['FS_SECTION']} {{ {PROPS['id']}: $section_id }})
            MERGE (c)-[r:{RELATIONSHIP_TYPES['HAS_FINANCIAL_STATEMENT']}]->(s)
            ON CREATE SET r.created_from_data = $has_data
            """,
            {
                "company_id": company_id,
                "section_id": section_id,
                "has_data": fs_section.get("has_data", False),
            },
        )

        processed_sections.add(section_id)
        created_count += 1

    print(f"✅ Created/updated {created_count} FS section nodes and relationships")


if __name__ == "__main__":
    # Test extraction with available files
    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        # Test with the most recent file
        test_file = available_files[-1]
        print(f"Testing FS sections extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        fs_sections = extract_fs_sections(data, config)
        print(f"FS Sections found: {len(fs_sections)}")
        for section in fs_sections:
            print(f"  {section['code']}: {section['name']} ({section['year']})")
    else:
        print("No processed files found for testing")
