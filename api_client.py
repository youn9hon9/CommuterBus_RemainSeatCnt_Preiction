# -*- coding: utf-8 -*-
"""버스 위치 API 비동기 호출 및 응답 파싱."""

import asyncio
import json
import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import aiohttp

import config

logger = logging.getLogger(__name__)

# 토큰 초과 등으로 수집 중단할 때 사용하는 예외
class QuotaExceededError(Exception):
    """API 토큰 한도 초과 등으로 수집 중단."""


@dataclass
class BusLocationRecord:
    """DB에 저장할 버스 위치 레코드."""
    plate_no: str
    route_id: str
    remain_seat_cnt: str | None
    station_id: str | None
    station_seq: str | None
    extra: dict[str, Any] = field(default_factory=dict)


def _parse_json_body(data: dict[str, Any], route_id: str) -> tuple[list[BusLocationRecord], bool]:
    """
    JSON 응답에서 레코드 리스트 추출.
    반환: (레코드 목록, quota_exceeded 여부)
    """
    quota_exceeded = False
    records: list[BusLocationRecord] = []

    # 공공 API 공통: msgHeader / msgBody (직접 또는 response 래퍼 안)
    resp = data.get("response") or {}
    msg_header = data.get("msgHeader") or resp.get("msgHeader") or resp.get("header") or {}
    msg_body = data.get("msgBody") or resp.get("msgBody") or resp.get("body") or {}

    # 에러/한도 메시지 확인
    result_code = (
        str(msg_header.get("resultCode", "") or msg_header.get("resultCd", ""))
    ).strip()
    result_msg = (
        str(msg_header.get("resultMsg", "") or msg_header.get("returnAuthMsg", "") or msg_header.get("returnReasonCode", ""))
    ).lower()
    if "quota" in result_msg or "exceeded" in result_msg or "한도" in result_msg or "초과" in result_msg:
        quota_exceeded = True
    if result_code and result_code not in ("0", "00", "OK", "NORMAL"):
        if "quota" in result_msg or "exceeded" in result_msg or "한도" in result_msg:
            quota_exceeded = True

    # 목록 추출 (경기 버스 위치 API: msgBody.busLocationList / itemList / item)
    item_list = (
        msg_body.get("busLocationList")
        or msg_body.get("itemList")
        or msg_body.get("item")
    )
    if isinstance(item_list, dict):
        item_list = [item_list]
    if not isinstance(item_list, list):
        item_list = []

    for item in item_list:
        if not isinstance(item, dict):
            continue
        rec = BusLocationRecord(
            plate_no=str(item.get("plateNo") or item.get("plate_no") or ""),
            route_id=str(item.get("routeId") or item.get("route_id") or route_id),
            remain_seat_cnt=_str_or_none(item.get("remainSeatCnt") or item.get("remain_seat_cnt")),
            station_id=_str_or_none(item.get("stationId") or item.get("station_id")),
            station_seq=_str_or_none(item.get("stationSeq") or item.get("station_seq")),
            extra={k: v for k, v in item.items() if k not in (
                "plateNo", "plate_no", "routeId", "route_id",
                "remainSeatCnt", "remain_seat_cnt", "stationId", "station_id",
                "stationSeq", "station_seq"
            )},
        )
        records.append(rec)

    return records, quota_exceeded


