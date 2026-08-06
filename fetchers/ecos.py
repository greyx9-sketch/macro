# -*- coding: utf-8 -*-
"""한국은행 ECOS 수집기 — 한국 기준금리.

통계표 722Y001 / 주기 D / 항목 0101000 = 한국은행 기준금리.
응답 단위는 연 % (예: '2.75') 이므로 100 으로 나눠 비율로 저장한다.
엑셀 금융시트 I8=0.0275 와 같은 규약이다.

일별 계열을 받아 **값이 바뀌는 시점**을 금통위 결정으로 간주해 releases 에 기록한다.
ECOS 가 '결정일' 자체를 주지는 않지만 기준금리는 결정 즉시 반영되므로
변화 시점이 곧 결정일이다.
"""

from __future__ import annotations

import json
import os
from typing import Optional

from core import db as db_mod
from core.series import BY_ID

from .base import FetchError, FetchResult, guarded, http_get

BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
SOURCE = "ecos"
SERIES_ID = "bok_base_rate"
CHUNK = 10000


def api_key() -> str:
    key = os.environ.get("ECOS_API_KEY", "").strip()
    if not key:
        raise FetchError(
            "ECOS_API_KEY 환경변수가 없습니다. "
            "https://ecos.bok.or.kr/api/ 에서 무료 발급하세요(승인까지 최대 1일)."
        )
    return key


def fetch_rows(start: str = "20000101", end: str = "20991231") -> list[dict]:
    """(TIME, DATA_VALUE) 목록. TIME 은 YYYYMMDD."""
    s = BY_ID[SERIES_ID]
    if not s.ecos_stat:
        raise FetchError(f"{SERIES_ID} 에 ecos_stat 정의가 없음")
    stat, cycle, item = s.ecos_stat
    key = api_key()

    out: list[dict] = []
    start_row = 1
    while True:
        end_row = start_row + CHUNK - 1
        url = f"{BASE}/{key}/json/kr/{start_row}/{end_row}/{stat}/{cycle}/{start}/{end}/{item}"
        # 기본값(30초·3회·2초 백오프)으로는 실제로 타임아웃이 났다.
        # ForexFactory 만큼 길게 잡을 필요는 없다 — 그쪽은 놓치면 영구 손실이지만
        # ECOS 는 과거 데이터를 언제든 다시 준다. 다만 한국 정부 API 는 느린 편이라
        # 한 번의 일시적 지연으로 하루치를 날리지 않을 만큼은 기다린다.
        payload = json.loads(http_get(url, retries=5, backoff=10.0, timeout=60))

        if "RESULT" in payload:
            code = payload["RESULT"].get("CODE", "")
            msg = payload["RESULT"].get("MESSAGE", "")
            if code == "INFO-200":  # 데이터 없음 — 끝에 도달
                break
            raise FetchError(f"ECOS {code}: {msg}")

        block = payload.get("StatisticSearch", {})
        rows = block.get("row", [])
        out.extend(rows)

        total = int(block.get("list_total_count", len(out)))
        if len(out) >= total or not rows:
            break
        start_row = end_row + 1

    return out


def _to_iso(time_str: str) -> Optional[str]:
    t = (time_str or "").strip()
    if len(t) == 8:
        return f"{t[:4]}-{t[4:6]}-{t[6:8]}"
    if len(t) == 6:  # 월간 응답이 섞여 오는 경우
        return f"{t[:4]}-{t[4:6]}-01"
    return None


@guarded(SOURCE)
def collect(conn, *, dry_run: bool = False) -> FetchResult:
    s = BY_ID[SERIES_ID]
    rows = fetch_rows()
    if not rows:
        return FetchResult(SOURCE, ok=False, message="ECOS 응답에 데이터가 없음")

    points: list[tuple[str, float]] = []
    bad = 0
    for r in rows:
        iso = _to_iso(r.get("TIME", ""))
        raw = r.get("DATA_VALUE")
        if iso is None or raw in (None, ""):
            bad += 1
            continue
        try:
            points.append((iso, float(raw) / 100.0))  # 연% -> 비율
        except ValueError:
            bad += 1

    points.sort()

    n_obs = 0
    for iso, value in points:
        if not dry_run:
            db_mod.upsert_observation(conn, s.id, iso, value, SOURCE)
        n_obs += 1

    # 값이 바뀐 시점 = 금통위 결정. 엑셀의 '실제 / 이전(수정)' 쌍에 대응한다.
    n_rel = 0
    prev_value: Optional[float] = None
    for iso, value in points:
        if prev_value is None or abs(value - prev_value) > 1e-12:
            if not dry_run:
                db_mod.upsert_release(
                    conn, s.id, iso,
                    release_date=iso,
                    actual=value,
                    previous=prev_value,
                    source=SOURCE,
                )
            n_rel += 1
        prev_value = value

    if not dry_run:
        conn.commit()

    issues = [f"해석 불가 행 {bad}건"] if bad else []
    return FetchResult(
        SOURCE, ok=True, rows=n_obs,
        message=f"관측치 {n_obs}건, 금리 변경 {n_rel}회",
        issues=issues,
    )
