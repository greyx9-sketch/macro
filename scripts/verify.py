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

  3) 우리 값이 원 통계기관 값과 같은가  (`--bls`)
     위 두 판정은 둘 다 FRED 를 거친다. FRED 계열을 잘못 골랐거나 변환이 틀리면
     둘 다 통과하면서 값은 틀릴 수 있다. BLS 공개 API 에서 **수준값을 직접 받아
     우리 변환을 다시 계산해** 대조하면 FRED 를 거치지 않는 독립 경로가 된다.
     API 키가 필요 없다 — 대신 **IP 당 하루 25회**다.
     한도를 넘으면 '값이 다르다'가 아니라 '물어보지 못함' 으로 보고한다(종료 코드 3).

사용법
------
    set FRED_API_KEY=...
    python scripts/verify.py
    python scripts/verify.py --series cpi_index --show 20
    python scripts/verify.py --bls          # 원 통계기관 독립 대조
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core.series import ALL_SERIES, BY_ID, Series, format_value  # noqa: E402
from core.transform import apply_transform, normalize_ref_date  # noqa: E402
from fetchers import fred  # noqa: E402
from fetchers.base import FetchError  # noqa: E402

# BLS 계열 -> 우리 지표. 값은 (계열ID, 우리 지표ID, BLS 원자료의 단위 배율).
#
# BLS 는 고용을 천명, 임금을 달러, 실업률을 퍼센트로 준다. 우리 단위(thousands /
# ratio)로 맞춘 뒤 series.py 의 transform 을 그대로 적용한다. 변환 코드를
# 재사용하는 것이 핵심이다 — 여기서 다시 구현하면 같은 버그를 두 번 쓰게 된다.
# 계절조정 여부까지 series.py 와 맞춰야 한다. CPI 를 SA(CUSR…)로 잡았더니
# 29건 중 26건이 어긋났다 — 우리 cpi_index 는 의도적으로 NSA(CPIAUCNS)다.
# 이 대조가 잡아낸 첫 오류가 대조표 자신의 오류였다는 점이 이 검사의 값어치다.
BLS_SERIES: list[tuple[str, str, float]] = [
    ("CES0500000003", "avg_hourly_earnings_mom", 1.0),   # 시간당 평균임금(달러, SA)
    ("CES0000000001", "nfp", 1.0),                       # 비농업 고용(천명, SA)
    ("LNS14000000", "unemployment_rate", 1.0),           # 실업률(%, SA)
    ("CUUR0000SA0", "cpi_index", 1.0),                   # CPI-U(지수, NSA)
    ("CUUR0000SA0", "cpi_yoy", 1.0),                     # 같은 NSA 지수 -> yoy 변환 검증
]

BLS_API = "https://api.bls.gov/publicAPI/v1/timeseries/data/"


class BlsUnavailable(Exception):
    """BLS 에 물어보지 못했다 — 값이 다르다는 뜻이 아니다.

    v1 은 키 없이 쓸 수 있는 대신 **IP 당 하루 25회**다. 한도를 넘으면
    '값이 원 통계기관과 다릅니다' 로 보고되는데, 그것은 거짓말이다.
    못 물어본 것과 물어봤더니 달랐던 것은 완전히 다른 결론이므로 갈라 놓는다.
    """


