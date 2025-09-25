# streamlit_app.py
import traceback
import json
import streamlit as st
import pandas as pd

# 백엔드 체인
from app_chain import (
    ask_with_evidence,
    get_advanced_analysis,
    get_available_analyses,
    get_database_summary,
)
from query_examples import analyze_question_intent, get_query_suggestions
from visualization import (
    display_financial_chart,
    format_financial_value,
    create_data_table,
    visualizer,
)

# 그래프 컴포넌트 (있으면 사용, 없으면 경고)
try:
    from streamlit_agraph import agraph, Node, Edge, Config

    HAS_AGRAPH = True
except Exception:
    HAS_AGRAPH = False


# =========================
# Page & Sidebar
# =========================
st.set_page_config(
    page_title="Samsung Electronics Audited Financials Q&A",
    page_icon="🧠",
    layout="centered",
)

# =========================
# Session State 초기화
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = []  # 이전 대화 기록

if "current_conversation" not in st.session_state:
    st.session_state.current_conversation = []  # 현재 진행 중인 대화

with st.sidebar:
    st.markdown("### 🏢 삼성전자 재무 분석 시스템")

    # 분석 모드 선택
    analysis_mode = st.selectbox(
        "분석 모드",
        ["일반 질의응답", "고급 재무 분석", "데이터베이스 요약"],
        help="원하는 분석 유형을 선택하세요",
    )

    st.markdown("### ⚙️ 표시 옵션")
    show_debug = st.checkbox("Cypher / Records 자동 펼치기", value=False)
    show_graph = st.checkbox("그래프 뷰 표시", value=True)
    show_charts = st.checkbox("차트 시각화 표시", value=True)

    st.markdown("---")

    # 고급 분석 옵션
    if analysis_mode == "고급 재무 분석":
        st.markdown("### 📊 고급 분석")
        available_analyses = get_available_analyses()
        analysis_options = [f"{a['name']} ({a['key']})" for a in available_analyses]

        selected_analysis = st.selectbox(
            "분석 유형 선택",
            analysis_options,
            help="사전 정의된 고급 분석을 선택하세요",
        )

        if selected_analysis:
            analysis_key = selected_analysis.split("(")[-1].rstrip(")")
            analysis_info = next(
                a for a in available_analyses if a["key"] == analysis_key
            )

            st.markdown(f"**설명:** {analysis_info['description']}")
            st.markdown(f"**예시:** {analysis_info['example']}")

            # 분석 파라미터 입력
            if analysis_key in [
                "hierarchical_balance_sheet",
                "profit_loss_analysis",
                "cash_flow_analysis",
            ]:
                year = st.number_input(
                    "연도", min_value=2014, max_value=2024, value=2024
                )
                if st.button("분석 실행", use_container_width=True):
                    result = get_advanced_analysis(analysis_key, year=year)
                    st.session_state.advanced_result = result

    elif analysis_mode == "데이터베이스 요약":
        if st.button("데이터베이스 요약 생성", use_container_width=True):
            with st.spinner("데이터베이스 요약 생성 중..."):
                summary = get_database_summary()
                st.session_state.db_summary = summary

                

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 대화 초기화", use_container_width=True):
            st.session_state.pop("messages", None)
            st.session_state.pop("advanced_result", None)
            st.session_state.pop("db_summary", None)
            st.rerun()
    with col2:
        if st.button("📊 차트 새로고침", use_container_width=True):
            st.rerun()

    st.markdown("---")
    st.caption(
        "**Enhanced Neo4j + LangChain** RAG 시스템\n계층적 재무 분석 • 시각화 • 고급 쿼리"
    )


# =========================
# Utils
# =========================
def _safe_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        return str(obj)


def _render_raw(
    answer: str | None, cypher: str | None, records: object | None, expand_default: bool
):
    """디버그/원시 결과 패널 렌더"""
    with st.expander("🔎 Generated Cypher", expanded=expand_default):
        st.code((cypher or "(n/a)"), language="cypher")
    with st.expander("📄 Records (raw)", expanded=expand_default):
        try:
            st.json(records if records is not None else {"info": "(no records)"})
        except Exception:
            st.text(_safe_json(records))


