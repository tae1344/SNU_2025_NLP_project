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

        for i, table in enumerate(table_tags):
            try:
                table_data = self._parse_table(table, i)
                if table_data:
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
        soup = BeautifulSoup(section_content, "html.parser")
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

            # 주석 컬럼 처리
            df = self._process_notes_columns(df)

            # 테이블 데이터 정리
            table_records = df.to_dict("records")
            table_records = self._clean_nan_values(table_records)

            # 테이블 메타데이터 추출
            metadata = self._extract_table_metadata(table, df)

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
            if "주석" in str(col):
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
