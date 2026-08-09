# -*- coding: utf-8 -*-
"""ForexFactory 캘린더 수집기 — 예측(컨센서스) 전 지표 + ISM 2종.

이 피드가 이 프로젝트에서 유일하게 컨센서스를 주는 소스다.
계획 단계에서 실측으로 investing.com 과 같은 값임을 확인했다:
    Unemployment Claims 2026-07-30  forecast=201K previous=187K  (엑셀 U8/V8 과 일치)
    Federal Funds Rate  2026-07-29  forecast=3.75%               (엑셀 C7/D7 과 일치)

★ 결정적 제약 ★
    이 공식 피드에는 thisweek 만 존재한다. lastweek / nextweek 는 404 다.
    한때 이걸 두고 "놓친 주는 영원히 복구할 수 없다"고 전제했는데 **그건 사실이 아니다** —
    캘린더 HTML 의 `?week=mmmD.yyyy` 로 과거 주를 받을 수 있다(`calendar_ff_html`, mar1.2020 까지 확인).
    다만 그 복구는 `scripts/backfill_ff_weeks.py` 를 **사람이 판단해서 돌리는** 경로다.
    자동으로 메워지지 않으므로 놓치는 비용이 0은 아니다. 그래서 두 가지를 계속 지킨다.
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
from core.transform import quarter_key, shift_months

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

    if s.frequency == "quarterly":
        # 분기 지표는 분기가 끝난 뒤에 발표된다(2026 Q2 -> 7월 말 속보치).
        # 발표일이 속한 분기의 '직전 분기' 가 기준시점이다.
        this_q = quarter_key(d.isoformat())
        return quarter_key(shift_months(this_q, 3))

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
    # ★ 이 소스만 재시도를 길게 잡는다 ★
    #   ForexFactory 는 429(Too Many Requests)를 돌려주는데, 기본 재시도(2초·4초)로는
    #   레이트 리밋이 풀리기 전에 포기한다. 다른 소스는 실패해도 다음 실행에서
    #   똑같이 다시 받으면 그만이지만, **이 피드는 이번 주치만 제공한다.**
    #   놓친 주가 영구 손실은 아니다 — `?week=` 백필로 되찾을 수 있다(모듈 docstring 참고).
    #   하지만 그건 사람이 알아채고 스크립트를 돌려야 하는 경로라, 자동으로 받아 두는 것보다
    #   훨씬 비싸다. 그래서 예산은 그대로 길게 유지한다.
    #   실측한 쿨다운은 약 5분이었다. 20/40/60/80초(합 3.3분)로는 모자라
    #   30/60/90/120/150초(합 7.5분)로 잡는다. 하루 두 번 도는 작업에서
    #   최악 7.5분을 더 기다리는 비용은, 나중에 사람 손을 빌리는 것에 비하면 싸다.
    raw = http_get(FEED_URL, retries=6, backoff=30.0)
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
    """(국가, 이벤트명) -> 지표. 정식 이름·옛 이름·정기 변형을 모두 색인한다.

    ★ 변형(ff_variants)을 빠뜨리면 안 된다 ★
        calendar_ff_html 도 이 색인을 그대로 쓴다. 여기서 빠지면 HTML 경로에서
        미시간대 예비치 매칭이 조용히 끊긴다. 경고 여부는 collect() 가 가르지,
        색인이 가르지 않는다.
    """
    index: dict[tuple[str, str], Series] = {}
    for s in series_mod.ff_mapped_series():
        if not s.ff_title:
            continue
        for title in (s.ff_title, *s.ff_aliases, *s.ff_variants):
            index[(s.ff_country, title)] = s
    return index


def _canonical_titles() -> set[str]:
    """커버리지 보고에 쓸 정식 이름만. 별칭은 '없음' 경고 대상이 아니다."""
    return {s.ff_title for s in series_mod.ff_mapped_series() if s.ff_title}


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
    matched_ids: set[str] = set()

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

        # 별칭으로 잡혔을 수도 있으므로 제목이 아니라 지표 id 로 기록한다.
        matched_ids.add(s.id)
        # 옛 이름으로 잡힌 것만 알린다. 정기 변형(ff_variants)은 정상이라 알리지 않는다 —
        # 미시간대 예비치처럼 매월 오는 것에 경고를 달면 매번 울리고, 매번 울리면 안 본다.
        if title in s.ff_aliases:
            issues.append(f"'{s.name_ko}' 이 옛 이름 '{title}' 로 잡혔습니다 — "
                          f"ForexFactory 가 이벤트명을 바꿨을 수 있습니다")
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
    missing = sorted(
        s.ff_title for s in series_mod.ff_mapped_series()
        if s.ff_title and s.id not in matched_ids
    )
    if missing:
        issues.append("이번 주 피드에 없던 지표(발표주가 아니면 정상): " + ", ".join(missing))
        # ff_title 오타는 '조용히 예측이 안 잡히는' 형태로 나타나 발견이 어렵다.
        # 비슷한 제목이 **이번 주 피드에** 있으면 오타를 의심해야 하므로 눈에 띄게 알린다.
        feed_titles = sorted({
            t for ev in events
            if (t := (ev.get("title") or "").strip())
            and (ev.get("country") or "").strip() in ("USD", "KRW")
        })
        for warn in suggest_mappings(feed_titles, missing):
            issues.append(warn)

    return FetchResult(
        source=SOURCE,
        ok=True,
        rows=mapped,
        message=f"원본 {stored}건 저장, {mapped}건 지표 매핑",
        issues=issues,
    )


def remap_from_stored(conn, *, dry_run: bool = False, overwrite: bool = False) -> FetchResult:
    """이미 저장된 calendar_events 를 다시 매핑한다.

    ff_title 을 잘못 적었거나 ForexFactory 가 이벤트명을 바꿨을 때,
    이미 보관해 둔 원본으로 다시 매핑하는 경로다. (원본이 없는 주까지 되찾으려면
    `scripts/backfill_ff_weeks.py` 로 `?week=` 를 받아 온 뒤 이걸 돌린다.)
    아무 곳에서도 자동으로 부르지 않는다 — 사람이 판단해서 쓰는 복구 도구다.

    ★ 기본값은 '빈 칸만 채우기' 다 ★
        오랫동안 이 함수는 무해했다 — 공식 JSON 피드가 actual 을 주지 않고
        calendar_events 가 200행 남짓이었기 때문이다. 지금은 다르다.
        calendar_ff_html 이 실제값을 채우고 과거 주 백필로 15,000행이 쌓였다.
        그 상태에서 한 번 돌려 보니 **169건의 예측·이전이 덮였다** —
        엑셀에서 온 발표 당시 컨센서스가 지금 렌더링된 값으로 바뀐 것이고,
        `prune_excel_actuals.py` 의 "예측·이전은 절대 건드리지 않는다" 위반이다.
        게다가 실제값은 반올림된 헤드라인이라 FRED 정밀도가 깎인다(7.359 -> 7.36).

        정말로 덮어써야 할 때(= 매핑이 틀렸던 것이 확인됐을 때)만 overwrite=True.
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
        actual = to_series_unit(s.unit, parse_raw_number(r["actual_raw"]))
        forecast = to_series_unit(s.unit, parse_raw_number(r["forecast_raw"]))
        previous = to_series_unit(s.unit, parse_raw_number(r["previous_raw"]))

        if not overwrite:
            existing = conn.execute(
                "SELECT actual, forecast, previous FROM releases"
                " WHERE series_id = ? AND ref_date = ?",
                (s.id, ref_date),
            ).fetchone()
            if existing is not None:
                if existing["actual"] is not None:
                    actual = None
                if existing["forecast"] is not None:
                    forecast = None
                if existing["previous"] is not None:
                    previous = None
        if actual is None and forecast is None and previous is None:
            continue

        if not dry_run:
            db_mod.upsert_release(
                conn, s.id, ref_date,
                release_date=dt.isoformat(),
                actual=actual, forecast=forecast, previous=previous,
                source=SOURCE,
            )
        mapped += 1

    if not dry_run:
        conn.commit()
    return FetchResult(source=SOURCE + ":remap", ok=True, rows=mapped,
                       message=f"보관된 원본에서 {mapped}건 재매핑")


