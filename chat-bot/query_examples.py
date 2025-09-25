# query_examples.py
# 삼성전자 KG에 최적화된 쿼리 예시들

QUERY_EXAMPLES = {
    "hierarchical_analysis": {
        "description": "계층적 재무 분석",
        "examples": [
            "2024년 재무상태표의 자산 구조를 계층별로 보여주세요",
            "손익계산서의 주요 항목들을 레벨별로 분석해주세요",
            "현금흐름표의 영업활동 현금흐름 세부 항목들을 보여주세요",
            "자본변동표의 자본 구성요소를 계층적으로 분석해주세요",
        ],
        "cypher_template": "MATCH (fc:fs_category)-[:related_to]->(fd:financial_data) WHERE fd.section_code = '{section}' AND fd.year = {year} RETURN fc.hierarchy_level, fc.name, fd.item_name, fd.values_current ORDER BY fc.hierarchy_level, fd.values_current DESC",
    },
    "category_analysis": {
        "description": "카테고리별 재무 분석",
        "examples": [
            "자산 카테고리별 총액을 보여주세요",
            "유동자산의 세부 구성항목들을 분석해주세요",
            "부채의 주요 카테고리별 금액을 보여주세요",
            "수익의 세부 항목들을 카테고리별로 보여주세요",
        ],
        "cypher_template": "MATCH (fc:fs_category)-[:related_to]->(fd:financial_data) WHERE fc.category_path CONTAINS '{category_path}' AND fd.year = {year} WITH fc.name, sum(fd.values_current) as total_value ORDER BY total_value DESC RETURN fc.name, total_value",
    },
    "financial_data": {
        "description": "재무 데이터 관련 질문",
        "examples": [
            "2024년 매출액 관련 데이터를 보여주세요",
            "자산 관련 재무 항목들을 알려주세요",
            "특정 연도의 재무상태표 데이터를 보여주세요",
            "현금및현금성자산의 연도별 변화를 보여주세요",
        ],
        "cypher_template": "MATCH (fc:fs_category)-[:related_to]->(fd:financial_data) WHERE fd.item_name CONTAINS '{keyword}' AND fd.year = {year} RETURN fd.item_name, fd.values_current, fd.values_previous, fc.category_path, fc.hierarchy_level",
    },
    "notes_analysis": {
        "description": "주석 및 문서 분석",
        "examples": [
            "재무상태표 관련 주석들을 보여주세요",
            "특정 재무 항목과 연결된 주석을 찾아주세요",
            "손익계산서 주석 중 중요한 내용을 요약해주세요",
            "현금흐름표의 주요 주석들을 분석해주세요",
        ],
        "cypher_template": "MATCH (fd:financial_data)-[:links_to_note]->(n:note) WHERE fd.section_code = '{section}' AND fd.year = {year} RETURN fd.item_name, n.note_number, n.title, n.category ORDER BY n.note_number",
    },
    "company_info": {
        "description": "회사 기본 정보",
        "examples": [
            "삼성전자 회사 정보를 알려주세요",
            "회사 노드의 개수를 보여주세요",
        ],
        "cypher_template": "MATCH (c:company) RETURN c.name, c.company_type",
    },
    "subsidiaries": {
        "description": "종속기업 관련 질문",
        "examples": [
            "삼성전자 종속기업들을 보여주세요",
            "종속기업 중 투자 관계가 있는 기업들을 알려주세요",
            "특정 지분율 이상의 종속기업을 보여주세요",
            "거래 관계가 있는 종속기업들을 분석해주세요",
        ],
        "cypher_template": "MATCH (c:company)-[:has_subsidiary]->(s:subsidiary) WHERE c.name CONTAINS '삼성전자' RETURN s.name, s.relationship_type, s.ownership_percentage, s.investment_amount",
    },
    "year_over_year": {
        "description": "연도별 비교 분석",
        "examples": [
            "2023년과 2024년 매출액 변화를 비교해주세요",
            "자산의 연도별 증가율을 분석해주세요",
            "현금흐름의 연도별 변화 추이를 보여주세요",
            "부채의 연도별 변화를 분석해주세요",
        ],
        "cypher_template": "MATCH (fd1:financial_data), (fd2:financial_data) WHERE fd1.item_name = fd2.item_name AND fd1.year = {year1} AND fd2.year = {year2} WITH fd1, fd2, (fd2.values_current - fd1.values_current) / fd1.values_current * 100 as growth_rate RETURN fd1.item_name, fd1.values_current, fd2.values_current, growth_rate ORDER BY abs(growth_rate) DESC",
    },
    "financial_trends": {
        "description": "재무 트렌드 분석",
        "examples": [
            "재무 트렌드 중 증가하는 항목들을 보여주세요",
            "변화율이 큰 재무 항목들을 알려주세요",
            "특정 연도간 재무 변화를 분석해주세요",
        ],
        "cypher_template": "MATCH (fd1:financial_data), (fd2:financial_data) WHERE fd1.item_name = fd2.item_name AND fd1.year = fd2.year - 1 WITH fd1, fd2, (fd2.values_current - fd1.values_current) / fd1.values_current * 100 as growth_rate WHERE abs(growth_rate) > 5 RETURN fd1.item_name, fd1.year, growth_rate ORDER BY abs(growth_rate) DESC",
    },
    "year_analysis": {
        "description": "연도별 분석",
        "examples": [
            "2014년부터 2024년까지의 연도별 데이터를 보여주세요",
            "특정 연도의 모든 재무 데이터를 알려주세요",
            "2024년 재무제표 섹션별 요약을 보여주세요",
        ],
        "cypher_template": "MATCH (fd:financial_data) WHERE fd.year = {year} WITH fd.section_code, sum(fd.values_current) as total_value, count(fd) as item_count RETURN fd.section_code, total_value, item_count ORDER BY total_value DESC",
    },
    "relationships": {
        "description": "기업간 관계 분석",
        "examples": [
            "삼성전자와 투자 관계가 있는 기업들을 보여주세요",
            "거래 관계가 있는 기업들을 알려주세요",
            "채무 관계가 있는 기업들을 보여주세요",
            "복합 관계가 있는 종속기업들을 분석해주세요",
        ],
        "cypher_template": "MATCH (c:company)-[r]->(s:subsidiary) WHERE c.name CONTAINS '삼성전자' RETURN c.name, s.name, type(r) as relationship_type, s.ownership_percentage, s.investment_amount ORDER BY s.name",
    },
    "section_summary": {
        "description": "재무제표 섹션별 요약",
        "examples": [
            "2024년 재무상태표 요약을 보여주세요",
            "손익계산서의 주요 항목들을 요약해주세요",
            "현금흐름표의 영업/투자/재무활동 현금흐름을 보여주세요",
            "자본변동표의 주요 변동사항을 분석해주세요",
        ],
        "cypher_template": "MATCH (fc:fs_category)-[:related_to]->(fd:financial_data) WHERE fd.section_code = '{section}' AND fd.year = {year} AND fc.hierarchy_level = 1 WITH fc.name, sum(fd.values_current) as total_value ORDER BY total_value DESC RETURN fc.name, total_value",
    },
    "complex_analysis": {
        "description": "복잡한 분석 쿼리",
        "examples": [
            "삼성전자의 종속기업 중에서 투자와 거래 관계가 모두 있는 기업들을 보여주세요",
            "2014년부터 2024년까지 매출액이 가장 많이 증가한 재무 항목을 분석해주세요",
            "재무 트렌드에서 증가하는 항목과 감소하는 항목을 비교 분석해주세요",
            "2024년 재무상태표의 자산 항목들을 연도별 변화율과 함께 보여주세요",
            "삼성전자와 종속기업들 간의 모든 재무 관계를 종합적으로 분석해주세요",
        ],
        "cypher_template": "MATCH (c:company)-[:has_subsidiary]->(s:subsidiary) OPTIONAL MATCH (c)-[:invests_in]->(s) OPTIONAL MATCH (c)-[:trades_with]->(s) WITH c, s, collect(DISTINCT type(r)) as relationships WHERE size(relationships) > 0 RETURN c.name, s.name, relationships",
    },
    "temporal_analysis": {
        "description": "시계열 분석",
        "examples": [
            "2014년부터 2024년까지의 연도별 매출액 변화 추이를 보여주세요",
            "재무 항목별로 연도간 변화율이 가장 큰 항목들을 분석해주세요",
            "특정 기간 동안 증가율이 높은 재무 항목들을 보여주세요",
            "연도별 재무 트렌드의 평균 변화율을 계산해주세요",
        ],
        "cypher_template": "MATCH (fd1:financial_data), (fd2:financial_data) WHERE fd1.item_name = fd2.item_name AND fd1.year = fd2.year - 1 WITH fd1, fd2, (fd2.value - fd1.value) / fd1.value * 100 as growth_rate WHERE growth_rate > 10 RETURN fd1.item_name, fd1.year, fd1.value, fd2.value, growth_rate ORDER BY growth_rate DESC",
    },
    "aggregation_analysis": {
        "description": "집계 분석",
        "examples": [
            "재무 항목별 평균 변화율과 최대/최소 변화율을 보여주세요",
            "종속기업별 투자 금액의 합계를 계산해주세요",
            "연도별 재무 데이터의 총 개수를 보여주세요",
            "재무 트렌드에서 변화율이 큰 상위 10개 항목을 보여주세요",
        ],
        "cypher_template": "MATCH (ft:financial_trend) WITH ft.item_name, collect(ft.change_rate) as rates, avg(ft.change_rate) as avg_rate WHERE size(rates) >= 3 RETURN item_name, avg_rate, max(rates) as max_rate, min(rates) as min_rate ORDER BY avg_rate DESC",
    },
}


