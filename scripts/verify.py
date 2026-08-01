# -*- coding: utf-8 -*-
"""엑셀 ↔ FRED 대조 검증.

이 스크립트의 목적은 '자동 수집이 엑셀을 제대로 대체하는가'를 증명하는 것이다.

두 가지를 판정한다.

  1) FRED 계열 매핑이 맞는가
     엑셀에 있던 실제값과 FRED 값이 허용오차 안에서 일치해야 한다.
     불일치가 많으면 series.py 의 fred_id 나 transform 이 틀린 것이다.
     fred_alternatives 가 정의된 지표는 대안 계열도 같이 시험해
     어느 쪽이 엑셀과 맞는지 알려준다 (PPI 의 계절조정 여부 등).

  2) 엑셀에 실재하던 오류가 실제로 드러나는가
     계획 단계에서 확인한 물가 15~17행, 고용 15~16행의 발표월 중복·누락이
     여기서 불일치로 잡혀야 정상이다. 안 잡히면 매핑이 틀렸다는 신호다.

사용법
------
    set FRED_API_KEY=...
    python scripts/verify.py
    python scripts/verify.py --series cpi_index --show 20
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core.series import ALL_SERIES, BY_ID, Series, format_value  # noqa: E402
from core.transform import apply_transform, normalize_ref_date  # noqa: E402
from fetchers import fred  # noqa: E402
from fetchers.base import FetchError  # noqa: E402


def tolerance(s: Series) -> float:
    """지표별 허용오차.

    엑셀은 반올림해서 적어 놨으므로(3.5% 를 0.035 로) 표시 자릿수만큼은 봐준다.
    """
    return {
        "ratio": 5e-4,      # 0.05%p
        "index": 0.05,
        "thousands": 1.0,   # 개정 전 값과 비교될 수 있어 넉넉히
        "millions": 0.01,
        "pp": 0.02,
        "bp": 0.5,
    }[s.unit]


def excel_actuals(conn, series_id: str) -> dict[str, float]:
    rows = conn.execute(
        "SELECT ref_date, actual FROM releases"
        " WHERE series_id = ? AND source = 'excel' AND actual IS NOT NULL",
        (series_id,),
    ).fetchall()
    return {r["ref_date"]: r["actual"] for r in rows}


def fred_values(s: Series, fred_id: str, key: str) -> dict[str, Optional[float]]:
    raw = fred.fetch_current(fred_id, start="2020-01-01", key=key)
    return {
        normalize_ref_date(d, s.frequency): v
        for d, v in apply_transform(raw, s.transform)
    }


def stored_values(conn, series_id: str) -> dict[str, Optional[float]]:
    """이미 수집돼 DB(=커밋된 CSV)에 들어있는 FRED 관측치.

    API 키 없이도 검증할 수 있게 하는 경로다. 저장소를 클론한 사람이
    '자동 수집이 엑셀을 제대로 대체했는가'를 네트워크 없이 확인할 수 있어야 한다.
    """
    rows = conn.execute(
        "SELECT ref_date, value FROM observations"
        " WHERE series_id = ? AND source = 'fred' AND value IS NOT NULL",
        (series_id,),
    ).fetchall()
    return {r["ref_date"]: r["value"] for r in rows}


def compare(
    s: Series, excel: dict[str, float], fred_map: dict[str, Optional[float]]
) -> tuple[int, int, list[tuple[str, float, Optional[float]]]]:
    tol = tolerance(s)
    matched = 0
    mismatches: list[tuple[str, float, Optional[float]]] = []

    common = sorted(set(excel) & set(fred_map), reverse=True)
    for ref in common:
        ev, fv = excel[ref], fred_map[ref]
        if fv is not None and abs(ev - fv) <= tol:
            matched += 1
        else:
            mismatches.append((ref, ev, fv))
    return matched, len(common), mismatches


def main() -> int:
    ap = argparse.ArgumentParser(description="엑셀 ↔ FRED 대조 검증")
    ap.add_argument("--series", help="이 지표만 검증")
    ap.add_argument("--show", type=int, default=6, help="지표당 출력할 불일치 개수")
    ap.add_argument("--offline", action="store_true",
                    help="API 를 부르지 않고 이미 수집된 DB 값과 대조한다")
    args = ap.parse_args()

    key: Optional[str] = None
    if not args.offline:
        try:
            key = fred.api_key()
        except FetchError as exc:
            print(f"{exc}\n", file=sys.stderr)
            print("이미 수집된 값과 대조하려면 --offline 을 쓰세요.", file=sys.stderr)
            return 2

    conn = db_mod.connect()
    targets = [BY_ID[args.series]] if args.series else [s for s in ALL_SERIES if s.fred_id]

    src = "이미 수집된 DB 값" if args.offline else "FRED API 값"
    print(f"엑셀에 기록된 '실제' 값과 {src}을 대조합니다.")
    print("불일치는 곧 (a) 매핑 오류 이거나 (b) 엑셀의 입력 오류입니다.\n")

    header = f"{'지표':<22}{'일치':>6}{'대상':>6}{'일치율':>8}   판정"
    print(header)
    print("-" * 70)

    total_bad = 0
    details: list[tuple[Series, list[tuple[str, float, Optional[float]]]]] = []

    for s in targets:
        excel = excel_actuals(conn, s.id)
        if not excel:
            print(f"{s.name_ko:<22}{'-':>6}{'-':>6}{'-':>8}   엑셀 데이터 없음")
            continue

        try:
            fmap = (stored_values(conn, s.id) if args.offline
                    else fred_values(s, s.fred_id, key))
        except Exception as exc:  # noqa: BLE001
            print(f"{s.name_ko:<22}{'-':>6}{'-':>6}{'-':>8}   FRED 오류: {exc}")
            total_bad += 1
            continue

        if not fmap:
            print(f"{s.name_ko:<22}{'-':>6}{'-':>6}{'-':>8}   수집된 FRED 값 없음")
            continue

        matched, total, mismatches = compare(s, excel, fmap)
        rate = matched / total if total else 0.0

        # ★ 정확 일치율만으로 판정하면 안 된다. ★
        # 엑셀에는 *발표 당시* 값이, FRED 에는 *개정된 현재* 값이 들어 있다.
        # NFP 는 두 번 개정되므로 일치율이 낮은 게 정상이다 — 매핑 오류가 아니다.
        # 차이의 크기가 그 지표의 통상 개정 폭 안에 있으면 매핑은 옳다고 본다.
        diffs = sorted(abs(e - f) for _d, e, f in mismatches if f is not None)
        median_diff = diffs[len(diffs) // 2] if diffs else 0.0

        if rate >= 0.9:
            verdict = "정상"
        elif s.revision_band > 0 and median_diff <= s.revision_band:
            verdict = f"개정 차이 (매핑 정상, 중앙값 {median_diff:.4g})"
        else:
            verdict = f"조사 필요 (중앙값 {median_diff:.4g})"
            total_bad += 1

        print(f"{s.name_ko:<22}{matched:>6}{total:>6}{rate:>7.0%}   {verdict}")

        # 매핑이 의심스러우면 대안 계열도 시험한다. (API 접근이 필요하다)
        if rate < 0.9 and s.fred_alternatives and not args.offline:
            for alt in s.fred_alternatives:
                try:
                    alt_map = fred_values(s, alt, key)
                except Exception:  # noqa: BLE001
                    continue
                am, at, _ = compare(s, excel, alt_map)
                alt_rate = am / at if at else 0.0
                flag = "  ←★ 이쪽이 맞습니다" if alt_rate > rate else ""
                print(f"{'  └ 대안 ' + alt:<22}{am:>6}{at:>6}{alt_rate:>7.0%}{flag}")

        if mismatches:
            details.append((s, mismatches))

    # ---- 불일치 상세 ------------------------------------------------------
    if details:
        print("\n" + "=" * 70)
        print("불일치 상세 (엑셀 값 vs FRED 값)")
        print("=" * 70)
        for s, mism in details:
            print(f"\n[{s.name_ko}]  {len(mism)}건")
            for ref, ev, fv in mism[: args.show]:
                shown_f = format_value(s, fv)
                print(f"   {ref}   엑셀 {format_value(s, ev):>12}   FRED {shown_f:>12}")
            if len(mism) > args.show:
                print(f"   … 외 {len(mism) - args.show}건")

    print("\n" + "=" * 70)
    print("'개정 차이' 는 정상입니다 — 엑셀은 발표 당시 값, FRED 는 개정된 현재 값입니다.")
    if total_bad == 0:
        print("모든 FRED 계열의 매핑이 확인되었습니다.")
    else:
        print(f"{total_bad}개 지표는 개정으로 설명되지 않습니다. 위 상세를 확인하세요.")
        print("엑셀 쪽 입력 오류라면 자동 수집값이 옳습니다 — 그것이 이 프로젝트의 목적입니다.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
