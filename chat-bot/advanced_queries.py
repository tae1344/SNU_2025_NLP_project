# advanced_queries.py
# Advanced query templates for Samsung Electronics financial analysis

from typing import Dict, List, Any, Optional
from dataclasses import dataclass


@dataclass
class QueryTemplate:
    """Query template with parameters and description"""

    name: str
    description: str
    cypher: str
    parameters: List[str]
    example_usage: str


class AdvancedFinancialQueries:
    """Advanced financial analysis query templates"""

    def __init__(self):
        self.templates = self._initialize_templates()

    def _initialize_templates(self) -> Dict[str, QueryTemplate]:
        """Initialize advanced query templates"""
        return {
            "hierarchical_balance_sheet": QueryTemplate(
                name="계층적 재무상태표 분석",
                description="재무상태표의 계층적 구조를 분석하여 자산, 부채, 자본의 세부 구성을 보여줍니다.",
                cypher="""
                MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                WHERE fd.section_code = 'BS' AND fd.year = {year}
                WITH fc.hierarchy_level as level, fc.name as category, fc.category_path as path, 
                     sum(fd.values_current) as total_value,
                     count(fd) as item_count
                ORDER BY level, total_value DESC
                RETURN level, category, path, total_value, item_count
                """,
                parameters=["year"],
                example_usage="2024년 재무상태표의 계층적 구조를 분석해주세요",
            ),
            "profit_loss_analysis": QueryTemplate(
                name="손익계산서 분석",
                description="손익계산서의 주요 항목들을 분석하여 수익과 비용 구조를 보여줍니다.",
                cypher="""
                MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                WHERE fd.section_code = 'PL' AND fd.year = {year}
                WITH fc.hierarchy_level as level, fc.name as category, fc.category_path as path,
                     sum(fd.values_current) as total_value
                ORDER BY level, total_value DESC
                RETURN level, category, path, total_value
                """,
                parameters=["year"],
                example_usage="2024년 손익계산서의 주요 항목들을 분석해주세요",
            ),
            "cash_flow_analysis": QueryTemplate(
                name="현금흐름표 분석",
                description="현금흐름표의 영업, 투자, 재무활동 현금흐름을 분석합니다.",
                cypher="""
                MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                WHERE fd.section_code = 'CF' AND fd.year = {year}
                WITH fc.hierarchy_level as level, fc.name as category, fc.category_path as path,
                     sum(fd.values_current) as total_value
                ORDER BY level, total_value DESC
                RETURN level, category, path, total_value
                """,
                parameters=["year"],
                example_usage="2024년 현금흐름표의 활동별 현금흐름을 분석해주세요",
            ),
            "year_over_year_growth": QueryTemplate(
                name="연도별 성장률 분석",
                description="특정 재무 항목의 연도별 성장률을 계산하여 변화 추이를 분석합니다.",
                cypher="""
                MATCH (fd1:financial_data), (fd2:financial_data)
                WHERE fd1.item_name = fd2.item_name 
                AND fd1.year = {year1} AND fd2.year = {year2}
                AND fd1.section_code = '{section}'
                WITH fd1, fd2, 
                     CASE 
                       WHEN fd1.values_current > 0 
                       THEN (fd2.values_current - fd1.values_current) / fd1.values_current * 100
                       ELSE 0 
                     END as growth_rate
                WHERE abs(growth_rate) > {min_growth}
                RETURN fd1.item_name as item, fd1.values_current as prev_value,
                       fd2.values_current as curr_value, growth_rate
                ORDER BY abs(growth_rate) DESC
                LIMIT {limit}
                """,
                parameters=["year1", "year2", "section", "min_growth", "limit"],
                example_usage="2023년과 2024년 재무상태표 항목들의 성장률을 분석해주세요",
            ),
            "subsidiary_relationship_analysis": QueryTemplate(
                name="종속기업 관계 분석",
                description="삼성전자와 종속기업들 간의 다양한 관계를 종합적으로 분석합니다.",
                cypher="""
                MATCH (c:company)-[:has_subsidiary]->(s:subsidiary)
                OPTIONAL MATCH (c)-[r1:invests_in]->(s)
                OPTIONAL MATCH (c)-[r2:trades_with]->(s)
                OPTIONAL MATCH (c)-[r3:owes_to]->(s)
                OPTIONAL MATCH (c)-[r4:guarantees_for]->(s)
                WITH c, s, 
                     collect(DISTINCT CASE 
                       WHEN r1 IS NOT NULL THEN '투자'
                       WHEN r2 IS NOT NULL THEN '거래'
                       WHEN r3 IS NOT NULL THEN '채무'
                       WHEN r4 IS NOT NULL THEN '보증'
                     END) as relationships,
                     s.ownership_percentage as ownership, s.investment_amount as investment, 
                     s.trade_amount as trade, s.debt_amount as debt
                WHERE size(relationships) > 0
                RETURN c.name as company, s.name as subsidiary, relationships,
                       ownership, investment, trade, debt
                ORDER BY size(relationships) DESC, s.name
                """,
                parameters=[],
                example_usage="삼성전자와 종속기업들 간의 모든 관계를 분석해주세요",
            ),
            "financial_notes_analysis": QueryTemplate(
                name="재무 주석 분석",
                description="재무 데이터와 연결된 주석들을 분석하여 상세 정보를 제공합니다.",
                cypher="""
                MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                OPTIONAL MATCH (fd)-[:links_to_note]->(n:note)
                WHERE fd.section_code = '{section}' AND fd.year = {year}
                WITH fd, fc, collect(n) as notes
                WHERE size(notes) > 0
                UNWIND notes as note
                RETURN fd.item_name as item, fc.category_path as category,
                       collect(note.note_number) as note_numbers,
                       collect(note.title) as note_titles,
                       fd.values_current as current_value
                ORDER BY fd.values_current DESC
                LIMIT {limit}
                """,
                parameters=["section", "year", "limit"],
                example_usage="2024년 재무상태표에서 주석이 있는 주요 항목들을 분석해주세요",
            ),
            "category_value_ranking": QueryTemplate(
                name="카테고리별 가치 순위",
                description="특정 재무제표 섹션의 카테고리별 총액을 순위별로 보여줍니다.",
                cypher="""
                MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                WHERE fd.section_code = '{section}' AND fd.year = {year}
                WITH fc.hierarchy_level as level, fc.name as category, fc.category_path as path,
                     sum(fd.values_current) as total_value,
                     count(fd) as item_count,
                     avg(fd.values_current) as avg_value
                ORDER BY total_value DESC
                RETURN level, category, path, total_value, item_count, avg_value
                LIMIT {limit}
                """,
                parameters=["section", "year", "limit"],
                example_usage="2024년 재무상태표의 자산 카테고리별 순위를 보여주세요",
            ),
            "trend_analysis": QueryTemplate(
                name="트렌드 분석",
                description="특정 기간 동안의 재무 항목 변화 추이를 분석합니다.",
                cypher="""
                MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
                WHERE fd.section_code = '{section}' 
                AND fd.year >= {start_year} AND fd.year <= {end_year}
                WITH fd.item_name as item_name, fd.year as year, fd.values_current as values_current, fc.category_path as category_path
                ORDER BY item_name, year
                WITH item_name, category_path, 
                     collect(year) as years, 
                     collect(values_current) as values
                WHERE size(years) >= {min_years}
                RETURN item_name as item, category_path as category,
                       years, values
                ORDER BY item_name
                LIMIT {limit}
                """,
                parameters=["section", "start_year", "end_year", "min_years", "limit"],
                example_usage="2020년부터 2024년까지 자산 항목들의 변화 추이를 분석해주세요",
            ),
            "cross_section_analysis": QueryTemplate(
                name="재무제표 간 상관관계 분석",
                description="서로 다른 재무제표 섹션 간의 상관관계를 분석합니다.",
                cypher="""
                MATCH (fc1:fs_category)-[:related_to]->(fd1:financial_data)
                MATCH (fc2:fs_category)-[:related_to]->(fd2:financial_data)
                WHERE fd1.year = fd2.year AND fd1.year = {year}
                AND fd1.section_code = '{section1}' AND fd2.section_code = '{section2}'
                AND fd1.item_name = fd2.item_name
                RETURN fd1.item_name as item, fd1.values_current as {section1}_value,
                       fd2.values_current as {section2}_value, fd1.year as year
                ORDER BY fd1.item_name
                """,
                parameters=["year", "section1", "section2"],
                example_usage="2024년 재무상태표와 손익계산서의 상관관계를 분석해주세요",
            ),
            "subsidiary_financial_impact": QueryTemplate(
                name="종속기업 재무 영향 분석",
                description="종속기업들의 재무적 영향과 관계를 분석합니다.",
                cypher="""
                MATCH (c:company)-[:has_subsidiary]->(s:subsidiary)
                OPTIONAL MATCH (c)-[r:invests_in|trades_with|owes_to|guarantees_for]->(s)
                WITH c, s, type(r) as rel_type, s.ownership_percentage as ownership,
                     s.investment_amount as investment, s.trade_amount as trade, s.debt_amount as debt
                WHERE ownership IS NOT NULL OR investment IS NOT NULL
                RETURN c.name as company, s.name as subsidiary, rel_type,
                       ownership, investment, trade, debt
                ORDER BY ownership DESC
                """,
                parameters=[],
                example_usage="종속기업들의 지분율과 재무적 영향을 분석해주세요",
            ),
        }

    def get_template(self, template_name: str) -> Optional[QueryTemplate]:
        """Get a specific query template by name"""
        return self.templates.get(template_name)

    def get_all_templates(self) -> Dict[str, QueryTemplate]:
        """Get all available query templates"""
        return self.templates

    def get_templates_by_category(self, category: str) -> Dict[str, QueryTemplate]:
        """Get templates filtered by category"""
        category_keywords = {
            "hierarchical": ["계층", "구조", "레벨"],
            "temporal": ["연도", "트렌드", "변화", "성장"],
            "relationship": ["종속기업", "관계", "투자", "거래"],
            "analysis": ["분석", "순위", "상관관계"],
            "notes": ["주석", "문서", "설명"],
        }

        if category not in category_keywords:
            return {}

        keywords = category_keywords[category]
        filtered = {}

        for name, template in self.templates.items():
            if any(keyword in template.description for keyword in keywords):
                filtered[name] = template

        return filtered

    def format_query(self, template_name: str, **kwargs) -> str:
        """Format a query template with given parameters"""
        template = self.get_template(template_name)
        if not template:
            raise ValueError(f"Template '{template_name}' not found")

        try:
            return template.cypher.format(**kwargs)
        except KeyError as e:
            missing_params = [p for p in template.parameters if p not in kwargs]
            raise ValueError(f"Missing required parameters: {missing_params}")


