# visualization.py
# Data visualization capabilities for financial analysis

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Any, Optional
import json


class FinancialVisualizer:
    """Financial data visualization utilities"""

    def __init__(self):
        self.color_palette = {
            "BS": "#1f77b4",  # Blue
            "PL": "#ff7f0e",  # Orange
            "CF": "#2ca02c",  # Green
            "EQ": "#d62728",  # Red
            "CI": "#9467bd",  # Purple
        }

    def format_currency(self, value: float, unit: str = "원") -> str:
        """Format currency values for display"""
        if value is None or value == 0:
            return "0원"

        if abs(value) >= 1e12:  # 조
            return f"{value/1e12:.1f}조{unit}"
        elif abs(value) >= 1e8:  # 억
            return f"{value/1e8:.1f}억{unit}"
        elif abs(value) >= 1e4:  # 만
            return f"{value/1e4:.1f}만{unit}"
        else:
            return f"{value:,.0f}{unit}"

    def create_hierarchical_sunburst(
        self, data: List[Dict], title: str = "재무제표 계층 구조"
    ) -> go.Figure:
        """Create hierarchical sunburst chart"""
        if not data:
            return go.Figure()

        # Prepare data for sunburst
        df = pd.DataFrame(data)

        # Create hierarchical structure
        labels = []
        parents = []
        values = []
        colors = []

        for _, row in df.iterrows():
            category_path = row.get("category_path", "")
            if not category_path:
                continue

            path_parts = category_path.split(">")
            section = path_parts[0] if path_parts else "Unknown"

            for i, part in enumerate(path_parts):
                if i == 0:
                    parent = ""
                else:
                    parent = ">".join(path_parts[:i])

                labels.append(part)
                parents.append(parent)
                values.append(row.get("total_value", 0))
                colors.append(self.color_palette.get(section, "#636363"))

        fig = go.Figure(
            go.Sunburst(
                labels=labels,
                parents=parents,
                values=values,
                branchvalues="total",
                hovertemplate="<b>%{label}</b><br>값: %{value:,.0f}원<extra></extra>",
                marker=dict(colors=colors),
            )
        )

        fig.update_layout(title=title, font_size=12, margin=dict(t=50, l=0, r=0, b=0))

        return fig

    def create_financial_trend_chart(
        self, data: List[Dict], title: str = "재무 트렌드 분석"
    ) -> go.Figure:
        """Create financial trend line chart"""
        if not data:
            return go.Figure()

        df = pd.DataFrame(data)

        # Group by item_name and create trend lines
        fig = go.Figure()

        for item in df["item_name"].unique():
            item_data = df[df["item_name"] == item].sort_values("year")

            fig.add_trace(
                go.Scatter(
                    x=item_data["year"],
                    y=item_data["values_current"],
                    mode="lines+markers",
                    name=item,
                    hovertemplate=f"<b>{item}</b><br>연도: %{{x}}<br>값: %{{y:,.0f}}원<extra></extra>",
                )
            )

        fig.update_layout(
            title=title,
            xaxis_title="연도",
            yaxis_title="금액 (원)",
            hovermode="closest",
            legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.01),
        )

        return fig

    def create_category_bar_chart(
        self, data: List[Dict], title: str = "카테고리별 분석"
    ) -> go.Figure:
        """Create category comparison bar chart"""
        if not data:
            return go.Figure()

        df = pd.DataFrame(data)

        # Sort by value
        df = df.sort_values("total_value", ascending=True)

        fig = go.Figure(
            go.Bar(
                x=df["total_value"],
                y=df["category"],
                orientation="h",
                hovertemplate="<b>%{y}</b><br>값: %{x:,.0f}원<extra></extra>",
                marker_color="lightblue",
            )
        )

        fig.update_layout(
            title=title,
            xaxis_title="금액 (원)",
            yaxis_title="카테고리",
            height=max(400, len(df) * 30),
        )

        return fig

    def create_growth_rate_chart(
        self, data: List[Dict], title: str = "성장률 분석"
    ) -> go.Figure:
        """Create growth rate analysis chart"""
        if not data:
            return go.Figure()

        df = pd.DataFrame(data)

        # Create color mapping based on growth rate
        colors = ["red" if x < 0 else "green" for x in df["growth_rate"]]

        fig = go.Figure(
            go.Bar(
                x=df["item_name"],
                y=df["growth_rate"],
                marker_color=colors,
                hovertemplate="<b>%{x}</b><br>성장률: %{y:.1f}%<extra></extra>",
            )
        )

        # Add zero line
        fig.add_hline(y=0, line_dash="dash", line_color="black", opacity=0.5)

        fig.update_layout(
            title=title,
            xaxis_title="재무 항목",
            yaxis_title="성장률 (%)",
            xaxis_tickangle=-45,
            height=max(400, len(df) * 30),
        )

        return fig

    def create_subsidiary_network(
        self, data: List[Dict], title: str = "종속기업 관계 네트워크"
    ) -> go.Figure:
        """Create subsidiary relationship network diagram"""
        if not data:
            return go.Figure()

        # Prepare node and edge data
        nodes = set()
        edges = []

        for record in data:
            company = record.get("company", "삼성전자")
            subsidiary = record.get("subsidiary", "")
            rel_type = record.get("relationship_type", "")

            if company and subsidiary:
                nodes.add(company)
                nodes.add(subsidiary)
                edges.append((company, subsidiary, rel_type))

        # Create network layout
        node_list = list(nodes)
        node_positions = {}

        # Simple circular layout
        import math

        center_x, center_y = 0, 0
        radius = 2

        for i, node in enumerate(node_list):
            angle = 2 * math.pi * i / len(node_list)
            x = center_x + radius * math.cos(angle)
            y = center_y + radius * math.sin(angle)
            node_positions[node] = (x, y)

        # Create edges
        edge_x = []
        edge_y = []
        edge_info = []

        for start, end, rel_type in edges:
            if start in node_positions and end in node_positions:
                x0, y0 = node_positions[start]
                x1, y1 = node_positions[end]
                edge_x.extend([x0, x1, None])
                edge_y.extend([y0, y1, None])
                edge_info.append(rel_type)

        # Create nodes
        node_x = [node_positions[node][0] for node in node_list]
        node_y = [node_positions[node][1] for node in node_list]
        node_text = node_list

        fig = go.Figure()

        # Add edges
        fig.add_trace(
            go.Scatter(
                x=edge_x,
                y=edge_y,
                line=dict(width=2, color="lightgray"),
                hoverinfo="none",
                mode="lines",
                showlegend=False,
            )
        )

        # Add nodes
        fig.add_trace(
            go.Scatter(
                x=node_x,
                y=node_y,
                mode="markers+text",
                marker=dict(size=20, color="lightblue"),
                text=node_text,
                textposition="middle center",
                hovertemplate="<b>%{text}</b><extra></extra>",
                showlegend=False,
            )
        )

        fig.update_layout(
            title=title,
            showlegend=False,
            hovermode="closest",
            margin=dict(b=20, l=5, r=5, t=40),
            annotations=[
                dict(
                    text="종속기업 관계 네트워크",
                    showarrow=False,
                    xref="paper",
                    yref="paper",
                    x=0.005,
                    y=-0.002,
                    xanchor="left",
                    yanchor="bottom",
                    font=dict(color="black", size=12),
                )
            ],
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
        )

        return fig

    def create_section_summary_chart(
        self, data: List[Dict], title: str = "재무제표 섹션별 요약"
    ) -> go.Figure:
        """Create financial statement section summary pie chart"""
        if not data:
            return go.Figure()

        df = pd.DataFrame(data)

        # Map section codes to Korean names
        section_names = {
            "BS": "재무상태표",
            "PL": "손익계산서",
            "CF": "현금흐름표",
            "EQ": "자본변동표",
            "CI": "포괄손익계산서",
        }

        df["section_name"] = (
            df["section_code"].map(section_names).fillna(df["section_code"])
        )

        fig = go.Figure(
            data=[
                go.Pie(
                    labels=df["section_name"],
                    values=df["total_value"],
                    hovertemplate="<b>%{label}</b><br>값: %{value:,.0f}원<br>비율: %{percent}<extra></extra>",
                    marker_colors=[
                        self.color_palette.get(code, "#636363")
                        for code in df["section_code"]
                    ],
                )
            ]
        )

        fig.update_layout(title=title, font_size=12)

        return fig

    def create_year_comparison_chart(
        self, data: List[Dict], title: str = "연도별 비교"
    ) -> go.Figure:
        """Create year-over-year comparison chart"""
        if not data:
            return go.Figure()

        df = pd.DataFrame(data)

        # Create grouped bar chart
        years = sorted(df["year"].unique())

        fig = go.Figure()

        for year in years:
            year_data = df[df["year"] == year]
            fig.add_trace(
                go.Bar(
                    name=str(year),
                    x=year_data["item_name"],
                    y=year_data["values_current"],
                    hovertemplate=f"<b>%{{x}}</b><br>{year}년: %{{y:,.0f}}원<extra></extra>",
                )
            )

        fig.update_layout(
            title=title,
            xaxis_title="재무 항목",
            yaxis_title="금액 (원)",
            barmode="group",
            xaxis_tickangle=-45,
        )

        return fig


