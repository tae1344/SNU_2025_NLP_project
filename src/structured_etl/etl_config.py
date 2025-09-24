from __future__ import annotations

"""ETL configuration and data source management.

Centralizes configuration for the Neo4j ETL pipeline to avoid hardcoded values.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any
import json

# Cache file path for FS table indices
FS_TABLES_CACHE_PATH = Path("results") / "fs_tables_index.json"


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


# Helper: save cache payload to disk
def save_fs_tables_cache(cache_payload: Dict[str, Any]) -> None:
    try:
        FS_TABLES_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        cache_payload.setdefault("metadata", {})["generated_at"] = (
            __import__("datetime").datetime.now().isoformat()
        )
        with open(FS_TABLES_CACHE_PATH, "w", encoding="utf-8") as cf:
            json.dump(cache_payload, cf, ensure_ascii=False, indent=2)
        print(f"Saved FS table index cache: {FS_TABLES_CACHE_PATH}")
    except Exception as e:
        print(f"Failed to write FS table index cache: {e}")


# Helper: read cache payload from disk (for other ETL steps)
def read_fs_tables_cache() -> Dict[str, Any]:
    try:
        if FS_TABLES_CACHE_PATH.exists():
            with open(FS_TABLES_CACHE_PATH, "r", encoding="utf-8") as cf:
                return json.load(cf)
    except Exception as e:
        print(f"Failed to read FS table index cache: {e}")
    return {"metadata": {"version": 1}, "files": {}}


# Helper: from a per-file cache entry, build allowed indices set and index->code map
def build_cached_indices_map(
    cache_entry: Dict[str, Any],
) -> tuple[set[int], Dict[int, str]]:
    allowed_indices: set[int] = set()
    index_to_code: Dict[int, str] = {}
    cached_fs_sections = (cache_entry or {}).get("fs_sections", {})
    for code, info in cached_fs_sections.items():
        for idx in info.get("table_indices", []):
            try:
                idx_int = int(idx)
                allowed_indices.add(idx_int)
                index_to_code[idx_int] = code
            except Exception:
                continue
    return allowed_indices, index_to_code


# Default configuration instance
DEFAULT_CONFIG = ETLConfig()
