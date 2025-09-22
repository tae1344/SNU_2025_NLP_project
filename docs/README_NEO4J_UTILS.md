# Neo4j Database Utilities

이 모듈은 Neo4j 데이터베이스 관리를 위한 포괄적인 유틸리티를 제공합니다.

## 🚀 주요 기능

- **데이터베이스 초기화**: 모든 노드와 관계 삭제
- **상태 모니터링**: 노드/관계 수 통계 및 건강 상태 체크
- **스키마 검증**: 제약조건 및 인덱스 확인
- **성능 최적화**: 인덱스 생성 및 데이터베이스 최적화
- **백업/복원**: 논리적 백업 생성
- **CLI 도구**: 명령줄 인터페이스

## 📦 모듈 구성

### 1. `neo4j_utils.py` - 핵심 유틸리티 클래스

```python
from src.structured_etl.neo4j_utils import Neo4jUtils

# Context manager 사용
with Neo4jUtils() as utils:
    # 건강 상태 체크
    health = utils.health_check()
    print(f"Status: {health['status']}")
    
    # 데이터베이스 통계
    stats = utils.get_database_stats()
    print(f"Total nodes: {stats['total_nodes']}")
    
    # 데이터베이스 초기화 (주의!)
    result = utils.clear_database(confirm=True)
    
    # 스키마 검증
    validation = utils.validate_schema()
    
    # 최적화
    opt_result = utils.optimize_database()
```

### 2. `neo4j_cli.py` - 명령줄 인터페이스

#### 사용법

```bash
# 환경변수 설정
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j  
export NEO4J_PASSWORD=your_password

# 또는 매번 지정
NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=your_password python -m src.structured_etl.neo4j_cli [command]
```

#### 명령어 목록

```bash
# 건강 상태 체크
python -m src.structured_etl.neo4j_cli health

# 데이터베이스 통계
python -m src.structured_etl.neo4j_cli stats
python -m src.structured_etl.neo4j_cli stats --json  # JSON 파일로 저장

# 데이터베이스 초기화 (위험!)
python -m src.structured_etl.neo4j_cli clear --confirm

# 데이터베이스 요약 내보내기
python -m src.structured_etl.neo4j_cli export summary.json

# 데이터베이스 최적화
python -m src.structured_etl.neo4j_cli optimize

# 백업 생성
python -m src.structured_etl.neo4j_cli backup ./backups
```

## 📊 출력 예시

### Health Check
```
🏥 Performing Neo4j health check...

✅ Status: HEALTHY
🔗 Connectivity: OK
📊 Nodes: 882
🔗 Relationships: 935

⚠️  Issues found:
   • Missing constraint: unique_company_id
   • Missing constraint: unique_subsidiary_id
```

### Database Statistics
```
📈 Database Overview:
   Total nodes: 882
   Total relationships: 935

🏷️  Node Types:
   COMPANY: 1
   SUBSIDIARY: 1
   FS_SECTION: 4
   FS_CATEGORY: 115
   YEAR_NODE: 12
   FINANCIAL_DATA: 642
   AUDITOR: 1
   AUDIT_INFO: 6
   NOTE: 92
   NOTE_CATEGORY: 8

🔗 Relationship Types:
   HAS_SUBSIDIARY: 1
   HAS_FINANCIAL_STATEMENT: 4
   HAS_CATEGORY: 115
   HAS_YEAR_DATA: 12
   CONTAINS_DATA: 642
   AUDITED_BY: 1
   HAS_AUDIT_INFO: 6
   HAS_NOTE: 92
   HAS_NOTE_CATEGORY: 54
   TREND_TO: 8
```

## 🔧 demo_smoke.py 통합

`demo_smoke.py`에 유틸리티가 통합되어 다음 기능을 제공합니다:

- **초기 건강 상태 체크**: Demo 시작 전 데이터베이스 상태 확인
- **기존 데이터 경고**: 데이터베이스에 기존 노드가 있으면 경고 메시지
- **최종 최적화**: Demo 완료 후 자동 인덱스 생성 및 최적화
- **최종 건강 상태 체크**: 모든 작업 완료 후 상태 확인

## 🛡️ 안전 기능

### 1. 확인 메커니즘
- `clear_database()`는 `confirm=True` 매개변수 필수
- CLI에서는 `--confirm` 플래그 필수

### 2. 상태 모니터링
- 연결 상태 실시간 체크
- 스키마 무결성 검증
- 성능 이슈 감지

### 3. 백업 기능
- 논리적 백업 생성 (Cypher 형태)
- 타임스탬프 기반 파일명
- 메타데이터 포함

## 🔍 문제 해결

### 일반적인 문제들

1. **연결 오류**
   ```bash
   # Neo4j 서버 상태 확인
   python -m src.structured_etl.neo4j_cli health
   ```

2. **성능 저하**
   ```bash
   # 데이터베이스 최적화
   python -m src.structured_etl.neo4j_cli optimize
   ```

3. **스키마 문제**
   ```bash
   # 스키마 검증
   python -m src.structured_etl.neo4j_cli health
   ```

4. **데이터 정리**
   ```bash
   # 모든 데이터 삭제 (주의!)
   python -m src.structured_etl.neo4j_cli clear --confirm
   ```

### 환경 설정

```bash
# .env 파일 또는 환경변수
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password

# Docker Neo4j 사용시
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=test
```

## 📈 성능 최적화

### 자동 인덱스 생성
- `company.name`
- `year_node.year`  
- `note.note_number`
- `financial_data.value`

### 권장사항
1. 정기적인 최적화 실행
2. 큰 데이터셋 처리 전 기존 데이터 정리
3. 건강 상태 정기 체크
4. 중요한 작업 전 백업 생성

## 🎯 사용 시나리오

### 개발 중
```bash
# 개발 시작 전 데이터베이스 정리
python -m src.structured_etl.neo4j_cli clear --confirm

# ETL 실행
python -m src.structured_etl.demo_smoke

# 결과 확인
python -m src.structured_etl.neo4j_cli stats
```

### 프로덕션
```bash
# 건강 상태 체크
python -m src.structured_etl.neo4j_cli health

# 백업 생성
python -m src.structured_etl.neo4j_cli backup ./backups

# 최적화 실행
python -m src.structured_etl.neo4j_cli optimize
```

이 유틸리티들을 통해 Neo4j 데이터베이스를 효율적이고 안전하게 관리할 수 있습니다.
