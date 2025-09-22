#!/usr/bin/env python3
"""Create SEARCH_DOC nodes for text indexing and search functionality.

Creates searchable document nodes from sections, notes, and tables to enable
full-text search across the knowledge graph.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Set

from .kg_schema import NODE_TYPES, RELATIONSHIP_TYPES, PROPS
from .id_utils import (
    build_search_doc_id,
    build_company_id,
    build_note_id,
    build_fs_section_id,
)
from .etl_config import ETLConfig, extract_company_info_from_data


def clean_text_for_search(text: str, max_length: int = 10000) -> str:
    """Clean text for search indexing with performance optimization.

    Args:
        text: Raw text content
        max_length: Maximum length to process (for performance)

    Returns:
        Cleaned text suitable for search
    """
    if not text or not isinstance(text, str):
        return ""

    try:
        # Truncate very long text for performance
        if len(text) > max_length:
            text = text[:max_length]

        # Remove excessive whitespace and normalize (optimized)
        cleaned = re.sub(r"\s+", " ", text.strip())

        # Simplified character filtering for performance
        # Keep Korean, English, numbers, and basic punctuation
        cleaned = re.sub(r"[^\w\s가-힣.,;:()\-]", " ", cleaned)

        # Final cleanup
        cleaned = re.sub(r"\s+", " ", cleaned.strip())

        return cleaned
    except Exception as e:
        print(f"Warning: Error cleaning text: {e}")
        return str(text)[:max_length] if text else ""


def extract_section_search_docs(
    sections: List[Dict[str, Any]], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract search documents from sections.

    Args:
        sections: List of section data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of search document dictionaries
    """
    search_docs = []

    for section in sections:
        section_id = section.get("section_id", "")
        title = section.get("title", "")
        content = section.get("content", "")
        section_type = section.get("section_type", "")

        if not content or len(content.strip()) < 50:  # Skip very short sections
            continue

        # Clean content for search
        cleaned_content = clean_text_for_search(content)
        cleaned_title = clean_text_for_search(title)

        if len(cleaned_content) < 30:  # Skip after cleaning if still too short
            continue

        # Create search doc
        doc_anchor = f"section_{section_id}"
        search_doc = {
            "id": build_search_doc_id(company_name, year, "section", doc_anchor),
            "doc_type": "section",
            "title": cleaned_title,
            "content": cleaned_content,
            "year": year,
            "company_name": company_name,
            "source_anchor": doc_anchor,
            "section_type": section_type,
            "content_length": len(cleaned_content),
            "word_count": len(cleaned_content.split()),
            "original_section_id": section_id,
        }
        search_docs.append(search_doc)

        # Process subsections recursively
        if "subsections" in section:
            subsection_docs = extract_section_search_docs(
                section["subsections"], year, company_name
            )
            search_docs.extend(subsection_docs)

    return search_docs


