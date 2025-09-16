"""
Data Processing Package V3.0

이 패키지는 삼성전자 감사보고서 HTML 파일의 파싱 및 데이터 처리를 담당합니다.
Version 3.0에서는 텍스트 기반 섹션 분류와 계층적 파싱을 지원합니다.

모듈 구성:
- html_parser_v3: HTML 파싱 및 기본 전처리 (Version 3.0)
- section_parser: 계층적 섹션 파싱 및 텍스트 기반 분류
- table_extractor: 테이블 데이터 추출 및 주석 참조 처리
- text_cleaner: 텍스트 정규화 및 정제
- data_validator: 데이터 품질 검증 및 무결성 확인

주요 개선사항:
- 텍스트 기반 섹션 분류 (태그 기반이 아님)
- 계층적 섹션 파싱 (SECTION-1 → SECTION-2 → SECTION-3...)
- 주석 섹션 특별 처리 ("주석" 텍스트 기반 감지)
- 부모-자식 관계 추적
- 중복 방지 및 견고한 에러 처리
"""

import sys
from pathlib import Path

# 현재 디렉토리를 Python 경로에 추가
sys.path.append(str(Path(__file__).parent))

from html_parser_v3 import HTMLParserV3
from section_parser import SectionParser
from table_extractor import TableExtractor
from text_cleaner import TextCleaner
from data_validator import DataValidator

__all__ = [
    "HTMLParserV3",
    "SectionParser",
    "TableExtractor",
    "TextCleaner",
    "DataValidator",
    # 호환성을 위한 기존 클래스
    "HTMLParser",
]

__version__ = "3.0.0"
