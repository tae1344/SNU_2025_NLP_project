from __future__ import annotations

"""Deterministic ID utilities for Knowledge Graph nodes and relationships.

IDs are stable SHA-1 hashes of canonical key parts joined by '|'.
Caller is responsible for choosing semantically stable key parts.
"""

from hashlib import sha1
from typing import Iterable


def _normalize(part: str) -> str:
    """Normalize a key part for hashing.

    - Strip surrounding whitespace
    - Use NFC normalization and lowercasing for stability (avoid locale issues)
    """
    # Note: Keeping implementation minimal to avoid extra deps.
    # If needed, add unicodedata.normalize("NFC", part) for stricter control.
    return part.strip().lower()


def make_sha1_id(key_parts: Iterable[str]) -> str:
    """Create a deterministic SHA-1 hex ID from ordered key parts.

    Args:
        key_parts: Ordered iterable of strings. Order must be stable across runs.

    Returns:
        Hex digest string (40 chars).
    """
    joined = "|".join(_normalize(p) for p in key_parts)
    return sha1(joined.encode("utf-8")).hexdigest()


# Convenience helpers (recommended key constructions)


def build_company_id(company_name: str) -> str:
    """Generate deterministic ID for COMPANY node."""
    return make_sha1_id([company_name])


def build_fs_section_id(company_name: str, section_code: str) -> str:
    """Generate deterministic ID for FS_SECTION node."""
    return make_sha1_id([company_name, section_code])


def build_category_id(company_name: str, section_code: str, category_path: str) -> str:
    """Generate deterministic ID for FS_CATEGORY node."""
    return make_sha1_id([company_name, section_code, category_path])


def build_year_node_id(company_name: str, section_code: str, year: int | str) -> str:
    """Generate deterministic ID for YEAR_NODE node."""
    return make_sha1_id([company_name, section_code, str(year)])


def build_financial_data_id(
    company_name: str, year: int | str, item_name: str, column_name: str
) -> str:
    """Generate deterministic ID for FINANCIAL_DATA node.

    Args:
        company_name: Name of the company
        year: Reporting year
        item_name: Financial statement line item name (e.g., "현금및현금성자산")
        column_name: Column name (e.g., "제 46 (당) 기")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, str(year), item_name, column_name])


def build_auditor_id(auditor_name: str) -> str:
    """Generate deterministic ID for AUDITOR node.

    Args:
        auditor_name: Name of the auditing firm (e.g., "삼일회계법인")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([auditor_name])


def build_audit_info_id(company_name: str, year: int | str, audit_type: str) -> str:
    """Generate deterministic ID for AUDIT_INFO node.

    Args:
        company_name: Name of the company
        year: Reporting year
        audit_type: Type of audit info (e.g., "감사의견", "내부회계관리제도")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, str(year), audit_type])


def build_note_id(company_name: str, year: int | str, note_number: str | int) -> str:
    """Generate deterministic ID for NOTE node."""
    return make_sha1_id([company_name, str(year), str(note_number)])


def build_note_category_id(note_category_name: str) -> str:
    """Generate deterministic ID for NOTE_CATEGORY node."""
    return make_sha1_id([note_category_name])


def build_fs_category_id(
    company_name: str, section_code: str, category_name: str
) -> str:
    """Generate deterministic ID for FS_CATEGORY node.

    Args:
        company_name: Name of the company
        section_code: Financial statement section (BS, PL, CF, EQ)
        category_name: Name of the financial category

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, section_code, category_name])


def build_search_doc_id(
    company_name: str, year: int | str, doc_type: str, anchor: str
) -> str:
    """Generate deterministic ID for SEARCH_DOC node."""
    return make_sha1_id([company_name, str(year), doc_type, anchor])


def build_subsidiary_id(company_name: str, subsidiary_name: str) -> str:
    """Generate deterministic ID for SUBSIDIARY node.

    Args:
        company_name: Name of the parent company (e.g., "삼성전자")
        subsidiary_name: Name of the subsidiary (e.g., "삼성디스플레이")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, subsidiary_name])


def build_affiliate_id(company_name: str, affiliate_name: str) -> str:
    """Generate deterministic ID for AFFILIATE node.

    Args:
        company_name: Name of the parent company (e.g., "삼성전자")
        affiliate_name: Name of the affiliate (e.g., "삼성SDI")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, "affiliate", affiliate_name])


def build_joint_venture_id(company_name: str, joint_venture_name: str) -> str:
    """Generate deterministic ID for JOINT_VENTURE node.

    Args:
        company_name: Name of the parent company (e.g., "삼성전자")
        joint_venture_name: Name of the joint venture

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, "joint_venture", joint_venture_name])


def build_special_relation_id(company_name: str, special_relation_name: str) -> str:
    """Generate deterministic ID for SPECIAL_RELATION node.

    Args:
        company_name: Name of the parent company (e.g., "삼성전자")
        special_relation_name: Name of the special relation company

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, "special_relation", special_relation_name])


def build_concept_id(concept_name: str, concept_category: str = "") -> str:
    """Generate deterministic ID for CONCEPT node.

    Args:
        concept_name: Name of the financial concept (e.g., "매출액", "유동자산")
        concept_category: Optional category for grouping (e.g., "자산", "수익")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    if concept_category:
        return make_sha1_id([concept_category, concept_name])
    return make_sha1_id([concept_name])


def build_risk_term_id(risk_term: str, risk_category: str = "") -> str:
    """Generate deterministic ID for RISK_TERM node.

    Args:
        risk_term: Risk terminology (e.g., "신용위험", "유동성위험")
        risk_category: Optional risk category (e.g., "금융위험", "운영위험")

    Returns:
        SHA-1 hash string representing the unique ID
    """
    if risk_category:
        return make_sha1_id([risk_category, risk_term])
    return make_sha1_id([risk_term])


# Alternative financial data ID for more detailed categorization
def build_detailed_financial_data_id(
    company_name: str,
    section_code: str,
    year: int | str,
    category_path: str,
    metric: str,
    unit: str,
    source_ref: str,
) -> str:
    """Generate deterministic ID for detailed FINANCIAL_DATA node with full categorization."""
    return make_sha1_id(
        [
            company_name,
            section_code,
            str(year),
            category_path,
            metric,
            unit,
            source_ref,
        ]
    )


# Alternative audit info ID with text hash for uniqueness
def build_detailed_audit_info_id(
    company_name: str, year: int | str, info_type: str, text_hash: str
) -> str:
    """Generate deterministic ID for AUDIT_INFO node with content hash."""
    return make_sha1_id([company_name, str(year), info_type, text_hash])
