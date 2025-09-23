from __future__ import annotations

"""Enhanced company relationship loader with ownership-based classification.

This module provides comprehensive company relationship loading with:
- Ownership percentage-based automatic classification
- Support for all company relationship types (SUBSIDIARY, AFFILIATE, JOINT_VENTURE, SPECIAL_RELATION)
- Extraction from notes sections and financial statements
- Creation of appropriate relationship types based on ownership percentages
- Enhanced financial relationship tracking (investment, trade, debt amounts)
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import (
    build_company_id,
    build_subsidiary_id,
    build_affiliate_id,
    build_joint_venture_id,
    build_special_relation_id,
)
from .etl_config import ETLConfig, extract_company_info_from_data


def classify_company_relationship(
    ownership_percentage: Optional[float], relationship_type: str
) -> str:
    """Classify company relationship based on ownership percentage and relationship type.

    Args:
        ownership_percentage: Ownership percentage (0-100)
        relationship_type: Type of relationship from source data

    Returns:
        Classified relationship type: SUBSIDIARY, AFFILIATE, JOINT_VENTURE, or SPECIAL_RELATION
    """
    if ownership_percentage is not None:
        if ownership_percentage >= 50:
            return "SUBSIDIARY"
        elif 20 <= ownership_percentage < 50:
            return "AFFILIATE"
        elif relationship_type in ["공동기업", "joint_venture", "공동지배"]:
            return "JOINT_VENTURE"
        else:
            return "SPECIAL_RELATION"
    else:
        # Fallback to relationship_type text analysis
        if relationship_type in ["종속기업", "subsidiary"]:
            return "SUBSIDIARY"
        elif relationship_type in ["관계기업", "affiliate"]:
            return "AFFILIATE"
        elif relationship_type in ["공동기업", "joint_venture", "공동지배"]:
            return "JOINT_VENTURE"
        else:
            return "SPECIAL_RELATION"


def extract_ownership_percentage(text: str) -> Optional[float]:
    """Extract ownership percentage from text.

    Args:
        text: Text containing ownership information

    Returns:
        Ownership percentage as float, or None if not found
    """
    if not text:
        return None

    # Pattern for percentage extraction (e.g., "51.2%", "20.8%", "지분 30%")
    patterns = [
        r"(\d+(?:\.\d+)?)%",  # Basic percentage
        r"지분\s*(\d+(?:\.\d+)?)%",  # 지분 XX%
        r"(\d+(?:\.\d+)?)\s*%",  # XX % (with space)
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        if matches:
            try:
                percentage = float(matches[0])
                # Validate reasonable ownership percentage
                if 0 <= percentage <= 100:
                    return percentage
            except ValueError:
                continue

    return None


def extract_enhanced_company_relationships(
    processed_data: Dict[str, Any], year: int
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract comprehensive company relationship information with enhanced classification.

    Args:
        processed_data: Parsed JSON data from audit report
        year: Report year

    Returns:
        Dictionary with categorized company information:
        {
            'subsidiaries': [{'name': str, 'ownership': float, 'type': str, 'source': str, 'amounts': dict}],
            'affiliates': [{'name': str, 'ownership': float, 'type': str, 'source': str, 'amounts': dict}],
            'joint_ventures': [{'name': str, 'ownership': float, 'type': str, 'source': str, 'amounts': dict}],
            'special_relations': [{'name': str, 'ownership': float, 'type': str, 'source': str, 'amounts': dict}]
        }
    """
    result = {
        "subsidiaries": [],
        "affiliates": [],
        "joint_ventures": [],
        "special_relations": [],
    }

    sections = processed_data.get("sections", [])

    for section in sections:
        # 1. Extract from financial statement line items
        if "재무제표" in section.get("title", ""):
            result = _extract_from_financial_statements(section, result)

        # 2. Extract from notes sections (detailed company information)
        elif "주석" in section.get("title", ""):
            result = _extract_from_notes_sections(section, result)

        # 3. Extract from audit information
        elif "감사" in section.get("title", ""):
            result = _extract_from_audit_sections(section, result)

    # Post-process and classify all companies
    result = _classify_and_deduplicate_companies(result)

    return result


