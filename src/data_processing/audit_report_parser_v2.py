"""
Samsung Electronics Audit Report Parser

이 모듈은 삼성전자 감사보고서 HTML 파일을 파싱하여 구조화된 데이터로 변환하는 클래스를 제공.
기존 html_to_json_hybrid.py의 기능을 클래스 기반으로 재구성.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from io import StringIO
import pandas as pd
from bs4 import BeautifulSoup


class AuditReportParser:
    """
    삼성전자 감사보고서 HTML 파일을 파싱하여 구조화된 데이터로 변환하는 클래스

    주요 기능:
    - HTML 파일 파싱 및 기본 전처리
    - 주요 섹션별 텍스트 추출
    - 재무제표 및 주요 표 데이터 추출
    - 금융 텍스트 정규화 및 정제
    """

    def __init__(self, log_level: str = "INFO"):
        """
        AuditReportParser 초기화

        Args:
            log_level: 로깅 레벨 (DEBUG, INFO, WARNING, ERROR)
        """
        self.logger = self._setup_logger(log_level)
        self.section_patterns = {
            "main_sections": r"SECTION-(\d+)",
            "subsections": r"^(\d+)\.\s*(.+?)(?:\s*:|$)",
            "tables": r"<table[^>]*>.*?</table>",
        }

    def _setup_logger(self, log_level: str) -> logging.Logger:
        """로거 설정"""
        logger = logging.getLogger(__name__)
        logger.setLevel(getattr(logging, log_level.upper()))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def parse_html(self, file_path: Union[str, Path]) -> BeautifulSoup:
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
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

        try:
            # 다양한 인코딩으로 시도하여 HTML 파일 읽기
            encodings = ["euc-kr", "cp949", "utf-8", "latin-1"]
            html_content = None

            for encoding in encodings:
                try:
                    with open(file_path, "r", encoding=encoding) as f:
                        html_content = f.read()
                    self.logger.debug(
                        f"성공적으로 파일을 읽었습니다 (인코딩: {encoding})"
                    )
                    break
                except UnicodeDecodeError:
                    continue

            if html_content is None:
                raise ValueError("지원되는 인코딩으로 파일을 읽을 수 없습니다")

            # HTML 구조 문제 수정
            html_content = self._fix_html_structure(html_content)

            # BeautifulSoup으로 파싱
            soup = BeautifulSoup(html_content, "html.parser")

            # 스크립트와 스타일 태그 제거
            for script in soup(["script", "style"]):
                script.decompose()

            self.logger.info(f"HTML 파일 파싱 완료: {file_path.name}")
            return soup

        except Exception as e:
            self.logger.error(f"HTML 파일 파싱 실패: {e}")
            raise ValueError(f"파일을 읽을 수 없습니다: {e}")

    def _fix_html_structure(self, html_content: str) -> str:
        """HTML 구조 문제 수정"""
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

        self.logger.debug("HTML 구조 수정 완료")
        return html_content

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
        text = re.sub(r"[₩]", "원", text)  # 원화 기호 통일
        text = re.sub(r"[%]", "%", text)  # 퍼센트 기호 정규화

        # 숫자와 단위 사이 공백 정리
        text = re.sub(r"(\d+)\s*([백만억조]원)", r"\1\2", text)

        # 괄호 정리
        text = re.sub(r"\(\s+", "(", text)
        text = re.sub(r"\s+\)", ")", text)

        # 연속된 구두점 정리
        text = re.sub(r"\.{2,}", "...", text)
        text = re.sub(r",{2,}", ",", text)

        return text

    def _extract_section_content(self, section_tag, soup: BeautifulSoup) -> str:
        """섹션 내용 추출"""
        content_parts = []

        # H3 태그인 경우 H3 태그 다음부터 내용 추출
        if section_tag.name == "h3":
            # H3 태그의 잘못된 구조 처리 (P 태그가 H3 안에 있음)
            current = section_tag.next_sibling
            # H3 태그 내부의 P 태그도 확인
            if section_tag.find("p"):
                p_text = section_tag.find("p").get_text(strip=True)
                if p_text:
                    content_parts.append(p_text)
        else:
            current = section_tag.next_sibling

        while current:
            if hasattr(current, "name"):
                if current.name == "p" and current.get("class"):
                    class_name = " ".join(current.get("class", []))
                    if "SECTION" in class_name:
                        break
                elif current.name in ["table", "div"]:
                    # 테이블이나 div는 별도 처리
                    pass
                elif current.name == "p":
                    # 일반 P 태그의 내용 추출
                    text = current.get_text(strip=True)
                    if text:
                        content_parts.append(text)
                else:
                    text = current.get_text(strip=True)
                    if text:
                        content_parts.append(text)
            else:
                text = str(current).strip()
                if text and not text.startswith("<"):
                    content_parts.append(text)

            current = current.next_sibling

        # 디버깅을 위한 로그 추가
        if section_tag.get_text(strip=True) == "주석":
            self.logger.debug(f"주석 섹션 내용 추출: {len(content_parts)}개 부분")
            for i, part in enumerate(content_parts[:3]):  # 처음 3개만 로그
                self.logger.debug(f"  부분 {i+1}: {part[:100]}...")

        return "\n".join(content_parts)

    def _extract_notes_section_content(self, section_tag, soup: BeautifulSoup) -> str:
        """주석 섹션의 내용을 직접 추출"""
        content_parts = []

        # H3 태그인 경우 H3 태그 다음부터 내용 추출
        if section_tag.name == "h3":
            current = section_tag.next_sibling
        else:
            current = section_tag.next_sibling

        while current:
            if hasattr(current, "name"):
                if current.name == "p" and current.get("class"):
                    class_name = " ".join(current.get("class", []))
                    if "SECTION" in class_name:
                        break
                elif current.name in ["table", "div"]:
                    # 테이블이나 div는 별도 처리
                    pass
                elif current.name == "p":
                    # 일반 P 태그의 내용 추출
                    text = current.get_text(strip=True)
                    if text:
                        content_parts.append(text)
                else:
                    text = current.get_text(strip=True)
                    if text:
                        content_parts.append(text)
            else:
                text = str(current).strip()
                if text and not text.startswith("<"):
                    content_parts.append(text)

            current = current.next_sibling

        # 디버깅을 위한 로그 추가
        self.logger.debug(f"주석 섹션 내용 추출: {len(content_parts)}개 부분")
        for i, part in enumerate(content_parts[:3]):  # 처음 3개만 로그
            self.logger.debug(f"  부분 {i+1}: {part[:100]}...")

        # 주석 섹션의 내용이 비어있는 경우 다른 방법으로 시도
        if not content_parts and section_tag.name == "h3":
            # H3 태그의 부모를 찾아서 그 다음부터 내용 추출
            parent = section_tag.parent
            if parent:
                current = parent.next_sibling
                while current:
                    if hasattr(current, "name"):
                        if current.name == "p" and current.get("class"):
                            class_name = " ".join(current.get("class", []))
                            if "SECTION" in class_name:
                                break
                        elif current.name == "p":
                            text = current.get_text(strip=True)
                            if text:
                                content_parts.append(text)
                    current = current.next_sibling

        return "\n".join(content_parts)

    def _clean_nan_values(self, obj):
        """중첩된 데이터 구조에서 NaN 값 정리"""
        if isinstance(obj, dict):
            return {k: self._clean_nan_values(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._clean_nan_values(item) for item in obj]
        elif pd.isna(obj) or (isinstance(obj, float) and str(obj).lower() == "nan"):
            return None
        else:
            return obj

    def parse_report(self, file_path: Union[str, Path]) -> Dict[str, Any]:
        """
        전체 감사보고서 파싱 (메인 메서드)
        SECTION-1 단위로 파싱하여 계층적 구조 유지

        Args:
            file_path: HTML 파일 경로

        Returns:
            파싱된 감사보고서 데이터
        """
        file_path = Path(file_path)

        # HTML 파싱
        soup = self.parse_html(file_path)

        # SECTION-1 단위로 파싱
        main_sections = self._extract_main_sections(soup)

        # 제목 추출
        title = self._extract_title(soup)

        # 연도 추출
        report_year = self._extract_year(file_path.name)

        # 전체 텍스트 추출
        all_text = self._extract_all_text(soup)

        # 결과 구성
        result = {
            "version": "2.0",
            "source_path": str(file_path.absolute()),
            "source_filename": file_path.name,
            "report_year": report_year,
            "title": title,
            "main_sections": main_sections,
            "total_main_sections": len(main_sections),
            "all_text": all_text,
            "extraction_metadata": {
                "extraction_timestamp": pd.Timestamp.now().isoformat(),
                "parser_version": "2.0",
                "file_size_bytes": file_path.stat().st_size,
                "total_elements_parsed": len(soup.find_all()),
                "total_content_length": len(all_text),
                "parsing_method": "hierarchical_section_based",
            },
        }

        self.logger.info(f"감사보고서 파싱 완료: {file_path.name}")
        return result

    def _extract_main_sections(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        모든 SECTION들을 추출하고 계층적 구조로 파싱

        Args:
            soup: BeautifulSoup 객체

        Returns:
            메인 섹션들의 리스트
        """
        main_sections = []

        # 모든 SECTION 클래스를 가진 태그들 찾기 (SECTION-1, SECTION-2 등)
        # P 태그와 H3 태그 모두 확인
        section_tags = []
        section_tags.extend(
            soup.find_all(
                "p",
                class_=lambda x: x and any(f"SECTION-{i}" in x for i in range(1, 7)),
            )
        )
        section_tags.extend(
            soup.find_all(
                "h3",
                class_=lambda x: x and any(f"SECTION-{i}" in x for i in range(1, 7)),
            )
        )

        for section_tag in section_tags:
            class_name = " ".join(section_tag.get("class", []))

            # H3 태그인 경우 내부 P 태그를 찾아서 처리
            if section_tag.name == "h3":
                p_tag = section_tag.find(
                    "p",
                    class_=lambda x: x
                    and any(f"SECTION-{i}" in x for i in range(1, 7)),
                )
                if p_tag:
                    section_tag = p_tag
                    class_name = " ".join(section_tag.get("class", []))

            # SECTION-1인 경우
            if "SECTION-1" in class_name:
                section_data = self._parse_section1(section_tag, soup)
                if section_data:
                    main_sections.append(section_data)
            # SECTION-2인 경우 (주석 섹션)
            elif "SECTION-2" in class_name:
                section_data = self._parse_section2(section_tag, soup)
                if section_data:
                    main_sections.append(section_data)

        self.logger.info(f"총 {len(main_sections)}개 메인 섹션 추출 완료")
        return main_sections

    def _parse_section1(
        self, section1_tag, soup: BeautifulSoup
    ) -> Optional[Dict[str, Any]]:
        """
        개별 SECTION-1을 파싱

        Args:
            section1_tag: SECTION-1 태그
            soup: BeautifulSoup 객체

        Returns:
            SECTION-1 데이터
        """
        try:
            # SECTION-1 제목 추출
            section1_title = section1_tag.get_text(strip=True)

            # SECTION-1 내용 추출
            section1_content = self._extract_section_content(section1_tag, soup)

            # SECTION-1 내의 테이블들 추출
            tables = self._extract_tables_for_section(section1_tag, soup)

            return {
                "section_type": "SECTION-1",
                "title": section1_title,
                "content": section1_content,
                "tables": tables,
                "total_tables": len(tables),
            }

        except Exception as e:
            self.logger.warning(f"SECTION-1 파싱 실패: {e}")
            return None

    def _parse_section2(
        self, section2_tag, soup: BeautifulSoup
    ) -> Optional[Dict[str, Any]]:
        """
        개별 SECTION-2 (주석 섹션)을 파싱하고 세부 주석들을 처리

        Args:
            section2_tag: SECTION-2 태그
            soup: BeautifulSoup 객체

        Returns:
            SECTION-2 데이터
        """
        try:
            # SECTION-2 제목 추출
            section2_title = section2_tag.get_text(strip=True)

            # SECTION-2 내용 추출
            section2_content = self._extract_section_content(section2_tag, soup)

            # 주석 섹션인 경우 특별 처리
            if "주석" in section2_title:
                # 주석 섹션의 내용을 직접 찾아서 추출
                section2_content = self._extract_notes_section_content(
                    section2_tag, soup
                )

            # 주석 세부 섹션들 파싱 (1. xxx, 2. xxx 형태)
            detailed_subsections = []
            if "주석" in section2_title:
                detailed_subsections = self._parse_notes_detailed_subsections(
                    section2_content
                )

            # SECTION-2 내의 테이블들 추출
            tables = self._extract_tables_for_section(section2_tag, soup)

            return {
                "section_type": "SECTION-2",
                "title": section2_title,
                "content": section2_content,
                "detailed_subsections": detailed_subsections,
                "tables": tables,
                "total_detailed_subsections": len(detailed_subsections),
                "total_tables": len(tables),
            }

        except Exception as e:
            self.logger.warning(f"SECTION-2 파싱 실패: {e}")
            return None

    def _parse_notes_detailed_subsections(self, content: str) -> List[Dict[str, Any]]:
        """
        SECTION-2 주석 섹션의 세부 섹션들 파싱 (1. xxx, 2. xxx 형태)

        Args:
            content: 주석 섹션 내용

        Returns:
            세부 섹션들의 리스트
        """
        detailed_subsections = []
        lines = content.split("\n")
        current_subsection = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 숫자로 시작하는 세부 섹션 패턴 확인 (1. xxx, 2. xxx 등)
            # HTML 태그를 제거한 후 패턴 매칭
            clean_line = re.sub(r"<[^>]+>", "", line)
            match = re.match(r"^(\d+)\.\s*(.+?)(?:\s*:|$)", clean_line)
            if match:
                # 이전 섹션 저장
                if current_subsection:
                    detailed_subsections.append(current_subsection)

                # 새 섹션 시작
                number = int(match.group(1))
                title = match.group(2).strip()
                current_subsection = {
                    "note_number": number,
                    "title": title,
                    "content": "",
                }
            else:
                # 현재 섹션에 내용 추가
                if current_subsection:
                    if current_subsection["content"]:
                        current_subsection["content"] += "\n" + line
                    else:
                        current_subsection["content"] = line

        # 마지막 섹션 저장
        if current_subsection:
            detailed_subsections.append(current_subsection)

        return detailed_subsections

    def _extract_tables_for_section(
        self, section_tag, soup: BeautifulSoup
    ) -> List[Dict[str, Any]]:
        """
        특정 섹션 내의 테이블들 추출

        Args:
            section_tag: 섹션 태그
            soup: BeautifulSoup 객체

        Returns:
            테이블들의 리스트
        """
        tables = []
        current = section_tag.next_sibling
        table_index = 0

        while current:
            if hasattr(current, "name"):
                if current.name == "table":
                    table_data = self._parse_table_with_notes_reference(
                        current, table_index
                    )
                    if table_data:
                        tables.append(table_data)
                        table_index += 1
                elif current.name == "p" and current.get("class"):
                    # 다음 섹션 시작 시 중단
                    class_name = " ".join(current.get("class", []))
                    if "SECTION" in class_name:
                        break

            current = current.next_sibling

        return tables

    def _parse_table_with_notes_reference(
        self, table, index: int
    ) -> Optional[Dict[str, Any]]:
        """
        테이블 파싱 시 주석 참조 처리

        Args:
            table: 테이블 태그
            index: 테이블 인덱스

        Returns:
            파싱된 테이블 데이터
        """
        try:
            table_html = str(table)

            # pandas로 테이블 파싱
            df = pd.read_html(StringIO(table_html), flavor="html5lib")[0]

            # NaN 값 처리
            df = df.where(pd.notnull(df), None)
            df = df.map(lambda x: None if pd.isna(x) else x)

            # 컬럼명 정리 (MultiIndex 처리)
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [
                    str(col) if isinstance(col, tuple) else col for col in df.columns
                ]

            # 주석 컬럼 처리
            processed_data = self._process_notes_columns(df)

            # 테이블 데이터 정리
            table_records = processed_data.to_dict("records")
            table_records = self._clean_nan_values(table_records)

            return {
                "index": index,
                "table_html": table_html,
                "data": table_records,
                "columns": [str(col) for col in processed_data.columns.tolist()],
                "shape": processed_data.shape,
                "row_count": processed_data.shape[0],
                "column_count": processed_data.shape[1],
                "has_notes_references": self._has_notes_references(processed_data),
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

    def _extract_title(self, soup: BeautifulSoup) -> str:
        """제목 추출"""
        title_tag = soup.find("title")
        if title_tag:
            return title_tag.get_text(strip=True)
        return "감사보고서"

    def _extract_year(self, filename: str) -> Optional[int]:
        """파일명에서 연도 추출"""
        match = re.search(r"(\d{4})", filename)
        return int(match.group(1)) if match else None

    def _extract_all_text(self, soup: BeautifulSoup) -> str:
        """전체 텍스트 추출"""
        all_text = soup.get_text(separator="\n", strip=True)
        # 공백 정리하되 줄바꿈은 보존
        all_text = re.sub(r"[ \t]+", " ", all_text)
        all_text = re.sub(r"\n\s*\n", "\n\n", all_text)
        return all_text

    def save_to_json(self, data: Dict[str, Any], output_path: Union[str, Path]) -> None:
        """
        파싱된 데이터를 JSON 파일로 저장

        Args:
            data: 저장할 데이터
            output_path: 출력 파일 경로
        """
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        self.logger.info(f"JSON 파일 저장 완료: {output_path}")


def main():
    """메인 함수 - 사용 예시"""
    parser = AuditReportParser(log_level="DEBUG")

    # HTML 파일 파싱
    input_file = "data/raw/감사보고서_2014.htm"
    output_file = "data/processed/감사보고서_2014_parser_v2.json"

    try:
        # 감사보고서 파싱
        result = parser.parse_report(input_file)

        # JSON 파일로 저장
        parser.save_to_json(result, output_file)

        print(f"파싱 완료: {result['total_main_sections']}개 메인 섹션")

        # 각 메인 섹션의 정보 출력
        for i, section in enumerate(result["main_sections"]):
            section_type = section.get("section_type", "UNKNOWN")
            title = section.get("title", "Unknown")
            tables = section.get("total_tables", 0)
            detailed_subsections = section.get("total_detailed_subsections", 0)

            print(f"  {section_type}-{i+1}: {title}")
            if detailed_subsections > 0:
                print(f"    - {detailed_subsections}개 세부 주석")
            if tables > 0:
                print(f"    - {tables}개 테이블")

    except Exception as e:
        print(f"파싱 실패: {e}")


if __name__ == "__main__":
    main()
