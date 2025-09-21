from __future__ import annotations

"""
Knowledge Graph schema constants and property conventions.

This module defines node and relationship labels following the
financial-knowledge-graph-schema and provides minimal validation helpers.
"""

from typing import Dict, Final, Iterable, Mapping


# Node labels (stable, referenced across loaders)
NODE_TYPES: Final[Dict[str, str]] = {
    "COMPANY": "company",
    "SUBSIDIARY": "subsidiary",
    "FS_SECTION": "financial_statement",
    "FS_CATEGORY": "fs_category",
    "YEAR_NODE": "year_node",
    "FINANCIAL_DATA": "financial_data",
    "AUDITOR": "auditor",
    "AUDIT_INFO": "audit_info",
    "NOTE": "note",
    "NOTE_CATEGORY": "note_category",
    "CONCEPT": "concept",
    "RISK_TERM": "risk_term",
    "SEARCH_DOC": "search_doc",
}


# Relationship types (stable)
RELATIONSHIP_TYPES: Final[Dict[str, str]] = {
    "HAS_SUBSIDIARY": "has_subsidiary",
    "HAS_FINANCIAL_STATEMENT": "has_financial_statement",
    "HAS_CATEGORY": "has_category",
    "HAS_YEAR_DATA": "has_year_data",
    "CONTAINS_DATA": "contains_data",
    "AUDITED_BY": "audited_by",
    "HAS_AUDIT_INFO": "has_audit_info",
    "HAS_NOTE": "has_note",
    "HAS_NOTE_CATEGORY": "has_note_category",
    "LINKS_TO_NOTE": "links_to_note",
    "TREND_TO": "trend_to",
    "RELATED_TO": "related_to",
    "MAPPED_TO": "mapped_to",
    # Financial relationship types for inter-company transactions
    "INVESTS_IN": "invests_in",  # Investment relationships with amounts
    "TRADES_WITH": "trades_with",  # Sales/purchase transactions
    "OWES_TO": "owes_to",  # Debt/credit relationships
    "GUARANTEES_FOR": "guarantees_for",  # Guarantee/collateral relationships
}


# Canonical property names used across labels
PROPS: Final[Dict[str, str]] = {
    "id": "id",
    "name": "name",
    "year": "year",
    "section_code": "section_code",  # BS | PL | CF | EQ
    "category_path": "category_path",  # e.g., Assets>CurrentAssets>Cash
    "metric": "metric",
    "unit": "unit",
    "value": "value",
    "currency": "currency",
    "source_ref": "source_ref",  # table/line anchor
    "text": "text",
    "note_number": "note_number",
    "category": "category",
    "confidence": "confidence",
    "company": "company",
    # FINANCIAL_DATA specific properties
    "item_name": "item_name",
    "column_name": "column_name",
    "original_text": "original_text",
    "is_negative": "is_negative",
    "note_references": "note_references",
    # AUDIT_INFO specific properties
    "audit_type": "audit_type",
    "audit_opinion": "audit_opinion",
    "audit_date": "audit_date",
    "auditor_name": "auditor_name",
    # Financial relationship properties (for relationships between companies)
    "transaction_type": "transaction_type",  # investment, trade, debt, guarantee
    "amount_current": "amount_current",  # 당기말 금액
    "amount_previous": "amount_previous",  # 전기말 금액
    "transaction_direction": "transaction_direction",  # inbound/outbound
    "reporting_year": "reporting_year",  # 보고 연도
    "guarantee_type": "guarantee_type",  # 보증 유형
    "guarantee_limit": "guarantee_limit",  # 보증 한도
    "collateral_type": "collateral_type",  # 담보 유형
    "interest_rate": "interest_rate",  # 이자율
    "maturity_date": "maturity_date",  # 만기일
    "transaction_details": "transaction_details",  # JSON 형태의 상세 정보
}


def ensure_required_properties(
    data: Mapping[str, object], required: Iterable[str]
) -> None:
    """Raise ValueError if any required property is missing from data.

    Args:
            data: Property dictionary to validate.
            required: Iterable of required property keys.

    Raises:
            ValueError: If a required key is not present in data.
    """
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError(f"Missing required properties: {missing}")


def validate_label(label: str) -> None:
    """Validate that a label is a known node label.

    Raises ValueError if not recognized.
    """
    if label not in NODE_TYPES.values():
        raise ValueError(f"Unknown node label: {label}")


def validate_relationship(rel_type: str) -> None:
    """Validate that a relationship type is recognized.

    Raises ValueError if not recognized.
    """
    if rel_type not in RELATIONSHIP_TYPES.values():
        raise ValueError(f"Unknown relationship type: {rel_type}")
