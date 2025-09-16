"""
Samsung Electronics Audit Report Parser V3.0

이 모듈은 삼성전자 감사보고서 HTML 파일을 파싱하여 구조화된 데이터로 변환하는 메인 클래스를 제공합니다.
Version 3.0에서는 텍스트 기반 섹션 분류와 계층적 파싱을 지원합니다.

주요 기능:
- 텍스트 기반 섹션 분류 (태그 기반이 아님)
- 계층적 섹션 파싱 (SECTION-1 → SECTION-2 → SECTION-3...)
- 주석 섹션 특별 처리 ("주석" 텍스트 기반 감지)
- 부모-자식 관계 추적
- 중복 방지 및 견고한 에러 처리
"""

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import pandas as pd

# 현재 디렉토리를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent))

from data_processing.html_parser_v3 import HTMLParserV3
from data_processing.section_parser import SectionParser
from data_processing.table_extractor import TableExtractor
from data_processing.text_cleaner import TextCleaner
from data_processing.data_validator import DataValidator


class AuditReportParser:
    """
    삼성전자 감사보고서 HTML 파일을 파싱하여 구조화된 데이터로 변환하는 메인 클래스 (Version 3.0)

    주요 기능:
    - HTML 파일 파싱 및 기본 전처리 (HTMLParserV3 모듈)
    - 텍스트 기반 섹션 분류 및 계층적 파싱 (SectionParser 모듈)
    - 주석 섹션 특별 처리 ("주석" 텍스트 기반 감지)
    - 테이블의 주석 참조 처리 (TableExtractor 모듈)
    - 금융 텍스트 정규화 및 정제 (TextCleaner 모듈)
    - 데이터 품질 검증 및 무결성 확인 (DataValidator 모듈)
    """

    def __init__(self, log_level: str = "INFO"):
        """
        AuditReportParser 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)

        # 하위 모듈 초기화
        self.html_parser = HTMLParserV3(log_level)
        self.section_parser = SectionParser(log_level)
        self.table_extractor = TableExtractor(log_level)
        self.text_cleaner = TextCleaner(log_level)
        self.data_validator = DataValidator(log_level)

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"{__name__}.AuditReportParser")
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def parse_html(self, file_path: Union[str, Path]):
        """
        HTML 파일 파싱 및 기본 전처리

        Args:
            file_path: HTML 파일 경로

        Returns:
            BeautifulSoup 객체

        Raises:
            FileNotFoundError: 파일이 존재하지 않는 경우
            ValueError: 파일을 읽을 수 없는 경우
        """
        return self.html_parser.load_and_clean(file_path)

    def parse_main_sections(self, parsed_html: Any) -> List[Dict[str, Any]]:
        """
        SECTION-1 기준 메인 섹션 파싱

        Args:
            parsed_html: BeautifulSoup 객체

        Returns:
            메인 섹션 정보가 담긴 딕셔너리 리스트
        """
        return self.section_parser.parse_main_sections(parsed_html)

    def parse_subsections(
        self, parent_section: Dict[str, Any], parsed_html: Any
    ) -> List[Dict[str, Any]]:
        """
        하위 섹션들 파싱

        Args:
            parent_section: 부모 섹션 정보
            parsed_html: BeautifulSoup 객체

        Returns:
            하위 섹션 정보가 담긴 딕셔너리 리스트
        """
        return self.section_parser.parse_subsections(parent_section, parsed_html)

    def normalize_text(self, text: str) -> str:
        """
        금융 텍스트 정규화 및 정제

        Args:
            text: 정규화할 텍스트

        Returns:
            정규화된 텍스트
        """
        return self.text_cleaner.normalize_text(text)

    def parse_report(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        전체 감사보고서 파싱 (메인 메서드) - Version 3.0

        Args:
            file_path: HTML 파일 경로

        Returns:
            파싱된 감사보고서 데이터
        """
        file_path = Path(file_path)

        # 1. HTML 파싱 및 정리
        soup = self.parse_html(file_path)

        # 2. SECTION-1 기준 메인 섹션 파싱
        main_sections = self.parse_main_sections(soup)

        # 3. 각 메인 섹션의 하위 섹션 파싱
        for section in main_sections:
            section["subsections"] = self.parse_subsections(section, soup)

        # 4. 제목 및 메타데이터 추출
        title = self.html_parser.extract_title(soup)
        report_year = self.html_parser.extract_year(file_path.name)
        all_text = self.html_parser.extract_all_text(soup)

        # 5. 결과 구성
        result = {
            "metadata": {
                "version": "3.0",
                "source_file": file_path.name,
                "source_path": str(file_path.absolute()),
                "report_year": report_year,
                "extraction_timestamp": pd.Timestamp.now().isoformat(),
                "parser_version": "3.0",
                "total_sections": len(main_sections),
                "file_size_bytes": file_path.stat().st_size,
                "total_elements_parsed": len(soup.find_all()),
                "total_content_length": len(all_text),
            },
            "sections": main_sections,
            "all_text": all_text,
        }

        # 6. 데이터 검증
        validation_result = self.data_validator.validate_parsed_data(result)
        result["validation"] = validation_result

        self.logger.info(f"감사보고서 파싱 완료: {file_path.name}")
        self.logger.info(
            f"총 {len(main_sections)}개 메인 섹션, {self._count_total_subsections(main_sections)}개 하위 섹션"
        )
        self.logger.info(
            f"품질 점수: {validation_result.get('overall_score', 0.0):.2f}"
        )

        return result

    def _count_total_subsections(self, main_sections: List[Dict[str, Any]]) -> int:
        """총 하위 섹션 수 계산"""
        total = 0
        for section in main_sections:
            total += len(section.get("subsections", []))
        return total

    def save_to_json(self, data: Dict[str, Any], output_path: Union[str, Path]) -> None:
        """
        파싱된 데이터를 JSON 파일로 저장

        Args:
            data: 저장할 데이터
            output_path: 출력 파일 경로
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # JSON 직렬화 가능하도록 데이터 정리
        cleaned_data = self._clean_for_json(data)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"JSON 파일 저장 완료: {output_path}")

    def _clean_for_json(self, obj: Any) -> Any:
        """JSON 직렬화를 위해 데이터 정리"""
        if isinstance(obj, dict):
            return {k: self._clean_for_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_for_json(item) for item in obj]
        elif hasattr(obj, "item"):  # numpy scalar
            return obj.item()
        elif hasattr(obj, "tolist"):  # numpy array
            return obj.tolist()
        else:
            return obj

    def validate_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        데이터 품질 검증

        Args:
            data: 검증할 데이터

        Returns:
            검증 결과
        """
        return self.data_validator.validate_parsed_data(data)

    def generate_validation_report(self, validation_result: Dict[str, Any]) -> str:
        """
        검증 결과 리포트 생성

        Args:
            validation_result: 검증 결과

        Returns:
            검증 리포트 문자열
        """
        return self.data_validator.generate_validation_report(validation_result)

