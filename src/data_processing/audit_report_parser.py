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

    def extract_sections(self, parsed_html: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        주요 섹션별 텍스트 추출

        Args:
            parsed_html: BeautifulSoup 객체

        Returns:
            섹션 정보가 담긴 딕셔너리 리스트
        """
        sections = []

        # SECTION 클래스를 가진 태그 찾기
        section_tags = parsed_html.find_all("p", class_=lambda x: x and "SECTION" in x)

        for tag in section_tags:
            class_name = " ".join(tag.get("class", []))
            section_match = re.search(
                self.section_patterns["main_sections"], class_name
            )

            if section_match:
                section_number = int(section_match.group(1))
                title = tag.get_text(strip=True)

                # 섹션 내용 추출
                content = self._extract_section_content(tag, parsed_html)

                # 주석 섹션인 경우 세부 섹션 파싱
                subsections = []
                if section_number == 2 and "주석" in title:
                    subsections = self._parse_notes_subsections(content)

                section_data = {
                    "title": title,
                    "level": f"SECTION-{section_number}",
                    "section_number": section_number,
                    "type": "main_section",
                    "content": content,
                    "subsections": subsections,
                    "tables": [],
                }

                sections.append(section_data)
                self.logger.debug(f"섹션 추출 완료: {title}")

        # 섹션 번호로 정렬
        sections.sort(key=lambda x: x["section_number"])

        self.logger.info(f"총 {len(sections)}개 섹션 추출 완료")
        return sections

    def extract_tables(self, parsed_html: BeautifulSoup) -> List[Dict[str, Any]]:
        """
        재무제표 및 주요 표 데이터 추출

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
                else:
                    text = current.get_text(strip=True)
                    if text:
                        content_parts.append(text)
            else:
                text = str(current).strip()
                if text:
                    content_parts.append(text)

            current = current.next_sibling

        return "\n".join(content_parts)

    def _parse_notes_subsections(self, content: str) -> List[Dict[str, Any]]:
        """주석 섹션의 세부 섹션 파싱"""
        subsections = []
        lines = content.split("\n")
        current_subsection = None

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 번호로 시작하는 세부 섹션 패턴 확인
            match = re.match(self.section_patterns["subsections"], line)
            if match:
                # 이전 섹션 저장
                if current_subsection:
                    subsections.append(current_subsection)

                # 새 섹션 시작
                number = int(match.group(1))
                title = match.group(2).strip()
                current_subsection = {"number": number, "title": title, "content": ""}
            else:
                # 현재 섹션에 내용 추가
                if current_subsection:
                    if current_subsection["content"]:
                        current_subsection["content"] += "\n" + line
                    else:
                        current_subsection["content"] = line

        # 마지막 섹션 저장
        if current_subsection:
            subsections.append(current_subsection)

        return subsections

    def _parse_table(self, table, index: int) -> Optional[Dict[str, Any]]:
        """개별 테이블 파싱"""
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

            # 테이블 데이터 정리
            table_records = df.to_dict("records")
            table_records = self._clean_nan_values(table_records)

            return {
                "index": index,
                "table_html": table_html,
                "data": table_records,
                "columns": [str(col) for col in df.columns.tolist()],
                "shape": df.shape,
                "row_count": df.shape[0],
                "column_count": df.shape[1],
            }

        except Exception as e:
            self.logger.warning(f"테이블 {index} 파싱 실패: {e}")
            return None

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

        Args:
            file_path: HTML 파일 경로

        Returns:
            파싱된 감사보고서 데이터
        """
        file_path = Path(file_path)

        # HTML 파싱
        soup = self.parse_html(file_path)

        # 섹션 추출
        sections = self.extract_sections(soup)

        # 테이블 추출
        tables = self.extract_tables(soup)

        # 제목 추출
        title = self._extract_title(soup)

        # 연도 추출
        report_year = self._extract_year(file_path.name)

        # 전체 텍스트 추출
        all_text = self._extract_all_text(soup)

        # 결과 구성
        result = {
            "version": "1.0",
            "source_path": str(file_path.absolute()),
            "source_filename": file_path.name,
            "report_year": report_year,
            "title": title,
            "sections": sections,
            "tables": tables,
            "total_sections": len(sections),
            "total_tables": len(tables),
            "all_text": all_text,
            "extraction_metadata": {
                "extraction_timestamp": pd.Timestamp.now().isoformat(),
                "parser_version": "1.0",
                "file_size_bytes": file_path.stat().st_size,
                "total_elements_parsed": len(soup.find_all()),
                "total_content_length": len(all_text),
            },
        }

        self.logger.info(f"감사보고서 파싱 완료: {file_path.name}")
        return result

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
    parser = AuditReportParser(log_level="INFO")

    # HTML 파일 파싱
    input_file = "data/raw/감사보고서_2014.htm"
    output_file = "data/processed/감사보고서_2014_parser.json"

    try:
        # 감사보고서 파싱
        result = parser.parse_report(input_file)

        # JSON 파일로 저장
        parser.save_to_json(result, output_file)

        print(
            f"파싱 완료: {result['total_sections']}개 섹션, {result['total_tables']}개 테이블"
        )

    except Exception as e:
        print(f"파싱 실패: {e}")


if __name__ == "__main__":
    main()
