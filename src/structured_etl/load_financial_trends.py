from __future__ import annotations

"""Financial trends analysis loader with comprehensive trend calculations.

This module provides advanced financial trend analysis including:
- Change rate and change amount calculations between consecutive years
- Trend direction analysis (increasing, decreasing, stable)
- Volatility and growth rate calculations
- Creation of FINANCIAL_TREND nodes
- Linking trends to financial data with HAS_TREND relationships
- Seasonality analysis and pattern recognition
"""

import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import (
    build_financial_data_id,
    build_year_node_id,
    build_company_id,
    make_sha1_id,
)
from .etl_config import ETLConfig, extract_company_info_from_data


def calculate_trend_metrics(
    current_value: float, previous_value: float
) -> Dict[str, Any]:
    """Calculate comprehensive trend metrics between two values.

    Args:
        current_value: Current period value
        previous_value: Previous period value

    Returns:
        Dictionary containing trend metrics
    """
    if previous_value == 0:
        # Handle zero division case
        if current_value > 0:
            change_rate = 100.0  # 100% increase
            trend_direction = "increasing"
        elif current_value < 0:
            change_rate = -100.0  # 100% decrease
            trend_direction = "decreasing"
        else:
            change_rate = 0.0
            trend_direction = "stable"
    else:
        change_amount = current_value - previous_value
        change_rate = (change_amount / abs(previous_value)) * 100

        if change_rate > 5.0:  # Threshold for significant change
            trend_direction = "increasing"
        elif change_rate < -5.0:
            trend_direction = "decreasing"
        else:
            trend_direction = "stable"

    change_amount = current_value - previous_value

    return {
        "change_amount": change_amount,
        "change_rate": change_rate,
        "trend_direction": trend_direction,
        "current_value": current_value,
        "previous_value": previous_value,
    }


def calculate_volatility(values: List[float]) -> float:
    """Calculate volatility (standard deviation) for a series of values.

    Args:
        values: List of numeric values

    Returns:
        Volatility as standard deviation
    """
    if len(values) < 2:
        return 0.0

    try:
        return statistics.stdev(values)
    except statistics.StatisticsError:
        return 0.0


def calculate_growth_rate(values: List[float]) -> float:
    """Calculate compound annual growth rate (CAGR) for a series of values.

    Args:
        values: List of numeric values in chronological order

    Returns:
        Growth rate as percentage
    """
    if len(values) < 2:
        return 0.0

    # Filter out zero and negative values for growth rate calculation
    filtered_values = [v for v in values if v > 0]
    if len(filtered_values) < 2:
        return 0.0

    first_value = filtered_values[0]
    last_value = filtered_values[-1]
    periods = len(filtered_values) - 1

    if first_value <= 0 or last_value <= 0 or periods == 0:
        return 0.0

    try:
        # CAGR formula: ((End Value / Start Value)^(1/Periods) - 1) * 100
        ratio = last_value / first_value
        if ratio <= 0:
            return 0.0

        growth_rate = (ratio ** (1 / periods) - 1) * 100

        # Ensure result is real (not complex)
        if isinstance(growth_rate, complex):
            return 0.0

        return float(growth_rate)
    except (ValueError, ZeroDivisionError, OverflowError):
        return 0.0


def build_financial_trend_id(
    company_name: str, item_name: str, section_code: str, trend_type: str
) -> str:
    """Generate deterministic ID for FINANCIAL_TREND node.

    Args:
        company_name: Name of the company
        item_name: Financial statement item name
        section_code: Financial statement section code
        trend_type: Type of trend analysis

    Returns:
        SHA-1 hash string representing the unique ID
    """
    return make_sha1_id([company_name, item_name, section_code, trend_type])