def bls_levels(series_id: str, start_year: int, end_year: int) -> list[tuple[str, float]]:
    """BLS 공개 API v1 에서 월별 수준값. 키 불필요.

    값이 '-' 로 오는 달이 있다 — 2025년 10월은 미 연방정부 셧다운으로 CPI·실업률이
    아예 발표되지 않았다. 0 으로 바꾸면 안 된다. 아예 없는 것으로 둬야
    변환이 그 구간을 None 으로 남기고, 대조에서 '비교 대상 아님'으로 빠진다.
    """
    url = f"{BLS_API}{series_id}?startyear={start_year}&endyear={end_year}"
    req = urllib.request.Request(url, headers={"User-Agent": "macro-dashboard-verify"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.load(resp)
    except OSError as exc:
        raise BlsUnavailable(f"BLS 접속 실패: {exc}") from exc
    if payload.get("status") != "REQUEST_SUCCEEDED":
        msg = " ".join(payload.get("message") or []) or str(payload.get("status"))
        if "threshold" in msg:
            raise BlsUnavailable("BLS 일일 한도 초과 (키 없는 v1 은 IP 당 25회/일)")
        raise BlsUnavailable(f"BLS 응답 실패: {msg}")
    out = []
    for row in payload["Results"]["series"][0]["data"]:
        period = row["period"]
        if not period.startswith("M") or period == "M13":   # M13 은 연평균이다
            continue
        try:
            value = float(row["value"])
        except ValueError:
            continue
        out.append((f"{row['year']}-{period[1:]}-01", value))
    return sorted(out)


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


def verify_bls(conn, start_year: int, end_year: int, show: int) -> int:
    """BLS 수준값에서 우리 변환을 다시 계산해 저장된 관측치와 대조한다."""
    print("BLS 공개 API 의 원 수준값으로 우리 계열을 독립 검증합니다.")
    print("FRED 를 거치지 않으므로 계열 선택·변환이 함께 확인됩니다.\n")
    print(f"{'지표':<22}{'일치':>6}{'대상':>6}{'건너뜀':>8}   판정")
    print("-" * 70)

    # 비교 건수가 이보다 적으면 '일치'라는 말에 무게가 없다. 조용히 통과하면 안 된다.
    MIN_COMPARED = 12

    bad = 0
    unreachable = 0
    for bls_id, sid, scale in BLS_SERIES:
        s = BY_ID[sid]
        try:
            raw = bls_levels(bls_id, start_year, end_year)
        except BlsUnavailable as exc:
            print(f"{s.name_ko:<22}{'-':>6}{'-':>6}{'-':>8}   물어보지 못함: {exc}")
            unreachable += 1
            continue
        except Exception as exc:  # noqa: BLE001
            print(f"{s.name_ko:<22}{'-':>6}{'-':>6}{'-':>8}   BLS 오류: {exc}")
            bad += 1
            continue

        expect = {
            normalize_ref_date(d, s.frequency): v
            for d, v in apply_transform([(d, v * scale) for d, v in raw], s.transform)
        }
        ours = stored_values(conn, sid)
        tol = tolerance(s)

        # 전월비·전월차는 받아온 구간의 **첫 달**을 계산할 수 없다(직전 달이 없다).
        # 셧다운으로 발표 자체가 없던 달도 마찬가지다. 둘 다 '우리와 다르다'가 아니라
        # '비교 대상이 아니다' 이므로 건너뛰되, 몇 건인지는 반드시 드러낸다.
        overlap = sorted(set(expect) & set(ours))
        common = [ref for ref in overlap if expect[ref] is not None]
        skipped = len(overlap) - len(common)

        mism = [
            (ref, expect[ref], ours[ref])
            for ref in common
            if abs(expect[ref] - ours[ref]) > tol
        ]
        ok = len(common) - len(mism)

        if len(common) < MIN_COMPARED:
            bad += 1
            print(f"{s.name_ko:<22}{ok:>6}{len(common):>6}{skipped:>8}"
                  f"   비교 건수 부족 ({MIN_COMPARED}건 미만) ★")
        elif mism:
            bad += 1
            print(f"{s.name_ko:<22}{ok:>6}{len(common):>6}{skipped:>8}"
                  f"   불일치 {len(mism)}건 ★")
            for ref, e, o in mism[:show]:
                print(f"   {ref}   BLS {format_value(s, e):>12}   우리 {format_value(s, o):>12}")
        else:
            print(f"{s.name_ko:<22}{ok:>6}{len(common):>6}{skipped:>8}   일치")

    print("\n" + "=" * 70)
    print("'건너뜀' 은 BLS 쪽에 비교할 값이 없는 달입니다 —")
    print("구간 첫 달(전월비를 계산할 직전 달이 없음)과 2025-10 셧다운 미발표분입니다.")
    if unreachable:
        print(f"\n{unreachable}개 계열은 BLS 에 물어보지 못했습니다. **값이 다르다는 뜻이 아닙니다.**")
        print("키 없는 v1 은 IP 당 하루 25회입니다. 내일 다시 돌리거나 시간을 두고 재시도하세요.")
    if bad == 0 and not unreachable:
        print("모든 계열이 원 통계기관 값과 일치합니다.")
    elif bad == 0:
        print("물어본 계열은 전부 원 통계기관 값과 일치합니다.")
    else:
        print(f"{bad}개 계열이 원 통계기관 값과 다릅니다. 계열 ID 나 변환을 확인하세요.")
    # 못 물어본 것도 '검증 완료'로 통과시키면 안 된다. 다만 값 불일치와는 종료 코드를 나눈다.
    if bad:
        return 1
    return 3 if unreachable else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="엑셀 ↔ FRED 대조 검증")
    ap.add_argument("--series", help="이 지표만 검증")
    ap.add_argument("--show", type=int, default=6, help="지표당 출력할 불일치 개수")
    ap.add_argument("--offline", action="store_true",
                    help="API 를 부르지 않고 이미 수집된 DB 값과 대조한다")
    ap.add_argument("--bls", action="store_true",
                    help="BLS 공개 API 원 수준값과 대조한다 (FRED 를 거치지 않는 독립 경로)")
    ap.add_argument("--bls-years", type=int, default=5,
                    help="--bls 가 대조할 기간(년). BLS v1 은 한 번에 최대 10년이다")
    args = ap.parse_args()

    if args.bls:
        conn = db_mod.connect()
        this_year = datetime.now(timezone.utc).year
        try:
            return verify_bls(conn, this_year - args.bls_years + 1, this_year, args.show)
        finally:
            conn.close()

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
    print(f"엑셀에 남아 있는 '실제' 값과 {src}을 대조합니다.")
    print("엑셀은 손으로 다른 출처에서 옮긴 값이므로 독립적인 대조군 역할을 한다.")
    print("맞으면 계열 매핑이 옳다는 증거이고, 틀리면 (a) 매핑 오류 (b) 엑셀 입력 오류다.")
    print("과거 전체 대조 결과는 git 이력에 있다: git show a21128e:data/releases.csv\n")

    header = f"{'지표':<22}{'일치':>6}{'대상':>6}{'일치율':>8}   판정"
    print(header)
    print("-" * 70)

    total_bad = 0
    details: list[tuple[Series, list[tuple[str, float, Optional[float]]]]] = []

    for s in targets:
        excel = excel_actuals(conn, s.id)
        if not excel:
            # 권위 있는 소스가 해당 기준시점을 모두 채우면 엑셀 행은 남지 않는다.
            # 이것이 정상적인 종착점이다 — 비교할 대상이 없다는 뜻이지 문제가 아니다.
            print(f"{s.name_ko:<22}{'-':>6}{'-':>6}{'-':>8}   권위 소스가 전부 인수함")
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
