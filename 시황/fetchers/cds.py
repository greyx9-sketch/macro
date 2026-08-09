# -*- coding: utf-8 -*-
"""CDS 5년물 수집기 (미국 / 한국) — 이 프로젝트에서 가장 취약한 부분.

왜 어려운가
-----------
worldgovernmentbonds.com 의 CDS 페이지는 HTTP 로는 값을 주지 않는다.
계획 단계 실측 결과:
  - 페이지는 200 이지만 모든 수치가 `data-async-variable=...>----</span>` 플레이스홀더
  - 실제 데이터는 wp-json/common/v1/historical 이 주는데 nonce 없이 호출하면 403

따라서 headless 브라우저로 페이지를 실제로 렌더링해야 한다.
Playwright 는 **선택적 의존성**이며, 없거나 실패해도
collect.py 는 나머지 16종 수집을 정상 완료한다.

전략
----
1순위: 페이지가 내부적으로 호출하는 historical 응답을 가로챈다 -> 전체 이력 확보
2순위: 렌더링된 DOM 에서 최신값 1건만 읽는다
둘 다 실패하면 실패로 기록하고 기존 값을 그대로 둔다. 절대 덮어쓰지 않는다.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Optional

from core import db as db_mod
from core import series as series_mod

from .base import FetchResult, guarded

SOURCE = "worldgovernmentbonds"
PAGE = "https://www.worldgovernmentbonds.com/cds-historical-data/{country}/5-years/"
HISTORICAL_PATH = "/wp-json/common/v1/historical"
NAV_TIMEOUT_MS = 45_000


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# 응답 해석
# ---------------------------------------------------------------------------
def _extract_pairs(payload: Any) -> list[tuple[str, float]]:
    """historical 응답에서 (날짜, 값) 쌍을 찾아낸다.

    응답 스키마가 공개돼 있지 않으므로 구조를 가정하지 않고 재귀 탐색한다.
    스키마가 바뀌어도 날짜/숫자 쌍 형태만 유지되면 계속 동작한다.
    """
    found: list[tuple[str, float]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            date_val = None
            num_val = None
            for k, v in node.items():
                kl = k.lower()
                if date_val is None and isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}.*", v):
                    date_val = v[:10]
                elif date_val is None and kl in {"d", "date", "data", "x"} and isinstance(v, (int, float)):
                    # 밀리초 타임스탬프
                    try:
                        date_val = datetime.fromtimestamp(v / 1000, tz=timezone.utc).date().isoformat()
                    except (ValueError, OSError, OverflowError):
                        pass
                # 실제 응답 스키마(2026-08 확인):
                #   {"result": {"quote": {"1": {"CLOSE_VAL": 45.5, "DATA_VAL": "2007-12-17", …}}}}
                # 종가 키가 'CLOSE_VAL' 이라 'close' 정확히 일치만 보면 전부 놓친다.
                # DATA_VAL·TIME_VAL 도 _val 로 끝나지만 문자열이므로 숫자 검사에서 걸러진다.
                if (
                    num_val is None
                    and isinstance(v, (int, float))
                    and not isinstance(v, bool)
                    and (kl in {"v", "value", "y", "valore", "close"}
                         or "close" in kl
                         or kl.endswith("_val"))
                ):
                    num_val = float(v)
            if date_val and num_val is not None:
                found.append((date_val, num_val))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            # [timestamp, value] 형태의 하이차트 시리즈
            if (
                len(node) == 2
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
                and node[0] > 1_000_000_000_000  # ms 타임스탬프로 보이는 크기
            ):
                try:
                    d = datetime.fromtimestamp(node[0] / 1000, tz=timezone.utc).date().isoformat()
                    found.append((d, float(node[1])))
                except (ValueError, OSError, OverflowError):
                    pass
            for v in node:
                walk(v)

    walk(payload)

    # 중복 제거 (마지막 값 우선)
    dedup: dict[str, float] = {}
    for d, v in found:
        dedup[d] = v
    return sorted(dedup.items())


def _plausible(values: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """CDS 스프레드로 말이 되는 범위만 남긴다.

    페이지에는 부도확률(%), 채권금리 등 다른 숫자도 섞여 있어서
    거르지 않으면 엉뚱한 값이 CDS 로 저장된다.
    """
    return [(d, v) for d, v in values if 0.5 <= v <= 2000.0]


# ---------------------------------------------------------------------------
# 수집
# ---------------------------------------------------------------------------
def _scrape_country(country: str) -> list[tuple[str, float]]:
    from playwright.sync_api import sync_playwright

    captured: list[Any] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--disable-dev-shm-usage"])
        try:
            page = browser.new_page(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
                )
            )

            def on_response(resp):
                if HISTORICAL_PATH in resp.url:
                    try:
                        captured.append(resp.json())
                    except Exception:  # noqa: BLE001 — 본문이 JSON 이 아니면 무시
                        pass

            page.on("response", on_response)
            page.goto(PAGE.format(country=country), timeout=NAV_TIMEOUT_MS,
                      wait_until="domcontentloaded")
            # 차트 데이터 요청이 끝날 시간을 준다
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except Exception:  # noqa: BLE001 — 광고 때문에 idle 에 못 갈 수 있다
                page.wait_for_timeout(6_000)

            # 1순위: 가로챈 이력 응답
            for payload in captured:
                pairs = _plausible(_extract_pairs(payload))
                if len(pairs) >= 5:
                    return pairs

            # 2순위: 렌더링된 최신값 1건
            value_text = page.eval_on_selector(
                "[data-async-variable='jsGlobalResult|result.ultimoValore']",
                "el => el.textContent",
            )
            date_text = page.eval_on_selector(
                "[data-async-variable='jsGlobalResult|result.ultimoTimestampDesc']",
                "el => el.textContent",
            )
            value = None
            try:
                value = float(str(value_text).strip().replace(",", ""))
            except (TypeError, ValueError):
                pass
            if value is None:
                return []

            iso = _parse_display_date(date_text)
            return _plausible([(iso, value)])
        finally:
            browser.close()


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _parse_display_date(text: Optional[str]) -> str:
    """'27 Jul 2026, 16:30' 형태를 ISO 로. 실패하면 오늘(UTC)."""
    if text:
        m = re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\s+(\d{4})", text)
        if m:
            day, mon, year = int(m.group(1)), _MONTHS.get(m.group(2).lower()), int(m.group(3))
            if mon:
                return f"{year:04d}-{mon:02d}-{day:02d}"
    return datetime.now(timezone.utc).date().isoformat()


@guarded(SOURCE)
def collect(conn, *, dry_run: bool = False) -> FetchResult:
    if not playwright_available():
        return FetchResult(
            SOURCE,
            ok=False,
            message=(
                "playwright 가 설치되어 있지 않아 CDS 를 건너뜁니다. "
                "`pip install playwright && playwright install chromium` "
                "또는 사이트에서 수동 입력하세요."
            ),
        )

    total = 0
    issues: list[str] = []
    failures = 0

    targets = [s for s in series_mod.ALL_SERIES if s.cds_country]
    for s in targets:
        try:
            pairs = _scrape_country(s.cds_country)
        except Exception as exc:  # noqa: BLE001 — 국가별로 격리
            failures += 1
            issues.append(f"{s.name_ko}: {type(exc).__name__}: {exc}")
            continue

        if not pairs:
            failures += 1
            issues.append(f"{s.name_ko}: 값을 찾지 못함 (페이지 구조 변경 가능성)")
            continue

        prev: Optional[float] = None
        for iso, value in pairs:
            if not dry_run:
                db_mod.upsert_observation(conn, s.id, iso, value, SOURCE)
                change = None if prev in (None, 0) else (value - prev) / prev
                db_mod.upsert_release(
                    conn, s.id, iso,
                    release_date=iso,
                    actual=value,
                    previous=prev,
                    source=SOURCE,
                )
                del change  # 변동%는 프론트엔드가 실제/이전으로 계산한다
            prev = value
            total += 1

    if not dry_run:
        conn.commit()

    ok = failures < len(targets)  # 하나라도 성공하면 부분 성공
    return FetchResult(
        SOURCE, ok=ok, rows=total,
        message=f"{len(targets) - failures}/{len(targets)} 국가 수집, {total}건",
        issues=issues,
    )