# ---------- Graph helpers ----------
def _records_to_graph_elements(
    records,
) -> tuple[list[Node], list[Edge], Config] | tuple[None, None, None]:
    """
    records(JSON-like) -> (agraph Nodes, agraph Edges, agraph Config)
    - 다양한 형태를 보수적으로 수용:
      1) 컬럼형(dict): {"company": "...", "item_name": "...", "year": 2021, ...}
      2) 노드형(dict): {"c": {...}, "fd": {...}, "yn": {...}}  (GraphCypherQAChain 환경)
    - 최소한 company / item_name / year 세 축을 시각화
    """
    if not HAS_AGRAPH or not records:
        return None, None, None

    nodes_map: dict[str, Node] = {}
    edges: list[Edge] = []

    def add_node(node_id: str, label: str, title: str | None = None):
        if not node_id:
            return
        if node_id not in nodes_map:
            nodes_map[node_id] = Node(
                id=node_id,
                label=label,
                title=title or label,
                size=20,
            )

    def add_edge(src: str, dst: str, label: str):
        if src and dst:
            edges.append(Edge(source=src, target=dst, label=label))

    # 리스트/단건 모두 처리
    if not isinstance(records, list):
        records = [records]

    for r in records:
        # 1) 컬럼형 우선 시도
        company = r.get("company") or r.get("company_name") or r.get("c.name")
        item = r.get("item_name") or r.get("fd.item_name") or r.get("item")
        year = r.get("year") or r.get("yn.year")
        period = r.get("period") or r.get("fd.column_name")
        value = r.get("value") or r.get("fd.value")

        # 2) 노드형 보조 시도
        c_node = (
            r.get("c") or r.get("company")
            if isinstance(r.get("c") or r.get("company"), dict)
            else None
        )
        fd_node = (
            r.get("fd") or r.get("financial_data")
            if isinstance(r.get("fd") or r.get("financial_data"), dict)
            else None
        )
        yn_node = (
            r.get("yn") or r.get("year_node")
            if isinstance(r.get("yn") or r.get("year_node"), dict)
            else None
        )

        # ---- 컬럼형에서 노드/엣지 구성 ----
        if company:
            add_node(f"company:{company}", str(company))
        if item:
            add_node(f"item:{item}", str(item))
        if year is not None:
            add_node(f"year:{year}", f"Y:{year}")
        if period:
            add_node(f"period:{period}", f"P:{period}")
        if value is not None:
            add_node(f"value:{company}:{item}:{year}", f"V:{value}")

        # 관계 (가능하면 단순, 직관적으로)
        if company and item:
            add_edge(f"company:{company}", f"item:{item}", "has_data")
        if item and year is not None:
            add_edge(f"item:{item}", f"year:{year}", "in_year")
        if year is not None and period:
            add_edge(f"year:{year}", f"period:{period}", "period")
        if item and value is not None:
            add_edge(f"item:{item}", f"value:{company}:{item}:{year}", "value")

        # ---- 노드형이 있으면 보조로 라벨링 강화 ----
        if c_node and c_node.get("name"):
            nodes_map[f"company:{company or c_node.get('name')}"].title = _safe_json(
                c_node
            )
        if fd_node and fd_node.get("item_name"):
            nodes_map[f"item:{item or fd_node.get('item_name')}"].title = _safe_json(
                fd_node
            )
        if yn_node and yn_node.get("year") is not None:
            nodes_map[f"year:{year or yn_node.get('year')}"].title = _safe_json(yn_node)

    config = Config(
        width=900,
        height=520,
        directed=True,
        physics=True,
        hierarchical=False,
    )
    return list(nodes_map.values()), edges, config


