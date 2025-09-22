#!/usr/bin/env python3
"""Link FS_CATEGORY nodes to NOTE nodes via LINKS_TO_NOTE relationships.

Creates relationships between financial statement categories and notes based on
note references found in financial tables.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_category_id, build_note_id
from .etl_config import ETLConfig, extract_company_info_from_data


def clean_category_name(item_name: str) -> str:
    """Clean category name by removing numbering prefixes.

    Args:
        item_name: Raw item name (e.g., "1. 현금및현금성자산")

    Returns:
        Cleaned item name (e.g., "현금및현금성자산")
    """
    if not item_name:
        return ""

    # Remove patterns like "1. ", "12. ", "Ⅰ. ", "가. ", etc.
    cleaned = re.sub(r"^[0-9]+\.?\s+", "", item_name.strip())
    cleaned = re.sub(r"^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+\.?\s+", "", cleaned)
    cleaned = re.sub(r"^[가나다라마바사아자차카타파하]\.?\s+", "", cleaned)
    cleaned = re.sub(r"^[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳]\.?\s+", "", cleaned)

    # Remove additional patterns found in actual data
    cleaned = re.sub(r"^[ㆍ·]+\s*", "", cleaned)  # Bullet points
    cleaned = re.sub(r"^\s*[-–—]\s*", "", cleaned)  # Dashes
    cleaned = re.sub(r"^\s*[•]\s*", "", cleaned)  # Bullets

    return cleaned.strip()


def _has_financial_table_structure(table_data: List[Dict[str, Any]]) -> bool:
    """Check if table has financial statement structure.

    Args:
        table_data: List of table row dictionaries

    Returns:
        True if table appears to be a financial statement
    """
    if not table_data:
        return False

    # Check for financial indicators in column names
    all_columns = set()
    for row in table_data:
        all_columns.update(row.keys())

    financial_indicators = [
        "과 목",
        "계정과목",
        "항목",
        "구분",
        "당기",
        "전기",
        "기말",
        "기초",
        "금액",
        "원",
        "백만원",
        "천원",
        "자산",
        "부채",
        "자본",
        "수익",
        "비용",
        "이익",
        # 추가된 지표들
        "매출",
        "현금",
        "투자",
        "차입",
        "포괄손익",
        "기타포괄손익",
        "자본변동",
        "이익잉여금",
        "주식발행",
        "영업활동",
        "투자활동",
        "재무활동",
        "현금흐름",
        "손익계산",
        "포괄손익계산",
    ]

    # Check if any financial indicators are present in column names
    for indicator in financial_indicators:
        if any(indicator in col for col in all_columns):
            return True

    # Check for financial keywords in table content
    content_text = " ".join(
        [
            str(value)
            for row in table_data
            for value in row.values()
            if isinstance(value, str)
        ]
    ).lower()

    for indicator in financial_indicators:
        if indicator in content_text:
            return True

    # Check for numeric data patterns (amounts with commas, parentheses for negatives)
    numeric_pattern = re.compile(r"[0-9,()]+")
    numeric_count = 0
    total_cells = 0

    for row in table_data:
        for value in row.values():
            total_cells += 1
            if isinstance(value, str) and numeric_pattern.search(value):
                numeric_count += 1

    # If more than 20% of cells contain numeric patterns, likely financial data
    if total_cells > 0 and numeric_count / total_cells > 0.2:
        return True

    return False


def extract_note_references_from_table(
    table: Dict[str, Any], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract note references from a financial table.

    Args:
        table: Table data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of note reference mappings
    """
    references = []

    table_data = table.get("data", [])
    if not table_data:
        return references

    # Enhanced section detection - check both metadata and content
    metadata = table.get("metadata", {})
    is_financial_table = metadata.get("is_financial_table", False)

    # Also check if table has financial structure (columns with amounts, etc.)
    has_financial_structure = _has_financial_table_structure(table_data)

    if not (is_financial_table or has_financial_structure):
        return references

    # Determine section code from table structure
    section_code = determine_section_from_table_structure(table_data)
    if not section_code:
        return references

    # Try multiple column names for item names
    item_column_candidates = ["과 목", "0", "주 석", "계정과목", "항목"]

    for row in table_data:
        item_name = ""
        notes_ref = None

        # Try different column names for item name
        for col_name in item_column_candidates:
            if col_name in row and row[col_name]:
                item_name = str(row[col_name]).strip()
                if item_name:
                    break

        if not item_name:
            continue

        # Try different column names for notes reference
        notes_column_candidates = ["주석", "주 석", "note", "notes"]
        for col_name in notes_column_candidates:
            if col_name in row:
                notes_ref = row[col_name]
                if notes_ref and isinstance(notes_ref, dict):
                    break

        if not isinstance(notes_ref, dict):
            continue

        if notes_ref.get("type") == "notes_reference":
            note_numbers = notes_ref.get("note_numbers", [])

            if not note_numbers:
                continue

            # Clean the item name by removing numbering prefixes
            cleaned_item_name = clean_category_name(item_name)

            if not cleaned_item_name:
                continue

            for note_number in note_numbers:
                reference = {
                    "item_name": cleaned_item_name,
                    "original_item_name": item_name,  # Keep original for debugging
                    "section_code": section_code,
                    "note_number": note_number,
                    "year": year,
                    "company_name": company_name,
                    "original_value": notes_ref.get("original_value", ""),
                    "reference_count": notes_ref.get("reference_count", 1),
                    "source_column": col_name,  # Track which column was used
                }
                references.append(reference)

    return references