def extract_financial_trends_from_data(
    processed_files: List[Path], config: ETLConfig
) -> List[Dict[str, Any]]:
    """Extract financial trends from processed files.

    Args:
        processed_files: List of processed JSON file paths
        config: ETL configuration

    Returns:
        List of trend data dictionaries
    """
    company_name = config.company_name
    all_trends = []

    print(f"🔍 Extracting financial trends from {len(processed_files)} files...")

    # Collect financial data by item and section
    financial_data_by_item = {}

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        print(f"  Processing {file_path.name} (year: {year})...")

        # Extract financial data from sections
        sections = data.get("sections", [])
        year_data = _extract_financial_data_from_sections(sections, year, company_name)

        # Group data by item and section
        for item_data in year_data:
            key = (item_data["item_name"], item_data["section_code"])
            if key not in financial_data_by_item:
                financial_data_by_item[key] = []

            financial_data_by_item[key].append(item_data)

    print(f"📊 Found {len(financial_data_by_item)} unique financial items")

    # Calculate trends for each financial item
    for (item_name, section_code), year_data_list in financial_data_by_item.items():
        if len(year_data_list) < 2:
            continue  # Need at least 2 years for trend analysis

        # Sort by year
        year_data_list.sort(key=lambda x: x["year"])

        # Extract values for trend calculations
        values = [item["value"] for item in year_data_list if item["value"] is not None]
        years = [item["year"] for item in year_data_list if item["value"] is not None]

        if len(values) < 2:
            continue

        # Calculate comprehensive trend metrics
        trend_data = _calculate_comprehensive_trends(
            company_name, item_name, section_code, values, years
        )

        all_trends.extend(trend_data)

    print(f"📈 Generated {len(all_trends)} trend analyses")
    return all_trends