def extract_note_search_docs(
    sections: List[Dict[str, Any]], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract search documents from notes.

    Args:
        sections: List of section data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of search document dictionaries for notes
    """
    search_docs = []

    for section in sections:
        # Process detailed notes
        detailed_notes = section.get("detailed_notes", [])

        # Group notes by note_number to handle fragmented notes (like Note 2)
        notes_by_number = {}
        for note in detailed_notes:
            note_number = note.get("note_number")
            if note_number not in notes_by_number:
                notes_by_number[note_number] = []
            notes_by_number[note_number].append(note)

        # Process each note number group
        for note_number, notes in notes_by_number.items():
            if len(notes) == 1:
                # Single note - process normally
                note = notes[0]
                title = note.get("title", "")
                content = note.get("content", "")

                if (
                    not content or len(content.strip()) < 100
                ):  # Notes should be substantial
                    continue

                # Clean content for search
                cleaned_content = clean_text_for_search(content)
                cleaned_title = clean_text_for_search(title)

                if len(cleaned_content) < 50:  # Skip after cleaning if still too short
                    continue

                # Create search doc
                doc_anchor = f"note_{note_number}"
                search_doc = {
                    "id": build_search_doc_id(company_name, year, "note", doc_anchor),
                    "doc_type": "note",
                    "title": cleaned_title,
                    "content": cleaned_content,
                    "year": year,
                    "company_name": company_name,
                    "source_anchor": doc_anchor,
                    "note_number": note_number,
                    "content_length": len(cleaned_content),
                    "word_count": len(cleaned_content.split()),
                    "original_note_id": build_note_id(company_name, year, note_number),
                }
                search_docs.append(search_doc)
            else:
                # Multiple notes with same number (fragmented note like Note 2)
                # Combine all sub-notes into a single comprehensive note
                combined_title = notes[0].get("title", "")  # Use first title as base
                combined_content_parts = []

                for i, note in enumerate(notes):
                    title = note.get("title", "")
                    content = note.get("content", "")

                    if (
                        content and len(content.strip()) >= 50
                    ):  # Include substantial content
                        if title and title != combined_title:
                            combined_content_parts.append(f"{title}: {content}")
                        else:
                            combined_content_parts.append(content)

                if combined_content_parts:
                    combined_content = "\n\n".join(combined_content_parts)

                    # Clean combined content for search
                    cleaned_content = clean_text_for_search(combined_content)
                    cleaned_title = clean_text_for_search(combined_title)

                    if (
                        len(cleaned_content) < 50
                    ):  # Skip after cleaning if still too short
                        continue

                    # Create search doc with combined content
                    doc_anchor = f"note_{note_number}_combined"
                    search_doc = {
                        "id": build_search_doc_id(
                            company_name, year, "note", doc_anchor
                        ),
                        "doc_type": "note",
                        "title": cleaned_title,
                        "content": cleaned_content,
                        "year": year,
                        "company_name": company_name,
                        "source_anchor": doc_anchor,
                        "note_number": note_number,
                        "content_length": len(cleaned_content),
                        "word_count": len(cleaned_content.split()),
                        "original_note_id": build_note_id(
                            company_name, year, note_number
                        ),
                        "sub_notes_count": len(notes),
                        "combined_from_fragments": True,
                    }
                    search_docs.append(search_doc)

        # Process subsections recursively
        if "subsections" in section:
            subsection_docs = extract_note_search_docs(
                section["subsections"], year, company_name
            )
            search_docs.extend(subsection_docs)

    return search_docs


def extract_table_search_docs(
    sections: List[Dict[str, Any]], year: int, company_name: str
) -> List[Dict[str, Any]]:
    """Extract search documents from tables.

    Args:
        sections: List of section data from processed JSON
        year: Reporting year
        company_name: Company name

    Returns:
        List of search document dictionaries for tables
    """
    search_docs = []

    for section in sections:
        section_title = section.get("title", "")
        tables = section.get("tables", [])

        for table_idx, table in enumerate(tables):
            table_data = table.get("data", [])
            metadata = table.get("metadata", {})
            is_financial = metadata.get("is_financial_table", False)

            if not table_data or len(table_data) < 2:  # Skip very small tables
                continue

            # Convert table data to searchable text
            table_text_parts = []

            # Add table context from section
            if section_title:
                table_text_parts.append(f"Table from: {section_title}")

            # Add table data as text
            for row in table_data:
                row_text = " ".join(
                    [
                        str(value)
                        for value in row.values()
                        if value is not None and str(value).strip()
                    ]
                )
                if row_text.strip():
                    table_text_parts.append(row_text.strip())

            if not table_text_parts:
                continue

            # Combine all table text
            table_content = "\n".join(table_text_parts)
            cleaned_content = clean_text_for_search(table_content)

            if len(cleaned_content) < 50:  # Skip very short table content
                continue

            # Create title for table
            table_title = f"Table {table_idx + 1}"
            if section_title:
                table_title += f" from {section_title}"
            if is_financial:
                table_title += " (Financial)"

            # Create search doc with unique anchor including section context
            section_id = section.get("section_id", f"section_{len(search_docs)}")
            doc_anchor = f"table_{section_id}_{table_idx}_{year}"
            search_doc = {
                "id": build_search_doc_id(company_name, year, "table", doc_anchor),
                "doc_type": "table",
                "title": clean_text_for_search(table_title),
                "content": cleaned_content,
                "year": year,
                "company_name": company_name,
                "source_anchor": doc_anchor,
                "table_index": table_idx,
                "is_financial_table": is_financial,
                "row_count": len(table_data),
                "column_count": len(table.get("columns", [])),
                "content_length": len(cleaned_content),
                "word_count": len(cleaned_content.split()),
                "section_title": section_title,
            }
            search_docs.append(search_doc)

        # Process subsections recursively
        if "subsections" in section:
            subsection_docs = extract_table_search_docs(
                section["subsections"], year, company_name
            )
            search_docs.extend(subsection_docs)

    return search_docs


def create_search_doc_nodes(
    session, processed_files: List[Path], config: ETLConfig, test_mode: bool = False
) -> Dict[str, Any]:
    """Create SEARCH_DOC nodes from sections, notes, and tables.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
        test_mode: If True, limit documents for testing. If False, process all data.

    Returns:
        Dictionary with operation results
    """
    company_name = config.company_name
    company_id = build_company_id(company_name)

    total_docs_created = 0
    docs_by_type = {"section": 0, "note": 0, "table": 0}

    print(f"Creating SEARCH_DOC nodes from {len(processed_files)} files...")

    for file_path in processed_files:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]

        print(f"  Processing {file_path.name} (year: {year})...")

        sections = data.get("sections", [])

        # Extract search docs from different sources
        print(f"    Extracting search documents...")

        if test_mode:
            # Test mode: Only notes, limited quantity
            note_docs = extract_note_search_docs(sections, year, company_name)
            all_docs = note_docs[:50] if len(note_docs) > 50 else note_docs
            batch_size = 10  # Small batches for testing
            print(f"    Found {len(all_docs)} documents (TEST MODE - limited)")
        else:
            # Production mode: All document types
            section_docs = extract_section_search_docs(sections, year, company_name)
            note_docs = extract_note_search_docs(sections, year, company_name)
            table_docs = extract_table_search_docs(sections, year, company_name)
            all_docs = section_docs + note_docs + table_docs
            batch_size = 100  # Larger batches for production
            print(
                f"    Found {len(section_docs)} section docs, {len(note_docs)} note docs, {len(table_docs)} table docs"
            )
            print(f"    Total: {len(all_docs)} documents")

        # Create SEARCH_DOC nodes in batches

        for i in range(0, len(all_docs), batch_size):
            batch = all_docs[i : i + batch_size]

            # Create nodes in batch
            batch_params = []
            for doc in batch:
                param = {
                    "doc_id": doc["id"],
                    "title": (
                        doc.get("title", "")[:500] if doc.get("title") else ""
                    ),  # Limit title length
                    "content": doc.get("content", "")[
                        :10000
                    ],  # Limit content length for performance
                    "year": doc["year"],
                    "company_name": doc["company_name"],
                    "doc_type": doc["doc_type"],
                    "source_anchor": doc["source_anchor"],
                    "content_length": doc["content_length"],
                    "word_count": doc["word_count"],
                    "note_number": None,  # Default values
                    "sub_notes_count": None,
                    "combined_from_fragments": None,
                }

                # Include note-specific properties if available
                if "note_number" in doc:
                    param["note_number"] = doc["note_number"]
                if "sub_notes_count" in doc:
                    param["sub_notes_count"] = doc["sub_notes_count"]
                if "combined_from_fragments" in doc:
                    param["combined_from_fragments"] = doc["combined_from_fragments"]

                # Include original_note_id if available
                if "original_note_id" in doc:
                    param["original_note_id"] = doc["original_note_id"]

                batch_params.append(param)

            # Batch create SEARCH_DOC nodes
            session.run(
                f"""
                UNWIND $batch AS doc
                MERGE (sd:{NODE_TYPES['SEARCH_DOC']} {{ {PROPS['id']}: doc.doc_id }})
                ON CREATE SET 
                    sd.{PROPS['name']} = doc.title,
                    sd.title = doc.title,
                    sd.{PROPS['text']} = doc.content,
                    sd.content = doc.content,
                    sd.{PROPS['year']} = doc.year,
                    sd.{PROPS['company']} = doc.company_name,
                    sd.doc_type = doc.doc_type,
                    sd.source_anchor = doc.source_anchor,
                    sd.content_length = doc.content_length,
                    sd.word_count = doc.word_count,
                    sd.note_number = doc.note_number,
                    sd.sub_notes_count = doc.sub_notes_count,
                    sd.combined_from_fragments = doc.combined_from_fragments
                ON MATCH SET
                    sd.{PROPS['name']} = coalesce(sd.{PROPS['name']}, doc.title),
                    sd.title = coalesce(sd.title, doc.title),
                    sd.{PROPS['text']} = coalesce(sd.{PROPS['text']}, doc.content),
                    sd.content = coalesce(sd.content, doc.content),
                    sd.content_length = coalesce(sd.content_length, doc.content_length),
                    sd.word_count = coalesce(sd.word_count, doc.word_count),
                    sd.note_number = coalesce(sd.note_number, doc.note_number),
                    sd.sub_notes_count = coalesce(sd.sub_notes_count, doc.sub_notes_count),
                    sd.combined_from_fragments = coalesce(sd.combined_from_fragments, doc.combined_from_fragments)
                """,
                {"batch": batch_params},
            )

            # Batch create relationships to COMPANY
            session.run(
                f"""
                UNWIND $batch AS doc
                MATCH (c:{NODE_TYPES['COMPANY']} {{ {PROPS['id']}: $company_id }})
                MATCH (sd:{NODE_TYPES['SEARCH_DOC']} {{ {PROPS['id']}: doc.doc_id }})
                MERGE (c)-[:{RELATIONSHIP_TYPES['RELATED_TO']}]->(sd)
                """,
                {"batch": batch_params, "company_id": company_id},
            )

            # Batch create NOTE relationships
            note_params = [
                {"doc_id": param["doc_id"], "note_id": param["original_note_id"]}
                for param in batch_params
                if param.get("doc_type") == "note" and "original_note_id" in param
            ]
            if note_params:
                session.run(
                    f"""
                    UNWIND $note_batch AS item
                    MATCH (n:{NODE_TYPES['NOTE']} {{ {PROPS['id']}: item.note_id }})
                    MATCH (sd:{NODE_TYPES['SEARCH_DOC']} {{ {PROPS['id']}: item.doc_id }})
                    MERGE (n)-[:{RELATIONSHIP_TYPES['RELATED_TO']}]->(sd)
                    """,
                    {"note_batch": note_params},
                )

            # Update counters
            for doc in batch:
                total_docs_created += 1
                docs_by_type[doc["doc_type"]] += 1

            # Progress indicator
            if i + batch_size < len(all_docs):
                print(f"    Processed {i + batch_size}/{len(all_docs)} documents...")
            else:
                print(
                    f"    Processed {len(all_docs)}/{len(all_docs)} documents (complete)"
                )

    # Summary
    result = {
        "status": "success",
        "total_docs_created": total_docs_created,
        "docs_by_type": docs_by_type,
        "files_processed": len(processed_files),
    }

    print(f"\n📊 SEARCH_DOC Creation Summary:")
    print(f"  Total documents created: {total_docs_created}")
    print(f"  By type:")
    for doc_type, count in docs_by_type.items():
        print(f"    {doc_type}: {count}")

    return result


def validate_search_docs(session, config: ETLConfig) -> Dict[str, Any]:
    """Validate created SEARCH_DOC nodes.

    Args:
        session: Neo4j session
        config: ETL configuration

    Returns:
        Dictionary with validation results
    """
    print("🔍 Validating SEARCH_DOC nodes...")

    # Count total search docs
    total_docs = session.run(
        f"""
        MATCH (sd:{NODE_TYPES['SEARCH_DOC']})
        RETURN count(sd) AS total_docs
        """
    ).single()["total_docs"]

    # Docs by type
    docs_by_type = session.run(
        f"""
        MATCH (sd:{NODE_TYPES['SEARCH_DOC']})
        RETURN sd.doc_type AS doc_type, count(sd) AS doc_count
        ORDER BY doc_count DESC
        """
    ).data()

    # Docs by year
    docs_by_year = session.run(
        f"""
        MATCH (sd:{NODE_TYPES['SEARCH_DOC']})
        RETURN sd.{PROPS['year']} AS year, count(sd) AS doc_count
        ORDER BY year DESC
        """
    ).data()

    # Average content length by type
    avg_length_by_type = session.run(
        f"""
        MATCH (sd:{NODE_TYPES['SEARCH_DOC']})
        RETURN sd.doc_type AS doc_type, 
               avg(sd.content_length) AS avg_length,
               avg(sd.word_count) AS avg_words
        ORDER BY avg_length DESC
        """
    ).data()

    # Sample docs
    sample_docs = session.run(
        f"""
        MATCH (sd:{NODE_TYPES['SEARCH_DOC']})
        RETURN sd.{PROPS['name']} AS title,
               sd.doc_type AS doc_type,
               sd.{PROPS['year']} AS year,
               sd.content_length AS length
        ORDER BY length DESC
        LIMIT 5
        """
    ).data()

    print(f"  Total SEARCH_DOC nodes: {total_docs}")

    if docs_by_type:
        print(f"  Documents by type:")
        for record in docs_by_type:
            print(f"    {record['doc_type']}: {record['doc_count']}")

    if docs_by_year:
        print(f"  Documents by year:")
        for record in docs_by_year:
            print(f"    {record['year']}: {record['doc_count']}")

    if avg_length_by_type:
        print(f"  Average content length by type:")
        for record in avg_length_by_type:
            print(
                f"    {record['doc_type']}: {record['avg_length']:.0f} chars, {record['avg_words']:.0f} words"
            )

    if sample_docs:
        print(f"  Largest documents:")
        for record in sample_docs:
            title = (
                record["title"][:50] + "..."
                if len(record["title"]) > 50
                else record["title"]
            )
            print(
                f"    {record['doc_type']} ({record['year']}): {title} ({record['length']:,} chars)"
            )

    return {
        "total_docs": total_docs,
        "docs_by_type": {r["doc_type"]: r["doc_count"] for r in docs_by_type},
        "docs_by_year": {r["year"]: r["doc_count"] for r in docs_by_year},
        "avg_length_by_type": avg_length_by_type,
        "sample_docs": sample_docs,
    }


def load_search_doc_nodes(
    session, processed_files: List[Path], config: ETLConfig, test_mode: bool = False
) -> None:
    """Main function to create and validate SEARCH_DOC nodes.

    Args:
        session: Neo4j session
        processed_files: List of processed JSON file paths
        config: ETL configuration
        test_mode: If True, limit documents for testing. If False, process all data.
    """
    # Create the search docs
    creation_result = create_search_doc_nodes(
        session, processed_files, config, test_mode
    )

    # Validate the results
    validation_result = validate_search_docs(session, config)

    print(f"\n✅ SEARCH_DOC creation completed!")
    print(f"   Documents created: {creation_result['total_docs_created']}")


if __name__ == "__main__":
    # Test SEARCH_DOC creation
    from .etl_config import DEFAULT_CONFIG

    config = DEFAULT_CONFIG
    # Use only recent files for testing
    recent_years = [2022, 2023, 2024]
    available_files = config.get_processed_files(recent_years)

    if available_files:
        print(f"Testing SEARCH_DOC creation with {len(available_files)} files")

        # Test with one file first
        test_file = available_files[-1]
        print(f"Testing with: {test_file.name}")

        with open(test_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        company_info = extract_company_info_from_data(data)
        year = company_info["year"]
        company_name = company_info["name"]

        print(f"Company: {company_name}, Year: {year}")

        sections = data.get("sections", [])

        # Test search doc extraction
        section_docs = extract_section_search_docs(sections, year, company_name)
        note_docs = extract_note_search_docs(sections, year, company_name)
        table_docs = extract_table_search_docs(sections, year, company_name)

        print(f"\nExtracted search documents:")
        print(f"  Section docs: {len(section_docs)}")
        print(f"  Note docs: {len(note_docs)}")
        print(f"  Table docs: {len(table_docs)}")

        # Show sample docs
        if section_docs:
            print(f"\nSample section doc:")
            sample = section_docs[0]
            print(f"  Title: {sample['title'][:50]}...")
            print(f"  Content length: {sample['content_length']} chars")
            print(f"  Word count: {sample['word_count']}")

        if note_docs:
            print(f"\nSample note doc:")
            sample = note_docs[0]
            print(f"  Title: {sample['title'][:50]}...")
            print(f"  Note number: {sample['note_number']}")
            print(f"  Content length: {sample['content_length']} chars")

        if table_docs:
            print(f"\nSample table doc:")
            sample = table_docs[0]
            print(f"  Title: {sample['title'][:50]}...")
            print(f"  Table index: {sample['table_index']}")
            print(f"  Is financial: {sample['is_financial_table']}")
            print(f"  Content length: {sample['content_length']} chars")

    else:
        print("No processed files found for testing")
