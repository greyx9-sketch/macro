# -*- coding: utf-8 -*-
"""엑셀에서 온 '실제값' 정리 — 이어붙인 계열 제거.

왜 필요한가
-----------
엑셀은 '어떤 지표를 볼지'에 대한 명세였지 재현해야 할 원본이 아니다.
그런데 백필로 들어온 엑셀 실제값이 권위 있는 소스와 섞이면서 계열을 오염시켰다.

  PPI      엑셀 값은 계절조정 전(investing.com)으로 보이는데 FRED 는 계절조정.
           그대로 두면 과거만 NSA 인 이어붙인 계열이 된다.
  10Y-2Y   엑셀 날짜가 어긋나 있다 — 2026-07-03, 2026-06-19 는 미국 휴장일이라
           FRED 에 호가 자체가 없는데 엑셀에는 값이 있다.
  CDS 2종  worldgovernmentbonds 가 2007년부터 보유. 날짜 규약도 다르다.

규칙 — '권위 소스가 그 날짜를 인정하지 않으면 지운다'
--------------------------------------------------
처음에는 '자동 소스가 있으면 엑셀 실제값을 전부 지운다'는 규칙을 쓰려 했다.
실제 데이터로 확인해 보니 **그 규칙은 너무 거칠어서 멀쩡한 데이터를 지운다.**

  신규 실업수당  엑셀 187 vs FRED 현재값 188 — 오염이 아니라 개정이다.
                FRED vintage 가 최초발표값을 187 로 확인해 줬다. 지워선 안 된다.
  기준금리       엑셀 행은 금리가 바뀌지 않은 FOMC·금통위 날짜다.
                값 충돌이 0건이고, 자동 소스에는 없는 '회의가 열렸다'는 정보를 더한다.

남는 진짜 문제는 **권위 있는 소스가 그 날짜에 값을 갖고 있지 않은 행**뿐이다.
그건 날짜 자체가 틀렸다는 뜻이다.

  10Y-2Y   2026-07-03, 2026-06-19 — 미국 휴장일이라 FRED 에 호가가 없다
  CDS      worldgovernmentbonds 이력에 없는 날짜

  유지  ISM 제조업/서비스업 — FRED 에 없어서 엑셀이 유일한 과거 실제값이다.

**예측·이전은 절대 건드리지 않는다.** ForexFactory 는 지난 주를 다시 주지 않으므로
과거 컨센서스는 엑셀이 세상에 남은 유일한 출처이고, 서프라이즈 계산의 근거다.

사용법
------
    python scripts/prune_excel_actuals.py --dry-run   # 무엇을 지울지 먼저 확인
    python scripts/prune_excel_actuals.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import db as db_mod  # noqa: E402
from core import store  # noqa: E402
from core.series import ALL_SERIES, format_value  # noqa: E402

# 엑셀 실제값을 유지할 지표 — 자동 소스가 과거 실제값을 주지 못하는 것들.
KEEP_EXCEL_ACTUALS = {s.id for s in ALL_SERIES
                      if s.fred_id is None and s.ecos_stat is None and s.cds_country is None}


def has_authoritative_source(series_id: str) -> bool:
    return series_id not in KEEP_EXCEL_ACTUALS


def main() -> int:
    ap = argparse.ArgumentParser(description="엑셀 실제값 정리")
    ap.add_argument("--dry-run", action="store_true", help="지우지 않고 보고만 한다")
    args = ap.parse_args()

    conn = db_mod.connect()

    # ---- 안전장치: 예측 건수를 미리 세어 두고 마지막에 대조한다 ----------
    def forecast_count() -> int:
        return conn.execute(
            "SELECT COUNT(*) c FROM releases WHERE forecast IS NOT NULL"
        ).fetchone()["c"]

    def previous_count() -> int:
        return conn.execute(
            "SELECT COUNT(*) c FROM releases WHERE previous IS NOT NULL"
        ).fetchone()["c"]

    before_fc, before_pv = forecast_count(), previous_count()
    print(f"정리 전 — 예측 {before_fc:,}건 / 이전 {before_pv:,}건")
    print("(이 두 숫자는 정리 후에도 같아야 한다. 줄면 복구 불가능한 데이터를 지운 것이다.)\n")

    total_cleared = 0
    total_deleted = 0

    for s in ALL_SERIES:
        if not has_authoritative_source(s.id):
            n = conn.execute(
                "SELECT COUNT(*) c FROM releases WHERE series_id = ? AND source = 'excel'"
                " AND actual IS NOT NULL", (s.id,)
            ).fetchone()["c"]
            print(f"  유지  {s.name_ko:<20} 엑셀 실제값 {n}건 "
                  f"(자동 소스 없음 — 유일한 과거 데이터)")
            continue

        rows = conn.execute(
            "SELECT ref_date, actual, forecast, previous FROM releases"
            " WHERE series_id = ? AND source = 'excel' AND actual IS NOT NULL"
            " ORDER BY ref_date DESC",
            (s.id,),
        ).fetchall()
        if not rows:
            continue

        # 권위 있는 소스가 이 기준시점에 값을 갖고 있는가?
        known = {
            r["ref_date"] for r in conn.execute(
                "SELECT ref_date FROM observations"
                " WHERE series_id = ? AND source != 'excel' AND value IS NOT NULL",
                (s.id,),
            )
        }
        orphans = [r for r in rows if r["ref_date"] not in known]

        if not orphans:
            print(f"  유지  {s.name_ko:<20} 엑셀 실제값 {len(rows)}건 "
                  f"(자동 소스가 모두 인정하는 날짜 — 개정 차이일 뿐 오염 아님)")
            continue

        # 예측/이전이 함께 들어 있는 행은 실제값만 비우고 행은 남긴다.
        keep_rows = [r for r in orphans if r["forecast"] is not None or r["previous"] is not None]
        drop_rows = [r for r in orphans if r["forecast"] is None and r["previous"] is None]

        sample = ", ".join(
            f"{r['ref_date']}={format_value(s, r['actual'])}" for r in orphans[:4]
        )
        print(f"  정리  {s.name_ko:<20} {len(orphans)}/{len(rows)}건이 자동 소스에 없는 날짜 "
              f"(실제값만 비움 {len(keep_rows)} / 행 삭제 {len(drop_rows)})")
        print(f"        {sample}")

        if not args.dry_run:
            conn.executemany(
                "UPDATE releases SET actual = NULL, updated_at = ?"
                " WHERE series_id = ? AND ref_date = ?",
                [(db_mod.utcnow(), s.id, r["ref_date"]) for r in keep_rows],
            )
            conn.executemany(
                "DELETE FROM releases WHERE series_id = ? AND ref_date = ?",
                [(s.id, r["ref_date"]) for r in drop_rows],
            )
            # 같은 날짜의 엑셀 관측치도 제거한다 (차트가 없는 날짜에 점을 찍지 않도록).
            conn.executemany(
                "DELETE FROM observations WHERE series_id = ? AND ref_date = ? AND source = 'excel'",
                [(s.id, r["ref_date"]) for r in orphans],
            )
        total_cleared += len(keep_rows)
        total_deleted += len(drop_rows)

    if not args.dry_run:
        conn.commit()

    after_fc, after_pv = forecast_count(), previous_count()
    print("\n" + "=" * 66)
    print(f"실제값 비움 {total_cleared:,}건 / 행 삭제 {total_deleted:,}건"
          + (" (dry-run, 저장 안 함)" if args.dry_run else ""))
    print(f"정리 후 — 예측 {after_fc:,}건 / 이전 {after_pv:,}건")

    ok = (after_fc == before_fc and after_pv == before_pv)
    if ok:
        print("✔ 예측·이전이 그대로 보존되었습니다.")
    else:
        print(f"✘ 경고: 예측 {before_fc - after_fc:+,}건, 이전 {before_pv - after_pv:+,}건 변동!")
        print("  복구 불가능한 데이터가 사라졌을 수 있습니다. git 으로 되돌리세요.")

    if not args.dry_run:
        store.dump(conn)
        print("\nCSV 갱신 완료")
    conn.close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