def determine_section_from_table_structure(table_data: List[Dict[str, Any]]) -> str:
    """Determine financial statement section from table structure.

    Args:
        table_data: List of table row dictionaries

    Returns:
        Section code (BS, PL, CI, CF, EQ) or empty string if not determinable
    """
    if not table_data:
        return ""

    # Look for section indicators in table content
    content_text = " ".join(
        [
            str(value)
            for row in table_data
            for value in row.values()
            if isinstance(value, str)
        ]
    ).lower()

    # Enhanced section detection with hierarchical priority and scoring

    # Balance Sheet indicators (highest priority for asset/liability structure)
    bs_indicators = [
        "자산",
        "부채",
        "자본",
        "재무상태표",
        "balance sheet",
        "유동자산",
        "비유동자산",
        "유동부채",
        "비유동부채",
        "현금및현금성자산",
        "매출채권",
        "재고자산",
        "유형자산",
        "무형자산",
        "단기차입금",
        "매입채무",
        "장기차입금",
        "사채",
        "이익잉여금",
    ]

    # Cash Flow indicators (high priority for activity-based structure)
    cf_indicators = [
        "현금",
        "흐름",
        "영업활동",
        "투자활동",
        "재무활동",
        "cash flow",
        "현금흐름표",
        "현금의 증가",
        "현금의 감소",
        "영업에서 창출된 현금",
        "투자활동으로 인한 현금흐름",
        "재무활동으로 인한 현금흐름",
        "현금 및 현금성자산의 순증가",
    ]

    # Equity Statement indicators (specific equity terms)
    eq_indicators = [
        "자본변동",
        "equity",
        "변동표",
        "자본금",
        "주식발행",
        "이익잉여금",
        "기타자본항목",
        "자본변동표",
        "주주자본",
        "자본총계",
        "자본변동내역",
        "주식발행전환사채",
        "신종자본증권",
    ]

    # Comprehensive Income indicators (before PL to distinguish CI from PL)
    ci_indicators = [
        "포괄손익",
        "기타포괄손익",
        "comprehensive income",
        "포괄손익계산서",
        "기타포괄손익누계액",
        "당기순이익",
        "기타포괄손익",
        "총포괄손익",
        "포괄손익계산서상 당기순이익",
        "기타포괄손익 합계",
    ]

    # Income Statement indicators (fallback for P&L)
    pl_indicators = [
        "매출",
        "수익",
        "비용",
        "이익",
        "손익계산서",
        "income statement",
        "profit",
        "loss",
        "매출액",
        "매출원가",
        "판매비와관리비",
        "영업이익",
        "당기순이익",
        "법인세비용",
        "금융비용",
        "금융수익",
    ]

    # Calculate scores for each section
    section_scores = {
        "BS": sum(1 for indicator in bs_indicators if indicator in content_text),
        "CF": sum(1 for indicator in cf_indicators if indicator in content_text),
        "EQ": sum(1 for indicator in eq_indicators if indicator in content_text),
        "CI": sum(1 for indicator in ci_indicators if indicator in content_text),
        "PL": sum(1 for indicator in pl_indicators if indicator in content_text),
    }

    # Return the section with the highest score, but only if score > 0
    max_score = max(section_scores.values())
    if max_score > 0:
        # In case of tie, prefer BS > CF > EQ > CI > PL
        priority_order = ["BS", "CF", "EQ", "CI", "PL"]
        for section in priority_order:
            if section_scores[section] == max_score:
                return section

    # Additional heuristic: check for specific patterns in column names
    all_columns = set()
    for row in table_data:
        all_columns.update(row.keys())

    column_text = " ".join(all_columns).lower()

    # Check for specific column patterns that indicate sections
    if any(
        pattern in column_text for pattern in ["당기", "전기", "기말", "기초"]
    ) and any(pattern in column_text for pattern in ["자산", "부채", "자본"]):
        return "BS"

    if any(pattern in column_text for pattern in ["영업활동", "투자활동", "재무활동"]):
        return "CF"

    if any(pattern in column_text for pattern in ["자본변동", "변동표"]):
        return "EQ"

    if any(pattern in column_text for pattern in ["포괄손익", "기타포괄손익"]):
        return "CI"

    if any(pattern in column_text for pattern in ["매출", "수익", "비용"]):
        return "PL"

    return ""


