from __future__ import annotations

"""Utilities for handling note reference cells across ETL modules.

Provides helpers to consistently work with values that may be plain strings
or structured dicts like:
  {"type": "notes_reference", "note_numbers": [4,5], "original_value": "4, 5"}
"""

import re
from typing import Any, List, Optional


def is_note_column(column_name: str | None) -> bool:
    """Return True if the column name looks like a note reference column.

    Checks space/case-insensitively for common variants: 주석, 주 석, note, notes, 비고.
    """
    if not column_name:
        return False
    name = str(column_name).strip().lower().replace(" ", "")
    return any(tok in name for tok in ("주석", "note", "notes", "비고"))


def normalize_note_cell(value: Any) -> str:
    """Render note cell value into a human-readable string.

    - If dict(notes_reference), return original_value if present, else join note_numbers.
    - If None, return empty string.
    - Else return trimmed string form.
    """
    if isinstance(value, dict):
        return (
            value.get("original_value")
            or ", ".join(str(n) for n in value.get("note_numbers", []))
            or ""
        )
    return "" if value is None else str(value).strip()


def extract_note_numbers(value: Any) -> List[int]:
    """Extract list of integers from a note cell (dict or string).

    Enhanced to handle various note reference patterns:
    - "4, 5" -> [4, 5]
    - "Note 4" -> [4]
    - "주석 4" -> [4]
    - "4)" -> [4]
    - "④" -> [4] (circled numbers)
    - "4, 5, 7, 28" -> [4, 5, 7, 28]
    """
    if isinstance(value, dict) and value.get("type") == "notes_reference":
        return [
            int(n)
            for n in value.get("note_numbers", [])
            if isinstance(n, (int, str)) and str(n).isdigit()
        ]

    text = normalize_note_cell(value)
    if not text:
        return []

    # Enhanced pattern matching for various note reference formats
    numbers = []

    # Handle circled numbers (①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳)
    circled_map = {
        "①": 1,
        "②": 2,
        "③": 3,
        "④": 4,
        "⑤": 5,
        "⑥": 6,
        "⑦": 7,
        "⑧": 8,
        "⑨": 9,
        "⑩": 10,
        "⑪": 11,
        "⑫": 12,
        "⑬": 13,
        "⑭": 14,
        "⑮": 15,
        "⑯": 16,
        "⑰": 17,
        "⑱": 18,
        "⑲": 19,
        "⑳": 20,
    }

    for circled, num in circled_map.items():
        if circled in text:
            numbers.append(num)

    # Handle regular number patterns
    # Look for patterns like "Note 4", "주석 4", "4)", etc.
    patterns = [
        r"(?:Note|note|주석|주 석)\s*(\d+)",  # "Note 4", "주석 4"
        r"(\d+)\)",  # "4)"
        r"(\d+)\s*[,，;；]",  # "4,", "4;"
        r"(\d+)(?:\s|$)",  # "4 " or "4" at end
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text)
        for match in matches:
            if match.isdigit():
                numbers.append(int(match))

    # Fallback to simple digit extraction
    if not numbers:
        numbers = [int(x) for x in re.findall(r"\d+", text)]

    # Remove duplicates and sort
    return sorted(list(set(numbers)))


def normalize_notes_array(notes: Any) -> Optional[List[str]]:
    """Convert note cell content to an array of strings acceptable by Neo4j.

    - None -> None
    - str -> [str]
    - list -> each element stringified if not primitive
    - dict/others -> [json.dumps(obj)]
    """
    if notes is None:
        return None
    if isinstance(notes, str):
        s = notes.strip()
        return [s] if s else None
    if isinstance(notes, list):
        result: List[str] = []
        for item in notes:
            if item is None:
                continue
            if isinstance(item, str):
                s = item.strip()
                if s:
                    result.append(s)
            else:
                try:
                    import json as _json

                    result.append(_json.dumps(item, ensure_ascii=False))
                except Exception:
                    result.append(str(item))
        return result or None
    # Fallback for dict or other types
    try:
        import json as _json

        return [_json.dumps(notes, ensure_ascii=False)]
    except Exception:
        return [str(notes)]
