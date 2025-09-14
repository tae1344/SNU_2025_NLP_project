## HTML → JSON Parsing

### Parser Versions

#### Version 1.0 (Basic Parser)
- **File**: `src/html_to_json.py`
- **Purpose**: Basic HTML to JSON conversion with flat content structure

#### Version 2.0 (Improved Parser)
- **File**: `src/html_to_json_improved.py`
- **Purpose**: Structured content extraction with section-based organization

#### Version 2.1 (Enhanced Parser) ⭐ **RECOMMENDED**
- **File**: `src/html_to_json_enhanced.py`
- **Purpose**: Production-ready parser with comprehensive validation and logging
- **Features**: 
  - Comprehensive error handling and logging
  - Data quality validation with scoring
  - Configuration file support (YAML)
  - Korean text encoding validation
  - Enhanced metadata extraction
  - Section extraction quality assessment

### Quick Start

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the enhanced parser:
```bash
python src/html_to_json_enhanced.py \
  --input data/raw \
  --output data/processed \
  --pattern "*.htm" \
  --log-level INFO
```

### Enhanced Output Format

```json
{
  "version": "2.1",
  "source_path": "data/raw/감사보고서_2014.htm",
  "source_filename": "감사보고서_2014.htm",
  "report_year": 2014,
  "title": "감사보고서",
  "headings": [{"level": "SECTION-1", "text": "독립된 감사인의 감사보고서"}],
  "sections": [
    {
      "title": "주석",
      "level": "SECTION-2",
      "content": "Section text content...",
      "tables": [{"index": 0, "columns": ["..."], "rows": [["..."]]}]
    }
  ],
  "total_sections": 4,
  "total_tables": 216,
  "data_quality_score": 0.80,
  "validation_results": {
    "section_extraction": {
      "quality_score": 0.80,
      "exact_matches": ["주석", "내부회계관리제도 검토의견"],
      "missing_sections": ["독립된 감사인의 감사보고서", "(첨부)재 무 제 표"]
    },
    "korean_text_encoding": {
      "encoding_issues": [],
      "encoding_issues_found": 0
    }
  },
  "extraction_metadata": {
    "extraction_timestamp": "2025-09-13T22:24:04.879130",
    "parser_version": "2.1",
    "file_size_bytes": 687160,
    "total_elements_parsed": 11353
  }
}
```

### Configuration

The enhanced parser uses `config/parser_config.yaml` for settings:
- Expected sections for validation
- Quality thresholds
- Logging configuration
- Output options

### Notes
- `report_year` is inferred from filename (e.g., `*_2019.*`). If absent, `-1`.
- Quality score ranges from 0.0 to 1.0 based on section extraction completeness
- Korean text encoding is validated automatically
- Both flat `content` and structured `sections` formats are provided for backward compatibility
