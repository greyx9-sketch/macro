# -*- coding: utf-8 -*-
"""영속 저장은 CSV, 작업은 SQLite.

왜 SQLite 파일을 커밋하지 않는가
--------------------------------
처음에는 `data/macro.sqlite` 를 그대로 커밋하려 했다. 하지만 CDS 전체 이력을
받고 나니 파일이 수 MB 가 됐고, git 은 바이너리를 델타 압축하지 못해
**커밋마다 전체 복사본**을 저장한다. 하루 두 번 × 1년이면 수백 MB 다.

CSV 로 저장하면
  - 하루치 변경이 몇 줄짜리 diff 로 남는다 (git 이 텍스트를 델타 압축한다)
  - `git log -p data/observations.csv` 가 **사람이 읽을 수 있는 수정치 감사 로그**가 된다
    — 원래 목표였던 '개정 추적'이 여기서 진짜로 완성된다
  - SQLite 는 언제든 CSV 에서 재생성 가능한 파생물이 된다

정렬을 고정하는 것이 핵심이다. 행 순서가 흔들리면 diff 가 무의미해진다.
"""

from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# (테이블, 열, 정렬 기준). 정렬은 반드시 결정적이어야 diff 가 안정적이다.
TABLES: list[tuple[str, list[str], str]] = [
    ("observations",
     ["series_id", "ref_date", "value", "source", "updated_at"],
     "series_id, ref_date"),
    ("releases",
     ["series_id", "ref_date", "release_date", "actual", "forecast", "previous",
      "source", "updated_at"],
     "series_id, ref_date"),
    ("revisions",
     ["series_id", "ref_date", "observed_at", "old_value", "new_value", "source"],
     "series_id, ref_date, observed_at"),
    ("calendar_events",
     ["event_key", "title", "country", "event_time", "impact",
      "actual_raw", "forecast_raw", "previous_raw", "first_seen", "last_seen"],
     "event_time, country, title"),
    ("manual_overrides",
     ["series_id", "ref_date", "field", "value", "reason", "created_at"],
     "series_id, ref_date, field"),
]

# fetch_log 는 무한히 늘어나므로 최근 것만 남긴다. UI 신선도 패널이 쓰는 용도라 충분하다.
LOG_KEEP = 200


def csv_path(table: str) -> Path:
    return DATA_DIR / f"{table}.csv"


def dump(conn: sqlite3.Connection) -> dict[str, int]:
    """DB -> CSV. 커밋 대상 파일을 갱신한다."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    counts: dict[str, int] = {}

    for table, cols, order in TABLES:
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM {table} ORDER BY {order}"
        ).fetchall()
        # newline='' 은 csv 모듈 규약. 줄바꿈은 '\n' 으로 고정해 OS 간 diff 잡음을 없앤다.
        with csv_path(table).open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(cols)
            w.writerows(rows)
        counts[table] = len(rows)

    log_cols = ["source", "started_at", "finished_at", "status", "rows", "message"]
    log_rows = conn.execute(
        f"SELECT {', '.join(log_cols)} FROM fetch_log"
        f" ORDER BY id DESC LIMIT {LOG_KEEP}"
    ).fetchall()
    with csv_path("fetch_log").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(log_cols)
        w.writerows(reversed(log_rows))
    counts["fetch_log"] = len(log_rows)

    return counts


def load(conn: sqlite3.Connection) -> dict[str, int]:
    """CSV -> DB. 저장소를 새로 클론했을 때 작업용 DB 를 복원한다."""
    counts: dict[str, int] = {}

    for table, cols, _order in TABLES:
        path = csv_path(table)
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = [
                tuple(None if r.get(c) in ("", None) else r.get(c) for c in cols)
                for r in reader
            ]
        if rows:
            conn.executemany(
                f"INSERT OR REPLACE INTO {table} ({', '.join(cols)})"
                f" VALUES ({', '.join('?' * len(cols))})",
                rows,
            )
        counts[table] = len(rows)

    log_path = csv_path("fetch_log")
    if log_path.exists():
        log_cols = ["source", "started_at", "finished_at", "status", "rows", "message"]
        with log_path.open(newline="", encoding="utf-8") as f:
            rows = [
                tuple(None if r.get(c) in ("", None) else r.get(c) for c in log_cols)
                for r in csv.DictReader(f)
            ]
        if rows:
            conn.executemany(
                f"INSERT INTO fetch_log ({', '.join(log_cols)})"
                f" VALUES ({', '.join('?' * len(log_cols))})",
                rows,
            )
        counts["fetch_log"] = len(rows)

    conn.commit()
    return counts


def csv_newer_than(db_path: Path) -> bool:
    """커밋된 CSV 가 작업용 DB 보다 새로운가.

    `git pull` 로 새 데이터를 받으면 CSV 만 갱신되고 SQLite 는 그대로다.
    이걸 확인하지 않으면 화면이 조용히 옛 데이터를 보여준다.
    """
    if not db_path.exists():
        return True
    db_mtime = db_path.stat().st_mtime
    return any(
        p.exists() and p.stat().st_mtime > db_mtime + 1  # 1초 여유
        for p in (csv_path(t) for t, _c, _o in TABLES)
    )


def is_empty(conn: sqlite3.Connection) -> bool:
    for table in ("observations", "releases", "calendar_events"):
        if conn.execute(f"SELECT 1 FROM {table} LIMIT 1").fetchone():
            return False
    return True
