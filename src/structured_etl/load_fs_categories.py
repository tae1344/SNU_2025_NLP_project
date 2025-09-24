from __future__ import annotations

"""Load FS_CATEGORY hierarchy and HAS_CATEGORY relationships.

Extracts financial statement category hierarchy from processed JSON tables
and creates nested category structures for BS/PL/CI/CF/EQ sections.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_fs_section_id, build_category_id
from .etl_config import (
    ETLConfig,
    read_fs_tables_cache,
    build_cached_indices_map,
    DEFAULT_CONFIG,
)
from .note_utils import normalize_note_cell
from .taxonomy_config import BS_TOP_LEVEL_PATTERNS, EQ_TOP_LEVEL_PATTERNS

# "매 출",
# "영업이익",
# "당기순이익",
# "영업활동",
# "투자활동",
# "재무활동",
# "포괄손익",
# "총포괄손익",


ROMAN_NUMERALS = ["Ⅰ.", "Ⅱ.", "Ⅲ.", "Ⅳ.", "Ⅴ.", "Ⅵ.", "Ⅶ.", "Ⅷ.", "Ⅸ.", "Ⅹ."]
NUMBERS = ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
KOREAN_ALPHAS = [
    "가.",
    "나.",
    "다.",
    "라.",
    "마.",
    "바.",
    "사.",
    "아.",
    "자.",
    "차.",
    "카.",
    "타.",
    "파.",
    "하.",
]


def _has_numbering_prefix(name: str) -> bool:
    """Return True if the name starts with any numbering prefix (Roman, numeric, Korean alpha)."""
    return (
        any(name.startswith(roman) for roman in ROMAN_NUMERALS)
        or any(name.startswith(i) for i in NUMBERS)
        or any(name.startswith(letter) for letter in KOREAN_ALPHAS)
    )


def extract_category_hierarchy(
    table_data: List[Dict[str, Any]], section_code: str
) -> List[Dict[str, Any]]:
    """Extract category hierarchy from a financial statement table.

    Args:
        table_data: Table data from processed JSON
        section_code: BS/PL/CI/CF/EQ section code

    Returns:
        List of category info dicts with hierarchy paths
    """
    categories = []
    # Track hierarchical context: level -> full path built so far
    # Level 1 parent is the section root
    last_path_by_level: Dict[int, str] = {0: section_code}

    for row in table_data:
        category_name = row.get("과 목", "").strip()
        if not category_name or category_name in ["과 목", ""]:
            continue

        # Determine hierarchy level based on formatting patterns
        level = determine_hierarchy_level(category_name, section_code)

        # Clean category name
        clean_name = clean_category_name(category_name)

        # Build hierarchical path using nearest parent level
        parent_level = max(0, level - 1)
        parent_path = last_path_by_level.get(parent_level, section_code)
        category_path = f"{parent_path}>{clean_name}"
        # Update context: current level path, and discard deeper stale levels
        last_path_by_level[level] = category_path
        for lv in list(last_path_by_level.keys()):
            if lv > level:
                last_path_by_level.pop(lv, None)

        note_cell = row.get("주석")
        note_refs = (
            row.get("주석", {}).get("note_numbers", [])
            if isinstance(row.get("주석"), dict)
            else []
        )

        # Build search keys from full and parent paths
        search_keys = _build_search_keys(category_path, parent_path)

        categories.append(
            {
                "name": clean_name,
                "original_name": category_name,
                "level": level,
                "path": category_path,
                "parent_path": parent_path,
                "section_code": section_code,
                "has_notes": bool(note_cell),
                "note_references": note_refs,
                **search_keys,
            }
        )

    return categories


def determine_hierarchy_level(category_name: str, section_code: str) -> int:
    """Determine hierarchy level based on category name patterns."""
    name = category_name.strip()

    # Level 1: Top-level section headers (자산, 부채, 자본, etc.)
    # - BS patterns are plain tokens (substring match)
    # - EQ patterns are regex strings (date labels like 2024.12.31(당기말))
    # Check if it's a standalone top-level category (no numbering)
    name_clean = name.lower().replace(" ", "")

    # First, match EQ regex patterns (date labels should be top-level regardless of numbering)
    for regex_pattern in EQ_TOP_LEVEL_PATTERNS:
        try:
            if re.search(regex_pattern, name):
                return 1
        except re.error:
            # If an EQ pattern is malformed, ignore and continue
            continue

    # Then, match BS token patterns by substring
    for token in BS_TOP_LEVEL_PATTERNS:
        token_clean = token.replace(" ", "")
        if token_clean in name_clean and not _has_numbering_prefix(name):
            return 1

    # Level 2: Roman numerals indicate major sections
    if any(roman in name for roman in ROMAN_NUMERALS):
        return 2

    # Level 3: Numbers indicate subsections (support multi-digit like 11., 12.)
    if re.match(r"^\d+\.\s*", name):
        return 3

    # Level 4: Korean letters indicate sub-subsections
    if any(name.startswith(letter) for letter in KOREAN_ALPHAS):
        return 4

    # Level 5: Detailed sub-items (often indented or have specific patterns)
    if any(pattern in name for pattern in ["후속적으로", "전기이월", "미처분"]):
        return 5

    # Default level for unmatched items
    return 3


def clean_category_name(name: str) -> str:
    """Clean category name by removing formatting characters."""
    # Remove Roman numerals and numbers
    cleaned = name
    for roman in ROMAN_NUMERALS:
        cleaned = cleaned.replace(roman, "").strip()

    # Note: do not use NUMBERS list for removal to avoid partial deletions (e.g., '11.' -> '1')

    # Remove letter prefixes
    for letter in KOREAN_ALPHAS:
        cleaned = cleaned.replace(f"{letter} ", "").strip()

    # Clean up spacing
    cleaned = " ".join(cleaned.split())

    # Detect date-like prefix (e.g., 2024.12.31(당기말)) to avoid stripping the year
    is_date_prefix = bool(re.match(r"^\d{4}\s*\.\s*\d{1,2}\s*\.\s*\d{1,2}", cleaned))

    # Remove numeric/bullet prefixes (only when followed by space to avoid dates)
    # Examples: "11. 제목", "(11) 제목", "11) 제목"
    if not is_date_prefix:
        cleaned = re.sub(r"^\d+\.\s+", "", cleaned)
        cleaned = re.sub(r"^\(\d+\)\s*", "", cleaned)
        cleaned = re.sub(r"^\d+\)\s*", "", cleaned)

    # Normalize spaces around and inside parentheses
    cleaned = re.sub(r"\(\s+", "(", cleaned)
    cleaned = re.sub(r"\s+\)", ")", cleaned)
    cleaned = re.sub(r"\s+\(", "(", cleaned)  # remove space before '('

    # Join spaced Hangul inside parentheses as well
    def _join_hangul_in_parens(m):
        inner = m.group(1)
        # collapse spaces between Hangul letters
        inner = re.sub(r"([가-힣])\s+([가-힣])", r"\1\2", inner)
        return f"({inner})"

    cleaned = re.sub(r"\(([^)]*)\)", _join_hangul_in_parens, cleaned)

    # Join runs of single-character Hangul tokens only (preserve normal word spaces)
    # e.g., ["영","업","이","익"] -> "영업이익" but keep "기타 투자활동" as-is
    token_list = cleaned.split(" ") if cleaned else []
    segments: List[str] = []
    i = 0
    while i < len(token_list):
        if not token_list[i]:
            i += 1
            continue
        if len(token_list[i]) == 1 and re.match(r"^[가-힣]$", token_list[i]):
            j = i
            while (
                j < len(token_list)
                and len(token_list[j]) == 1
                and re.match(r"^[가-힣]$", token_list[j])
            ):
                j += 1
            segments.append("".join(token_list[i:j]))
            i = j
        else:
            # Join single Hangul followed by token starting with Hangul or '(' (e.g., '비' + '용(수익)')
            if (
                len(token_list[i]) == 1
                and re.match(r"^[가-힣]$", token_list[i])
                and i + 1 < len(token_list)
                and re.match(r"^[가-힣(]", token_list[i + 1])
            ):
                segments.append(token_list[i] + token_list[i + 1])
                i += 2
                continue
            segments.append(token_list[i])
            i += 1
    cleaned = " ".join([s for s in segments if s])
    # Final fix: remove space when Hangul is followed by Hangul immediately before '('
    # e.g., "법인세비 용(수익)" -> "법인세비용(수익)", "영업이 익(손실)" -> "영업이익(손실)"
    cleaned = re.sub(r"([가-힣])\s+(?=[가-힣]\()", r"\1", cleaned)
    return cleaned


def build_category_path(name: str, level: int, section_code: str) -> str:
    """Build hierarchical path for category."""
    # For now, use simple path structure
    # In production, this would maintain parent-child relationships
    return f"{section_code}>{name}"


def _normalize_component(text: str) -> str:
    """Normalize a single category component into a search-friendly slug.

    - Lowercase
    - Collapse whitespace to single underscores
    - Remove brackets and most punctuation
    - Keep Korean letters and ASCII alphanumerics
    """
    t = (text or "").strip().lower()
    # Replace whitespace with underscores
    t = "_".join(t.split())
    # Remove common brackets and quotes
    t = re.sub(r"[\(\)\[\]\{\}\"\'`]+", "", t)
    # Replace remaining non-word chars (except underscores) with nothing
    t = re.sub(r"[^0-9a-z가-힣_]", "", t)
    # Collapse multiple underscores
    t = re.sub(r"_+", "_", t).strip("_")
    return t


def _build_search_keys(full_path: str, parent_path: str) -> Dict[str, Any]:
    """Build search-friendly keys for full and parent paths.

    - path_normalized: normalized full path (lowercased + slugged components joined by '>')
    - path_tokens: space-separated tokens for fulltext search
    - path_key: compact full path removing non-alphanumerics except '>'
    - parent_path_normalized: normalized parent path
    """

    def norm_path(p: str) -> Tuple[str, str, str]:
        if not p:
            return "", "", ""
        parts = [s.strip() for s in p.split(">") if s.strip()]
        # normalize each component
        norm_parts = [_normalize_component(s) for s in parts]
        path_normalized = ">".join(norm_parts)
        path_tokens = " ".join(norm_parts)
        compact = ">".join(re.sub(r"[^0-9a-z가-힣]", "", s) for s in norm_parts)
        return path_normalized, path_tokens, compact

    fp_norm, fp_tokens, fp_compact = norm_path(full_path)
    pp_norm, _, _ = norm_path(parent_path)

    return {
        "path_normalized": fp_norm,
        "path_tokens": fp_tokens,
        "path_key": fp_compact,
        "parent_path_normalized": pp_norm,
    }


def load_fs_category_nodes(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Load FS_CATEGORY nodes and HAS_CATEGORY relationships with deduplication.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)  # TODO : 회사 id가 중복 생성되는지 체크

    all_categories: Dict[Tuple[str, str], Dict[str, Any]] = (
        {}
    )  # (section_code, name) -> category_info

    # Load FS tables cache once
    fs_tables_cache = read_fs_tables_cache()

    # Process all files to collect categories
    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Extract categories from each section
        sections = data.get("sections", [])
        # Per-file cache entry
        cache_entry = fs_tables_cache.get("files", {}).get(file_path.name, {})
        cached_fs_sections = cache_entry.get("fs_sections", {})

        for section in sections:
            tables = section.get("tables", [])
            section_title = section.get("title", "")

            # Only process Financial Statements section using cached indices
            if "재 무 제 표" not in section_title or not cached_fs_sections:
                continue

            # Build allowed indices and reverse mapping index -> FS code
            allowed_indices, index_to_code = build_cached_indices_map(cache_entry)

            for table_idx, table in enumerate(tables):
                if table_idx not in allowed_indices:
                    continue

                table_data = table.get("data", [])
                if not table_data or "과 목" not in table_data[0]:
                    continue

                # Use section code from cache mapping
                section_code = index_to_code.get(table_idx, "")
                if not section_code:
                    continue

                categories = extract_category_hierarchy(table_data, section_code)

                for category in categories:
                    key = (category["section_code"], category["name"])

                    # Deduplicate: keep the one with more information
                    if key not in all_categories:
                        all_categories[key] = category
                    else:
                        existing = all_categories[key]
                        # Prefer categories with notes or higher level (more important)
                        if (
                            category.get("has_notes", False)
                            and not existing.get("has_notes", False)
                        ) or (category.get("level", 3) < existing.get("level", 3)):
                            all_categories[key] = category

    print(
        f"Extracted {len(all_categories)} unique FS categories from {len(processed_files)} files"
    )

    # Group by section for statistics
    section_stats = {}
    for (section_code, name), category in all_categories.items():
        if section_code not in section_stats:
            section_stats[section_code] = {"count": 0, "with_notes": 0}
        section_stats[section_code]["count"] += 1
        if category.get("has_notes", False):
            section_stats[section_code]["with_notes"] += 1

    for section_code, stats in section_stats.items():
        notes_pct = (
            (stats["with_notes"] / stats["count"] * 100) if stats["count"] > 0 else 0
        )
        print(
            f"  - {section_code}: {stats['count']} categories ({stats['with_notes']} with notes, {notes_pct:.1f}%)"
        )

    # Create FS_CATEGORY nodes and relationships
    created_count = 0
    for (section_code, category_name), category in all_categories.items():
        category_path = category["path"]
        category_id = build_category_id(company_name, section_code, category_path)
        fs_section_id = build_fs_section_id(company_name, section_code)

        # Create FS_CATEGORY node with enhanced properties
        session.run(
            f"""
            MERGE (cat:{NODE_TYPES['FS_CATEGORY']} {{ {PROPS['id']}: $category_id }})
            ON CREATE SET 
                cat.{PROPS['name']} = $name,
                cat.{PROPS['category_path']} = $path,
                cat.{PROPS['section_code']} = $section_code,
                cat.{PROPS['company']} = $company_name,
                cat.hierarchy_level = $level,
                cat.has_notes = $has_notes,
                cat.original_name = $original_name
            ON MATCH SET
                cat.{PROPS['name']} = coalesce(cat.{PROPS['name']}, $name),
                cat.{PROPS['category_path']} = coalesce(cat.{PROPS['category_path']}, $path),
                cat.{PROPS['section_code']} = coalesce(cat.{PROPS['section_code']}, $section_code),
                cat.{PROPS['company']} = coalesce(cat.{PROPS['company']}, $company_name),
                cat.hierarchy_level = coalesce(cat.hierarchy_level, $level),
                cat.has_notes = coalesce(cat.has_notes, $has_notes),
                cat.original_name = coalesce(cat.original_name, $original_name)
            """,
            {
                "category_id": category_id,
                "name": category_name,
                "path": category_path,
                "section_code": section_code,
                "company_name": company_name,
                "level": category.get("level", 3),
                "has_notes": category.get("has_notes", False),
                "original_name": category.get("original_name", category_name),
            },
        )

        # Create HAS_CATEGORY relationship from FS_SECTION to FS_CATEGORY
        session.run(
            f"""
            MATCH (fs:{NODE_TYPES['FS_SECTION']} {{ {PROPS['id']}: $fs_section_id }})
            MATCH (cat:{NODE_TYPES['FS_CATEGORY']} {{ {PROPS['id']}: $category_id }})
            MERGE (fs)-[r:{RELATIONSHIP_TYPES['HAS_CATEGORY']}]->(cat)
            ON CREATE SET r.has_notes = $has_notes
            """,
            {
                "fs_section_id": fs_section_id,
                "category_id": category_id,
                "has_notes": category.get("has_notes", False),
            },
        )

        created_count += 1

    print(f"✅ Created/updated {created_count} FS category nodes and relationships")


if __name__ == "__main__":
    # Test extraction with available files
    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        # Test with the most recent file
        test_file = available_files[-1]
        print(f"Testing FS categories extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Find financial tables using cached indices
        sections = data.get("sections", [])
        categories_found = 0

        cache = read_fs_tables_cache()
        cache_entry = cache.get("files", {}).get(test_file.name, {})
        cached_fs_sections = cache_entry.get("fs_sections", {})

        if not cached_fs_sections:
            print("No cache found for this file; skipping cache-based test.")
        else:
            # Build index->section_code mapping
            _, index_to_code = build_cached_indices_map(cache_entry)

            for section in sections:
                tables = section.get("tables", [])
                section_title = section.get("title", "")
                if "재 무 제 표" not in section_title:
                    continue

                for table_idx, table in enumerate(tables):
                    if table_idx not in index_to_code:
                        continue
                    table_data = table.get("data", [])
                    if not table_data or "과 목" not in table_data[0]:
                        continue

                    section_code = index_to_code[table_idx]
                    categories = extract_category_hierarchy(table_data, section_code)
                    categories_found += len(categories)
                    print(
                        f"\n=== {section_code} Categories ({len(categories)} found) ==="
                    )

                    print(f"categories: {categories[3]}\n")
                    for cat in categories[:]:  # Show first 5
                        print(
                            f"  Level {cat['level']}: {cat['name']} (Path: {cat['path']})"
                        )

        print(f"\nTotal categories found: {categories_found}")
    else:
        print("No processed files found for testing")
