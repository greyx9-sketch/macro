# -*- coding: utf-8 -*-
"""FRED (세인트루이스 연은) 수집기 — 실제값 12종.

두 종류의 값을 나눠 가져온다.

  현재값 (기본 요청)
      개정이 모두 반영된 최신 시계열. observations 테이블에 들어가며
      차트와 파생계산(YoY/MoM/차분)의 기준이 된다.

  최초발표값 (output_type=4)
      발표 당시 실제로 나왔던 숫자와 그 발표일. releases 테이블의 actual/release_date
      기본값이 된다. 엑셀의 '실제' 열이 의미하던 것이 바로 이 값이다.

이 둘을 구분하는 것이 엑셀 대비 개선점이다. 엑셀은 나중에 수정된 값을 덮어써
버려서 "발표 당시엔 뭐라고 나왔는지"를 잃는다.

주의: fredgraph.csv 무인증 엔드포인트는 접속이 막혀 있어 반드시 API 키를 쓴다.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

from core import series as series_mod
from core.series import Series
from core.transform import apply_transform, normalize_ref_date

from .base import FetchError, FetchResult, guarded, http_get

API = "https://api.stlouisfed.org/fred/series/observations"
META_API = "https://api.stlouisfed.org/fred/series"
SOURCE = "fred"

# FRED 는 분당 120회를 허용한다. 24회 남짓이라 여유롭지만 매너 있게 간격을 둔다.
_THROTTLE_SEC = 0.15


def api_key() -> str:
    key = os.environ.get("FRED_API_KEY", "").strip()
    if not key:
        raise FetchError(
            "FRED_API_KEY 환경변수가 없습니다. "
            "https://fredaccount.stlouisfed.org/apikeys 에서 무료 발급 후 설정하세요."
        )
    return key


def _request(params: dict) -> dict:
    raw = http_get(API, params)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError(f"FRED 응답이 JSON 이 아님: {raw[:200]!r}") from exc


def _to_float(text: str) -> Optional[float]:
    """FRED 는 결측을 '.' 으로 준다. 0 이 아니라 None 이다."""
    if text is None or text.strip() in (".", ""):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def fetch_metadata(fred_id: str, *, key: Optional[str] = None) -> dict:
    """계열 메타데이터. 단위·계절조정 여부 등이 들어 있다."""
    raw = http_get(META_API, {
        "series_id": fred_id,
        "api_key": key or api_key(),
        "file_type": "json",
    })
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FetchError(f"FRED 메타데이터 응답이 JSON 이 아님: {raw[:200]!r}") from exc
    items = data.get("seriess") or []
    if not items:
        raise FetchError(f"FRED 계열 '{fred_id}' 을(를) 찾을 수 없습니다")
    time.sleep(_THROTTLE_SEC)
    return items[0]


def assert_seasonal_adjustment(s: Series, *, key: Optional[str] = None) -> str:
    """요구된 계절조정 상태가 실제와 맞는지 확인한다.

    계절조정 여부는 값을 통째로 바꾸는 선택인데 계열 ID 만 봐서는 알 수 없다.
    (PPIFIS 가 SA 라는 것은 문서를 읽어야 알 수 있는 사실이지 ID 에서 유도되지 않는다.)
    맞지 않으면 조용히 잘못된 값을 쌓는 대신 그 지표만 실패시킨다.
    """
    want = s.require_seasonal_adjustment
    if not want or not s.fred_id:
        return ""
    meta = fetch_metadata(s.fred_id, key=key)
    got = (meta.get("seasonal_adjustment_short") or "").strip()
    if got.upper() != want.upper():
        raise FetchError(
            f"{s.name_ko}({s.fred_id}) 는 계절조정 '{want}' 를 요구하지만 "
            f"FRED 는 '{got}' ({meta.get('seasonal_adjustment')}) 로 제공합니다. "
            f"core/series.py 의 fred_id 를 올바른 계열로 바꾸세요 "
            f"(대안 후보: {', '.join(s.fred_alternatives) or '없음'})."
        )
    return got


def fetch_current(
    fred_id: str, *, start: str = "1990-01-01", key: Optional[str] = None
) -> list[tuple[str, Optional[float]]]:
    """개정이 반영된 현재 시계열."""
    data = _request(
        {
            "series_id": fred_id,
            "api_key": key or api_key(),
            "file_type": "json",
            "observation_start": start,
        }
    )
    time.sleep(_THROTTLE_SEC)
    return [(o["date"], _to_float(o.get("value"))) for o in data.get("observations", [])]


def fetch_initial_releases(
    fred_id: str, *, start: str = "1990-01-01", key: Optional[str] = None
) -> list[tuple[str, Optional[float], Optional[str]]]:
    """최초 발표값과 발표일.

    output_type=4 는 각 기준시점의 '처음 공개된' 값만 돌려주고,
    realtime_start 가 그 값이 처음 이용 가능해진 날짜 = 발표일이다.

    일부 계열(특히 일간 시장금리)은 vintage 이력이 없어 빈 응답이 온다.
    그 경우 호출자가 현재값으로 대체하면 되므로 예외로 취급하지 않는다.

    ★ realtime 범위를 반드시 넓혀야 한다 ★
      지정하지 않으면 realtime_start=realtime_end=오늘 로 기본 설정되고,
      그러면 '오늘 시점에 최초 공개된 값'만 남아 사실상 빈 응답이 온다.
      실제로 이 파라미터를 빠뜨려 최초발표값이 한 건도 저장되지 않고 있었다.
    """
    data = _request(
        {
            "series_id": fred_id,
            "api_key": key or api_key(),
            "file_type": "json",
            "observation_start": start,
            "output_type": 4,
            "realtime_start": "1776-07-04",   # FRED 가 허용하는 최소값
            "realtime_end": "9999-12-31",     # FRED 가 허용하는 최대값
        }
    )
    time.sleep(_THROTTLE_SEC)
    return [
        (o["date"], _to_float(o.get("value")), o.get("realtime_start"))
        for o in data.get("observations", [])
    ]


def series_points(
    s: Series, *, start: str = "1990-01-01", key: Optional[str] = None
) -> dict:
    """지표 하나에 대해 변환까지 마친 결과.

    반환:
        {
          "current":  [(ref_date, value), ...],          # 변환 적용됨
          "initial":  {ref_date: (value, release_date)},  # 변환 적용됨
        }
    """
    if not s.fred_id:
        raise ValueError(f"{s.id} 는 FRED 계열이 아님")

    k = key or api_key()

    raw_current = fetch_current(s.fred_id, start=start, key=k)
    current = [
        (normalize_ref_date(d, s.frequency), v)
        for d, v in apply_transform(raw_current, s.transform)
    ]

    initial: dict[str, tuple[Optional[float], Optional[str]]] = {}
    try:
        raw_initial = fetch_initial_releases(s.fred_id, start=start, key=k)
    except FetchError:
        raw_initial = []

    if raw_initial:
        # 변환(YoY/차분)은 계열 전체가 필요하므로 값만 뽑아 동일 파이프라인을 태운다.
        release_by_date = {d: rt for d, _, rt in raw_initial}
        transformed = apply_transform([(d, v) for d, v, _ in raw_initial], s.transform)
        for d, v in transformed:
            ref = normalize_ref_date(d, s.frequency)
            initial[ref] = (v, release_by_date.get(d))

    # vintage 이력이 없는 계열도 있고, FRED 가 응답을 바꿀 수도 있다.
    # 그럴 때 발표 실제값이 통째로 비어 화면이 '—' 로 도배되면 안 되므로
    # 현재값으로 메운다. 최초발표값이 있으면 그쪽이 우선이다.
    for ref_date, value in current:
        if value is not None and ref_date not in initial:
            initial[ref_date] = (value, None)

    return {"current": current, "initial": initial}


def all_fred_series() -> list[Series]:
    return series_mod.fred_series()


# ---------------------------------------------------------------------------
# 수집 진입점
# ---------------------------------------------------------------------------
@guarded(SOURCE)
def collect(conn, *, dry_run: bool = False, start: str = "1990-01-01") -> FetchResult:
    from core import db as db_mod
    from core.validate import validate_series_points

    key = api_key()
    total = 0
    revised = 0
    resourced = 0
    issues: list[str] = []
    failed: list[str] = []

    for s in all_fred_series():
        try:
            # 계절조정 요구가 걸린 지표는 값을 받기 전에 먼저 검증한다.
            # 틀린 계열이면 한 건도 저장하지 않는 것이 맞다.
            sa = assert_seasonal_adjustment(s, key=key)
            if sa:
                issues.append(f"{s.name_ko}: 계절조정 '{sa}' 확인됨")
            result = series_points(s, start=start, key=key)
        except Exception as exc:  # noqa: BLE001 — 지표 단위로 격리
            failed.append(f"{s.name_ko}({s.fred_id}): {type(exc).__name__}: {exc}")
            continue

        current = result["current"]
        issues.extend(str(i) for i in validate_series_points(s, current))

        for ref_date, value in current:
            if not dry_run:
                outcome = db_mod.upsert_observation(conn, s.id, ref_date, value, SOURCE)
                if outcome == "revised":
                    revised += 1
                elif outcome == "resourced":
                    resourced += 1
            total += 1

        # 최초발표값과 발표일 -> releases 의 기본값.
        # 캘린더가 나중에 같은 행을 채우더라도 upsert_release 가 필드별로 병합한다.
        initial = result["initial"]

        if s.frequency == "event":
            # 정책금리(DFEDTARU)는 일별 계열로 오지만 '발표'는 FOMC 때만 일어난다.
            # 매일을 발표로 기록하면 최신 발표가 오늘 날짜가 되어 FOMC 이벤트가 묻히고,
            # 예측·이전 값이 붙어 있던 진짜 발표 행과도 어긋난다.
            # ECOS 수집기와 같은 규칙으로 값이 바뀐 시점만 남긴다.
            change_points: dict[str, tuple] = {}
            prev_val: Optional[float] = None
            for ref_date, value in current:
                if value is None:
                    continue
                if prev_val is None or abs(value - prev_val) > 1e-12:
                    change_points[ref_date] = (value, ref_date)
                prev_val = value
            initial = change_points

        for ref_date, (value, release_date) in initial.items():
            if value is None and release_date is None:
                continue
            if not dry_run:
                db_mod.upsert_release(
                    conn, s.id, ref_date,
                    release_date=release_date,
                    actual=value,
                    source=SOURCE,
                )

    if not dry_run:
        conn.commit()

    if failed:
        issues.extend(failed)

    ok = len(failed) < len(all_fred_series())
    return FetchResult(
        source=SOURCE,
        ok=ok,
        rows=total,
        message=f"{len(all_fred_series()) - len(failed)}/{len(all_fred_series())} 계열, "
                f"관측치 {total}건, 개정 감지 {revised}건"
                + (f", 출처 교체 {resourced}건" if resourced else ""),
        issues=issues,
    )