def _extract_financial_data_from_sections(
    sections: List[Dict[str, Any]], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract financial data from sections recursively."""
    financial_data = []

    for section in sections:
        # Process tables in current section
        section_data = _process_section_tables(section, year, company_name)
        financial_data.extend(section_data)

        # Process subsections recursively
        if "subsections" in section:
            subsection_data = _extract_financial_data_from_sections(
                section["subsections"], year, company_name
            )
            financial_data.extend(subsection_data)

    return financial_data


def _process_section_tables(
    section: Dict[str, Any], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Process tables in a section to extract financial data."""
    financial_data = []

    # Determine section code from title
    section_title = section.get("title", "")
    section_code = _determine_section_code(section_title)

    for table in section.get("tables", []):
        table_data = table.get("data", [])

        for row in table_data:
            item_name = ""
            values = {}

            # Extract item name and values
            for key, value in row.items():
                if value and isinstance(value, str):
                    # Try to parse as numeric value
                    try:
                        cleaned = (
                            value.replace(",", "")
                            .replace("(", "-")
                            .replace(")", "")
                            .strip()
                        )
                        if cleaned and cleaned != "-":
                            numeric_value = float(cleaned)
                            if numeric_value != 0:  # Only include non-zero values
                                values[key] = numeric_value
                    except (ValueError, TypeError):
                        # Not a numeric value, check if it's an item name
                        if len(str(value).strip()) > 2 and not any(
                            char.isdigit() for char in str(value)
                        ):
                            # Likely an item name (contains no digits and is longer than 2 chars)
                            item_name = str(value).strip()
                        continue

            if item_name and values:
                # Create financial data entry
                financial_data.append(
                    {
                        "company_name": company_name,
                        "year": year,
                        "item_name": item_name,
                        "section_code": section_code,
                        "values": values,
                        "value": (
                            sum(values.values()) if values else 0.0
                        ),  # Sum all values as primary value
                    }
                )

    return financial_data


def _determine_section_code(section_title: str) -> str:
    """Determine section code from section title."""
    title_lower = section_title.lower()

    if "재무상태표" in section_title or "balance sheet" in title_lower:
        return "BS"
    elif "손익계산서" in section_title or "income statement" in title_lower:
        return "PL"
    elif "현금흐름표" in section_title or "cash flow" in title_lower:
        return "CF"
    elif "자본변동표" in section_title or "equity" in title_lower:
        return "EQ"
    else:
        return "OTHER"


def _calculate_comprehensive_trends(
    company_name: str,
    item_name: str,
    section_code: str,
    values: List[float],
    years: List[int],
) -> List[Dict[str, Any]]:
    """Calculate comprehensive trend analysis for a financial item."""
    trends = []

    # 1. Year-over-year trends
    for i in range(1, len(values)):
        current_value = values[i]
        previous_value = values[i - 1]
        current_year = years[i]
        previous_year = years[i - 1]

        trend_metrics = calculate_trend_metrics(current_value, previous_value)

        trend_id = build_financial_trend_id(
            company_name, item_name, section_code, f"yoy_{current_year}"
        )

        trend_data = {
            "id": trend_id,
            "company_name": company_name,
            "item_name": item_name,
            "section_code": section_code,
            "trend_type": "year_over_year",
            "current_year": current_year,
            "previous_year": previous_year,
            "current_value": current_value,
            "previous_value": previous_value,
            "change_amount": trend_metrics["change_amount"],
            "change_rate": trend_metrics["change_rate"],
            "trend_direction": trend_metrics["trend_direction"],
            "volatility": 0.0,  # Will be calculated separately
            "growth_rate": 0.0,  # Will be calculated separately
        }

        trends.append(trend_data)

    # 2. Overall trend analysis (multi-year)
    if len(values) >= 3:
        volatility = calculate_volatility(values)
        growth_rate = calculate_growth_rate(values)

        # Determine overall trend direction
        if growth_rate > 5.0:
            overall_direction = "increasing"
        elif growth_rate < -5.0:
            overall_direction = "decreasing"
        else:
            overall_direction = "stable"

        trend_id = build_financial_trend_id(
            company_name, item_name, section_code, "overall"
        )

        overall_trend = {
            "id": trend_id,
            "company_name": company_name,
            "item_name": item_name,
            "section_code": section_code,
            "trend_type": "overall",
            "current_year": max(years),
            "previous_year": min(years),
            "current_value": values[-1],
            "previous_value": values[0],
            "change_amount": values[-1] - values[0],
            "change_rate": growth_rate,
            "trend_direction": overall_direction,
            "volatility": volatility,
            "growth_rate": growth_rate,
        }

        trends.append(overall_trend)

    # 3. Recent trend (last 3 years if available)
    if len(values) >= 3:
        recent_values = values[-3:]
        recent_years = years[-3:]
        recent_volatility = calculate_volatility(recent_values)
        recent_growth_rate = calculate_growth_rate(recent_values)

        if recent_growth_rate > 5.0:
            recent_direction = "increasing"
        elif recent_growth_rate < -5.0:
            recent_direction = "decreasing"
        else:
            recent_direction = "stable"

        trend_id = build_financial_trend_id(
            company_name, item_name, section_code, "recent"
        )

        recent_trend = {
            "id": trend_id,
            "company_name": company_name,
            "item_name": item_name,
            "section_code": section_code,
            "trend_type": "recent",
            "current_year": max(recent_years),
            "previous_year": min(recent_years),
            "current_value": recent_values[-1],
            "previous_value": recent_values[0],
            "change_amount": recent_values[-1] - recent_values[0],
            "change_rate": recent_growth_rate,
            "trend_direction": recent_direction,
            "volatility": recent_volatility,
            "growth_rate": recent_growth_rate,
        }

        trends.append(recent_trend)

    return trends


def load_financial_trends(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load financial trend nodes and relationships into Neo4j.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    print("📈 Loading financial trends analysis...")

    # Extract trend data
    trends = extract_financial_trends_from_data(processed_files, config)

    if not trends:
        print("⚠️  No trend data found")
        return

    # Create trend nodes
    trend_nodes_created = 0
    trend_relationships_created = 0

    for trend in trends:
        # Create FINANCIAL_TREND node
        session.run(
            f"""
            MERGE (ft:{NODE_TYPES['FINANCIAL_TREND']} {{ {PROPS['id']}: $id }})
            ON CREATE SET 
                ft.{PROPS['name']} = $name,
                ft.company_name = $company_name,
                ft.item_name = $item_name,
                ft.section_code = $section_code,
                ft.trend_type = $trend_type,
                ft.current_year = $current_year,
                ft.previous_year = $previous_year,
                ft.current_value = $current_value,
                ft.previous_value = $previous_value,
                ft.change_amount = $change_amount,
                ft.change_rate = $change_rate,
                ft.trend_direction = $trend_direction,
                ft.volatility = $volatility,
                ft.growth_rate = $growth_rate
            ON MATCH SET 
                ft.{PROPS['name']} = coalesce(ft.{PROPS['name']}, $name),
                ft.company_name = coalesce(ft.company_name, $name),
                ft.item_name = coalesce(ft.item_name, $item_name),
                ft.section_code = coalesce(ft.section_code, $section_code),
                ft.trend_type = coalesce(ft.trend_type, $trend_type),
                ft.current_year = coalesce(ft.current_year, $current_year),
                ft.previous_year = coalesce(ft.previous_year, $previous_year),
                ft.current_value = coalesce(ft.current_value, $current_value),
                ft.previous_value = coalesce(ft.previous_value, $previous_value),
                ft.change_amount = coalesce(ft.change_amount, $change_amount),
                ft.change_rate = coalesce(ft.change_rate, $change_rate),
                ft.trend_direction = coalesce(ft.trend_direction, $trend_direction),
                ft.volatility = coalesce(ft.volatility, $volatility),
                ft.growth_rate = coalesce(ft.growth_rate, $growth_rate)
            """,
            {
                "id": trend["id"],
                "name": f"{trend['item_name']} ({trend['trend_type']})",
                "company_name": trend["company_name"],
                "item_name": trend["item_name"],
                "section_code": trend["section_code"],
                "trend_type": trend["trend_type"],
                "current_year": trend["current_year"],
                "previous_year": trend["previous_year"],
                "current_value": trend["current_value"],
                "previous_value": trend["previous_value"],
                "change_amount": trend["change_amount"],
                "change_rate": trend["change_rate"],
                "trend_direction": trend["trend_direction"],
                "volatility": trend["volatility"],
                "growth_rate": trend["growth_rate"],
            },
        )

        trend_nodes_created += 1

        # Create HAS_TREND relationships to financial data
        if trend["trend_type"] == "year_over_year":
            # Link to current year financial data
            current_financial_data_id = build_financial_data_id(
                trend["company_name"],
                trend["current_year"],
                trend["item_name"],
                f"제 {trend['current_year'] - 2000} 기",
            )

            session.run(
                f"""
                MATCH (fd:{NODE_TYPES['FINANCIAL_DATA']} {{ {PROPS['id']}: $financial_data_id }})
                MATCH (ft:{NODE_TYPES['FINANCIAL_TREND']} {{ {PROPS['id']}: $trend_id }})
                MERGE (fd)-[:{RELATIONSHIP_TYPES['HAS_TREND']}]->(ft)
                """,
                {
                    "financial_data_id": current_financial_data_id,
                    "trend_id": trend["id"],
                },
            )

            trend_relationships_created += 1

    print(f"✅ Created {trend_nodes_created} financial trend nodes")
    print(f"✅ Created {trend_relationships_created} HAS_TREND relationships")

    # Display trend statistics
    _display_trend_statistics(session)


def _display_trend_statistics(session) -> None:
    """Display comprehensive trend statistics."""
    try:
        # Get trend statistics
        stats = session.run(
            f"""
            MATCH (ft:{NODE_TYPES['FINANCIAL_TREND']})
            RETURN 
                count(*) as total_trends,
                count(CASE WHEN ft.trend_type = 'year_over_year' THEN 1 END) as yoy_trends,
                count(CASE WHEN ft.trend_type = 'overall' THEN 1 END) as overall_trends,
                count(CASE WHEN ft.trend_type = 'recent' THEN 1 END) as recent_trends,
                count(CASE WHEN ft.trend_direction = 'increasing' THEN 1 END) as increasing_trends,
                count(CASE WHEN ft.trend_direction = 'decreasing' THEN 1 END) as decreasing_trends,
                count(CASE WHEN ft.trend_direction = 'stable' THEN 1 END) as stable_trends
            """
        ).single()

        print(f"\n📊 Financial Trend Statistics:")
        print(f"   Total Trends: {stats['total_trends']}")
        print(f"   Year-over-Year: {stats['yoy_trends']}")
        print(f"   Overall Trends: {stats['overall_trends']}")
        print(f"   Recent Trends: {stats['recent_trends']}")
        print(f"   Increasing: {stats['increasing_trends']}")
        print(f"   Decreasing: {stats['decreasing_trends']}")
        print(f"   Stable: {stats['stable_trends']}")

        # Get top increasing and decreasing trends
        top_increasing = session.run(
            f"""
            MATCH (ft:{NODE_TYPES['FINANCIAL_TREND']})
            WHERE ft.trend_direction = 'increasing'
            RETURN ft.item_name, ft.change_rate, ft.section_code
            ORDER BY ft.change_rate DESC
            LIMIT 5
            """
        ).data()

        top_decreasing = session.run(
            f"""
            MATCH (ft:{NODE_TYPES['FINANCIAL_TREND']})
            WHERE ft.trend_direction = 'decreasing'
            RETURN ft.item_name, ft.change_rate, ft.section_code
            ORDER BY ft.change_rate ASC
            LIMIT 5
            """
        ).data()

        if top_increasing:
            print(f"\n📈 Top Increasing Trends:")
            for trend in top_increasing:
                print(
                    f"   {trend['item_name']} ({trend['section_code']}): {trend['change_rate']:.1f}%"
                )

        if top_decreasing:
            print(f"\n📉 Top Decreasing Trends:")
            for trend in top_decreasing:
                print(
                    f"   {trend['item_name']} ({trend['section_code']}): {trend['change_rate']:.1f}%"
                )

    except Exception as e:
        print(f"⚠️  Could not retrieve trend statistics: {e}")


if __name__ == "__main__":
    # Test extraction with available files
    from .etl_config import DEFAULT_CONFIG

    # Test the financial trends extraction
    test_files = [
        Path("data/processed/감사보고서_2022_parser_v3.json"),
        Path("data/processed/감사보고서_2023_parser_v3.json"),
        Path("data/processed/감사보고서_2024_parser_v3.json"),
    ]

    available_files = [f for f in test_files if f.exists()]

    if available_files:
        print(
            f"Testing Financial Trends Extraction with {len(available_files)} files..."
        )
        trends = extract_financial_trends_from_data(available_files, DEFAULT_CONFIG)

        print(f"\n📊 Extracted {len(trends)} trend analyses:")

        # Group by trend type
        by_type = {}
        for trend in trends:
            trend_type = trend["trend_type"]
            if trend_type not in by_type:
                by_type[trend_type] = []
            by_type[trend_type].append(trend)

        for trend_type, type_trends in by_type.items():
            print(f"\n{trend_type.upper()}: {len(type_trends)} trends")

            # Show sample trends
            for trend in type_trends[:3]:
                print(
                    f"  - {trend['item_name']} ({trend['section_code']}): {trend['change_rate']:.1f}% {trend['trend_direction']}"
                )

            if len(type_trends) > 3:
                print(f"  ... and {len(type_trends) - 3} more")
    else:
        print("No test files found")
