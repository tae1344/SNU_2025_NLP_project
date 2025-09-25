# app_chain.py
import re
from typing import Any, Dict, List, Tuple, Optional
from langchain_openai import ChatOpenAI
from graph_conn import graph
from prompts import cypher_prompt, answer_prompt, financial_analysis_prompt
from query_examples import analyze_question_intent, get_query_suggestions
from advanced_queries import advanced_queries

llm = ChatOpenAI(model="gpt-4o", temperature=0)

BAD = re.compile(
    r"\b(CREATE|MERGE|SET|DELETE|REMOVE|LOAD\s+CSV|CALL\s|APOC\.|apoc\.|DROP|DETACH|INDEX|CONSTRAINT|PROCEDURE|FUNCTION)\b",
    re.I,
)


def guard(cypher: str):
    if BAD.search(cypher or ""):
        raise ValueError(
            f"Blocked: write-like/dangerous clause detected in: {cypher[:100]}..."
        )


def adjust_limit_by_intent(cypher: str, intent: str) -> str:
    """Adjust LIMIT clause based on question intent"""
    try:
        # 질문 의도에 따른 LIMIT 값 결정
        limit_mapping = {
            "hierarchical_analysis": 100,  # 계층적 분석은 더 많은 데이터 필요
            "category_analysis": 100,  # 카테고리 분석도 상세한 데이터 필요
            "year_over_year": 50,  # 연도별 비교는 중간 정도
            "financial_data": 200,  # 재무 데이터 조회는 많은 데이터 필요
            "notes_analysis": 50,  # 주석 분석은 중간 정도
            "subsidiaries": 100,  # 종속기업 분석은 상세한 데이터 필요
            "complex_analysis": 200,  # 복잡한 분석은 많은 데이터 필요
            "section_summary": 20,  # 섹션 요약은 적은 데이터로 충분
        }

        # 기본 LIMIT 값
        default_limit = 50

        # 의도에 따른 LIMIT 값 결정
        suggested_limit = limit_mapping.get(intent, default_limit)

        # 현재 쿼리에 LIMIT이 있는지 확인
        if "LIMIT" in cypher.upper():
            # 기존 LIMIT 값을 새로운 값으로 교체
            import re

            pattern = r"LIMIT\s+\d+"
            replacement = f"LIMIT {suggested_limit}"
            cypher = re.sub(pattern, replacement, cypher, flags=re.IGNORECASE)
        else:
            # LIMIT이 없으면 추가
            cypher = cypher.rstrip() + f"\nLIMIT {suggested_limit}"

        return cypher

    except Exception:
        # 오류 발생 시 원본 쿼리 반환
        return cypher


def fix_cypher_aliases(cypher: str) -> str:
    """Fix common Cypher alias issues in generated queries"""
    try:
        lines = cypher.split("\n")
        fixed_lines = []
        alias_map = {}

        # 1단계: WITH 절에서 별칭 추출
        for line in lines:
            line = line.strip()
            if line.upper().startswith("WITH "):
                with_content = line[5:].strip()
                if " as " in with_content:
                    # 쉼표로 분리하여 각 부분 처리
                    parts = [part.strip() for part in with_content.split(",")]
                    for part in parts:
                        if " as " in part:
                            original, alias = part.split(" as ", 1)
                            original = original.strip()
                            alias = alias.strip()
                            alias_map[original] = alias
                break  # 첫 번째 WITH 절만 처리

        # 2단계: 모든 라인을 처리하며 별칭 적용
        for line in lines:
            line = line.strip()

            if line.upper().startswith("RETURN "):
                return_content = line[7:].strip()
                # 원래 변수명을 별칭으로 교체
                for original, alias in alias_map.items():
                    return_content = return_content.replace(original, alias)
                fixed_lines.append(f"RETURN {return_content}")

            elif line.upper().startswith("ORDER BY "):
                order_content = line[9:].strip()
                # 원래 변수명을 별칭으로 교체
                for original, alias in alias_map.items():
                    order_content = order_content.replace(original, alias)
                fixed_lines.append(f"ORDER BY {order_content}")

            else:
                fixed_lines.append(line)

        return "\n".join(fixed_lines)

    except Exception as e:
        # 수정 중 오류가 발생하면 원본 쿼리 반환
        print(f"Warning: Failed to fix Cypher aliases: {e}")
        return cypher


