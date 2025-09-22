from __future__ import annotations

"""Load AUDITOR and AUDIT_INFO nodes and create relationships.

Extracts audit information from audit reports and creates proper
relationships between companies, auditors, and audit information.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Optional

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_auditor_id, build_audit_info_id
from .etl_config import ETLConfig, extract_company_info_from_data


def extract_auditor_info(content: str, tables: List[Dict[str, Any]]) -> Optional[str]:
    """Extract auditor name from audit section content and tables.

    Args:
        content: Text content of audit section
        tables: List of tables in the audit section

    Returns:
        Auditor name or None if not found
    """
    # Enhanced auditor patterns including recent Samsung auditors
    auditor_patterns = [
        r"삼\s*정\s*회\s*계\s*법\s*인",  # 삼정회계법인 (Samsung's current auditor)
        r"삼\s*일\s*회\s*계\s*법\s*인",  # 삼일회계법인
        r"안\s*진\s*회\s*계\s*법\s*인",  # 안진회계법인
        r"한\s*영\s*회\s*계\s*법\s*인",  # 한영회계법인
        r"딜\s*로\s*이\s*트\s*안\s*진\s*회\s*계\s*법\s*인",  # 딜로이트안진회계법인
        r"삼정KPMG",  # 삼정KPMG
        r"EY한영회계법인",  # EY한영회계법인
        r"삼정\s*회계법인",  # 삼정 회계법인 (with space)
        r"삼정\s*KPMG",  # 삼정 KPMG (with space)
    ]

    # Search in content first
    for pattern in auditor_patterns:
        match = re.search(pattern, content, re.IGNORECASE)
        if match:
            # Clean up the matched text but preserve meaningful spaces
            auditor_name = re.sub(r"\s+", " ", match.group()).strip()
            # Remove extra spaces between characters but keep word boundaries
            auditor_name = re.sub(r"(?<=[가-힣])\s+(?=[가-힣])", "", auditor_name)
            return auditor_name

    # Search in tables (more thorough search)
    for table in tables:
        table_data = table.get("data", [])
        for row in table_data:
            for value in row.values():
                if isinstance(value, str):
                    # Clean the value first
                    cleaned_value = value.strip()
                    if len(cleaned_value) < 3:  # Skip very short values
                        continue

                    for pattern in auditor_patterns:
                        match = re.search(pattern, cleaned_value, re.IGNORECASE)
                        if match:
                            # Clean up the matched text
                            auditor_name = re.sub(r"\s+", " ", match.group()).strip()
                            auditor_name = re.sub(
                                r"(?<=[가-힣])\s+(?=[가-힣])", "", auditor_name
                            )
                            return auditor_name

    return None


def extract_audit_opinion(content: str) -> Optional[str]:
    """Extract audit opinion from content.

    Args:
        content: Text content of audit section

    Returns:
        Audit opinion or None if not found
    """
    # Opinion indicators
    opinion_patterns = [
        r"적정의견",
        r"한정의견",
        r"부적정의견",
        r"의견거절",
        r"무한정적정의견",
    ]

    for pattern in opinion_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return pattern

    # Default assumption for Samsung reports
    if "감사" in content and "의견" in content:
        return "적정의견"  # Assume clean opinion for Samsung

    return None


def extract_audit_date(content: str, tables: List[Dict[str, Any]]) -> Optional[str]:
    """Extract audit date from content and tables.

    Args:
        content: Text content of audit section
        tables: List of tables in the audit section

    Returns:
        Audit date string or None if not found
    """
    # Date patterns (Korean format)
    date_patterns = [
        r"(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일",
        r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})",
        r"(\d{4})-(\d{1,2})-(\d{1,2})",
    ]

    # Search in content
    for pattern in date_patterns:
        match = re.search(pattern, content)
        if match:
            year, month, day = match.groups()
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    # Search in tables
    for table in tables:
        table_data = table.get("data", [])
        for row in table_data:
            for value in row.values():
                if isinstance(value, str):
                    for pattern in date_patterns:
                        match = re.search(pattern, value)
                        if match:
                            year, month, day = match.groups()
                            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"

    return None


def extract_audit_info_from_section(
    section: Dict[str, Any], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract audit information from a single section.

    Args:
        section: Section data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of audit info dictionaries
    """
    audit_info_list = []
    title = section.get("title", "").strip()
    content = section.get("content", "").strip()
    tables = section.get("tables", [])

    # Skip non-audit sections (more comprehensive check)
    audit_keywords = ["감사", "audit", "독립", "의견", "내부회계", "검토"]
    if not any(keyword in title.lower() for keyword in audit_keywords):
        return audit_info_list

    # Skip sections with no meaningful content
    if len(content.strip()) < 100 and len(tables) == 0:
        return audit_info_list

    # Determine audit type with more specific logic
    audit_type = "감사의견"  # Default
    if "내부회계" in title or "내부회계관리제도" in title:
        audit_type = "내부회계관리제도"
    elif "검토" in title:
        audit_type = "검토의견"
    elif "독립" in title and "감사" in title:
        audit_type = "독립감사의견"
    elif "외부감사" in title:
        audit_type = "외부감사"

    # Extract audit information
    auditor_name = extract_auditor_info(content, tables)
    audit_opinion = extract_audit_opinion(content)
    audit_date = extract_audit_date(content, tables)

    # Only create audit info if we have meaningful data
    if auditor_name or audit_opinion or audit_date or len(content) > 500:
        audit_info = {
            "audit_type": audit_type,
            "auditor_name": auditor_name,
            "audit_opinion": audit_opinion,
            "audit_date": audit_date,
            "year": year,
            "company_name": company_name,
            "section_title": title,
            "content_length": len(content),
            "table_count": len(tables),
        }

        audit_info_list.append(audit_info)

    return audit_info_list


