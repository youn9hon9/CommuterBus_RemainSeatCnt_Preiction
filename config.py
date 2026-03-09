# -*- coding: utf-8 -*-
"""수집 대상 노선 및 DB 등 설정."""

import os
from pathlib import Path

# .env 로드는 main 진입 전에 호출됨
_env_path = Path(__file__).resolve().parent / ".env"
if _env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_path)

# 수집 대상 노선 ID 목록 (5개)
ROUTE_IDS: list[str] = [
    "232000090",  #김포 G6000
    "234000011",  #1113-1
    "228000431",  #5003A
    "234000995",  #M4403
    "204000057",  #3330
]

# API 키: 쉼표로 구분된 복수 키 지원, 순환 사용
def get_api_keys() -> list[str]:
    raw = os.getenv("API_KEY", "").strip()
    if not raw:
        return []
    return [k.strip() for k in raw.split(",") if k.strip()]

# DB 연결 문자열
DB_URL: str = os.getenv("DB_URL", "postgresql://postgres:password@localhost:5432/busdb")

# API 기본 URL
API_BASE_URL: str = "https://apis.data.go.kr/6410000/buslocationservice/v2/getBusLocationListv2"

# 응답 형식: "json" 또는 "xml"
API_FORMAT: str = os.getenv("API_FORMAT", "json").lower()
if API_FORMAT not in ("json", "xml"):
    API_FORMAT = "json"

# 수집 주기(초)
COLLECT_INTERVAL_SEC: int = 60

# 운영 모드 수집 시작 시각 (시, 분)
PRODUCTION_START_HOUR: int = 6
PRODUCTION_START_MINUTE: int = 30

# 수집 종료 후 PC 종료 전 대기 시간(초)
SHUTDOWN_DELAY_SEC: int = 600  # 10분

# 로그 레벨: DEBUG | INFO | WARNING | ERROR. 디버깅 시 DEBUG 사용
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