# Global instance
advanced_queries = AdvancedFinancialQueries()


# Quick access functions
def get_hierarchical_analysis(year: int) -> str:
    """Get hierarchical balance sheet analysis query"""
    return advanced_queries.format_query("hierarchical_balance_sheet", year=year)


def get_year_over_year_growth(
    year1: int,
    year2: int,
    section: str = "BS",
    min_growth: float = 5.0,
    limit: int = 20,
) -> str:
    """Get year-over-year growth analysis query"""
    return advanced_queries.format_query(
        "year_over_year_growth",
        year1=year1,
        year2=year2,
        section=section,
        min_growth=min_growth,
        limit=limit,
    )


def get_subsidiary_analysis() -> str:
    """Get comprehensive subsidiary relationship analysis query"""
    return advanced_queries.format_query("subsidiary_relationship_analysis")


def get_financial_notes_analysis(section: str, year: int, limit: int = 20) -> str:
    """Get financial data with notes analysis query"""
    return advanced_queries.format_query(
        "financial_notes_analysis", section=section, year=year, limit=limit
    )


def get_category_ranking(section: str, year: int, limit: int = 20) -> str:
    """Get category value ranking query"""
    return advanced_queries.format_query(
        "category_value_ranking", section=section, year=year, limit=limit
    )
