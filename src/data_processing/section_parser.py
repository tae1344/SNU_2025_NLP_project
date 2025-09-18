"""
Section Parsing Module

이 모듈은 감사보고서의 계층적 섹션 파싱을 담당합니다.
텍스트 기반 섹션 분류와 부모-자식 관계 추적을 지원합니다.
"""

import logging
import re
from typing import Any, Dict, List, Optional, Union
from bs4 import BeautifulSoup
from io import StringIO
import pandas as pd
from data_processing.text_cleaner import TextCleaner
from data_processing.table_extractor import TableExtractor


class SectionParser:
    """
    계층적 섹션 파싱을 담당하는 클래스

    주요 기능:
    - SECTION-1 기준 메인 섹션 파싱
    - 텍스트 기반 섹션 분류
    - 하위 섹션 파싱 및 부모-자식 관계 추적
    - 주석 섹션 특별 처리
    """

    def __init__(self, log_level: str = "INFO"):
        """
        SectionParser 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)
        self.text_cleaner = TextCleaner(log_level)
        self.table_extractor = TableExtractor(log_level)

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(f"{__name__}.SectionParser")
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def parse_main_sections(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """SECTION-1 기준 메인 섹션 파싱"""
        main_sections = []

        # SECTION-1 태그들 찾기
        section1_tags = soup.find_all("h2", class_=lambda x: x and "SECTION-1" in x)

        for i, section1_tag in enumerate(section1_tags):
            section_data = self._parse_section1(section1_tag, soup, i)
            if section_data:
                main_sections.append(section_data)

        # 독립적인 SECTION-2 (주석) 섹션 찾기
        notes_section = self._find_notes_section(soup)
        if notes_section:
            main_sections.append(notes_section)

        self.logger.info(f"총 {len(main_sections)}개의 메인 섹션 파싱 완료")
        return main_sections

    def _find_notes_section(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """독립적인 주석 섹션 찾기"""
        # H3 태그의 SECTION-2 중에서 "주석"인 것 찾기
        notes_tags = soup.find_all("h3", class_=lambda x: x and "SECTION-2" in x)

        for tag in notes_tags:
            text = self._extract_clean_text(tag)
            if "주석" in text.lower():
                return self._parse_notes_section(tag, soup, None, 0)

        return None

    def _parse_section1(
        self, section1_tag, soup: BeautifulSoup, index: int
    ) -> Optional[Dict[str, Any]]:
        """SECTION-1 파싱"""
        try:
            title = self._extract_clean_text(section1_tag)
            section_id = f"SECTION-1-{index + 1}"

            # 섹션 내용 추출
            content = self._extract_section_content(section1_tag, soup)

            # 테이블 추출
            tables = self._extract_tables_in_section(section1_tag, soup)

            return {
                "section_id": section_id,
                "section_type": "SECTION-1",
                "title": title,
                "hierarchy_level": 1,
                "parent_section": None,
                "content": content,
                "tables": tables,
                "subsections": [],  # 하위 섹션은 별도 처리
            }
        except Exception as e:
            self.logger.warning(f"SECTION-1 파싱 실패: {e}")
            return None

    def parse_subsections(
        self, parent_section: Dict[str, Any], soup: BeautifulSoup
    ) -> List[Dict[str, Any]]:
        """하위 섹션들 파싱"""
        subsections = []
        parent_tag = self._find_section_tag_by_id(parent_section["section_id"], soup)

        if not parent_tag:
            return subsections

        # "외부감사 실시내용" 섹션의 경우에만 하위 섹션 파싱
        if "외부감사 실시내용" in parent_section.get("title", ""):
            subsections = self._parse_external_audit_subsections(
                parent_tag, soup, parent_section
            )
        else:
            # 다른 섹션들은 다음 SECTION-1까지의 범위에서 하위 섹션 찾기
            next_section1 = self._find_next_section1_tag(parent_tag, soup)

            current = parent_tag.next_sibling
            subsection_index = 0

            while current and current != next_section1:
                if self._is_section_tag(current):
                    section_data = self._parse_section_by_text_content(
                        current, soup, parent_section, subsection_index
                    )
                    if section_data:
                        subsections.append(section_data)
                        subsection_index += 1
                elif self._is_section1_tag(current):
                    # 다음 SECTION-1을 만나면 중단
                    break

                current = current.next_sibling

        self.logger.info(
            f"섹션 '{parent_section['title']}'에서 {len(subsections)}개의 하위 섹션 파싱"
        )
        return subsections

    def _parse_external_audit_subsections(
        self, parent_tag, soup: BeautifulSoup, parent_section: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """외부감사 실시내용 섹션의 하위 섹션들 파싱"""
        subsections = []

        # P 태그의 SECTION-2들 찾기 (1. 감사대상업무, 2. 감사참여자 구분별 인원수 및 감사시간, 3. 주요 감사실시내용)
        section2_p_tags = soup.find_all("p", class_=lambda x: x and "SECTION-2" in x)

        for i, tag in enumerate(section2_p_tags):
            text = self._extract_clean_text(tag)
            if re.match(r"^\d+\.\s*", text):  # 번호로 시작하는 하위 섹션
                section_data = self._parse_regular_subsection(
                    tag, soup, parent_section, i
                )
                if section_data:
                    subsections.append(section_data)

        return subsections

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

    def _parse_section_by_text_content(
        self,
        section_tag,
        soup: BeautifulSoup,
        parent_section: Dict[str, Any],
        index: int,
    ) -> Optional[Dict[str, Any]]:
        """텍스트 내용을 기준으로 섹션 분류 및 파싱"""
        section_text = self._extract_clean_text(section_tag)

        if self.is_notes_section(section_text):
            return self._parse_notes_section(section_tag, soup, parent_section, index)
        elif self.is_regular_subsection(section_text):
            return self._parse_regular_subsection(
                section_tag, soup, parent_section, index
            )
        else:
            return None

    def is_notes_section(self, text: str) -> bool:
        """주석 섹션 판별"""
        cleaned_text = text.strip().lower()
        return "주석" in cleaned_text and not re.match(r"^\d+\.", cleaned_text)

    def is_regular_subsection(self, text: str) -> bool:
        """일반 하위 섹션 판별"""
        cleaned_text = text.strip()
        return re.match(r"^\d+\.\s*", cleaned_text)

    def _parse_notes_section(
        self, notes_tag, soup: BeautifulSoup, parent_section: Dict[str, Any], index: int
    ) -> Dict[str, Any]:
        """주석 섹션 특별 처리"""
        title = self._extract_clean_text(notes_tag)
        content = self._extract_section_content(notes_tag, soup)
        tables = self._extract_tables_in_section(notes_tag, soup)
        detailed_notes = self._parse_detailed_notes(content)

        return {
            "section_id": f"SECTION-2-INDEPENDENT",
            "section_type": "SECTION-2",
            "title": title,
            "hierarchy_level": 1,  # 독립 섹션
            "parent_section": None,
            "content": content,
            "tables": tables,
            "detailed_notes": detailed_notes,
        }

    def _parse_regular_subsection(
        self,
        subsection_tag,
        soup: BeautifulSoup,
        parent_section: Dict[str, Any],
        index: int,
    ) -> Dict[str, Any]:
        """일반 하위 섹션 처리"""
        section_text = self._extract_clean_text(subsection_tag)
        section_number = self._extract_section_number(section_text)

        content = self._extract_section_content(subsection_tag, soup)
        tables = self._extract_tables_in_section(subsection_tag, soup)

        return {
            "section_id": f"{parent_section["section_id"]}-{index + 1}",
            "section_type": "SECTION-2",  # 하위 섹션은 항상 SECTION-2
            "title": section_text,
            "hierarchy_level": 2,
            "parent_section": {
                "id": parent_section["section_id"],
                "title": parent_section["title"],
            },
            "content": content,
            "tables": tables,
        }

    def _parse_detailed_notes(self, content: str) -> List[Dict[str, Any]]:
        """세부 주석들 파싱 (1. xxx, 2. xxx 형태)"""
        detailed_notes = []

        # 정규식으로 세부 주석 파싱
        pattern = r"^(\d+)\.\s*(.+?)(?=\n\d+\.|\Z)"
        matches = re.finditer(pattern, content, re.MULTILINE | re.DOTALL)

        for match in matches:
            body = match.group(2).strip()

            # 제목 후보: 본문 첫 줄만 사용하고, 번호/콜론 제거
            first_line = body.split("\n", 1)[0].strip()
            # 앞쪽에 붙은 번호 패턴 제거 (예: "2.1", "1")
            first_line = re.sub(r"^\d+(?:\.\d+)*\s*", "", first_line)
            # 제목 끝의 콜론/전각콜론 제거
            first_line = re.sub(r"[:：]\s*$", "", first_line)

            detailed_notes.append(
                {
                    "note_number": int(match.group(1)),
                    "title": first_line,
                    "content": match.group(0).strip(),
                }
            )

        return detailed_notes

    def _extract_section_number(self, text: str) -> int:
        """섹션 번호 추출"""
        match = re.match(r"^(\d+)\.", text.strip())
        return int(match.group(1)) if match else 2

    def _extract_section_content(self, section_tag, soup: BeautifulSoup) -> str:
        """섹션의 텍스트 콘텐츠 추출"""
        content_parts = []
        current = section_tag.next_sibling

        while current:
            if self._is_section_tag(current):
                break
            elif current.name == "table":
                # 테이블은 별도 처리
                pass
            else:
                text = self._extract_clean_text(current)
                if text:
                    content_parts.append(text)

            current = current.next_sibling

        return "\n".join(content_parts)

    def _extract_tables_in_section(
        self, section_tag, soup: BeautifulSoup
    ) -> List[Dict[str, Any]]:
        """섹션 내의 테이블들 추출"""
        parts = []
        current = section_tag.next_sibling
        while current:
            if self._is_section_tag(current):  # 다음 섹션 시작이면 종료
                break
            parts.append(str(current))  # fragment 누적
            current = current.next_sibling
        html_fragment = "".join(parts)
        return self.table_extractor.extract_tables_from_section(html_fragment)

    def _extract_clean_text(self, element) -> str:
        """요소에서 깨끗한 텍스트 추출"""
        if not element:
            return ""

        text = element.get_text(strip=True)
        # HTML 태그 제거
        text = re.sub(r"<[^>]+>", "", text)
        # 공백 정리
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _is_section_tag(self, element) -> bool:
        """섹션 태그인지 확인"""
        if not hasattr(element, "get"):
            return False

        class_name = element.get("class", [])
        if isinstance(class_name, list):
            class_name = " ".join(class_name)

        return "SECTION" in str(class_name)

    def _is_section1_tag(self, element) -> bool:
        """SECTION-1 태그인지 확인"""
        if not hasattr(element, "get"):
            return False

        class_name = element.get("class", [])
        if isinstance(class_name, list):
            class_name = " ".join(class_name)

        return "SECTION-1" in str(class_name)

    def _find_section_tag_by_id(
        self, section_id: str, soup: BeautifulSoup
    ) -> Optional[Any]:
        """섹션 ID로 태그 찾기"""
        # SECTION-1-1 -> SECTION-1
        section_type = section_id.split("-")[0] + "-" + section_id.split("-")[1]

        tags = soup.find_all("h2", class_=lambda x: x and section_type in x)
        if tags:
            return tags[0]

        return None
