# -*- coding: utf-8 -*-
"""한국은행 ECOS 수집기 — 한국 기준금리.

통계표 722Y001 / 주기 D / 항목 0101000 = 한국은행 기준금리.
응답 단위는 연 % (예: '2.75') 이므로 100 으로 나눠 비율로 저장한다.
엑셀 금융시트 I8=0.0275 와 같은 규약이다.

일별 계열을 받아 **값이 바뀌는 시점**을 금통위 결정으로 간주해 releases 에 기록한다.
ECOS 가 '결정일' 자체를 주지는 않지만 기준금리는 결정 즉시 반영되므로
변화 시점이 곧 결정일이다.

★ 요청은 증분이다 ★
    예전에는 매 실행마다 `20000101~20991231` 전 구간(9,700여 행)을 다시 받았다.
    이미 갖고 있는 값을 매번 다시 받는 것도 낭비지만, 진짜 문제는 **실패율**이었다 —
    2026-08-04 이후 24회 중 4회가 같은 요청에서 타임아웃했고, 한 번 실패할 때마다
    재시도 5회 × 백오프 10초로 6분 40초를 쓰고 0행으로 끝났다.
    그동안 사이트에는 빨간 실패 배너가 떴다.

    지금은 저장된 마지막 관측일에서 겹침 구간만큼만 되돌려 오늘까지를 받는다.
    응답이 9,700행에서 수십 행으로 줄어 타임아웃 확률이 크게 내려간다.
    전체를 다시 받아야 하면 `ECOS_FULL_HISTORY=1` 을 준다(첫 실행은 자동으로 전체).
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from core import db as db_mod
from core.series import BY_ID

from .base import FetchError, FetchResult, guarded, http_get

BASE = "https://ecos.bok.or.kr/api/StatisticSearch"
SOURCE = "ecos"
SERIES_ID = "bok_base_rate"
CHUNK = 10000

# 이력의 시작. 엑셀 금융시트가 2000년부터라 그 앞은 볼 이유가 없다.
FIRST_DAY = "20000101"

# 증분 요청이 되돌아가는 폭. 기준금리는 개정되지 않으므로 큰 값이 필요 없다.
# 그래도 0 이 아닌 이유는 실행이 며칠 밀리거나 ECOS 반영이 늦는 경우를 흡수하기 위해서다.
OVERLAP_DAYS = 30

# ECOS 는 한국 기관이고 TIME 이 KST 날짜다. UTC 로 끝을 잡으면 하루가 빌 수 있다.
KST = timezone(timedelta(hours=9))


def api_key() -> str:
    key = os.environ.get("ECOS_API_KEY", "").strip()
    if not key:
        raise FetchError(
            "ECOS_API_KEY 환경변수가 없습니다. "
            "https://ecos.bok.or.kr/api/ 에서 무료 발급하세요(승인까지 최대 1일)."
        )
    return key


def request_window(conn, *, full: bool = False) -> tuple[str, str, bool]:
    """(start, end, 전체수집인가). YYYYMMDD.

    저장된 값이 없으면 전체를 받는다 — 첫 실행이거나 DB 를 새로 만든 경우다.
    """
    end = datetime.now(KST).date().strftime("%Y%m%d")
    if full:
        return FIRST_DAY, end, True

    row = conn.execute(
        "SELECT MAX(ref_date) AS m FROM observations WHERE series_id = ?", (SERIES_ID,)
    ).fetchone()
    latest = row["m"] if row else None
    if not latest:
        return FIRST_DAY, end, True

    start = date.fromisoformat(latest[:10]) - timedelta(days=OVERLAP_DAYS)
    return start.strftime("%Y%m%d"), end, False


def _seed_previous(conn, start_iso: str) -> Optional[float]:
    """증분 창이 시작되기 **직전**의 저장된 값.

    ★ 이걸 빠뜨리면 가짜 금통위가 생긴다 ★
      아래 releases 기록은 `prev_value` 와 달라질 때마다 '금리 변경'으로 친다.
      `None` 에서 시작하면 창의 **첫 점이 언제나 변경으로 잡혀**, 금통위가 열리지도 않은
      날에 발표 행이 하나 생긴다. 전체 수집일 때만 None 에서 시작해야 맞다.
    """
    row = conn.execute(
        "SELECT value FROM observations"
        " WHERE series_id = ? AND ref_date < ? ORDER BY ref_date DESC LIMIT 1",
        (SERIES_ID, start_iso),
    ).fetchone()
    return row["value"] if row else None


def fetch_rows(start: str, end: str) -> list[dict]:
    """(TIME, DATA_VALUE) 목록. TIME 은 YYYYMMDD.

    구간은 **반드시 호출자가 정한다.** 예전에는 `20991231` 이 기본값이었는데,
    73년 뒤까지 훑게 하는 기본값을 남겨 두면 누군가 인자 없이 부르는 순간
    §-1-1 에서 고친 문제가 조용히 되살아난다. `request_window()` 를 쓸 것.
    """
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
        # ForexFactory 만큼 길게 잡을 필요는 없다 — 그쪽은 놓치면 사람이 백필을 돌려야 하지만
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

    full = os.environ.get("ECOS_FULL_HISTORY", "").strip() not in ("", "0")
    start, end, is_full = request_window(conn, full=full)
    rows = fetch_rows(start, end)

    if not rows:
        # 전체 수집인데 비었다면 진짜 이상이다. 증분에서 비는 것은 흔한 일이다 —
        # 주말·연휴에는 새 일자가 없다. 그걸 실패로 세면 사이트에 상시 빨간 배너가 뜬다.
        if is_full:
            return FetchResult(SOURCE, ok=False, message="ECOS 응답에 데이터가 없음")
        return FetchResult(
            SOURCE, ok=True, rows=0,
            message=f"새 값 없음 ({start}~{end})",
        )

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
    prev_value: Optional[float] = None if is_full else _seed_previous(conn, points[0][0])
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

    # 이 실행에서 받은 건수만 적으면 '9,715 → 31' 이 수집 축소로 오해된다.
    # 누적을 함께 적어 창이 좁아진 것뿐임을 로그만 보고도 알 수 있게 한다.
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM observations WHERE series_id = ?", (SERIES_ID,)
    ).fetchone()["n"]
    scope = "전체" if is_full else f"{start}~{end}"
    return FetchResult(
        SOURCE, ok=True, rows=n_obs,
        message=f"관측치 {n_obs}건({scope}), 누적 {total}건, 금리 변경 {n_rel}회",
        issues=issues,
    )