def create_fs_note_links(
    session, processed_files: List[Path], config: ETLConfig
) -> Dict[str, Any]:
    """Create LINKS_TO_NOTE relationships between FS_CATEGORY and NOTE nodes.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration

    Returns:
        Dictionary with operation results
    """
    company_name = config.company_name
    links_created = 0
    links_attempted = 0
    missing_categories = set()
    missing_notes = set()

    print(f"Creating FS-to-Notes links for {len(processed_files)} files...")

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        print(f"  Processing {file_path.name} (year: {year})...")

        # Extract note references from all sections with enhanced processing
        all_references = []
        sections = data.get("sections", [])

        # Track section statistics
        section_stats = {}
        total_tables_processed = 0
        total_financial_tables = 0

        for section in sections:
            section_title = section.get("title", "")
            tables = section.get("tables", [])

            section_refs = []
            financial_tables_in_section = 0

            for table in tables:
                total_tables_processed += 1

                # Check if table has financial structure
                table_data = table.get("data", [])
                if _has_financial_table_structure(table_data):
                    total_financial_tables += 1
                    financial_tables_in_section += 1

                references = extract_note_references_from_table(
                    table, year, company_name
                )
                section_refs.extend(references)

            all_references.extend(section_refs)

            # Store section statistics
            if section_refs or financial_tables_in_section > 0:
                section_stats[section_title] = {
                    "total_tables": len(tables),
                    "financial_tables": financial_tables_in_section,
                    "note_references": len(section_refs),
                    "sections_detected": len(
                        set(ref.get("section_code", "") for ref in section_refs)
                    ),
                }

        print(f"    Found {len(all_references)} note references")

        # Print section statistics
        if section_stats:
            print(f"    📊 Section Analysis:")
            for section_title, stats in section_stats.items():
                print(f"      {section_title}:")
                print(f"        - Total tables: {stats['total_tables']}")
                print(f"        - Financial tables: {stats['financial_tables']}")
                print(f"        - Note references: {stats['note_references']}")
                if stats["sections_detected"] > 0:
                    print(f"        - Sections detected: {stats['sections_detected']}")

        print(f"    📊 Overall Processing:")
        print(f"      - Total tables processed: {total_tables_processed}")
        print(f"      - Financial tables identified: {total_financial_tables}")
        print(
            f"      - Financial table ratio: {total_financial_tables/total_tables_processed*100:.1f}%"
        )

        # Create links for each reference
        for ref in all_references:
            links_attempted += 1

            # Build IDs - use category_path format like in load_fs_categories
            category_path = f"{ref['section_code']}>{ref['item_name']}"
            category_id = build_category_id(
                company_name, ref["section_code"], category_path
            )
            note_id = build_note_id(company_name, ref["year"], ref["note_number"])

            # Check if both nodes exist and create link
            result = session.run(
                f"""
                OPTIONAL MATCH (cat:{NODE_TYPES['FS_CATEGORY']} {{ {PROPS['id']}: $category_id }})
                OPTIONAL MATCH (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: $note_id }})
                RETURN cat.{PROPS['name']} AS category_name, 
                       n.{PROPS['note_number']} AS note_number,
                       cat IS NOT NULL AS cat_exists,
                       n IS NOT NULL AS note_exists
                """,
                {"category_id": category_id, "note_id": note_id},
            )

            record = result.single()
            if record:
                cat_exists = record["cat_exists"]
                note_exists = record["note_exists"]

                if cat_exists and note_exists:
                    # Both nodes exist, create the link
                    link_result = session.run(
                        f"""
                        MATCH (cat:{NODE_TYPES['FS_CATEGORY']} {{ {PROPS['id']}: $category_id }})
                        MATCH (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: $note_id }})
                        MERGE (cat)-[r:{RELATIONSHIP_TYPES['LINKS_TO_NOTE']}]->(n)
                        ON CREATE SET r.original_value = $original_value,
                                     r.reference_count = $reference_count
                        RETURN 'success' AS status
                        """,
                        {
                            "category_id": category_id,
                            "note_id": note_id,
                            "original_value": ref["original_value"],
                            "reference_count": ref["reference_count"],
                        },
                    )

                    link_record = link_result.single()
                    if link_record:
                        links_created += 1
                        if links_created <= 5:  # Show first few links
                            print(
                                f"    ✓ Linked: {record['category_name']} -> Note {record['note_number']}"
                            )
                elif not cat_exists:
                    missing_categories.add(f"{ref['section_code']}:{ref['item_name']}")
                    if len(missing_categories) <= 3:
                        print(
                            f"    ❌ Missing category: {ref['item_name']} (ID: {category_id[:20]}...)"
                        )
                elif not note_exists:
                    missing_notes.add(f"{ref['year']}:{ref['note_number']}")
                    if len(missing_notes) <= 3:
                        print(
                            f"    ❌ Missing note: {ref['year']} Note {ref['note_number']} (ID: {note_id[:20]}...)"
                        )

    # Summary
    success_rate = (links_created / links_attempted * 100) if links_attempted > 0 else 0

    result = {
        "status": "success",
        "links_created": links_created,
        "links_attempted": links_attempted,
        "success_rate": round(success_rate, 1),
        "missing_categories": len(missing_categories),
        "missing_notes": len(missing_notes),
    }

    print(f"\n📊 Enhanced Links Creation Summary:")
    print(f"  Links created: {links_created}/{links_attempted} ({success_rate:.1f}%)")

    # Section-wise breakdown
    section_breakdown = {}
    for ref in all_references:
        section = ref.get("section_code", "Unknown")
        if section not in section_breakdown:
            section_breakdown[section] = 0
        section_breakdown[section] += 1

    if section_breakdown:
        print(f"  Links by section:")
        for section, count in sorted(section_breakdown.items()):
            print(f"    {section}: {count} links")

    if missing_categories:
        print(f"  Missing categories: {len(missing_categories)}")
        # Show a few examples
        for example in list(missing_categories)[:3]:
            print(f"    - {example}")
        if len(missing_categories) > 3:
            print(f"    ... and {len(missing_categories) - 3} more")

    if missing_notes:
        print(f"  Missing notes: {len(missing_notes)}")
        for example in list(missing_notes)[:3]:
            print(f"    - {example}")
        if len(missing_notes) > 3:
            print(f"    ... and {len(missing_notes) - 3} more")

    # Improvement potential
    print(f"\n🎯 Improvement Analysis:")
    total_sections_with_links = len(section_breakdown)
    print(f"  Sections with links: {total_sections_with_links}/5")

    if total_sections_with_links < 5:
        missing_sections = set(["BS", "PL", "CI", "CF", "EQ"]) - set(
            section_breakdown.keys()
        )
        print(f"  Missing sections: {', '.join(sorted(missing_sections))}")
        print(f"  Potential for improvement: {5 - total_sections_with_links} sections")

    return result