def render_graph_panel(records):
    """그래프 시각화 패널"""
    st.subheader("🌐 Graph")
    if not HAS_AGRAPH:
        st.warning(
            "`streamlit-agraph`가 설치되어 있지 않습니다. `pip install streamlit-agraph` 후 사용하세요."
        )
        return
    nodes, edges, config = _records_to_graph_elements(records)
    if not nodes:
        st.info("그래프에 표시할 노드/관계가 없습니다.")
        return
    agraph(nodes=nodes, edges=edges, config=config)


# =========================
# Main Interface
# =========================
st.title("🏢 삼성전자 재무 분석 시스템")
st.markdown("**Enhanced Knowledge Graph 기반 재무 분석 및 시각화**")

# 분석 모드에 따른 메인 인터페이스
if analysis_mode == "고급 재무 분석":
    st.header("📊 고급 재무 분석")

    if "advanced_result" in st.session_state:
        result = st.session_state.advanced_result
        st.markdown("### 분석 결과")
        st.markdown(result.get("answer", "분석 결과가 없습니다."))

        if result.get("records"):
            try:
                render_visualization_panel(result["records"], "advanced_analysis")
            except NameError:
                # render_visualization_panel이 정의되기 전에 호출되는 경우
                pass
            create_data_table(result["records"], "상세 데이터")

        if show_debug and result.get("cypher"):
            with st.expander("생성된 Cypher 쿼리", expanded=True):
                st.code(result["cypher"], language="cypher")

    else:
        st.info("사이드바에서 분석 유형을 선택하고 실행하세요.")