def ask_with_evidence(question: str):
    """Enhanced question answering with advanced financial analysis capabilities"""
    try:
        # 1. 질문 의도 분석
        intent = analyze_question_intent(question)

        # 2. 스키마 정보 가져오기
        schema = graph.get_schema()

        # 3. Cypher 쿼리 생성
        prompt = cypher_prompt.format(schema=schema, question=question)
        response = llm.invoke(prompt)
        cypher = response.content.strip()

        # 마크다운 코드 블록 제거
        if cypher.startswith("```"):
            lines = cypher.split("\n")
            if len(lines) > 1:
                cypher = "\n".join(lines[1:-1])
            else:
                cypher = cypher.replace("```", "").strip()

        # 4. 보안 검사
        guard(cypher)

        # 5. 쿼리 후처리 (별칭 문제 수정)
        cypher = fix_cypher_aliases(cypher)

        # 6. LIMIT 조정 (질문 의도에 따라)
        cypher = adjust_limit_by_intent(cypher, intent)

        # 7. 쿼리 실행
        records = graph.query(cypher)

        # 6. 고급 분석이 필요한 경우 추가 처리
        analysis_type = None
        if intent in ["hierarchical_analysis", "category_analysis", "year_over_year"]:
            analysis_type = intent
        elif len(records) > 10 and any(
            "values_current" in str(record) for record in records
        ):
            analysis_type = "financial_analysis"

        # 7. 답변 생성
        if records:
            if analysis_type:
                # 고급 분석 프롬프트 사용
                formatted_prompt = financial_analysis_prompt.format(
                    question=question,
                    analysis_type=analysis_type,
                    data=records[:10],  # 처음 10개만 사용
                )
                answer_response = llm.invoke(formatted_prompt)
                answer = answer_response.content.strip()
            else:
                # 기본 답변 프롬프트 사용
                formatted_prompt = answer_prompt.format(
                    question=question, cypher=cypher, records=records
                )
                answer_response = llm.invoke(formatted_prompt)
                answer = answer_response.content.strip()
        else:
            # 데이터가 없는 경우 제안 제공
            suggestions = get_query_suggestions(intent)
            suggestion_text = ""
            if suggestions and "examples" in suggestions:
                suggestion_text = f"\n\n관련 질문 예시:\n" + "\n".join(
                    [f"- {ex}" for ex in suggestions["examples"][:3]]
                )

            answer = f"해당 질문에 대한 데이터를 찾을 수 없습니다.{suggestion_text}\n\n다른 키워드로 질문해보시거나 관련 정보를 확인해보세요."

        return {
            "answer": answer,
            "cypher": cypher,
            "records": records,
            "intent": intent,
            "analysis_type": analysis_type,
        }

    except Exception as e:
        return {
            "answer": f"오류가 발생했습니다: {str(e)}",
            "cypher": "",
            "records": [],
            "intent": "error",
            "analysis_type": None,
        }


def get_advanced_analysis(analysis_type: str, **kwargs) -> Dict[str, Any]:
    """Get advanced financial analysis using predefined templates"""
    try:
        template = advanced_queries.get_template(analysis_type)
        if not template:
            return {
                "answer": f"분석 유형 '{analysis_type}'을 찾을 수 없습니다.",
                "cypher": "",
                "records": [],
                "intent": "error",
                "analysis_type": None,
            }

        # 쿼리 생성
        cypher = advanced_queries.format_query(analysis_type, **kwargs)

        # 보안 검사
        guard(cypher)

        # 쿼리 실행
        records = graph.query(cypher)

        # 답변 생성
        if records:
            formatted_prompt = financial_analysis_prompt.format(
                question=f"{template.description} (고급 분석)",
                analysis_type=analysis_type,
                data=records,
            )
            answer_response = llm.invoke(formatted_prompt)
            answer = answer_response.content.strip()
        else:
            answer = f"{template.description}에 대한 데이터를 찾을 수 없습니다."

        return {
            "answer": answer,
            "cypher": cypher,
            "records": records,
            "intent": analysis_type,
            "analysis_type": analysis_type,
        }

    except Exception as e:
        return {
            "answer": f"고급 분석 중 오류가 발생했습니다: {str(e)}",
            "cypher": "",
            "records": [],
            "intent": "error",
            "analysis_type": None,
        }


def get_available_analyses() -> List[Dict[str, str]]:
    """Get list of available advanced analyses"""
    templates = advanced_queries.get_all_templates()
    return [
        {
            "name": template.name,
            "description": template.description,
            "key": key,
            "example": template.example_usage,
        }
        for key, template in templates.items()
    ]


