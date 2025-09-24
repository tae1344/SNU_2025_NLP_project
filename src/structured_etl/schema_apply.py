from __future__ import annotations

"""Apply comprehensive Neo4j constraints and indexes idempotently.

Reads canonical labels from kg_schema and creates:
1. Unique constraints on ID for all node types (including new company relationship types)
2. Basic lookup indexes for common query patterns
3. Full-text search indexes for content search
4. Composite indexes for complex multi-property queries
5. Enhanced company relationship indexes (ownership percentage, relationship type)
6. Financial relationship analysis indexes (investment, trade, debt amounts)
7. Time-series trend analysis indexes (change rate, volatility, growth rate)

This ensures optimal performance for the Samsung Financial Knowledge Graph
across all expected query patterns including:
- Enhanced company relationship analysis (subsidiary, affiliate, joint venture, special relation)
- Financial relationship tracking (investment, trade, debt, guarantee relationships)
- Time-series trend analysis and relationship change tracking
- Multi-dimensional filtering and complex financial queries
"""

from typing import Iterable

from .kg_schema import NODE_TYPES


UNIQUE_CONSTRAINT_CYPHER = """
CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE
"""

LOOKUP_INDEXES: dict[str, list[tuple[str, str]]] = {
    # label -> list of (property, cypher)
    # Cypher will be formatted with the label and property
    # Core entity indexes
    "company": [("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})")],
    "subsidiary": [
        ("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("company_type", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        (
            "ownership_percentage",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
        (
            "relationship_type",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
    ],
    # Enhanced company relationship indexes
    "affiliate": [
        ("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        (
            "ownership_percentage",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
        (
            "relationship_type",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
    ],
    "joint_venture": [
        ("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        (
            "ownership_percentage",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
        (
            "relationship_type",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
    ],
    "special_relation": [
        ("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        (
            "relationship_type",
            "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})",
        ),
    ],
    # Financial statement structure indexes
    "financial_statement": [
        ("section_code", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("section_name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    "fs_category": [
        ("category_name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("category_path", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("hierarchy_level", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    # Time-series and data indexes
    "year_node": [
        ("year", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("section_code", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    "financial_data": [
        ("item_name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("year", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("value", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("column_name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    # Audit and compliance indexes
    "auditor": [("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})")],
    "audit_info": [
        ("audit_opinion", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("audit_date", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("audit_type", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    # Notes and classification indexes
    "note": [
        ("note_number", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("year", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("category", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    "note_category": [
        ("category", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    # Search and analysis indexes
    "search_doc": [
        ("doc_type", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("year", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("title", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    # Concept and risk management indexes
    "concept": [
        ("name", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("category", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    "risk_term": [
        ("term", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("category", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    # Time-series analysis indexes
    "financial_trend": [
        ("trend_direction", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("change_rate", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("volatility", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("growth_rate", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
    "relationship_change": [
        ("change_type", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("change_amount", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
        ("change_rate", "CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.{prop})"),
    ],
}


# Full-text search indexes for text content
FULLTEXT_INDEXES: list[str] = [
    # Full-text indexes for content search (Neo4j 4.x+ syntax)
    "CREATE FULLTEXT INDEX search_doc_content_idx IF NOT EXISTS FOR (n:search_doc) ON EACH [n.content]",
    "CREATE FULLTEXT INDEX note_text_idx IF NOT EXISTS FOR (n:note) ON EACH [n.text]",
    "CREATE FULLTEXT INDEX note_name_idx IF NOT EXISTS FOR (n:note) ON EACH [n.name]",
    "CREATE FULLTEXT INDEX audit_kam_idx IF NOT EXISTS FOR (n:audit_info) ON EACH [n.key_audit_matters]",
]


# Composite indexes for complex queries
COMPOSITE_INDEXES: list[str] = [
    # Time-series analysis: year + section combination
    "CREATE INDEX year_section_idx IF NOT EXISTS FOR (n:year_node) ON (n.year, n.section_code)",
    # Year node: company + year + section for fast lookups
    "CREATE INDEX year_company_section_idx IF NOT EXISTS FOR (n:year_node) ON (n.company, n.year, n.section_code)",
    # Financial data analysis: item + year combination
    "CREATE INDEX financial_item_year_idx IF NOT EXISTS FOR (n:financial_data) ON (n.item_name, n.year)",
    # Note analysis: year + category combination
    "CREATE INDEX note_year_category_idx IF NOT EXISTS FOR (n:note) ON (n.year, n.category)",
    # Search document analysis: type + year combination
    "CREATE INDEX search_doc_type_year_idx IF NOT EXISTS FOR (n:search_doc) ON (n.doc_type, n.year)",
    # Category hierarchy: section + category combination
    "CREATE INDEX fs_section_category_idx IF NOT EXISTS FOR (n:fs_category) ON (n.section_code, n.category_name)",
    # Enhanced company relationship indexes
    "CREATE INDEX company_relationship_idx IF NOT EXISTS FOR (n:company) ON (n.year, n.relationship_type)",
    "CREATE INDEX subsidiary_ownership_idx IF NOT EXISTS FOR (n:subsidiary) ON (n.ownership_percentage, n.relationship_type)",
    "CREATE INDEX affiliate_ownership_idx IF NOT EXISTS FOR (n:affiliate) ON (n.ownership_percentage, n.relationship_type)",
    "CREATE INDEX joint_venture_ownership_idx IF NOT EXISTS FOR (n:joint_venture) ON (n.ownership_percentage, n.relationship_type)",
    # Financial relationship analysis indexes
    "CREATE INDEX investment_year_idx IF NOT EXISTS FOR (n:company) ON (n.year, n.investment_amount)",
    "CREATE INDEX trade_year_idx IF NOT EXISTS FOR (n:company) ON (n.year, n.trade_amount)",
    "CREATE INDEX debt_year_idx IF NOT EXISTS FOR (n:company) ON (n.year, n.debt_amount)",
    # Trend analysis indexes
    "CREATE INDEX trend_direction_rate_idx IF NOT EXISTS FOR (n:financial_trend) ON (n.trend_direction, n.change_rate)",
    "CREATE INDEX trend_volatility_idx IF NOT EXISTS FOR (n:financial_trend) ON (n.volatility, n.growth_rate)",
    "CREATE INDEX relationship_change_idx IF NOT EXISTS FOR (n:relationship_change) ON (n.change_type, n.change_amount)",
]


def build_constraint_statements() -> list[str]:
    """Build all constraint and index statements for the knowledge graph schema.

    Returns:
        List of Cypher statements to create constraints and indexes
    """
    stmts: list[str] = []

    # 1. Unique constraints on ID for all node types
    labels = sorted(set(NODE_TYPES.values()))
    stmts.extend([UNIQUE_CONSTRAINT_CYPHER.format(label=label) for label in labels])

    # 2. Basic lookup indexes
    for label, entries in LOOKUP_INDEXES.items():
        for prop, cy in entries:
            stmts.append(cy.format(label=label, prop=prop))

    # 3. Full-text search indexes
    stmts.extend(FULLTEXT_INDEXES)

    # 4. Composite indexes for complex queries
    stmts.extend(COMPOSITE_INDEXES)

    return stmts


def apply_schema(session) -> None:
    """Apply constraints and indexes using a given neo4j session.

    Args:
            session: neo4j.Session
    """
    for cypher in build_constraint_statements():
        session.run(cypher)