def validate_fs_note_links(session, config: ETLConfig) -> Dict[str, Any]:
    """Validate created LINKS_TO_NOTE relationships.

    Args:
        session: Neo4j session
        config: ETL configuration

    Returns:
        Dictionary with validation results
    """
    print("🔍 Validating FS-to-Notes links...")

    # Count total links
    total_links = session.run(
        f"""
        MATCH (cat:{NODE_TYPES['FS_CATEGORY']})-[r:{RELATIONSHIP_TYPES['LINKS_TO_NOTE']}]->(n:{NODE_TYPES['NOTE']})
        RETURN count(r) AS total_links
        """
    ).single()["total_links"]

    # Links by section
    links_by_section = session.run(
        f"""
        MATCH (fs:{NODE_TYPES['FS_SECTION']})-[:{RELATIONSHIP_TYPES['HAS_CATEGORY']}]->(cat:{NODE_TYPES['FS_CATEGORY']})
        MATCH (cat)-[r:{RELATIONSHIP_TYPES['LINKS_TO_NOTE']}]->(n:{NODE_TYPES['NOTE']})
        RETURN fs.{PROPS['section_code']} AS section_code, count(r) AS link_count
        ORDER BY link_count DESC
        """
    ).data()

    # Most referenced notes
    top_notes = session.run(
        f"""
        MATCH (cat:{NODE_TYPES['FS_CATEGORY']})-[r:{RELATIONSHIP_TYPES['LINKS_TO_NOTE']}]->(n:{NODE_TYPES['NOTE']})
        RETURN n.{PROPS['note_number']} AS note_number, 
               n.{PROPS['name']} AS note_title,
               count(r) AS reference_count
        ORDER BY reference_count DESC
        LIMIT 5
        """
    ).data()

    # Categories with most note references
    top_categories = session.run(
        f"""
        MATCH (cat:{NODE_TYPES['FS_CATEGORY']})-[r:{RELATIONSHIP_TYPES['LINKS_TO_NOTE']}]->(n:{NODE_TYPES['NOTE']})
        RETURN cat.{PROPS['name']} AS category_name,
               count(r) AS reference_count
        ORDER BY reference_count DESC
        LIMIT 5
        """
    ).data()

    print(f"  Total LINKS_TO_NOTE relationships: {total_links}")

    if links_by_section:
        print(f"  Links by section:")
        for record in links_by_section:
            print(f"    {record['section_code']}: {record['link_count']}")

    if top_notes:
        print(f"  Most referenced notes:")
        for record in top_notes:
            title = (
                record["note_title"][:50] + "..."
                if len(record["note_title"]) > 50
                else record["note_title"]
            )
            print(
                f"    Note {record['note_number']}: {record['reference_count']} refs ({title})"
            )

    if top_categories:
        print(f"  Categories with most references:")
        for record in top_categories:
            name = (
                record["category_name"][:40] + "..."
                if len(record["category_name"]) > 40
                else record["category_name"]
            )
            print(f"    {name}: {record['reference_count']} refs")

    return {
        "total_links": total_links,
        "links_by_section": {
            r["section_code"]: r["link_count"] for r in links_by_section
        },
        "top_notes": top_notes,
        "top_categories": top_categories,
    }


