from bs4 import BeautifulSoup, NavigableString, Tag
import re
import collections # defaultdict를 사용하기 위해 import
import pandas as pd  
import io 

class AuditReportParser:
    
    ## 과제 요구사항

    ### **1차 목표: HTML 파싱 및 데이터 추출**
    #### HTML 구조 분석 및 파싱 모듈 개발
    # **HTML 구조 분석**: 각 연도별 감사보고서의 구조적 차이점 파악
    # **섹션 식별**: 재무제표, 주석, 감사의견 등 주요 섹션 자동 분류
    # **표 데이터 추출**: HTML 테이블을 구조화된 데이터로 변환

    def __init__(self):
        
        self._dict_data: dict[str, BeautifulSoup] = {}
        pass
        
    def parse_html(self, file_name):
        #"""HTML 파일 파싱 및 기본 전처리"""
        #data 폴더 내부에 있는 것을 간주로 한다.
        
        if file_name in self._dict_data:
            return self._dict_data[file_name]
        
        with open('data/' + file_name, 'r', encoding='cp949') as file:
            html_content = file.read()
            
        soup = BeautifulSoup(html_content, 'html.parser')
        
        self._dict_data[file_name] = soup
        
        return soup
    
    def extract_sections(self, file_name):
        """
        'SECTION-*' 클래스를 최상위 키, 'id' 또는 텍스트를 하위 키로 사용하고,
        섹션 사이의 모든 콘텐츠를 빠짐없이 추출합니다.
        """
        soup = self.parse_html(file_name)
        
        sections = collections.defaultdict(dict)

        # 문서에 있는 모든 SECTION 태그를 리스트로 미리 만들어 둡니다.
        section_tags = soup.find_all(class_=re.compile(r'SECTION', re.IGNORECASE))
        
        # 다음 섹션 태그를 빠르게 찾기 위해 Set으로도 만들어 둡니다 (성능 향상).
        section_tag_set = set(section_tags)

        for title_tag in section_tags:
            # --- 1. 최상위 키 (클래스 이름) 결정 ---
            class_list = title_tag.get('class', [])
            section_class_key = 'SECTION-UNKNOWN'
            for c in class_list:
                if 'SECTION' in c.upper():
                    section_class_key = c
                    break

            # --- 2. 하위 키 (id 또는 텍스트) 결정 ---
            # id 속성이 있는지 확인하고, 있으면 id를 sub_key로 사용합니다.
            if title_tag.has_attr('id') and title_tag['id']:
                sub_key = title_tag['id']
            # id가 없으면 기존처럼 태그의 텍스트를 사용합니다.
            else:
                sub_key = title_tag.get_text(strip=True)
            
            # 만약 id도 없고 텍스트도 비어있다면, 임시 키를 부여합니다.
            if not sub_key:
                sub_key = f"untitled_section_{len(sections[section_class_key])}"

            # --- 3. 콘텐츠(content)를 빠짐없이 추출 ---
            content_elements = []
            # .next_siblings는 현재 태그 바로 다음에 오는 모든 형제 요소들을 순서대로 가져옵니다.
            for sibling in title_tag.next_siblings:
                # 다음 형제가 또 다른 SECTION 태그라면, 현재 섹션의 내용이 끝난 것입니다.
                if sibling in section_tag_set:
                    break
                # SECTION 태그가 아니라면 모두 현재 섹션의 내용이므로 리스트에 추가합니다.
                content_elements.append(sibling)
            
            # --- 4. 최종 데이터 구조에 저장 ---
            if len(content_elements) > 0:
                sections[section_class_key][sub_key] = content_elements
            
        return sections
    
    def extract_tables(self, file_name):
        """
        '제목 테이블'과 '데이터 테이블'이 한 쌍을 이루는 구조적 규칙을 기반으로
        핵심 재무제표를 정확하게 찾아 추출합니다.
        """
        soup = self.parse_html(file_name)
        extracted_tables = {}

        # 1. 우리가 찾고 싶은 핵심 재무제표의 제목 키워드를 정의합니다.
        #    띄어쓰기를 제거한 형태로 비교할 것입니다.
        target_keywords = ["재무상태표", "손익계산서", "포괄손익계산서", "자본변동표", "현금흐름표"]

        # 2. 문서에 있는 모든 <table> 태그를 순회합니다.
        all_tables = soup.find_all('table')
        
        for table in all_tables:
            # 테이블의 전체 텍스트를 가져와 띄어쓰기를 제거합니다.
            table_text = "".join(table.get_text(strip=True).split())
            
            # 3. 현재 테이블이 '제목 테이블'인지 확인합니다.
            found_title = None
            for target in target_keywords:
                if target in table_text:
                    found_title = target
                    break
            
            # 4. '제목 테이블'을 찾았다면, 바로 다음 형제 테이블이 '데이터 테이블'입니다.
            if found_title:
                data_table = table.find_next_sibling('table')
                
                if data_table:
                    try:
                        # '데이터 테이블'을 DataFrame으로 변환합니다.
                        df_list = pd.read_html(io.StringIO(str(data_table)))
                        if df_list:
                            df = df_list[0]
                            
                            # 최종 제목을 키로 사용하여 딕셔너리에 저장합니다.
                            # 중복 제목 처리를 위한 로직은 만약을 위해 유지합니다.
                            unique_title = found_title
                            count = 1
                            while unique_title in extracted_tables:
                                unique_title = f"{found_title}_{count}"
                                count += 1
                            extracted_tables[unique_title] = df

                    except Exception as e:
                        print(f"'{found_title}' 데이터 테이블 변환 실패: {e}")

        return extracted_tables
    
    def normalize_text(self, text):
        """
        금융 텍스트를 정규화하여 깨끗한 숫자 데이터로 변환합니다.
        (예: "(1,234)" -> -1234)
        """
        # 입력값이 문자열이 아니면 (이미 숫자이거나 None이면) 그대로 반환
        if not isinstance(text, str):
            return text

        # 좌우 공백 제거
        clean_text = text.strip()
        
        # 비어있거나, 하이픈(-)만 있는 경우는 0으로 처리
        if clean_text == '' or clean_text == '-':
            return 0

        # 음수 괄호 처리
        is_negative = False
        if clean_text.startswith('(') and clean_text.endswith(')'):
            is_negative = True
            clean_text = clean_text[1:-1] # 괄호 제거

        # 숫자와 소수점을 제외한 모든 문자(쉼표, '원' 등)를 제거
        clean_text = re.sub(r'[^\d.]', '', clean_text)
        
        # 정제 후 남은 것이 없으면 0으로 처리
        if not clean_text:
            return 0

        try:
            # 실수(float)로 먼저 변환
            value = float(clean_text)
            if is_negative:
                value = -value
            
            # 정수로 표현 가능하다면 정수로 변환 (예: 123.0 -> 123)
            if value.is_integer():
                return int(value)
            else:
                return value
        except ValueError:
            # 숫자로 변환할 수 없는 텍스트는 원래 형태로 반환 (예: '유동자산')
            return text
        
    def get_all_normalized_tables(self, file_name):
        """
        문서에서 모든 테이블을 추출한 뒤, 각 테이블의 모든 셀에 대해
        normalize_text 함수를 적용하여 데이터를 정제합니다.
        
        Returns:
            dict: {테이블 제목: 정제된 DataFrame} 형태의 딕셔너리
        """
        raw_tables = self.extract_tables(file_name)
        normalized_tables = {}

        for title, df in raw_tables.items():
            # .applymap()은 데이터프레임의 모든(map) 셀에 함수를 적용(apply)합니다.
            normalized_df = df.apply(lambda col: col.map(self.normalize_text, na_action='ignore'))
            normalized_tables[title] = normalized_df
            
        return normalized_tables
    
    
# # # --- 최종 사용 예시 ---
# parser = AuditReportParser()

# for i in range(11) :
#      # # 1. 정제되지 않은 원본 테이블 추출
#      num = 2014 + i
#      file_name = '감사보고서_'+ str(num) +'.htm'
     
#      print("--- file name ---")
#      print(file_name)
#      section = parser.extract_sections(file_name)

#      print("--- Section ---")
#      print(section)
#      raw_tables = parser.extract_tables(file_name)
     
#      print("--- 원본 '재무상태표' (일부) ---")
#      print(raw_tables['재무상태표'])
     
#      # # 2. 모든 데이터가 숫자로 정제된 테이블 추출
#      normalized_tables = parser.get_all_normalized_tables(file_name)

#      print("\n--- 정제된 '재무상태표' (일부) ---")
#      print(normalized_tables['재무상태표']) # 데이터 타입이 숫자로 바뀐 것 확인 가능
#      a = normalized_tables['재무상태표']
#      print(a.loc[1]) #재무상태표 유동자산
