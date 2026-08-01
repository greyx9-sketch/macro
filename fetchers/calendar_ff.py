# -*- coding: utf-8 -*-
"""ForexFactory 캘린더 수집기 — 예측(컨센서스) 전 지표 + ISM 2종.

이 피드가 이 프로젝트에서 유일하게 컨센서스를 주는 소스다.
계획 단계에서 실측으로 investing.com 과 같은 값임을 확인했다:
    Unemployment Claims 2026-07-30  forecast=201K previous=187K  (엑셀 U8/V8 과 일치)
    Federal Funds Rate  2026-07-29  forecast=3.75%               (엑셀 C7/D7 과 일치)

★ 결정적 제약 ★
    thisweek 만 존재한다. lastweek / nextweek 는 404 다.
    즉 **놓친 주는 영원히 복구할 수 없다.**
    그래서 두 가지를 지킨다.
      1) 매핑 성공 여부와 무관하게 원본 이벤트를 calendar_events 에 전량 먼저 저장한다.
         나중에 매핑이 틀렸다고 판명나도 원본이 남아 있으면 고칠 수 있다.
      2) 매일 수집한다. 주 5회 중복 캡처로 하루이틀 장애를 흡수한다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from typing import Optional

from core import db as db_mod
from core import series as series_mod
from core.series import Series
from core.transform import shift_months

from .base import FetchResult, guarded, http_get, parse_raw_number, to_series_unit

FEED_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
SOURCE = "forexfactory"


# ---------------------------------------------------------------------------
# 기준시점 역산
# ---------------------------------------------------------------------------
def derive_ref_date(s: Series, release_dt: datetime) -> str:
    """발표 시각으로부터 그 발표가 가리키는 기준시점을 구한다.

    엑셀의 (발표월, 기준월) 쌍이 근거다:
        NFP    발표 2026-08 / 기준 2026-07  -> lag 1
        JOLTS  발표 2026-08 / 기준 2026-06  -> lag 2
        주간 청구  발표 2026-07-23(목) -> 직전 토요일로 끝나는 주
        FOMC/금통위 발표일 자체가 기준시점
    """
    d = release_dt.date()

    if s.frequency == "monthly":
        return shift_months(f"{d.year:04d}-{d.month:02d}-01", s.ref_lag_months)

    if s.frequency == "weekly":
        # FRED ICSA 의 기준시점은 '토요일로 끝나는 주'.
        # 목요일 발표는 직전 토요일까지의 주를 대상으로 한다.
        # weekday(): 월=0 … 토=5. 발표일보다 앞선 가장 가까운 토요일을 찾는다.
        days_back = (d.weekday() - 5) % 7
        if days_back == 0:
            days_back = 7
        return (d - timedelta(days=days_back)).isoformat()

    # daily / event
    return d.isoformat()


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def fetch_feed() -> list[dict]:
    raw = http_get(FEED_URL)
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError(f"캘린더 피드 형식이 예상과 다름: {type(data).__name__}")
    return data


def _parse_event_time(value: str) -> Optional[datetime]:
    """'2026-07-30T08:30:00-04:00' 파싱. 형식이 바뀌면 조용히 넘기지 않고 None."""
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _title_index() -> dict[tuple[str, str], Series]:
    return {
        (s.ff_country, s.ff_title): s
        for s in series_mod.ff_mapped_series()
        if s.ff_title
    }


@guarded(SOURCE)
def collect(conn, *, dry_run: bool = False) -> FetchResult:
    events = fetch_feed()

    # --- 1단계: 원본 전량 저장 (매핑보다 먼저) -----------------------------
    stored = 0
    for ev in events:
        title = (ev.get("title") or "").strip()
        country = (ev.get("country") or "").strip()
        etime = (ev.get("date") or "").strip()
        if not title or not country or not etime:
            continue
        if not dry_run:
            db_mod.upsert_calendar_event(
                conn,
                title=title,
                country=country,
                event_time=etime,
                impact=ev.get("impact"),
                actual_raw=ev.get("actual"),
                forecast_raw=ev.get("forecast"),
                previous_raw=ev.get("previous"),
            )
        stored += 1
    if not dry_run:
        conn.commit()

    # --- 2단계: 아는 지표에만 매핑 ----------------------------------------
    index = _title_index()
    mapped = 0
    issues: list[str] = []
    matched_titles: set[str] = set()

    for ev in events:
        title = (ev.get("title") or "").strip()
        country = (ev.get("country") or "").strip()
        s = index.get((country, title))
        if s is None:
            continue

        dt = _parse_event_time(ev.get("date", ""))
        if dt is None:
            issues.append(f"{title}: 발표시각 파싱 실패 ({ev.get('date')!r})")
            continue

        matched_titles.add(title)
        ref_date = derive_ref_date(s, dt)

        actual = to_series_unit(s.unit, parse_raw_number(ev.get("actual")))
        forecast = to_series_unit(s.unit, parse_raw_number(ev.get("forecast")))
        previous = to_series_unit(s.unit, parse_raw_number(ev.get("previous")))

        if actual is None and forecast is None and previous is None:
            # 발표 예정만 있고 숫자가 아직 없는 이벤트. 발표일만 기록해 둔다.
            if not dry_run:
                db_mod.upsert_release(
                    conn, s.id, ref_date, release_date=dt.isoformat(), source=SOURCE
                )
            continue

        if not dry_run:
            db_mod.upsert_release(
                conn,
                s.id,
                ref_date,
                release_date=dt.isoformat(),
                actual=actual,
                forecast=forecast,
                previous=previous,
                source=SOURCE,
            )
        mapped += 1

    if not dry_run:
        conn.commit()

    # --- 커버리지 보고 -----------------------------------------------------
    # ISM 은 매월 1·3영업일에만 나오므로 '이번 주에 없음'이 정상일 수 있다.
    # 그래도 무엇이 안 잡혔는지는 남겨야 나중에 매핑 오류를 발견할 수 있다.
    expected = {t for (_c, t) in index}
    missing = sorted(expected - matched_titles)
    if missing:
        issues.append("이번 주 피드에 없던 지표(발표주가 아니면 정상): " + ", ".join(missing))
        # ff_title 오타는 '조용히 영원히 예측이 안 잡히는' 형태로 나타나 발견이 어렵다.
        # 비슷한 제목이 피드에 있으면 오타를 의심해야 하므로 눈에 띄게 알린다.
        for warn in suggest_mappings(conn, missing):
            issues.append(warn)

    return FetchResult(
        source=SOURCE,
        ok=True,
        rows=mapped,
        message=f"원본 {stored}건 저장, {mapped}건 지표 매핑",
        issues=issues,
    )


def remap_from_stored(conn, *, dry_run: bool = False) -> FetchResult:
    """이미 저장된 calendar_events 를 다시 매핑한다.

    ff_title 을 잘못 적었거나 ForexFactory 가 이벤트명을 바꿨을 때,
    과거 데이터를 다시 받을 수 없으므로 보관해 둔 원본으로 복구하는 경로다.
    """
    index = _title_index()
    rows = conn.execute(
        "SELECT title, country, event_time, actual_raw, forecast_raw, previous_raw"
        " FROM calendar_events"
    ).fetchall()

    mapped = 0
    for r in rows:
        s = index.get((r["country"], r["title"]))
        if s is None:
            continue
        dt = _parse_event_time(r["event_time"])
        if dt is None:
            continue
        ref_date = derive_ref_date(s, dt)
        if not dry_run:
            db_mod.upsert_release(
                conn,
                s.id,
                ref_date,
                release_date=dt.isoformat(),
                actual=to_series_unit(s.unit, parse_raw_number(r["actual_raw"])),
                forecast=to_series_unit(s.unit, parse_raw_number(r["forecast_raw"])),
                previous=to_series_unit(s.unit, parse_raw_number(r["previous_raw"])),
                source=SOURCE,
            )
        mapped += 1

    if not dry_run:
        conn.commit()
    return FetchResult(source=SOURCE + ":remap", ok=True, rows=mapped,
                       message=f"보관된 원본에서 {mapped}건 재매핑")


def suggest_mappings(conn, missing_titles: list[str], cutoff: float = 0.75) -> list[str]:
    """매칭 실패한 ff_title 에 대해 피드의 유사 제목을 제안한다.

    ForexFactory 가 이벤트명을 바꾸면(과거에 'ISM Non-Manufacturing PMI' ->
    'ISM Services PMI' 처럼) 매칭이 조용히 끊기고, 피드는 지난 주를 다시 주지 않으므로
    발견이 늦을수록 손실이 크다. 유사 제목을 들이대 즉시 알아채게 한다.
    """
    import difflib

    rows = conn.execute(
        "SELECT DISTINCT country, title FROM calendar_events WHERE country IN ('USD','KRW')"
    ).fetchall()
    pool = [r["title"] for r in rows]
    if not pool:
        return []

    known = {s.ff_title for s in series_mod.ff_mapped_series() if s.ff_title}
    out: list[str] = []
    for title in missing_titles:
        close = [
            c for c in difflib.get_close_matches(title, pool, n=2, cutoff=cutoff)
            if c not in known
        ]
        if close:
            out.append(
                f"⚠ ff_title 확인 필요 — '{title}' 은 못 찾았지만 피드에 비슷한 제목이 있음: "
                + ", ".join(repr(c) for c in close)
            )
    return out


def unmapped_titles(conn, limit: int = 40) -> list[tuple[str, str, int]]:
    """매핑되지 않은 이벤트 제목 목록 — ff_title 오타를 찾는 데 쓴다."""
    index = _title_index()
    rows = conn.execute(
        "SELECT country, title, COUNT(*) AS n FROM calendar_events"
        " GROUP BY country, title ORDER BY n DESC"
    ).fetchall()
    out = []
    for r in rows:
        if (r["country"], r["title"]) in index:
            continue
        out.append((r["country"], r["title"], r["n"]))
        if len(out) >= limit:
            break
    return out
