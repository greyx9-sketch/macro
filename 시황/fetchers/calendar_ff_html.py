# -*- coding: utf-8 -*-
"""ForexFactory 캘린더 **HTML** 수집기 — 실제값(actual) 보충 전용.

왜 이게 필요한가
----------------
공식 피드(`ff_calendar_thisweek.json`)는 **actual 을 아예 주지 않는다.**
실측으로 확인했다 — 99건 중 actual 이 있는 것 0건, XML 판에는 `<actual>` 엘리먼트
자체가 없다. 예측(forecast)·이전(previous)만 주는 예고용 피드다.

문제는 ISM 2종이다. ISM 은 라이선스 정책상 FRED 에 없어(`fred_id=None`)
이 피드가 유일한 실제값 경로였다. 즉 **구조적으로 영원히 안 들어왔다.**
프로젝트 시작 이래 ISM 관측치 22건은 전부 엑셀 백필이었고,
2026-07 분(제조업 8/03, 서비스업 8/05 발표)은 며칠이 지나도 비어 있었다.

캘린더 **웹페이지**에는 있다. 페이지 안에 `window.calendarComponentStates[N]` 이
있고 그 `days` 배열이 공식 피드의 상위집합이다 — actual 과 revision 까지 들어 있다.

    2026-08-03T14:00Z  ISM Manufacturing PMI  A='55.6' F='54.0' P='53.3'
    2026-08-06T12:30Z  Unemployment Claims    A='199K' F='203K' P='197K' rev='198K'

파서 정합성은 두 가지로 교차 검증했다.
  - 청구건수 199K == FRED ICSA 의 2026-08-01 = 199000
  - ?week=jul6.2026 의 ISM 서비스업 (54.0 / 54.2 / 54.5) == 엑셀 백필 2026-06 과 3값 일치

★ 이것은 공식 피드를 **대체하지 않는다** ★
    예측·이전의 주소스는 계속 `calendar_ff.py` 다. 여기는 빈 칸만 메운다.
    한 값을 두 소스가 각자 계산하기 시작하면 언젠가 갈린다.
    저장은 `upsert_release` 를 쓰므로 **빈 값이 기존 값을 덮지 않는다.**

★ 스크레이핑이라는 사실을 숨기지 않는다 ★
    ForexFactory 앞에는 Cloudflare 가 있다(robots.txt 조차 챌린지를 돌려준다).
    집 IP 에서는 평문 GET 이 통과했지만 GitHub Actions 데이터센터 IP 에서도
    통과한다는 보장은 없다. 그래서
      1) 평문 GET → 2) Playwright 렌더링(cds.py 와 같은 패턴) → 3) 명확한 실패
    로 3단을 두고, **챌린지 페이지를 성공으로 세지 않는다.**
    HTTP 200 을 받았다고 통과한 걸로 치면 '0건 매핑' 이 정상처럼 보인다.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from core import db as db_mod

from .base import FetchResult, guarded, http_get, parse_raw_number, to_series_unit
from .calendar_ff import SOURCE as FF_SOURCE
from .calendar_ff import _title_index, derive_ref_date

SOURCE = "forexfactory_html"

BASE_URL = "https://www.forexfactory.com/calendar"
NAV_TIMEOUT_MS = 45_000

# 브라우저처럼 보이지 않으면 곧바로 챌린지로 넘어간다.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

# 차단 판정은 **좁게** 잡아야 한다.
# 처음에 'challenge-platform' 을 넣었다가 멀쩡한 응답을 전부 차단으로 오판했다 —
# 그 문자열은 Cloudflare 가 모든 페이지에 심는 수동 탐지 스크립트 경로
# (/cdn-cgi/challenge-platform/scripts/jsd/main.js)라 정상 페이지에도 늘 있다.
# 아래 둘은 인터스티셜에만 나온다.
_CHALLENGE_MARKERS = ("cf_chl_opt", "Just a moment...")

# 진짜 성공 판정은 이것이다 — 데이터 블롭이 실제로 있는가.
_BLOB_MARKER = "window.calendarComponentStates"


# ---------------------------------------------------------------------------
# 미 동부 시간
#
# zoneinfo 를 쓰지 않는다. Windows 에는 시스템 tz 데이터베이스가 없어
# `pip install tzdata` 가 필요한데, 이 프로젝트의 필수 의존성은 openpyxl 하나뿐이고
# 그 원칙 때문에 requests 도 안 쓴다. 규칙은 2007년 이후 바뀐 적이 없고
# 우리 데이터는 2020년부터라 직접 계산해도 안전하다.
#
# 왜 UTC 로 두면 안 되는가: ForexFactory 는 동부 시간 기준으로 날짜를 나누고,
# 공식 피드도 '-04:00' 오프셋 시각을 준다. 예컨대 20:30 ET 발표는 UTC 로는
# 다음 날이 되어 `derive_ref_date` 의 기준시점 역산이 한 달 어긋난다.
# ---------------------------------------------------------------------------
def _nth_weekday(year: int, month: int, weekday: int, n: int) -> datetime:
    """그 달의 n번째 `weekday`(월=0…일=6) 00:00 UTC."""
    d = datetime(year, month, 1, tzinfo=timezone.utc)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _eastern_offset(utc_dt: datetime) -> timedelta:
    """그 시각의 미 동부 오프셋. EDT(-4) 또는 EST(-5).

    서머타임: 3월 둘째 일요일 02:00 EST(=07:00 UTC) ~ 11월 첫째 일요일 02:00 EDT(=06:00 UTC).
    """
    y = utc_dt.year
    start = _nth_weekday(y, 3, 6, 2) + timedelta(hours=7)   # 일요일=6
    end = _nth_weekday(y, 11, 6, 1) + timedelta(hours=6)
    return timedelta(hours=-4) if start <= utc_dt < end else timedelta(hours=-5)


def to_eastern(ts: float) -> datetime:
    """유닉스 초 -> 미 동부 시각(오프셋 포함)."""
    utc = datetime.fromtimestamp(ts, timezone.utc)
    off = _eastern_offset(utc)
    return utc.astimezone(timezone(off))


class BlockedError(RuntimeError):
    """봇 차단 페이지를 받았다 — 값이 없다는 뜻이 아니라 물어보지 못했다는 뜻이다."""


def _looks_blocked(html: str) -> bool:
    return any(m in html for m in _CHALLENGE_MARKERS)


def _has_blob(html: str) -> bool:
    return _BLOB_MARKER in html


# ---------------------------------------------------------------------------
# 파싱
# ---------------------------------------------------------------------------
def week_token(d: "datetime | Any") -> str:
    """'2026-08-03' -> 'aug3.2026'. ?week= 파라미터 형식."""
    return f"{d.strftime('%b').lower()}{d.day}.{d.year}"


def parse_days(html: str) -> list[dict]:
    """`window.calendarComponentStates[N] = { days: [...] }` 에서 days 배열만 꺼낸다.

    **통째로 json.loads 하면 깨진다.** 최상위가 JS 객체 리터럴이라 `days` 키에
    따옴표가 없다. `days:` 뒤에서부터 raw_decode 로 배열 하나만 읽는다.
    """
    i = html.find(_BLOB_MARKER)
    if i < 0:
        # 블롭이 없을 때에만 차단인지 구조 변경인지를 가른다. 둘은 대응이 다르다 —
        # 차단은 렌더링으로 재시도할 여지가 있고, 구조 변경은 코드를 고쳐야 한다.
        if _looks_blocked(html):
            raise BlockedError("Cloudflare 챌린지 페이지를 받았습니다")
        raise ValueError(
            f"{_BLOB_MARKER} 를 찾지 못했습니다 — 페이지 구조가 바뀌었을 수 있습니다"
        )
    j = html.find("days:", i)
    if j < 0:
        raise ValueError("days 배열을 찾지 못했습니다 — 페이지 구조가 바뀌었을 수 있습니다")

    tail = html[j + len("days:"):].lstrip()
    days, _end = json.JSONDecoder().raw_decode(tail)
    if not isinstance(days, list):
        raise ValueError(f"days 가 배열이 아닙니다: {type(days).__name__}")
    return days


def iter_events(days: list[dict]):
    """(발표시각 datetime[ET], 통화, 이벤트명, actual, forecast, previous, revision)."""
    for day in days:
        for ev in day.get("events", []) or []:
            ts = ev.get("dateline")
            name = (ev.get("name") or "").strip()
            cur = (ev.get("currency") or "").strip()
            if not isinstance(ts, (int, float)) or not name or not cur:
                continue
            dt = to_eastern(ts)
            yield (
                dt, cur, name,
                (ev.get("actual") or "").strip() or None,
                (ev.get("forecast") or "").strip() or None,
                (ev.get("previous") or "").strip() or None,
                (ev.get("revision") or "").strip() or None,
            )


# ---------------------------------------------------------------------------
# 가져오기 — 평문 GET, 막히면 Playwright
# ---------------------------------------------------------------------------
def _fetch_plain(url: str) -> str:
    raw = http_get(url, headers={"User-Agent": BROWSER_UA,
                                 "Accept": "text/html,application/xhtml+xml"},
                   retries=2, backoff=5.0)
    html = raw.decode("utf-8", errors="replace")
    # 블롭이 있으면 성공이다. 없을 때에만 왜 없는지를 따진다.
    if not _has_blob(html) and _looks_blocked(html):
        raise BlockedError("Cloudflare 챌린지")
    return html


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _fetch_rendered(url: str) -> str:
    """cds.py 와 같은 패턴. 워크플로가 이미 Chromium 을 설치한다."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-dev-shm-usage"])
        try:
            page = browser.new_page(user_agent=BROWSER_UA)
            page.goto(url, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
            try:
                page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:  # noqa: BLE001 — 광고 때문에 idle 에 못 갈 수 있다
                page.wait_for_timeout(4_000)
            return page.content()
        finally:
            browser.close()


def fetch_week_html(week: Optional[str] = None) -> tuple[str, str]:
    """(html, 사용한 경로). 평문이 막히면 렌더링으로 넘어간다."""
    url = BASE_URL if not week else f"{BASE_URL}?week={week}"
    try:
        return _fetch_plain(url), "http"
    except Exception as plain_exc:  # noqa: BLE001 — 차단·타임아웃 모두 여기로
        if not _playwright_available():
            raise BlockedError(
                f"평문 요청 실패({type(plain_exc).__name__}) · playwright 미설치로 대체 불가"
            ) from plain_exc
        html = _fetch_rendered(url)
        if not _has_blob(html) and _looks_blocked(html):
            raise BlockedError("평문·렌더링 모두 Cloudflare 챌린지") from plain_exc
        return html, "playwright"


# ---------------------------------------------------------------------------
# 저장
# ---------------------------------------------------------------------------
def _existing_release(conn, series_id: str, ref_date: str):
    return conn.execute(
        "SELECT actual, forecast, previous FROM releases"
        " WHERE series_id = ? AND ref_date = ?",
        (series_id, ref_date),
    ).fetchone()


def store_week(
    conn, days: list[dict], *, dry_run: bool = False, fill_only: bool = False
) -> tuple[int, int, int]:
    """(원본 저장 건수, 지표 매핑 건수, actual 이 있던 매핑 건수).

    `fill_only` — 이미 값이 있는 칸은 건드리지 않는다. 과거 주 백필에서 쓴다.
    `upsert_release` 는 새 값이 non-null 이면 기존 값을 덮으므로, 그대로 두면
    엑셀에서 온 **발표 당시 컨센서스**가 지금 렌더링된 값으로 조용히 바뀐다.
    `prune_excel_actuals.py` 의 "예측·이전은 절대 건드리지 않는다" 와 같은 이유다.
    """
    index = _title_index()
    stored = mapped = with_actual = 0

    for dt, cur, name, actual, forecast, previous, revision in iter_events(days):
        # 1단계: 원본 전량 보관. 매핑이 틀려도 나중에 되살릴 수 있어야 한다.
        #
        # `revision`(직전값 개정: 197K→198K)은 공식 피드에 없는 값이지만
        # **저장하지 않는다.** 처음엔 previous_raw 에 '197K→198K' 로 합쳐 넣었는데,
        # 그 문자열은 parse_raw_number 가 해석하지 못해 None 이 된다 —
        # remap_from_stored() 가 돌면 previous 가 조용히 사라진다.
        # 한 칸에 두 값을 넣는 것보다 안 넣는 편이 낫다. 개정 이력을 다루게 되면
        # calendar_events 에 revision_raw 열을 따로 만든다.
        if not dry_run:
            db_mod.upsert_calendar_event(
                conn, title=name, country=cur, event_time=dt.isoformat(),
                impact=None, actual_raw=actual,
                forecast_raw=forecast, previous_raw=previous,
            )
        stored += 1

        # 2단계: 아는 지표만 매핑
        s = index.get((cur, name))
        if s is None:
            continue
        ref_date = derive_ref_date(s, dt)
        a = to_series_unit(s.unit, parse_raw_number(actual))
        f = to_series_unit(s.unit, parse_raw_number(forecast))
        p = to_series_unit(s.unit, parse_raw_number(previous))
        # 권위 소스가 있는 지표(FRED·ECOS)의 실제값은 **덮지 않는다.**
        # 캘린더가 주는 것은 반올림된 헤드라인이고, FRED 는 전체 정밀도에
        # 최초발표값(vintage)까지 준다. 실제로 이 보호가 없을 때
        # JOLTS 2026-06 이 7.359 → 7.36 으로 깎였다.
        # 빈 칸을 메우는 것은 허용한다 — 없는 것보다는 낫다.
        authoritative = s.fred_id is not None or s.ecos_stat is not None
        old = _existing_release(conn, s.id, ref_date) if (authoritative or fill_only) else None

        if old is not None:
            if authoritative and old["actual"] is not None:
                a = None
            if fill_only:
                if old["actual"] is not None:
                    a = None
                if old["forecast"] is not None:
                    f = None
                if old["previous"] is not None:
                    p = None

        if a is None and f is None and p is None:
            continue

        if not dry_run:
            # 소스명은 공식 피드와 같은 값을 쓴다. 같은 발표를 두 경로로 받는 것뿐이고,
            # 여기서 이름을 갈라 놓으면 releases 의 source 열이 무의미해진다.
            db_mod.upsert_release(
                conn, s.id, ref_date, release_date=dt.isoformat(),
                actual=a, forecast=f, previous=p, source=FF_SOURCE,
            )
            # 권위 소스가 없는 지표(= ISM 2종)는 여기서 관측치까지 채운다.
            # releases 에만 넣으면 차트·스파크라인·맥락 계산이 쓰는 observations 가
            # 엑셀 백필 시점에 멈춰 버린다. 조건은 import_excel.py 와 **같은 규칙**이다.
            if s.fred_id is None and s.ecos_stat is None and a is not None:
                db_mod.upsert_observation(conn, s.id, ref_date, a, FF_SOURCE)
        mapped += 1
        if a is not None:
            with_actual += 1

    if not dry_run:
        conn.commit()
    return stored, mapped, with_actual


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------
@guarded(SOURCE)
def collect(conn, *, dry_run: bool = False) -> FetchResult:
    try:
        html, via = fetch_week_html()
        days = parse_days(html)
    except BlockedError as exc:
        # ★ 실패를 성공으로 세지 않는다 ★
        # 0건 매핑을 ok 로 돌려주면 ISM 이 또 조용히 죽는다.
        return FetchResult(
            SOURCE, ok=False,
            message=f"캘린더 페이지를 받지 못했습니다: {exc}",
            issues=["ISM 2종은 이 경로로만 실제값이 들어옵니다 — "
                    "계속 막히면 data/manual_overrides.csv 로 직접 넣어야 합니다"],
        )

    stored, mapped, with_actual = store_week(conn, days, dry_run=dry_run)

    issues: list[str] = []
    if with_actual == 0:
        issues.append("실제값이 하나도 없습니다 — 페이지 구조가 바뀌었는지 확인이 필요합니다")
    return FetchResult(
        SOURCE, ok=True, rows=with_actual,
        message=f"{via} 경로, 원본 {stored}건 · 매핑 {mapped}건 · 실제값 {with_actual}건",
        issues=issues,
    )
