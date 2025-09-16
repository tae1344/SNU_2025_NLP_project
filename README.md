# 삼성전자 감사보고서 기반 금융 지식 그래프 구축  

서울대학교 빅데이터 AI 핀테크 고급전문가 과정  
자연어처리 프로젝트 · 11기 2조  

---

## 📌 프로젝트 개요
삼성전자 2014–2024년 감사보고서를 기반으로, 기업의 재무 구조 및 외부 금융기관과의 관계를 **금융 지식 그래프(Financial Knowledge Graph)** 로 구축합니다.  
- 감사보고서의 표/텍스트 데이터 자동 파싱  
- 회사, 사업부문, 재무항목, 금액 등 **엔티티 및 관계 추출**  
- Neo4j 기반 지식 그래프 모델링 및 시각화  
- 연도별 변화를 추적하는 **Temporal Graph 분석**  

---

## 🛠 기술 스택
- **데이터 처리:** Python, BeautifulSoup, lxml, pandas  
- **NLP 모델:** Hugging Face Transformers (KLUE-BERT Fine-tuning), 규칙 기반 관계 추출  
- **그래프 DB:** Neo4j (Cypher Query)  
- **시각화:** NetworkX, pyvis, Gephi  

---

## 삼성전자 감사보고서 기반 금융 지식 그래프 구축 및 분석 계획서
[[서울대 AI] 자연어처리_1차 향후 계획서.pdf](https://github.com/user-attachments/files/22353211/AI._1.pdf)

## DB 스키마 및 ERD

```mermaid
erDiagram
  COMPANIES {
    INTEGER company_id PK
    TEXT    name_ko
    TEXT    stock_code
    TEXT    country_code
  }

  AUDITORS {
    INTEGER auditor_id PK
    TEXT    firm_name
    TEXT    address
    TEXT    city
    TEXT    country_code
  }

  CONCEPTS {
    INTEGER concept_id PK
    TEXT    norm_name
    TEXT    ifrs_code
    TEXT    description
  }

  CONCEPT_ALIASES {
    INTEGER alias_id PK
    INTEGER concept_id FK
    TEXT    alias_name
  }

  UNITS {
    INTEGER unit_id PK
    TEXT    label
    TEXT    currency_code
    INTEGER multiplier
  }

  REPORTS {
    INTEGER report_id PK
    INTEGER company_id FK
    INTEGER fiscal_year
    TEXT    period_start
    TEXT    period_end
    TEXT    audit_report_date
    TEXT    currency_code
    INTEGER presentation_unit_id FK
    INTEGER is_consolidated
    INTEGER auditor_id FK
    TEXT    audit_opinion_code
    TEXT    audit_opinion_excerpt
    TEXT    emphasis_of_matter_excerpt
    TEXT    source
    TEXT    created_at
    TEXT    updated_at
  }

  REPORT_FILES {
    INTEGER file_id PK
    INTEGER report_id FK
    TEXT    src_path
    TEXT    file_hash
    INTEGER html_table_count
    TEXT    encoding
    TEXT    loaded_at
  }

  ETL_LOGS {
    INTEGER log_id PK
    INTEGER report_id FK
    TEXT    stage
    TEXT    level
    TEXT    message
    TEXT    detail_json
    TEXT    created_at
  }

  RAW_TABLES {
    INTEGER raw_table_id PK
    INTEGER report_id FK
    INTEGER file_id FK
    INTEGER table_index
    TEXT    caption
    TEXT    section_hint
    INTEGER n_rows
    INTEGER n_cols
    INTEGER unit_id FK
    TEXT    html
    TEXT    text
  }

  RAW_TABLE_CELLS {
    INTEGER cell_id PK
    INTEGER raw_table_id FK
    INTEGER row_idx
    INTEGER col_idx
    INTEGER rowspan
    INTEGER colspan
    TEXT    text
  }

  FINANCIAL_STATEMENTS {
    INTEGER fs_id PK
    INTEGER report_id FK
    TEXT    statement_type
    TEXT    title
    INTEGER unit_id FK
    INTEGER raw_title_table FK
    INTEGER body_table FK
  }

  FINANCIAL_STATEMENT_LINES {
    INTEGER line_id PK
    INTEGER fs_id FK
    INTEGER order_in_table
    INTEGER indent_level
    TEXT    raw_label
    TEXT    note_refs
    INTEGER concept_id FK
    NUMERIC amount_current
    NUMERIC amount_prior
    INTEGER sign_current
    INTEGER sign_prior
    TEXT    raw_current_str
    TEXT    raw_prior_str
    INTEGER source_table_row
  }

  NOTES {
    INTEGER note_id PK
    INTEGER report_id FK
    TEXT    note_no
    TEXT    title
    TEXT    body_text
  }

  NOTE_LINKS {
    INTEGER link_id PK
    INTEGER line_id FK
    INTEGER note_id FK
  }

  SECTIONS {
    INTEGER section_id PK
    INTEGER report_id FK
    TEXT    section_type
    TEXT    title
    INTEGER order_in_doc
    TEXT    text
  }

  KAM_ITEMS {
    INTEGER kam_id PK
    INTEGER report_id FK
    TEXT    title
    TEXT    why_significant
    TEXT    audit_response
    TEXT    findings_summary
  }

  AUDIT_COMM_MEETINGS {
    INTEGER meeting_id PK
    INTEGER report_id FK
    INTEGER seq_no
    TEXT    meeting_date
    TEXT    attendees
    TEXT    mode
    TEXT    topics
  }

  RISK_TERMS {
    INTEGER term_id PK
    TEXT    category
    TEXT    term
  }

  RISK_HITS {
    INTEGER hit_id PK
    INTEGER report_id FK
    INTEGER section_id FK
    INTEGER raw_table_id FK
    INTEGER term_id FK
    TEXT    span_text
    TEXT    context_text
    INTEGER start_char
    INTEGER end_char
  }

  SEARCH_DOCS {
    INTEGER doc_id PK
    INTEGER report_id FK
    TEXT    source_type
    INTEGER source_ref_id
    TEXT    text
  }

  %% Relationships
  COMPANIES ||--o{ REPORTS : "company_id"
  AUDITORS  ||--o{ REPORTS : "auditor_id"
  UNITS     ||--o{ REPORTS : "presentation_unit_id"

  REPORTS   ||--o{ REPORT_FILES : "report_id"
  REPORTS   ||--o{ ETL_LOGS     : "report_id"
  REPORTS   ||--o{ RAW_TABLES   : "report_id"
  REPORTS   ||--o{ FINANCIAL_STATEMENTS : "report_id"
  REPORTS   ||--o{ NOTES        : "report_id"
  REPORTS   ||--o{ SECTIONS     : "report_id"
  REPORTS   ||--o{ KAM_ITEMS    : "report_id"
  REPORTS   ||--o{ AUDIT_COMM_MEETINGS : "report_id"
  REPORTS   ||--o{ RISK_HITS    : "report_id"
  REPORTS   ||--o{ SEARCH_DOCS  : "report_id"

  REPORT_FILES ||--o{ RAW_TABLES : "file_id"

  RAW_TABLES ||--o{ RAW_TABLE_CELLS : "raw_table_id"
  UNITS      ||--o{ RAW_TABLES      : "unit_id"

  UNITS      ||--o{ FINANCIAL_STATEMENTS : "unit_id"
  RAW_TABLES ||--o{ FINANCIAL_STATEMENTS : "raw_title_table / body_table"

  FINANCIAL_STATEMENTS ||--o{ FINANCIAL_STATEMENT_LINES : "fs_id"
  CONCEPTS             ||--o{ FINANCIAL_STATEMENT_LINES : "concept_id"

  CONCEPTS        ||--o{ CONCEPT_ALIASES : "concept_id"
  FINANCIAL_STATEMENT_LINES ||--o{ NOTE_LINKS : "line_id"
  NOTES           ||--o{ NOTE_LINKS : "note_id"

  SECTIONS  ||--o{ RISK_HITS : "section_id"
  RAW_TABLES||--o{ RISK_HITS : "raw_table_id"
  RISK_TERMS||--o{ RISK_HITS : "term_id"