def _str_or_none(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _parse_xml_body(text: str, route_id: str) -> tuple[list[BusLocationRecord], bool]:
    """
    XML 응답에서 레코드 리스트 추출.
    반환: (레코드 목록, quota_exceeded 여부)
    """
    quota_exceeded = False
    records: list[BusLocationRecord] = []

    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return records, quota_exceeded

    # 한도 초과 메시지 확인 (공통 헤더)
    for tag in root.iter():
        if tag.text and ("quota" in tag.text.lower() or "exceeded" in tag.text.lower() or "한도" in tag.text or "초과" in tag.text):
            quota_exceeded = True
        if tag.tag and ("resultCode" in tag.tag or "returnAuthMsg" in tag.tag):
            if tag.text and ("quota" in (tag.text or "").lower() or "exceeded" in (tag.text or "").lower() or "한도" in (tag.text or "")):
                quota_exceeded = True

    # item 또는 itemList 하위 항목
    def get_text(parent: ET.Element, *names: str) -> str:
        for name in names:
            el = parent.find(f".//{name}")
            if el is not None and el.text:
                return (el.text or "").strip()
        return ""

    def get_attr(e: ET.Element, key: str) -> str:
        return (e.get(key) or "").strip()

    items = root.findall(".//item") or root.findall(".//itemList/item")
    if not items:
        items = list(root.iter("item"))

    for item in items:
        if not isinstance(item, ET.Element):
            continue
        rec = BusLocationRecord(
            plate_no=get_text(item, "plateNo", "plate_no") or get_attr(item, "plateNo"),
            route_id=get_text(item, "routeId", "route_id") or route_id,
            remain_seat_cnt=_str_or_none(get_text(item, "remainSeatCnt", "remain_seat_cnt")) or None,
            station_id=_str_or_none(get_text(item, "stationId", "station_id")) or None,
            station_seq=_str_or_none(get_text(item, "stationSeq", "station_seq")) or None,
            extra={},
        )
        records.append(rec)

    return records, quota_exceeded


class ApiKeyRotator:
    """API 키 순환."""
    def __init__(self, keys: list[str]):
        self._keys = [k for k in keys if k]
        self._index = 0

    def get_next(self) -> str | None:
        if not self._keys:
            return None
        key = self._keys[self._index % len(self._keys)]
        self._index += 1
        return key


async def fetch_route_locations(
    session: aiohttp.ClientSession,
    route_id: str,
    service_key: str,
    fmt: str,
) -> tuple[list[BusLocationRecord], bool]:
    """
    한 노선에 대해 API 호출 후 파싱.
    반환: (레코드 목록, quota_exceeded 여부)
    """
    params = {
        "serviceKey": service_key,
        "routeId": route_id,
        "format": fmt,
    }
    url = f"{config.API_BASE_URL}?{urlencode(params)}"
    records: list[BusLocationRecord] = []
    quota_exceeded = False

    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            text = await resp.text()
            logger.debug(
                "routeId=%s HTTP %d, 응답 %d bytes",
                route_id, resp.status, len(text),
            )
            if resp.status != 200:
                if "quota" in text.lower() or "exceeded" in text.lower() or "한도" in text or "초과" in text:
                    quota_exceeded = True
                    logger.debug("routeId=%s 한도 초과 또는 에러 응답", route_id)
                return records, quota_exceeded

            if fmt == "json":
                try:
                    data = json.loads(text)
                    records, quota_exceeded = _parse_json_body(data, route_id)
                except json.JSONDecodeError as e:
                    logger.debug("routeId=%s JSON 파싱 실패: %s, 본문 앞 200자: %s", route_id, e, text[:200])
                    if "quota" in text.lower() or "exceeded" in text.lower() or "한도" in text:
                        quota_exceeded = True
            else:
                records, quota_exceeded = _parse_xml_body(text, route_id)

            logger.debug("routeId=%s 파싱 결과 %d건, quota_exceeded=%s", route_id, len(records), quota_exceeded)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.debug("routeId=%s 요청/파싱 오류: %s", route_id, e, exc_info=True)

    return records, quota_exceeded


async def fetch_all_routes(
    route_ids: list[str],
    key_rotator: ApiKeyRotator,
) -> tuple[list[BusLocationRecord], bool]:
    """
    5개 노선 동시 요청.
    반환: (전체 레코드 목록, quota_exceeded 발생 여부)
    """
    fmt = config.API_FORMAT
    all_records: list[BusLocationRecord] = []
    any_quota_exceeded = False

    async with aiohttp.ClientSession() as session:
        tasks = []
        keys_used = []
        for rid in route_ids:
            key = key_rotator.get_next()
            if not key:
                break
            keys_used.append((rid, key))
            tasks.append(fetch_route_locations(session, rid, key, fmt))

        if not tasks:
            return all_records, True

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            rid = route_ids[i] if i < len(route_ids) else "?"
            if isinstance(res, Exception):
                if isinstance(res, QuotaExceededError):
                    any_quota_exceeded = True
                logger.debug("routeId=%s 예외: %s", rid, res)
                continue
            recs, qe = res
            all_records.extend(recs)
            if qe:
                any_quota_exceeded = True

    logger.debug("전체 %d개 노선 요청, 총 %d건 수집", len(route_ids), len(all_records))
    return all_records, any_quota_exceeded
