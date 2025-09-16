# 삼성전자 금융 지식그래프 프로젝트

## 📌 프로젝트 개요
본 프로젝트는 **삼성전자 주주**를 주요 타겟으로 하여,  
2014년부터 2024년까지의 **11개년 감사보고서**를 바탕으로  
**핵심 감사 및 재무 정보를 한눈에 확인할 수 있는 금융 지식그래프**를 구축하는 것을 목표로 합니다.

### 🎯 목적
- 매년 감사보고서의 핵심 내용을 주주가 빠르게 이해할 수 있도록 **시각적이고 탐색 가능한 구조** 제공
- 숫자 중심의 재무제표뿐만 아니라, **주석·사업부문·개념 관계**를 그래프 형태로 직관화
- 장기적으로는 **금융 도메인 특화 QA/NLP 시스템**의 기반 데이터베이스로 활용 가능

---

## 현재까지 진행 상황
1. **원자료 확보**
   - 삼성전자 2014–2024년 감사보고서 HTML 파일 (11개)
2. **데이터 파싱 및 전처리**
   - BeautifulSoup 기반 파서 작성
   - 주요 섹션 텍스트 및 재무제표 표 단위 추출
   - 텍스트 정규화, 단위 변환(백만원 → 원) 일부 적용
3. **중간 산출물**
   - JSON 포맷의 연도별 보고서 데이터

---

## 향후 추진 계획

### 1. 그래프 데이터 모델링
- **노드(labels)**: Company, Report(연도), Statement(재무제표), LineItem, Concept, Unit, Note
- **관계(relationships)**:  
  - `(Company)-[:HAS_REPORT]->(Report)`  
  - `(Report)-[:HAS_STATEMENT]->(Statement)`  
  - `(Statement)-[:HAS_LINE]->(LineItem)`  
  - `(LineItem)-[:OF_CONCEPT]->(Concept)`  
  - `(LineItem)-[:MEASURED_IN]->(Unit)`  
  - `(Report)-[:HAS_NOTE]->(Note)`

### 2. 데이터 적재
- **Neo4j (AuraDB Free / Community Edition)** 사용
- 파서 출력(JSON/CSV) → Python 드라이버로 **Upsert 적재**
- **개념 매핑(concept_map.csv)** 정의 → 다양한 표현을 표준화된 Concept 키로 통일
- **단위 관리(Unit 노드)** → 통일된 환산 스케일 적용

### 3. 데모 구현
- **주주 친화적 시나리오 질의**
  1. **연도별 핵심 지표 추세**
     - 영업이익, 당기순이익, 자산총계, 부채총계
  2. **주석과 연결된 항목 확인**
     - 예: “주석 21”이 설명하는 항목과 금액
  3. **연도별 재무 구조 비교**
     - 자산=부채+자본 평형 여부
  4. **산업/경쟁사 비교 (옵션)**
     - 동일 산업 내 주요 기업의 재무 지표 비교

- **시각화**
  - Neo4j Browser/Bloom 활용 → 보고서→재무제표→라인아이템 구조를 그래프로 표시
  - 시계열 질의 결과를 표/차트 형태로 변환하여 제시

---

## 기대 효과
- **주주 맞춤형 요약**: 11개년 주요 지표 및 감사 핵심사항을 빠르게 확인 가능  
- **관계 기반 탐색**: 주석 ↔ 항목 ↔ 개념 관계를 직관적으로 탐색  
- **시간 차원 비교**: 연도별 재무 데이터 추이를 그래프 질의로 분석  
- **확장성**: 외부 산업·경쟁사 데이터와 연결해 맥락 있는 해석 제공  

---

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