def main():
    """메인 함수 - 2014년부터 2024년까지 모든 감사보고서 파싱"""
    # 파서 초기화
    parser = AuditReportParser(log_level="INFO")

    # 연도별 파싱 결과 저장
    all_results = {}
    total_quality_score = 0.0
    successful_parses = 0

    year_range = range(2014, 2025)
    print(f"=== {year_range[0]}년 ~ {year_range[-1]}년 감사보고서 파싱 시작 ===")

    for year in year_range:  # 2014년부터 2024년까지
        input_file = f"data/raw/감사보고서_{year}.htm"
        output_file = f"data/processed/감사보고서_{year}_parser_v3.json"

        print(f"\n--- {year}년 감사보고서 파싱 중... ---")

        try:
            # 파일 존재 확인
            if not os.path.exists(input_file):
                print(f"❌ 파일이 존재하지 않습니다: {input_file}")
                continue

            # 파싱 실행
            result = parser.parse_report(input_file)

            # JSON 파일로 저장
            parser.save_to_json(result, output_file)

            # 결과 저장
            all_results[year] = result
            quality_score = result["validation"]["overall_score"]
            total_quality_score += quality_score
            successful_parses += 1

            # 결과 출력
            print(f"✅ 파싱 완료: {result['metadata']['total_sections']}개 메인 섹션")
            print(f"   품질 점수: {quality_score:.2f}")

            # 각 메인 섹션의 정보 출력 (간략하게)
            for i, section in enumerate(result["sections"]):
                section_type = section.get("section_type", "UNKNOWN")
                title = section.get("title", "Unknown")
                tables = len(section.get("tables", []))
                subsections = section.get("subsections", [])

                print(f"   {section_type}-{i+1}: {title}")
                if subsections:
                    print(f"     - {len(subsections)}개 하위 섹션")
                if tables > 0:
                    print(f"     - {tables}개 테이블")

            print(f"   JSON 파일 저장 완료: {output_file}")

        except Exception as e:
            print(f"❌ {year}년 파싱 실패: {str(e)}")
            continue

    # 전체 결과 요약
    print(f"\n=== 전체 파싱 결과 요약 ===")
    print(f"성공적으로 파싱된 연도: {successful_parses}/11년")
    if successful_parses > 0:
        avg_quality_score = total_quality_score / successful_parses
        print(f"평균 품질 점수: {avg_quality_score:.2f}")

        # 연도별 품질 점수 출력
        print(f"\n연도별 품질 점수:")
        for year, result in all_results.items():
            quality_score = result["validation"]["overall_score"]
            print(f"  {year}년: {quality_score:.2f}")


if __name__ == "__main__":
    main()
