# 버스 위치 수집기 (광역 버스 5개 노선)

광역 버스 5개 노선에 대해 1분마다 공공 API를 비동기로 호출해 버스 위치를 수집하고, 결과를 TimescaleDB에 저장하는 프로그램입니다.

## 요구 사항

- **Python**: 3.11 이상
- **TimescaleDB**: Docker로 실행 (PostgreSQL 확장)

## 1. 프로젝트 설정 (venv)

아무것도 설치되어 있지 않은 환경에서도 venv만으로 실행할 수 있습니다.

```powershell

# 가상환경 생성
python -m venv .venv

# 가상환경 활성화 (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 의존성 설치
pip install -r requirements.txt
```

## 2. 환경 변수 (.env)

프로젝트 루트에 `.env` 파일을 만들고 아래 항목을 설정합니다.

| 변수 | 설명 |
|------|------|
| `API_KEY` | 공공데이터 API 인증키. 복수 키는 쉼표로 구분해 순환 사용 가능. |
| `DB_URL` | TimescaleDB 연결 문자열. 예: `postgresql://postgres:password@localhost:5432/busdb` |
| `API_FORMAT` | (선택) 응답 형식. `json` 또는 `xml`. 기본값: `json` |

`.env.example`을 복사해 사용할 수 있습니다.

## 3. TimescaleDB 실행 (Docker)
docker 설치 후, 터미널에서 Docker가 잘 작동하는지 확인
```
docker --version
```
로컬에서 DB를 Docker로 띄울 때 예시는 아래와 같습니다.
```powershell
docker run -d `
  --name timescaledb `
  -p 5432:5432 `
  -e POSTGRES_PASSWORD=your_password `
  -e POSTGRES_DB=your_db_name `
  timescale/timescaledb:latest-pg16
```
- **이미지**: `timescale/timescaledb` (최신은 `timescale/timescaledb:latest-pg16` 등)
- **DB정보**your_password, your_db_name은 자유롭게 설정하세요.
- 이 정보는 .env 파일에도 아래와 같이 동일하게 등록해야 합니다.
```
DB_URL=postgresql://postgres:your_password@localhost:5432/your_db_name
```

## 4. DB 테이블 생성(초기화)

수집 전에 테이블을 한 번 만들어 둡니다. **첫 수집 실행 시 자동으로 테이블을 만들기도 하지만**, 미리 초기화하려면:

```powershell
python init_db.py
```

## 5. 수집 대상 노선 설정

`config.py`의 `ROUTE_IDS` 리스트에 사용할 노선ID를 넣습니다.
노선ID는 https://www.data.go.kr/data/15080662/openapi.do#/ 에서 확인할 수 있습니다.

```python
ROUTE_IDS: list[str] = [
    "200000150",
    "200000151",
    # ... 실제 노선 ID로 교체
]
```

## 6. 실행 방법

### 테스트 실행 (바로 1분마다 수집)

즉시 1분 간격 수집을 시작합니다.

```powershell
python main.py --test
```

### 디버깅 실행 (바로 1분마다 수집)

응답 메시지의 상태를 바로 확인합니다.

```powershell
python main.py --test --debug
```

### 운영 실행 (6시 30분 대기 후 수집)

아침에 컴퓨터를 켜두고 할 일 하다가 등교하면, 자동으로 데이터도 수집하고 컴퓨터를 종료해주도록 설계하였습니다. (종료하지 않는다면, shutdown 옵션 제거) 실행 후 출근시간인 **오늘 6시 30분**까지 대기했다가, 6시 30분부터 1분마다 수집을 시작합니다. 노선 5개에 대해서 수집하면, 개발계정의 API 제한 횟수인 1000회를 소진하였을 때 9시 50분까지 200분의 데이터를 얻을 수 있습니다.

```powershell
python main.py --shutdown
```

## db 내용 csv로 내보내기
쿼리를 통해 필요한 정보만 조회하는 것이 아니라, 간단하게 csv로 보고 싶을 때 사용
csv는 data 폴더 안에 저장

현재까지 저장된 데이터 모두 내보내기
```powershell
python exprot_csv.py
```

특정 기간의 데이터만 내보내기
```powershell
python exprot_csv.py --startdate 20260301 --enddate 20260309
```