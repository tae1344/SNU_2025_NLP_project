"""
Table Extraction Module

이 모듈은 HTML에서 테이블 데이터를 추출하고 구조화하는 기능을 담당합니다.
pandas를 사용하여 테이블을 파싱하고 JSON 직렬화 가능한 형태로 변환합니다.
"""

import logging
import re
import sys
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pandas as pd
from bs4 import BeautifulSoup, Tag

# 현재 디렉토리를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent))

from text_cleaner import TextCleaner


class TableExtractor:
    """
    HTML 테이블 추출 및 구조화를 담당하는 클래스

    주요 기능:
    - HTML 테이블 추출 및 파싱
    - pandas를 사용한 테이블 데이터 변환
    - MultiIndex 컬럼 처리
    - NaN 값 정리 및 JSON 직렬화
    """

    def __init__(self, log_level: str = "INFO"):
        """
        TableExtractor 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)
        self.text_cleaner = TextCleaner(log_level)

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"{__name__}.TableExtractor")
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def extract_tables(self, parsed_html: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        HTML에서 모든 테이블 추출

        Args:
            parsed_html: BeautifulSoup 객체

        Returns:
            테이블 정보가 담긴 딕셔너리 리스트
        """
        tables = []
        table_tags = parsed_html.find_all("table")

        # Apply unit only to the table immediately following a unit anchor
        pending_unit: Optional[Dict[str, Any]] = None

        for i, table in enumerate(table_tags):
            try:
                table_data = self._parse_table(table, i)
                if not table_data:
                    continue

                # 단위 상속/적용 메타 처리
                meta = table_data.get("metadata", {})
                unit_candidate = meta.get("unit_candidate")
                require_unit = bool(meta.get("require_unit"))

                if unit_candidate:
                    # Mark this table as an anchor and schedule unit for the next table only
                    unit_candidate["table_index"] = i
                    meta["unit"] = unit_candidate
                    table_data.setdefault("normalized", {})["unit"] = unit_candidate
                    pending_unit = unit_candidate
                else:
                    if pending_unit:
                        # Apply the pending unit to this table, then clear
                        inherited = dict(pending_unit)
                        inherited["source"] = "inherited"
                        inherited["inherited_from_index"] = pending_unit.get(
                            "table_index"
                        )
                        meta["unit"] = inherited
                        table_data.setdefault("normalized", {})["unit"] = inherited
                        meta["unit_inherited"] = True
                        pending_unit = None
                    else:
                        meta["unit_inherited"] = False

                tables.append(table_data)
                self.logger.debug(f"테이블 {i+1} 추출 완료")

            except Exception as e:
                self.logger.warning(f"테이블 {i+1} 추출 실패: {e}")
                continue

        self.logger.info(f"총 {len(tables)}개 테이블 추출 완료")
        return tables

    def extract_tables_from_section(self, section_content: str) -> List[Dict[str, Any]]:
        """
        섹션 내용에서 테이블 추출

        Args:
            section_content: 섹션 HTML 내용

        Returns:
            테이블 정보가 담긴 딕셔너리 리스트
        """
        soup = BeautifulSoup(str(section_content), "html.parser")
        return self.extract_tables(soup)

    def _parse_table(self, table: Tag, index: int) -> Optional[Dict[str, Any]]:
        """
        개별 테이블 파싱

        Args:
            table: BeautifulSoup Table 태그
            index: 테이블 인덱스

        Returns:
            파싱된 테이블 데이터 딕셔너리
        """
        try:
            table_html = str(table)

            # pandas로 테이블 파싱
            df = pd.read_html(StringIO(table_html), flavor="html5lib")[0]

            # NaN 값 처리
            df = self._clean_dataframe(df)

            # 컬럼명 정리 (MultiIndex 처리)
            df = self._normalize_columns(df)

            # 주석 컬럼 처리 (공백/영문 표기까지 포함해 감지)
            df = self._process_notes_columns(df)

            # 테이블 데이터 정리
            table_records = df.to_dict("records")

            # 주석 컬럼 판별 헬퍼 (공백/대소문자/영문 대응)
            def _is_note_col(col_name: str) -> bool:
                n = str(col_name or "").strip().lower().replace(" ", "")
                return any(
                    tok in n for tok in ["주석", "note", "비고"]
                )  # space-insensitive

            # 테이블 숫자/텍스트 정리 (주석 컬럼은 원본 유지)
            for record in table_records:
                for k, v in record.items():
                    if _is_note_col(k):
                        # 주석 컬럼은 dict(notes_reference) 또는 원문 문자열 유지
                        record[k] = v
                    else:
                        record[k] = (
                            self.text_cleaner.clean_table_text(v)
                            if isinstance(v, str)
                            else v
                        )

            table_records = self._clean_nan_values(table_records)

            # 테이블 메타데이터 추출
            metadata = self._extract_table_metadata(table, df)

            # 단위 후보/필요여부/오버라이드 탐지
            unit_candidate = self._detect_unit_from_table(
                table, table_html, df, table_records
            )
            require_unit, column_units = self._classify_require_unit(df, table_records)
            overrides = self._detect_unit_overrides(table_records)

            if unit_candidate:
                metadata["unit_candidate"] = unit_candidate

            metadata["require_unit"] = require_unit
            if column_units:
                metadata["column_units"] = column_units
            if overrides:
                metadata["override_units"] = overrides

            return {
                "index": index,
                "table_html": table_html,
                "data": table_records,
                "columns": [str(col) for col in df.columns.tolist()],
                "shape": df.shape,
                "row_count": df.shape[0],
                "column_count": df.shape[1],
                "metadata": metadata,
                "has_notes_references": self._has_notes_references(df),
            }

        except Exception as e:
            self.logger.warning(f"테이블 {index} 파싱 실패: {e}")
            return None

    def _process_notes_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        테이블의 주석 컬럼에서 comma 구분 숫자값을 주석 번호 참조로 처리

        Args:
            df: 원본 DataFrame

        Returns:
            처리된 DataFrame
        """
        processed_df = df.copy()

        for col in processed_df.columns:
            col_norm = str(col).strip().lower().replace(" ", "")
            if any(tok in col_norm for tok in ["주석", "note", "비고"]):
                processed_df[col] = processed_df[col].apply(
                    self._process_notes_reference
                )

        return processed_df

    def _process_notes_reference(self, value) -> Optional[Dict[str, Any]]:
        """
        주석 참조 값 처리 (comma 구분 숫자 -> 주석 번호 참조)

        Args:
            value: 원본 값

        Returns:
            처리된 주석 참조 데이터
        """
        if pd.isna(value) or value is None:
            return None

        value_str = str(value).strip()

        # comma로 구분된 숫자 패턴 확인
        if re.match(r"^\d+(?:,\s*\d+)*$", value_str):
            # comma로 구분된 숫자들을 리스트로 변환
            note_numbers = [int(x.strip()) for x in value_str.split(",")]
            return {
                "type": "notes_reference",
                "note_numbers": note_numbers,
                "original_value": value_str,
                "reference_count": len(note_numbers),
            }
        else:
            # 일반 텍스트는 그대로 반환
            return {"type": "text", "value": value_str}

    def _has_notes_references(self, df: pd.DataFrame) -> bool:
        """
        테이블에 주석 참조가 있는지 확인

        Args:
            df: DataFrame

        Returns:
            주석 참조 존재 여부
        """
        for col in df.columns:
            if "주석" in str(col):
                for value in df[col]:
                    if (
                        isinstance(value, dict)
                        and value.get("type") == "notes_reference"
                    ):
                        return True
        return False

    def _clean_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        DataFrame 정리

        Args:
            df: 정리할 DataFrame

        Returns:
            정리된 DataFrame
        """
        # NaN 값 처리
        df = df.where(pd.notnull(df), None)
        df = df.map(lambda x: None if pd.isna(x) else x)

        # 빈 행 제거
        df = df.dropna(how="all")

        # 빈 열 제거
        df = df.dropna(axis=1, how="all")

        return df

    def _normalize_columns(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        컬럼명 정규화

        Args:
            df: 정규화할 DataFrame

        Returns:
            정규화된 DataFrame
        """
        # MultiIndex 컬럼 처리
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [
                str(col) if isinstance(col, tuple) else col for col in df.columns
            ]

        # 컬럼명 정리
        df.columns = [
            self.text_cleaner.clean_table_text(str(col)) for col in df.columns
        ]

        # 중복 컬럼명 처리
        df.columns = self._handle_duplicate_columns(df.columns)

        return df

    def _handle_duplicate_columns(self, columns: List[str]) -> List[str]:
        """
        중복 컬럼명 처리

        Args:
            columns: 컬럼명 리스트

        Returns:
            중복이 제거된 컬럼명 리스트
        """
        seen = {}
        new_columns = []

        for col in columns:
            if col in seen:
                seen[col] += 1
                new_columns.append(f"{col}_{seen[col]}")
            else:
                seen[col] = 0
                new_columns.append(col)

        return new_columns

    def _clean_nan_values(self, obj: Any) -> Any:
        """
        중첩된 데이터 구조에서 NaN 값 정리

        Args:
            obj: 정리할 객체

        Returns:
            정리된 객체
        """
        if isinstance(obj, dict):
            return {k: self._clean_nan_values(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_nan_values(item) for item in obj]
        elif pd.isna(obj) or (isinstance(obj, float) and str(obj).lower() == "nan"):
            return None
        else:
            return obj

    def _extract_table_metadata(self, table: Tag, df: pd.DataFrame) -> Dict[str, Any]:
        """
        테이블 메타데이터 추출

        Args:
            table: BeautifulSoup Table 태그
            df: 파싱된 DataFrame

        Returns:
            테이블 메타데이터 딕셔너리
        """
        metadata = {
            "has_header": self._has_header_row(table),
            "has_footer": self._has_footer_row(table),
            "is_financial_table": self._is_financial_table(df),
            "data_types": self._infer_data_types(df),
            "empty_cells": self._count_empty_cells(df),
        }

        return metadata

    # -------------------------
    # Unit helpers
    # -------------------------

    def _parse_unit_from_text(self, text: str) -> Optional[Dict[str, Any]]:
        """텍스트에서 (단위: X) 패턴을 추출하여 multiplier 계산."""
        if not text:
            return None
        m = re.search(r"\(\s*단위\s*[:：]\s*([^\)]+)\)", text)
        if not m:
            return None
        unit_raw = m.group(1).strip()
        unit_norm = unit_raw.replace(" ", "")
        multiplier = None
        # 한국어 단위
        if any(k in unit_norm for k in ["백만원", "백만 원", "백만원"]):
            multiplier = 1_000_000
            unit_label = "백만원"
        elif any(k in unit_norm for k in ["천원", "천 원"]):
            multiplier = 1_000
            unit_label = "천원"
        elif any(k in unit_norm for k in ["억원", "억 원"]):
            multiplier = 100_000_000
            unit_label = "억원"
        elif any(k in unit_norm for k in ["원"]):
            multiplier = 1
            unit_label = "원"
        else:
            # 외화/기타 단위는 원문 유지
            unit_label = unit_raw
            multiplier = None

        return {"unit": unit_label, "multiplier": multiplier, "source": "table"}

    def _should_apply_inherited_unit(
        self,
        metadata: Dict[str, Any],
        table_records: List[Dict[str, Any]],
        columns: List[str],
    ) -> bool:
        """상속 단위를 적용할지 여부에 대한 경량 휴리스틱.

        규칙:
        - 숫자 비중이 일정 수준(>= 0.15) 이상이면 적용
        - 또는 금융 키워드(금액/합계/원/백만원 등)나 합계 행이 존재하면 적용
        - 그 외(순수 텍스트/요약 표)는 미적용
        """
        # 1) 숫자 비중 계산
        total = 0
        numeric = 0
        for rec in table_records:
            for v in rec.values():
                total += 1
                if isinstance(v, (int, float)):
                    numeric += 1
                elif (
                    isinstance(v, str) and v.replace(",", "").replace(".", "").isdigit()
                ):
                    numeric += 1
        if total > 0 and (numeric / total) >= 0.15:
            return True

        # 2) 금융 키워드/통화 힌트
        keywords = ["원", "백만원", "천원", "억원", "금액", "합계", "총계", "%"]
        col_text = " ".join([str(c) for c in columns])
        if any(k in col_text for k in keywords):
            return True
        # 레코드 텍스트 스캔(가벼운 검사)
        scan_limit = min(len(table_records), 5)
        for rec in table_records[:scan_limit]:
            for v in rec.values():
                if isinstance(v, str) and any(k in v for k in keywords):
                    return True

        # 3) 메타 힌트: is_financial_table이 참이면 적용
        if bool(metadata.get("is_financial_table")):
            return True

        return False

    def _normalize_single_unit(self, token: str) -> Dict[str, Any]:
        """단일 단위 토큰을 표준화하여 유형/배율 정보를 부여."""
        tok = token.strip()
        tok_norm = tok.replace(" ", "").lower()

        unit_type = "other"
        multiplier = None
        label = tok

        # 통화 단위
        if any(k in tok_norm for k in ["백만원"]):
            unit_type, label, multiplier = "money", "백만원", 1_000_000
        elif any(k in tok_norm for k in ["천원"]):
            unit_type, label, multiplier = "money", "천원", 1_000
        elif any(k in tok_norm for k in ["억원"]):
            unit_type, label, multiplier = "money", "억원", 100_000_000
        elif any(k in tok_norm for k in ["원"]):
            unit_type, label, multiplier = "money", "원", 1
        elif any(k in tok_norm for k in ["usd", "us$", "달러"]):
            unit_type, label, multiplier = "money", tok, None

        # 수량/주식 단위
        elif any(k in tok_norm for k in ["천주"]):
            unit_type, label, multiplier = "shares", "천주", 1_000
        elif any(k in tok_norm for k in ["주"]):
            unit_type, label, multiplier = "shares", "주", 1

        # 비율
        elif "%" in tok or any(k in tok_norm for k in ["percent", "퍼센트", "율"]):
            unit_type, label, multiplier = "percent", "%", None

        return {"raw": tok, "unit": label, "type": unit_type, "multiplier": multiplier}

    def _parse_units_from_text(self, text: str) -> Optional[List[Dict[str, Any]]]:
        """텍스트에서 (단위: X[, Y ...]) 패턴을 모두 파싱하여 단위 리스트 반환."""
        if not text:
            return None
        m = re.search(r"\(\s*단위\s*[:：]\s*([^\)]+)\)", text)
        if not m:
            return None
        payload = m.group(1)
        tokens = re.split(r"[,，;；·]+", payload)
        units = [self._normalize_single_unit(t) for t in tokens if t.strip()]
        return units or None

    def _detect_unit_from_table(
        self,
        table: Tag,
        table_html: str,
        df: pd.DataFrame,
        table_records: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """헤더/캡션 우선 단위 후보 탐지. 필요 시 '앵커성 표'에 한해 본문도 허용.

        주의: 행/셀 내부의 "(단위: ...)"는 표 전체 단위를 덮지 않기 위해 이 단계에서 무시하고
        별도의 _detect_unit_overrides()에서 행 오버라이드로만 처리한다.
        """
        # 헤더/캡션 텍스트에서만 탐지
        header_texts = []
        for tag_name in ("caption", "thead", "th"):
            for tag in table.find_all(tag_name):
                header_texts.append(tag.get_text(" "))
        units = self._parse_units_from_text(" \n ".join(header_texts))
        if units:
            main = next((u for u in units if u.get("type") == "money"), units[0])
            return {
                "unit": main["unit"],
                "multiplier": main.get("multiplier"),
                "source": "table",
                "units": units,
            }

        # 앵커성 표(작고 숫자 비중 낮은 표)는 본문에서도 단위 문구를 앵커로 허용
        row_count = df.shape[0]
        col_count = df.shape[1]
        total = 0
        numeric = 0
        for rec in table_records:
            for v in rec.values():
                total += 1
                if isinstance(v, (int, float)):
                    numeric += 1
                elif (
                    isinstance(v, str) and v.replace(",", "").replace(".", "").isdigit()
                ):
                    numeric += 1
        numeric_ratio = (numeric / total) if total else 0

        is_anchor_like = row_count <= 6 and col_count <= 4 and numeric_ratio < 0.2
        if is_anchor_like:
            body_texts = []
            for rec in table_records:
                for v in rec.values():
                    if isinstance(v, str):
                        body_texts.append(v)
            units = self._parse_units_from_text(" \n ".join(body_texts))
            if units:
                main = next((u for u in units if u.get("type") == "money"), units[0])
                return {
                    "unit": main["unit"],
                    "multiplier": main.get("multiplier"),
                    "source": "table",
                    "units": units,
                }
        return None

    def _classify_require_unit(
        self, df: pd.DataFrame, table_records: List[Dict[str, Any]]
    ) -> (bool, Optional[Dict[str, str]]):
        """단위 필요 여부와 컬럼별 단위 힌트('%', '율' 등) 분류."""
        # 숫자 비중 기반 휴리스틱
        numeric_cells = 0
        total_cells = 0
        for rec in table_records:
            for v in rec.values():
                total_cells += 1
                if isinstance(v, (int, float)):
                    numeric_cells += 1
                elif (
                    isinstance(v, str) and v.replace(",", "").replace(".", "").isdigit()
                ):
                    numeric_cells += 1
        numeric_ratio = (numeric_cells / total_cells) if total_cells else 0
        require_unit = numeric_ratio > 0.3

        # 컬럼 단위 힌트 수집
        column_units: Dict[str, str] = {}
        for col in df.columns:
            c = str(col)
            c_norm = c.lower().replace(" ", "")
            if "%" in c or any(k in c_norm for k in ["율", "ratio", "margin"]):
                column_units[str(col)] = "%"
            elif any(k in c_norm for k in ["주식수", "shares", "주식", "주"]):
                column_units[str(col)] = "주"

        return require_unit, (column_units or None)

    def _detect_unit_overrides(
        self, table_records: List[Dict[str, Any]]
    ) -> Optional[Dict[int, Dict[str, Any]]]:
        """행 레벨 단위 오버라이드 탐지."""
        overrides: Dict[int, Dict[str, Any]] = {}
        for idx, rec in enumerate(table_records):
            texts = [v for v in rec.values() if isinstance(v, str)]
            if not texts:
                continue
            unit = None
            for t in texts:
                units = self._parse_units_from_text(t)
                if units:
                    main = next(
                        (u for u in units if u.get("type") == "money"), units[0]
                    )
                    unit = {
                        "unit": main["unit"],
                        "multiplier": main.get("multiplier"),
                        "source": "table",
                        "units": units,
                    }
                    break
            if unit:
                overrides[idx] = unit
        return overrides or None

    def _has_header_row(self, table: Tag) -> bool:
        """헤더 행 존재 여부 확인"""
        return bool(table.find("th") or table.find("thead"))

    def _has_footer_row(self, table: Tag) -> bool:
        """푸터 행 존재 여부 확인"""
        return bool(table.find("tfoot"))

    def _is_financial_table(self, df: pd.DataFrame) -> bool:
        """재무 테이블 여부 확인"""
        financial_keywords = [
            "재무제표",
            "손익계산서",
            "현금흐름표",
            "자본변동표",
            "매출액",
            "매출원가",
            "영업이익",
            "당기순이익",
            "자산",
            "부채",
            "자본",
            "현금",
            "투자",
        ]

        # 컬럼명이나 데이터에서 금융 키워드 검색
        text_content = " ".join([str(col) for col in df.columns])
        text_content += " " + " ".join([str(val) for val in df.values.flatten() if val])

        return any(keyword in text_content for keyword in financial_keywords)

    def _infer_data_types(self, df: pd.DataFrame) -> Dict[str, str]:
        """데이터 타입 추론"""
        data_types = {}

        for col in df.columns:
            col_data = df[col].dropna()

            if col_data.empty:
                data_types[str(col)] = "empty"
            elif col_data.dtype == "object":
                # 숫자 패턴 확인
                numeric_count = 0
                for val in col_data:
                    if (
                        isinstance(val, str)
                        and val.replace(",", "").replace(".", "").isdigit()
                    ):
                        numeric_count += 1

                if numeric_count / len(col_data) > 0.8:
                    data_types[str(col)] = "numeric_string"
                else:
                    data_types[str(col)] = "text"
            else:
                data_types[str(col)] = str(col_data.dtype)

        return data_types

    def _count_empty_cells(self, df: pd.DataFrame) -> int:
        """빈 셀 개수 계산"""
        return df.isnull().sum().sum()

    def validate_table(self, table_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        테이블 데이터 유효성 검증

        Args:
            table_data: 검증할 테이블 데이터

        Returns:
            검증 결과 딕셔너리
        """
        result = {
            "is_valid": True,
            "issues": [],
            "warnings": [],
        }

        # 기본 구조 검증
        if not table_data.get("data"):
            result["is_valid"] = False
            result["issues"].append("테이블 데이터가 없습니다.")
            return result

        if table_data.get("row_count", 0) == 0:
            result["is_valid"] = False
            result["issues"].append("테이블에 행이 없습니다.")
            return result

        if table_data.get("column_count", 0) == 0:
            result["is_valid"] = False
            result["issues"].append("테이블에 열이 없습니다.")
            return result

        # 데이터 품질 검증
        empty_cells = table_data.get("metadata", {}).get("empty_cells", 0)
        total_cells = table_data.get("row_count", 0) * table_data.get("column_count", 0)

        if total_cells > 0:
            empty_ratio = empty_cells / total_cells
            if empty_ratio > 0.5:
                result["warnings"].append(f"빈 셀이 {empty_ratio:.1%}를 차지합니다.")

        return result

    def get_table_summary(self, tables: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        테이블 목록 요약 정보 생성

        Args:
            tables: 테이블 데이터 리스트

        Returns:
            요약 정보 딕셔너리
        """
        if not tables:
            return {"total_tables": 0}

        total_tables = len(tables)
        total_rows = sum(table.get("row_count", 0) for table in tables)
        total_columns = sum(table.get("column_count", 0) for table in tables)

        financial_tables = sum(
            1
            for table in tables
            if table.get("metadata", {}).get("is_financial_table", False)
        )

        largest_table = max(tables, key=lambda x: x.get("row_count", 0))

        return {
            "total_tables": total_tables,
            "total_rows": total_rows,
            "total_columns": total_columns,
            "financial_tables": financial_tables,
            "largest_table": {
                "index": largest_table.get("index", 0),
                "rows": largest_table.get("row_count", 0),
                "columns": largest_table.get("column_count", 0),
            },
            "average_rows": total_rows / total_tables if total_tables > 0 else 0,
            "average_columns": total_columns / total_tables if total_tables > 0 else 0,
        }
