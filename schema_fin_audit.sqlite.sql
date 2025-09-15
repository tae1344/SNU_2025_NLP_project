-- schema_fin_audit.sqlite.sql (v2)
-- Domain: Samsung audit reports (2014–2024) — HTML ingest → normalization → analytics
-- Target DB: SQLite 3
-- Usage: sqlite3 app.db < schema_fin_audit.sqlite.sql

PRAGMA foreign_keys = ON;

BEGIN TRANSACTION;

-- =========================
-- 0) Lookup / reference
-- =========================
CREATE TABLE IF NOT EXISTS audit_opinions (
    code        TEXT PRIMARY KEY,        -- '적정','한정','부적정','의견거절'
    name_ko     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS section_types (
    code        TEXT PRIMARY KEY,        -- 'intro','opinion','basis','management_resp','auditor_resp','emphasis','KAM','IC_opinion','other'
    name_ko     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS statement_types (
    code        TEXT PRIMARY KEY,        -- 'BS','PL','CF','EQ'
    name_ko     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS units (
    unit_id     INTEGER PRIMARY KEY,
    label       TEXT NOT NULL,           -- e.g., '백만원', '억원', '조원'
    currency_code TEXT NOT NULL DEFAULT 'KRW',
    multiplier  INTEGER NOT NULL         -- e.g., 1_000_000 for '백만원'
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_units_label_currency ON units(label, currency_code);

CREATE TABLE IF NOT EXISTS companies (
    company_id  INTEGER PRIMARY KEY,
    name_ko     TEXT NOT NULL,           -- e.g., '삼성전자주식회사'
    stock_code  TEXT,                    -- '005930'
    country_code TEXT DEFAULT 'KR'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_companies_name ON companies(name_ko);

CREATE TABLE IF NOT EXISTS auditors (
    auditor_id  INTEGER PRIMARY KEY,
    firm_name   TEXT NOT NULL,           -- e.g., '삼정회계법인', '삼일회계법인'
    address     TEXT,
    city        TEXT,
    country_code TEXT DEFAULT 'KR'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_auditors_firm ON auditors(firm_name);

CREATE TABLE IF NOT EXISTS concepts (
    concept_id  INTEGER PRIMARY KEY,
    norm_name   TEXT NOT NULL,           -- normalized label: '현금및현금성자산'
    ifrs_code   TEXT,                    -- optional external taxonomy code
    description TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_concepts_norm ON concepts(norm_name);

CREATE TABLE IF NOT EXISTS concept_aliases (
    alias_id    INTEGER PRIMARY KEY,
    concept_id  INTEGER NOT NULL REFERENCES concepts(concept_id) ON DELETE CASCADE,
    alias_name  TEXT NOT NULL           -- observed variant in reports
);
CREATE INDEX IF NOT EXISTS ix_aliases_name ON concept_aliases(alias_name);

-- =========================
-- 1) Report metadata
-- =========================
CREATE TABLE IF NOT EXISTS reports (
    report_id           INTEGER PRIMARY KEY,
    company_id          INTEGER NOT NULL REFERENCES companies(company_id) ON DELETE RESTRICT,
    fiscal_year         INTEGER NOT NULL CHECK (fiscal_year BETWEEN 1900 AND 2100),
    period_start        TEXT,           -- 'YYYY-MM-DD'
    period_end          TEXT,           -- 'YYYY-MM-DD'
    audit_report_date   TEXT,           -- 'YYYY-MM-DD'
    currency_code       TEXT NOT NULL DEFAULT 'KRW',
    presentation_unit_id INTEGER REFERENCES units(unit_id),
    is_consolidated     INTEGER NOT NULL DEFAULT 0 CHECK (is_consolidated IN (0,1)),
    auditor_id          INTEGER REFERENCES auditors(auditor_id),
    audit_opinion_code  TEXT REFERENCES audit_opinions(code), -- NULL allowed until extracted
    audit_opinion_excerpt TEXT,
    emphasis_of_matter_excerpt TEXT,
    source              TEXT,           -- file path / link / note
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    CHECK (period_start IS NULL OR period_start GLOB '____-__-__'),
    CHECK (period_end   IS NULL OR period_end   GLOB '____-__-__'),
    CHECK (audit_report_date IS NULL OR audit_report_date GLOB '____-__-__'),
    CHECK (period_start IS NULL OR period_end IS NULL OR period_start <= period_end)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_reports_unique ON reports(company_id, fiscal_year, is_consolidated);
CREATE INDEX IF NOT EXISTS ix_reports_year ON reports(fiscal_year);

-- Trigger: auto-update updated_at
CREATE TRIGGER IF NOT EXISTS trg_reports_updated_at
AFTER UPDATE ON reports
FOR EACH ROW
BEGIN
    UPDATE reports SET updated_at = datetime('now') WHERE report_id = NEW.report_id;
END;

-- =========================
-- 2) Ingested files & ETL logs
-- =========================
CREATE TABLE IF NOT EXISTS report_files (
    file_id         INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    src_path        TEXT NOT NULL,      -- local path or URI
    file_hash       TEXT,               -- SHA-256
    html_table_count INTEGER,
    encoding       TEXT,
    loaded_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_files_report ON report_files(report_id);

CREATE TABLE IF NOT EXISTS etl_logs (
    log_id          INTEGER PRIMARY KEY,
    report_id       INTEGER REFERENCES reports(report_id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,      -- parse_html / normalize_tables / load_db / ...
    level           TEXT NOT NULL CHECK (level IN ('INFO','WARN','ERROR')),
    message         TEXT NOT NULL,
    detail_json     TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
);

-- =========================
-- 3) Raw HTML capture
-- =========================
CREATE TABLE IF NOT EXISTS raw_tables (
    raw_table_id    INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    file_id         INTEGER REFERENCES report_files(file_id) ON DELETE SET NULL,
    table_index     INTEGER NOT NULL,   -- order in HTML (0-based)
    caption         TEXT,
    section_hint    TEXT,               -- heuristic label: '재무상태표-제목', '포괄손익-본문', ...
    n_rows          INTEGER,
    n_cols          INTEGER,
    unit_id         INTEGER REFERENCES units(unit_id), -- detected per table if any
    html            TEXT,               -- original HTML
    text            TEXT                -- flattened text
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_table_idx ON raw_tables(report_id, table_index);

CREATE TABLE IF NOT EXISTS raw_table_cells (
    cell_id         INTEGER PRIMARY KEY,
    raw_table_id    INTEGER NOT NULL REFERENCES raw_tables(raw_table_id) ON DELETE CASCADE,
    row_idx         INTEGER NOT NULL,
    col_idx         INTEGER NOT NULL,
    rowspan         INTEGER NOT NULL DEFAULT 1,
    colspan         INTEGER NOT NULL DEFAULT 1,
    text            TEXT
);
CREATE INDEX IF NOT EXISTS ix_cells_table ON raw_table_cells(raw_table_id);

-- =========================
-- 4) Normalized statements
-- =========================
CREATE TABLE IF NOT EXISTS financial_statements (
    fs_id           INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    statement_type  TEXT NOT NULL REFERENCES statement_types(code), -- 'BS','PL','CF','EQ'
    title           TEXT,
    unit_id         INTEGER REFERENCES units(unit_id),
    raw_title_table INTEGER REFERENCES raw_tables(raw_table_id),
    body_table      INTEGER REFERENCES raw_tables(raw_table_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_fs_unique ON financial_statements(report_id, statement_type);

CREATE TABLE IF NOT EXISTS financial_statement_lines (
    line_id         INTEGER PRIMARY KEY,
    fs_id           INTEGER NOT NULL REFERENCES financial_statements(fs_id) ON DELETE CASCADE,
    order_in_table  INTEGER NOT NULL,   -- row order
    indent_level    INTEGER NOT NULL DEFAULT 0,
    raw_label       TEXT NOT NULL,
    note_refs       TEXT,               -- e.g., '4, 28', '27-1'
    concept_id      INTEGER REFERENCES concepts(concept_id),
    amount_current  NUMERIC,            -- normalized to KRW (won)
    amount_prior    NUMERIC,
    sign_current    INTEGER NOT NULL DEFAULT 1 CHECK (sign_current IN (-1,0,1)),
    sign_prior      INTEGER NOT NULL DEFAULT 1 CHECK (sign_prior IN (-1,0,1)),
    raw_current_str TEXT,
    raw_prior_str   TEXT,
    source_table_row INTEGER,
    UNIQUE (fs_id, order_in_table)
);
CREATE INDEX IF NOT EXISTS ix_fsl_concept ON financial_statement_lines(concept_id);
CREATE INDEX IF NOT EXISTS ix_fsl_fs ON financial_statement_lines(fs_id);

-- =========================
-- 5) Notes (주석)
-- =========================
CREATE TABLE IF NOT EXISTS notes (
    note_id         INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    note_no         TEXT,               -- '4', '25', '27-1'
    title           TEXT,
    body_text       TEXT
);
CREATE INDEX IF NOT EXISTS ix_notes_report ON notes(report_id);

CREATE TABLE IF NOT EXISTS note_links (
    link_id         INTEGER PRIMARY KEY,
    line_id         INTEGER REFERENCES financial_statement_lines(line_id) ON DELETE CASCADE,
    note_id         INTEGER REFERENCES notes(note_id) ON DELETE CASCADE
);

-- =========================
-- 6) Narrative sections & KAM
-- =========================
CREATE TABLE IF NOT EXISTS sections (
    section_id      INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    section_type    TEXT NOT NULL REFERENCES section_types(code),
    title           TEXT,
    order_in_doc    INTEGER,
    text            TEXT
);
CREATE INDEX IF NOT EXISTS ix_sections_report ON sections(report_id);
CREATE INDEX IF NOT EXISTS ix_sections_type ON sections(section_type);

CREATE TABLE IF NOT EXISTS kam_items (
    kam_id          INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    title           TEXT,
    why_significant TEXT,
    audit_response  TEXT,
    findings_summary TEXT
);

CREATE TABLE IF NOT EXISTS audit_comm_meetings (
    meeting_id      INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    seq_no          INTEGER,
    meeting_date    TEXT,               -- 'YYYY-MM-DD'
    attendees       TEXT,
    mode            TEXT,               -- '대면회의' 등
    topics          TEXT,
    CHECK (meeting_date IS NULL OR meeting_date GLOB '____-__-__')
);

-- =========================
-- 7) Risk dictionary & hits
-- =========================
CREATE TABLE IF NOT EXISTS risk_terms (
    term_id         INTEGER PRIMARY KEY,
    category        TEXT,
    term            TEXT NOT NULL        -- keyword or regex
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_risk_terms_term ON risk_terms(term);

CREATE TABLE IF NOT EXISTS risk_hits (
    hit_id          INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    section_id      INTEGER REFERENCES sections(section_id) ON DELETE SET NULL,
    raw_table_id    INTEGER REFERENCES raw_tables(raw_table_id) ON DELETE SET NULL,
    term_id         INTEGER NOT NULL REFERENCES risk_terms(term_id) ON DELETE CASCADE,
    span_text       TEXT,
    context_text    TEXT,
    start_char      INTEGER,
    end_char        INTEGER
);
CREATE INDEX IF NOT EXISTS ix_risk_hits_report ON risk_hits(report_id);

-- =========================
-- 8) IR search docs
-- =========================
CREATE TABLE IF NOT EXISTS search_docs (
    doc_id          INTEGER PRIMARY KEY,
    report_id       INTEGER NOT NULL REFERENCES reports(report_id) ON DELETE CASCADE,
    source_type     TEXT NOT NULL CHECK (source_type IN ('paragraph','table')),
    source_ref_id   INTEGER,            -- section_id or raw_table_id
    text            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_search_docs_report ON search_docs(report_id);

-- =========================
-- 9) Views for quick analytics
-- =========================
CREATE VIEW IF NOT EXISTS v_kpi_yearly AS
SELECT
    r.report_id,
    r.fiscal_year,
    MAX(CASE WHEN fs.statement_type='BS' AND REPLACE(fsl.raw_label,' ','') IN ('자산총계','총자산','자산총계(연결)') THEN fsl.amount_current END) AS total_assets,
    MAX(CASE WHEN fs.statement_type='PL' AND REPLACE(fsl.raw_label,' ','') IN ('매출액','매출','수익') THEN fsl.amount_current END) AS revenue,
    MAX(CASE WHEN fs.statement_type='PL' AND REPLACE(fsl.raw_label,' ','') IN ('당기순이익','분기순이익','기말순이익','지배기업소유주지분순이익') THEN fsl.amount_current END) AS net_income
FROM reports r
LEFT JOIN financial_statements fs ON fs.report_id = r.report_id
LEFT JOIN financial_statement_lines fsl ON fsl.fs_id = fs.fs_id
GROUP BY r.report_id, r.fiscal_year;

CREATE VIEW IF NOT EXISTS v_fs_lines AS
SELECT
    r.fiscal_year,
    r.is_consolidated,
    r.audit_opinion_code,
    fs.statement_type,
    fsl.order_in_table,
    fsl.indent_level,
    fsl.raw_label,
    fsl.amount_current,
    fsl.amount_prior
FROM reports r
JOIN financial_statements fs ON fs.report_id = r.report_id
JOIN financial_statement_lines fsl ON fsl.fs_id = fs.fs_id;

-- =========================
-- 10) Seeds
-- =========================
INSERT OR IGNORE INTO audit_opinions(code, name_ko) VALUES
    ('적정','적정의견'),
    ('한정','한정의견'),
    ('부적정','부적정의견'),
    ('의견거절','의견거절');

INSERT OR IGNORE INTO section_types(code, name_ko) VALUES
    ('intro','서론/표지'),
    ('opinion','감사의견'),
    ('basis','감사의견의 근거'),
    ('management_resp','경영진의 책임'),
    ('auditor_resp','감사인의 책임'),
    ('emphasis','강조사항'),
    ('KAM','핵심감사사항'),
    ('IC_opinion','내부회계관리제도'),
    ('other','기타');

INSERT OR IGNORE INTO statement_types(code, name_ko) VALUES
    ('BS','재무상태표'),
    ('PL','포괄손익계산서'),
    ('CF','현금흐름표'),
    ('EQ','자본변동표');

INSERT OR IGNORE INTO units(unit_id, label, currency_code, multiplier) VALUES
    (1, '백만원', 'KRW', 1000000),
    (2, '억원',   'KRW', 100000000),
    (3, '조원',   'KRW', 1000000000000);

INSERT OR IGNORE INTO auditors(auditor_id, firm_name, address, city, country_code) VALUES
    (1, '삼정회계법인', '서울특별시 강남구 테헤란로 152 강남파이낸스센터 27층', '서울', 'KR'),
    (2, '삼일회계법인', '서울특별시 용산구 한강대로 92', '서울', 'KR');

INSERT OR IGNORE INTO companies(company_id, name_ko, stock_code, country_code) VALUES
    (1, '삼성전자주식회사', '005930', 'KR');

COMMIT;