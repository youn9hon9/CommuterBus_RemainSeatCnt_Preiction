# -*- coding: utf-8 -*-
"""DB 테이블 생성(초기화) 전용. 수집기 실행 없이 테이블만 만들 때 사용."""

import asyncio
import config
from db import TABLE_NAME, get_connection, init_db


async def _main() -> None:
    conn = await get_connection()
    try:
        await init_db(conn)
        await conn.execute(f"TRUNCATE TABLE {TABLE_NAME}")
        print("테이블 초기화 완료 (기존 데이터 삭제됨).")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(_main())