# Global visualizer instance
visualizer = FinancialVisualizer()


# Streamlit helper functions
def display_financial_chart(
    data: List[Dict], chart_type: str, title: str = None
) -> None:
    """Display financial chart in Streamlit"""
    if not data:
        st.warning("표시할 데이터가 없습니다.")
        return

    if chart_type == "hierarchical":
        fig = visualizer.create_hierarchical_sunburst(data, title or "계층 구조")
    elif chart_type == "trend":
        fig = visualizer.create_financial_trend_chart(data, title or "트렌드 분석")
    elif chart_type == "category":
        fig = visualizer.create_category_bar_chart(data, title or "카테고리별 분석")
    elif chart_type == "growth":
        fig = visualizer.create_growth_rate_chart(data, title or "성장률 분석")
    elif chart_type == "network":
        fig = visualizer.create_subsidiary_network(data, title or "종속기업 관계")
    elif chart_type == "section":
        fig = visualizer.create_section_summary_chart(data, title or "섹션별 요약")
    elif chart_type == "year_comparison":
        fig = visualizer.create_year_comparison_chart(data, title or "연도별 비교")
    else:
        st.error(f"지원하지 않는 차트 유형: {chart_type}")
        return

    st.plotly_chart(fig, use_container_width=True)


def format_financial_value(value: float, unit: str = "원") -> str:
    """Format financial value for display"""
    return visualizer.format_currency(value, unit)


def create_data_table(data: List[Dict], title: str = "데이터 테이블") -> None:
    """Create formatted data table in Streamlit"""
    if not data:
        st.warning("표시할 데이터가 없습니다.")
        return

    df = pd.DataFrame(data)

    # Format currency columns
    for col in df.columns:
        if "value" in col.lower() or "amount" in col.lower():
            df[col] = df[col].apply(
                lambda x: format_financial_value(x) if pd.notnull(x) else x
            )

    st.subheader(title)
    st.dataframe(df, use_container_width=True)
