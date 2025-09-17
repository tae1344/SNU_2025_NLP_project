"""
HTML Parsing Module V3

이 모듈은 삼성전자 감사보고서 HTML 파일의 파싱 및 기본 전처리를 담당합니다.
Version 3.0에서는 텍스트 기반 섹션 분류와 계층적 파싱을 지원합니다.
"""

import logging
import re
from pathlib import Path
from typing import Optional, Union, Dict, Any
from bs4.element import ResultSet
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

        # BR/공백/&nbsp;만 포함된 레이아웃용 태그 제거
        self._remove_empty_layout_tags(soup)

        # 불필요한 텍스트 패턴 제거
        self._remove_unnecessary_texts(soup)

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

    def _remove_empty_layout_tags(self, soup: BeautifulSoup) -> None:
        """
        BR/공백/&nbsp;만 포함된 P/DIV/SPAN 등의 레이아웃용 태그 제거

        - <p><br></p>, <p><br><br>...</p>
        - <p><br><br>... &nbsp; &nbsp; ...</p>
        - <span>&nbsp; &nbsp; ...</span>
        - 텍스트가 공백/nbsp 뿐인 경우
        """
        removed_count = 0

        def is_layout_only(tag: ResultSet) -> bool:
            # 태그가 문자열만 가지고 있고, 그 문자열이 공백/nbsp 뿐인지 검사
            def is_empty_text(text: str) -> bool:
                if text is None:
                    return True
                # BeautifulSoup에서는 &nbsp;가 \u00A0로 변환되는 경우가 많음
                normalized = text.replace("\u00a0", " ")
                normalized = normalized.replace("\xa0", " ")
                # &nbsp; 리터럴이 남아있을 수 있어 추가 치환
                normalized = normalized.replace("&nbsp;", " ")
                normalized = normalized.replace("&#160;", " ")
                return len(normalized.strip()) == 0

            # 허용되는 하위 요소: <br> 또는 공백/nbsp 텍스트, 그리고 같은 규칙의 <span>
            for child in tag.contents:
                name = getattr(child, "name", None)
                if name == "br":
                    continue
                if name in {"span"}:
                    # span 내부 텍스트가 비어있는지 확인
                    if not is_empty_text(child.get_text("", strip=False)):
                        return False
                    continue
                if isinstance(child, str):
                    if not is_empty_text(child):
                        return False
                    continue
                # 그 외의 태그가 존재하면 레이아웃 전용이 아님
                return False

            # 내용이 모두 허용 요소로만 구성됨
            # 추가로 전체 텍스트가 비어있는지 확인
            return is_empty_text(tag.get_text("", strip=False))

        # 대상 태그 순회 (p/div/span 중심)
        for t in list(soup.find_all(["p", "div", "span"])):
            try:
                if is_layout_only(t):
                    t.decompose()
                    removed_count += 1
            except Exception:
                # 예외가 발생해도 파싱에 영향 없도록 무시
                continue

        # 연속된 <br> 정리: 같은 부모 아래에서 2개 이상 연속된 <br>는 1개만 남김
        for parent in soup.find_all(True):
            # 너무 많은 반복을 피하기 위해 자식 수가 적은 경우만 처리
            if not parent.contents or len(parent.contents) < 2:
                continue
            i = 0
            while i < len(parent.contents) - 1:
                curr = parent.contents[i]
                nxt = parent.contents[i + 1]
                if (
                    getattr(curr, "name", None) == "br"
                    and getattr(nxt, "name", None) == "br"
                ):
                    nxt.extract()
                    removed_count += 1
                    continue  # 같은 i에서 다음 것도 검사
                i += 1

        self.logger.debug(f"빈/형식용 태그 제거: {removed_count}개")

    def _remove_unnecessary_texts(self, soup: BeautifulSoup) -> None:
        """
        불필요한 텍스트 패턴 제거

        - "계속;" 텍스트가 포함된 태그 제거
        - 다른 content 안의 "계속;" 텍스트를 빈 문자열로 치환
        - 추후 다른 패턴도 쉽게 추가 가능한 구조
        """
        removed_count = 0

        # 제거할 텍스트 패턴 정의 (문자열과 정규식 모두 지원)
        text_patterns = {
            # 문자열 패턴 예시
            # "더보기": {
            #     "type": "string",
            #     "action": "remove_tag_if_only_text",
            #     "fallback_action": "replace_with_empty",
            #     "description": "더보기 텍스트 패턴",
            # },
            # 정규식 패턴
            "계속_패턴": {
                "type": "regex",
                "pattern": r"계속\s*[;:]",  # "계속;", "계속:", "계속 :", "계속 ;" 등
                "action": "remove_tag_if_only_text",
                "fallback_action": "replace_with_empty",
                "description": "계속 관련 텍스트 패턴",
            },
        }

        for pattern, config in text_patterns.items():
            removed_count += self._process_text_pattern(soup, pattern, config)

        self.logger.debug(f"불필요한 텍스트 패턴 제거: {removed_count}개")

    def _process_text_pattern(
        self, soup: BeautifulSoup, pattern_name: str, config: Dict[str, Any]
    ) -> int:
        """
        특정 텍스트 패턴 처리 (문자열과 정규식 모두 지원)

        Args:
            soup: BeautifulSoup 객체
            pattern_name: 패턴 이름
            config: 처리 설정

        Returns:
            처리된 항목 수
        """
        removed_count = 0
        pattern_type = config.get("type", "string")

        if pattern_type == "string":
            # 문자열 패턴 처리
            pattern = pattern_name
            tags_with_pattern = soup.find_all(
                string=lambda text: text and pattern in text
            )

        elif pattern_type == "regex":
            # 정규식 패턴 처리
            pattern = config["pattern"]
            compiled_pattern = re.compile(pattern)
            tags_with_pattern = soup.find_all(
                string=lambda text: text and compiled_pattern.search(text)
            )

        else:
            self.logger.warning(f"지원하지 않는 패턴 타입: {pattern_type}")
            return 0

        for text_node in tags_with_pattern:
            try:
                parent_tag = text_node.parent
                if not parent_tag:
                    continue

                # 태그의 전체 텍스트에서 패턴 확인
                full_text = parent_tag.get_text(strip=True)

                # 패턴 매칭 확인
                if pattern_type == "string":
                    is_exact_match = full_text == pattern
                    has_pattern = pattern in full_text
                else:  # regex
                    is_exact_match = bool(compiled_pattern.fullmatch(full_text))
                    has_pattern = bool(compiled_pattern.search(full_text))

                if is_exact_match:
                    # 패턴만 있는 경우: 태그 전체 제거
                    if config["action"] == "remove_tag_if_only_text":
                        parent_tag.decompose()
                        removed_count += 1
                        self.logger.debug(
                            f"태그 제거: '{pattern_name}' - {parent_tag.name}"
                        )

                elif has_pattern:
                    # 다른 텍스트와 함께 있는 경우: 패턴만 치환
                    if config["fallback_action"] == "replace_with_empty":
                        if pattern_type == "string":
                            # 문자열 패턴 치환
                            new_text = text_node.replace(pattern, "").strip()
                        else:
                            # 정규식 패턴 치환
                            new_text = compiled_pattern.sub("", text_node).strip()

                        if new_text:
                            text_node.replace_with(new_text)
                        else:
                            # 빈 텍스트가 되면 제거
                            text_node.extract()
                        removed_count += 1
                        self.logger.debug(f"텍스트 치환: '{pattern_name}' -> 빈 문자열")

            except Exception as e:
                # 예외 발생 시 로깅하고 계속 진행
                self.logger.warning(f"텍스트 패턴 처리 중 오류: {e}")
                continue

        return removed_count

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
