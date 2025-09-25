from __future__ import annotations

"""Load NOTE and NOTE_CATEGORY nodes and create relationships.

Extracts note information from processed JSON and classified notes data,
creating proper relationships between companies, notes, and categories.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Set, Optional

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import build_company_id, build_note_id, build_note_category_id
from .etl_config import ETLConfig, extract_company_info_from_data
import re


# def _has_better_structure(content1: str, content2: str) -> bool:
#     """Check if content1 has better structure than content2 for note merging.

#     Args:
#         content1: First content to compare
#         content2: Second content to compare

#     Returns:
#         True if content1 has better structure
#     """

#     def _calculate_structure_score(content: str) -> float:
#         """Calculate structure quality score for content."""
#         if not content or len(content.strip()) < 10:
#             return 0.0

#         score = 0.0

#         # Check for structured patterns (higher score for better structure)
#         structured_patterns = [
#             r"\d+\.\s+[^\\n]+",  # Numbered lists: 1. item
#             r"[가-힣]\.\s+[^\\n]+",  # Korean letter lists: 가. item
#             r"\([0-9가-힣]+\)\s+[^\\n]+",  # Parenthesized items: (1) item
#             r"-\s+[^\\n]+",  # Dash lists: - item
#         ]

#         for pattern in structured_patterns:
#             matches = re.findall(pattern, content)
#             score += len(matches) * 0.1

#         # Check for complete sentences (proper punctuation)
#         sentence_endings = content.count(".") + content.count("?") + content.count("!")
#         score += sentence_endings * 0.05

#         # Check for paragraph breaks (double newlines)
#         paragraphs = content.count("\\n\\n")
#         score += paragraphs * 0.2

#         # Penalty for very short content
#         if len(content.strip()) < 50:
#             score *= 0.5

#         return score

#     score1 = _calculate_structure_score(content1)
#     score2 = _calculate_structure_score(content2)

#     # content1 is better if it has significantly higher structure score
#     return score1 > score2 * 1.2


