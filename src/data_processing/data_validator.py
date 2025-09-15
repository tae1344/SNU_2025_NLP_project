"""
Data Validation Module

이 모듈은 추출된 데이터의 품질을 검증하고 데이터 무결성을 확인하는 기능을 담당합니다.
금융 문서의 특성을 고려한 검증 규칙을 제공합니다.
"""

import logging
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
import pandas as pd

# 현재 디렉토리를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent))

from text_cleaner import TextCleaner


class DataValidator:
    """
    데이터 품질 검증 및 무결성 확인을 담당하는 클래스

    주요 기능:
    - 추출된 데이터의 완성도 및 정확성 검증
    - 금융 데이터 특화 검증 규칙
    - 누락 데이터 식별 및 처리
    - 데이터 표준화 검증
    """

    def __init__(self, log_level: str = "INFO"):
        """
        DataValidator 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)
        self.text_cleaner = TextCleaner(log_level)

        # 금융 데이터 검증 규칙 (v3 업데이트)
        self.validation_rules = {
            "required_sections": ["재무제표", "주석", "감사의견"],
            "required_section_types": ["SECTION-1", "SECTION-2"],
            "section_title_patterns": {
                "재무제표": ["재무제표", "(첨부)재무제표", "재 무 제 표", "재무제표"],
                "감사의견": ["감사의견", "독립된 감사인의 감사보고서", "감사보고서"],
                "주석": ["주석", "주석사항"],
            },
            "financial_keywords": [
                "매출액",
                "매출원가",
                "영업이익",
                "당기순이익",
                "자산",
                "부채",
                "자본",
                "현금",
                "투자",
            ],
            "date_patterns": [
                r"\d{4}년\s*\d{1,2}월\s*\d{1,2}일",
                r"\d{4}-\d{2}-\d{2}",
                r"\d{4}\.\d{2}\.\d{2}",
            ],
            "currency_patterns": [
                r"\d+(?:,\d{3})*\s*[백만억조]원",
                r"\d+(?:,\d{3})*\s*[천원|만원]",
            ],
        }

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"{__name__}.DataValidator")
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def validate_parsed_data(self, parsed_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        파싱된 전체 데이터 검증 (v2 구조 지원)

        Args:
            parsed_data: 검증할 파싱 데이터

        Returns:
            검증 결과 딕셔너리
        """
        validation_result = {
            "is_valid": True,
            "overall_score": 0.0,
            "section_validation": {},
            "table_validation": {},
            "data_quality_issues": [],
            "recommendations": [],
        }

        # 기본 구조 검증
        basic_validation = self._validate_basic_structure(parsed_data)
        validation_result.update(basic_validation)

        # v3 구조 지원: sections 검증
        if "sections" in parsed_data:
            section_validation = self.validate_sections_v3(parsed_data["sections"])
            validation_result["section_validation"] = section_validation
        # v2 구조 지원: main_sections 검증
        elif "main_sections" in parsed_data:
            section_validation = self.validate_main_sections(
                parsed_data["main_sections"]
            )
            validation_result["section_validation"] = section_validation

        # 테이블 검증 (v3에서는 섹션별로 테이블이 있음)
        if "sections" in parsed_data:
            all_tables = []
            for section in parsed_data["sections"]:
                if "tables" in section:
                    all_tables.extend(section["tables"])
                # 하위 섹션의 테이블도 포함
                if "subsections" in section:
                    for subsection in section["subsections"]:
                        if "tables" in subsection:
                            all_tables.extend(subsection["tables"])
            if all_tables:
                table_validation = self.validate_tables(all_tables)
                validation_result["table_validation"] = table_validation
        # v2 구조 지원
        elif "main_sections" in parsed_data:
            all_tables = []
            for section in parsed_data["main_sections"]:
                if "tables" in section:
                    all_tables.extend(section["tables"])
            if all_tables:
                table_validation = self.validate_tables(all_tables)
                validation_result["table_validation"] = table_validation
        # 레거시 구조 지원
        elif "tables" in parsed_data:
            table_validation = self.validate_tables(parsed_data["tables"])
            validation_result["table_validation"] = table_validation

        # 전체 품질 점수 계산
        validation_result["overall_score"] = self._calculate_quality_score(
            validation_result
        )

        return validation_result

    def validate_main_sections(
        self, main_sections: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        v2 구조의 main_sections 데이터 검증

        Args:
            main_sections: 검증할 메인 섹션 리스트

        Returns:
            메인 섹션 검증 결과
        """
        result = {
            "total_sections": len(main_sections),
            "section_types": {},
            "detailed_subsections_count": 0,
            "tables_count": 0,
            "issues": [],
            "score": 0.0,
        }

        # 섹션 타입별 카운트
        for section in main_sections:
            section_type = section.get("section_type", "UNKNOWN")
            if section_type not in result["section_types"]:
                result["section_types"][section_type] = 0
            result["section_types"][section_type] += 1

            # 세부 주석 카운트
            if "detailed_subsections" in section:
                result["detailed_subsections_count"] += len(
                    section["detailed_subsections"]
                )

            # 테이블 카운트
            if "tables" in section:
                result["tables_count"] += len(section["tables"])

        # 필수 섹션 타입 확인
        required_types = self.validation_rules.get("required_section_types", [])
        for req_type in required_types:
            if req_type not in result["section_types"]:
                result["issues"].append(f"필수 섹션 타입 '{req_type}' 누락")

        # 주석 섹션의 세부 주석 확인
        notes_sections = [s for s in main_sections if "주석" in s.get("title", "")]
        if notes_sections and result["detailed_subsections_count"] == 0:
            result["issues"].append("주석 섹션에 세부 주석이 없음")

        # 점수 계산
        total_possible = len(required_types) + 1  # 필수 섹션 + 세부 주석
        actual_score = len(required_types) - len(
            [i for i in result["issues"] if "필수 섹션" in i]
        )
        if result["detailed_subsections_count"] > 0:
            actual_score += 1
        result["score"] = actual_score / total_possible if total_possible > 0 else 0.0

        return result

    def validate_sections_v3(self, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        v3 구조의 sections 데이터 검증

        Args:
            sections: 검증할 섹션 리스트

        Returns:
            섹션 검증 결과
        """
        result = {
            "total_sections": len(sections),
            "valid_sections": 0,
            "section_types": {},
            "missing_sections": [],
            "issues": [],
            "recommendations": [],
            "score": 0.0,
        }

        # 섹션 타입별 카운트
        for section in sections:
            section_type = section.get("section_type", "UNKNOWN")
            if section_type not in result["section_types"]:
                result["section_types"][section_type] = 0
            result["section_types"][section_type] += 1

        # 필수 섹션 확인 (패턴 매칭 사용)
        section_titles = [section.get("title", "") for section in sections]
        required_sections = self.validation_rules["required_sections"]
        section_patterns = self.validation_rules["section_title_patterns"]

        for required_section in required_sections:
            found = False
            patterns = section_patterns.get(required_section, [required_section])

            for pattern in patterns:
                if any(pattern in title for title in section_titles):
                    found = True
                    break

            if not found:
                result["missing_sections"].append(required_section)
                result["issues"].append(
                    f"필수 섹션 '{required_section}'이 누락되었습니다."
                )

        # 각 섹션 개별 검증
        for i, section in enumerate(sections):
            section_validation = self._validate_single_section_v3(section, i)
            if section_validation["is_valid"]:
                result["valid_sections"] += 1
            else:
                result["issues"].extend(section_validation["issues"])

        # 하위 섹션 검증
        total_subsections = 0
        for section in sections:
            subsections = section.get("subsections", [])
            total_subsections += len(subsections)

            # 하위 섹션의 유효성 검증
            for j, subsection in enumerate(subsections):
                sub_validation = self._validate_single_section_v3(
                    subsection, f"{i}-{j}"
                )
                if not sub_validation["is_valid"]:
                    result["issues"].extend(
                        [
                            f"하위 섹션 {i}-{j}: {issue}"
                            for issue in sub_validation["issues"]
                        ]
                    )

        result["total_subsections"] = total_subsections

        # 점수 계산
        total_possible = len(required_sections) + 1  # 필수 섹션 + 하위 섹션 존재
        actual_score = len(required_sections) - len(result["missing_sections"])
        if total_subsections > 0:
            actual_score += 1
        result["score"] = actual_score / total_possible if total_possible > 0 else 0.0

        return result

    def _validate_single_section_v3(
        self, section: Dict[str, Any], section_index: Union[int, str]
    ) -> Dict[str, Any]:
        """
        v3 구조의 단일 섹션 검증

        Args:
            section: 검증할 섹션
            section_index: 섹션 인덱스

        Returns:
            섹션 검증 결과
        """
        result = {
            "is_valid": True,
            "issues": [],
            "recommendations": [],
        }

        # 필수 필드 확인 (v3 구조에 맞게)
        required_fields = ["section_id", "section_type", "title", "hierarchy_level"]
        for field in required_fields:
            if field not in section:
                result["is_valid"] = False
                result["issues"].append(f"필수 필드 '{field}'이 누락되었습니다.")

        # 섹션 타입 검증
        section_type = section.get("section_type", "")
        if section_type and not section_type.startswith("SECTION-"):
            result["issues"].append(f"섹션 타입 '{section_type}'이 올바르지 않습니다.")

        # 계층 레벨 검증
        hierarchy_level = section.get("hierarchy_level", 0)
        if not isinstance(hierarchy_level, int) or hierarchy_level < 1:
            result["issues"].append(
                f"계층 레벨 '{hierarchy_level}'이 올바르지 않습니다."
            )

        # 제목 검증
        title = section.get("title", "")
        if not title or len(title.strip()) < 2:
            result["issues"].append("섹션 제목이 너무 짧거나 비어있습니다.")

        # 테이블 데이터 검증
        tables = section.get("tables", [])
        if tables:
            for i, table in enumerate(tables):
                if not isinstance(table, dict):
                    result["issues"].append(f"테이블 {i}이 올바른 형식이 아닙니다.")
                elif "data" not in table:
                    result["issues"].append(f"테이블 {i}에 데이터가 없습니다.")

        return result

    def validate_sections(self, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        섹션 데이터 검증

        Args:
            sections: 검증할 섹션 리스트

        Returns:
            섹션 검증 결과
        """
        result = {
            "total_sections": len(sections),
            "valid_sections": 0,
            "missing_sections": [],
            "issues": [],
            "recommendations": [],
        }

        # 필수 섹션 확인
        section_titles = [section.get("title", "") for section in sections]

        for required_section in self.validation_rules["required_sections"]:
            if not any(required_section in title for title in section_titles):
                result["missing_sections"].append(required_section)
                result["issues"].append(
                    f"필수 섹션 '{required_section}'이 누락되었습니다."
                )

        # 각 섹션 개별 검증
        for i, section in enumerate(sections):
            section_validation = self._validate_single_section(section, i)
            if section_validation["is_valid"]:
                result["valid_sections"] += 1
            else:
                result["issues"].extend(section_validation["issues"])

        # 섹션 순서 검증
        section_numbers = [s.get("section_number", 0) for s in sections]
        if section_numbers != sorted(section_numbers):
            result["issues"].append("섹션 번호가 순서대로 정렬되지 않았습니다.")
            result["recommendations"].append("섹션을 번호 순으로 정렬하세요.")

        return result

    def validate_tables(self, tables: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        테이블 데이터 검증

        Args:
            tables: 검증할 테이블 리스트

        Returns:
            테이블 검증 결과
        """
        result = {
            "total_tables": len(tables),
            "valid_tables": 0,
            "empty_tables": 0,
            "financial_tables": 0,
            "issues": [],
            "recommendations": [],
        }

        for i, table in enumerate(tables):
            table_validation = self._validate_single_table(table, i)

            if table_validation["is_valid"]:
                result["valid_tables"] += 1
            else:
                result["issues"].extend(table_validation["issues"])

            if table_validation.get("is_empty", False):
                result["empty_tables"] += 1

            if table_validation.get("is_financial", False):
                result["financial_tables"] += 1

        # 테이블 품질 분석
        if result["empty_tables"] > 0:
            result["issues"].append(
                f"{result['empty_tables']}개의 빈 테이블이 있습니다."
            )

        if result["financial_tables"] == 0:
            result["issues"].append("재무 테이블이 발견되지 않았습니다.")
            result["recommendations"].append("재무제표 관련 테이블을 확인하세요.")

        return result

    def _validate_basic_structure(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """기본 구조 검증"""
        result = {
            "is_valid": True,
            "issues": [],
            "recommendations": [],
        }

        # 필수 필드 확인
        required_fields = [
            "version",
            "source_filename",
            "report_year",
            "sections",
            "tables",
        ]

        for field in required_fields:
            if field not in data:
                result["is_valid"] = False
                result["issues"].append(f"필수 필드 '{field}'이 누락되었습니다.")

        # 데이터 타입 검증
        if "report_year" in data and not isinstance(
            data["report_year"], (int, type(None))
        ):
            result["issues"].append("report_year는 정수여야 합니다.")

        if "sections" in data and not isinstance(data["sections"], list):
            result["issues"].append("sections는 리스트여야 합니다.")

        if "tables" in data and not isinstance(data["tables"], list):
            result["issues"].append("tables는 리스트여야 합니다.")

        return result

    def _validate_single_section(
        self, section: Dict[str, Any], index: int
    ) -> Dict[str, Any]:
        """개별 섹션 검증"""
        result = {
            "is_valid": True,
            "issues": [],
            "warnings": [],
        }

        # 필수 필드 확인
        required_fields = ["title", "level", "section_number", "content"]

        for field in required_fields:
            if field not in section:
                result["is_valid"] = False
                result["issues"].append(
                    f"섹션 {index}: 필수 필드 '{field}'이 누락되었습니다."
                )

        # 내용 검증
        if "content" in section:
            content = section["content"]
            if not content or not content.strip():
                result["warnings"].append(f"섹션 {index}: 내용이 비어있습니다.")
            else:
                # 금융 키워드 포함 여부 확인
                has_financial_keywords = any(
                    keyword in content
                    for keyword in self.validation_rules["financial_keywords"]
                )
                if not has_financial_keywords:
                    result["warnings"].append(
                        f"섹션 {index}: 금융 키워드가 포함되지 않았습니다."
                    )

        # 주석 섹션 특별 검증
        if section.get("section_number") == 2 and "주석" in section.get("title", ""):
            subsections = section.get("subsections", [])
            if not subsections:
                result["warnings"].append("주석 섹션에 세부 섹션이 없습니다.")

        return result

    def _validate_single_table(
        self, table: Dict[str, Any], index: int
    ) -> Dict[str, Any]:
        """개별 테이블 검증 (v3 업데이트)"""
        result = {
            "is_valid": True,
            "is_empty": False,
            "is_financial": False,
            "issues": [],
            "warnings": [],
        }

        # v3 구조에 맞는 데이터 확인
        data = table.get("data")
        if not data:
            result["is_valid"] = False
            result["is_empty"] = True
            result["issues"].append(f"테이블 {index}: 데이터가 없습니다.")
            return result

        # v3 구조에서 shape 정보 확인
        shape = table.get("shape", [0, 0])
        if isinstance(shape, list) and len(shape) >= 2:
            row_count, column_count = shape[0], shape[1]
        else:
            # shape 정보가 없으면 data에서 직접 계산
            if isinstance(data, list):
                row_count = len(data)
                column_count = len(data[0]) if data and isinstance(data[0], dict) else 0
            else:
                row_count, column_count = 0, 0

        # 빈 테이블 확인 (더 관대한 기준)
        if row_count == 0:
            result["is_valid"] = False
            result["is_empty"] = True
            result["issues"].append(f"테이블 {index}: 행이 없습니다.")
            return result

        # 재무 테이블 여부 확인 (v3 구조)
        if table.get("has_notes_references", False):
            result["is_financial"] = True

        # 데이터 품질 확인 (v3 구조)
        if isinstance(data, list) and data:
            # 빈 셀 비율 계산
            total_cells = 0
            empty_cells = 0

            for row in data:
                if isinstance(row, dict):
                    for key, value in row.items():
                        total_cells += 1
                        if value is None or value == "" or str(value).strip() == "":
                            empty_cells += 1

            if total_cells > 0:
                empty_ratio = empty_cells / total_cells
                if empty_ratio > 0.5:  # 50% 이상이 비어있으면 경고
                    result["warnings"].append(
                        f"테이블 {index}: {empty_ratio:.1%}의 셀이 비어있습니다."
                    )

        return result

    def _calculate_quality_score(self, validation_result: Dict[str, Any]) -> float:
        """품질 점수 계산 (0.0 ~ 1.0) - v3 업데이트"""
        score = 1.0

        # 기본 구조 문제로 인한 감점 (더 관대하게)
        issues = validation_result.get("issues", [])
        score -= len(issues) * 0.05  # 0.1에서 0.05로 감소

        # 섹션 검증 결과 반영
        section_validation = validation_result.get("section_validation", {})

        # v3 구조에서는 score 필드가 있으면 사용
        if "score" in section_validation:
            section_score = section_validation["score"]
        else:
            # 레거시 방식
            total_sections = section_validation.get("total_sections", 0)
            valid_sections = section_validation.get("valid_sections", 0)
            section_score = (
                valid_sections / total_sections if total_sections > 0 else 0.0
            )

        # 테이블 검증 결과 반영
        table_validation = validation_result.get("table_validation", {})
        total_tables = table_validation.get("total_tables", 0)
        valid_tables = table_validation.get("valid_tables", 0)
        table_score = valid_tables / total_tables if total_tables > 0 else 1.0

        # 가중 평균 계산 (섹션 60%, 테이블 30%, 기본 10%)
        final_score = (section_score * 0.6) + (table_score * 0.3) + (score * 0.1)

        return max(0.0, min(1.0, final_score))

    def validate_financial_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        금융 데이터 특화 검증

        Args:
            data: 검증할 데이터

        Returns:
            금융 데이터 검증 결과
        """
        result = {
            "is_valid": True,
            "financial_indicators": {},
            "issues": [],
            "recommendations": [],
        }

        # 재무제표 항목 검증
        financial_items = self._extract_financial_items(data)
        result["financial_indicators"] = financial_items

        # 금액 데이터 검증
        amount_validation = self._validate_amounts(data)
        result.update(amount_validation)

        # 날짜 데이터 검증
        date_validation = self._validate_dates(data)
        result.update(date_validation)

        return result

    def _extract_financial_items(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """재무 항목 추출 및 분석"""
        items = {
            "revenue": [],
            "assets": [],
            "liabilities": [],
            "equity": [],
            "profit": [],
        }

        # 섹션에서 재무 항목 추출
        for section in data.get("sections", []):
            content = section.get("content", "")

            # 매출 관련
            if "매출" in content:
                items["revenue"].append(section.get("title", ""))

            # 자산 관련
            if "자산" in content:
                items["assets"].append(section.get("title", ""))

            # 부채 관련
            if "부채" in content:
                items["liabilities"].append(section.get("title", ""))

            # 자본 관련
            if "자본" in content:
                items["equity"].append(section.get("title", ""))

            # 손익 관련
            if "손익" in content or "이익" in content:
                items["profit"].append(section.get("title", ""))

        return items

    def _validate_amounts(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """금액 데이터 검증"""
        result = {
            "amount_issues": [],
            "amount_recommendations": [],
        }

        # 테이블에서 금액 패턴 검색
        for table in data.get("tables", []):
            table_data = table.get("data", [])

            for row in table_data:
                for value in row.values():
                    if isinstance(value, str):
                        # 금액 패턴 확인
                        if re.search(r"\d+(?:,\d{3})*", value):
                            # 음수 금액 확인
                            if "(" in value and ")" in value:
                                result["amount_recommendations"].append(
                                    "음수 금액이 괄호로 표시되어 있습니다."
                                )

        return result

    def _validate_dates(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """날짜 데이터 검증"""
        result = {
            "date_issues": [],
            "date_recommendations": [],
        }

        # 파일명에서 연도 추출
        filename = data.get("source_filename", "")
        year_match = re.search(r"(\d{4})", filename)

        if year_match:
            file_year = int(year_match.group(1))
            report_year = data.get("report_year")

            if report_year and file_year != report_year:
                result["date_issues"].append(
                    f"파일명 연도({file_year})와 보고서 연도({report_year})가 일치하지 않습니다."
                )

        return result

    def generate_validation_report(self, validation_result: Dict[str, Any]) -> str:
        """
        검증 결과 리포트 생성

        Args:
            validation_result: 검증 결과

        Returns:
            검증 리포트 문자열
        """
        report = []
        report.append("=== 데이터 검증 리포트 ===")
        report.append("")

        # 전체 점수
        score = validation_result.get("overall_score", 0.0)
        report.append(f"전체 품질 점수: {score:.2f}/1.00")
        report.append("")

        # 섹션 검증 결과
        section_validation = validation_result.get("section_validation", {})
        report.append("=== 섹션 검증 결과 ===")
        report.append(f"총 섹션 수: {section_validation.get('total_sections', 0)}")
        report.append(f"유효한 섹션 수: {section_validation.get('valid_sections', 0)}")

        if section_validation.get("missing_sections"):
            report.append(
                f"누락된 섹션: {', '.join(section_validation['missing_sections'])}"
            )

        report.append("")

        # 테이블 검증 결과
        table_validation = validation_result.get("table_validation", {})
        report.append("=== 테이블 검증 결과 ===")
        report.append(f"총 테이블 수: {table_validation.get('total_tables', 0)}")
        report.append(f"유효한 테이블 수: {table_validation.get('valid_tables', 0)}")
        report.append(f"재무 테이블 수: {table_validation.get('financial_tables', 0)}")
        report.append(f"빈 테이블 수: {table_validation.get('empty_tables', 0)}")
        report.append("")

        # 문제점 및 권장사항
        issues = validation_result.get("data_quality_issues", [])
        if issues:
            report.append("=== 발견된 문제점 ===")
            for issue in issues:
                report.append(f"- {issue}")
            report.append("")

        recommendations = validation_result.get("recommendations", [])
        if recommendations:
            report.append("=== 권장사항 ===")
            for rec in recommendations:
                report.append(f"- {rec}")
            report.append("")

        return "\n".join(report)
