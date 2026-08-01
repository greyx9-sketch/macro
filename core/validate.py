# -*- coding: utf-8 -*-
"""수집값 검증.

목적은 '틀린 값이 조용히 DB 에 들어가는 것'을 막는 것이다.
검증에 걸린 값은 버리지 않고 경고와 함께 반환해 사람이 판단하게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .series import Series, sanity_range


@dataclass
class Issue:
    series_id: str
    ref_date: str
    kind: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.series_id} {self.ref_date}: {self.detail}"


def check_range(series: Series, ref_date: str, value: Optional[float]) -> Optional[Issue]:
    """단위 변환 실수를 잡는 1차 방어선.

    실업률이 4.2 로 들어오면(0.042 이어야 함) 여기서 걸린다.
    """
    if value is None:
        return None
    lo, hi = sanity_range(series)
    if not (lo <= value <= hi):
        return Issue(
            series.id,
            ref_date,
            "range",
            f"{value!r} 가 {series.unit} 상식 범위 [{lo}, {hi}] 밖 — 단위 변환 확인 필요",
        )
    return None


def check_jump(
    series: Series,
    ref_date: str,
    value: Optional[float],
    previous: Optional[float],
    max_rel: float = 0.5,
) -> Optional[Issue]:
    """직전 대비 급변 감지 — 파싱 오류를 잡기 위한 검사.

    지수(CPI·PPI·PMI)와 백만 단위(JOLTS)에만 적용한다.
    CDS(bp)는 제외한다: 위기 때 실제로 며칠 만에 두 배가 된다
    (2023-03 미국 부채한도 26→41bp, 2008-02 한국 48→76bp).
    이런 진짜 시장 움직임을 경고로 띄우면 경고 자체가 무시당한다.
    """
    if value is None or previous is None or previous == 0:
        return None
    if series.unit not in ("index", "millions"):
        return None
    rel = abs(value - previous) / abs(previous)
    if rel > max_rel:
        return Issue(
            series.id,
            ref_date,
            "jump",
            f"직전 {previous} -> {value} ({rel:.0%} 변동) — 파싱 오류 가능성",
        )
    return None


def check_monotonic_dates(series: Series, ref_dates: list[str]) -> list[Issue]:
    """기준시점 중복 검사.

    엑셀에서 발견된 '발표월 2025-12 가 두 번' 류의 오류가 다시 생기지 않게 한다.
    """
    seen: dict[str, int] = {}
    issues: list[Issue] = []
    for d in ref_dates:
        seen[d] = seen.get(d, 0) + 1
    for d, n in seen.items():
        if n > 1:
            issues.append(Issue(series.id, d, "duplicate", f"기준시점이 {n}회 중복"))
    return issues


def validate_series_points(
    series: Series, points: list[tuple[str, Optional[float]]]
) -> list[Issue]:
    issues: list[Issue] = []
    issues.extend(check_monotonic_dates(series, [d for d, _ in points]))

    ordered = sorted(points, key=lambda p: p[0])
    prev: Optional[float] = None
    for ref_date, value in ordered:
        issue = check_range(series, ref_date, value)
        if issue:
            issues.append(issue)
        issue = check_jump(series, ref_date, value, prev)
        if issue:
            issues.append(issue)
        if value is not None:
            prev = value
    return issues
