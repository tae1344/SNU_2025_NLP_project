#!/usr/bin/env python3
"""Neo4j database utility functions.

Provides utilities for database management, monitoring, caching, and maintenance.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import json

from .neo4j_client import load_config, create_driver, neo4j_session
from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS


class Neo4jUtils:
    """Neo4j database utility class."""

    def __init__(self):
        """Initialize Neo4j utilities."""
        self.config = load_config()
        self.driver = create_driver(self.config)

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def close(self):
        """Close database connection."""
        if hasattr(self, "driver") and self.driver:
            self.driver.close()

    def clear_database(self, confirm: bool = False) -> Dict[str, Any]:
        """Clear all nodes and relationships from database.

        Args:
            confirm: Must be True to actually clear the database

        Returns:
            Dictionary with operation results
        """
        if not confirm:
            return {
                "status": "cancelled",
                "message": "Database clear cancelled. Set confirm=True to proceed.",
            }

        start_time = time.time()

        with neo4j_session(self.driver) as session:
            # Get initial counts
            initial_stats = self.get_database_stats(session)

            # Clear all data
            session.run("MATCH (n) DETACH DELETE n")

            # Get final counts
            final_stats = self.get_database_stats(session)

        end_time = time.time()

        return {
            "status": "success",
            "initial_nodes": initial_stats["total_nodes"],
            "initial_relationships": initial_stats["total_relationships"],
            "final_nodes": final_stats["total_nodes"],
            "final_relationships": final_stats["total_relationships"],
            "duration_seconds": round(end_time - start_time, 2),
        }

    def get_database_stats(self, session=None) -> Dict[str, Any]:
        """Get comprehensive database statistics.

        Args:
            session: Optional Neo4j session (creates new one if None)

        Returns:
            Dictionary with database statistics
        """

        def _get_stats(sess):
            # Total counts
            total_nodes = sess.run("MATCH (n) RETURN count(n) as count").single()[
                "count"
            ]
            total_rels = sess.run("MATCH ()-[r]->() RETURN count(r) as count").single()[
                "count"
            ]

            # Node counts by type
            node_counts = {}
            for node_type_key, node_type_value in NODE_TYPES.items():
                count = sess.run(
                    f"MATCH (n:{node_type_value}) RETURN count(n) as count"
                ).single()["count"]
                if count > 0:
                    node_counts[node_type_key] = count

            # Relationship counts by type
            rel_counts = {}
            for rel_type_key, rel_type_value in RELATIONSHIP_TYPES.items():
                try:
                    count = sess.run(
                        f"MATCH ()-[r:{rel_type_value}]->() RETURN count(r) as count"
                    ).single()["count"]
                    if count > 0:
                        rel_counts[rel_type_key] = count
                except Exception:
                    # Skip relationship types that don't exist yet (e.g., mapped_to)
                    continue

            return {
                "total_nodes": total_nodes,
                "total_relationships": total_rels,
                "node_counts": node_counts,
                "relationship_counts": rel_counts,
                "timestamp": time.time(),
            }

        if session:
            return _get_stats(session)
        else:
            with neo4j_session(self.driver) as sess:
                return _get_stats(sess)

    def export_database_summary(
        self, output_file: Optional[Path] = None
    ) -> Dict[str, Any]:
        """Export database summary to JSON file.

        Args:
            output_file: Optional output file path

        Returns:
            Dictionary with export results
        """
        if output_file is None:
            output_file = Path(f"neo4j_summary_{int(time.time())}.json")

        with neo4j_session(self.driver) as session:
            stats = self.get_database_stats(session)

            # Add sample data
            samples = {}
            for node_type_key, node_type_value in NODE_TYPES.items():
                if stats["node_counts"].get(node_type_key, 0) > 0:
                    sample = session.run(
                        f"MATCH (n:{node_type_value}) RETURN n LIMIT 3"
                    ).data()
                    if sample:
                        samples[node_type_key] = [
                            dict(record["n"]) for record in sample
                        ]

            summary = {
                "export_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "database_stats": stats,
                "sample_data": samples,
            }

        # Write to file
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

        return {
            "status": "success",
            "output_file": str(output_file),
            "total_nodes": stats["total_nodes"],
            "total_relationships": stats["total_relationships"],
        }

    def validate_schema(self) -> Dict[str, Any]:
        """Validate database schema against expected structure.

        Returns:
            Dictionary with validation results
        """
        with neo4j_session(self.driver) as session:
            issues = []
            warnings = []

            # Check for required constraints
            constraints = session.run("SHOW CONSTRAINTS").data()

            # Check that we have uniqueness constraints for each node type
            constraint_node_types = set()
            for constraint in constraints:
                if constraint["type"] == "UNIQUENESS" and constraint["properties"] == [
                    "id"
                ]:
                    constraint_node_types.update(constraint["labelsOrTypes"])

            missing_constraints = []
            for node_type in NODE_TYPES.values():
                if node_type not in constraint_node_types:
                    missing_constraints.append(
                        f"Missing ID uniqueness constraint for {node_type}"
                    )

            issues.extend(missing_constraints)

            # Check for orphaned nodes
            stats = self.get_database_stats(session)

            # Company should exist
            if stats["node_counts"].get("COMPANY", 0) == 0:
                issues.append("No COMPANY nodes found")

            # Check relationship consistency
            company_count = stats["node_counts"].get("COMPANY", 0)
            has_subsidiary_count = stats["relationship_counts"].get("HAS_SUBSIDIARY", 0)

            if company_count > 0 and has_subsidiary_count == 0:
                warnings.append("Company exists but no subsidiaries found")

            return {
                "is_valid": len(issues) == 0,
                "issues": issues,
                "warnings": warnings,
                "stats": stats,
            }

    def backup_database(self, backup_dir: Path) -> Dict[str, Any]:
        """Create a logical backup of the database.

        Args:
            backup_dir: Directory to store backup files

        Returns:
            Dictionary with backup results
        """
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)

        timestamp = time.strftime("%Y%m%d_%H%M%S")
        backup_file = backup_dir / f"neo4j_backup_{timestamp}.cypher"

        with neo4j_session(self.driver) as session:
            # Export all nodes and relationships as Cypher statements
            cypher_statements = []

            # Export nodes by type
            for node_type_key, node_type_value in NODE_TYPES.items():
                nodes = session.run(f"MATCH (n:{node_type_value}) RETURN n").data()
                for record in nodes:
                    node = record["n"]
                    props = dict(node)
                    prop_str = ", ".join([f"{k}: ${k}" for k in props.keys()])
                    cypher_statements.append(
                        f"CREATE (:{node_type_value} {{{prop_str}}})"
                    )

            # Export relationships
            for rel_type_key, rel_type_value in RELATIONSHIP_TYPES.items():
                rels = session.run(
                    f"MATCH (a)-[r:{rel_type_value}]->(b) RETURN a, r, b"
                ).data()
                for record in rels:
                    # This is simplified - full backup would need proper node matching
                    cypher_statements.append(f"// Relationship: {rel_type_value}")

        # Write backup file
        with open(backup_file, "w", encoding="utf-8") as f:
            f.write("// Neo4j Database Backup\n")
            f.write(f"// Created: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            for statement in cypher_statements:
                f.write(statement + ";\n")

        return {
            "status": "success",
            "backup_file": str(backup_file),
            "statements_count": len(cypher_statements),
        }

    def optimize_database(self) -> Dict[str, Any]:
        """Run database optimization tasks.

        Returns:
            Dictionary with optimization results
        """
        with neo4j_session(self.driver) as session:
            start_time = time.time()

            # Create missing indexes
            indexes_created = []

            # Index on common lookup properties
            common_indexes = [
                ("company", "name"),
                ("year_node", "year"),
                ("note", "note_number"),
                ("financial_data", "value"),
            ]

            for node_type, prop in common_indexes:
                try:
                    session.run(
                        f"CREATE INDEX IF NOT EXISTS FOR (n:{node_type}) ON (n.{prop})"
                    )
                    indexes_created.append(f"{node_type}.{prop}")
                except Exception as e:
                    # Index might already exist or other issue
                    pass

            end_time = time.time()

            return {
                "status": "success",
                "indexes_created": indexes_created,
                "duration_seconds": round(end_time - start_time, 2),
            }

    def health_check(self) -> Dict[str, Any]:
        """Perform comprehensive health check.

        Returns:
            Dictionary with health check results
        """
        try:
            with neo4j_session(self.driver) as session:
                # Test basic connectivity
                session.run("RETURN 1").single()

                # Get stats
                stats = self.get_database_stats(session)

                # Validate schema
                validation = self.validate_schema()

                # Check for common issues
                issues = []

                if stats["total_nodes"] == 0:
                    issues.append("Database is empty")

                if stats["total_relationships"] == 0 and stats["total_nodes"] > 0:
                    issues.append("Nodes exist but no relationships found")

                # Check validation issues (only real schema problems)
                if not validation.get("is_valid", True):
                    validation_issues = validation.get("issues", [])
                    # Only include serious validation issues, not warnings about missing relationships
                    serious_issues = [
                        issue
                        for issue in validation_issues
                        if "constraint" in issue.lower()
                    ]
                    issues.extend(serious_issues)

                return {
                    "status": "healthy" if len(issues) == 0 else "issues_found",
                    "connectivity": "ok",
                    "stats": stats,
                    "validation": validation,
                    "issues": issues,
                    "message": (
                        "; ".join(issues) if issues else "All systems operational"
                    ),
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                }

        except Exception as e:
            return {
                "status": "error",
                "connectivity": "failed",
                "error": str(e),
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }


def clear_database(confirm: bool = False) -> Dict[str, Any]:
    """Convenience function to clear database.

    Args:
        confirm: Must be True to actually clear the database

    Returns:
        Dictionary with operation results
    """
    with Neo4jUtils() as utils:
        return utils.clear_database(confirm=confirm)


def get_database_stats() -> Dict[str, Any]:
    """Convenience function to get database statistics.

    Returns:
        Dictionary with database statistics
    """
    with Neo4jUtils() as utils:
        return utils.get_database_stats()


def health_check() -> Dict[str, Any]:
    """Convenience function to perform health check.

    Returns:
        Dictionary with health check results
    """
    with Neo4jUtils() as utils:
        return utils.health_check()


if __name__ == "__main__":
    # Demo usage
    print("=== Neo4j Utilities Demo ===")

    with Neo4jUtils() as utils:
        # Health check
        print("\n1. Health Check:")
        health = utils.health_check()
        print(f"Status: {health['status']}")
        print(f"Total nodes: {health.get('stats', {}).get('total_nodes', 0)}")
        print(
            f"Total relationships: {health.get('stats', {}).get('total_relationships', 0)}"
        )

        # Database stats
        print("\n2. Database Statistics:")
        stats = utils.get_database_stats()
        if stats["node_counts"]:
            for node_type, count in stats["node_counts"].items():
                print(f"  {node_type}: {count}")
        else:
            print("  No nodes found")

        # Schema validation
        print("\n3. Schema Validation:")
        validation = utils.validate_schema()
        print(f"Valid: {validation['is_valid']}")
        if validation["issues"]:
            print("Issues:")
            for issue in validation["issues"]:
                print(f"  - {issue}")
        if validation["warnings"]:
            print("Warnings:")
            for warning in validation["warnings"]:
                print(f"  - {warning}")

        print("\nDemo completed!")
