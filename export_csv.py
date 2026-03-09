# -*- coding: utf-8 -*-
"""
버스 위치 DB 데이터를 CSV로 내보내기.

사용법:
  python export_csv.py
  python export_csv.py --startdate 20260301 --enddate 20260309
  python export_csv.py --limit 1000
"""

import argparse
import asyncio
import csv
import json
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from db import TABLE_NAME, get_connection

DATA_DIR = Path(__file__).resolve().parent / "data"
KST = ZoneInfo("Asia/Seoul")


def _format_time_kst(val) -> str:
    """datetime을 KST 기준 'YYYY-MM-DD HH:MM:SS' 문자열로 통일."""
    if val is None:
        return ""
    if not isinstance(val, datetime):
        return str(val)
    if val.tzinfo is None:
        # naive면 KST로 간주하고 그대로 포맷
        return val.strftime("%Y-%m-%d %H:%M:%S")
    # aware면 KST로 변환 후 포맷
    kst = val.astimezone(KST)
    return kst.strftime("%Y-%m-%d %H:%M:%S")


def _parse_date(s: str) -> date:
    """YYYYMMDD 8자리 파싱. 8자리가 아니면 ValueError."""
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        raise ValueError("날짜는 8자리(YYYYMMDD)로 입력해 주세요. 예: 20260301")
    return datetime.strptime(s, "%Y%m%d").date()


async def export_to_csv(
    output_path: Path,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
) -> int:
    """bus_location 테이블을 CSV로 내보냄. 반환: 내보낸 행 수."""
    conn = await get_connection()
    try:
        sql = f"SELECT time, plate_no, route_id, remain_seat_cnt, station_id, station_seq, extra FROM {TABLE_NAME}"
        params: list = []
        conditions = []
        if start_date is not None:
            params.append(start_date)
            conditions.append(f"(time::date >= ${len(params)})")
        if end_date is not None:
            params.append(end_date)
            conditions.append(f"(time::date <= ${len(params)})")
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY time ASC"
        if limit is not None:
            sql += f" LIMIT {limit}"
        rows = await conn.fetch(sql, *params) if params else await conn.fetch(sql)

        columns = ["time", "plate_no", "route_id", "remain_seat_cnt", "station_id", "station_seq", "extra"]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            for row in rows:
                values = []
                for c in columns:
                    val = row[c]
                    if c == "time":
                        values.append(_format_time_kst(val))
                    elif c == "extra" and val is not None:
                        values.append(json.dumps(val, ensure_ascii=False))
                    else:
                        values.append("" if val is None else str(val))
                writer.writerow(values)

        return len(rows)
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="버스 위치 DB를 CSV로 내보내기")
    parser.add_argument("--startdate", type=str, default=None, metavar="YYYYMMDD", help="시작 날짜 8자리 (포함)")
    parser.add_argument("--enddate", type=str, default=None, metavar="YYYYMMDD", help="끝 날짜 8자리 (포함)")
    parser.add_argument("--limit", type=int, default=None, help="내보낼 최대 행 수 (미지정 시 전체)")
    args = parser.parse_args()

    today = date.today()
    today_6 = today.strftime("%Y%m%d")

    try:
        start_d = _parse_date(args.startdate) if args.startdate else None
        end_d = _parse_date(args.enddate) if args.enddate else None
    except ValueError as e:
        print(f"날짜 형식 오류: {e}")
        sys.exit(1)

    if start_d is not None and end_d is not None:
        filename = f"bus_location_{start_d:%Y%m%d}_{end_d:%Y%m%d}.csv"
    elif start_d is not None:
        filename = f"bus_location_{start_d:%Y%m%d}_to_{today_6}.csv"
    elif end_d is not None:
        filename = f"bus_location_to_{end_d:%Y%m%d}.csv"
    else:
        filename = f"bus_location_{today_6}.csv"

    output_path = DATA_DIR / filename
    count = asyncio.run(export_to_csv(output_path, start_date=start_d, end_date=end_d, limit=args.limit))
    print(f"{count}건 내보냄: {output_path.resolve()}")


if __name__ == "__main__":
    main()
