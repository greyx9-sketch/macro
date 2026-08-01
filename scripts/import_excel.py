# -*- coding: utf-8 -*-
"""엑셀 `매크로 머티리얼.xlsm` 1회 백필 임포터.

왜 필요한가
-----------
ForexFactory 는 이번 주 데이터만 준다. 즉 **과거 예측(컨센서스)·ISM·CDS 는
이 엑셀이 세상에 남은 유일한 출처**다. FRED 로 실제값은 언제든 다시 받을 수 있지만
컨센서스는 다시 받을 수 없다.

무엇을 넣는가
-------------
releases      : 전 지표의 (발표일, 실제, 예측, 이전)
observations  : FRED/ECOS 로 못 받는 지표(ISM 2종, CDS 2종)만.
                나머지는 FRED 가 권위 있는 소스이므로 엑셀 값으로 오염시키지 않는다.

무엇을 고치는가
---------------
원본에 실재하는 입력 오류를 정정하고 전부 보고한다.
  - 날짜 열에 섞인 엑셀 일련번호 (46204, 46233, 46240 …)
  - 숫자 열에 섞인 '187K' 같은 문자열
  - 기준시점 중복 (발표월 2025-12 가 두 번 등)
조용히 고치지 않는다. 무엇을 어떻게 바꿨는지 전부 출력한다.

사용법
------
    python scripts/import_excel.py "C:\\Users\\greyx\\Desktop\\매크로 머티리얼.xlsm"
    python scripts/import_excel.py <경로> --dry-run     # DB 를 건드리지 않고 보고만
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core import xlsx  # noqa: E402
from core.series import BY_ID, Series  # noqa: E402
from core.transform import normalize_ref_date  # noqa: E402
from fetchers.base import parse_raw_number, to_series_unit  # noqa: E402
from fetchers.calendar_ff import derive_ref_date  # noqa: E402

SOURCE = "excel"

# 시트 row3 의 출처 URL 로 지표를 식별한다. 지표명 텍스트보다 안정적이다.
URL_TO_SERIES = {
    "cpi-index,-n.s.a.-1549": "cpi_index",
    "cpi-733": "cpi_yoy",
    "ppi-238": "ppi_index",
    "pce-price-index-906": "pce_yoy",
    "core-pce-price-index-905": "core_pce_yoy",
    "nonfarm-payrolls-227": "nfp",
    "unemployment-rate-300": "unemployment_rate",
    "average-hourly-earnings-8": "avg_hourly_earnings_mom",
    "initial-jobless-claims-294": "initial_claims",
    "jolts-job-openings-1057": "jolts",
    "ism-manufacturing-pmi-173": "ism_manufacturing",
    "ism-non-manufacturing-pmi-176": "ism_services",
    "interest-rate-decision-168": "fed_funds_upper",
    "interest-rate-decision-473": "bok_base_rate",
    "series/T10Y2Y": "t10y2y",
    "united-states-cds-5-years": "cds_us_5y",
    "south-korea-cds-5-year": "cds_kr_5y",
}

HEADER_ROW = 5
FIRST_DATA_ROW = 7
URL_ROW = 3

ROLE_BY_HEADER = {
    "발표월": "release",
    "발표일": "release",
    "날짜": "release",
    "기준월": "ref",
    "실제": "actual",
    "예측": "forecast",
    "이전": "previous",
    "이전(수정)": "previous",
    "변동%": "skip",  # 실제/이전으로 계산 가능하므로 저장하지 않는다
}


class Report:
    """정정 내역과 이상 징후 수집."""

    def __init__(self) -> None:
        self.fixed_serial: list[str] = []
        self.fixed_text: list[str] = []
        self.duplicates: list[str] = []
        self.unparsed: list[str] = []
        self.range_flags: list[str] = []

    def any(self) -> bool:
        return bool(
            self.fixed_serial or self.fixed_text or self.duplicates
            or self.unparsed or self.range_flags
        )


# ---------------------------------------------------------------------------
# 셀 해석
# ---------------------------------------------------------------------------
def read_date(sheet: xlsx.Sheet, ref: str, rep: Report) -> Optional[str]:
    """날짜 셀 -> ISO 문자열. 일련번호·'2026-08'·'2026-07-23' 모두 처리."""
    cell = sheet.cells.get(ref)
    if cell is None or cell.value is None:
        return None

    if not cell.is_text:  # 숫자 = 엑셀 날짜 일련번호
        try:
            d = xlsx.serial_to_date(float(cell.value))
        except (ValueError, OverflowError):
            rep.unparsed.append(f"{sheet.name}!{ref}: 날짜 일련번호 해석 실패 ({cell.value!r})")
            return None
        rep.fixed_serial.append(
            f"{sheet.name}!{ref}: 일련번호 {int(cell.value)} -> {d.isoformat()}"
        )
        return d.isoformat()

    text = str(cell.value).strip()
    if not text or text == "—":
        return None
    if len(text) == 7 and text[4] == "-":
        # '2026-08' — 엑셀의 발표월은 애초에 월 단위 정보다.
        # '2026-08-01' 로 바꾸면 8월 1일에 발표된다는 거짓 정보가 되므로
        # 7자리 그대로 두어 정밀도를 자기서술적으로 유지한다.
        return text
    if len(text) == 10 and text[4] == "-":    # '2026-07-23'
        return text
    # '6월' 처럼 날짜가 아닌 라벨 — 오류가 아니라 원본의 표기 방식이다.
    return None


def read_value(sheet: xlsx.Sheet, ref: str, s: Series, rep: Report) -> Optional[float]:
    """값 셀 -> 저장 단위 숫자. '187K' 같은 문자열도 처리."""
    cell = sheet.cells.get(ref)
    if cell is None or cell.value is None:
        return None

    if not cell.is_text:
        return float(cell.value)

    text = str(cell.value).strip()
    if not text or text in {"—", "-", "N/A"}:
        return None

    value = to_series_unit(s.unit, parse_raw_number(text))
    if value is None:
        rep.unparsed.append(f"{sheet.name}!{ref}: 값 해석 실패 ({text!r})")
        return None
    rep.fixed_text.append(f"{sheet.name}!{ref}: 문자열 {text!r} -> {value}")
    return value


# ---------------------------------------------------------------------------
# 블록 탐지
# ---------------------------------------------------------------------------
def find_blocks(sheet: xlsx.Sheet) -> list[tuple[str, dict[str, str]]]:
    """시트에서 (series_id, {역할: 열문자}) 목록을 뽑는다.

    3행의 URL 로 지표를 식별하고, 5행의 헤더로 각 열의 역할을 정한다.
    열 위치를 하드코딩하지 않으므로 시트 구조가 조금 달라져도 견딘다.

    ★ 블록 경계는 반드시 '다음 URL 열' 로 끊는다.
      블록마다 열 개수가 다르고(10Y-2Y 는 2열, CDS 는 4열) 중간에 빈 열도 있어서
      고정 폭으로 훑으면 옆 블록을 침범한다. 실제로 그 버그 때문에
      미국 CDS 의 '이전'(36.85bp)이 10Y-2Y 금리차의 '이전'으로 들어갔다.
    """
    # 1) 지표가 시작되는 열들을 순서대로 찾는다.
    starts: list[tuple[int, str, str]] = []  # (열인덱스, 열문자, series_id)
    for ref, cell in sheet.cells.items():
        row = int("".join(ch for ch in ref if ch.isdigit()) or 0)
        if row != URL_ROW or not cell.is_text:
            continue
        sid = next((v for k, v in URL_TO_SERIES.items() if k in str(cell.value)), None)
        if sid is None:
            continue
        col = xlsx.col_letters(ref)
        starts.append((xlsx.col_index(col), col, sid))
    starts.sort()

    # 2) 각 블록의 열 범위 = [자기 시작열, 다음 블록 시작열)
    blocks: list[tuple[str, dict[str, str]]] = []
    for i, (start_idx, _start_col, sid) in enumerate(starts):
        end_idx = starts[i + 1][0] if i + 1 < len(starts) else start_idx + 8

        roles: dict[str, str] = {}
        for idx in range(start_idx, end_idx):
            col = xlsx.index_to_col(idx)
            header = sheet.text(f"{col}{HEADER_ROW}")
            if header is None:
                continue
            role = ROLE_BY_HEADER.get(header.strip())
            if role and role != "skip" and role not in roles:
                roles[role] = col

        if "actual" in roles or "release" in roles:
            blocks.append((sid, roles))

    return blocks


# ---------------------------------------------------------------------------
# 임포트
# ---------------------------------------------------------------------------
def import_block(
    conn, sheet: xlsx.Sheet, sid: str, roles: dict[str, str], rep: Report, dry_run: bool
) -> int:
    s = BY_ID[sid]
    last_row = sheet.max_row()
    seen: dict[str, int] = {}
    written = 0

    for row in range(FIRST_DATA_ROW, last_row + 1):
        release_iso = read_date(sheet, f"{roles['release']}{row}", rep) if "release" in roles else None
        ref_iso = read_date(sheet, f"{roles['ref']}{row}", rep) if "ref" in roles else None

        # 월간 지표의 '발표월' 열은 본래 월 단위다. 셀에 일련번호가 섞여 들어온 경우
        # (원본 오류로 이미 보고됨) 완전한 날짜로 해석되는데, 그대로 두면
        # '8월 1일에 발표' 라는 없는 정보를 만들어낸다. 월 정밀도로 되돌린다.
        if s.frequency == "monthly" and release_iso and len(release_iso) == 10:
            release_iso = release_iso[:7]

        actual = read_value(sheet, f"{roles['actual']}{row}", s, rep) if "actual" in roles else None
        forecast = read_value(sheet, f"{roles['forecast']}{row}", s, rep) if "forecast" in roles else None
        previous = read_value(sheet, f"{roles['previous']}{row}", s, rep) if "previous" in roles else None

        if release_iso is None and ref_iso is None:
            continue  # 빈 행
        if actual is None and forecast is None and previous is None:
            continue  # 날짜만 있고 값이 없는 행은 넣지 않는다

        # --- 기준시점 결정 -------------------------------------------------
        if ref_iso:
            ref_date = normalize_ref_date(ref_iso, s.frequency)
        elif s.frequency == "weekly" and release_iso and len(release_iso) == 10:
            # 주간 청구건수: 엑셀은 발표일(목)만 있고 기준주가 없다.
            # FRED ICSA 규약(토요일로 끝나는 주)에 맞춰 역산한다.
            ref_date = derive_ref_date(s, datetime.fromisoformat(release_iso))
        elif release_iso and (s.frequency == "monthly" or len(release_iso) == 10):
            # 월간이면 7자리도 정규화된다. 그 외 주기는 완전한 날짜가 있어야 한다.
            ref_date = normalize_ref_date(release_iso, s.frequency)
        else:
            rep.unparsed.append(
                f"{s.name_ko} {row}행: 기준시점을 정할 수 없음 (발표={release_iso!r})"
            )
            continue

        seen[ref_date] = seen.get(ref_date, 0) + 1

        # --- 상식 범위 점검 -------------------------------------------------
        from core.validate import check_range
        for label, v in (("실제", actual), ("예측", forecast), ("이전", previous)):
            issue = check_range(s, ref_date, v)
            if issue:
                rep.range_flags.append(f"{s.name_ko} {label} {issue.detail}")

        if not dry_run:
            db_mod.upsert_release(
                conn, sid, ref_date,
                release_date=release_iso,
                actual=actual, forecast=forecast, previous=previous,
                source=SOURCE,
            )
            # FRED/ECOS 로 못 받는 지표만 관측치까지 채운다.
            if s.fred_id is None and s.ecos_stat is None and actual is not None:
                db_mod.upsert_observation(conn, sid, ref_date, actual, SOURCE)
        written += 1

    for ref_date, n in sorted(seen.items()):
        if n > 1:
            rep.duplicates.append(f"{s.name_ko}: 기준시점 {ref_date} 이 {n}회 중복 — 원본 확인 필요")

    return written


def main() -> int:
    ap = argparse.ArgumentParser(description="매크로 머티리얼 엑셀 백필 임포터")
    ap.add_argument("path", nargs="?",
                    default=r"C:\Users\greyx\Desktop\매크로 머티리얼.xlsm")
    ap.add_argument("--dry-run", action="store_true", help="DB 를 건드리지 않고 보고만 한다")
    args = ap.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"파일을 찾을 수 없습니다: {path}", file=sys.stderr)
        return 1

    sheets = xlsx.load(path)
    rep = Report()
    conn = None if args.dry_run else db_mod.connect()

    print(f"엑셀 임포트: {path.name}")
    print(f"시트: {', '.join(sheets)}")
    print()

    total = 0
    found: set[str] = set()
    for name, sheet in sheets.items():
        blocks = find_blocks(sheet)
        if not blocks:
            continue
        print(f"[{name}]")
        for sid, roles in blocks:
            found.add(sid)
            n = import_block(conn, sheet, sid, roles, rep, args.dry_run)
            total += n
            cols = " ".join(f"{k}={v}" for k, v in roles.items())
            print(f"  {BY_ID[sid].name_ko:22s} {n:4d}행   ({cols})")
        print()

    missing = sorted(set(BY_ID) - found)
    if missing:
        print("⚠ 엑셀에서 찾지 못한 지표:", ", ".join(BY_ID[m].name_ko for m in missing))
        print()

    # ---- 정정 및 이상 보고 -------------------------------------------------
    print("=" * 70)
    print(f"총 {total}행 임포트" + (" (dry-run, 저장 안 함)" if args.dry_run else ""))
    print("=" * 70)

    def section(title: str, items: list[str], limit: int = 30) -> None:
        if not items:
            return
        print(f"\n■ {title} ({len(items)}건)")
        for line in items[:limit]:
            print(f"   - {line}")
        if len(items) > limit:
            print(f"   … 외 {len(items) - limit}건")

    section("날짜 일련번호 정정", rep.fixed_serial)
    section("문자열 값 정정", rep.fixed_text)
    section("기준시점 중복 (원본 오류)", rep.duplicates)
    section("상식 범위 이탈", rep.range_flags)
    section("해석 실패 (건너뜀)", rep.unparsed)

    if not rep.any():
        print("\n이상 없음.")

    if conn is not None:
        conn.commit()
        merged = db_mod.reconcile_event_releases(conn)
        if merged:
            print(f"\n■ 이벤트 발표일 병합 ({len(merged)}건)")
            for line in merged:
                print(f"   - {line}")

        from core import store
        counts = store.dump(conn)
        print("\n■ CSV 저장 " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
        conn.close()
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
