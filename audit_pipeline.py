from __future__ import annotations

from dataclasses import dataclass
import importlib.util
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import hashlib
import re
import sqlite3

import pandas as pd
from bs4 import BeautifulSoup, NavigableString, Tag


# =========================
# 설정
# =========================
INPUT_DIR = "/Users/sangjaelee/Desktop/핀테크과제/삼성전자_감사보고서_2014_2024"
DB_PATH = "/Users/sangjaelee/Desktop/핀테크과제/app.db"
SCHEMA_SQL_PATH = "/Users/sangjaelee/Desktop/핀테크과제/schema_fin_audit.sqlite.sql"

DEFAULT_COMPANY_ID = 1
DEFAULT_AUDITOR_ID = 1
DEFAULT_UNIT_ID = 1
DEFAULT_IS_CONSOLIDATED = 1
DEFAULT_CURRENCY = "KRW"


# =========================
# 유틸
# =========================
_KR_SPACE_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def normalize_whitespace(text: str) -> str:
    if text is None:
        return ""
    text = text.replace("\u00a0", " ")  # nbsp
    text = _KR_SPACE_RE.sub(" ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text.strip())
    return text.strip()


def parse_amount(cell: Any) -> Optional[float]:
    if cell is None:
        return None
    s = str(cell).strip()
    if s in {"", "-", "–", "—", "N/A"}:
        return None
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg = True
        s = s[1:-1]
    s = s.replace(",", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    if not m:
        return None
    try:
        val = float(m.group(0))
        return -val if neg else val
    except Exception:
        return None


def file_hash(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def text_nearby(table_tag: Tag, window: int = 400) -> str:
    txt = []
    prev = table_tag.previous_sibling
    count = 0
    while prev and count < 5:
        if isinstance(prev, NavigableString):
            txt.append(str(prev))
        elif isinstance(prev, Tag):
            txt.append(prev.get_text(" ", strip=True))
        prev = prev.previous_sibling
        count += 1

    nxt = table_tag.next_sibling
    count = 0
    while nxt and count < 5:
        if isinstance(nxt, NavigableString):
            txt.append(str(nxt))
        elif isinstance(nxt, Tag):
            txt.append(nxt.get_text(" ", strip=True))
        nxt = nxt.next_sibling
        count += 1
    joined = normalize_whitespace(" ".join(filter(None, txt)))
    return joined[:window]


# =========================
# 패턴/상수
# =========================
SECTION_PATTERNS: Dict[str, List[str]] = {
    "AUDIT_OPINION": [r"\b감사의견\b", r"Auditor.?s?\s+Report\b"],
    "BASIS_FOR_OPINION": [r"\b의견의\s*근거\b", r"Basis\s+for\s+Opinion\b"],
    "KAM": [r"\b핵심감사사항\b", r"Key\s+Audit\s+Matters\b"],
    "RESPONSIBILITY_MGMT": [r"\b경영진의\s*책임\b", r"Management.?s?\s+Responsibil"],
    "RESPONSIBILITY_AUDITOR": [r"\b감사인의\s*책임\b", r"Auditor.?s?\s+Responsibil"],
    "EMPHASIS": [r"\b강조사항\b", r"Emphasis\s+of\s+Matter\b"],
    "ICFR": [r"\b내부회계관리제도\b", r"Internal\s+Control\b"],
    "ATTACH_FS": [r"\(첨부\)\s*재무제표\b", r"\bFinancial\s+Statements\b", r"\b재무제표\b"],
}

SECTION_TYPE_ALIASES: Dict[str, str] = {
    "AUDIT_OPINION": "opinion",
    "BASIS_FOR_OPINION": "basis",
    "KAM": "KAM",
    "RESPONSIBILITY_MGMT": "management_resp",
    "RESPONSIBILITY_AUDITOR": "auditor_resp",
    "EMPHASIS": "emphasis",
    "ICFR": "IC_opinion",
    "ATTACH_FS": "other",
}

TABLE_CAPTION_KEYWORDS: Dict[str, List[str]] = {
    "BS": ["재무상태표", "Statement of Financial Position", "Financial Position"],
    "PL": ["손익계산서", "포괄손익", "Comprehensive Income", "Profit or Loss"],
    "CF": ["현금흐름표", "Cash Flows"],
    "EQ": ["자본변동표", "Changes in Equity"],
}

UNIT_PATTERNS: List[Tuple[str, str, int]] = [
    (r"단위\s*[:：]?\s*백?만원", "백만원", 1_000_000),
    (r"단위\s*[:：]?\s*억원", "억원", 100_000_000),
    (r"단위\s*[:：]?\s*조원", "조원", 1_000_000_000_000),
]

UNIT_SCALE = {
    "백만원": 1_000_000,
    "억원": 100_000_000,
    "조원": 1_000_000_000_000,
}


# =========================
# 데이터 모델
# =========================
@dataclass
class SectionBlock:
    section_type_code: str
    title: Optional[str]
    order_in_doc: int
    text: str


@dataclass
class RawTablePackage:
    table_index: int
    caption: Optional[str]
    section_hint: Optional[str]
    n_rows: int
    n_cols: int
    unit_id: Optional[int]
    html: str
    text: str
    cells: List[Tuple[int, int, str]]


@dataclass
class FSBlock:
    statement_type: str  # 'BS','PL','CF','EQ'
    table_index: int     # source raw table index
    title: Optional[str]
    unit_id: Optional[int]
    lines: List[Dict[str, Any]]  # keys: order_in_table, indent_level, raw_label, amount_current, amount_prior, raw_current_str, raw_prior_str, source_table_row


@dataclass
class ParsedReport:
    meta: Dict[str, Any]
    sections: List[SectionBlock]
    raw_tables: List[RawTablePackage]
    financials: List[FSBlock]


# =========================
# 파서 구현
# =========================
class AuditReportParser:
    def __init__(self) -> None:
        self.current_file_stem: Optional[str] = None

    # 1) HTML 파싱
    def parse_html(self, file_path: str) -> BeautifulSoup:
        data = Path(file_path).read_bytes()
        # 사용 가능한 파서 우선순위: lxml > html5lib > html.parser
        parsers: List[str] = []
        if importlib.util.find_spec("lxml") is not None:
            parsers.append("lxml")
        if importlib.util.find_spec("html5lib") is not None:
            parsers.append("html5lib")
        parsers.append("html.parser")

        last_err: Optional[Exception] = None
        for parser_name in parsers:
            try:
                soup = BeautifulSoup(data, parser_name)
                for tag in soup(["script", "style", "noscript"]):
                    tag.decompose()
                return soup
            except Exception as e:
                last_err = e
                continue
        raise last_err or RuntimeError("No HTML parser available.")

    # 공통 텍스트 정규화
    def normalize_text(self, text: str) -> str:
        t = normalize_whitespace(text)
        t = re.sub(r"\[(주|Note)\s*\d+\]", "", t)
        t = re.sub(r"\(주\)", "", t)
        t = re.sub(r"※\s*", "", t)
        return t.strip()

    # 2) 섹션 추출
    def extract_sections(self, soup: BeautifulSoup) -> List[SectionBlock]:
        text = normalize_whitespace(soup.get_text("\n"))
        lines = text.split("\n")
        header_rx = {k: re.compile("|".join(v), re.IGNORECASE) for k, v in SECTION_PATTERNS.items()}

        headers: List[Tuple[int, str, str]] = []
        for i, line in enumerate(lines):
            L = line.strip()
            if not L:
                continue
            for sec_key, rx in header_rx.items():
                if rx.search(L):
                    headers.append((i, sec_key, L))
                    break
        if not headers:
            return []

        headers.append((len(lines), "END", ""))
        out: List[SectionBlock] = []
        order = 1
        for (s_idx, sec_key, title), (e_idx, _, _) in zip(headers[:-1], headers[1:]):
            body = normalize_whitespace("\n".join(lines[s_idx + 1 : e_idx]))
            if not body:
                continue
            code = SECTION_TYPE_ALIASES.get(sec_key, "other")
            out.append(
                SectionBlock(
                    section_type_code=code,
                    title=self.normalize_text(title),
                    order_in_doc=order,
                    text=self.normalize_text(body),
                )
            )
            order += 1
        return out

    # 3) 표/재무제표 추출
    def extract_tables(self, soup: BeautifulSoup) -> Tuple[List[RawTablePackage], List[FSBlock]]:
        html_str = str(soup)
        # read_html 백엔드 가용성에 따라 순차 시도
        dfs: List[pd.DataFrame] = []
        tried: List[str] = []
        for flavor in [f for f in ["lxml", "html5lib"] if importlib.util.find_spec(f) is not None]:
            try:
                dfs = pd.read_html(StringIO(html_str), flavor=flavor)
                break
            except Exception:
                tried.append(flavor)
                dfs = []
        if not dfs:
            # 마지막 시도: pandas 기본값 (가용 백엔드 자동 선택)
            try:
                dfs = pd.read_html(StringIO(html_str))
            except Exception:
                dfs = []

        soup_tables = soup.find_all("table")
        raw_list: List[RawTablePackage] = []
        fs_best: Dict[str, Tuple[int, FSBlock]] = {}

        # 파일명에서 연도 추정
        file_year = None
        if self.current_file_stem:
            m = re.search(r"(20\d{2})", self.current_file_stem)
            if m:
                file_year = int(m.group(1))

        for t_idx, df in enumerate(dfs):
            if t_idx >= len(soup_tables):
                break

            t_tag = soup_tables[t_idx]
            near = text_nearby(t_tag)
            table_text = normalize_whitespace(t_tag.get_text(" "))

            caption = self._guess_caption(near, table_text)
            pool = normalize_whitespace(" ".join([caption or "", table_text or ""]))
            # 테이블 내 포함된 여러 유형(BS/PL/CF/EQ)을 모두 후보로 수집
            types_matched = [st for st, kws in TABLE_CAPTION_KEYWORDS.items() if any(kw in pool for kw in kws)]
            unit_id, scale = self._detect_unit(near + " " + table_text)

            flat = df.copy()
            flat.columns = self._flatten_columns(flat.columns)
            flat = self._header_fix(flat)
            flat.columns = [normalize_whitespace(str(c)) for c in flat.columns]

            # raw capture
            cells: List[Tuple[int, int, str]] = []
            for r in range(flat.shape[0]):
                for c in range(flat.shape[1]):
                    cells.append((r, c, normalize_whitespace(str(flat.iat[r, c]))))

            raw_list.append(
                RawTablePackage(
                    table_index=t_idx,
                    caption=caption,
                    section_hint=caption,
                    n_rows=int(flat.shape[0]),
                    n_cols=int(flat.shape[1]),
                    unit_id=unit_id,
                    html=str(t_tag),
                    text=table_text,
                    cells=cells,
                )
            )

            # 재무제표 후보만 정규화
            cols = [str(c) for c in flat.columns]
            acc_idx = self._find_account_col(cols)
            role_year = self._role_year_map(cols, file_year)

            # 3-A) 복합표 분리: 테이블 내부 소제목으로 구간 나눔
            segments = self._detect_subheader_segments(flat, acc_idx)
            if segments:
                for st_type, start_row, end_row, header_label in segments:
                    seg_df = flat.iloc[start_row:end_row].reset_index(drop=True)
                    seg_lines = self._extract_lines_from_df(seg_df, acc_idx, role_year, scale)
                    if st_type == "BS":
                        self._ensure_bs_total_assets(seg_lines)
                    fs_block = FSBlock(
                        statement_type=st_type,
                        table_index=t_idx,
                        title=header_label or caption,
                        unit_id=unit_id,
                        lines=seg_lines,
                    )
                    prev = fs_best.get(st_type)
                    score = self._score_fs(seg_lines, st_type)
                    if (prev is None) or (score > prev[0]):
                        fs_best[st_type] = (score, fs_block)
                continue  # 이 테이블은 분리 처리 완료

            # 3-B) 일반 표 처리 (분리 불가 시 기존 방식)
            if not types_matched:
                continue
            lines = self._extract_lines_from_df(flat, acc_idx, role_year, scale)
            # BS 보강: 자산총계 없으면 유동+비유동 합산 추가
            if "BS" in types_matched:
                self._ensure_bs_total_assets(lines)

            labels = [normalize_whitespace(str(ln.get("raw_label") or "")).replace(" ", "") for ln in lines]
            has_revenue = any(("매출" in L) or ("수익" in L) for L in labels)
            has_net_income = any(L in ("당기순이익", "지배기업소유주지분순이익", "분기순이익") for L in labels)
            has_total_assets = any(("자산총계" in L) or ("총자산" in L) for L in labels)
            has_assets_parts = ("유동자산" in labels) and ("비유동자산" in labels)
            type_bonus: Dict[str, int] = {
                "PL": (10000 if (has_net_income or has_revenue) else 0),
                "BS": (10000 if (has_total_assets or has_assets_parts) else 0),
                "CF": 0,
                "EQ": 0,
            }
            base_score = self._score_fs(lines, None)
            for st_type in types_matched:
                score = base_score + type_bonus.get(st_type, 0)
                fs_block = FSBlock(
                    statement_type=st_type,
                    table_index=t_idx,
                    title=caption,
                    unit_id=unit_id,
                    lines=lines,
                )
                prev = fs_best.get(st_type)
                if (prev is None) or (score > prev[0]):
                    fs_best[st_type] = (score, fs_block)

        fs_list = [pair[1] for _, pair in sorted(fs_best.items(), key=lambda kv: kv[1][1].table_index)]
        return raw_list, fs_list

    # 내부 헬퍼
    def _guess_caption(self, near_text: str, table_text: str) -> Optional[str]:
        corpus = normalize_whitespace((near_text or "") + " " + (table_text or ""))
        for st, kws in TABLE_CAPTION_KEYWORDS.items():
            for kw in kws:
                if kw in corpus:
                    return kw
        m = re.search(r"(재무상태표|손익계산서|포괄손익|현금흐름표|자본변동표)", corpus)
        return m.group(1) if m else None

    def _map_statement_type(self, caption: Optional[str], table_text: str) -> Optional[str]:
        pool = normalize_whitespace(" ".join([caption or "", table_text or ""]))
        for st, kws in TABLE_CAPTION_KEYWORDS.items():
            if any(kw in pool for kw in kws):
                return st
        return None

    def _detect_unit(self, near_and_table_text: str) -> Tuple[Optional[int], Optional[int]]:
        t = normalize_whitespace(near_and_table_text)
        for pat, name, scale in UNIT_PATTERNS:
            if re.search(pat, t, re.IGNORECASE):
                return DEFAULT_UNIT_ID, scale
        return None, None

    # --------- 복합표 분리/라인 생성/스코어링/자산총계 보강 ---------
    def _detect_subheader_segments(self, df: pd.DataFrame, acc_idx: int) -> List[Tuple[str, int, int, Optional[str]]]:
        try:
            labels = [normalize_whitespace(str(v)).replace(" ", "") for v in df.iloc[:, acc_idx].tolist()]
        except Exception:
            return []
        # 소제목 후보 → statement type
        header_map = {
            "BS": ["요약재무상태표", "재무상태표"],
            "PL": ["요약포괄손익", "포괄손익", "손익계산서", "포괄손익계산서"],
            "CF": ["현금흐름표"],
            "EQ": ["자본변동표"],
        }
        heads: List[Tuple[int, str]] = []
        for i, lab in enumerate(labels):
            for st, kws in header_map.items():
                if any(kw in lab for kw in kws):
                    heads.append((i, st))
                    break
        if not heads:
            return []
        heads.append((len(labels), "END"))
        segments: List[Tuple[str, int, int, Optional[str]]] = []
        for (h_idx, st), (n_idx, _st2) in zip(heads[:-1], heads[1:]):
            start = h_idx + 1  # 헤더 다음 행부터 데이터
            end = n_idx
            if start < end:
                header_label = labels[h_idx]
                segments.append((st, start, end, header_label))
        return segments

    def _extract_lines_from_df(self, df: pd.DataFrame, acc_idx: int, role_year: List[Tuple[str, Optional[int]]], scale: Optional[int]) -> List[Dict[str, Any]]:
        lines: List[Dict[str, Any]] = []
        for ord_idx, (_, row) in enumerate(df.iterrows(), start=1):
            label = normalize_whitespace(str(row.iloc[acc_idx])) if acc_idx < len(row) else ""
            if not label or label.lower() in {"nan", "none"}:
                continue
            amount_current: Optional[float] = None
            amount_prior: Optional[float] = None
            raw_curr: Optional[str] = None
            raw_prev: Optional[str] = None
            for c_idx, val in enumerate(row):
                if c_idx == acc_idx:
                    continue
                role, _year = role_year[c_idx] if c_idx < len(role_year) else ("OTHER", None)
                raw_str = str(val)
                num = parse_amount(raw_str)
                if num is None:
                    continue
                mul = scale or UNIT_SCALE.get("백만원")
                num_norm = float(num) * mul if mul else float(num)
                if role == "CURRENT" and amount_current is None:
                    amount_current, raw_curr = num_norm, raw_str
                elif role == "PRIOR" and amount_prior is None:
                    amount_prior, raw_prev = num_norm, raw_str
            lines.append({
                "order_in_table": ord_idx,
                "indent_level": 0,
                "raw_label": label,
                "amount_current": amount_current,
                "amount_prior": amount_prior,
                "raw_current_str": raw_curr,
                "raw_prior_str": raw_prev,
                "source_table_row": ord_idx,
            })
        return lines

    @staticmethod
    def _score_fs(lines: List[Dict[str, Any]], st_type: Optional[str]) -> int:
        # 기본: 금액 보유 행 수
        base = sum(1 for ln in lines if (ln.get("amount_current") is not None) or (ln.get("amount_prior") is not None))
        return base

    @staticmethod
    def _ensure_bs_total_assets(lines: List[Dict[str, Any]]) -> None:
        labels_n = [normalize_whitespace(str(ln.get("raw_label") or "")).replace(" ", "") for ln in lines]
        if any(l in ("자산총계", "총자산") for l in labels_n):
            return
        # 유동/비유동 자산 합산
        curr = next((ln for ln in lines if normalize_whitespace(str(ln.get("raw_label") or "")).replace(" ", "") == "유동자산" and ln.get("amount_current") is not None), None)
        nonc = next((ln for ln in lines if normalize_whitespace(str(ln.get("raw_label") or "")).replace(" ", "") == "비유동자산" and ln.get("amount_current") is not None), None)
        if curr or nonc:
            amt_c = (curr.get("amount_current") if curr else None)
            amt_p = (curr.get("amount_prior") if curr else None)
            if nonc:
                if amt_c is None and nonc.get("amount_current") is not None:
                    amt_c = nonc.get("amount_current")
                elif amt_c is not None and nonc.get("amount_current") is not None:
                    amt_c = float(amt_c) + float(nonc.get("amount_current"))
                if amt_p is None and nonc.get("amount_prior") is not None:
                    amt_p = nonc.get("amount_prior")
                elif amt_p is not None and nonc.get("amount_prior") is not None:
                    amt_p = float(amt_p) + float(nonc.get("amount_prior"))
            order = (max([ln.get("order_in_table", 0) for ln in lines]) or 0) + 1
            lines.append({
                "order_in_table": order,
                "indent_level": 0,
                "raw_label": "자산총계",
                "amount_current": amt_c,
                "amount_prior": amt_p,
                "raw_current_str": "computed",
                "raw_prior_str": "computed",
                "source_table_row": order,
            })

    @staticmethod
    def _flatten_columns(cols) -> List[str]:
        try:
            if isinstance(cols, pd.MultiIndex):
                return ["|".join([str(x) for x in tup if str(x) != "nan"]).strip() for tup in cols.to_list()]
        except Exception:
            pass
        return [str(c) for c in cols]

    @staticmethod
    def _header_fix(df: pd.DataFrame) -> pd.DataFrame:
        cols = [str(c) for c in df.columns]
        # pandas read_html가 'Unnamed' 열명을 만드는 경우 헤더를 첫 행으로 승격 시도
        if any("Unnamed" in c for c in cols) and df.shape[0] > 0:
            cand = df.iloc[0]
            if sum(1 for v in cand if isinstance(v, str)) >= max(2, int(df.shape[1] * 0.5)):
                df2 = df.copy()
                df2.columns = [normalize_whitespace(str(x)) for x in cand]
                df2 = df2.drop(df2.index[0]).reset_index(drop=True)
                return df2
        return df

    @staticmethod
    def _find_account_col(columns: List[str]) -> int:
        for i, name in enumerate(columns):
            if re.search(r"계정|과목|항목|Account|Description", str(name), re.IGNORECASE):
                return i
        return 0

    @staticmethod
    def _role_year_map(columns: List[str], file_fiscal_year: Optional[int]) -> List[Tuple[str, Optional[int]]]:
        mapping: List[Tuple[str, Optional[int]]] = []
        for name in columns:
            n = normalize_whitespace(str(name))
            year = None
            m = re.search(r"(20\d{2})", n)
            if m:
                year = int(m.group(1))

            role = None
            if re.search(r"당기|Current|This\s*year", n, re.IGNORECASE):
                role = "CURRENT"
            elif re.search(r"전기|Prior|Previous|Last\s*year", n, re.IGNORECASE):
                role = "PRIOR"

            if role is None and year is not None and file_fiscal_year:
                if year == file_fiscal_year:
                    role = "CURRENT"
                elif year == file_fiscal_year - 1:
                    role = "PRIOR"

            mapping.append((role or "OTHER", year))
        return mapping


# =========================
# DB 저장 유틸
# =========================
def connect_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def ensure_schema(conn: sqlite3.Connection, schema_sql_path: str) -> None:
    sql = Path(schema_sql_path).read_text(encoding="utf-8")
    conn.executescript(sql)
    conn.commit()


def insert_report(conn: sqlite3.Connection, meta: Dict[str, Any]) -> int:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT report_id FROM reports
        WHERE company_id=? AND fiscal_year=? AND is_consolidated=?;
        """,
        (meta["company_id"], meta["fiscal_year"], meta["is_consolidated"]),
    )
    row = cur.fetchone()
    if row:
        return row[0]

    cur.execute(
        """
        INSERT INTO reports(company_id, fiscal_year, currency_code, presentation_unit_id,
                            is_consolidated, auditor_id, audit_opinion_code, source)
        VALUES(?,?,?,?,?,?,?,?)
        """,
        (
            meta["company_id"],
            meta["fiscal_year"],
            meta["currency_code"],
            meta["presentation_unit_id"],
            meta["is_consolidated"],
            meta["auditor_id"],
            meta["audit_opinion_code"],
            meta["source"],
        ),
    )
    conn.commit()
    return cur.lastrowid


def insert_report_file(conn: sqlite3.Connection, report_id: int, path: str, html_table_count: Optional[int]) -> int:
    cur = conn.cursor()
    h = file_hash(path)
    cur.execute(
        """
        INSERT INTO report_files(report_id, src_path, file_hash, html_table_count)
        VALUES(?,?,?,?)
        """,
        (report_id, path, h, html_table_count),
    )
    conn.commit()
    return cur.lastrowid


def insert_sections(conn: sqlite3.Connection, report_id: int, sections: List[SectionBlock]) -> None:
    if not sections:
        return
    cur = conn.cursor()
    for s in sections:
        cur.execute(
            """
            INSERT INTO sections(report_id, section_type, title, order_in_doc, text)
            VALUES(?,?,?,?,?)
            """,
            (report_id, s.section_type_code, s.title, s.order_in_doc, s.text),
        )
    conn.commit()


def insert_raw_tables(conn: sqlite3.Connection, report_id: int, file_id: int, raws: List[RawTablePackage]) -> List[int]:
    cur = conn.cursor()
    raw_ids: List[int] = []
    for rt in raws:
        # UPSERT raw_tables by (report_id, table_index)
        cur.execute(
            """
            INSERT INTO raw_tables(report_id, file_id, table_index, caption, section_hint,
                                   n_rows, n_cols, unit_id, html, text)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(report_id, table_index) DO UPDATE SET
                file_id=excluded.file_id,
                caption=excluded.caption,
                section_hint=excluded.section_hint,
                n_rows=excluded.n_rows,
                n_cols=excluded.n_cols,
                unit_id=excluded.unit_id,
                html=excluded.html,
                text=excluded.text
            """,
            (
                report_id,
                file_id,
                rt.table_index,
                rt.caption,
                rt.section_hint,
                rt.n_rows,
                rt.n_cols,
                rt.unit_id,
                rt.html,
                rt.text,
            ),
        )
        # fetch raw_table_id
        cur.execute(
            "SELECT raw_table_id FROM raw_tables WHERE report_id=? AND table_index=?",
            (report_id, rt.table_index),
        )
        raw_id = cur.fetchone()[0]
        raw_ids.append(raw_id)

        # refresh cells
        cur.execute("DELETE FROM raw_table_cells WHERE raw_table_id=?", (raw_id,))
        for (r, c, txt) in rt.cells:
            cur.execute(
                """
                INSERT INTO raw_table_cells(raw_table_id, row_idx, col_idx, rowspan, colspan, text)
                VALUES(?,?,?,?,?,?)
                """,
                (raw_id, r, c, 1, 1, txt),
            )
    conn.commit()
    return raw_ids


def upsert_financials(conn: sqlite3.Connection, report_id: int, raws: List[int], financials: List[FSBlock]) -> None:
    if not financials:
        return
    cur = conn.cursor()
    for fs in financials:
        raw_table_id = raws[fs.table_index] if (0 <= fs.table_index < len(raws)) else None
        cur.execute(
            """
            INSERT INTO financial_statements(report_id, statement_type, title, unit_id, raw_title_table, body_table)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(report_id, statement_type) DO UPDATE SET
                title=excluded.title,
                unit_id=excluded.unit_id,
                raw_title_table=excluded.raw_title_table,
                body_table=excluded.body_table
            """,
            (report_id, fs.statement_type, fs.title, fs.unit_id, None, raw_table_id),
        )
        cur.execute(
            "SELECT fs_id FROM financial_statements WHERE report_id=? AND statement_type=?",
            (report_id, fs.statement_type),
        )
        fs_id = cur.fetchone()[0]
        # 라인 재구성
        cur.execute("DELETE FROM financial_statement_lines WHERE fs_id=?", (fs_id,))
        for line in fs.lines:
            amt_c = line.get("amount_current")
            amt_p = line.get("amount_prior")
            sign_c = -1 if (isinstance(amt_c, (int, float)) and amt_c < 0) else 1
            sign_p = -1 if (isinstance(amt_p, (int, float)) and amt_p < 0) else 1
            cur.execute(
                """
                INSERT INTO financial_statement_lines(
                    fs_id, order_in_table, indent_level, raw_label,
                    amount_current, amount_prior, sign_current, sign_prior,
                    raw_current_str, raw_prior_str, source_table_row
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    fs_id,
                    line["order_in_table"],
                    line["indent_level"],
                    line["raw_label"],
                    amt_c,
                    amt_p,
                    sign_c,
                    sign_p,
                    line.get("raw_current_str"),
                    line.get("raw_prior_str"),
                    line.get("source_table_row"),
                ),
            )
    conn.commit()


# =========================
# ETL 파이프라인
# =========================
def build_payload(file_path: str) -> ParsedReport:
    parser = AuditReportParser()
    parser.current_file_stem = Path(file_path).stem
    soup = parser.parse_html(file_path)

    # 파일명에서 연도 추정
    year = None
    m = re.search(r"(20\d{2})", Path(file_path).stem)
    if m:
        year = int(m.group(1))

    sections = parser.extract_sections(soup)
    raw_tables, financials = parser.extract_tables(soup)

    return ParsedReport(
        meta={
            "company_id": DEFAULT_COMPANY_ID,
            "fiscal_year": year,
            "currency_code": DEFAULT_CURRENCY,
            "presentation_unit_id": DEFAULT_UNIT_ID,
            "is_consolidated": DEFAULT_IS_CONSOLIDATED,
            "auditor_id": DEFAULT_AUDITOR_ID,
            "audit_opinion_code": None,
            "source": file_path,
        },
        sections=sections,
        raw_tables=raw_tables,
        financials=financials,
    )


def process_file_into_db(conn: sqlite3.Connection, file_path: str) -> int:
    parsed = build_payload(file_path)

    report_id = insert_report(conn, parsed.meta)
    file_id = insert_report_file(conn, report_id, parsed.meta["source"], html_table_count=len(parsed.raw_tables))
    if parsed.sections:
        insert_sections(conn, report_id, parsed.sections)
    raw_ids: List[int] = []
    if parsed.raw_tables:
        raw_ids = insert_raw_tables(conn, report_id, file_id, parsed.raw_tables)
    if parsed.financials:
        upsert_financials(conn, report_id, raw_ids, parsed.financials)
    return report_id


def process_directory(conn: sqlite3.Connection, input_dir: str) -> None:
    d = Path(input_dir)
    files = sorted(list(d.glob("*.htm")) + list(d.glob("*.html")))
    print(f"발견된 파일 수: {len(files)}")
    for fp in files:
        try:
            rid = process_file_into_db(conn, str(fp))
            print(f"[OK] report_id={rid} ← {fp.name}")
        except Exception as e:
            print(f"[ERR] {fp.name}: {e}")


def init_and_run(input_dir: str = INPUT_DIR, db_path: str = DB_PATH, schema_path: str = SCHEMA_SQL_PATH) -> None:
    conn = connect_db(db_path)
    ensure_schema(conn, schema_path)
    process_directory(conn, input_dir)


if __name__ == "__main__":
    init_and_run()