def extract_notes_from_section(
    section: Dict[str, Any], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract note information from a notes section with deduplication.

    Args:
        section: Section data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of note info dictionaries
    """
    notes_list = []
    title = section.get("title", "").strip()

    # Only process notes sections
    if "주석" not in title:
        return notes_list

    # Extract from detailed_notes if available
    detailed_notes = section.get("detailed_notes", [])

    # Group notes by note_number to handle duplicates
    notes_by_number = {}

    for note_data in detailed_notes:
        note_number = note_data.get("note_number")
        note_title = note_data.get("title", "").strip()
        note_content = note_data.get("content", "").strip()

        if not note_number:
            continue

        # Skip very short content (likely parsing artifacts)
        if len(note_content.strip()) < 20:
            continue

        if note_number not in notes_by_number:
            # First occurrence of this note number
            notes_by_number[note_number] = {
                "note_number": note_number,
                "title": note_title,
                "content": note_content,
                "year": year,
                "company_name": company_name,
                "content_length": len(note_content),
                "category": None,  # Will be filled from classified data
                "subcategory": None,
                "confidence": None,
                "keywords": [],
                "source_count": 1,
            }
        else:
            # Merge with existing note (intelligent merging for large notes)
            existing = notes_by_number[note_number]

            # For note 2 (large note pattern), combine all sub-notes sequentially
            if note_number == 2:
                # Check if we need to initialize sub_notes list
                if "sub_notes" not in existing:
                    existing["sub_notes"] = [
                        {
                            "title": existing["title"],
                            "content": existing["content"],
                            "order": 0,
                        }
                    ]
                    existing["merged_reason"] = "sequential_combination"

                # Add current note to sub_notes list
                existing["sub_notes"].append(
                    {
                        "title": note_title,
                        "content": note_content,
                        "order": existing["source_count"],  # Track order
                    }
                )

                # Combine all sub-notes content sequentially
                combined_content = ""
                combined_title = ""

                # Sort by order to maintain sequence
                sorted_sub_notes = sorted(
                    existing["sub_notes"], key=lambda x: x["order"]
                )

                for i, sub_note in enumerate(sorted_sub_notes):
                    if sub_note["content"].strip():
                        if i > 0:
                            combined_content += "\n\n"  # Add spacing between sections
                        combined_content += sub_note["content"]

                        # Use the first non-empty title as main title
                        if not combined_title and sub_note["title"].strip():
                            combined_title = sub_note["title"]

                # Update with combined content
                existing["title"] = combined_title or existing["title"]
                existing["content"] = combined_content
                existing["content_length"] = len(combined_content)
                existing["merged_reason"] = "sequential_combination"
            else:
                # For other notes, use simple length-based selection
                if len(note_content) > len(existing["content"]):
                    existing["title"] = note_title
                    existing["content"] = note_content
                    existing["content_length"] = len(note_content)
                    existing["merged_reason"] = "longer_content"
                else:
                    existing["merged_reason"] = "kept_existing"

            # Track how many sources we merged
            existing["source_count"] += 1

    # Convert to list and add metadata about merging
    for note_info in notes_by_number.values():
        if note_info["source_count"] > 1:
            # Add metadata about merging
            note_info["merged_sources"] = note_info["source_count"]
            merge_reason = note_info.get("merged_reason", "unknown")

            # Create descriptive title based on merge reason
            if merge_reason == "sequential_combination":
                note_info["note_title"] = (
                    f"{note_info['title']} (combined from {note_info['source_count']} sequential sub-notes)"
                )
            elif merge_reason == "longer_content":
                note_info["note_title"] = (
                    f"{note_info['title']} (merged from {note_info['source_count']} sources - selected longest)"
                )
            elif merge_reason == "better_structure":
                note_info["note_title"] = (
                    f"{note_info['title']} (merged from {note_info['source_count']} sources - selected best structure)"
                )
            else:
                note_info["note_title"] = (
                    f"{note_info['title']} (merged from {note_info['source_count']} sources)"
                )

            # Add merge quality indicator
            note_info["merge_quality"] = (
                "high"
                if note_info["source_count"] > 10
                else "medium" if note_info["source_count"] > 5 else "low"
            )
        else:
            note_info["note_title"] = note_info["title"]
            note_info["merged_sources"] = 1
            note_info["merge_quality"] = "single"

        # Remove internal tracking fields
        if "source_count" in note_info:
            del note_info["source_count"]
        if "merged_reason" in note_info:
            del note_info["merged_reason"]

        notes_list.append(note_info)

    return notes_list


def load_classified_notes_data(classified_notes_path: Path) -> List[Dict[str, Any]]:
    """Load classified notes data from JSON file.

    Args:
        classified_notes_path: Path to classified notes JSON file

    Returns:
        List of classified note dictionaries
    """
    if not classified_notes_path.exists():
        print(f"Warning: Classified notes file not found: {classified_notes_path}")
        return []

    with open(classified_notes_path, "r", encoding="utf-8") as f:
        classified_data = json.load(f)

    return classified_data if isinstance(classified_data, list) else []


def merge_notes_with_classification(
    notes_from_json: List[Dict[str, Any]], classified_notes: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Merge notes from processed JSON with classification data.

    Args:
        notes_from_json: Notes extracted from processed JSON
        classified_notes: Notes with classification data

    Returns:
        List of merged note dictionaries
    """
    # Create lookup dictionary for classified notes
    classified_lookup = {}
    for classified_note in classified_notes:
        year = classified_note.get("year")
        note_number = classified_note.get("note_number")
        if year and note_number:
            key = (year, note_number)
            classified_lookup[key] = classified_note

    # Merge data
    merged_notes = []

    for note in notes_from_json:
        year = note.get("year")
        note_number = note.get("note_number")
        key = (year, note_number)

        # Start with original note data
        merged_note = note.copy()

        # Add classification data if available
        if key in classified_lookup:
            classified = classified_lookup[key]
            merged_note.update(
                {
                    "category": classified.get("category"),
                    "subcategory": classified.get("subcategory"),
                    "confidence": classified.get("confidence"),
                    "keywords": classified.get("keywords", []),
                }
            )

        merged_notes.append(merged_note)

    # Add any classified notes that weren't in the processed JSON
    processed_keys = {(note["year"], note["note_number"]) for note in notes_from_json}

    for classified_note in classified_notes:
        year = classified_note.get("year")
        note_number = classified_note.get("note_number")
        key = (year, note_number)

        if key not in processed_keys:
            # Create note from classified data only
            merged_note = {
                "note_number": note_number,
                "title": classified_note.get("title", ""),
                "content": classified_note.get("content", ""),
                "year": year,
                "company_name": "삼성전자",  # Default for this project
                "content_length": len(classified_note.get("content", "")),
                "category": classified_note.get("category"),
                "subcategory": classified_note.get("subcategory"),
                "confidence": classified_note.get("confidence"),
                "keywords": classified_note.get("keywords", []),
            }
            merged_notes.append(merged_note)

    return merged_notes


def classify_notes_realtime(processed_files: List[Path]) -> List[Dict[str, Any]]:
    """Classify notes in real-time using note_classifier.py

    Args:
        processed_files: List of processed JSON file paths

    Returns:
        List of classified note dictionaries
    """
    try:
        # Import here to avoid circular dependencies
        import sys

        sys.path.append(str(Path(__file__).parent.parent))
        from note_classifier import NoteClassifier

        classifier = NoteClassifier()
        all_classified = []

        for file_path in processed_files:
            print(f"Classifying notes from: {file_path.name}")
            classifications = classifier.extract_notes_from_json(file_path)

            # Convert NoteClassification objects to dictionaries
            for classification in classifications:
                classified_note = {
                    "note_number": classification.note_number,
                    "title": classification.title,
                    "content": classification.content,
                    "category": classification.category,
                    "subcategory": classification.subcategory,
                    "confidence": classification.confidence,
                    "keywords": classification.keywords,
                    "year": classification.year,
                }
                all_classified.append(classified_note)

        return all_classified

    except ImportError as e:
        print(f"Warning: Could not import note_classifier: {e}")
        return []
    except Exception as e:
        print(f"Warning: Error during real-time classification: {e}")
        return []


def load_note_nodes(session, processed_files: List[Path], config: ETLConfig) -> None:
    """Load NOTE and NOTE_CATEGORY nodes with relationships.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)

    # Try real-time classification first, fallback to pre-classified data
    print("Attempting real-time note classification...")
    classified_notes = classify_notes_realtime(processed_files)

    if not classified_notes:
        print("Falling back to pre-classified data...")
        classified_notes = load_classified_notes_data(config.classified_notes_path)

    print(f"Using {len(classified_notes)} classified notes")

    # Extract notes from processed JSON files
    all_notes_from_json: List[Dict[str, Any]] = []
    year_file_map = {}  # Track which years we have files for

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]
        year_file_map[year] = file_path.name

        # Extract notes from sections
        sections = data.get("sections", [])
        for section in sections:
            notes_list = extract_notes_from_section(section, year, company_name)
            all_notes_from_json.extend(notes_list)

    print(f"Extracted {len(all_notes_from_json)} notes from processed JSON")
    print(f"Years processed: {sorted(year_file_map.keys())}")

    # Filter classified notes to only include years we have data for
    relevant_classified_notes = [
        note for note in classified_notes if note.get("year") in year_file_map
    ]
    print(
        f"Relevant classified notes (matching years): {len(relevant_classified_notes)}"
    )

    # Merge with classification data
    merged_notes = merge_notes_with_classification(
        all_notes_from_json, relevant_classified_notes
    )
    print(f"Merged total: {len(merged_notes)} notes")

    # Collect unique categories
    all_categories: Set[str] = set()
    for note in merged_notes:
        if note.get("category"):
            all_categories.add(note["category"])
        if note.get("subcategory"):
            all_categories.add(note["subcategory"])

    print(f"Found {len(all_categories)} unique categories: {list(all_categories)}")

    # Create NOTE_CATEGORY nodes
    for category_name in all_categories:
        category_id = build_note_category_id(category_name)

        session.run(
            f"""
            MERGE (nc:{NODE_TYPES['NOTE_CATEGORY']} {{ {PROPS['id']}: $category_id }})
            ON CREATE SET 
                nc.{PROPS['name']} = $category_name,
                nc.{PROPS['category']} = $category_name
            ON MATCH SET
                nc.{PROPS['name']} = coalesce(nc.{PROPS['name']}, $category_name)
            """,
            {"category_id": category_id, "category_name": category_name},
        )

    # Create NOTE nodes and relationships
    for note in merged_notes:
        note_id = build_note_id(company_name, note["year"], note["note_number"])

        # Create NOTE node with enhanced properties
        session.run(
            f"""
            MERGE (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: $note_id }})
            ON CREATE SET 
                n.{PROPS['note_number']} = $note_number,
                n.{PROPS['name']} = $title,
                n.{PROPS['text']} = $content,
                n.{PROPS['year']} = $year,
                n.{PROPS['company']} = $company_name,
                n.{PROPS['category']} = $category,
                n.{PROPS['confidence']} = $confidence,
                n.content_length = $content_length,
                n.merged_sources = $merged_sources,
                n.merge_quality = $merge_quality,
                n.created_from_data = true
            ON MATCH SET
                n.{PROPS['text']} = coalesce(n.{PROPS['text']}, $content),
                n.{PROPS['category']} = coalesce(n.{PROPS['category']}, $category),
                n.{PROPS['confidence']} = coalesce(n.{PROPS['confidence']}, $confidence),
                n.content_length = coalesce(n.content_length, $content_length),
                n.merged_sources = coalesce(n.merged_sources, $merged_sources),
                n.merge_quality = coalesce(n.merge_quality, $merge_quality),
                n.created_from_data = coalesce(n.created_from_data, true)
            """,
            {
                "note_id": note_id,
                "note_number": note["note_number"],
                "title": note.get("note_title", note["title"]),
                "content": note["content"],
                "year": note["year"],
                "company_name": note["company_name"],
                "category": note.get("category"),
                "confidence": note.get("confidence"),
                "content_length": note["content_length"],
                "merged_sources": note.get("merged_sources", 1),
                "merge_quality": note.get("merge_quality", "single"),
            },
        )

        # Create HAS_NOTE relationship from COMPANY to NOTE
        session.run(
            f"""
            MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
            MATCH (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: $note_id }})
            MERGE (c)-[:{RELATIONSHIP_TYPES['HAS_NOTE']}]->(n)
            """,
            {"company_id": company_id, "note_id": note_id},
        )

        # Create HAS_NOTE_CATEGORY relationships
        for category_field in ["category", "subcategory"]:
            category_value = note.get(category_field)
            if category_value:
                category_id = build_note_category_id(category_value)

                session.run(
                    f"""
                    MATCH (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: $note_id }})
                    MATCH (nc:{NODE_TYPES['NOTE_CATEGORY']} {{ {PROPS['id']}: $category_id }})
                    MERGE (n)-[:{RELATIONSHIP_TYPES['HAS_NOTE_CATEGORY']}]->(nc)
                    """,
                    {"note_id": note_id, "category_id": category_id},
                )


def create_links_to_note_relationships(
    session, processed_files: List[Path], config: ETLConfig
) -> None:
    """Create LINKS_TO_NOTE relationships between FS_CATEGORY and NOTE nodes.

    This function finds financial statement items that reference specific notes
    and creates relationships between them.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
    """
    company_name = config.company_name
    links_created = 0

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        # Look through all sections for tables with notes references
        sections = data.get("sections", [])
        for section in sections:
            tables = section.get("tables", [])

            for table in tables:
                # TODO: check
                if not table.get("metadata", {}).get("is_financial_table", False):
                    continue

                table_data = table.get("data", [])
                for row in table_data:
                    item_name = row.get("과 목", "").strip()
                    notes_ref = row.get("주석")

                    if not item_name or not isinstance(notes_ref, dict):
                        continue

                    if notes_ref.get("type") == "notes_reference":
                        note_numbers = notes_ref.get("note_numbers", [])

                        for note_number in note_numbers:
                            # Create LINKS_TO_NOTE relationship
                            note_id = build_note_id(company_name, year, note_number)

                            # Find matching FS_CATEGORY and NOTE, then create link
                            result = session.run(
                                f"""
                                MATCH (cat:{NODE_TYPES['FS_CATEGORY']})
                                WHERE cat.{PROPS['name']} CONTAINS $item_name
                                WITH cat LIMIT 1
                                MATCH (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: $note_id }})
                                MERGE (cat)-[r:{RELATIONSHIP_TYPES['LINKS_TO_NOTE']}]->(n)
                                RETURN cat.{PROPS['name']} AS category_name, n.{PROPS['note_number']} AS note_num
                                """,
                                {"item_name": item_name, "note_id": note_id},
                            )

                            # Check if link was created
                            record = result.single()
                            if record:
                                links_created += 1
                                if links_created <= 5:  # Show first few links
                                    print(
                                        f"  Linked: {record['category_name']} -> Note {record['note_num']}"
                                    )
                            elif links_created <= 5:  # Show missing links for debugging
                                print(
                                    f"  No match for item: {item_name} -> Note {note_number}"
                                )

    print(f"Created {links_created} LINKS_TO_NOTE relationships")


if __name__ == "__main__":
    # Test notes extraction
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        # Test with the most recent file
        test_file = available_files[-1]
        print(f"Testing notes extraction with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]
        company_name = company_info["name"]

        print(f"Company: {company_name}, Year: {year}")

        # Extract notes from sections
        sections = data.get("sections", [])
        all_notes = []

        for section in sections:
            notes_list = extract_notes_from_section(section, year, company_name)
            all_notes.extend(notes_list)

        print(f"\nExtracted {len(all_notes)} notes from processed JSON:")
        for i, note in enumerate(all_notes[:5]):  # Show first 5
            print(
                f"  {i+1}. Note {note['note_number']}: {note['title'][:50]}... ({note['content_length']} chars)"
            )
        if len(all_notes) > 5:
            print(f"  ... and {len(all_notes) - 5} more")

        # Test real-time classification
        print(f"\nTesting real-time classification...")
        classified_notes = classify_notes_realtime([test_file])
        print(f"Real-time classified: {len(classified_notes)} notes")

        # Test merging
        merged_notes = merge_notes_with_classification(all_notes, classified_notes)
        print(f"Merged total: {len(merged_notes)} notes")

        # Show sample merged note with classification
        classified_notes_found = [n for n in merged_notes if n.get("category")]
        if classified_notes_found:
            sample = classified_notes_found[0]
            print(f"\nSample classified note:")
            print(f"  Number: {sample['note_number']}")
            print(f"  Title: {sample['title'][:50]}...")
            print(f"  Category: {sample.get('category', 'N/A')}")
            print(f"  Confidence: {sample.get('confidence', 'N/A')}")

        print(f"\nClassified notes: {len(classified_notes_found)}/{len(merged_notes)}")
    else:
        print("No processed files found for testing")