elif analysis_mode == "데이터베이스 요약":
    st.header("📈 데이터베이스 요약")

    if "db_summary" in st.session_state:
        summary = st.session_state.db_summary

        if "error" in summary:
            st.error(summary["error"])
        else:
            # 노드 개수 표시
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric(
                    "재무 데이터",
                    f"{summary['node_counts'].get('financial_data', 0):,}개",
                )
            with col2:
                st.metric(
                    "카테고리", f"{summary['node_counts'].get('fs_category', 0):,}개"
                )
            with col3:
                st.metric("주석", f"{summary['node_counts'].get('note', 0):,}개")

            # 노드 개수 시각화 (도넛 차트)
            try:
                import plotly.express as px
                import pandas as pd

                node_pie_df = pd.DataFrame(
                    [
                        {
                            "label": "financial_data",
                            "count": summary["node_counts"].get("financial_data", 0),
                        },
                        {
                            "label": "fs_category",
                            "count": summary["node_counts"].get("fs_category", 0),
                        },
                        {
                            "label": "note",
                            "count": summary["node_counts"].get("note", 0),
                        },
                    ]
                )
                fig_node = px.pie(
                    node_pie_df,
                    names="label",
                    values="count",
                    hole=0.5,
                    title="주요 노드 비중",
                )
                st.plotly_chart(fig_node, use_container_width=True)
            except Exception:
                pass

            # 재무제표 섹션별 통계
            if summary.get("financial_stats"):
                st.subheader("재무제표 섹션별 통계")
                df_stats = pd.DataFrame(summary["financial_stats"])
                st.dataframe(df_stats, use_container_width=True)

                # 섹션별 개수/총액 시각화
                try:
                    import plotly.express as px

                    cols = st.columns(2)
                    with cols[0]:
                        fig_cnt = px.bar(
                            df_stats,
                            x="section_code",
                            y="count",
                            title="섹션별 데이터 개수",
                        )
                        st.plotly_chart(fig_cnt, use_container_width=True)
                    with cols[1]:
                        fig_val = px.bar(
                            df_stats,
                            x="section_code",
                            y="total_value",
                            title="섹션별 총 금액",
                        )
                        st.plotly_chart(fig_val, use_container_width=True)
                except Exception:
                    pass

            # 카테고리 계층 통계
            if summary.get("category_stats"):
                st.subheader("카테고리 계층별 통계")
                df_cat = pd.DataFrame(summary["category_stats"])
                st.dataframe(df_cat, use_container_width=True)

            charts = summary.get("charts", {})

            # 1) 연도별 섹션 합계 (선형 차트)
            fb = charts.get("financial_by_year") or []
            if fb:
                import pandas as pd
                import plotly.express as px

                df = pd.DataFrame(fb)
                fig = px.line(
                    df,
                    x="year",
                    y="total_value",
                    color="section_code",
                    markers=True,
                    title="연도별 섹션별 합계",
                )
                st.plotly_chart(fig, use_container_width=True)

            # 1-1) 전체 연도 흐름(총합) & 데이터 건수/주석 수 (보조 시계열)
            total_by_year = charts.get("total_by_year") or []
            counts_by_year = charts.get("counts_by_year") or []
            notes_by_year = charts.get("notes_by_year") or []
            if total_by_year:
                import pandas as pd
                import plotly.express as px

                df_total = pd.DataFrame(total_by_year)
                fig = px.line(
                    df_total,
                    x="year",
                    y="total_value",
                    markers=True,
                    title="연도별 총 재무값 합계",
                )
                st.plotly_chart(fig, use_container_width=True)

            colx, coly = st.columns(2)
            with colx:
                if counts_by_year:
                    import pandas as pd
                    import plotly.express as px

                    df_cnt = pd.DataFrame(counts_by_year)
                    fig = px.bar(
                        df_cnt,
                        x="year",
                        y="count",
                        title="연도별 재무 데이터 건수",
                    )
                    st.plotly_chart(fig, use_container_width=True)
            with coly:
                if notes_by_year:
                    import pandas as pd
                    import plotly.express as px

                    df_notes = pd.DataFrame(notes_by_year)
                    fig = px.bar(
                        df_notes, x="year", y="notes", title="연도별 주석 개수"
                    )
                    st.plotly_chart(fig, use_container_width=True)

            # 2) 2024 BS 상위 10 카테고리 (막대 차트)
            top_bs = charts.get("top_categories_2024_bs") or []
            if top_bs:
                import pandas as pd
                import plotly.express as px

                df = pd.DataFrame(top_bs)
                fig = px.bar(
                    df,
                    x="category",
                    y="total_value",
                    title="2024년 재무상태표(BS) 상위 카테고리",
                )
                st.plotly_chart(fig, use_container_width=True)

            # 3) 섹션별 주석 수 (도넛 차트)
            notes_by_section = charts.get("notes_by_section") or []
            if notes_by_section:
                import pandas as pd
                import plotly.express as px

                df = pd.DataFrame(notes_by_section)
                fig = px.pie(
                    df,
                    names="section_code",
                    values="notes_count",
                    hole=0.45,
                    title="섹션별 연결 주석 수 분포",
                )
                st.plotly_chart(fig, use_container_width=True)

            # 4) BS 주석 번호 분포 (막대 차트)
            notes_dist = charts.get("notes_bs_distribution") or []
            if notes_dist:
                import pandas as pd
                import plotly.express as px

                df = pd.DataFrame(notes_dist)
                fig = px.bar(
                    df,
                    x="note_number",
                    y="count",
                    title="재무상태표(BS) 관련 주석 번호 분포",
                )
                st.plotly_chart(fig, use_container_width=True)

            # 5) 종속기업 채무/보증 요약 (카드)
            col1, col2 = st.columns(2)
            debt_summary = (charts.get("subsidiary_debt_summary") or [{}])[0]
            guar_summary = (charts.get("guarantees_summary") or [{}])[0]
            with col1:
                st.metric(
                    "종속기업 채무 합계",
                    f"{(debt_summary.get('total_debt') or 0):,.0f}",
                    help="has_subsidiary 관계의 채무 관련 속성 합산",
                )
            with col2:
                st.metric(
                    "보증 한도 합계",
                    f"{(guar_summary.get('total_guarantee_limit') or 0):,.0f}",
                    help="guarantees_for 관계의 guarantee_limit 합산",
                )

                # 섹션-계층 스택 막대 시각화
                try:
                    import plotly.express as px

                    fig_cat = px.bar(
                        df_cat,
                        x="section_code",
                        y="count",
                        color="hierarchy_level",
                        barmode="stack",
                        title="섹션별 계층 수준 분포",
                    )
                    st.plotly_chart(fig_cat, use_container_width=True)
                except Exception:
                    pass

    else:
        st.info("사이드바에서 '데이터베이스 요약 생성' 버튼을 클릭하세요.")

