from __future__ import annotations

"""Utilities for handling note reference cells across ETL modules.

Provides helpers to consistently work with values that may be plain strings
or structured dicts like:
  {"type": "notes_reference", "note_numbers": [4,5], "original_value": "4, 5"}
"""

import re
from typing import Any, List


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
    """Extract list of integers from a note cell (dict or string)."""
    if isinstance(value, dict) and value.get("type") == "notes_reference":
        return [
            int(n)
            for n in value.get("note_numbers", [])
            if isinstance(n, (int, str)) and str(n).isdigit()
        ]

    text = normalize_note_cell(value)
    if not text:
        return []
    return [int(x) for x in re.findall(r"\d+", text)]
