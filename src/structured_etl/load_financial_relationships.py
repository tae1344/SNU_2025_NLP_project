from __future__ import annotations

"""Load financial relationships between companies (investments, trades, debts, guarantees).

Extracts inter-company financial relationship data from processed JSON and creates:
- INVESTS_IN relationships (investment with amounts and ownership)
- TRADES_WITH relationships (sales/purchase transactions)
- OWES_TO relationships (debt/credit positions)
- GUARANTEES_FOR relationships (guarantee and collateral arrangements)
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_subsidiary_id
from .etl_config import ETLConfig, extract_company_info_from_data


def extract_financial_relationships(
    processed_data: Dict[str, Any], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract comprehensive financial relationship data between companies.

    Args:
        processed_data: Parsed JSON data from audit report
        year: Reporting year
        company_name: Parent company name

    Returns:
        List of financial relationship dictionaries
    """
    relationships = []
    sections = processed_data.get("sections", [])

    for section in sections:
        if "주석" not in section.get("title", ""):
            continue

        # Process tables for relationship data
        for table in section.get("tables", []):
            table_data = table.get("data", [])
            columns = table.get("columns", [])

            # 1. Investment relationships (INVESTS_IN)
            investment_rels = _extract_investment_relationships(
                table_data, columns, year, company_name
            )
            relationships.extend(investment_rels)

            # 2. Trade relationships (TRADES_WITH)
            trade_rels = _extract_trade_relationships(
                table_data, columns, year, company_name
            )
            relationships.extend(trade_rels)

            # 3. Debt/Credit relationships (OWES_TO)
            debt_rels = _extract_debt_relationships(
                table_data, columns, year, company_name
            )
            relationships.extend(debt_rels)

            # 4. Guarantee relationships (GUARANTEES_FOR)
            guarantee_rels = _extract_guarantee_relationships(
                table_data, columns, year, company_name
            )
            relationships.extend(guarantee_rels)

    return relationships