else:  # 일반 질의응답
    # 질문 제안
    st.markdown("### 💡 질문 제안")
    suggestions = [
        "2024년 재무상태표의 자산 구조를 계층별로 보여주세요",
        "삼성전자 종속기업들의 관계를 분석해주세요",
        "2023년과 2024년 매출액 변화를 비교해주세요",
        "현금흐름표의 주요 항목들을 보여주세요",
        "재무상태표 관련 주석들을 찾아주세요",
    ]

    cols = st.columns(2)
    for i, suggestion in enumerate(suggestions):
        with cols[i % 2]:
            if st.button(suggestion, key=f"suggestion_{i}", use_container_width=True):
                st.session_state.suggested_question = suggestion
                st.rerun()

# =========================
# Chat Interface
# =========================
if "messages" not in st.session_state:
    st.session_state.messages = []


def render_user_message(text: str):
    with st.chat_message("user"):
        st.markdown(text)


def render_assistant_message(
    answer: str,
    cypher: str | None,
    records: object | None,
    intent: str = None,
    analysis_type: str = None,
):
    with st.chat_message("assistant"):
        st.markdown(answer if answer else "_(답변 없음)_")

        # 의도 및 분석 유형 표시
        if intent and intent != "error":
            pass
            # st.info(f"🔍 감지된 질문 유형: {intent}")
        if analysis_type:
            st.success(f"📊 분석 유형: {analysis_type}")

        # 원시 데이터 표시
        _render_raw(answer, cypher, records, expand_default=show_debug)

        # 차트 시각화
        if show_charts and records:
            try:
                render_visualization_panel(records, intent, analysis_type)
            except Exception as e:
                st.warning(f"차트 렌더링 중 문제가 발생했습니다: {str(e)}")

        # 그래프 뷰
        if show_graph:
            try:
                render_graph_panel(records)
            except Exception:
                st.info(
                    "그래프 렌더링 중 문제가 발생했습니다. Records 구조를 확인해 주세요."
                )


def render_visualization_panel(records, intent: str = None, analysis_type: str = None):
    """차트 시각화 패널"""
    if not records:
        return

    st.subheader("📊 데이터 시각화")

    # 데이터를 DataFrame으로 변환
    try:
        df = pd.DataFrame(records)
    except Exception:
        st.warning("데이터를 DataFrame으로 변환할 수 없습니다.")
        return

    # 의도에 따른 차트 선택
    if intent == "hierarchical_analysis" or "계층" in str(records):
        if "category_path" in df.columns and "total_value" in df.columns:
            display_financial_chart(records, "hierarchical", "계층적 재무 구조")
        elif "hierarchy_level" in df.columns:
            display_financial_chart(records, "category", "카테고리별 분석")

    elif intent == "year_over_year" or "growth_rate" in str(records):
        if "growth_rate" in df.columns:
            display_financial_chart(records, "growth", "성장률 분석")
        elif "year" in df.columns and "values_current" in df.columns:
            display_financial_chart(records, "trend", "연도별 트렌드")

    elif intent == "financial_trends" or "year" in df.columns:
        if "year" in df.columns and "values_current" in df.columns:
            display_financial_chart(records, "trend", "재무 트렌드 분석")

    elif intent == "subsidiaries" or "subsidiary" in str(records):
        if "subsidiary" in df.columns and "relationship_type" in df.columns:
            display_financial_chart(records, "network", "종속기업 관계 네트워크")

    elif intent == "section_summary" or "section_code" in df.columns:
        if "section_code" in df.columns and "total_value" in df.columns:
            display_financial_chart(records, "section", "재무제표 섹션별 요약")

    # 기본 차트 (데이터에 따라 자동 선택)
    else:
        if "total_value" in df.columns and "category" in df.columns:
            display_financial_chart(records, "category", "카테고리별 분석")
        elif "values_current" in df.columns and "year" in df.columns:
            display_financial_chart(records, "trend", "시계열 분석")
        elif len(df) > 0:
            # 데이터 테이블로 표시
            create_data_table(records, "데이터 테이블")


