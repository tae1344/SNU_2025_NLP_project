"""
Text Cleaning Module

이 모듈은 금융 텍스트의 정규화 및 정제를 담당합니다.
한국어 금융 문서의 특성을 고려한 텍스트 전처리 기능을 제공합니다.
"""

import logging
import re
from typing import Any, Dict, List, Optional


class TextCleaner:
    """
    금융 텍스트 정규화 및 정제를 담당하는 클래스

    주요 기능:
    - 금융 텍스트 정규화 및 정제
    - 한국어 금융 용어 표준화
    - 숫자 및 단위 정리
    - 구두점 및 공백 정리
    """

    def __init__(self, log_level: str = "INFO"):
        """
        TextCleaner 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)

        # 금융 용어 매핑 - {value, code} 형태
        # 재무상태표(BS), 손익계산서, 포괄손익계산서(PL), 자본변동표(Changes in Equity), 현금흐름표(CF)
        self.financial_terms = {
            # 재무제표 관련
            "재무상태표": {"value": "재무상태표", "code": "BS"},
            # 손익계산서 관련
            "손익계산서": {"value": "손익계산서", "code": "PL"},
            "포괄손익계산서": {"value": "포괄손익계산서", "code": "PL"},
            # 현금흐름표 관련
            "현금흐름표": {"value": "현금흐름표", "code": "CF"},
            # 자본변동표 관련
            "자본변동표": {"value": "자본변동표", "code": "EQ"},
            # 기타 재무 용어
            "주석": {"value": "주석", "code": "NOTE"},
            "감사의견": {"value": "감사의견", "code": "AUDIT"},
            "매출액": {"value": "매출액", "code": "REV"},
            "매출원가": {"value": "매출원가", "code": "COGS"},
            "영업이익": {"value": "영업이익", "code": "OPI"},
            "당기순이익": {"value": "당기순이익", "code": "NI"},
            "자산": {"value": "자산", "code": "ASSET"},
            "부채": {"value": "부채", "code": "LIAB"},
            "자본": {"value": "자본", "code": "EQUITY"},
            "현금": {"value": "현금", "code": "CASH"},
            "투자": {"value": "투자", "code": "INV"},
        }

        # 단위 정규화 패턴
        self.unit_patterns = [
            (r"(\d+)\s*([백만억조]원)", r"\1\2"),  # 숫자-단위 공백 제거
            (r"(\d+)\s*([%])", r"\1\2"),  # 숫자-퍼센트 공백 제거
            (r"(\d+)\s*([천원|만원|억원|조원])", r"\1\2"),  # 숫자-단위 공백 제거
        ]

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"{__name__}.TextCleaner")
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def normalize_text(self, text: str) -> str:
        """
        금융 텍스트 정규화 및 정제

        Args:
            text: 정규화할 텍스트

        Returns:
            정규화된 텍스트
        """
        if not text:
            return ""

        # 기본 텍스트 정리
        text = text.strip()

        # 연속된 공백을 단일 공백으로 변환
        text = re.sub(r"\s+", " ", text)

        # 금융 관련 특수 문자 정규화
        text = self._normalize_currency_symbols(text)

        # 숫자와 단위 사이 공백 정리
        text = self._normalize_units(text)

        # 괄호 정리
        text = self._normalize_brackets(text)

        # 연속된 구두점 정리
        text = self._normalize_punctuation(text)

        # 금융 용어 표준화
        text = self._standardize_financial_terms(text)

        return text

    def clean_section_content(self, content: str) -> str:
        """
        섹션 내용 정리

        Args:
            content: 섹션 내용 텍스트

        Returns:
            정리된 섹션 내용
        """
        if not content:
            return ""

        # 기본 정규화
        cleaned = self.normalize_text(content)

        # 줄바꿈 정리
        cleaned = self._normalize_line_breaks(cleaned)

        # 빈 줄 정리
        cleaned = self._remove_empty_lines(cleaned)

        return cleaned

    def clean_table_text(self, text: str) -> str:
        """
        테이블 텍스트 정리

        Args:
            text: 테이블 셀 텍스트

        Returns:
            정리된 테이블 텍스트
        """
        if not text:
            return ""

        # 기본 정규화
        cleaned = self.normalize_text(text)

        # 테이블 특화 정리
        cleaned = self._clean_table_specific(cleaned)

        return cleaned

    def _normalize_currency_symbols(self, text: str) -> str:
        """통화 기호 정규화"""
        # 원화 기호 통일
        text = re.sub(r"[₩]", "원", text)

        # 달러 기호 정규화
        text = re.sub(r"[$]", "USD", text)

        # 유로 기호 정규화
        text = re.sub(r"[€]", "EUR", text)

        return text

    def _normalize_units(self, text: str) -> str:
        """단위 정규화"""
        for pattern, replacement in self.unit_patterns:
            text = re.sub(pattern, replacement, text)

        return text

    def _normalize_brackets(self, text: str) -> str:
        """괄호 정리"""
        # 괄호 앞뒤 공백 정리
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)

        # 괄호 안 공백 정리
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)

        return text

    def _normalize_punctuation(self, text: str) -> str:
        """구두점 정리"""
        # 연속된 마침표 정리
        text = re.sub(r"\.{2,}", "...", text)

        # 연속된 쉼표 정리
        text = re.sub(r",{2,}", ",", text)

        # 연속된 물음표 정리
        text = re.sub(r"\?{2,}", "?", text)

        # 연속된 느낌표 정리
        text = re.sub(r"!{2,}", "!", text)

        return text

    def _standardize_financial_terms(self, text: str) -> str:
        """금융 용어 표준화"""
        for original, term_info in self.financial_terms.items():
            # 대소문자 구분 없이 매칭
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            # 표준화된 값으로 교체
            text = pattern.sub(term_info["value"], text)

        return text

    def _normalize_line_breaks(self, text: str) -> str:
        """줄바꿈 정리"""
        # 연속된 줄바꿈을 최대 2개로 제한
        text = re.sub(r"\n\s*\n", "\n\n", text)

        # 줄 끝 공백 제거
        text = re.sub(r"[ \t]+\n", "\n", text)

        return text

    def _remove_empty_lines(self, text: str) -> str:
        """빈 줄 제거"""
        lines = text.split("\n")
        cleaned_lines = [line for line in lines if line.strip()]
        return "\n".join(cleaned_lines)

    def _clean_table_specific(self, text: str) -> str:
        """테이블 특화 정리"""
        # 테이블 셀의 불필요한 공백 제거
        text = text.strip()

        # 숫자 패턴 정리
        text = re.sub(r"(\d+)\s*,\s*(\d+)", r"\1,\2", text)  # 천 단위 구분자

        # 괄호 안 숫자를 음수로 처리
        # 금융 문서에서 괄호는 일반적으로 음수를 나타냄
        text = re.sub(r"\((\d+(?:,\d{3})*(?:\.\d+)?)\)", r"-\1", text)

        return text

    def extract_financial_numbers(self, text: str) -> list[dict]:
        """
        텍스트에서 금융 숫자 추출

        Args:
            text: 분석할 텍스트

        Returns:
            추출된 금융 숫자 정보 리스트
        """
        numbers = []

        # 금액 패턴 (백만원, 억원 등) - 괄호 포함
        amount_patterns = [
            r"\((\d+(?:,\d{3})*)\)\s*([백만억조]원)",  # 괄호로 감싸진 금액 (음수)
            r"\((\d+(?:,\d{3})*)\)\s*([천원|만원])",  # 괄호로 감싸진 금액 (음수)
            r"(\d+(?:,\d{3})*)\s*([백만억조]원)",  # 일반 금액
            r"(\d+(?:,\d{3})*)\s*([천원|만원])",  # 일반 금액
        ]

        for i, pattern in enumerate(amount_patterns):
            matches = re.finditer(pattern, text)
            for match in matches:
                value_str = match.group(1).replace(",", "")
                unit = match.group(2)
                original = match.group(0)

                # 처음 두 패턴은 괄호로 감싸진 음수
                is_negative = i < 2
                if is_negative:
                    value_str = "-" + value_str

                numbers.append(
                    {
                        "value": value_str,
                        "numeric_value": (
                            float(value_str)
                            if value_str.replace("-", "").replace(".", "").isdigit()
                            else None
                        ),
                        "unit": unit,
                        "original": original,
                        "is_negative": is_negative,
                        "position": match.start(),
                    }
                )

        return numbers

    def extract_percentages(self, text: str) -> list[dict]:
        """
        텍스트에서 퍼센트 추출

        Args:
            text: 분석할 텍스트

        Returns:
            추출된 퍼센트 정보 리스트
        """
        percentages = []

        # 퍼센트 패턴
        pattern = r"(\d+(?:\.\d+)?)\s*%"
        matches = re.finditer(pattern, text)

        for match in matches:
            percentages.append(
                {
                    "value": float(match.group(1)),
                    "original": match.group(0),
                    "position": match.start(),
                }
            )

        return percentages

    def validate_financial_text(self, text: str) -> dict:
        """
        금융 텍스트 유효성 검증

        Args:
            text: 검증할 텍스트

        Returns:
            검증 결과 딕셔너리
        """
        result = {
            "is_valid": True,
            "issues": [],
            "suggestions": [],
        }

        # 빈 텍스트 검사
        if not text or not text.strip():
            result["is_valid"] = False
            result["issues"].append("빈 텍스트입니다.")
            return result

        # 금융 용어 포함 여부 검사
        has_financial_terms = any(term in text for term in self.financial_terms.keys())

        if not has_financial_terms:
            result["suggestions"].append("금융 용어가 포함되지 않았습니다.")
        else:
            # 금융 용어 분석 추가
            financial_analysis = self.analyze_financial_content(text)
            if financial_analysis["statement_type"]:
                result["suggestions"].append(
                    f"재무제표 유형 감지: {financial_analysis['statement_type']}"
                )
            if financial_analysis["total_terms"] > 0:
                result["suggestions"].append(
                    f"금융 용어 {financial_analysis['total_terms']}개 발견"
                )

        # 숫자 포함 여부 검사
        has_numbers = bool(re.search(r"\d+", text))

        if not has_numbers:
            result["suggestions"].append("숫자가 포함되지 않았습니다.")

        # 특수 문자 검사
        special_chars = re.findall(r"[^\w\s가-힣.,()%원]", text)
        if special_chars:
            result["suggestions"].append(
                f"특수 문자가 포함되어 있습니다: {set(special_chars)}"
            )

        return result

    def extract_financial_terms(self, text: str) -> List[Dict[str, Any]]:
        """
        텍스트에서 금융 용어 추출 및 분석

        Args:
            text: 분석할 텍스트

        Returns:
            추출된 금융 용어 정보 리스트
        """
        terms = []

        for original, term_info in self.financial_terms.items():
            # 대소문자 구분 없이 매칭
            pattern = re.compile(re.escape(original), re.IGNORECASE)
            matches = pattern.finditer(text)

            for match in matches:
                terms.append(
                    {
                        "original": match.group(0),
                        "standardized": term_info["value"],
                        "code": term_info["code"],
                        "position": match.start(),
                        "length": len(match.group(0)),
                    }
                )

        # 위치 순으로 정렬
        terms.sort(key=lambda x: x["position"])
        return terms

    def get_financial_statement_type(self, text: str) -> Optional[str]:
        """
        텍스트에서 재무제표 유형 추출

        Args:
            text: 분석할 텍스트

        Returns:
            재무제표 유형 코드 (BS, PL, CF, EQ, None)
        """
        # 재무제표 유형별 키워드 매핑
        statement_keywords = {
            "BS": [
                "재무상태표",
            ],
            "PL": [
                "손익계산서",
                "포괄손익계산서",
            ],
            "CF": ["현금흐름표"],
            "EQ": ["자본변동표"],
        }

        # 각 유형별로 키워드 매칭 확인
        for stmt_type, keywords in statement_keywords.items():
            if any(keyword in text for keyword in keywords):
                return stmt_type

        return None

    def analyze_financial_content(self, text: str) -> Dict[str, Any]:
        """
        금융 내용 종합 분석

        Args:
            text: 분석할 텍스트

        Returns:
            금융 내용 분석 결과
        """
        # 금융 용어 추출
        terms = self.extract_financial_terms(text)

        # 재무제표 유형 추출
        statement_type = self.get_financial_statement_type(text)

        # 금융 숫자 추출
        numbers = self.extract_financial_numbers(text)

        # 퍼센트 추출
        percentages = self.extract_percentages(text)

        # 용어별 그룹화
        terms_by_code = {}
        for term in terms:
            code = term["code"]
            if code not in terms_by_code:
                terms_by_code[code] = []
            terms_by_code[code].append(term)

        return {
            "statement_type": statement_type,
            "total_terms": len(terms),
            "terms_by_code": terms_by_code,
            "financial_numbers": numbers,
            "percentages": percentages,
            "has_financial_content": len(terms) > 0 or len(numbers) > 0,
            "content_richness": self._calculate_content_richness(text, terms, numbers),
        }

    def _calculate_content_richness(
        self, text: str, terms: List[Dict], numbers: List[Dict]
    ) -> float:
        """내용 풍부도 계산 (0.0 ~ 1.0)"""
        if not text.strip():
            return 0.0

        # 기본 점수
        score = 0.0

        # 금융 용어 비율
        if terms:
            term_ratio = len(terms) / len(text.split())
            score += min(term_ratio * 10, 0.4)  # 최대 0.4점

        # 금융 숫자 비율
        if numbers:
            number_ratio = len(numbers) / len(text.split())
            score += min(number_ratio * 10, 0.3)  # 최대 0.3점

        # 텍스트 길이 점수
        text_length = len(text.strip())
        if text_length > 100:
            score += 0.1
        if text_length > 500:
            score += 0.1
        if text_length > 1000:
            score += 0.1

        return min(score, 1.0)
