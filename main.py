# -*- coding: utf-8 -*-
"""
진입점: 테스트 모드(--test)는 즉시 1분 간격 수집, 운영 모드는 6시 30분까지 대기 후 수집.
"""

import argparse
import asyncio
import logging
import sys
import subprocess
import time
from datetime import datetime, timezone

# .env 로드 (config 임포트 전에 경로만 지정 가능하므로 config에서 load_dotenv 함)
import config

# 로깅 설정 (main 진입 시 로그 레벨 적용)
logger = logging.getLogger(__name__)
from api_client import ApiKeyRotator, fetch_all_routes
from db import init_db, get_connection, save_locations


def wait_until_start_time() -> None:
    """운영 모드: 오늘 6시 30분(로컬)까지 대기."""
    now = datetime.now()
    start = now.replace(
        hour=config.PRODUCTION_START_HOUR,
        minute=config.PRODUCTION_START_MINUTE,
        second=0,
        microsecond=0,
    )
    if now >= start:
        # 이미 지났으면 다음날 6:30은 아니고, 당일 다음 주기로 하지 않음. 당일 한 번만 실행한다고 가정하면 오늘은 스킵.
        # 작업 스케줄러가 매일 6:30에 실행하므로, 실행 시점이 6:30 이후일 수 없음. 만약 수동 실행이면 즉시 시작.
        return
    delta = (start - now).total_seconds()
    logger.info("운영 모드: %s 까지 %.0f초 대기합니다.", start.isoformat(), delta)
    time.sleep(delta)


async def run_once(key_rotator: ApiKeyRotator) -> str | None:
    """
    한 번 수집 실행.
    반환: None = 정상, "quota" = 한도 초과(정상 종료), "failure" = 기타 실패
    """
    route_ids = config.ROUTE_IDS
    if not route_ids:
        logger.warning("config.ROUTE_IDS가 비어 있습니다.")
        return "failure"

    keys = key_rotator._keys
    if not keys:
        logger.error("API_KEY가 .env에 설정되지 않았습니다.")
        return "failure"

    try:
        records, quota_exceeded = await fetch_all_routes(route_ids, key_rotator)
    except Exception as e:
        logger.exception("API 수집 실패: %s", e)
        return "failure"

    if quota_exceeded:
        logger.info("API 토큰 한도 초과로 수집을 종료합니다.")
        return "quota"

    try:
        saved = await save_locations(records)
        logger.info("수집 완료: 노선 %d개에 대한 응답, %d건 저장", len(route_ids), saved)
    except Exception as e:
        logger.exception("DB 저장 실패: %s", e)
        return "failure"

    return None


async def main_async(test_mode: bool, do_shutdown: bool) -> int:
    """비동기 메인: 테스트면 즉시, 아니면 6:30 대기 후 1분마다 수집."""
    # 운영 모드일 때만 6:30 대기
    if not test_mode:
        wait_until_start_time()

    keys = config.get_api_keys()
    if not keys:
        logger.error(".env에 API_KEY를 설정해 주세요.")
        return 1

    key_rotator = ApiKeyRotator(keys)

    # DB 초기화
    try:
        conn = await get_connection()
        await init_db(conn)
        await conn.close()
    except Exception as e:
        logger.exception("DB 연결/초기화 실패: %s", e)
        return 1

    exit_reason: str | None = None  # None=계속, "quota", "failure"

    while True:
        reason = await run_once(key_rotator)
        if reason == "quota":
            exit_reason = "quota"
            break
        if reason == "failure":
            exit_reason = "failure"
            break
        await asyncio.sleep(config.COLLECT_INTERVAL_SEC)

    # 수집 종료 후 10분 대기 후 PC 종료 옵션
    if do_shutdown:
        delay = config.SHUTDOWN_DELAY_SEC
        logger.info("수집 종료. %d초 후 PC를 종료합니다.", delay)
        time.sleep(delay)
        if sys.platform == "win32":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
        else:
            logger.info("(비 Windows 환경에서는 shutdown을 수행하지 않습니다.)")

    return 0 if exit_reason == "quota" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="버스 위치 수집 (1분 간격)")
    parser.add_argument("--test", action="store_true", help="테스트 모드: 즉시 1분 간격 수집 시작")
    parser.add_argument("--shutdown", action="store_true", help="수집 종료 후 10분 대기 후 PC 종료")
    parser.add_argument("--debug", action="store_true", help="DEBUG 로그 출력 (API 응답 상세 등)")
    args = parser.parse_args()

    # 로깅 초기화
    log_level = logging.DEBUG if args.debug else getattr(logging, config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 테스트 모드 미지정 시 운영 모드(6:30 대기)
    test_mode = args.test
    do_shutdown = args.shutdown

    exit_code = asyncio.run(main_async(test_mode=test_mode, do_shutdown=do_shutdown))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