def load_fs_note_links(session, processed_files: List[Path], config: ETLConfig) -> None:
    """Main function to create and validate FS-to-Notes links.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    # Create the links
    creation_result = create_fs_note_links(session, processed_files, config)

    # Validate the results
    validation_result = validate_fs_note_links(session, config)

    print(f"\n✅ FS-to-Notes linking completed!")
    print(f"   Links created: {creation_result['links_created']}")
    print(f"   Success rate: {creation_result['success_rate']}%")


if __name__ == "__main__":
    # Test FS-to-Notes linking
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        print(f"Testing FS-to-Notes linking with {len(available_files)} files")

        # Test note reference extraction from one file
        test_file = available_files[-1]
        print(f"Testing with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]
        company_name = company_info["name"]

        print(f"Company: {company_name}, Year: {year}")

        # Extract note references from all tables
        all_references = []
        sections = data.get("sections", [])

        for section in sections:
            tables = section.get("tables", [])
            for table in tables:
                references = extract_note_references_from_table(
                    table, year, company_name
                )
                all_references.extend(references)

        print(f"\nExtracted {len(all_references)} note references:")

        # Group by section
        by_section = {}
        for ref in all_references:
            section = ref["section_code"]
            if section not in by_section:
                by_section[section] = []
            by_section[section].append(ref)

        for section_code, refs in by_section.items():
            print(f"  {section_code}: {len(refs)} references")
            for ref in refs[:3]:  # Show first 3
                print(f"    {ref['item_name']} -> Note {ref['note_number']}")
            if len(refs) > 3:
                print(f"    ... and {len(refs) - 3} more")

    else:
        print("No processed files found for testing")
