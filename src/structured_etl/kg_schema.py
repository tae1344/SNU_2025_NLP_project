from __future__ import annotations

"""
Knowledge Graph schema constants and property conventions.

This module defines node and relationship labels following the
financial-knowledge-graph-schema and provides minimal validation helpers.
"""

from typing import Dict, Final, Iterable, Mapping


# Node labels (stable, referenced across loaders)
NODE_TYPES: Final[Dict[str, str]] = {
    # 기본 구조
    "COMPANY": "company",
    "SUBSIDIARY": "subsidiary",  # 종속기업 (50% 이상 지분)
    "AFFILIATE": "affiliate",  # 관계기업 (20-50% 지분)
    "JOINT_VENTURE": "joint_venture",  # 공동기업
    "SPECIAL_RELATION": "special_relation",  # 특수관계기업
    # 재무제표 구조
    "FS_SECTION": "financial_statement",  # 재무제표 섹션
    "FS_CATEGORY": "fs_category",  # 재무제표 세부 카테고리
    "YEAR_NODE": "year_node",  # 년도별 노드
    "FINANCIAL_DATA": "financial_data",  # 실제 재무 데이터
    # 감사 정보
    "AUDITOR": "auditor",  # 감사사
    "AUDIT_INFO": "audit_info",  # 감사 정보
    # 주석 시스템
    "NOTE": "note",  # 주석 본문
    "NOTE_CATEGORY": "note_category",  # 주석 유형
    # 시계열 분석
    "FINANCIAL_TREND": "financial_trend",  # 재무 트렌드 분석
    "RELATIONSHIP_CHANGE": "relationship_change",  # 관계 변화 추적
    # 검색 및 개념
    "CONCEPT": "concept",  # 재무 개념
    "RISK_TERM": "risk_term",  # 리스크 용어
    "SEARCH_DOC": "search_doc",  # 검색 문서
}


RELATIONSHIP_TYPES: Final[Dict[str, str]] = {
    # 회사 관계 세분화
    "HAS_SUBSIDIARY": "has_subsidiary",  # 종속기업 관계
    "HAS_AFFILIATE": "has_affiliate",  # 관계기업 관계
    "HAS_JOINT_VENTURE": "has_joint_venture",  # 공동기업 관계
    "HAS_SPECIAL_RELATION": "has_special_relation",  # 특수관계기업
    # 회사간 재무 관계
    "INVESTS_IN": "invests_in",  # 투자 관계
    "TRADES_WITH": "trades_with",  # 거래 관계
    "OWES_TO": "owes_to",  # 채무 관계
    "GUARANTEES_FOR": "guarantees_for",  # 보증 관계
    # 재무제표 구조
    "HAS_FINANCIAL_STATEMENT": "has_financial_statement",
    "HAS_CATEGORY": "has_category",
    "HAS_YEAR_DATA": "has_year_data",
    "CONTAINS_DATA": "contains_data",
    # 감사 정보
    "AUDITED_BY": "audited_by",
    "HAS_AUDIT_INFO": "has_audit_info",
    # 주석 시스템
    "HAS_NOTE": "has_note",
    "HAS_NOTE_CATEGORY": "has_note_category",
    "LINKS_TO_NOTE": "links_to_note",
    # 시계열 분석
    "TREND_TO": "trend_to",  # 시계열 트렌드
    "HAS_TREND": "has_trend",  # 트렌드 관계
    "HAS_CHANGE": "has_change",  # 변화 관계
    "PRECEDES": "precedes",  # 시간적 선후 관계
    # 일반 관계
    "RELATED_TO": "related_to",
    "MAPPED_TO": "mapped_to",
}


# Canonical property names used across labels
PROPS: Final[Dict[str, str]] = {
    # 기본 식별자
    "id": "id",
    "name": "name",
    "year": "year",
    "company": "company",
    # 회사 관계 속성
    "ownership_percentage": "ownership_percentage",  # 지분율
    "relationship_type": "relationship_type",  # 관계 유형
    "investment_amount": "investment_amount",  # 투자 금액
    "trade_amount": "trade_amount",  # 거래 금액
    "debt_amount": "debt_amount",  # 채무 금액
    # 재무제표 구조
    "section_code": "section_code",  # BS | PL | CI | CF | EQ
    "category_path": "category_path",  # Assets>CurrentAssets>Cash
    "category_name": "category_name",
    "hierarchy_level": "hierarchy_level",
    # 재무 데이터
    "item_name": "item_name",
    "column_name": "column_name",
    "original_text": "original_text",
    "value": "value",
    "unit": "unit",
    "currency": "currency",
    "is_negative": "is_negative",
    "note_references": "note_references",
    # 주석 관련
    "note_number": "note_number",
    "category": "category",
    "confidence": "confidence",
    "text": "text",
    "content": "content",
    # 감사 정보
    "audit_type": "audit_type",
    "audit_opinion": "audit_opinion",
    "audit_date": "audit_date",
    "auditor_name": "auditor_name",
    # 시계열 분석
    "change_rate": "change_rate",  # 변화율
    "change_amount": "change_amount",  # 변화량
    "trend_direction": "trend_direction",  # 트렌드 방향
    "volatility": "volatility",  # 변동성
    "growth_rate": "growth_rate",  # 성장률
    # 회사간 재무 관계
    "transaction_type": "transaction_type",
    "amount_current": "amount_current",
    "amount_previous": "amount_previous",
    "transaction_direction": "transaction_direction",
    "reporting_year": "reporting_year",
    "guarantee_type": "guarantee_type",
    "guarantee_limit": "guarantee_limit",
    "collateral_type": "collateral_type",
    "interest_rate": "interest_rate",
    "maturity_date": "maturity_date",
    "transaction_details": "transaction_details",
    # 기타
    "metric": "metric",
    "source_ref": "source_ref",  # table/line anchor
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
