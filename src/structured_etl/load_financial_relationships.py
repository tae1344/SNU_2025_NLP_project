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

# Constants for relationship types and node types
INVESTS_IN = RELATIONSHIP_TYPES["INVESTS_IN"]
TRADES_WITH = RELATIONSHIP_TYPES["TRADES_WITH"]
OWES_TO = RELATIONSHIP_TYPES["OWES_TO"]
GUARANTEES_FOR = RELATIONSHIP_TYPES.get("GUARANTEES_FOR", "guarantees_for")

COMPANY_NODE = NODE_TYPES["COMPANY"]
SUBSIDIARY_NODE = NODE_TYPES["SUBSIDIARY"]


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
        relationship_nature = None
        region = None
        business_type = None

        # Identify target company and amounts
        for key, value in row.items():
            if not value:
                continue

            key_lower = str(key).lower()
            value_str = str(value)

            # Company name identification - improved pattern matching
            if any(
                term in key_lower
                for term in [
                    "기업명",
                    "회사명",
                    "기업 명",
                    "company",
                    "('기업명",
                    "('회사명",
                    "기업명(*",
                    "회사명(*",
                ]
            ):
                # Check if it's a Samsung-related company
                if any(
                    samsung_term in value_str
                    for samsung_term in [
                        "삼성",
                        "Samsung",
                        "SAMEX",
                        "SEDA",
                        "SEM",
                        "SEDAM",
                        "SEUK",
                        "SEL",
                        "SSEL",
                        "SGE",
                        "SETK",
                        "SAPL",
                        "SESP",
                        "SME",
                        "SCIC",
                        "SEHK",
                        "SET",
                        "SEA",
                        "SII",
                    ]
                ):
                    target_company = value_str.strip()

            # Ownership percentage identification - improved patterns
            elif any(
                term in key_lower
                for term in ["지분율", "지분", "ownership", "지분율(%", "지분율 %"]
            ) and _is_numeric_amount(value):
                ownership_pct = _parse_percentage(value)

            # Amount identification - improved patterns
            elif any(
                term in key_lower
                for term in ["당기말", "당기", "current", "('당기말", "('당기"]
            ) and _is_numeric_amount(value):
                current_amount = _parse_amount(value)
            elif any(
                term in key_lower
                for term in ["전기말", "전기", "previous", "('전기말", "('전기"]
            ) and _is_numeric_amount(value):
                previous_amount = _parse_amount(value)

            # Book value and market value identification
            elif any(
                term in key_lower
                for term in ["장부금액", "장부가액", "book", "취득원가"]
            ) and _is_numeric_amount(value):
                book_value = _parse_amount(value)
            elif any(
                term in key_lower
                for term in ["시장가치", "시장가액", "market", "시장가치"]
            ) and _is_numeric_amount(value):
                market_value = _parse_amount(value)

            # Relationship nature and business type
            elif any(
                term in key_lower
                for term in ["관계의 성격", "업종", "business", "nature"]
            ):
                relationship_nature = value_str.strip()
            elif any(term in key_lower for term in ["지역", "region", "area"]):
                region = value_str.strip()

        # Create relationship if we have meaningful data
        # Relaxed condition:只要有公司名就创建关系，不一定要有金额
        if target_company:
            relationships.append(
                {
                    "relationship_type": INVESTS_IN,
                    "source_company": company_name,
                    "target_company": target_company,
                    "year": year,
                    "amount_current": current_amount,
                    "amount_previous": previous_amount,
                    "ownership_percentage": ownership_pct,
                    "book_value": book_value,
                    "market_value": market_value,
                    "relationship_nature": relationship_nature,
                    "region": region,
                    "business_type": business_type,
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
        relationship_type = None
        assets = None
        liabilities = None
        net_income = None

        # Identify company and transaction amounts
        for key, value in row.items():
            if not value:
                continue

            key_lower = str(key).lower()
            value_str = str(value)

            # Company name - improved pattern matching
            if any(
                term in key_lower
                for term in [
                    "기업명",
                    "회사명",
                    "company",
                    "('기업명",
                    "('회사명",
                    "기업명(*",
                    "회사명(*",
                    "기업명(*1)",
                    "회사명(*1)",
                ]
            ):
                # Check if it's a Samsung-related company
                if any(
                    samsung_term in value_str
                    for samsung_term in [
                        "삼성",
                        "Samsung",
                        "SAMEX",
                        "SEDA",
                        "SEM",
                        "SEDAM",
                        "SEUK",
                        "SEL",
                        "SSEL",
                        "SGE",
                        "SETK",
                        "SAPL",
                        "SESP",
                        "SME",
                        "SCIC",
                        "SEHK",
                        "SET",
                        "SEA",
                        "SII",
                        "디스플레이",
                        "에스디에스",
                        "바이오로직스",
                        "SDI",
                        "제일기획",
                    ]
                ):
                    target_company = value_str.strip()

            # Transaction amounts - improved patterns
            elif any(
                term in key_lower
                for term in ["매출", "매출액", "매출 등", "sales", "('매출", "('매출액"]
            ) and _is_numeric_amount(value):
                sales_amount = _parse_amount(value)
            elif any(
                term in key_lower
                for term in [
                    "매입",
                    "매입액",
                    "매입 등",
                    "purchase",
                    "('매입",
                    "('매입액",
                ]
            ) and _is_numeric_amount(value):
                purchase_amount = _parse_amount(value)
            elif any(
                term in key_lower
                for term in ["비유동자산 처분", "자산 처분", "asset disposal"]
            ) and _is_numeric_amount(value):
                asset_disposal = _parse_amount(value)
            elif any(
                term in key_lower
                for term in ["비유동자산 매입", "자산 매입", "asset acquisition"]
            ) and _is_numeric_amount(value):
                asset_acquisition = _parse_amount(value)

            # Additional financial data
            elif any(
                term in key_lower for term in ["자산", "assets", "('자산"]
            ) and _is_numeric_amount(value):
                assets = _parse_amount(value)
            elif any(
                term in key_lower for term in ["부채", "liabilities", "('부채"]
            ) and _is_numeric_amount(value):
                liabilities = _parse_amount(value)
            elif any(
                term in key_lower
                for term in ["당기순이익", "순이익", "net income", "('당기순이익"]
            ) and _is_numeric_amount(value):
                net_income = _parse_amount(value)

            # Relationship type identification
            elif any(
                term in key_lower for term in ["구분", "구분:", "type", "category"]
            ):
                relationship_type = value_str.strip()

        # Create relationships for sales (outbound)
        if target_company and sales_amount and sales_amount > 0:
            relationships.append(
                {
                    "relationship_type": TRADES_WITH,
                    "source_company": company_name,
                    "target_company": target_company,
                    "year": year,
                    "amount_current": sales_amount,
                    "assets": assets,
                    "liabilities": liabilities,
                    "net_income": net_income,
                    "relationship_category": relationship_type,
                    "transaction_type": "sales",
                    "transaction_direction": "outbound",
                    "data_source": "trade_table",
                }
            )

        # Create relationships for purchases (inbound)
        if target_company and purchase_amount and purchase_amount > 0:
            relationships.append(
                {
                    "relationship_type": TRADES_WITH,
                    "source_company": target_company,  # Reverse direction for purchases
                    "target_company": company_name,
                    "year": year,
                    "amount_current": purchase_amount,
                    "relationship_category": relationship_type,
                    "transaction_type": "purchase",
                    "transaction_direction": "inbound",
                    "data_source": "trade_table",
                }
            )

        # Create relationships for asset transactions
        if target_company and (asset_disposal or asset_acquisition):
            relationships.append(
                {
                    "relationship_type": TRADES_WITH,
                    "source_company": company_name,
                    "target_company": target_company,
                    "year": year,
                    "amount_current": asset_disposal or asset_acquisition,
                    "asset_disposal": asset_disposal,
                    "asset_acquisition": asset_acquisition,
                    "relationship_category": relationship_type,
                    "transaction_type": "asset_transaction",
                    "transaction_direction": (
                        "outbound" if asset_disposal else "inbound"
                    ),
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
        relationship_type = None

        # Identify company and debt/credit amounts
        for key, value in row.items():
            if not value:
                continue

            key_lower = str(key).lower()
            value_str = str(value)

            # Company name - improved pattern matching
            if any(
                term in key_lower
                for term in [
                    "기업명",
                    "회사명",
                    "company",
                    "('기업명",
                    "('회사명",
                    "기업명(*",
                    "회사명(*",
                    "기업명(*1)",
                    "회사명(*1)",
                ]
            ):
                # Check if it's a Samsung-related company
                if any(
                    samsung_term in value_str
                    for samsung_term in [
                        "삼성",
                        "Samsung",
                        "SAMEX",
                        "SEDA",
                        "SEM",
                        "SEDAM",
                        "SEUK",
                        "SEL",
                        "SSEL",
                        "SGE",
                        "SETK",
                        "SAPL",
                        "SESP",
                        "SME",
                        "SCIC",
                        "SEHK",
                        "SET",
                        "SEA",
                        "SII",
                        "디스플레이",
                        "에스디에스",
                        "바이오로직스",
                        "SDI",
                        "제일기획",
                    ]
                ):
                    target_company = value_str.strip()

            # Debt/Credit amounts - improved patterns
            elif any(
                term in key_lower
                for term in ["채권", "채권 등", "receivables", "('채권", "채권 등(*2)"]
            ) and _is_numeric_amount(value):
                receivables = _parse_amount(value)
            elif any(
                term in key_lower
                for term in [
                    "채무",
                    "채무 등",
                    "payables",
                    "('채무",
                    "채무 등(*2)",
                    "채무 등(*3)",
                ]
            ) and _is_numeric_amount(value):
                payables = _parse_amount(value)

            # Relationship type identification
            elif any(
                term in key_lower for term in ["구분", "구분:", "type", "category"]
            ):
                relationship_type = value_str.strip()

        # Create receivables relationship (target company owes to source)
        if target_company and receivables and receivables > 0:
            relationships.append(
                {
                    "relationship_type": OWES_TO,
                    "source_company": target_company,  # Debtor
                    "target_company": company_name,  # Creditor
                    "year": year,
                    "amount_current": receivables,
                    "relationship_category": relationship_type,
                    "transaction_type": "debt",
                    "transaction_direction": "inbound",  # Money flows to parent
                    "data_source": "debt_table",
                }
            )

        # Create payables relationship (source owes to target company)
        if target_company and payables and payables > 0:
            relationships.append(
                {
                    "relationship_type": OWES_TO,
                    "source_company": company_name,  # Debtor
                    "target_company": target_company,  # Creditor
                    "year": year,
                    "amount_current": payables,
                    "relationship_category": relationship_type,
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
        target_company = None
        guarantee_limit = None
        related_debt = None
        guarantee_end_date = None
        guarantor = None
        guarantee_type = None

        # Check if row contains guarantee-related content
        row_text = " ".join(str(v) for v in row.values() if v).lower()

        if any(term in row_text for term in ["보증", "담보", "guarantee"]) and any(
            samsung_term in row_text
            for samsung_term in ["삼성", "samsung", "setk", "sea"]
        ):

            # Extract specific guarantee information from structured data
            for key, value in row.items():
                if not value:
                    continue

                key_lower = str(key).lower()
                value_str = str(value)

                # Company identification for guarantee relationships
                if any(
                    term in key_lower
                    for term in [
                        "해외종속기업",
                        "보증처",
                        "기업명",
                        "회사명",
                        "subsidiary",
                    ]
                ):
                    if any(
                        samsung_term in value_str
                        for samsung_term in [
                            "삼성",
                            "Samsung",
                            "SETK",
                            "SEDA",
                            "SEM",
                            "SEDAM",
                            "SEUK",
                            "SEL",
                            "SSEL",
                            "SGE",
                            "SAPL",
                            "SESP",
                            "SME",
                            "SCIC",
                            "SEHK",
                            "SET",
                            "SEA",
                            "SII",
                        ]
                    ):
                        target_company = value_str.strip()

                # Guarantee limit identification
                elif any(
                    term in key_lower
                    for term in [
                        "채무보증한도",
                        "보증한도",
                        "guarantee limit",
                        "보증한도",
                    ]
                ) and _is_numeric_amount(value):
                    guarantee_limit = _parse_amount(value)

                # Related debt identification
                elif any(
                    term in key_lower
                    for term in ["관련 차입금", "차입금", "related debt", "관련차입금"]
                ) and _is_numeric_amount(value):
                    related_debt = _parse_amount(value)

                # Guarantee end date
                elif any(
                    term in key_lower
                    for term in ["보증종료일", "종료일", "end date", "만료일"]
                ):
                    guarantee_end_date = value_str.strip()

                # Guarantor identification
                elif any(
                    term in key_lower for term in ["보증처", "guarantor", "보증기관"]
                ):
                    guarantor = value_str.strip()

            # Extract guarantee amounts from text if not found in structured fields
            if not guarantee_limit and not related_debt:
                amounts = re.findall(r"[0-9,]+", row_text)
                large_amounts = [
                    _parse_amount(amt)
                    for amt in amounts
                    if len(amt.replace(",", "")) >= 6
                ]  # 6+ digits
                if large_amounts:
                    guarantee_limit = max(large_amounts)

            # Determine guarantee type
            if any(term in row_text for term in ["채무보증", "debt guarantee"]):
                guarantee_type = "debt_guarantee"
            elif any(term in row_text for term in ["지급보증", "payment guarantee"]):
                guarantee_type = "payment_guarantee"
            elif any(term in row_text for term in ["담보", "collateral"]):
                guarantee_type = "collateral"
            else:
                guarantee_type = "guarantee"

            # Create guarantee relationship
            if guarantee_limit or related_debt:
                relationships.append(
                    {
                        "relationship_type": "guarantees_for",
                        "source_company": company_name,  # Guarantor
                        "target_company": target_company or "subsidiaries_general",
                        "year": year,
                        "amount_current": guarantee_limit,
                        "guarantee_limit": guarantee_limit,
                        "related_debt": related_debt,
                        "guarantee_end_date": guarantee_end_date,
                        "guarantor": guarantor,
                        "guarantee_type": guarantee_type,
                        "transaction_type": "guarantee",
                        "data_source": "guarantee_table",
                        "transaction_details": json.dumps(
                            {
                                "raw_text": row_text[:200],
                                "guarantee_end_date": guarantee_end_date,
                                "guarantor": guarantor,
                            }
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

    # Improved deduplication logic with relationship-specific keys
    unique_relationships = {}
    duplicate_count = 0

    for rel in all_relationships:
        # Create more specific deduplication key based on relationship type
        if rel["relationship_type"] == INVESTS_IN:
            # For investments, use company + ownership percentage as key
            key = (
                rel["source_company"],
                rel["target_company"],
                INVESTS_IN,
                rel.get("ownership_percentage"),
            )
        elif rel["relationship_type"] == TRADES_WITH:
            # For trades, use company + transaction type as key
            key = (
                rel["source_company"],
                rel["target_company"],
                TRADES_WITH,
                rel.get("transaction_type", "unknown"),
            )
        elif rel["relationship_type"] == OWES_TO:
            # For debts, use company + transaction direction as key
            key = (
                rel["source_company"],
                rel["target_company"],
                OWES_TO,
                rel.get("transaction_direction", "unknown"),
            )
        elif rel["relationship_type"] == GUARANTEES_FOR:
            # For guarantees, use company + guarantee type as key
            key = (
                rel["source_company"],
                rel["target_company"],
                GUARANTEES_FOR,
                rel.get("guarantee_type", "unknown"),
            )
        else:
            # Fallback to basic key
            key = (
                rel["source_company"],
                rel["target_company"],
                rel["relationship_type"],
            )

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

            # Merge additional properties
            for prop in [
                "relationship_nature",
                "region",
                "business_type",
                "relationship_category",
                "guarantee_limit",
                "related_debt",
                "guarantee_end_date",
                "guarantor",
                "assets",
                "liabilities",
                "net_income",
            ]:
                if rel.get(prop) and not existing.get(prop):
                    merged[prop] = rel[prop]

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

            # Prepare relationship properties with all new fields
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
                "relationship_nature": relationship.get("relationship_nature"),
                "region": relationship.get("region"),
                "business_type": relationship.get("business_type"),
                "relationship_category": relationship.get("relationship_category"),
                "related_debt": relationship.get("related_debt"),
                "guarantee_end_date": relationship.get("guarantee_end_date"),
                "guarantor": relationship.get("guarantor"),
                "assets": relationship.get("assets"),
                "liabilities": relationship.get("liabilities"),
                "net_income": relationship.get("net_income"),
                "asset_disposal": relationship.get("asset_disposal"),
                "asset_acquisition": relationship.get("asset_acquisition"),
                "transaction_details": relationship.get("transaction_details"),
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
                    r.relationship_nature = $relationship_nature,
                    r.region = $region,
                    r.business_type = $business_type,
                    r.relationship_category = $relationship_category,
                    r.related_debt = $related_debt,
                    r.guarantee_end_date = $guarantee_end_date,
                    r.guarantor = $guarantor,
                    r.assets = $assets,
                    r.liabilities = $liabilities,
                    r.net_income = $net_income,
                    r.asset_disposal = $asset_disposal,
                    r.asset_acquisition = $asset_acquisition,
                    r.transaction_details = $transaction_details,
                    r.data_source = $data_source
                ON MATCH SET
                    r.{PROPS['amount_current']} = coalesce(r.{PROPS['amount_current']}, $amount_current),
                    r.{PROPS['amount_previous']} = coalesce(r.{PROPS['amount_previous']}, $amount_previous),
                    r.ownership_percentage = coalesce(r.ownership_percentage, $ownership_percentage),
                    r.book_value = coalesce(r.book_value, $book_value),
                    r.market_value = coalesce(r.market_value, $market_value),
                    r.relationship_nature = coalesce(r.relationship_nature, $relationship_nature),
                    r.region = coalesce(r.region, $region),
                    r.business_type = coalesce(r.business_type, $business_type),
                    r.relationship_category = coalesce(r.relationship_category, $relationship_category),
                    r.related_debt = coalesce(r.related_debt, $related_debt),
                    r.guarantee_end_date = coalesce(r.guarantee_end_date, $guarantee_end_date),
                    r.guarantor = coalesce(r.guarantor, $guarantor),
                    r.assets = coalesce(r.assets, $assets),
                    r.liabilities = coalesce(r.liabilities, $liabilities),
                    r.net_income = coalesce(r.net_income, $net_income),
                    r.asset_disposal = coalesce(r.asset_disposal, $asset_disposal),
                    r.asset_acquisition = coalesce(r.asset_acquisition, $asset_acquisition)
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
