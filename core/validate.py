# -*- coding: utf-8 -*-
"""수집값 검증.

목적은 '틀린 값이 조용히 DB 에 들어가는 것'을 막는 것이다.
검증에 걸린 값은 버리지 않고 경고와 함께 반환해 사람이 판단하게 한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
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


def check_release_vs_observation(
    series: Series,
    releases: dict[str, Optional[float]],
    observations: dict[str, Optional[float]],
    tolerance_multiple: float = 3.0,
    max_violation_share: float = 0.02,
) -> list[Issue]:
    """발표 실제값과 관측치가 통상 개정 폭 안에서 일치하는지 본다.

    범위 검사만으로는 못 잡는 계열의 버그를 잡는다.
    실제로 최초발표 '수준값'을 차분하다 NFP 2010-01 이 -1,383천명(정답 -6천명),
    PCE 가 -8.8%(정답 2.4%)로 저장된 적이 있는데, 두 값 모두 단위 범위 안이라
    기존 검사에 걸리지 않았다.

    ★ 개별 이상치가 아니라 '계열 전체가 틀렸는지' 를 본다 ★
      개별 시점을 하나씩 경고하면 진짜 개정이 큰 시점(2020년 실업수당은
      최초발표와 개정치가 702천건까지 벌어졌다)이 경고를 채워 버린다.
      계산 경로가 틀리면 거의 모든 시점이 어긋나므로(NFP 버그는 437건 중 436건),
      **위반 비율**로 판정하면 둘을 깔끔하게 가른다.

    개정 폭을 모르는 지표(revision_band=0)는 건너뛴다.
    """
    if series.revision_band <= 0:
        return []

    limit = series.revision_band * tolerance_multiple
    pairs = [
        (d, r, observations[d])
        for d, r in releases.items()
        if r is not None and observations.get(d) is not None
    ]
    if len(pairs) < 10:  # 표본이 적으면 비율이 의미 없다
        return []

    violations = [(d, r, o) for d, r, o in pairs if abs(r - o) > limit]
    share = len(violations) / len(pairs)
    if share <= max_violation_share:
        return []

    worst = max(violations, key=lambda x: abs(x[1] - x[2]))
    return [
        Issue(
            series.id, worst[0], "release-vs-observation",
            f"발표값과 관측치가 {len(violations)}/{len(pairs)}건({share:.0%})에서 "
            f"개정 폭({limit:.4g})을 넘게 어긋남 — 계산 경로가 틀렸을 가능성이 높음. "
            f"최악: {worst[0]} 발표={worst[1]:.4g} 관측={worst[2]:.4g}",
        )
    ]


# ---------------------------------------------------------------------------
# 정체 감지
#
# ISM 2종이 두 달 동안 조용히 죽어 있었다. 값이 **틀린** 게 아니라 아예 **안 들어왔고**,
# 위의 검사들은 전부 '들어온 값이 말이 되는가' 만 본다. 안 들어온 것을 보는 눈이 없었다.
#
# 발표 예정일 추정(export_json.estimate_next_release)에 기대면 안 된다.
# 그건 과거 발표일 표본이 있어야 하는데, ISM 은 발표일이 전부 엑셀에서 온 월 단위라
# 표본이 0이다 — **가장 망가진 계열이 정확히 그 감지기의 사각지대**였다.
# 그래서 주기만 보고 판정한다. 주기는 항상 알고 있다.
# ---------------------------------------------------------------------------

# 날짜 차이를 그대로 쓰면 안 된다. JOLTS 는 **설계상** 2개월 지연 발표라
# 정상일 때도 최신 기준시점이 67일 전이고, 그건 갱신이 멈춘 미시간대와 같은 숫자다.
# 그래서 지표마다 다른 `ref_lag_months` 를 빼고 **몇 주기 밀렸는지**로 센다.
PERIOD_DAYS = {"monthly": 30.44, "quarterly": 91.3, "weekly": 7.0, "daily": 1.0}

# 몇 주기부터 경보인가.
#
# 1주기는 정상 구간이다 — 월간 지표는 그 달 발표가 나기 전까지 늘 1주기 뒤에 있다.
# 2주기는 '한 번 통째로 놓쳤다' 라 변명의 여지가 없다.
# 매번 울리는 경보는 아무도 안 보게 되므로 확실할 때만 운다.
STALE_PERIODS = 2.0

# 일간 계열은 주기 개념이 다르다 — 연휴를 감안해도 열흘은 과하다.
STALE_DAILY_DAYS = 10


def periods_behind(series: Series, latest_ref: Optional[str], today: str) -> Optional[float]:
    """예상 기준시점 대비 몇 주기나 밀려 있는가. 모르면 None."""
    span = PERIOD_DAYS.get(series.frequency)
    if span is None or not latest_ref:       # event(정책금리)는 주기가 없다
        return None

    days = (date.fromisoformat(today) - date.fromisoformat(latest_ref[:10])).days
    if series.frequency == "daily":
        return days / span
    # 발표 지연은 정상이다. 지표별 지연을 빼고 남은 것만 '밀린 것' 으로 센다.
    days -= series.ref_lag_months * 30.44
    return max(0.0, days / span)


def check_staleness(
    series: Series, latest_ref: Optional[str], today: str
) -> Optional[Issue]:
    """관측치 갱신이 멈췄는가."""
    if series.frequency not in PERIOD_DAYS:
        return None
    if not latest_ref:
        return Issue(series.id, "-", "stale", "관측치가 하나도 없습니다")

    if series.frequency == "daily":
        days = (date.fromisoformat(today) - date.fromisoformat(latest_ref[:10])).days
        if days <= STALE_DAILY_DAYS:
            return None
        return Issue(series.id, latest_ref, "stale",
                     f"최신 관측이 {days}일 전입니다 (일간 한계 {STALE_DAILY_DAYS}일)")

    behind = periods_behind(series, latest_ref, today)
    if behind is None or behind < STALE_PERIODS:
        return None
    unit = {"monthly": "개월", "quarterly": "분기", "weekly": "주"}[series.frequency]
    return Issue(
        series.id, latest_ref, "stale",
        f"발표 지연({series.ref_lag_months}개월)을 감안해도 {behind:.1f}{unit}치가 "
        f"밀려 있습니다 — 수집이 끊겼는지 확인이 필요합니다",
    )


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
