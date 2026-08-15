# -*- coding: utf-8 -*-
"""ForexFactory 과거 주 백필 — ISM 역사 복구용 1회성 스크립트.

왜 필요한가
-----------
공식 피드(`ff_calendar_thisweek.json`)는 이번 주치만 주고 **실제값을 아예 주지 않는다.**
그래서 ISM 2종은 프로젝트 시작 이래 자동 수집된 값이 하나도 없었고, 남아 있는 22건은
전부 엑셀 백필이다.

캘린더 웹페이지는 `?week=aug3.2026` 형태로 **과거 주를 돌려준다.** 실측으로
2020-03 까지 정상 응답을 확인했고 값도 맞다(2020-02 ISM 제조업 50.1).
즉 README 가 여러 곳에서 전제해 온 "놓친 주는 영원히 복구할 수 없다" 가
더 이상 사실이 아니다.

무엇을 받는가
-------------
**월 첫 두 주만** 받는다. ISM 은 매월 1·3영업일에 나오므로 그 안에 다 들어온다.
6년치가 약 150주다. 전 주를 받으면 5배가 되는데, 나머지 계열의 실제값은
FRED 가 권위 소스라 얻을 게 거의 없다.

그 대가로 **월 중순·말일 발표는 이 규칙에 구조적으로 안 걸린다.** 실제로 미시간대
(예비치 중순 · 확정치 말일) 2026-07 이 그렇게 빠졌다. 그런 구멍은 자동 생성 규칙을
넓히지 말고 `--weeks` 로 해당 주를 콕 집어 받는다 — 규칙을 넓히면 매번 5배를 받게 된다.

지키는 것
---------
- 요청 사이 `SLEEP` 초 이상 쉰다. 한 번에 몰아 받지 않는다.
- 이미 받은 주는 건너뛴다 — 재실행해도 안전하고, 중단된 지점부터 이어진다.
- **기존 예측·이전 값을 덮지 않는다.** `upsert_release` 의 병합 규칙(빈 값으로
  덮지 않음)에 더해, 이 스크립트는 아예 `--fill-only` 로 빈 칸만 채운다.
  `prune_excel_actuals.py` 의 "예측·이전은 절대 건드리지 않는다" 원칙을 그대로 따른다.

사용법
------
    python scripts/backfill_ff_weeks.py --from 2020-01 --dry-run
    python scripts/backfill_ff_weeks.py --from 2020-01

    # 특정 주만 (월요일 날짜). 이미 이벤트가 들어와 있는 주는 --force 가 필요하다.
    python scripts/backfill_ff_weeks.py --weeks 2026-07-13,2026-07-27 --force
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core import store  # noqa: E402
from fetchers import calendar_ff_html as ffh  # noqa: E402

SLEEP = 3.0          # 요청 간 최소 간격(초)
MAX_FAILS = 5        # 연속 실패가 이만큼이면 멈춘다 — 차단당한 채로 계속 두드리지 않는다


def target_weeks(start: date, end: date) -> list[date]:
    """각 월의 1일과 8일이 속한 주의 월요일. ISM 발표주를 덮는다."""
    out: list[date] = []
    y, m = start.year, start.month
    while date(y, m, 1) <= end:
        for day in (1, 8):
            d = date(y, m, day)
            if d > end:
                continue
            monday = d - timedelta(days=d.weekday())
            if monday not in out:
                out.append(monday)
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return out


def explicit_weeks(spec: str) -> list[date]:
    """'2026-07-13,2026-07-27' -> 그 주의 월요일 목록.

    월요일이 아닌 날짜를 줘도 그 날이 속한 주의 월요일로 맞춘다 —
    발표일(7/17·7/31)을 그대로 붙여 넣는 쪽이 사람에게 자연스럽기 때문이다.
    """
    out: list[date] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        d = date.fromisoformat(part)
        monday = d - timedelta(days=d.weekday())
        if monday not in out:
            out.append(monday)
    if not out:
        raise ValueError("--weeks 에 유효한 날짜가 없습니다")
    return sorted(out)


def already_have(conn, monday: date) -> bool:
    """그 주의 원본 이벤트를 이미 받아 뒀는가."""
    lo = monday.isoformat()
    hi = (monday + timedelta(days=7)).isoformat()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM calendar_events WHERE event_time >= ? AND event_time < ?",
        (lo, hi),
    ).fetchone()["n"]
    return n > 0


def main() -> int:
    ap = argparse.ArgumentParser(description="ForexFactory 과거 주 백필")
    ap.add_argument("--from", dest="start", default="2020-01", help="시작 월 (YYYY-MM)")
    ap.add_argument("--to", dest="end", default=None, help="끝 월 (YYYY-MM, 기본=이번 달)")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 확인만")
    ap.add_argument("--limit", type=int, default=0, help="이번 실행에서 받을 최대 주 수")
    ap.add_argument("--force", action="store_true", help="이미 받은 주도 다시 받는다")
    ap.add_argument("--weeks", default=None,
                    help="특정 주만 받는다. 날짜를 쉼표로 (YYYY-MM-DD). --from/--to 를 무시한다")
    args = ap.parse_args()

    conn = db_mod.connect()
    if args.weeks:
        weeks = explicit_weeks(args.weeks)
    else:
        start = date(int(args.start[:4]), int(args.start[5:7]), 1)
        end = date.today() if not args.end else date(int(args.end[:4]), int(args.end[5:7]), 28)
        weeks = target_weeks(start, end)
    todo = [w for w in weeks if args.force or not already_have(conn, w)]
    if args.limit:
        todo = todo[: args.limit]

    print(f"대상 주 {len(weeks)}개 중 {len(todo)}개를 받습니다 "
          f"(간격 {SLEEP}초, 예상 {len(todo) * SLEEP / 60:.0f}분)")
    if not todo:
        print("이미 전부 받아 두었습니다.")
        return 0

    ok = fails = 0
    consecutive = 0
    total_actual = 0
    for i, monday in enumerate(todo, 1):
        token = ffh.week_token(monday)
        try:
            html, via = ffh.fetch_week_html(token)
            days = ffh.parse_days(html)
        except Exception as exc:  # noqa: BLE001 — 한 주가 실패해도 다음 주로 간다
            fails += 1
            consecutive += 1
            print(f"  [{i}/{len(todo)}] {token:14} 실패 — {type(exc).__name__}: {exc}")
            if consecutive >= MAX_FAILS:
                print(f"\n연속 {MAX_FAILS}회 실패 — 차단됐을 가능성이 큽니다. 중단합니다.")
                print("시간을 두고 다시 실행하면 받은 주는 건너뛰고 이어서 진행합니다.")
                break
            time.sleep(SLEEP)
            continue

        consecutive = 0
        # fill_only — 이미 있는 값은 절대 덮지 않는다. 엑셀에서 온 발표 당시
        # 컨센서스를 지금 렌더링된 값으로 바꿔치기하면 서프라이즈 계산이 통째로 흔들린다.
        stored, mapped, with_actual = ffh.store_week(
            conn, days, dry_run=args.dry_run, fill_only=True
        )
        total_actual += with_actual
        ok += 1
        # fill_only 라 '매핑' 은 곧 **새로 채운 칸**이다. 이미 값이 있던 칸은 세지 않는다.
        print(f"  [{i}/{len(todo)}] {token:14} {via:10} 원본 {stored:3} · 새로 채움 {mapped:2} · 그중 실제값 {with_actual:2}")

        if i < len(todo):
            time.sleep(SLEEP)

    print(f"\n{ok}주 성공 / {fails}주 실패 · 실제값 {total_actual}건")
    if not args.dry_run and ok:
        counts = store.dump(conn)
        print("CSV 저장: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
