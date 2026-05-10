# -*- coding: utf-8 -*-
"""
진입점: --mode에 따라 6:30(로컬) 대기·한도 초과 시 동작을 구분.
런 모드는 한도 초과 후 다음날 같은 시각까지 대기하며 같은 프로세스에서 재개.
"""

import argparse
import asyncio
import logging
import sys
import subprocess
import time
from datetime import datetime, timedelta

# .env 로드 (config 임포트 전에 경로만 지정 가능하므로 config에서 load_dotenv 함)
import config

# 로깅 설정 (main 진입 시 로그 레벨 적용)
logger = logging.getLogger(__name__)
from api_client import ApiKeyRotator, fetch_all_routes
from db import init_db, get_connection, save_locations


def wait_until_start_time() -> None:
    """오늘 6시 30분(로컬)까지 대기."""
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
    logger.info("%s 까지 %.0f초 대기합니다.", start.isoformat(), delta)
    time.sleep(delta)


def wait_until_next_scheduled_start() -> None:
    """다음 수집 시작 시각(config의 시·분, 로컬)까지 대기. 런 모드에서 한도 초과 후 재개용."""
    now = datetime.now()
    today_start = now.replace(
        hour=config.PRODUCTION_START_HOUR,
        minute=config.PRODUCTION_START_MINUTE,
        second=0,
        microsecond=0,
    )
    if now < today_start:
        target = today_start
    else:
        target = today_start + timedelta(days=1)
    delta = (target - datetime.now()).total_seconds()
    if delta > 0:
        logger.info(
            "다음 수집 시작(%s, 로컬)까지 약 %.0f초 대기합니다.",
            target.isoformat(timespec="seconds"),
            delta,
        )
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


async def main_async(
    skip_wait_until_start: bool,
    shutdown_on_quota: bool,
    resume_after_quota_next_day: bool,
) -> int:
    """비동기 메인: 1분 간격 수집. skip_wait_until_start면 6:30 대기 생략."""
    if not skip_wait_until_start:
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
            if shutdown_on_quota:
                exit_reason = "quota"
                break
            if resume_after_quota_next_day:
                logger.info(
                    "런 모드: 금일 한도 초과로 수집 중단 후, 다음 예정 시작 시각까지 대기합니다."
                )
                wait_until_next_scheduled_start()
                continue
            exit_reason = "quota"
            break
        if reason == "failure":
            exit_reason = "failure"
            break
        await asyncio.sleep(config.COLLECT_INTERVAL_SEC)

    # 운영 모드: API 한도 초과로만 PC 종료
    if shutdown_on_quota and exit_reason == "quota":
        delay = config.SHUTDOWN_DELAY_SEC
        logger.info("수집 종료(한도 초과). %d초 후 PC를 종료합니다.", delay)
        time.sleep(delay)
        if sys.platform == "win32":
            subprocess.run(["shutdown", "/s", "/t", "0"], check=False)
        else:
            logger.info("(비 Windows 환경에서는 shutdown을 수행하지 않습니다.)")

    return 0 if exit_reason == "quota" else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="버스 위치 수집 (1분 간격)")
    parser.add_argument(
        "--mode",
        choices=("test", "prod", "run"),
        required=True,
        help=(
            "test=즉시 수집·한도 초과 시 종료, "
            "prod=6:30까지 대기·한도 초과 시 PC 종료, "
            "run=6:30까지 대기·한도 초과 시 다음날 6:30까지 대기 후 재개"
        ),
    )
    parser.add_argument("--debug", action="store_true", help="DEBUG 로그 출력 (API 응답 상세 등)")
    args = parser.parse_args()

    # 로깅 초기화
    log_level = logging.DEBUG if args.debug else getattr(logging, config.LOG_LEVEL, logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    resume_after_quota = False
    if args.mode == "test":
        skip_wait = True
        shutdown_on_quota = False
        logger.info("테스트 모드: 6:30 대기 없이 즉시 수집합니다.")
    elif args.mode == "prod":
        skip_wait = False
        shutdown_on_quota = True
        logger.info("운영 모드: 6:30까지 대기 후 수집, 한도 초과 시 PC 종료.")
    else:
        skip_wait = False
        shutdown_on_quota = False
        resume_after_quota = True
        logger.info(
            "런 모드: 6:30까지 대기 후 수집, PC 종료 없음. 한도 초과 시 다음날 같은 시각까지 대기 후 재개."
        )

    exit_code = asyncio.run(
        main_async(skip_wait, shutdown_on_quota, resume_after_quota)
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
