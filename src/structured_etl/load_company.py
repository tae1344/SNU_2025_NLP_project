from __future__ import annotations

"""Load COMPANY and SUBSIDIARY nodes and relationships.

Extracts company information from processed JSON metadata and creates:
- COMPANY node (삼성전자)  
- SUBSIDIARY nodes (from notes section if available)
- HAS_SUBSIDIARY relationships
"""

import json
from pathlib import Path
from typing import Any, Dict, List

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_subsidiary_id
from .etl_config import ETLConfig, extract_company_info_from_data


def extract_subsidiary_info(
    processed_data: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    """Extract comprehensive subsidiary, affiliate, and joint venture information.

    Args:
        processed_data: Parsed JSON data from audit report

    Returns:
        Dictionary with categorized company information:
        {
            'subsidiaries': [{'name': str, 'ownership': float, 'type': str, 'source': str}],
            'affiliates': [{'name': str, 'ownership': float, 'type': str, 'source': str}],
            'joint_ventures': [{'name': str, 'ownership': float, 'type': str, 'source': str}]
        }
    """
    result = {"subsidiaries": [], "affiliates": [], "joint_ventures": []}

    sections = processed_data.get("sections", [])

    for section in sections:
        # 1. Extract from financial statement line items
        if "재무제표" in section.get("title", ""):
            for table in section.get("tables", []):
                table_data = table.get("data", [])
                for row in table_data:
                    item_name = ""
                    # Find the item name column
                    for key, value in row.items():
                        if "과 목" in key and value:
                            item_name = str(value)
                            break

                    if (
                        "종속기업" in item_name
                        or "관계기업" in item_name
                        or "공동기업" in item_name
                    ):
                        # This indicates investment in subsidiaries/affiliates
                        company_type = (
                            "subsidiary"
                            if "종속기업" in item_name
                            else (
                                "affiliate"
                                if "관계기업" in item_name
                                else "joint_venture"
                            )
                        )

                        # Extract amount information if available
                        amounts = {}
                        for key, value in row.items():
                            if "기" in key and value and value != item_name:
                                try:
                                    amounts[key] = float(str(value).replace(",", ""))
                                except:
                                    pass

                        # Handle plural forms correctly
                        category_key = (
                            "subsidiaries"
                            if company_type == "subsidiary"
                            else f"{company_type}s"
                        )
                        result[category_key].append(
                            {
                                "name": item_name,
                                "ownership": None,
                                "type": company_type,
                                "source": "financial_statement",
                                "amounts": amounts,
                            }
                        )

        # 2. Extract from notes tables (detailed company information)
        elif "주석" in section.get("title", ""):
            for table in section.get("tables", []):
                table_data = table.get("data", [])

                # Look for company name tables
                for row in table_data:
                    company_name = None
                    ownership_pct = None
                    company_type = None

                    # Check for company name columns
                    for key, value in row.items():
                        if any(
                            term in key.lower()
                            for term in ["기업명", "회사명", "기업 명"]
                        ):
                            company_name = str(value) if value else None
                        elif any(term in key.lower() for term in ["지분율", "지분"]):
                            try:
                                ownership_pct = (
                                    float(str(value).replace("%", "").replace(",", ""))
                                    if value
                                    else None
                                )
                            except:
                                ownership_pct = None
                        elif any(term in key.lower() for term in ["관계", "성격"]):
                            relation_type = str(value).lower() if value else ""
                            if "종속" in relation_type:
                                company_type = "subsidiary"
                            elif "관계" in relation_type:
                                company_type = "affiliate"
                            elif "공동" in relation_type:
                                company_type = "joint_venture"

                    # Add known Samsung companies if found in data
                    if company_name and any(
                        samsung_name in company_name
                        for samsung_name in [
                            "삼성",
                            "Samsung",
                            "SEC",
                            "SDI",
                            "디스플레이",
                            "전기",
                            "화재",
                            "물산",
                            "중공업",
                            "카드",
                            "생명",
                            "증권",
                            "SDS",
                            "C&T",
                        ]
                    ):
                        # Determine type based on ownership or name patterns
                        if company_type is None:
                            if ownership_pct and ownership_pct > 50:
                                company_type = "subsidiary"
                            elif ownership_pct and ownership_pct < 50:
                                company_type = "affiliate"
                            else:
                                # Default classification based on common Samsung entities
                                if any(
                                    name in company_name
                                    for name in ["디스플레이", "Display"]
                                ):
                                    company_type = "subsidiary"
                                elif any(
                                    name in company_name
                                    for name in ["SDI", "전기", "카드"]
                                ):
                                    company_type = "affiliate"
                                else:
                                    company_type = "affiliate"  # Default

                        # Handle plural forms correctly
                        category_key = (
                            "subsidiaries"
                            if company_type == "subsidiary"
                            else f"{company_type}s"
                        )
                        result[category_key].append(
                            {
                                "name": company_name,
                                "ownership": ownership_pct,
                                "type": company_type,
                                "source": "notes_table",
                                "row_data": row,
                            }
                        )

        # 3. Extract from notes content (fallback)
        if "주석" in section.get("title", ""):
            content = section.get("content", "")
            detailed_notes = section.get("detailed_notes", [])

            # Check detailed notes for company mentions
            for note in detailed_notes:
                note_content = note.get("content", "")
                note_title = note.get("title", "")

                # Look for specific company mentions in context
                samsung_companies = [
                    "삼성디스플레이",
                    "Samsung Display",
                    "삼성SDI",
                    "Samsung SDI",
                    "삼성전기",
                    "Samsung Electro-Mechanics",
                    "삼성카드",
                    "Samsung Card",
                    "삼성물산",
                    "Samsung C&T",
                    "삼성중공업",
                    "Samsung Heavy Industries",
                    "삼성화재",
                    "Samsung Fire",
                    "삼성생명",
                    "Samsung Life",
                    "Samsung Electronics America",
                    "Samsung Electronics Europe",
                    "Samsung Semiconductor",
                    "Samsung Austin Semiconductor",
                ]

                for company in samsung_companies:
                    if company in note_content or company in note_title:
                        # Try to determine relationship type from context
                        context = note_content.lower()
                        if "종속기업" in context or "subsidiary" in context:
                            company_type = "subsidiary"
                        elif "관계기업" in context or "affiliate" in context:
                            company_type = "affiliate"
                        elif "공동기업" in context or "joint venture" in context:
                            company_type = "joint_venture"
                        else:
                            # Default classification
                            if "디스플레이" in company or "Display" in company:
                                company_type = "subsidiary"
                            else:
                                company_type = "affiliate"

                        # Check if already added
                        category_key = (
                            "subsidiaries"
                            if company_type == "subsidiary"
                            else f"{company_type}s"
                        )
                        existing = [
                            c for c in result[category_key] if c["name"] == company
                        ]
                        if not existing:
                            result[category_key].append(
                                {
                                    "name": company,
                                    "ownership": None,
                                    "type": company_type,
                                    "source": "notes_content",
                                    "note_number": note.get("note_number"),
                                    "note_title": note_title,
                                }
                            )

    # Remove duplicates and clean up
    for category in result:
        seen_names = set()
        unique_companies = []
        for company in result[category]:
            if company["name"] not in seen_names:
                seen_names.add(company["name"])
                unique_companies.append(company)
        result[category] = unique_companies

    return result


def load_company_nodes(session, processed_files: List[Path], config: ETLConfig) -> None:
    """Load COMPANY and SUBSIDIARY nodes with comprehensive relationship information.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    all_companies = {"subsidiaries": [], "affiliates": [], "joint_ventures": []}
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

        # Extract comprehensive subsidiary/affiliate information
        company_data = extract_subsidiary_info(data)

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

    # Create SUBSIDIARY nodes and relationships (for subsidiaries and affiliates)
    total_companies = 0

    for category, companies in all_companies.items():
        if not companies:
            continue

        print(f"Processing {len(companies)} {category}...")

        for company_info in companies:
            subsidiary_name = company_info["name"]
            subsidiary_id = build_subsidiary_id(company_name, subsidiary_name)

            # Determine node properties based on company type and data
            node_properties = {
                "id": subsidiary_id,
                "name": subsidiary_name,
                "company_type": company_info["type"],
                "data_source": company_info["source"],
            }

            # Add ownership percentage if available
            if company_info.get("ownership") is not None:
                node_properties["ownership_percentage"] = company_info["ownership"]

            # Add financial amounts if available
            if "amounts" in company_info and company_info["amounts"]:
                node_properties["investment_amounts"] = json.dumps(
                    company_info["amounts"]
                )

            # Add note reference if available
            if "note_number" in company_info:
                node_properties["source_note"] = company_info["note_number"]

            # Create SUBSIDIARY node (we use SUBSIDIARY for all related companies)
            session.run(
                f"""
                MERGE (s:{NODE_TYPES['SUBSIDIARY']} {{ {PROPS['id']}: $id }})
                ON CREATE SET 
                    s.{PROPS['name']} = $name,
                    s.company_type = $company_type,
                    s.data_source = $data_source,
                    s.ownership_percentage = $ownership_percentage,
                    s.investment_amounts = $investment_amounts,
                    s.source_note = $source_note
                ON MATCH SET 
                    s.{PROPS['name']} = coalesce(s.{PROPS['name']}, $name),
                    s.company_type = coalesce(s.company_type, $company_type),
                    s.data_source = coalesce(s.data_source, $data_source),
                    s.ownership_percentage = coalesce(s.ownership_percentage, $ownership_percentage),
                    s.investment_amounts = coalesce(s.investment_amounts, $investment_amounts),
                    s.source_note = coalesce(s.source_note, $source_note)
                """,
                {
                    "id": subsidiary_id,
                    "name": subsidiary_name,
                    "company_type": company_info["type"],
                    "data_source": company_info["source"],
                    "ownership_percentage": company_info.get("ownership"),
                    "investment_amounts": (
                        json.dumps(company_info.get("amounts", {}))
                        if company_info.get("amounts")
                        else None
                    ),
                    "source_note": company_info.get("note_number"),
                },
            )

            # Create appropriate relationship based on company type
            relationship_type = RELATIONSHIP_TYPES["HAS_SUBSIDIARY"]  # Default
            relationship_properties = {
                "relationship_type": company_info["type"],
                "data_source": company_info["source"],
            }

            if company_info.get("ownership") is not None:
                relationship_properties["ownership_percentage"] = company_info[
                    "ownership"
                ]

            session.run(
                f"""
                MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
                MATCH (s:{NODE_TYPES['SUBSIDIARY']} {{ {PROPS['id']}: $subsidiary_id }})
                MERGE (c)-[r:{relationship_type}]->(s)
                ON CREATE SET 
                    r.relationship_type = $relationship_type,
                    r.data_source = $data_source,
                    r.ownership_percentage = $ownership_percentage
                ON MATCH SET 
                    r.relationship_type = coalesce(r.relationship_type, $relationship_type),
                    r.data_source = coalesce(r.data_source, $data_source),
                    r.ownership_percentage = coalesce(r.ownership_percentage, $ownership_percentage)
                """,
                {
                    "company_id": company_id,
                    "subsidiary_id": subsidiary_id,
                    "relationship_type": company_info["type"],
                    "data_source": company_info["source"],
                    "ownership_percentage": company_info.get("ownership"),
                },
            )

            total_companies += 1

    print(f"✅ Loaded {total_companies} related companies:")
    for category, companies in all_companies.items():
        if companies:
            print(f"   - {len(companies)} {category}")
            for company in companies[:3]:  # Show first 3 examples
                ownership_str = (
                    f" ({company['ownership']}%)" if company.get("ownership") else ""
                )
                print(f"     • {company['name']}{ownership_str}")
            if len(companies) > 3:
                print(f"     ... and {len(companies) - 3} more")


if __name__ == "__main__":
    # Test extraction with available files
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2014, 2022, 2023, 2024]  # Include 2014 for comprehensive testing
    available_files = config.get_processed_files(recent_years)

    if available_files:
        # Test with the most recent file
        test_file = available_files[-1]
        print(f"🧪 Testing enhanced company extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        company_data = extract_subsidiary_info(data)

        print(f"\n📊 Results:")
        print(f"Company: {company_info['name']}")
        print(f"Year: {company_info['year']}")

        total_companies = sum(len(companies) for companies in company_data.values())
        print(f"Total related companies found: {total_companies}")

        for category, companies in company_data.items():
            if companies:
                print(f"\n{category.title()} ({len(companies)}):")
                for i, company in enumerate(companies[:5]):  # Show first 5
                    ownership_str = (
                        f" - {company['ownership']}%"
                        if company.get("ownership")
                        else ""
                    )
                    source_str = f" [{company['source']}]"
                    print(f"  {i+1}. {company['name']}{ownership_str}{source_str}")

                    # Show additional details for first company
                    if i == 0 and company.get("amounts"):
                        print(f"     Investment amounts: {company['amounts']}")
                    if i == 0 and company.get("note_number"):
                        print(f"     Source note: #{company['note_number']}")

                if len(companies) > 5:
                    print(f"  ... and {len(companies) - 5} more")
    else:
        print("No processed files found for testing")
