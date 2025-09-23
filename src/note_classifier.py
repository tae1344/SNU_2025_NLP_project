#!/usr/bin/env python3
"""
주석 분류기 (Note Classifier)

감사보고서의 주석을 유형별로 자동 분류하는 모듈

한계/확장 포인트
- 단순 키워드 매칭 기반이라 문맥/동의어에 취약

개선:
- 도메인 사전 확장, 
- 정규식 보강(표/리스트 처리), 
- 임베딩 기반 보조 분류기 추가, 
- 연도별 패턴 차이 보정
"""

import re
import json
import logging
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from collections import Counter

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class NoteClassification:
    """주석 분류 결과"""

    note_number: int
    title: str
    content: str
    category: str
    subcategory: str
    confidence: float
    keywords: List[str]
    year: int


class NoteClassifier:
    """주석 분류기"""

    def __init__(self):
        """주석 분류기 초기화"""
        self.category_patterns = self._load_category_patterns()
        self.subcategory_patterns = self._load_subcategory_patterns()

    def _load_category_patterns(self) -> Dict[str, List[str]]:
        """주요 카테고리 패턴 로드"""
        return {
            "회계정책": [
                "회계정책",
                "회계처리방법",
                "회계기준",
                "회계정책과 공시의 변경",
                "재무제표 작성기준",
                "회계정책의 변경",
                "회계처리방침",
            ],
            "재무상태": [
                "자산",
                "부채",
                "자본",
                "유동자산",
                "비유동자산",
                "유동부채",
                "비유동부채",
                "현금및현금성자산",
                "매출채권",
                "재고자산",
                "유형자산",
                "무형자산",
            ],
            "손익계산": [
                "매출",
                "수익",
                "매출원가",
                "판매비",
                "관리비",
                "영업이익",
                "당기순이익",
                "매출총이익",
                "영업외수익",
                "영업외비용",
                "법인세비용",
            ],
            "현금흐름": [
                "현금흐름",
                "현금흐름표",
                "영업활동현금흐름",
                "투자활동현금흐름",
                "재무활동현금흐름",
                "현금및현금성자산의 증감",
            ],
            "자본변동": [
                "자본변동",
                "자본변동표",
                "자본금",
                "자본잉여금",
                "이익잉여금",
                "기타포괄손익",
                "자본거래",
                "배당",
            ],
            "관련자거래": [
                "관련자",
                "관련회사",
                "관련자거래",
                "지배기업",
                "종속기업",
                "연결회사",
                "관련자와의 거래",
                "관련자 거래",
            ],
            "우발부채": [
                "우발부채",
                "우발사항",
                "보증",
                "담보",
                "소송",
                "분쟁",
                "계약상 의무",
                "우발부채 및 우발자산",
            ],
            "사업부문": [
                "사업부문",
                "부문별",
                "사업부문별",
                "부문별 정보",
                "사업부문 정보",
                "DX부문",
                "DS부문",
                "Device eXperience",
                "Device Solutions",
            ],
            "리스크관리": [
                "위험",
                "리스크",
                "위험관리",
                "신용위험",
                "시장위험",
                "유동성위험",
                "운영위험",
                "법적위험",
                "규제위험",
            ],
            "감사정보": [
                "감사",
                "감사인",
                "감사보고서",
                "감사의견",
                "감사위원회",
                "내부회계관리제도",
                "감사비용",
                "감사인 선임",
            ],
            "기타": ["기타", "일반", "기타사항", "기타 정보", "추가 정보"],
        }

    def _load_subcategory_patterns(self) -> Dict[str, Dict[str, List[str]]]:
        """세부 카테고리 패턴 로드"""
        return {
            "회계정책": {
                "기준": ["한국채택국제회계기준", "K-IFRS", "회계기준", "기준서"],
                "변경": ["회계정책의 변경", "기준서 개정", "신규 적용", "변경사항"],
                "추정": ["회계추정", "추정치", "가정", "판단", "추정의 변경"],
            },
            "재무상태": {
                "자산": [
                    "현금",
                    "매출채권",
                    "재고자산",
                    "유형자산",
                    "무형자산",
                    "투자자산",
                ],
                "부채": ["매입채무", "차입금", "사채", "충당부채", "퇴직급여충당부채"],
                "자본": ["자본금", "자본잉여금", "이익잉여금", "기타포괄손익"],
            },
            "손익계산": {
                "수익": ["매출", "수익", "매출원가", "매출총이익"],
                "비용": ["판매비", "관리비", "연구개발비", "감가상각비"],
                "이익": ["영업이익", "당기순이익", "법인세비용"],
            },
            "현금흐름": {
                "영업": ["영업활동현금흐름", "영업현금흐름"],
                "투자": ["투자활동현금흐름", "투자현금흐름"],
                "재무": ["재무활동현금흐름", "재무현금흐름"],
            },
            "자본변동": {
                "자본거래": ["자본금", "자본잉여금", "자본거래"],
                "이익분배": ["배당", "이익분배", "배당금"],
                "기타포괄손익": ["기타포괄손익", "OCI", "기타포괄손익누계액"],
            },
        }

    def classify_note(
        self, note_number: int, title: str, content: str, year: int
    ) -> NoteClassification:
        """주석 분류"""
        # 제목과 내용을 결합하여 분석
        full_text = f"{title} {content}".lower()

        # 카테고리 점수 계산
        category_scores = {}
        for category, patterns in self.category_patterns.items():
            score = 0
            matched_keywords = []
            for pattern in patterns:
                if pattern.lower() in full_text:
                    score += 1
                    matched_keywords.append(pattern)
            category_scores[category] = (score, matched_keywords)

        # 가장 높은 점수의 카테고리 선택
        best_category = max(category_scores.items(), key=lambda x: x[1][0])
        category = best_category[0]
        confidence = best_category[1][0] / len(self.category_patterns[category])
        keywords = best_category[1][1]

        # 세부 카테고리 분류
        subcategory = self._classify_subcategory(category, full_text)

        return NoteClassification(
            note_number=note_number,
            title=title,
            content=content,
            category=category,
            subcategory=subcategory,
            confidence=confidence,
            keywords=keywords,
            year=year,
        )

    def _classify_subcategory(self, category: str, text: str) -> str:
        """세부 카테고리 분류"""
        if category not in self.subcategory_patterns:
            return "기타"

        subcategory_scores = {}
        for subcategory, patterns in self.subcategory_patterns[category].items():
            score = sum(1 for pattern in patterns if pattern.lower() in text)
            subcategory_scores[subcategory] = score

        if not subcategory_scores or max(subcategory_scores.values()) == 0:
            return "기타"

        return max(subcategory_scores.items(), key=lambda x: x[1])[0]

    def extract_notes_from_json(self, json_file_path: Path) -> List[NoteClassification]:
        """JSON 파일에서 주석 추출 및 분류"""
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        year = data.get("metadata", {}).get("report_year", 2024)
        notes = []

        # 주석 섹션 찾기
        notes_section = None
        for section in data.get("sections", []):
            if section.get("title") == "주석":
                notes_section = section
                break

        if not notes_section:
            logger.warning(f"주석 섹션을 찾을 수 없습니다: {json_file_path}")
            return notes

        # 주석 내용에서 번호별 주석 추출
        content = notes_section.get("content", "")
        note_blocks = self._extract_note_blocks(content)

        for note_number, note_content in note_blocks.items():
            title = f"주석 {note_number}"
            classification = self.classify_note(note_number, title, note_content, year)
            notes.append(classification)

        return notes

    def _extract_note_blocks(self, content: str) -> Dict[int, str]:
        """주석 내용에서 번호별 주석 블록 추출"""
        note_blocks = {}

        # 주석 번호 패턴 (예: "1. 일반적 사항:", "2. 중요한 회계처리방침:")
        pattern = r"(\d+)\.\s*([^:]+):\s*([^0-9]+?)(?=\d+\.|$)"
        matches = re.findall(pattern, content, re.DOTALL)

        for match in matches:
            note_number = int(match[0])
            title = match[1].strip()
            note_content = match[2].strip()

            # 다음 주석까지의 내용 포함
            if note_number > 1:
                # 이전 주석의 끝부터 현재 주석까지
                start_pattern = f"{note_number-1}\\.\\s*[^:]+:\\s*"
                end_pattern = f"{note_number}\\.\\s*[^:]+:\\s*"

                # 더 정확한 추출을 위해 정규식 사용
                full_pattern = f"{note_number}\\.\\s*{re.escape(title)}:\\s*([^0-9]+?)(?=\\d+\\.|$)"
                full_match = re.search(full_pattern, content, re.DOTALL)
                if full_match:
                    note_content = full_match.group(1).strip()

            note_blocks[note_number] = f"{title}: {note_content}"

        return note_blocks

    def classify_all_files(self, input_dir: Path, output_dir: Path) -> None:
        """모든 JSON 파일의 주석 분류"""
        output_dir.mkdir(parents=True, exist_ok=True)

        json_files = list(input_dir.glob("*.json"))
        logger.info(f"총 {len(json_files)}개 파일 처리 시작")

        all_classifications = []

        for json_file in json_files:
            logger.info(f"처리 중: {json_file.name}")
            try:
                notes = self.extract_notes_from_json(json_file)
                all_classifications.extend(notes)

                # 개별 파일 결과 저장
                year = json_file.stem.split("_")[-1].replace("parser_v3", "")
                output_file = output_dir / f"notes_classified_{year}.json"

                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(
                        [note.__dict__ for note in notes],
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )

                logger.info(f"주석 {len(notes)}개 분류 완료: {output_file}")

            except Exception as e:
                logger.error(f"파일 처리 실패 {json_file}: {e}")

        # 전체 결과 저장
        summary_file = output_dir / "notes_classification_summary.json"
        summary = self._create_summary(all_classifications)

        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        logger.info(f"전체 분류 완료: {len(all_classifications)}개 주석")
        logger.info(f"요약 저장: {summary_file}")

    def _create_summary(
        self, classifications: List[NoteClassification]
    ) -> Dict[str, Any]:
        """분류 결과 요약 생성"""
        # 카테고리별 통계
        category_counts = Counter(note.category for note in classifications)
        subcategory_counts = Counter(
            f"{note.category}-{note.subcategory}" for note in classifications
        )

        # 연도별 통계
        year_stats = {}
        for note in classifications:
            year = note.year
            if year not in year_stats:
                year_stats[year] = {"total": 0, "categories": Counter()}
            year_stats[year]["total"] += 1
            year_stats[year]["categories"][note.category] += 1

        return {
            "total_notes": len(classifications),
            "category_distribution": dict(category_counts),
            "subcategory_distribution": dict(subcategory_counts),
            "year_statistics": {
                str(year): dict(stats) for year, stats in year_stats.items()
            },
            "confidence_stats": {
                "average": sum(note.confidence for note in classifications)
                / len(classifications),
                "min": min(note.confidence for note in classifications),
                "max": max(note.confidence for note in classifications),
            },
        }


def main():
    """메인 함수"""
    input_dir = Path("data/processed")
    output_dir = Path("data/notes_classified")

    classifier = NoteClassifier()
    classifier.classify_all_files(input_dir, output_dir)


if __name__ == "__main__":
    main()
