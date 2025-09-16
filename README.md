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
  UNIT_LU {
    TINYINT unit_id PK
    VARCHAR unit_name
    CHAR currency_code
    INT scale
  }

  REPORTS {
    BIGINT report_id PK
    VARCHAR company_kor
    INT fiscal_year
    VARCHAR fiscal_period
    INT version
    DATE opinion_date
    VARCHAR source_file
    CHAR source_hash
    DATETIME extracted_at
    VARCHAR parser_version
    TIMESTAMP created_at
  }

  SECTIONS {
    BIGINT section_id PK
    BIGINT report_id FK
    VARCHAR section_type
    VARCHAR title
    TINYINT unit_id FK
    TEXT raw_html
  }

  TEXT_BLOCKS {
    BIGINT text_id PK
    BIGINT section_id FK
    VARCHAR text_type
    INT block_order
    TEXT content
    VARCHAR ref_note_no
  }

  TABLES_META {
    BIGINT table_id PK
    BIGINT section_id FK
    VARCHAR caption
    TINYINT unit_id FK
    INT table_order
    TINYINT has_multi_year
  }

  TABLE_ROWS {
    BIGINT row_id PK
    BIGINT table_id FK
    INT row_order
    VARCHAR account_kor
    VARCHAR note_refs
    TINYINT level
  }

  TABLE_VALUES {
    BIGINT value_id PK
    BIGINT row_id FK
    TINYINT unit_id FK
    INT fiscal_year
    VARCHAR column_role
    DECIMAL amount_decimal
    DECIMAL normalized_krw
  }

  NOTES {
    BIGINT note_id PK
    BIGINT report_id FK
    VARCHAR note_no
    VARCHAR title
    TEXT content
  }

  ROW_NOTE_MAP {
    BIGINT row_id FK
    BIGINT note_id FK
  }

  TEXT_NOTE_MAP {
    BIGINT text_id FK
    BIGINT note_id FK
  }

  REPORTS ||--o{ SECTIONS : ""
  REPORTS ||--o{ NOTES : ""
  UNIT_LU ||--o{ SECTIONS : ""
  UNIT_LU ||--o{ TABLES_META : ""
  UNIT_LU ||--o{ TABLE_VALUES : ""
  SECTIONS ||--o{ TEXT_BLOCKS : ""
  SECTIONS ||--o{ TABLES_META : ""
  TABLES_META ||--o{ TABLE_ROWS : ""
  TABLE_ROWS ||--o{ TABLE_VALUES : ""
  TABLE_ROWS ||--o{ ROW_NOTE_MAP : ""
  NOTES ||--o{ ROW_NOTE_MAP : ""
  TEXT_BLOCKS ||--o{ TEXT_NOTE_MAP : ""
  NOTES ||--o{ TEXT_NOTE_MAP : ""
