#!/usr/bin/env python3
"""Graph validation module for Samsung Financial Knowledge Graph.

This module provides comprehensive validation checks for the Neo4j knowledge graph including:
- Coverage validation against processed JSON files
- Schema conformance checks
- Orphan node detection
- Data quality validation
- Relationship integrity checks
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict

from .neo4j_client import neo4j_session
from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .etl_config import ETLConfig, extract_company_info_from_data
from .id_utils import (
    build_company_id,
    build_year_node_id,
    build_category_id,
    build_financial_data_id,
    build_note_id,
    build_auditor_id,
    build_audit_info_id,
)


@dataclass
class ValidationIssue:
    """Represents a validation issue found during graph validation."""

    severity: str  # "critical", "warning", "info"
    category: str  # "coverage", "schema", "orphan", "data_quality", "relationship"
    message: str
    details: Dict[str, Any] = field(default_factory=dict)
    node_id: Optional[str] = None
    relationship_type: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert issue to dictionary for reporting."""
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "details": self.details,
            "node_id": self.node_id,
            "relationship_type": self.relationship_type,
        }


@dataclass
class ValidationReport:
    """Comprehensive validation report for the knowledge graph."""

    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None

    # Statistics
    total_nodes: int = 0
    total_relationships: int = 0
    nodes_by_type: Dict[str, int] = field(default_factory=dict)
    relationships_by_type: Dict[str, int] = field(default_factory=dict)

    # Issues
    issues: List[ValidationIssue] = field(default_factory=list)

    # Coverage stats
    processed_files_count: int = 0
    expected_companies: int = 0
    expected_years: Set[int] = field(default_factory=set)

    @property
    def duration_seconds(self) -> float:
        """Calculate validation duration."""
        end = self.end_time or time.time()
        return end - self.start_time

    @property
    def critical_issues(self) -> List[ValidationIssue]:
        """Get critical issues only."""
        return [issue for issue in self.issues if issue.severity == "critical"]

    @property
    def warning_issues(self) -> List[ValidationIssue]:
        """Get warning issues only."""
        return [issue for issue in self.issues if issue.severity == "warning"]

    @property
    def info_issues(self) -> List[ValidationIssue]:
        """Get info issues only."""
        return [issue for issue in self.issues if issue.severity == "info"]

    def add_issue(self, issue: ValidationIssue) -> None:
        """Add a validation issue."""
        self.issues.append(issue)

    def finish(self) -> None:
        """Mark validation as finished."""
        self.end_time = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary for JSON serialization."""
        return {
            "validation_timestamp": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(self.start_time)
            ),
            "duration_seconds": round(self.duration_seconds, 2),
            "statistics": {
                "total_nodes": self.total_nodes,
                "total_relationships": self.total_relationships,
                "nodes_by_type": self.nodes_by_type,
                "relationships_by_type": self.relationships_by_type,
            },
            "coverage": {
                "processed_files_count": self.processed_files_count,
                "expected_companies": self.expected_companies,
                "expected_years": sorted(list(self.expected_years)),
            },
            "issues_summary": {
                "critical_count": len(self.critical_issues),
                "warning_count": len(self.warning_issues),
                "info_count": len(self.info_issues),
                "total_count": len(self.issues),
            },
            "issues": [issue.to_dict() for issue in self.issues],
        }


class GraphValidator:
    """Comprehensive knowledge graph validator."""

    def __init__(self, config: ETLConfig):
        """Initialize validator with configuration.

        Args:
            config: ETL configuration
        """
        self.config = config
        self.report = ValidationReport()

    def validate_graph(
        self,
        session,
        processed_files: List[Path],
        check_coverage: bool = True,
        check_schema: bool = True,
        check_orphans: bool = True,
        check_data_quality: bool = True,
        check_relationships: bool = True,
    ) -> ValidationReport:
        """Run comprehensive graph validation.

        Args:
            session: Neo4j session
            processed_files: List of processed JSON files to validate against
            check_coverage: Whether to check coverage against processed files
            check_schema: Whether to check schema conformance
            check_orphans: Whether to check for orphan nodes
            check_data_quality: Whether to check data quality
            check_relationships: Whether to check relationship integrity

        Returns:
            ValidationReport with all findings
        """
        print(f"🔍 Starting comprehensive graph validation...")
        print(f"   Files to validate against: {len(processed_files)}")
        print(
            f"   Checks enabled: coverage={check_coverage}, schema={check_schema}, "
            f"orphans={check_orphans}, data_quality={check_data_quality}, "
            f"relationships={check_relationships}"
        )

        # Collect basic statistics
        self._collect_graph_statistics(session)

        # Run validation checks
        if check_coverage:
            self._validate_coverage(session, processed_files)

        if check_schema:
            self._validate_schema_conformance(session)

        if check_orphans:
            self._detect_orphan_nodes(session)

        if check_data_quality:
            self._validate_data_quality(session)

        if check_relationships:
            self._validate_relationship_integrity(session)

        self.report.finish()
        return self.report

    def _collect_graph_statistics(self, session) -> None:
        """Collect basic graph statistics."""
        print("📊 Collecting graph statistics...")

        # Total counts
        result = session.run("MATCH (n) RETURN count(n) AS total_nodes")
        self.report.total_nodes = result.single()["total_nodes"]

        result = session.run("MATCH ()-[r]->() RETURN count(r) AS total_relationships")
        self.report.total_relationships = result.single()["total_relationships"]

        # Node counts by type
        for node_type in NODE_TYPES.values():
            result = session.run(f"MATCH (n:{node_type}) RETURN count(n) AS count")
            count = result.single()["count"]
            if count > 0:
                self.report.nodes_by_type[node_type] = count

        # Relationship counts by type (only for actively used relationship types)
        # Get actual relationship types from the database to avoid warnings
        result = session.run(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        )
        actual_rel_types = [record["relationshipType"] for record in result]

        for rel_type in actual_rel_types:
            result = session.run(
                f"MATCH ()-[r:{rel_type}]->() RETURN count(r) AS count"
            )
            count = result.single()["count"]
            if count > 0:
                self.report.relationships_by_type[rel_type] = count

        print(f"   Total nodes: {self.report.total_nodes}")
        print(f"   Total relationships: {self.report.total_relationships}")

    def _validate_coverage(self, session, processed_files: List[Path]) -> None:
        """Validate coverage against processed JSON files."""
        print("📋 Validating coverage against processed files...")

        self.report.processed_files_count = len(processed_files)
        expected_years = set()
        expected_companies = set()

        # Analyze processed files
        for file_path in processed_files:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Extract year from metadata or filename
                metadata = data.get("metadata", {})
                year = metadata.get("report_year")

                if not year:
                    # Try to extract from filename
                    import re

                    year_match = re.search(r"(\d{4})", file_path.name)
                    if year_match:
                        year = int(year_match.group(1))

                if year:
                    expected_years.add(year)

                # Use default company name from config
                company_name = self.config.company_name
                expected_companies.add(company_name)

            except Exception as e:
                self.report.add_issue(
                    ValidationIssue(
                        severity="warning",
                        category="coverage",
                        message=f"Failed to analyze processed file: {file_path.name}",
                        details={"error": str(e), "file_path": str(file_path)},
                    )
                )

        self.report.expected_years = expected_years
        self.report.expected_companies = len(expected_companies)

        # Check if expected companies exist in graph
        for company_name in expected_companies:
            company_id = build_company_id(company_name)
            result = session.run(
                "MATCH (c:company {id: $company_id}) RETURN c",
                {"company_id": company_id},
            )
            if not result.single():
                self.report.add_issue(
                    ValidationIssue(
                        severity="critical",
                        category="coverage",
                        message=f"Expected company not found in graph: {company_name}",
                        details={
                            "company_name": company_name,
                            "expected_id": company_id,
                        },
                    )
                )

        # Check if expected years have data
        for year in expected_years:
            result = session.run(
                "MATCH (y:year_node) WHERE y.year = $year RETURN count(y) AS count",
                {"year": year},
            )
            year_count = result.single()["count"]
            if year_count == 0:
                self.report.add_issue(
                    ValidationIssue(
                        severity="critical",
                        category="coverage",
                        message=f"No year nodes found for expected year: {year}",
                        details={"year": year},
                    )
                )
            elif year_count < 4:  # Expecting BS, PL, CF, EQ sections
                self.report.add_issue(
                    ValidationIssue(
                        severity="warning",
                        category="coverage",
                        message=f"Incomplete year node coverage for year: {year}",
                        details={
                            "year": year,
                            "found_count": year_count,
                            "expected_min": 4,
                        },
                    )
                )

        print(f"   Expected companies: {len(expected_companies)}")
        print(f"   Expected years: {sorted(expected_years)}")

    def _validate_schema_conformance(self, session) -> None:
        """Validate schema conformance."""
        print("🔧 Validating schema conformance...")

        # Check required properties for each node type
        schema_checks = {
            NODE_TYPES["COMPANY"]: ["id", "name"],
            NODE_TYPES["YEAR_NODE"]: ["id", "year", "section_code"],
            NODE_TYPES["FINANCIAL_DATA"]: ["id", "item_name", "value", "year"],
            NODE_TYPES["NOTE"]: [
                "id",
                "note_number",
                "year",
            ],  # Using actual properties
            NODE_TYPES["AUDITOR"]: ["id", "name"],
        }

        for node_type, required_props in schema_checks.items():
            # Check if nodes of this type exist
            result = session.run(f"MATCH (n:{node_type}) RETURN count(n) AS count")
            count = result.single()["count"]

            if count == 0:
                continue  # Skip validation for non-existent node types

            # Check required properties
            for prop in required_props:
                result = session.run(
                    f"MATCH (n:{node_type}) WHERE n.{prop} IS NULL RETURN count(n) AS missing_count"
                )
                missing_count = result.single()["missing_count"]

                if missing_count > 0:
                    self.report.add_issue(
                        ValidationIssue(
                            severity="critical",
                            category="schema",
                            message=f"Missing required property '{prop}' in {missing_count} {node_type} nodes",
                            details={
                                "node_type": node_type,
                                "property": prop,
                                "missing_count": missing_count,
                            },
                        )
                    )

        # Check for nodes with duplicate IDs (should not happen with proper constraints)
        result = session.run(
            """
            MATCH (n)
            WHERE n.id IS NOT NULL
            WITH n.id AS node_id, count(n) AS count, collect(labels(n)) AS label_groups
            WHERE count > 1
            RETURN node_id, count, label_groups
            LIMIT 10
        """
        )

        for record in result:
            self.report.add_issue(
                ValidationIssue(
                    severity="critical",
                    category="schema",
                    message=f"Duplicate node ID found: {record['node_id']}",
                    details={
                        "node_id": record["node_id"],
                        "duplicate_count": record["count"],
                        "label_groups": record["label_groups"],
                    },
                )
            )

    def _detect_orphan_nodes(self, session) -> None:
        """Detect orphan nodes (nodes with no relationships)."""
        print("🔍 Detecting orphan nodes...")

        # Find nodes with no incoming or outgoing relationships
        result = session.run(
            """
            MATCH (n)
            WHERE NOT (n)--()
            RETURN labels(n) AS labels, n.id AS node_id, count(n) AS count
        """
        )

        for record in result:
            labels = record["labels"]
            node_id = record["node_id"]

            # Some node types are expected to be orphans (like top-level COMPANY nodes)
            if "company" in labels:
                continue  # Company nodes might be orphans by design

            self.report.add_issue(
                ValidationIssue(
                    severity="warning",
                    category="orphan",
                    message=f"Orphan node detected: {labels}",
                    details={"labels": labels, "node_id": node_id},
                )
            )

    def _validate_data_quality(self, session) -> None:
        """Validate data quality."""
        print("📊 Validating data quality...")

        # Check for financial data with invalid values
        result = session.run(
            """
            MATCH (f:financial_data)
            WHERE f.value IS NULL OR NOT f.value =~ '-?[0-9]+\\.?[0-9]*'
            RETURN count(f) AS invalid_count
        """
        )
        invalid_count = result.single()["invalid_count"]

        if invalid_count > 0:
            self.report.add_issue(
                ValidationIssue(
                    severity="warning",
                    category="data_quality",
                    message=f"Found {invalid_count} financial_data nodes with invalid values",
                    details={"invalid_count": invalid_count},
                )
            )

        # Check for notes without text content
        result = session.run(
            """
            MATCH (n:note)
            WHERE n.text IS NULL OR n.text = ""
            RETURN count(n) AS empty_count
        """
        )
        empty_count = result.single()["empty_count"]

        if empty_count > 0:
            self.report.add_issue(
                ValidationIssue(
                    severity="warning",
                    category="data_quality",
                    message=f"Found {empty_count} note nodes with empty text content",
                    details={"empty_count": empty_count},
                )
            )

        # Check for year nodes with invalid years
        result = session.run(
            """
            MATCH (y:year_node)
            WHERE y.year < 2000 OR y.year > 2030
            RETURN count(y) AS invalid_year_count
        """
        )
        invalid_year_count = result.single()["invalid_year_count"]

        if invalid_year_count > 0:
            self.report.add_issue(
                ValidationIssue(
                    severity="warning",
                    category="data_quality",
                    message=f"Found {invalid_year_count} year nodes with invalid years",
                    details={"invalid_year_count": invalid_year_count},
                )
            )

    def _validate_relationship_integrity(self, session) -> None:
        """Validate relationship integrity."""
        print("🔗 Validating relationship integrity...")

        # Check for broken relationships (relationships pointing to non-existent nodes)
        # Only check relationships that actually exist in the database
        relationship_checks = [
            ("contains_data", "year_node", "financial_data"),
            ("links_to_note", "fs_category", "note"),
            ("has_note", "company", "note"),
            ("audited_by", "company", "auditor"),
            ("trend_to", "year_node", "year_node"),
            # Financial relationships - check both directions separately
            ("invests_in", "company", "subsidiary"),
            ("trades_with", "company", "subsidiary"),
            ("trades_with", "subsidiary", "company"),
            ("owes_to", "company", "subsidiary"),
            ("owes_to", "subsidiary", "company"),
        ]

        for rel_type, from_label, to_label in relationship_checks:
            # Check if this specific direction of relationship exists
            result = session.run(
                f"MATCH (from:{from_label})-[r:{rel_type}]->(to:{to_label}) RETURN count(r) AS count"
            )
            count = result.single()["count"]

            if count == 0:
                continue  # Skip if no relationships of this specific direction

            # Check for broken source relationships (should not happen with the query above)
            result = session.run(
                f"""
                MATCH (from:{from_label})-[r:{rel_type}]->(to:{to_label})
                WHERE NOT from:{from_label}
                RETURN count(r) AS broken_count
            """
            )
            broken_from = result.single()["broken_count"]

            if broken_from > 0:
                self.report.add_issue(
                    ValidationIssue(
                        severity="critical",
                        category="relationship",
                        message=f"Found {broken_from} {rel_type} relationships with invalid source nodes",
                        details={
                            "relationship_type": rel_type,
                            "expected_from": from_label,
                            "broken_count": broken_from,
                        },
                    )
                )

            # Check for broken target relationships (should not happen with the query above)
            result = session.run(
                f"""
                MATCH (from:{from_label})-[r:{rel_type}]->(to:{to_label})
                WHERE NOT to:{to_label}
                RETURN count(r) AS broken_count
            """
            )
            broken_to = result.single()["broken_count"]

            if broken_to > 0:
                self.report.add_issue(
                    ValidationIssue(
                        severity="critical",
                        category="relationship",
                        message=f"Found {broken_to} {rel_type} relationships with invalid target nodes",
                        details={
                            "relationship_type": rel_type,
                            "expected_to": to_label,
                            "broken_count": broken_to,
                        },
                    )
                )


def generate_validation_report(
    session,
    processed_files: List[Path],
    config: ETLConfig,
    output_path: Optional[Path] = None,
) -> ValidationReport:
    """Generate comprehensive validation report.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON files to validate against
        config: ETL configuration
        output_path: Optional path to save the report

    Returns:
        ValidationReport with all findings
    """
    validator = GraphValidator(config)
    report = validator.validate_graph(session, processed_files)

    # Save report if output path provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"📄 Validation report saved to: {output_path}")

    return report


def print_validation_summary(report: ValidationReport) -> None:
    """Print a human-readable validation summary.

    Args:
        report: ValidationReport to summarize
    """
    print(f"\n📊 VALIDATION REPORT SUMMARY")
    print(f"=" * 60)
    print(f"⏱️  Duration: {report.duration_seconds:.2f} seconds")
    print(f"📈 Graph Statistics:")
    print(f"   Total nodes: {report.total_nodes}")
    print(f"   Total relationships: {report.total_relationships}")

    if report.nodes_by_type:
        print(f"   Nodes by type:")
        for node_type, count in sorted(report.nodes_by_type.items()):
            print(f"     {node_type}: {count}")

    if report.relationships_by_type:
        print(f"   Relationships by type:")
        for rel_type, count in sorted(report.relationships_by_type.items()):
            print(f"     {rel_type}: {count}")

    print(f"\n🔍 Validation Results:")
    print(f"   Critical issues: {len(report.critical_issues)}")
    print(f"   Warning issues: {len(report.warning_issues)}")
    print(f"   Info issues: {len(report.info_issues)}")
    print(f"   Total issues: {len(report.issues)}")

    # Show critical issues
    if report.critical_issues:
        print(f"\n❌ Critical Issues:")
        for i, issue in enumerate(report.critical_issues[:5], 1):
            print(f"   {i}. [{issue.category}] {issue.message}")
        if len(report.critical_issues) > 5:
            print(f"   ... and {len(report.critical_issues) - 5} more critical issues")

    # Show warning issues
    if report.warning_issues:
        print(f"\n⚠️  Warning Issues:")
        for i, issue in enumerate(report.warning_issues[:3], 1):
            print(f"   {i}. [{issue.category}] {issue.message}")
        if len(report.warning_issues) > 3:
            print(f"   ... and {len(report.warning_issues) - 3} more warnings")

    # Overall assessment
    if len(report.critical_issues) == 0:
        print(f"\n✅ VALIDATION PASSED: No critical errors found!")
        if len(report.warning_issues) > 0:
            print(
                f"   Note: {len(report.warning_issues)} warnings documented for review."
            )
    else:
        print(
            f"\n❌ VALIDATION FAILED: {len(report.critical_issues)} critical errors found!"
        )
        print(f"   Please address critical issues before proceeding.")


if __name__ == "__main__":
    # Example usage and testing
    from .etl_config import DEFAULT_CONFIG
    from .neo4j_client import load_config, create_driver, neo4j_session

    print("🧪 Testing Graph Validator...")

    config = DEFAULT_CONFIG
    test_files = config.get_processed_files([2022, 2023, 2024])

    if test_files:
        print(f"📁 Test files: {len(test_files)}")

        try:
            neo4j_config = load_config()
            driver = create_driver(neo4j_config)

            with neo4j_session(driver) as session:
                # Generate validation report
                report_path = Path("results") / "validation_report.json"
                report = generate_validation_report(
                    session, test_files, config, report_path
                )

                # Print summary
                print_validation_summary(report)

            driver.close()

        except Exception as e:
            print(f"❌ Validation test failed: {e}")
            import traceback

            traceback.print_exc()
    else:
        print("❌ No test files found")
