# audit_parser.py
from __future__ import annotations
from bs4 import BeautifulSoup, Tag
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
import re, hashlib
import chardet

# --------------------------------------------------------------------
# 중간 결과 모델(로더 계층에 그대로 넘기기 쉬운 dict로 변환 가능)
# --------------------------------------------------------------------
@dataclass
class ParsedHTML:
    soup: BeautifulSoup
    encoding: str
    file_hash: str
    html_table_count: int

# --------------------------------------------------------------------
# 파서 본체
# --------------------------------------------------------------------
class AuditReportParser:
    """
    Samsung audit report(HTML) → 섹션/표/셀 중간결과 생성
    - BeautifulSoup(lxml) 기반
    - 표 단위 raw capture + 셀 텍스트 추출
    - 단위/문맥에서 재무제표 종류(BS/PL/CF/EQ) 추정
    - 섹션(감사의견/KAM 등) 텍스트 블록 추출
    """

    # 문서별 섹션/헤더 후보 셀렉터(연도/템플릿 변형 대비)
    SECTION_HINT_SELECTORS = [
        "p.SECTION-1", "p.SECTION-2", "p.SECTION-3", "p.part",
        "h1", "h2", "h3", "h4"
    ]

    # 재무제표 키워드(공백/자모/특수문자 제거 후 매칭)
    STMT_KEYWORDS = {
        "BS": ["재무상태표", "대차대조표"],
        "PL": ["손익계산서", "포괄손익계산서", "포괄손익"],
        "CF": ["현금흐름표", "현금흐름"],
        "EQ": ["자본변동표", "자본의변동표"]
    }

    # 섹션 유형 힌트
    SECTION_TYPES = {
        "감사의견": "opinion",
        "감사범위 및 근거": "basis",
        "강조사항": "emphasis",
        "핵심감사사항": "KAM",
        "경영진의 책임": "management_resp",
        "감사인의 책임": "auditor_resp",
        "내부회계관리제도": "IC_opinion",
        "서문": "intro",
        "기타": "other",
    }

    UNIT_PAT = re.compile(r"\(단위\s*[:：]\s*([^)]+)\)")
    NUM_PAT = re.compile(r"[-+()]?\d{1,3}(?:,\d{3})*(?:\.\d+)?")

    # ----------------------------
    # 1) HTML 파일 파싱 및 기본 전처리
    # ----------------------------
    def parse_html(self, file_path: str) -> ParsedHTML:
        """HTML 파일 파싱 및 기본 전처리"""
        raw = Path(file_path).read_bytes()
        enc = (chardet.detect(raw) or {}).get("encoding") or "euc-kr"
        text = raw.decode(enc, errors="ignore")

        # 제어문자/불필요 태그 정리
        text = text.replace("\u00a0", " ")
        soup = BeautifulSoup(text, "lxml")
        for t in soup(["script", "style"]):
            t.decompose()

        # 문서 메타
        file_hash = hashlib.sha256(raw).hexdigest()
        html_table_count = len(soup.find_all("table"))

        return ParsedHTML(
            soup=soup,
            encoding=enc,
            file_hash=file_hash,
            html_table_count=html_table_count
        )

    # ----------------------------
    # 2) 주요 섹션별 텍스트 추출
    # ----------------------------
    def extract_sections(self, parsed_html: ParsedHTML) -> List[Dict[str, Any]]:
        """주요 섹션별 텍스트 추출 → sections 테이블 스키마에 맞춘 중간결과"""
        soup = parsed_html.soup
        sections: List[Dict[str, Any]] = []
        seen_titles: set[str] = set()
        order = 0

        # 섹션 헤더 후보 탐색
        candidates: List[Tag] = []
        for sel in self.SECTION_HINT_SELECTORS:
            candidates.extend(soup.select(sel))
        # 문서 순서대로 중복 제거
        seen_ids = set()
        ordered = []
        for n in candidates:
            if id(n) not in seen_ids:
                seen_ids.add(id(n))
                ordered.append(n)

        for node in ordered:
            title = self._clean(node.get_text(" ", strip=True))
            if not title:
                continue

            # 다음 섹션 전까지 본문 모으기
            body_parts: List[str] = []
            for sib in node.next_siblings:
                if isinstance(sib, Tag) and self._is_section_header(sib):
                    break
                if isinstance(sib, Tag) and sib.name not in {"table", "script", "style"}:
                    body_parts.append(self._clean(sib.get_text(" ", strip=True)))
            body = "\n".join([p for p in body_parts if p])

            # 섹션 유형 추정
            section_type = self._guess_section_type(title, body)
            # 같은 제목이 연속으로 나오면 1회만 수집
            key = (title, section_type)
            if key in seen_titles:
                continue
            seen_titles.add(key)

            order += 1
            sections.append({
                # sections(report_id, section_type, title, order_in_doc, text)
                "section_type": section_type,   # e.g., 'opinion','KAM','other'
                "title": title,
                "order_in_doc": order,
                "text": body
            })

        return sections

    # ----------------------------
    # 3) 재무제표 및 주요 표 데이터 추출 (raw_tables/raw_table_cells + statement 추정)
    # ----------------------------
    def extract_tables(self, parsed_html: ParsedHTML) -> Dict[str, Any]:
        """
        raw_tables/raw_table_cells 형태의 구조와,
        재무제표 추정 결과(financial_statements + financial_statement_lines 유사 구조)를 함께 반환.
        실제 DB 적재는 별도 로더 계층에서 수행.
        """
        soup = parsed_html.soup
        tables = soup.find_all("table")

        raw_tables: List[Dict[str, Any]] = []
        raw_cells: List[Dict[str, Any]] = []
        fs_list: List[Dict[str, Any]] = []
        fs_lines: List[Dict[str, Any]] = []

        for idx, tbl in enumerate(tables):
            # 표 주변 텍스트에서 캡션/단위/문맥 추정
            near_text = self._neighbor_text(tbl, limit_up=2, limit_down=0)
            unit_label = self._detect_unit(near_text)
            stmt_type = self._guess_statement_type(near_text)

            # 표 플랫 텍스트 & HTML
            flat_text = self._clean(tbl.get_text(" ", strip=True))
            html_str = str(tbl)

            # 셀 추출
            matrix, (n_rows, n_cols) = self._table_to_matrix(tbl)

            raw_table_id = None  # 실제 적재 시 생성될 PK (여기선 None)
            raw_tables.append({
                # raw_tables(report_id, file_id, table_index, caption, section_hint, n_rows, n_cols, unit_id, html, text)
                "table_index": idx,
                "caption": self._caption_from_text(near_text),
                "section_hint": stmt_type or "",
                "n_rows": n_rows,
                "n_cols": n_cols,
                "unit_label": unit_label,   # units 테이블과 매핑은 로더에서 수행
                "html": html_str,
                "text": flat_text
            })

            # raw_table_cells
            for r, row in enumerate(matrix):
                for c, cell_text in enumerate(row):
                    raw_cells.append({
                        # raw_table_cells(raw_table_id, row_idx, col_idx, rowspan, colspan, text)
                        "raw_table_idx": idx,
                        "row_idx": r,
                        "col_idx": c,
                        "rowspan": 1,
                        "colspan": 1,
                        "text": self._clean(cell_text)
                    })

            # 재무제표 본문 후보: 열/행 수와 키워드로 대략 구분
            if stmt_type and n_rows >= 3 and n_cols >= 2:
                fs_list.append({
                    # financial_statements(report_id, statement_type, title, unit_id, raw_title_table, body_table)
                    "statement_type": stmt_type,          # 'BS'/'PL'/'CF'/'EQ'
                    "title": self._caption_from_text(near_text),
                    "raw_title_table": None,
                    "body_table": idx,
                    "unit_label": unit_label
                })
                # 라인 파싱(1열=항목명, 나머지=당기/전기 수치로 가정; 실제 문서별로 조정 필요)
                header, body_rows = self._split_header_body(matrix)
                col_roles = self._infer_amount_columns(header)
                order_in_table = 0
                for row in body_rows:
                    if not row:
                        continue
                    order_in_table += 1
                    raw_label = self._clean(row[0]) if len(row) > 0 else ""
                    amounts = self._extract_amounts(row, col_roles)
                    fs_lines.append({
                        # financial_statement_lines(fs_id, order_in_table, raw_label, note_refs, concept_id, amount_current, amount_prior, ...)
                        "statement_type": stmt_type,
                        "source_table_idx": idx,
                        "order_in_table": order_in_table,
                        "raw_label": raw_label,
                        "note_refs": self._extract_note_refs(raw_label),
                        "amount_current": amounts.get("current"),
                        "amount_prior": amounts.get("prior"),
                        "raw_current_str": amounts.get("raw_current"),
                        "raw_prior_str": amounts.get("raw_prior"),
                        "indent_level": self._infer_indent(raw_label),
                        "sign_current": -1 if self._looks_negative(amounts.get("raw_current")) else 1,
                        "sign_prior": -1 if self._looks_negative(amounts.get("raw_prior")) else 1,
                        # concept_id 매핑은 별도(동의어 사전/개념 테이블)
                        "concept_id": None
                    })

        return {
            "raw_tables": raw_tables,
            "raw_table_cells": raw_cells,
            "financial_statements": fs_list,
            "financial_statement_lines": fs_lines
        }

    # ----------------------------
    # 4) 금융 텍스트 정규화 및 정제
    # ----------------------------
    def normalize_text(self, text: str) -> str:
        """금융 텍스트 정규화 및 정제 (숫자/한글 공백/특수기호 정리)"""
        if text is None:
            return ""
        t = str(text)
        # 공백/제어문자
        t = t.replace("\u00a0", " ")
        t = re.sub(r"[ \t\r\f\v]+", " ", t)
        t = re.sub(r"\s*\n+\s*", "\n", t).strip()
        # 한글 특수문자/긴 대시/전각 부호 정리
        t = t.replace("–", "-").replace("—", "-").replace("－", "-")
        # 숫자 괄호 음수 표기를 유지하기 위해 숫자는 그대로 둡니다.
        return t

    # ================================================================
    # 내부 유틸
    # ================================================================
    def _clean(self, s: str | None) -> str:
        return self.normalize_text(s or "")

    def _is_section_header(self, node: Tag) -> bool:
        if not isinstance(node, Tag):
            return False
        if node.name in {"h1", "h2", "h3", "h4"}:
            return True
        if node.name == "p" and any(cls.startswith("SECTION") or cls == "part"
                                    for cls in (node.get("class") or [])):
            return True
        # 키워드 기반 간이 판단
        text = self._clean(node.get_text(" ", strip=True))
        return any(k in text for k in ["감사의견", "핵심감사사항", "강조사항", "감사인의 책임"])

    def _guess_section_type(self, title: str, body: str) -> str:
        t = self._strip_spaces(title)
        for k, v in self.SECTION_TYPES.items():
            if self._strip_spaces(k) in t:
                return v
        # 본문 키워드로 보정
        if "핵심감사사항" in title or "핵심감사사항" in body:
            return "KAM"
        if "감사의견" in title:
            return "opinion"
        if "강조사항" in title:
            return "emphasis"
        return "other"

    def _strip_spaces(self, s: str) -> str:
        return re.sub(r"\s+", "", s)

    def _neighbor_text(self, tbl: Tag, limit_up: int = 2, limit_down: int = 0) -> str:
        """표 근처(앞쪽 몇 개 블록)의 텍스트를 이어붙여 문맥을 만든다."""
        texts = []
        # 위쪽 두 블록 정도만 확인(제목/단위/문맥)
        prevs = []
        p = tbl
        for _ in range(limit_up):
            p = p.find_previous(["p", "h1", "h2", "h3", "h4"])
            if not p:
                break
            prevs.append(p)
        prevs.reverse()
        for n in prevs:
            texts.append(self._clean(n.get_text(" ", strip=True)))
        if limit_down > 0:
            q = tbl
            for _ in range(limit_down):
                q = q.find_next(["p", "h1", "h2", "h3", "h4"])
                if not q:
                    break
                texts.append(self._clean(q.get_text(" ", strip=True)))
        return " ".join([t for t in texts if t])

    def _detect_unit(self, text: str) -> Optional[str]:
        """'(단위: 백만원)' 등에서 단위 라벨만 추출 (units.label 매핑은 로더에서)"""
        if not text:
            return None
        m = self.UNIT_PAT.search(text)
        if m:
            return m.group(1).strip()
        # 보조 규칙: '단위 백만원' 같은 변형
        m2 = re.search(r"단위\s*([가-힣A-Za-z]+)", text)
        if m2:
            return m2.group(1).strip()
        return None

    def _guess_statement_type(self, text: str) -> Optional[str]:
        """문맥 키워드로 BS/PL/CF/EQ 추정"""
        if not text:
            return None
        t = self._strip_spaces(text)
        for code, keys in self.STMT_KEYWORDS.items():
            for k in keys:
                if self._strip_spaces(k) in t:
                    return code
        return None

    def _caption_from_text(self, text: str) -> Optional[str]:
        if not text:
            return None
        # 첫 문장/키워드 라인만 슬라이스
        return text[:180]

    def _table_to_matrix(self, table: Tag) -> Tuple[List[List[str]], Tuple[int, int]]:
        """단순 테이블 → 2차원 문자열 배열 (rowspan/colspan은 펼치지 않고 최소 구현)"""
        matrix: List[List[str]] = []
        for tr in table.find_all("tr"):
            row = [self._clean(td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
            if any(cell for cell in row):
                matrix.append(row)
        n_rows = len(matrix)
        n_cols = max((len(r) for r in matrix), default=0)
        # 짧은 행은 우측을 빈 문자열로 패딩(간단 정렬용)
        for r in matrix:
            if len(r) < n_cols:
                r.extend([""] * (n_cols - len(r)))
        return matrix, (n_rows, n_cols)

    def _split_header_body(self, matrix: List[List[str]]) -> Tuple[List[str], List[List[str]]]:
        """첫 행을 헤더로 가정(문서별 변형 많으므로 단순 규칙)"""
        if not matrix:
            return [], []
        header = matrix[0]
        body = matrix[1:] if len(matrix) > 1 else []
        return header, body

    def _infer_amount_columns(self, header: List[str]) -> Dict[str, int]:
        """
        당기/전기 추정:
        - 헤더에 '제56기','당기','2024' 등 최신 연도 → current
        - '제55기','전기','2023' 등 → prior
        """
        roles = {"current": None, "prior": None}
        if not header:
            return roles
        hdr_join = " ".join(header)
        # 최신 연/전년 단순 휴리스틱
        # (로더에서 보고서 연도로 보강하는 것을 권장)
        for i, h in enumerate(header):
            h2 = self._strip_spaces(h)
            if any(tok in h2 for tok in ["당기", "제56기", "2024", "현재"]):
                roles["current"] = i
            if any(tok in h2 for tok in ["전기", "제55기", "2023", "전년"]):
                roles["prior"] = i
        # 컬럼 지정이 없으면 오른쪽 2개를 current/prior로 가정
        if roles["current"] is None and len(header) >= 2:
            roles["current"] = len(header) - 1
        if roles["prior"] is None and len(header) >= 2:
            roles["prior"] = len(header) - 2
        return roles

    def _looks_negative(self, raw: Optional[str]) -> bool:
        if not raw:
            return False
        return "(" in raw and ")" in raw or raw.strip().startswith("-")

    def _to_number(self, s: Optional[str]) -> Optional[float]:
        if not s:
            return None
        s2 = s.strip()
        neg = self._looks_negative(s2)
        s2 = s2.replace("(", "").replace(")", "")
        s2 = s2.replace(",", "")
        m = self.NUM_PAT.fullmatch(s2)
        if not m:
            return None
        try:
            val = float(s2)
            return -val if neg else val
        except Exception:
            return None

    def _extract_amounts(self, row: List[str], roles: Dict[str, Optional[int]]) -> Dict[str, Any]:
        d: Dict[str, Any] = {}
        ci = roles.get("current")
        pi = roles.get("prior")
        if ci is not None and ci < len(row):
            d["raw_current"] = row[ci]
            d["current"] = self._to_number(row[ci])
        if pi is not None and pi < len(row):
            d["raw_prior"] = row[pi]
            d["prior"] = self._to_number(row[pi])
        return d

    def _extract_note_refs(self, label: str) -> Optional[str]:
        # 예: '현금및현금성자산 (주석 4, 27)' → '4, 27'
        m = re.search(r"주석\s*([0-9,\-\s]+)", label)
        if m:
            return m.group(1).strip()
        return None

    def _infer_indent(self, label: str) -> int:
        """
        들여쓰기 수준 추정(Ⅰ/1/가 등 계층 표현)
        - 추후 문서별 규칙 보강 가능
        """
        t = self._strip_spaces(label)
        if re.match(r"^[ⅠIIIVX]+[.\)]", t):
            return 0
        if re.match(r"^\d+[.\)]", t):
            return 1
        if re.match(r"^[가-힣][.\)]", t):
            return 2
        return 0
