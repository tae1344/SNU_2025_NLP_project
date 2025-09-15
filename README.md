# 삼성전자 감사보고서 ETL 파이프라인

한국어(KR) HTM/HTML 감사보고서를 파싱해 SQLite DB(`schema_fin_audit.sqlite.sql`) 구조로 적재하는 파이프라인입니다. 파서는 EUC-KR을 포함한 인코딩을 자동 감지하고, 표에서 재무제표(BS/PL/CF/EQ) 후보를 식별해 정규화된 라인으로 저장합니다.

## 구성

- `audit_pipeline.py`: 파서 + ETL 실행 스크립트
  - `AuditReportParser`: `parse_html`, `extract_sections`, `extract_tables`, `normalize_text`
  - 데이터 모델: `SectionBlock`, `RawTablePackage`, `FSBlock`, `ParsedReport`
  - DB 유틸: 스키마 적용, UPSERT 저장, 재실행 안전(idempotent)
- `schema_fin_audit.sqlite.sql`: 대상 DB 스키마와 기본 시드
- 입력 폴더: `/Users/sangjaelee/Desktop/핀테크과제/삼성전자_감사보고서_2014_2024`
- 출력 DB: `/Users/sangjaelee/Desktop/핀테크과제/app.db`

## 빠른 시작

- 의존성 설치(권장)
  - `python -m pip install beautifulsoup4 pandas lxml html5lib`
  - lxml 미설치여도 동작하지만, 정확도를 위해 설치 권장
- 실행
  - 터미널: `python audit_pipeline.py`
  - 노트북: 
    - `import audit_pipeline as ap`
    - `ap.init_and_run()`
- 기본 경로/DB/스키마는 `audit_pipeline.py` 상단 상수로 설정 가능

## 처리 흐름(Flow)

```text
[HTM/HTML Files]
    |
    v
AuditReportParser.parse_html  (EUC-KR 등 인코딩 자동 감지, script/style 제거)
    |
    +--> extract_sections     (헤더 패턴 매칭 → 구간분리 → SectionBlock[])
    |
    +--> extract_tables       (pandas.read_html → 표 평탄화/헤더보정 →
    |                           캡션/본문 키워드로 BS/PL/CF/EQ 후보 식별 →
    |                           단위 감지 → RawTablePackage 적재용 캡처 →
    |                           계정열/당기·전기 매핑 → FSBlock 후보 생성 →
    |                           유형별 최고 스코어 1개 선택)
    |
    v
build_payload                (meta + sections + raw_tables + financials)
    |
    v
ensure_schema                (schema_fin_audit.sqlite.sql 실행)
    |
    v
insert_report                (보고서 메타 UPSERT)
    |
    v
insert_report_file           (원문 파일 경로/해시/표 수 기록)
    |
    v
insert_raw_tables            ((report_id, table_index) 기준 UPSERT, 셀 재생성)
    |
    v
upsert_financials            ((report_id, statement_type) UPSERT,
                              기존 라인 삭제 후 재삽입)
    |
    v
[SQLite: reports, report_files, raw_tables, raw_table_cells,
         financial_statements, financial_statement_lines]
```

## 데이터 모델(요약)

- `SectionBlock`: `section_type_code`, `title`, `order_in_doc`, `text`
- `RawTablePackage`: `table_index`, `caption`, `section_hint`, `n_rows`, `n_cols`, `unit_id`, `html`, `text`, `cells[(r,c,text)]`
- `FSBlock`: `statement_type('BS'|'PL'|'CF'|'EQ')`, `table_index`, `title`, `unit_id`, `lines[...]`
- `ParsedReport`: `meta`, `sections[]`, `raw_tables[]`, `financials[]`

## 저장 정책(Idempotent)
- `raw_tables`: `(report_id, table_index)` 충돌 시 최신으로 갱신, 셀은 전량 재생성
- `financial_statements`: `(report_id, statement_type)` 충돌 시 갱신, 라인은 전량 재삽입
- 재실행 시에도 중복 제약 오류 없이 최신 상태로 정합성 유지

## 검증 방법
- 파일 존재: `ls -lh /Users/sangjaelee/Desktop/핀테크과제/app.db`
- 무결성: `sqlite3 app.db "PRAGMA integrity_check;"`
- 주요 카운트/샘플
  - `sqlite3 app.db "SELECT COUNT(*) FROM reports;"`
  - `sqlite3 app.db "SELECT report_id, statement_type, COUNT(*) FROM financial_statements GROUP BY 1,2;"`
  - `sqlite3 app.db "SELECT COUNT(*) FROM financial_statement_lines;"`
  - 2024년 라벨/금액 샘플:
    - `sqlite3 -cmd ".mode tabs" app.db "SELECT r.fiscal_year, fs.statement_type, fsl.order_in_table, REPLACE(fsl.raw_label,' ','') AS label, fsl.amount_current FROM financial_statement_lines fsl JOIN financial_statements fs ON fs.fs_id=fsl.fs_id JOIN reports r ON r.report_id=fs.report_id WHERE r.fiscal_year=2024 AND fs.statement_type IN ('BS','PL') ORDER BY fs.statement_type, fsl.order_in_table LIMIT 40;"`


## 설정 변경
- `audit_pipeline.py` 상단 상수 수정
  - `INPUT_DIR`, `DB_PATH`, `SCHEMA_SQL_PATH`
  - 기본 ID: `DEFAULT_COMPANY_ID`, `DEFAULT_AUDITOR_ID`, `DEFAULT_UNIT_ID`, `DEFAULT_IS_CONSOLIDATED`

## 다음 단계 아이디어
- 라벨 정규화 사전/개념 매핑(예: `현금및현금성자산` 등 → concepts)
- 복합 요약표 내부 구간 분리(BS/PL/CF/EQ) 로직 강화
- KAM/강조사항 등 내러티브 섹션 정규화 및 검색 인덱스 생성