def _extract_from_financial_statements(
    section: Dict[str, Any], result: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract company relationships from financial statement tables."""
    for table in section.get("tables", []):
        table_data = table.get("data", [])
        for row in table_data:
            item_name = ""

            # Find the item name column
            for key, value in row.items():
                if ("과목" in key or "항목" in key) and value:
                    item_name = str(value)
                    break

            # Check if this row contains company relationship information
            if any(
                keyword in item_name
                for keyword in ["종속기업", "관계기업", "공동기업", "특수관계기업"]
            ):
                # Extract amounts from all columns
                amounts = {}
                ownership_info = None

                for key, value in row.items():
                    if value and value != item_name:
                        try:
                            # Try to extract numeric values
                            numeric_value = float(
                                str(value)
                                .replace(",", "")
                                .replace("(", "-")
                                .replace(")", "")
                            )
                            amounts[key] = numeric_value
                        except (ValueError, TypeError):
                            # Check for ownership percentage in text
                            if isinstance(value, str):
                                ownership = extract_ownership_percentage(value)
                                if ownership is not None:
                                    ownership_info = ownership

                # Determine relationship type from item name
                relationship_type = _determine_relationship_type_from_text(item_name)

                # Create company entry
                company_entry = {
                    "name": item_name,
                    "ownership": ownership_info,
                    "type": relationship_type,
                    "source": "financial_statement",
                    "amounts": amounts,
                    "original_text": item_name,
                }

                # Add to appropriate category based on initial classification
                category = _get_initial_category(relationship_type)
                result[category].append(company_entry)

    return result


def _extract_from_notes_sections(
    section: Dict[str, Any], result: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract detailed company information from notes sections."""
    for table in section.get("tables", []):
        table_data = table.get("data", [])

        # Look for company relationship tables
        for i, row in enumerate(table_data):
            company_name = None
            ownership_percentage = None
            relationship_type = None

            # Extract company information from row
            for key, value in row.items():
                if value and isinstance(value, str):
                    # Look for company names (usually in first column)
                    if (
                        not company_name
                        and len(value) > 2
                        and any(
                            char in value for char in ["주식회사", "㈜", "유한회사"]
                        )
                    ):
                        company_name = value.strip()

                    # Extract ownership percentage
                    if ownership_percentage is None:
                        ownership_percentage = extract_ownership_percentage(value)

                    # Determine relationship type
                    if relationship_type is None:
                        relationship_type = _determine_relationship_type_from_text(
                            value
                        )

            if company_name and company_name not in [
                existing["name"]
                for category in result.values()
                for existing in category
            ]:
                company_entry = {
                    "name": company_name,
                    "ownership": ownership_percentage,
                    "type": relationship_type or "unknown",
                    "source": "notes",
                    "amounts": {},
                    "original_text": " ".join(str(v) for v in row.values() if v),
                }

                # Add to appropriate category
                category = _get_initial_category(relationship_type or "unknown")
                result[category].append(company_entry)

    return result


def _extract_from_audit_sections(
    section: Dict[str, Any], result: Dict[str, List[Dict[str, Any]]]
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract company information from audit sections."""
    # This can be extended to extract audit-related company information
    # For now, we'll focus on financial statements and notes
    return result


def _determine_relationship_type_from_text(text: str) -> str:
    """Determine relationship type from text content."""
    text_lower = text.lower()

    if "종속기업" in text or "subsidiary" in text_lower:
        return "종속기업"
    elif "관계기업" in text or "affiliate" in text_lower:
        return "관계기업"
    elif "공동기업" in text or "joint_venture" in text_lower or "공동지배" in text:
        return "공동기업"
    elif "특수관계기업" in text or "special_relation" in text_lower:
        return "특수관계기업"
    else:
        return "unknown"


def _get_initial_category(relationship_type: str) -> str:
    """Get initial category for company based on relationship type."""
    if relationship_type in ["종속기업", "subsidiary"]:
        return "subsidiaries"
    elif relationship_type in ["관계기업", "affiliate"]:
        return "affiliates"
    elif relationship_type in ["공동기업", "joint_venture"]:
        return "joint_ventures"
    else:
        return "special_relations"


def _classify_and_deduplicate_companies(
    result: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Classify companies based on ownership percentage and deduplicate."""
    # Collect all companies
    all_companies = []
    for category in result.values():
        all_companies.extend(category)

    # Deduplicate and reclassify
    seen_names = set()
    classified_result = {
        "subsidiaries": [],
        "affiliates": [],
        "joint_ventures": [],
        "special_relations": [],
    }

    for company in all_companies:
        name = company["name"]
        if name in seen_names:
            continue
        seen_names.add(name)

        # Reclassify based on ownership percentage
        classified_type = classify_company_relationship(
            company["ownership"], company["type"]
        )

        # Update company type
        company["classified_type"] = classified_type

        # Add to appropriate category
        if classified_type == "SUBSIDIARY":
            classified_result["subsidiaries"].append(company)
        elif classified_type == "AFFILIATE":
            classified_result["affiliates"].append(company)
        elif classified_type == "JOINT_VENTURE":
            classified_result["joint_ventures"].append(company)
        else:
            classified_result["special_relations"].append(company)

    return classified_result


def load_enhanced_company_nodes(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load enhanced company relationship nodes with ownership-based classification.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    all_companies = {
        "subsidiaries": [],
        "affiliates": [],
        "joint_ventures": [],
        "special_relations": [],
    }
    company_name = config.company_name

    # Process all files to collect comprehensive company information
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract company info and verify it matches config
        company_info = extract_company_info_from_data(data)
        if company_info["name"] != company_name:
            print(
                f"Warning: Company name mismatch. Config: {company_name}, Data: {company_info['name']}"
            )

        # Extract enhanced company relationship information
        company_data = extract_enhanced_company_relationships(
            data, company_info["year"]
        )

        # Merge data from multiple files
        for category in all_companies:
            existing_names = {c["name"] for c in all_companies[category]}
            for company in company_data[category]:
                if company["name"] not in existing_names:
                    all_companies[category].append(company)

    # Create main COMPANY node
    company_id = build_company_id(company_name)

    session.run(
        f"""
        MERGE (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $id }})
        ON CREATE SET 
            c.{PROPS['name']} = $name,
            c.company_type = 'parent'
        ON MATCH SET 
            c.{PROPS['name']} = coalesce(c.{PROPS['name']}, $name),
            c.company_type = coalesce(c.company_type, 'parent')
        """,
        {"id": company_id, "name": company_name},
    )

    # Create enhanced company relationship nodes
    total_companies = 0
    relationship_mapping = {
        "subsidiaries": (
            NODE_TYPES["SUBSIDIARY"],
            RELATIONSHIP_TYPES["HAS_SUBSIDIARY"],
            build_subsidiary_id,
        ),
        "affiliates": (
            NODE_TYPES["AFFILIATE"],
            RELATIONSHIP_TYPES["HAS_AFFILIATE"],
            build_affiliate_id,
        ),
        "joint_ventures": (
            NODE_TYPES["JOINT_VENTURE"],
            RELATIONSHIP_TYPES["HAS_JOINT_VENTURE"],
            build_joint_venture_id,
        ),
        "special_relations": (
            NODE_TYPES["SPECIAL_RELATION"],
            RELATIONSHIP_TYPES["HAS_SPECIAL_RELATION"],
            build_special_relation_id,
        ),
    }

    for category, companies in all_companies.items():
        if not companies:
            continue

        node_type, relationship_type, id_builder = relationship_mapping[category]

        for company in companies:
            # Build unique ID for the company
            company_node_id = id_builder(company_name, company["name"])

            # Create company node
            session.run(
                f"""
                MERGE (company:{node_type} {{ {PROPS['id']}: $id }})
                ON CREATE SET 
                    company.{PROPS['name']} = $name,
                    company.company_type = $company_type,
                    company.ownership_percentage = $ownership_percentage,
                    company.relationship_type = $relationship_type,
                    company.source = $source,
                    company.original_text = $original_text,
                    company.amounts = $amounts
                ON MATCH SET 
                    company.{PROPS['name']} = coalesce(company.{PROPS['name']}, $name),
                    company.company_type = coalesce(company.company_type, $company_type),
                    company.ownership_percentage = coalesce(company.ownership_percentage, $ownership_percentage),
                    company.relationship_type = coalesce(company.relationship_type, $relationship_type),
                    company.source = coalesce(company.source, $source),
                    company.original_text = coalesce(company.original_text, $original_text),
                    company.amounts = coalesce(company.amounts, $amounts)
                """,
                {
                    "id": company_node_id,
                    "name": company["name"],
                    "company_type": company["classified_type"].lower(),
                    "ownership_percentage": company["ownership"],
                    "relationship_type": company["type"],
                    "source": company["source"],
                    "original_text": company["original_text"],
                    "amounts": (
                        json.dumps(company["amounts"]) if company["amounts"] else None
                    ),
                },
            )

            # Create relationship to parent company
            # Prepare relationship properties, excluding null values
            rel_props = {}
            if company["ownership"] is not None:
                rel_props["ownership_percentage"] = company["ownership"]
            if company["type"]:
                rel_props["relationship_type"] = company["type"]
            if company["source"]:
                rel_props["source"] = company["source"]

            # Create the relationship with or without properties
            if rel_props:
                props_str = ", ".join([f"{key}: ${key}" for key in rel_props.keys()])
                rel_props["parent_id"] = company_id
                rel_props["company_id"] = company_node_id

                session.run(
                    f"""
                    MATCH (parent:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $parent_id }})
                    MATCH (company:{node_type} {{ {PROPS['id']}: $company_id }})
                    MERGE (parent)-[:{relationship_type} {{{props_str}}}]->(company)
                    """,
                    rel_props,
                )
            else:
                # Create relationship without properties
                session.run(
                    f"""
                    MATCH (parent:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $parent_id }})
                    MATCH (company:{node_type} {{ {PROPS['id']}: $company_id }})
                    MERGE (parent)-[:{relationship_type}]->(company)
                    """,
                    {
                        "parent_id": company_id,
                        "company_id": company_node_id,
                    },
                )

            total_companies += 1

    print(f"✅ Created/updated {total_companies} enhanced company relationship nodes")
    print(f"   - Subsidiaries: {len(all_companies['subsidiaries'])}")
    print(f"   - Affiliates: {len(all_companies['affiliates'])}")
    print(f"   - Joint Ventures: {len(all_companies['joint_ventures'])}")
    print(f"   - Special Relations: {len(all_companies['special_relations'])}")


if __name__ == "__main__":
    # Test extraction with available files
    from .etl_config import DEFAULT_CONFIG

    # Test the enhanced company relationship extraction
    test_file = Path("data/processed/감사보고서_2024_parser_v3.json")
    if test_file.exists():
        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        result = extract_enhanced_company_relationships(data, 2024)
        print("Enhanced Company Relationships:")
        for category, companies in result.items():
            print(f"\n{category.upper()}:")
            for company in companies:
                print(
                    f"  - {company['name']} (Ownership: {company['ownership']}%, Type: {company['classified_type']})"
                )
    else:
        print("Test file not found")
