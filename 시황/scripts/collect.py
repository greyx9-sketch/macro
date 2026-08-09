# -*- coding: utf-8 -*-
"""일일 수집 진입점. GitHub Actions 가 매일 이걸 실행한다.

핵심 성질: **부분 실패는 정상 동작이다.**
CDS(headless 브라우저)가 죽어도 FRED 12종과 캘린더는 커밋되어야 한다.
따라서 어떤 소스가 실패해도 종료 코드는 0 이고, 실패 사실은 fetch_log 에 남아
대시보드의 신선도 패널에 표시된다.

종료 코드 1 은 '전부 실패' 또는 '치명적 오류' 일 때만.

사용법
------
    python scripts/collect.py                # 전체 수집
    python scripts/collect.py --only fred    # 특정 소스만
    python scripts/collect.py --dry-run      # 저장하지 않고 확인만
    python scripts/collect.py --no-cds       # CDS 건너뛰기 (로컬에서 유용)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core import store  # noqa: E402
from fetchers import calendar_ff, calendar_ff_html, cds, ecos, fred  # noqa: E402
from fetchers.base import FetchResult  # noqa: E402

# 순서가 의미를 갖는다.
#   1) 캘린더 공식 피드가 가장 먼저 — 예측·이전의 주소스다.
#   2) 캘린더 HTML 은 그 바로 뒤 — 공식 피드가 주지 않는 **실제값**만 메운다.
#      ISM 2종은 FRED 에 없어 이 경로가 유일한 실제값 소스다.
#   3) FRED/ECOS 는 언제든 다시 받을 수 있다.
#   4) CDS 는 가장 취약하므로 마지막.
SOURCES = [
    ("forexfactory", calendar_ff.collect),
    ("forexfactory_html", calendar_ff_html.collect),
    ("fred", fred.collect),
    ("ecos", ecos.collect),
    ("cds", cds.collect),
]


def staleness_check(conn) -> list[str]:
    """오래 갱신되지 않은 계열을 찾는다.

    ISM 2종이 두 달 동안 조용히 멈춰 있었는데 어떤 검사에도 안 걸렸다.
    `cross_check` 는 '들어온 값이 서로 맞는가' 만 보고, 안 들어온 것은 보지 않는다.
    """
    from datetime import datetime, timezone

    from core.series import ALL_SERIES
    from core.validate import check_staleness

    today = datetime.now(timezone.utc).date().isoformat()
    out: list[str] = []
    for s in ALL_SERIES:
        row = conn.execute(
            "SELECT MAX(ref_date) AS m FROM observations WHERE series_id = ?", (s.id,)
        ).fetchone()
        issue = check_staleness(s, row["m"] if row else None, today)
        if issue:
            out.append(str(issue))
    return out


def cross_check(conn) -> list[str]:
    """전 지표에 대해 발표 실제값과 관측치를 대조한다."""
    from core.series import ALL_SERIES
    from core.validate import check_release_vs_observation

    out: list[str] = []
    for s in ALL_SERIES:
        rel = {
            r["ref_date"]: r["actual"]
            for r in conn.execute(
                "SELECT ref_date, actual FROM releases WHERE series_id = ?", (s.id,)
            )
        }
        obs = {
            r["ref_date"]: r["value"]
            for r in conn.execute(
                "SELECT ref_date, value FROM observations WHERE series_id = ?", (s.id,)
            )
        }
        out.extend(str(i) for i in check_release_vs_observation(s, rel, obs))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="매크로 지표 일일 수집")
    ap.add_argument("--only", action="append", help="이 소스만 실행 (반복 지정 가능)")
    ap.add_argument("--no-cds", action="store_true", help="CDS 수집 건너뛰기")
    ap.add_argument("--dry-run", action="store_true", help="저장하지 않고 확인만")
    args = ap.parse_args()

    conn = db_mod.connect()

    selected = SOURCES
    if args.only:
        wanted = {n.lower() for n in args.only}
        selected = [(n, f) for n, f in SOURCES if n in wanted]
        if not selected:
            print(f"알 수 없는 소스: {args.only}", file=sys.stderr)
            return 1
    if args.no_cds:
        selected = [(n, f) for n, f in selected if n != "cds"]

    results: list[tuple[str, FetchResult]] = []

    for name, fn in selected:
        print(f"\n▶ {name}")
        log_id = None if args.dry_run else db_mod.log_start(conn, name)
        result = fn(conn, dry_run=args.dry_run)
        results.append((name, result))

        status = "ok" if result.ok else "failed"
        print(f"   {'성공' if result.ok else '실패'} — {result.message or '(메시지 없음)'}")
        for issue in result.issues:
            print(f"   · {issue}")

        if log_id is not None:
            msg = result.message
            if result.issues:
                msg += " | " + " | ".join(result.issues)
            db_mod.log_finish(conn, log_id, status, result.rows, msg)

    if not args.dry_run:
        # 소스마다 FOMC/금통위 날짜 표기가 하루씩 다르므로 병합한다.
        for line in db_mod.reconcile_event_releases(conn):
            print(f"\n▶ {line}")

        # 발표값과 관측치가 서로 크게 어긋나지 않는지 본다.
        # 단위 범위 검사로는 못 잡는 '계산 경로가 틀린' 버그를 여기서 잡는다.
        cross = cross_check(conn)
        if cross:
            print(f"\n▶ 발표값↔관측치 불일치 {len(cross)}건")
            for line in cross[:10]:
                print(f"   · {line}")
            if len(cross) > 10:
                print(f"   · … 외 {len(cross) - 10}건")

        # 값이 틀린 게 아니라 **안 들어오는** 경우를 본다.
        # 수집은 성공했으므로 종료 코드에는 반영하지 않는다 — 눈에 띄게만 한다.
        stale = staleness_check(conn)
        if stale:
            print(f"\n▶ 갱신이 멈춘 계열 {len(stale)}건")
            for line in stale:
                print(f"   · {line}")

        # 수동 오버라이드는 항상 마지막에 — 자동 수집값을 덮어써야 하므로.
        n = db_mod.apply_overrides(conn)
        if n:
            print(f"\n▶ 수동 오버라이드 {n}건 적용")

    # CSV 로 내보내기 — 이것이 커밋되는 영속 형식이다.
    if not args.dry_run:
        counts = store.dump(conn)
        print("\n▶ CSV 저장: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))

    print("\n" + "=" * 62)
    ok_count = sum(1 for _, r in results if r.ok)
    for name, r in results:
        mark = "OK  " if r.ok else "FAIL"
        print(f"  {mark} {name:14s} {r.rows:6d}행  {r.message}")
    print("=" * 62)
    print(f"{ok_count}/{len(results)} 소스 성공"
          + (" (dry-run)" if args.dry_run else ""))

    conn.commit()
    conn.close()

    # 전부 실패했을 때만 실패로 처리한다. 부분 실패는 설계상 정상.
    return 0 if ok_count > 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