def _extract_investment_relationships(
    table_data: List[Dict[str, Any]], columns: List[str], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract investment relationships from table data."""
    relationships = []

    # Look for investment tables with company names and amounts
    for row in table_data:
        target_company = None
        current_amount = None
        previous_amount = None
        ownership_pct = None
        book_value = None
        market_value = None

        # Identify target company and amounts
        for key, value in row.items():
            if not value:
                continue

            key_lower = str(key).lower()
            value_str = str(value)

            # Company name identification
            if any(
                term in key_lower for term in ["기업명", "회사명", "기업 명"]
            ) and any(samsung_term in value_str for samsung_term in ["삼성", "Samsung"]):
                target_company = value_str.strip()

            # Amount identification
            elif any(
                term in key_lower for term in ["당기말", "당기"]
            ) and _is_numeric_amount(value):
                current_amount = _parse_amount(value)
            elif any(
                term in key_lower for term in ["전기말", "전기"]
            ) and _is_numeric_amount(value):
                previous_amount = _parse_amount(value)
            elif any(
                term in key_lower for term in ["지분율", "지분"]
            ) and _is_numeric_amount(value):
                ownership_pct = _parse_percentage(value)
            elif any(
                term in key_lower for term in ["장부금액", "장부가액"]
            ) and _is_numeric_amount(value):
                book_value = _parse_amount(value)
            elif any(
                term in key_lower for term in ["시장가치", "시장가액"]
            ) and _is_numeric_amount(value):
                market_value = _parse_amount(value)

        # Create relationship if we have meaningful data
        if target_company and (current_amount or previous_amount or ownership_pct):
            relationships.append(
                {
                    "relationship_type": "invests_in",
                    "source_company": company_name,
                    "target_company": target_company,
                    "year": year,
                    "amount_current": current_amount,
                    "amount_previous": previous_amount,
                    "ownership_percentage": ownership_pct,
                    "book_value": book_value,
                    "market_value": market_value,
                    "transaction_type": "investment",
                    "data_source": "investment_table",
                }
            )

    return relationships


def _extract_trade_relationships(
    table_data: List[Dict[str, Any]], columns: List[str], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract trade relationships (sales/purchases) from table data."""
    relationships = []

    for row in table_data:
        target_company = None
        sales_amount = None
        purchase_amount = None
        asset_disposal = None
        asset_acquisition = None

        # Identify company and transaction amounts
        for key, value in row.items():
            if not value:
                continue

            key_lower = str(key).lower()
            value_str = str(value)

            # Company name
            if any(term in key_lower for term in ["기업명", "회사명"]) and any(
                samsung_term in value_str for samsung_term in ["삼성", "Samsung"]
            ):
                target_company = value_str.strip()

            # Transaction amounts
            elif any(term in key_lower for term in ["매출"]) and _is_numeric_amount(
                value
            ):
                sales_amount = _parse_amount(value)
            elif any(term in key_lower for term in ["매입"]) and _is_numeric_amount(
                value
            ):
                purchase_amount = _parse_amount(value)
            elif any(
                term in key_lower for term in ["자산", "처분"]
            ) and _is_numeric_amount(value):
                asset_disposal = _parse_amount(value)
            elif any(
                term in key_lower for term in ["자산", "매입"]
            ) and _is_numeric_amount(value):
                asset_acquisition = _parse_amount(value)

        # Create relationships for sales (outbound)
        if target_company and sales_amount and sales_amount > 0:
            relationships.append(
                {
                    "relationship_type": "trades_with",
                    "source_company": company_name,
                    "target_company": target_company,
                    "year": year,
                    "amount_current": sales_amount,
                    "transaction_type": "sales",
                    "transaction_direction": "outbound",
                    "data_source": "trade_table",
                }
            )

        # Create relationships for purchases (inbound)
        if target_company and purchase_amount and purchase_amount > 0:
            relationships.append(
                {
                    "relationship_type": "trades_with",
                    "source_company": target_company,  # Reverse direction for purchases
                    "target_company": company_name,
                    "year": year,
                    "amount_current": purchase_amount,
                    "transaction_type": "sales",  # From counterparty perspective
                    "transaction_direction": "outbound",
                    "data_source": "trade_table",
                }
            )

    return relationships


def _extract_debt_relationships(
    table_data: List[Dict[str, Any]], columns: List[str], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract debt/credit relationships from table data."""
    relationships = []

    for row in table_data:
        target_company = None
        receivables = None
        payables = None

        # Identify company and debt/credit amounts
        for key, value in row.items():
            if not value:
                continue

            key_lower = str(key).lower()
            value_str = str(value)

            # Company name
            if any(term in key_lower for term in ["기업명", "회사명"]) and any(
                samsung_term in value_str for samsung_term in ["삼성", "Samsung"]
            ):
                target_company = value_str.strip()

            # Debt/Credit amounts
            elif any(term in key_lower for term in ["채권"]) and _is_numeric_amount(
                value
            ):
                receivables = _parse_amount(value)
            elif any(term in key_lower for term in ["채무"]) and _is_numeric_amount(
                value
            ):
                payables = _parse_amount(value)

        # Create receivables relationship (target company owes to source)
        if target_company and receivables and receivables > 0:
            relationships.append(
                {
                    "relationship_type": "owes_to",
                    "source_company": target_company,  # Debtor
                    "target_company": company_name,  # Creditor
                    "year": year,
                    "amount_current": receivables,
                    "transaction_type": "debt",
                    "transaction_direction": "inbound",  # Money flows to parent
                    "data_source": "debt_table",
                }
            )

        # Create payables relationship (source owes to target company)
        if target_company and payables and payables > 0:
            relationships.append(
                {
                    "relationship_type": "owes_to",
                    "source_company": company_name,  # Debtor
                    "target_company": target_company,  # Creditor
                    "year": year,
                    "amount_current": payables,
                    "transaction_type": "debt",
                    "transaction_direction": "outbound",  # Money flows from parent
                    "data_source": "debt_table",
                }
            )

    return relationships


def _extract_guarantee_relationships(
    table_data: List[Dict[str, Any]], columns: List[str], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract guarantee/collateral relationships from table data."""
    relationships = []

    # Look for guarantee-related content in table data
    for row in table_data:
        row_text = " ".join(str(v) for v in row.values() if v).lower()

        if any(term in row_text for term in ["보증", "담보"]) and any(
            samsung_term in row_text for samsung_term in ["삼성", "samsung"]
        ):

            # Extract guarantee amounts
            amounts = re.findall(r"[0-9,]+", row_text)
            large_amounts = [
                _parse_amount(amt) for amt in amounts if len(amt.replace(",", "")) >= 6
            ]  # 6+ digits

            if large_amounts:
                # Determine guarantee type
                guarantee_type = (
                    "debt_guarantee"
                    if "채무보증" in row_text
                    else (
                        "payment_guarantee"
                        if "지급보증" in row_text
                        else "collateral" if "담보" in row_text else "guarantee"
                    )
                )

                relationships.append(
                    {
                        "relationship_type": "guarantees_for",
                        "source_company": company_name,  # Guarantor
                        "target_company": "subsidiaries_general",  # General subsidiaries
                        "year": year,
                        "amount_current": max(large_amounts),  # Largest amount
                        "guarantee_type": guarantee_type,
                        "transaction_type": "guarantee",
                        "data_source": "guarantee_table",
                        "transaction_details": json.dumps(
                            {"all_amounts": large_amounts, "raw_text": row_text[:200]}
                        ),
                    }
                )

    return relationships


def _is_numeric_amount(value: Any) -> bool:
    """Check if value represents a numeric amount."""
    if not value:
        return False

    value_str = str(value).replace(",", "").replace(" ", "")
    try:
        float(value_str)
        return len(value_str) >= 3  # At least 3 digits
    except (ValueError, TypeError):
        return False


def _parse_amount(value: Any) -> Optional[float]:
    """Parse amount from various formats."""
    if not value:
        return None

    try:
        value_str = str(value).replace(",", "").replace(" ", "")
        return float(value_str)
    except (ValueError, TypeError):
        return None


def _parse_percentage(value: Any) -> Optional[float]:
    """Parse percentage value."""
    if not value:
        return None

    try:
        value_str = str(value).replace("%", "").replace(" ", "")
        return float(value_str)
    except (ValueError, TypeError):
        return None


def load_financial_relationship_edges(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load financial relationship edges between companies.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    all_relationships = []

    # Extract relationships from all files
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        relationships = extract_financial_relationships(data, year, company_name)
        all_relationships.extend(relationships)

    print(f"Extracted {len(all_relationships)} financial relationships")

    # Deduplicate relationships by (source, target, relationship_type) key
    unique_relationships = {}
    duplicate_count = 0

    for rel in all_relationships:
        # Create unique key for deduplication
        key = (rel["source_company"], rel["target_company"], rel["relationship_type"])

        if key in unique_relationships:
            duplicate_count += 1
            existing = unique_relationships[key]

            # Merge data: prefer non-null values, higher amounts, etc.
            merged = existing.copy()

            # Prefer non-null amounts (choose higher value if both exist)
            if rel.get("amount_current") and (
                not existing.get("amount_current")
                or rel["amount_current"] > existing["amount_current"]
            ):
                merged["amount_current"] = rel["amount_current"]

            # Prefer non-null ownership percentages
            if rel.get("ownership_percentage") and not existing.get(
                "ownership_percentage"
            ):
                merged["ownership_percentage"] = rel["ownership_percentage"]

            # Prefer more detailed source information
            if rel.get("book_value") and not existing.get("book_value"):
                merged["book_value"] = rel["book_value"]
            if rel.get("market_value") and not existing.get("market_value"):
                merged["market_value"] = rel["market_value"]

            # Update data source to indicate merge
            if existing["data_source"] != rel["data_source"]:
                merged["data_source"] = (
                    f"{existing['data_source']},{rel['data_source']}"
                )

            unique_relationships[key] = merged
        else:
            unique_relationships[key] = rel

    deduplicated_relationships = list(unique_relationships.values())

    print(
        f"After deduplication: {len(deduplicated_relationships)} unique relationships"
    )
    if duplicate_count > 0:
        print(f"  - Merged {duplicate_count} duplicates")

    # Group by relationship type
    relationship_counts = {}
    for rel in deduplicated_relationships:
        rel_type = rel["relationship_type"]
        relationship_counts[rel_type] = relationship_counts.get(rel_type, 0) + 1

    for rel_type, count in relationship_counts.items():
        print(f"  - {rel_type}: {count}")

    # Create relationship edges in Neo4j
    created_count = 0
    for relationship in deduplicated_relationships:
        try:
            # Get source and target node IDs
            source_id = (
                build_company_id(relationship["source_company"])
                if relationship["source_company"] == company_name
                else build_subsidiary_id(company_name, relationship["source_company"])
            )

            target_id = (
                build_company_id(relationship["target_company"])
                if relationship["target_company"] == company_name
                else build_subsidiary_id(company_name, relationship["target_company"])
            )

            # Skip if target is generic
            if relationship["target_company"] == "subsidiaries_general":
                continue

            # Create relationship with properties
            rel_type = RELATIONSHIP_TYPES[relationship["relationship_type"].upper()]

            # Prepare relationship properties
            rel_props = {
                "source_id": source_id,
                "target_id": target_id,
                "transaction_type": relationship.get("transaction_type"),
                "year": relationship["year"],
                "amount_current": relationship.get("amount_current"),
                "amount_previous": relationship.get("amount_previous"),
                "transaction_direction": relationship.get("transaction_direction"),
                "data_source": relationship.get("data_source"),
                "ownership_percentage": relationship.get("ownership_percentage"),
                "book_value": relationship.get("book_value"),
                "market_value": relationship.get("market_value"),
                "guarantee_type": relationship.get("guarantee_type"),
                "guarantee_limit": relationship.get("guarantee_limit"),
            }

            session.run(
                f"""
                MATCH (source) WHERE source.id = $source_id
                MATCH (target) WHERE target.id = $target_id
                MERGE (source)-[r:{rel_type}]->(target)
                ON CREATE SET 
                    r.{PROPS['transaction_type']} = $transaction_type,
                    r.{PROPS['reporting_year']} = $year,
                    r.{PROPS['amount_current']} = $amount_current,
                    r.{PROPS['amount_previous']} = $amount_previous,
                    r.{PROPS['transaction_direction']} = $transaction_direction,
                    r.ownership_percentage = $ownership_percentage,
                    r.book_value = $book_value,
                    r.market_value = $market_value,
                    r.{PROPS['guarantee_type']} = $guarantee_type,
                    r.{PROPS['guarantee_limit']} = $guarantee_limit,
                    r.data_source = $data_source
                ON MATCH SET
                    r.{PROPS['amount_current']} = coalesce(r.{PROPS['amount_current']}, $amount_current),
                    r.{PROPS['amount_previous']} = coalesce(r.{PROPS['amount_previous']}, $amount_previous),
                    r.ownership_percentage = coalesce(r.ownership_percentage, $ownership_percentage),
                    r.book_value = coalesce(r.book_value, $book_value),
                    r.market_value = coalesce(r.market_value, $market_value)
                """,
                rel_props,
            )
            created_count += 1

        except Exception as e:
            print(
                f"Warning: Failed to create relationship {relationship['relationship_type']}: {e}"
            )
            continue

    print(f"✅ Created {created_count} financial relationship edges")


if __name__ == "__main__":
    # Test financial relationship extraction
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use recent files for testing
    recent_files = config.get_processed_files([2024])

    if recent_files:
        test_file = recent_files[-1]
        print(f"🧪 Testing financial relationship extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        relationships = extract_financial_relationships(
            data, company_info["year"], company_info["name"]
        )

        print(f"\n📊 Results:")
        print(f"Total relationships found: {len(relationships)}")

        # Group by type
        by_type = {}
        for rel in relationships:
            rel_type = rel["relationship_type"]
            if rel_type not in by_type:
                by_type[rel_type] = []
            by_type[rel_type].append(rel)

        for rel_type, rels in by_type.items():
            print(f"\n{rel_type.upper()} ({len(rels)}):")
            for i, rel in enumerate(rels[:3]):  # Show first 3
                print(f"  {i+1}. {rel['source_company']} → {rel['target_company']}")
                if rel.get("amount_current"):
                    print(f"     Amount: {rel['amount_current']:,.0f}")
                if rel.get("ownership_percentage"):
                    print(f"     Ownership: {rel['ownership_percentage']}%")
                print(f"     Type: {rel.get('transaction_type', 'N/A')}")
            if len(rels) > 3:
                print(f"  ... and {len(rels) - 3} more")
    else:
        print("No processed files found for testing")
