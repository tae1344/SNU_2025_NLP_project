from __future__ import annotations

"""ETL configuration and data source management.

Centralizes configuration for the Neo4j ETL pipeline to avoid hardcoded values.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
import json


@dataclass(frozen=True)
class ETLConfig:
    """Configuration for ETL pipeline."""

    # Company information
    company_name: str = "삼성전자"

    # Data paths
    processed_data_dir: Path = Path("data/processed")

    # File patterns
    processed_file_pattern: str = "감사보고서_{year}_parser_v3.json"

    # Year range
    start_year: int = 2014
    end_year: int = 2024

    # Financial statement sections
    fs_sections: List[str] = None

    def __post_init__(self):
        if self.fs_sections is None:
            object.__setattr__(self, "fs_sections", ["BS", "PL", "CI", "CF", "EQ"])

    def get_processed_files(self, years: Optional[List[int]] = None) -> List[Path]:
        """Get list of processed JSON files for specified years.

        Args:
            years: List of years to include. If None, uses all available years.

        Returns:
            List of Path objects to processed JSON files.
        """
        if years is None:
            years = list(range(self.start_year, self.end_year + 1))

        files = []
        for year in years:
            file_path = self.processed_data_dir / self.processed_file_pattern.format(
                year=year
            )
            if file_path.exists():
                files.append(file_path)

        return files

    def get_available_years(self) -> List[int]:
        """Get list of years for which processed files exist."""
        years = []
        for year in range(self.start_year, self.end_year + 1):
            file_path = self.processed_data_dir / self.processed_file_pattern.format(
                year=year
            )
            if file_path.exists():
                years.append(year)
        return years


def extract_company_info_from_data(processed_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract company information from processed JSON data.

    Args:
        processed_data: Parsed JSON data from audit report

    Returns:
        Company info dict with name, year, and other metadata
    """
    # Try to get company name from content or default
    company_name = "삼성전자"  # Default for Samsung reports

    # Extract from various sources if available
    sections = processed_data.get("sections", [])
    for section in sections:
        tables = section.get("tables", [])
        for table in tables:
            data_rows = table.get("data", [])
            for row in data_rows:
                for value in row.values():
                    if isinstance(value, str) and "주식회사" in value:
                        # Extract company name
                        if "삼성전자주식회사" in value:
                            company_name = "삼성전자"
                        break

    # Extract year
    year = processed_data.get("metadata", {}).get("report_year")
    if not year:
        # Try to extract from source filename
        source_file = processed_data.get("metadata", {}).get("source_file", "")
        for test_year in range(2014, 2025):
            if str(test_year) in source_file:
                year = test_year
                break
        if not year:
            year = 2014  # Default fallback

    return {
        "name": company_name,
        "year": year,
        "source_file": processed_data.get("metadata", {}).get("source_file", ""),
        "report_year": year,
    }


def load_etl_config(config_path: Optional[Path] = None) -> ETLConfig:
    """Load ETL configuration from file or use defaults.

    Args:
        config_path: Path to configuration file. If None, uses defaults.

    Returns:
        ETLConfig instance
    """
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config_data = json.load(f)

        return ETLConfig(
            company_name=config_data.get("company_name", "삼성전자"),
            processed_data_dir=Path(
                config_data.get("processed_data_dir", "data/processed")
            ),
            processed_file_pattern=config_data.get(
                "processed_file_pattern", "감사보고서_{year}_parser_v3.json"
            ),
            start_year=config_data.get("start_year", 2014),
            end_year=config_data.get("end_year", 2024),
            fs_sections=config_data.get("fs_sections", ["BS", "PL", "CF", "EQ"]),
        )

    return ETLConfig()


# Default configuration instance
DEFAULT_CONFIG = ETLConfig()
