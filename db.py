# -*- coding: utf-8 -*-
"""TimescaleDB 연결 및 버스 위치 저장."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import asyncpg

import config
from api_client import BusLocationRecord


# TimescaleDB 연결용: postgresql:// -> postgres:// (asyncpg 규칙)
def _dsn_for_asyncpg(url: str) -> str:
    if url.startswith("postgresql://"):
        return "postgres://" + url[len("postgresql://"):]
    return url


async def get_connection() -> asyncpg.Connection:
    """DB 연결 풀 없이 단일 연결 반환. 세션 타임존은 Asia/Seoul(KST)로 설정."""
    dsn = _dsn_for_asyncpg(config.DB_URL)
    conn = await asyncpg.connect(dsn)
    await conn.execute("SET timezone = 'Asia/Seoul'")
    return conn


TABLE_NAME = "bus_location"


def get_create_table_sql() -> str:
    """테이블 생성 SQL (TimescaleDB 하이퍼테이블)."""
    return f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        time        TIMESTAMPTZ NOT NULL,
        plate_no    TEXT,
        route_id    TEXT NOT NULL,
        remain_seat_cnt TEXT,
        station_id  TEXT,
        station_seq TEXT,
        extra       JSONB,
        PRIMARY KEY (time, route_id, plate_no)
    );

    SELECT create_hypertable(
        '{TABLE_NAME}',
        'time',
        if_not_exists => TRUE,
        migrate_data => TRUE
    );
    """


async def init_db(conn: asyncpg.Connection) -> None:
    """테이블이 없으면 생성 (하이퍼테이블)."""
    sql = get_create_table_sql()
    # create_hypertable는 별도 실행
    base_sql = f"""
    CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
        time        TIMESTAMPTZ NOT NULL,
        plate_no    TEXT,
        route_id    TEXT NOT NULL,
        remain_seat_cnt TEXT,
        station_id  TEXT,
        station_seq TEXT,
        extra       JSONB,
        PRIMARY KEY (time, route_id, plate_no)
    );
    """
    await conn.execute(base_sql)
    # 기존 일반 테이블이면 hypertable로 변환 (이미 hypertable이면 무시)
    try:
        await conn.execute(
            f"SELECT create_hypertable('{TABLE_NAME}', 'time', if_not_exists => TRUE);"
        )
    except asyncpg.exceptions.DuplicateObjectError:
        pass


async def insert_records(conn: asyncpg.Connection, records: list[BusLocationRecord], collected_at: datetime) -> int:
    """한 시각에 수집한 레코드 일괄 삽입."""
    if not records:
        return 0

    # plate_no가 빈 경우 PK 충돌 방지를 위해 route_id+index 등 사용 가능. 여기서는 빈 문자열 허용.
    values: list[tuple] = []
    for r in records:
        extra_json = json.dumps(r.extra, ensure_ascii=False) if r.extra else None
        values.append((
            collected_at,
            r.plate_no or "",
            r.route_id or "",
            r.remain_seat_cnt,
            r.station_id,
            r.station_seq,
            extra_json,
        ))

    await conn.executemany(
        f"""
        INSERT INTO {TABLE_NAME}
        (time, plate_no, route_id, remain_seat_cnt, station_id, station_seq, extra)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (time, route_id, plate_no) DO UPDATE SET
            remain_seat_cnt = EXCLUDED.remain_seat_cnt,
            station_id = EXCLUDED.station_id,
            station_seq = EXCLUDED.station_seq,
            extra = EXCLUDED.extra
        """,
        values,
    )
    return len(values)


async def save_locations(records: list[BusLocationRecord]) -> int:
    """현재 시각 기준으로 레코드 저장. 연결 생성/해제 포함."""
    collected_at = datetime.now(ZoneInfo("Asia/Seoul"))
    conn = await get_connection()
    try:
        return await insert_records(conn, records, collected_at)
    finally:
        await conn.close()