# 일반 질의응답 모드
if analysis_mode == "일반 질의응답":
    # 1. 이전 대화 기록 렌더링 (완료된 대화만)
    for m in st.session_state.messages:
        if m["role"] == "user":
            render_user_message(m["content"])
        else:
            meta = m.get("meta", {}) or {}
            render_assistant_message(
                answer=m.get("content", ""),
                cypher=meta.get("cypher"),
                records=meta.get("records"),
                intent=meta.get("intent"),
                analysis_type=meta.get("analysis_type"),
            )

    # 2. 현재 진행 중인 대화 렌더링 (새 요청 처리 중)
    for m in st.session_state.current_conversation:
        if m["role"] == "user":
            render_user_message(m["content"])
        else:
            meta = m.get("meta", {}) or {}
            render_assistant_message(
                answer=m.get("content", ""),
                cypher=meta.get("cypher"),
                records=meta.get("records"),
                intent=meta.get("intent"),
                analysis_type=meta.get("analysis_type"),
            )

    # 3. 질문 입력창 (항상 표시)
    prompt = st.chat_input(
        "질문을 입력하세요 (예: 2024년 재무상태표의 자산 구조를 계층별로 보여주세요)"
    )

    # 제안된 질문 처리
    if "suggested_question" in st.session_state:
        prompt = st.session_state.suggested_question
        del st.session_state.suggested_question

    if prompt:
        # 4. 새 질문 처리 시작
        # 현재 대화 상태 초기화 (이전 응답이 보이지 않도록)
        st.session_state.current_conversation = []

        # 사용자 메시지를 현재 대화에 추가
        st.session_state.current_conversation.append(
            {"role": "user", "content": prompt}
        )

        # 사용자 메시지 렌더링
        render_user_message(prompt)

        # 5. 백엔드 호출
        try:
            # Spinner를 별도 컨테이너에 배치하여 기존 응답과 분리
            spinner_container = st.empty()
            with spinner_container.container():
                with st.spinner("재무 데이터 분석 중…"):
                    out = ask_with_evidence(
                        prompt
                    )  # -> {"answer","cypher","records","intent","analysis_type"}

            # Spinner 컨테이너 제거
            spinner_container.empty()

            answer = out.get("answer") or "알고 있는 정보가 없습니다."
            cypher = out.get("cypher")
            records = out.get("records")
            intent = out.get("intent")
            analysis_type = out.get("analysis_type")

            # 6. 응답을 현재 대화에 추가 및 렌더링
            assistant_message = {
                "role": "assistant",
                "content": answer,
                "meta": {
                    "cypher": cypher,
                    "records": records,
                    "intent": intent,
                    "analysis_type": analysis_type,
                },
            }
            st.session_state.current_conversation.append(assistant_message)
            render_assistant_message(answer, cypher, records, intent, analysis_type)

            # 7. 완료된 대화를 이전 대화 기록에 추가
            st.session_state.messages.extend(st.session_state.current_conversation)
            st.session_state.current_conversation = []  # 현재 대화 상태 초기화

        except Exception:
            err_trace = traceback.format_exc()
            with st.chat_message("assistant"):
                st.error("🚨 Internal Error")
                st.code(err_trace)

            # 에러 메시지를 현재 대화에 추가
            error_message = {
                "role": "assistant",
                "content": "요청 처리 중 오류가 발생했습니다.",
                "meta": {"traceback": err_trace},
            }
            st.session_state.current_conversation.append(error_message)

            # 완료된 대화를 이전 대화 기록에 추가
            st.session_state.messages.extend(st.session_state.current_conversation)
            st.session_state.current_conversation = []  # 현재 대화 상태 초기화

# Footer
st.markdown("---")
st.caption(
    "💡 Tip: 답변 아래에서 Cypher와 원시 Records, 그리고 (선택 시) 그래프 뷰를 확인할 수 있어요."
)
