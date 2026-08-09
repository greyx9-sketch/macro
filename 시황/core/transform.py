# -*- coding: utf-8 -*-
"""FRED 원계열 -> 엑셀 저장 단위로의 변환.

전년동월비/전월비는 **위치가 아니라 달력 기준**으로 짝을 찾는다.
계열 중간에 결측이 있을 때 위치 기반(shift)으로 계산하면 조용히 틀린 값이 나오는데,
바로 그런 조용한 오류를 없애려고 이 프로젝트를 만드는 것이므로 여기서부터 지킨다.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

Point = tuple[str, Optional[float]]  # (ref_date ISO, value)

# 관측치 하나만으로는 계산할 수 없는 변환 — 다른 시점의 값이 있어야 한다.
#
# ★ 이 집합은 변환 정의 바로 옆에 둔다 ★
#   전에는 fetchers/fred.py 가 따로 들고 있었는데, qoq 를 추가하면서 그쪽에
#   등록하는 것을 잊었다. 그 결과 최초발표값 경로가 1개짜리 목록으로 전분기비를
#   계산하려다 고용비용지수의 발표값 101건이 전부 비었다.
#   변환을 추가하는 사람이 반드시 여기도 보게 되도록 같은 파일에 둔다.
CROSS_PERIOD_TRANSFORMS = {"yoy", "mom", "qoq", "diff"}

# 관측치 하나로 끝나는 변환. 위와 합쳐 apply_transform 이 아는 전부여야 한다.
PER_OBSERVATION_TRANSFORMS = {"div100", "div1000"}

SUPPORTED_TRANSFORMS = CROSS_PERIOD_TRANSFORMS | PER_OBSERVATION_TRANSFORMS


def month_key(iso: str) -> str:
    """'2026-06-15' -> '2026-06-01'. 월간 계열의 기준시점 정규화."""
    return iso[:7] + "-01"


def quarter_key(iso: str) -> str:
    """'2026-05-20' -> '2026-04-01'. 분기 계열의 기준시점 정규화.

    분기는 그 분기의 첫 달 1일로 표현한다. FRED 도 분기 계열을 그렇게 준다.
    """
    y, m = int(iso[:4]), int(iso[5:7])
    return f"{y:04d}-{(m - 1) // 3 * 3 + 1:02d}-01"


def quarter_label(iso: str) -> str:
    """'2026-04-01' -> '2026 Q2'. 화면·리포트 표기용."""
    return f"{iso[:4]} Q{(int(iso[5:7]) - 1) // 3 + 1}"


def shift_months(iso_month: str, months: int) -> str:
    y, m = int(iso_month[:4]), int(iso_month[5:7])
    total = y * 12 + (m - 1) - months
    return f"{total // 12:04d}-{total % 12 + 1:02d}-01"


def _lookup(index: dict[str, Optional[float]], key: str) -> Optional[float]:
    v = index.get(key)
    return v if v is not None else None


def apply_transform(points: list[Point], transform: Optional[str]) -> list[Point]:
    """(날짜, 값) 목록에 변환 적용. 계산 불가한 시점은 값이 None 이 된다.

    None 을 0 으로 바꾸지 않는 것이 중요하다 — '모름'과 '0%'는 다르다.
    """
    if not transform:
        return points
    if transform not in SUPPORTED_TRANSFORMS:
        # 새 변환을 추가하면서 위 두 집합에 등록하지 않으면 여기서 멈춘다.
        # 조용히 잘못된 값을 만드는 것보다 낫다.
        raise ValueError(
            f"알 수 없는 변환 '{transform}'. core/transform.py 의 "
            f"CROSS_PERIOD_TRANSFORMS 또는 PER_OBSERVATION_TRANSFORMS 에 등록하세요."
        )

    if transform == "div100":
        return [(d, None if v is None else v / 100.0) for d, v in points]
    if transform == "div1000":
        return [(d, None if v is None else v / 1000.0) for d, v in points]

    ordered = sorted(points, key=lambda p: p[0])

    if transform in ("yoy", "mom", "qoq"):
        # 분기(qoq)도 같은 달력 기준 조회를 쓴다 — 3개월 전을 찾는다.
        # 위치 기반(직전 원소)으로 하면 계열 중간이 비었을 때 6개월 차이를
        # 3개월인 것처럼 계산하고도 아무 신호를 주지 않는다.
        lag = {"yoy": 12, "mom": 1, "qoq": 3}[transform]
        index = {month_key(d): v for d, v in ordered}
        out: list[Point] = []
        for d, v in ordered:
            key = month_key(d)
            base = _lookup(index, shift_months(key, lag))
            if v is None or base is None or base == 0:
                out.append((d, None))
            else:
                out.append((d, v / base - 1.0))
        return out

    if transform == "diff":
        index = {month_key(d): v for d, v in ordered}
        out = []
        for d, v in ordered:
            key = month_key(d)
            base = _lookup(index, shift_months(key, 1))
            if v is None or base is None:
                out.append((d, None))
            else:
                out.append((d, v - base))
        return out

    raise ValueError(f"알 수 없는 변환: {transform}")


def normalize_ref_date(iso: str, frequency: str) -> str:
    """기준시점을 저장 규약에 맞춘다.

    월간 지표는 해당 월 1일로, 분기 지표는 그 분기 첫 달 1일로 정규화한다.
    FRED 도 그렇게 주지만 다른 소스(캘린더 피드)는 발표일을 주므로 여기서 통일한다.
    """
    if frequency == "monthly":
        return month_key(iso)
    if frequency == "quarterly":
        return quarter_key(iso)
    return iso[:10]


def parse_iso_date(value: str) -> date:
    return date(int(value[:4]), int(value[5:7]), int(value[8:10]))
