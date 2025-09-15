"""
HTML Parsing Module V3

이 모듈은 삼성전자 감사보고서 HTML 파일의 파싱 및 기본 전처리를 담당합니다.
Version 3.0에서는 텍스트 기반 섹션 분류와 계층적 파싱을 지원합니다.
"""

import logging
import re
from pathlib import Path
from typing import Optional, Union, List, Dict, Any
from io import StringIO
import pandas as pd
from bs4 import BeautifulSoup


class HTMLParserV3:
    """
    HTML 파일 파싱 및 기본 전처리를 담당하는 클래스 (Version 3.0)

    주요 기능:
    - 다양한 인코딩 자동 감지 및 처리
    - HTML 구조 오류 수정
    - 텍스트 기반 섹션 분류
    - 계층적 섹션 파싱
    """

    def __init__(self, log_level: str = "INFO"):
        """
        HTMLParserV3 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)
        self.encoding_priority = ["euc-kr", "utf-8", "cp949"]

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"{__name__}.HTMLParserV3")
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def load_and_clean(self, file_path: Union[str, Path]) -> BeautifulSoup:
        """
        HTML 파일 로딩 및 구조 정리

        Args:
            file_path: HTML 파일 경로

        Returns:
            BeautifulSoup 객체

        Raises:
            FileNotFoundError: 파일이 존재하지 않는 경우
            ValueError: 파일을 읽을 수 없는 경우
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        # HTML 파일 로딩
        html_content = self._load_html_with_encoding(file_path)

        # HTML 구조 정리
        html_content = self._clean_html_structure(html_content)

        # BeautifulSoup으로 파싱
        soup = BeautifulSoup(html_content, "html.parser")

        # 스크립트/스타일 태그 제거
        self._remove_unnecessary_tags(soup)

        self.logger.info(f"HTML 파일 로딩 및 정리 완료: {file_path.name}")
        return soup

    def _load_html_with_encoding(self, file_path: Path) -> str:
        """다양한 인코딩으로 HTML 파일 로딩"""
        for encoding in self.encoding_priority:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                self.logger.debug(f"성공적으로 파일을 읽었습니다 (인코딩: {encoding})")
                return content
            except UnicodeDecodeError:
                continue

        raise ValueError("지원되는 인코딩으로 파일을 읽을 수 없습니다")

    def _clean_html_structure(self, html_content: str) -> str:
        """HTML 구조 오류 수정"""
        # 잘못된 H3 태그 구조 수정
        # <h3 class="SECTION-2" id="toc_4">
        #     <P class='SECTION-2'>주석
        #   </h3>
        #   </P>
        # 를 다음과 같이 수정:
        # <h3 class="SECTION-2" id="toc_4">주석</h3>

        # 패턴 1: <P class='SECTION-2'>주석</h3></P> 형태 수정
        pattern1 = (
            r'<h3 class="SECTION-2"[^>]*>\s*<P class=\'SECTION-2\'>([^<]+)</h3>\s*</P>'
        )
        replacement1 = r'<h3 class="SECTION-2" id="toc_4">\1</h3>'
        html_content = re.sub(pattern1, replacement1, html_content, flags=re.DOTALL)

        # 패턴 2: 다른 잘못된 H3 구조들도 수정
        pattern2 = r"<h3[^>]*>\s*<P[^>]*>([^<]+)</h3>\s*</P>"
        replacement2 = r"<h3>\1</h3>"
        html_content = re.sub(pattern2, replacement2, html_content, flags=re.DOTALL)

        return html_content

    def _remove_unnecessary_tags(self, soup: BeautifulSoup) -> None:
        """불필요한 태그 제거"""
        for tag in soup(["script", "style", "meta", "link"]):
            tag.decompose()

    def find_section1_tags(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """모든 SECTION-1 태그 찾기"""
        section1_tags = []

        # H2 태그의 SECTION-1 클래스 찾기
        h2_sections = soup.find_all("h2", class_=lambda x: x and "SECTION-1" in x)

        for i, tag in enumerate(h2_sections):
            section1_tags.append(
                {
                    "tag": tag,
                    "title": self._extract_clean_text(tag),
                    "section_id": f"SECTION-1-{i + 1}",
                    "index": i,
                }
            )

        self.logger.info(f"총 {len(section1_tags)}개의 SECTION-1 태그 발견")
        return section1_tags

    def find_section_boundaries(
        self, section1_tag, soup: BeautifulSoup
    ) -> Dict[str, Any]:
        """SECTION-1의 시작과 끝 경계 정의"""
        start_tag = section1_tag
        end_tag = self._find_next_section1_tag(section1_tag, soup)

        return {
            "start": start_tag,
            "end": end_tag,
            "content_range": self._get_content_between_tags(start_tag, end_tag),
        }

    def _find_next_section1_tag(
        self, current_tag, soup: BeautifulSoup
    ) -> Optional[Any]:
        """다음 SECTION-1 태그 찾기"""
        current = current_tag.next_sibling

        while current:
            if hasattr(current, "name") and current.name == "h2":
                if current.get("class") and "SECTION-1" in " ".join(
                    current.get("class", [])
                ):
                    return current
            current = current.next_sibling

        return None

    def _get_content_between_tags(self, start_tag, end_tag) -> List[Any]:
        """두 태그 사이의 콘텐츠 가져오기"""
        content = []
        current = start_tag.next_sibling

        while current and current != end_tag:
            content.append(current)
            current = current.next_sibling

        return content

    def extract_clean_text(self, element) -> str:
        """요소에서 깨끗한 텍스트 추출"""
        if not element:
            return ""

        text = element.get_text(strip=True)
        # HTML 태그 제거
        text = re.sub(r"<[^>]+>", "", text)
        # 공백 정리
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _extract_clean_text(self, element) -> str:
        """내부용 텍스트 추출 메서드"""
        return self.extract_clean_text(element)

    def extract_title(self, soup: BeautifulSoup) -> str:
        """HTML에서 제목 추출"""
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        return "감사보고서"

    def extract_year(self, filename: str) -> Optional[int]:
        """파일명에서 연도 추출"""
        match = re.search(r"(\d{4})", filename)
        return int(match.group(1)) if match else None

    def extract_all_text(self, soup: BeautifulSoup) -> str:
        """HTML에서 전체 텍스트 추출"""
        all_text = soup.get_text(separator="\n", strip=True)
        # 공백 정리하되 줄바꿈은 보존
        all_text = re.sub(r"[ \t]+", " ", all_text)
        all_text = re.sub(r"\n\s*\n", "\n\n", all_text)
        return all_text