def get_database_summary() -> Dict[str, Any]:
    """Get comprehensive database summary"""
    try:
        node_counts = graph.get_node_counts()
        rel_counts = graph.get_relationship_counts()

        # 주요 재무 데이터 통계
        financial_stats = graph.query(
            """
            MATCH (fd:financial_data)
            WITH fd.section_code as section_code, count(fd) as count, 
                 sum(fd.values_current) as total_value,
                 min(fd.year) as min_year, max(fd.year) as max_year
            RETURN section_code, count, total_value, min_year, max_year
            ORDER BY count DESC
        """
        )

        # 카테고리 통계
        category_stats = graph.query(
            """
            MATCH (fc:fs_category)
            WITH fc.section_code as section_code, fc.hierarchy_level as hierarchy_level, count(fc) as count
            RETURN section_code, hierarchy_level, count
            ORDER BY section_code, hierarchy_level
        """
        )

        # 연도별 섹션 합계 (차트용)
        financial_by_year = graph.query(
            """
            MATCH (fd:financial_data)
            WHERE fd.year IS NOT NULL AND fd.values_current IS NOT NULL
            WITH fd.year AS year, fd.section_code AS section_code, sum(fd.values_current) AS total_value
            RETURN year, section_code, total_value
            ORDER BY year ASC, section_code ASC
            """
        )

        # 최근 연도별 상위 카테고리 (BS 2024 상위 10)
        top_categories_2024_bs = graph.query(
            """
            MATCH (fc:fs_category)-[:related_to]->(fd:financial_data)
            WHERE fd.year = 2024 AND fd.section_code = 'BS' AND fd.values_current IS NOT NULL
            WITH fc.name AS category, sum(fd.values_current) AS total_value
            RETURN category, total_value
            ORDER BY total_value DESC
            LIMIT 10
            """
        )

        # 주석 통계: 섹션별 연결 주석 수 및 번호 분포 (BS)
        notes_by_section = graph.query(
            """
            MATCH (fc:fs_category)-[:links_to_note]->(n:note)
            RETURN fc.section_code AS section_code, count(DISTINCT n) AS notes_count
            ORDER BY notes_count DESC
            """
        )

        notes_bs_distribution = graph.query(
            """
            MATCH (fc:fs_category)-[:links_to_note]->(n:note)
            WHERE fc.section_code = 'BS'
            RETURN n.note_number AS note_number, count(*) AS count
            ORDER BY note_number ASC
            """
        )

        # 종속기업 채무/보증 요약 (관계 속성 기반)
        subsidiary_debt_summary = graph.query(
            """
            MATCH (:company)-[r:has_subsidiary]->(:subsidiary)
            WITH 
                sum(coalesce(r.debt_amount,0) + coalesce(r.debt_amount_2,0) + coalesce(r.amount_채무_등3,0)) AS total_debt,
                sum(CASE WHEN r.debt_amount IS NOT NULL OR r.debt_amount_2 IS NOT NULL OR r.amount_채무_등3 IS NOT NULL THEN 1 ELSE 0 END) AS relationships_with_debt
            RETURN total_debt, relationships_with_debt
            """
        )

        guarantees_summary = graph.query(
            """
            MATCH (:company)-[r:guarantees_for]->(:subsidiary)
            RETURN sum(coalesce(r.guarantee_limit,0)) AS total_guarantee_limit, count(r) AS relationships
            """
        )

        # 전년도 전범위 통계 (연도 흐름 차트용)
        total_by_year = graph.query(
            """
            MATCH (fd:financial_data)
            WHERE fd.year IS NOT NULL AND fd.values_current IS NOT NULL
            WITH fd.year AS year, sum(fd.values_current) AS total_value
            RETURN year, total_value
            ORDER BY year ASC
            """
        )

        counts_by_year = graph.query(
            """
            MATCH (fd:financial_data)
            WHERE fd.year IS NOT NULL
            WITH fd.year AS year, count(fd) AS count
            RETURN year, count
            ORDER BY year ASC
            """
        )

        notes_by_year = graph.query(
            """
            MATCH (n:note)
            WHERE n.year IS NOT NULL
            WITH n.year AS year, count(n) AS notes
            RETURN year, notes
            ORDER BY year ASC
            """
        )

        return {
            "node_counts": node_counts,
            "relationship_counts": rel_counts,
            "financial_stats": financial_stats,
            "category_stats": category_stats,
            # 차트/시각화용 데이터 세트
            "charts": {
                "financial_by_year": financial_by_year,
                "total_by_year": total_by_year,
                "counts_by_year": counts_by_year,
                "notes_by_year": notes_by_year,
                "top_categories_2024_bs": top_categories_2024_bs,
                "notes_by_section": notes_by_section,
                "notes_bs_distribution": notes_bs_distribution,
                "subsidiary_debt_summary": subsidiary_debt_summary,
                "guarantees_summary": guarantees_summary,
            },
            "total_financial_data": sum(
                node_counts.get(label, 0)
                for label in ["financial_data", "fs_category", "note"]
            ),
            "years_covered": (
                f"{min([s['min_year'] for s in financial_stats])}-{max([s['max_year'] for s in financial_stats])}"
                if financial_stats
                else "N/A"
            ),
        }

    except Exception as e:
        return {"error": f"데이터베이스 요약 생성 중 오류: {str(e)}"}