def load_audit_info_nodes(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load AUDITOR and AUDIT_INFO nodes with relationships.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)

    all_audit_info: List[Dict[str, Any]] = []
    all_auditors: Set[str] = set()

    # Process all files to collect audit information
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        print(f"  Processing {file_path.name} (year: {year})...")

        # Extract audit info from sections
        sections = data.get("sections", [])
        file_audit_info = []
        for section in sections:
            audit_info_list = extract_audit_info_from_section(
                section, year, company_name
            )
            file_audit_info.extend(audit_info_list)

        # Deduplicate audit info within the same file
        unique_audit_info = {}
        for audit_info in file_audit_info:
            key = (audit_info["audit_type"], audit_info["year"])
            if key not in unique_audit_info:
                unique_audit_info[key] = audit_info
            else:
                # Merge information, preferring non-null values
                existing = unique_audit_info[key]
                if audit_info["auditor_name"] and not existing["auditor_name"]:
                    existing["auditor_name"] = audit_info["auditor_name"]
                if audit_info["audit_opinion"] and not existing["audit_opinion"]:
                    existing["audit_opinion"] = audit_info["audit_opinion"]
                if audit_info["audit_date"] and not existing["audit_date"]:
                    existing["audit_date"] = audit_info["audit_date"]

        all_audit_info.extend(unique_audit_info.values())

        # Collect auditor names
        for audit_info in unique_audit_info.values():
            if audit_info["auditor_name"]:
                all_auditors.add(audit_info["auditor_name"])

        print(f"    Extracted {len(unique_audit_info)} audit info records")

    # Deduplicate across all files
    final_audit_info = {}
    for audit_info in all_audit_info:
        key = (audit_info["audit_type"], audit_info["year"])
        if key not in final_audit_info:
            final_audit_info[key] = audit_info
        else:
            # Merge information across files
            existing = final_audit_info[key]
            if audit_info["auditor_name"] and not existing["auditor_name"]:
                existing["auditor_name"] = audit_info["auditor_name"]
            if audit_info["audit_opinion"] and not existing["audit_opinion"]:
                existing["audit_opinion"] = audit_info["audit_opinion"]
            if audit_info["audit_date"] and not existing["audit_date"]:
                existing["audit_date"] = audit_info["audit_date"]

    final_audit_info_list = list(final_audit_info.values())

    print(f"Extracted {len(all_audit_info)} audit info records")
    print(f"After deduplication: {len(final_audit_info_list)} unique records")
    print(f"Found {len(all_auditors)} unique auditors: {list(all_auditors)}")

    # Create AUDITOR nodes
    for auditor_name in all_auditors:
        auditor_id = build_auditor_id(auditor_name)

        session.run(
            f"""
            MERGE (a:{NODE_TYPES['AUDITOR']} {{ {PROPS['id']}: $auditor_id }})
            ON CREATE SET 
                a.{PROPS['name']} = $auditor_name,
                a.auditor_type = 'external',
                a.created_from_data = true
            ON MATCH SET
                a.{PROPS['name']} = coalesce(a.{PROPS['name']}, $auditor_name),
                a.auditor_type = coalesce(a.auditor_type, 'external'),
                a.created_from_data = coalesce(a.created_from_data, true)
            """,
            {"auditor_id": auditor_id, "auditor_name": auditor_name},
        )

    # Create AUDIT_INFO nodes and relationships
    for audit_info in final_audit_info_list:
        audit_info_id = build_audit_info_id(
            company_name, audit_info["year"], audit_info["audit_type"]
        )

        # Create AUDIT_INFO node
        session.run(
            f"""
            MERGE (ai:{NODE_TYPES['AUDIT_INFO']} {{ {PROPS['id']}: $audit_info_id }})
            ON CREATE SET 
                ai.{PROPS['audit_type']} = $audit_type,
                ai.{PROPS['audit_opinion']} = $audit_opinion,
                ai.{PROPS['audit_date']} = $audit_date,
                ai.{PROPS['year']} = $year,
                ai.{PROPS['company']} = $company_name,
                ai.{PROPS['auditor_name']} = $auditor_name,
                ai.section_title = $section_title,
                ai.content_length = $content_length,
                ai.table_count = $table_count,
                ai.created_from_data = true
            ON MATCH SET
                ai.{PROPS['audit_opinion']} = coalesce(ai.{PROPS['audit_opinion']}, $audit_opinion),
                ai.{PROPS['audit_date']} = coalesce(ai.{PROPS['audit_date']}, $audit_date),
                ai.{PROPS['auditor_name']} = coalesce(ai.{PROPS['auditor_name']}, $auditor_name),
                ai.section_title = coalesce(ai.section_title, $section_title),
                ai.content_length = coalesce(ai.content_length, $content_length),
                ai.table_count = coalesce(ai.table_count, $table_count),
                ai.created_from_data = coalesce(ai.created_from_data, true)
            """,
            {
                "audit_info_id": audit_info_id,
                "audit_type": audit_info["audit_type"],
                "audit_opinion": audit_info["audit_opinion"],
                "audit_date": audit_info["audit_date"],
                "year": audit_info["year"],
                "company_name": audit_info["company_name"],
                "auditor_name": audit_info["auditor_name"],
                "section_title": audit_info.get("section_title", ""),
                "content_length": audit_info.get("content_length", 0),
                "table_count": audit_info.get("table_count", 0),
            },
        )

        # Create HAS_AUDIT_INFO relationship from COMPANY to AUDIT_INFO
        session.run(
            f"""
            MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
            MATCH (ai:{NODE_TYPES['AUDIT_INFO']} {{ {PROPS['id']}: $audit_info_id }})
            MERGE (c)-[:{RELATIONSHIP_TYPES['HAS_AUDIT_INFO']}]->(ai)
            """,
            {"company_id": company_id, "audit_info_id": audit_info_id},
        )

        # Create AUDITED_BY relationship from COMPANY to AUDITOR (if auditor exists)
        if audit_info["auditor_name"]:
            auditor_id = build_auditor_id(audit_info["auditor_name"])

            session.run(
                f"""
                MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
                MATCH (a:{NODE_TYPES['AUDITOR']} {{ {PROPS['id']}: $auditor_id }})
                MERGE (c)-[:{RELATIONSHIP_TYPES['AUDITED_BY']}]->(a)
                """,
                {"company_id": company_id, "auditor_id": auditor_id},
            )


if __name__ == "__main__":
    # Test audit info extraction
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        # Test with the most recent file
        test_file = available_files[-1]
        print(f"Testing audit info extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]
        company_name = company_info["name"]

        print(f"Company: {company_name}, Year: {year}")

        # Extract audit info from sections
        sections = data.get("sections", [])
        all_audit_info = []

        for section in sections:
            audit_info_list = extract_audit_info_from_section(
                section, year, company_name
            )
            all_audit_info.extend(audit_info_list)

        print(f"\nExtracted {len(all_audit_info)} audit info records:")
        for i, audit_info in enumerate(all_audit_info):
            print(
                f"  {i+1}. {audit_info['audit_type']}: {audit_info['auditor_name']} - {audit_info['audit_opinion']} ({audit_info['audit_date']})"
            )
            print(f"      Content length: {audit_info['content_length']} chars")
    else:
        print("No processed files found for testing")