def get_query_suggestions(question_type: str = None) -> dict:
    """질문 유형에 따른 쿼리 제안"""
    if question_type and question_type in QUERY_EXAMPLES:
        return QUERY_EXAMPLES[question_type]
    return QUERY_EXAMPLES


def analyze_question_intent(question: str) -> str:
    """Enhanced question intent analysis"""
    question_lower = question.lower()

    # 계층적 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["계층", "레벨", "구조", "상위", "하위", "세부", "구성"]
    ):
        return "hierarchical_analysis"

    # 카테고리별 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in [
            "카테고리",
            "분류",
            "항목별",
            "구성항목",
            "구성 항목",
            "구성 요소",
            "세부항목",
            "세부 항목",
        ]
    ):
        return "category_analysis"

    # 주석 및 문서 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["주석", "각주", "설명", "문서", "내용", "요약"]
    ):
        return "notes_analysis"

    # 연도별 비교 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["비교", "대비", "증가율", "감소율", "변화율", "성장률"]
    ):
        return "year_over_year"

    # 재무제표 섹션별 요약 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["요약", "개요", "주요항목", "주요 항목" "핵심", "요점"]
    ):
        return "section_summary"

    # 복잡한 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["모두", "모든", "종합", "분석", "복합", "전체"]
    ):
        return "complex_analysis"

    # 시계열 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["추이", "변화", "연도별", "기간", "트렌드", "흐름"]
    ):
        return "financial_trends"

    # 집계 분석 질문 감지
    if any(
        keyword in question_lower
        for keyword in ["평균", "합계", "최대", "최소", "상위", "집계", "총계"]
    ):
        return "year_analysis"

    # 기본 카테고리들
    if any(
        keyword in question_lower
        for keyword in ["종속기업", "자회사", "subsidiary", "관계기업"]
    ):
        return "subsidiaries"
    elif any(
        keyword in question_lower
        for keyword in ["재무", "매출", "자산", "부채", "이익", "현금", "자본"]
    ):
        return "financial_data"
    elif any(
        keyword in question_lower
        for keyword in ["투자", "거래", "채무", "관계", "보증"]
    ):
        return "relationships"
    elif any(
        keyword in question_lower
        for keyword in [
            "년",
            "연도",
            "2024",
            "2023",
            "2022",
            "2021",
            "2020",
            "2019",
            "2018",
            "2017",
            "2016",
            "2015",
            "2014",
            "2024년",
            "2023년",
            "2022년",
            "2021년",
            "2020년",
            "2019년",
            "2018년",
            "2017년",
            "2016년",
            "2015년",
            "2014년",
        ]
    ):
        return "year_analysis"
    else:
        return "company_info"