def suggest_mappings(feed_titles: list[str], missing_titles: list[str],
                     cutoff: float = 0.75) -> list[str]:
    """매칭 실패한 ff_title 에 대해 **이번 주 피드의** 유사 제목을 제안한다.

    ForexFactory 가 이벤트명을 바꾸면(과거에 'ISM Non-Manufacturing PMI' ->
    'ISM Services PMI' 처럼) 매칭이 조용히 끊기고, 공식 피드는 이번 주치만 주므로
    발견이 늦을수록 그 사이 컨센서스를 놓친다. 유사 제목을 들이대 즉시 알아채게 한다.

    ★ 후보는 반드시 '이번 주 피드'여야 한다 ★
        한때 `calendar_events` 전체를 후보로 썼다. 그 테이블이 200행 남짓일 때는 무해했지만
        과거 주 백필로 15,000행(USD/KRW 제목 127개)이 되자 매 실행 오탐이 터졌다 —
        'ISM Manufacturing PMI' 에 가격지불 하위지수인 'ISM Manufacturing Prices' 를,
        'Non-Farm Employment Change' 에 아예 다른 지표인 'ADP Non-Farm Employment Change' 를
        들이댔다. 셋 다 이력에 늘 있는 별개 이벤트라 영구히 울린다.

        개명은 정의상 **같은 주 안에서** '정식 이름이 사라지고 비슷한 새 이름이 나타나는' 모습이다.
        그러니 후보를 이번 주로 좁히면 탐지력은 그대로면서 오탐만 사라진다:
        ISM 발표가 없는 주에는 'ISM Manufacturing Prices' 도 피드에 없다.
    """
    import difflib

    pool = list(feed_titles)
    if not pool:
        return []

    # 이미 매핑된 이름(별칭 포함)은 제안 대상에서 뺀다.
    known = {t for (_c, t) in _title_index()}
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
