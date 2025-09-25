# graph_conn.py
import os
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
from typing import List, Dict, Any, Optional
import json

load_dotenv(Path(__file__).with_name("local.env"))


class EnhancedNeo4jGraph:
    """Enhanced Neo4j graph class with advanced financial analysis capabilities"""

    def __init__(self, url: str, username: str, password: str, database: str = "neo4j"):
        self.driver = GraphDatabase.driver(url, auth=(username, password))
        self.database = database
        self._schema = None
        self._node_counts = None
        self._relationship_counts = None

    def query(self, cypher: str, parameters: Dict = None) -> List[Dict]:
        """Cypher 쿼리 실행"""
        with self.driver.session(database=self.database) as session:
            result = session.run(cypher, parameters or {})
            return [record.data() for record in result]

    def get_schema(self) -> str:
        """Enhanced schema information extraction"""
        if self._schema is None:
            self._schema = self._build_enhanced_schema()
        return self._schema

    def get_node_counts(self) -> Dict[str, int]:
        """Get node counts for all labels"""
        if self._node_counts is None:
            self._node_counts = self._get_node_counts()
        return self._node_counts

    def get_relationship_counts(self) -> Dict[str, int]:
        """Get relationship counts for all types"""
        if self._relationship_counts is None:
            self._relationship_counts = self._get_relationship_counts()
        return self._relationship_counts

    def _get_node_counts(self) -> Dict[str, int]:
        """Get node counts efficiently"""
        try:
            result = self.query("CALL db.labels()")
            labels = [
                record.get("label", "") for record in result if record.get("label")
            ]

            counts = {}
            for label in labels:
                try:
                    count_result = self.query(
                        f"MATCH (n:{label}) RETURN count(n) as count"
                    )
                    counts[label] = (
                        count_result[0].get("count", 0) if count_result else 0
                    )
                except:
                    counts[label] = 0
            return counts
        except:
            return {}

    def _get_relationship_counts(self) -> Dict[str, int]:
        """Get relationship counts efficiently"""
        try:
            result = self.query("CALL db.relationshipTypes()")
            rel_types = [
                record.get("relationshipType", "")
                for record in result
                if record.get("relationshipType")
            ]

            counts = {}
            for rel_type in rel_types:
                try:
                    count_result = self.query(
                        f"MATCH ()-[r:{rel_type}]->() RETURN count(r) as count"
                    )
                    counts[rel_type] = (
                        count_result[0].get("count", 0) if count_result else 0
                    )
                except:
                    counts[rel_type] = 0
            return counts
        except:
            return {}

    def get_financial_analysis_data(
        self, year: Optional[int] = None, section_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """Get comprehensive financial analysis data"""
        where_clauses = []
        if year:
            where_clauses.append(f"fd.year = {year}")
        if section_code:
            where_clauses.append(f"fd.section_code = '{section_code}'")

        where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

        # Get financial data with categories
        financial_data_query = f"""
        MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
        WHERE {where_clause}
        RETURN fd.item_name, fd.section_code, fd.year, fd.values_current, fd.values_previous, 
               fd.category_path, fc.hierarchy_level, fc.parent_path
        ORDER BY fd.year DESC, fd.section_code, fc.hierarchy_level
        LIMIT 100
        """

        # Get trend analysis
        trend_query = f"""
        MATCH (fd1:financial_data), (fd2:financial_data)
        WHERE fd1.item_name = fd2.item_name 
        AND fd1.year = fd2.year - 1
        AND {where_clause.replace('fd.', 'fd1.')}
        WITH fd1, fd2, 
             CASE 
               WHEN fd1.values_previous > 0 
               THEN (fd2.values_current - fd1.values_current) / fd1.values_current * 100
               ELSE 0 
             END as growth_rate
        WHERE abs(growth_rate) > 5
        RETURN fd1.item_name, fd1.year, fd1.values_current, fd2.values_current, growth_rate
        ORDER BY abs(growth_rate) DESC
        LIMIT 20
        """

        return {
            "financial_data": self.query(financial_data_query),
            "trends": self.query(trend_query),
        }

    def get_hierarchical_categories(
        self, section_code: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Get hierarchical category structure"""
        where_clause = (
            f"WHERE fc.section_code = '{section_code}'" if section_code else ""
        )

        query = f"""
        MATCH (fc:fs_category)
        {where_clause}
        RETURN fc.name, fc.section_code, fc.hierarchy_level, fc.category_path, 
               fc.parent_path, fc.path_normalized, fc.note_references
        ORDER BY fc.section_code, fc.hierarchy_level, fc.category_path
        """

        return self.query(query)

    def get_subsidiary_relationships(self) -> List[Dict[str, Any]]:
        """Get comprehensive subsidiary relationship data"""
        query = """
        MATCH (c:company)-[r]->(s:subsidiary)
        RETURN c.name as company, s.name as subsidiary, type(r) as relationship_type,
               s.relationship_type, s.ownership_percentage, s.investment_amount,
               s.trade_amount, s.debt_amount
        ORDER BY s.name, type(r)
        """
        return self.query(query)

    def search_notes(
        self, keyword: str, category: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Search notes by keyword and optional category"""
        where_clauses = [
            f"n.content CONTAINS '{keyword}' OR n.title CONTAINS '{keyword}'"
        ]
        if category:
            where_clauses.append(f"n.category = '{category}'")

        query = f"""
        MATCH (n:note)
        WHERE {' AND '.join(where_clauses)}
        RETURN n.note_number, n.title, n.category, n.content
        ORDER BY n.note_number
        LIMIT 50
        """
        return self.query(query)

    def get_financial_summary(self, year: int) -> Dict[str, Any]:
        """Get comprehensive financial summary for a year"""
        # Key financial metrics
        metrics_query = f"""
        MATCH (fd:financial_data)
        WHERE fd.year = {year}
        WITH fd.section_code as section, 
             collect(DISTINCT fd.item_name) as items,
             sum(fd.values_current) as total_current,
             sum(fd.values_previous) as total_previous
        RETURN section, size(items) as item_count, total_current, total_previous,
               CASE WHEN total_previous > 0 
               THEN (total_current - total_previous) / total_previous * 100 
               ELSE 0 END as change_rate
        ORDER BY section
        """

        # Top categories by value
        categories_query = f"""
        MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
        WHERE fd.year = {year}
        WITH fc.category_path as category_path, sum(fd.values_current) as total_value
        ORDER BY total_value DESC
        LIMIT 10
        RETURN category_path, total_value
        """

        return {
            "metrics": self.query(metrics_query),
            "top_categories": self.query(categories_query),
        }

    def _build_enhanced_schema(self) -> str:
        """Enhanced schema with comprehensive financial knowledge graph information"""
        try:
            node_counts = self.get_node_counts()
            rel_counts = self.get_relationship_counts()

            schema_parts = []

            # Enhanced node information
            schema_parts.append("=== SAMSUNG ELECTRONICS FINANCIAL KNOWLEDGE GRAPH ===")
            schema_parts.append("\\nNode labels with counts:")
            for label, count in sorted(
                node_counts.items(), key=lambda x: x[1], reverse=True
            ):
                schema_parts.append(f"  - {label} ({count:,}개)")

            # Enhanced relationship information
            schema_parts.append("\\nRelationship types with counts:")
            for rel_type, count in sorted(
                rel_counts.items(), key=lambda x: x[1], reverse=True
            ):
                schema_parts.append(f"  - {rel_type} ({count:,}개)")

            # Detailed node properties
            schema_parts.append("\\nDetailed node properties:")
            key_labels = [
                "financial_data",
                "fs_category",
                "note",
                "subsidiary",
                "company",
                "year_node",
            ]

            for label in key_labels:
                if label in node_counts and node_counts[label] > 0:
                    try:
                        sample_result = self.query(
                            f"MATCH (n:{label}) RETURN keys(n) as props LIMIT 1"
                        )
                        if sample_result:
                            props = sorted(sample_result[0].get("props", []))
                            schema_parts.append(f"  {label}: {props}")
                    except:
                        pass

            # Financial statement structure
            schema_parts.append("\\nFinancial Statement Structure:")
            schema_parts.append("  BS: 재무상태표 (Balance Sheet) - 자산, 부채, 자본")
            schema_parts.append("  PL: 손익계산서 (Profit & Loss) - 수익, 비용, 이익")
            schema_parts.append("  CF: 현금흐름표 (Cash Flow) - 영업, 투자, 재무활동")
            schema_parts.append("  EQ: 자본변동표 (Equity) - 자본의 변동사항")
            schema_parts.append(
                "  CI: 포괄손익계산서 (Comprehensive Income) - 기타포괄손익"
            )

            # Sample data with enhanced information
            schema_parts.append("\\nSample Financial Data:")
            try:
                result = self.query(
                    """
                    MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                    RETURN fd.item_name, fd.section_code, fd.year, fd.values_current, 
                           fd.category_path, fc.hierarchy_level
                    LIMIT 5
                """
                )
                if result:
                    for record in result:
                        item = record.get("fd.item_name", "N/A")[:25]
                        section = record.get("fd.section_code", "N/A")
                        year = record.get("fd.year", "N/A")
                        value = record.get("fd.values_current", 0)
                        path = record.get("fd.category_path", "N/A")
                        level = record.get("fc.hierarchy_level", "N/A")
                        schema_parts.append(
                            f"    {item} ({section}, {year}): {value:,}원 [L{level}] {path}"
                        )
            except:
                pass

            # Sample categories
            schema_parts.append("\\nSample Category Hierarchy:")
            try:
                result = self.query(
                    """
                    MATCH (fc:fs_category)
                    WHERE fc.hierarchy_level <= 3
                    RETURN fc.name, fc.section_code, fc.hierarchy_level, fc.category_path
                    ORDER BY fc.section_code, fc.hierarchy_level
                    LIMIT 8
                """
                )
                if result:
                    for record in result:
                        name = record.get("fc.name", "N/A")
                        section = record.get("fc.section_code", "N/A")
                        level = record.get("fc.hierarchy_level", "N/A")
                        path = record.get("fc.category_path", "N/A")
                        indent = "  " * (level - 1)
                        schema_parts.append(
                            f"    {indent}{name} ({section}, L{level}) - {path}"
                        )
            except:
                pass

            # Sample subsidiary relationships
            schema_parts.append("\\nSample Subsidiary Relationships:")
            try:
                result = self.query(
                    """
                    MATCH (c:company)-[r]->(s:subsidiary)
                    RETURN c.name, s.name, type(r) as rel_type, s.relationship_type
                    LIMIT 5
                """
                )
                if result:
                    for record in result:
                        company = record.get("c.name", "N/A")
                        subsidiary = record.get("s.name", "N/A")[:30]
                        rel_type = record.get("rel_type", "N/A")
                        sub_type = record.get("s.relationship_type", "N/A")
                        schema_parts.append(
                            f"    {company} -[{rel_type}]-> {subsidiary} ({sub_type})"
                        )
            except:
                pass

            return "\\n".join(schema_parts)

        except Exception as e:
            return f"Enhanced schema extraction failed: {str(e)}"


# Enhanced graph instance
graph = EnhancedNeo4jGraph(
    url=os.getenv("NEO4J_URI"),
    username=os.getenv("NEO4J_USERNAME"),
    password=os.getenv("NEO4J_PASSWORD"),
    database="neo4j",
)
