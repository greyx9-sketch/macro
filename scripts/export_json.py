# -*- coding: utf-8 -*-
"""SQLite -> 정적 사이트가 읽을 JSON.

프론트엔드는 빌드 체인이 없다. 여기서 만든 JSON 을 fetch 해서 그릴 뿐이다.
따라서 '표시에 필요한 계산'은 되도록 여기서 끝낸다 — 서프라이즈, 방향, 신선도 등.

산출물
------
    site/data/dashboard.json   전체 (지표 메타 + 최근 발표 + 시계열 + 상태)

파일 하나로 두는 이유: 전체가 수백 KB 수준이라 쪼개면 요청만 늘고 이득이 없다.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core.series import ALL_SERIES, CATEGORY_ORDER, Series  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent.parent / "site" / "data"
OUT_FILE = OUT_DIR / "dashboard.json"

# 차트에 실을 최대 관측치 수.
# 단순히 최근 N개를 자르면 '전체' 버튼이 전체를 못 보여주는 거짓말이 된다
# (미국 CDS 는 2017년부터 3,254건인데 최근 400건만 나가면 2025년 이후만 보인다).
# 그래서 자르지 않고 **전 구간을 균등 다운샘플링**한다. 해상도는 낮아지되 범위는 정직해진다.
MAX_POINTS = 1200
# 표에 실을 최대 발표 행 수.
MAX_RELEASES = 60
# 상세 패널의 서프라이즈 추이 막대 개수.
MAX_SURPRISES = 12
# 상단 '최근 발표' 타임라인 길이.
MAX_TIMELINE = 20


def collapse_steps(points: list[dict]) -> list[dict]:
    """연속으로 같은 값이 이어지는 구간을 접는다.

    기준금리는 일별 계열로 오지만 실제로는 계단 함수다(한국은행 ECOS 9,707일 =
    금리 변경 60회). 평평한 구간을 전부 내보내면 JSON 만 커지고 그림은 똑같다.
    각 구간의 첫 점과 마지막 점만 남기면 계단 모양이 그대로 보존된다.
    """
    if len(points) < 3:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        if points[i]["v"] != points[i - 1]["v"] or points[i]["v"] != points[i + 1]["v"]:
            out.append(points[i])
    out.append(points[-1])
    return out


def downsample(points: list[dict], limit: int = MAX_POINTS) -> list[dict]:
    """시간순 관측치를 전 구간에 걸쳐 균등하게 솎아낸다.

    최근 N개만 남기는 방식과 다르다. 범위(첫 점~마지막 점)를 보존해야
    '전체' 버튼이 실제로 전체를 보여준다. 첫 점과 마지막 점은 항상 살린다 —
    마지막 점이 곧 최신값이라 절대 잃으면 안 된다.
    """
    n = len(points)
    if n <= limit:
        return points
    step = n / limit
    picked = [points[int(i * step)] for i in range(limit)]
    if picked[-1] is not points[-1]:
        picked[-1] = points[-1]
    return picked


def _series_meta(s: Series) -> dict:
    return {
        "id": s.id,
        "name": s.name_ko,
        "category": s.category,
        "unit": s.unit,
        "frequency": s.frequency,
        "decimals": s.decimals,
        "note": s.note,
        "higherIsBetter": s.higher_is_better,
        "hasForecastSource": s.ff_title is not None,
    }


def _surprise(s: Series, actual: Optional[float], forecast: Optional[float]) -> Optional[float]:
    if actual is None or forecast is None:
        return None
    return actual - forecast


def _latest_released(rows: list[dict]) -> Optional[dict]:
    """실제값이 있는 가장 최근 발표. 미발표 행(실제=None)은 건너뛴다."""
    for r in rows:
        if r["actual"] is not None:
            return r
    return None


def _next_scheduled(rows: list[dict]) -> Optional[dict]:
    """실제값이 아직 없는 가장 이른 예정 발표.

    발표일은 정밀도가 두 가지다.
      'YYYY-MM-DD'  캘린더 피드에서 온 정확한 발표 시각
      'YYYY-MM'     엑셀 '발표월' 에서 온 월 단위 정보
    월 단위 값을 날짜처럼 비교하면 그 달 내내 '지난 발표'로 잘못 판정되므로
    같은 정밀도끼리 비교한다.
    """
    pending = [r for r in rows if r["actual"] is None and r["releaseDate"]]
    if not pending:
        return None
    today = datetime.now(timezone.utc).date().isoformat()

    def is_future(r: dict) -> bool:
        d = r["releaseDate"]
        if len(d) <= 7:            # 월 단위: 이번 달이면 아직 예정으로 본다
            return d[:7] >= today[:7]
        return d[:10] >= today

    future = [r for r in pending if is_future(r)]
    return min(future, key=lambda r: r["releaseDate"]) if future else None


def build(conn) -> dict:
    manual_keys = {
        (r["series_id"], r["ref_date"], r["field"])
        for r in conn.execute("SELECT series_id, ref_date, field FROM manual_overrides")
    }

    series_out = []
    for s in ALL_SERIES:
        rel_rows = db_mod.releases_for(conn, s.id, limit=MAX_RELEASES)
        # 실제·예측·이전이 모두 비어 있는 행은 표에 '— — —' 한 줄로만 보여
        # 정보가 없다. YoY 계열의 첫 12개월(기준값 없음)이나 발표가 건너뛰어진
        # 시점에서 생긴다. 단 아직 발표 전인 행은 '다가오는 발표' 로 쓰이므로 남긴다.
        today = datetime.now(timezone.utc).date().isoformat()

        def informative(r) -> bool:
            if r["actual"] is not None or r["forecast"] is not None or r["previous"] is not None:
                return True
            rd = r["release_date"] or ""
            return bool(rd) and rd[:10] >= today[: len(rd[:10])]

        rel_rows = [r for r in rel_rows if informative(r)]
        releases = [
            {
                "refDate": r["ref_date"],
                "releaseDate": r["release_date"],
                "actual": r["actual"],
                "forecast": r["forecast"],
                "previous": r["previous"],
                "source": r["source"],
                "manual": any(
                    (s.id, r["ref_date"], f) in manual_keys
                    for f in ("actual", "forecast", "previous")
                ),
            }
            for r in rel_rows
        ]

        obs_rows = db_mod.observations_for(conn, s.id)  # 전량 — 자르지 않는다
        # 차트는 시간순이어야 하므로 뒤집는다.
        points = [
            {"d": r["ref_date"], "v": r["value"]}
            for r in reversed(obs_rows)
            if r["value"] is not None
        ]
        if s.frequency == "event":
            points = collapse_steps(points)  # 정책금리는 계단 함수다
        observations = downsample(points)
        # FRED/ECOS 수집을 아직 안 돌린 상태(API 키 미설정)에서는 observations 가 비어 있다.
        # 그 경우 엑셀에서 온 발표값으로 시계열을 대신 만들어 차트가 비지 않게 한다.
        # 값의 출처가 다르므로 프론트엔드에 알려 준다.
        obs_from_releases = False
        if not observations:
            observations = [
                {"d": r["ref_date"], "v": r["actual"]}
                for r in reversed(rel_rows)
                if r["actual"] is not None
            ]
            obs_from_releases = bool(observations)

        latest = _latest_released(releases)
        upcoming = _next_scheduled(releases)

        revisions = conn.execute(
            "SELECT ref_date, observed_at, old_value, new_value FROM revisions"
            " WHERE series_id = ? ORDER BY observed_at DESC LIMIT 10",
            (s.id,),
        ).fetchall()

        meta = _series_meta(s)
        meta.update(
            {
                "releases": releases,
                "observations": observations,
                "observationsFromReleases": obs_from_releases,
                "latest": (
                    {
                        **latest,
                        "surprise": _surprise(s, latest["actual"], latest["forecast"]),
                    }
                    if latest
                    else None
                ),
                "upcoming": upcoming,
                # 예측을 계속 상회/하회하는 편향은 값 하나로는 안 보이고 이력으로만 보인다.
                # (NFP 최근 6회: -57 / +44 / +83 / +149 / -214 / +94)
                "surpriseHistory": [
                    {"refDate": r["refDate"],
                     "value": _surprise(s, r["actual"], r["forecast"])}
                    for r in releases[:MAX_SURPRISES]
                    if r["actual"] is not None and r["forecast"] is not None
                ][::-1],
                "revisions": [
                    {
                        "refDate": r["ref_date"],
                        "observedAt": r["observed_at"],
                        "from": r["old_value"],
                        "to": r["new_value"],
                    }
                    for r in revisions
                ],
                "lastUpdated": rel_rows[0]["updated_at"] if rel_rows else None,
            }
        )
        series_out.append(meta)

    # 다가오는 발표 일정 (전 지표 통합)
    upcoming_all = sorted(
        (
            {
                "seriesId": s["id"],
                "name": s["name"],
                "category": s["category"],
                "releaseDate": s["upcoming"]["releaseDate"],
                "forecast": s["upcoming"]["forecast"],
                "previous": s["upcoming"]["previous"],
            }
            for s in series_out
            if s["upcoming"]
        ),
        key=lambda x: x["releaseDate"],
    )

    # ---- 최근 발표 타임라인 -------------------------------------------------
    # 카테고리를 가로질러 '언제 무엇이 나왔나' 만 시간순으로 본다.
    #
    # 일간 계열(CDS·10Y-2Y)은 제외한다. 매일이 '발표'라 목록을 통째로 뒤덮어
    # 정작 보려던 월간 지표 발표가 묻힌다.
    # 월 단위 발표일(엑셀 백필분)도 제외한다 — 며칠에 나왔는지 모르는 항목을
    # 날짜순 목록에 섞으면 순서가 거짓이 된다.
    #
    # 지표당 최근 1건만 넣는다. 주간 지표(신규 실업수당)는 매주 나오므로
    # 제한이 없으면 20칸 중 7칸을 혼자 차지하고 월간 지표를 밀어낸다.
    # 보려는 것은 '어느 지표가 마지막으로 언제 뭐라고 나왔나' 이지
    # '한 지표의 지난 두 달' 이 아니다.
    TIMELINE_FREQ = {"monthly", "quarterly", "weekly", "event"}
    TIMELINE_PER_SERIES = 1
    timeline = []
    for s in series_out:
        if s["frequency"] not in TIMELINE_FREQ:
            continue
        taken = 0
        for r in s["releases"]:
            if taken >= TIMELINE_PER_SERIES:
                break
            rd = r["releaseDate"]
            if not rd or len(rd) <= 7 or r["actual"] is None:
                continue
            timeline.append({
                "seriesId": s["id"],
                "name": s["name"],
                "category": s["category"],
                "releaseDate": rd,
                "refDate": r["refDate"],
                "actual": r["actual"],
                "forecast": r["forecast"],
                "previous": r["previous"],
            })
            taken += 1
    timeline.sort(key=lambda x: x["releaseDate"], reverse=True)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "categories": CATEGORY_ORDER,
        "series": series_out,
        "timeline": timeline[:MAX_TIMELINE],
        "upcoming": upcoming_all[:12],
        "sources": db_mod.latest_status(conn),
        "counts": {
            "series": len(series_out),
            "observations": conn.execute("SELECT COUNT(*) c FROM observations").fetchone()["c"],
            "releases": conn.execute("SELECT COUNT(*) c FROM releases").fetchone()["c"],
            "calendarEvents": conn.execute("SELECT COUNT(*) c FROM calendar_events").fetchone()["c"],
        },
    }


def main() -> int:
    conn = db_mod.connect()
    payload = build(conn)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    size_kb = OUT_FILE.stat().st_size / 1024
    print(f"{OUT_FILE.relative_to(OUT_FILE.parent.parent.parent)} 생성 ({size_kb:.0f} KB)")
    print(
        f"  지표 {payload['counts']['series']} · "
        f"관측치 {payload['counts']['observations']} · "
        f"발표 {payload['counts']['releases']} · "
        f"캘린더 원본 {payload['counts']['calendarEvents']}"
    )
    conn.close()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
