# -*- coding: utf-8 -*-
"""SQLite 접근 계층.

여기서만 쓰기가 일어난다. 모든 쓰기는
  - 값이 실제로 바뀔 때만 updated_at 을 갱신하고
  - 바뀌었다면 revisions 에 흔적을 남긴다.
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from . import series as series_mod

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "macro.sqlite"
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"

# 부동소수 비교 허용오차. 이보다 작은 차이는 개정으로 치지 않는다.
EPSILON = 1e-9


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Optional[Path] = None, *, autoload: bool = True) -> sqlite3.Connection:
    """작업용 SQLite 연결.

    SQLite 파일은 커밋 대상이 아니라 CSV 에서 재생성되는 파생물이다(core/store.py 참조).
    비어 있으면 커밋된 CSV 에서 자동 복원한다 — 저장소를 새로 클론했거나
    GitHub Actions 러너처럼 매번 빈 상태로 시작하는 환경을 위해서다.
    """
    from . import store

    db_path = path or DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    sync_series(conn)

    if autoload and store.is_empty(conn):
        store.load(conn)

    return conn


def sync_series(conn: sqlite3.Connection) -> None:
    """core/series.py 의 정의를 DB 에 반영. 정의가 유일한 진실이다."""
    rows = [
        (s.id, s.name_ko, s.category, s.unit, s.frequency, s.decimals, s.note)
        for s in series_mod.ALL_SERIES
    ]
    conn.executemany(
        """
        INSERT INTO series (id, name_ko, category, unit, frequency, decimals, note)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name_ko   = excluded.name_ko,
            category  = excluded.category,
            unit      = excluded.unit,
            frequency = excluded.frequency,
            decimals  = excluded.decimals,
            note      = excluded.note
        """,
        rows,
    )
    conn.commit()


def _changed(old: Optional[float], new: Optional[float]) -> bool:
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    return abs(old - new) > EPSILON


# ---------------------------------------------------------------------------
# observations
# ---------------------------------------------------------------------------
def upsert_observation(
    conn: sqlite3.Connection,
    series_id: str,
    ref_date: str,
    value: Optional[float],
    source: str,
) -> str:
    """반환값: 'inserted' | 'revised' | 'unchanged'.

    값이 바뀐 경우에만 revisions 에 기록한다. 이것이 수정치 추적의 근거가 된다.
    """
    now = utcnow()
    row = conn.execute(
        "SELECT value, source FROM observations WHERE series_id = ? AND ref_date = ?",
        (series_id, ref_date),
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO observations (series_id, ref_date, value, source, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (series_id, ref_date, value, source, now),
        )
        return "inserted"

    old = row["value"]
    if not _changed(old, value):
        return "unchanged"

    conn.execute(
        "UPDATE observations SET value = ?, source = ?, updated_at = ?"
        " WHERE series_id = ? AND ref_date = ?",
        (value, source, now, series_id, ref_date),
    )

    # ★ 소스가 바뀐 경우는 '개정'이 아니라 '출처 교체'다. ★
    # 엑셀(investing.com)과 worldgovernmentbonds 는 같은 CDS 를 하루씩 다른 날짜에
    # 붙여 놓기 때문에, 구분하지 않으면 개정 로그가 출처 차이로만 가득 찬다.
    # 개정 이력은 '같은 소스가 같은 기준시점의 값을 바꿨다'는 뜻이어야 쓸모가 있다
    # (NFP 2회 개정처럼).
    if row["source"] != source:
        return "resourced"

    conn.execute(
        "INSERT OR REPLACE INTO revisions"
        " (series_id, ref_date, observed_at, old_value, new_value, source)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (series_id, ref_date, now, old, value, source),
    )
    return "revised"


# ---------------------------------------------------------------------------
# releases
# ---------------------------------------------------------------------------
def upsert_release(
    conn: sqlite3.Connection,
    series_id: str,
    ref_date: str,
    *,
    release_date: Optional[str] = None,
    actual: Optional[float] = None,
    forecast: Optional[float] = None,
    previous: Optional[float] = None,
    source: str,
    overwrite_with_none: bool = False,
) -> str:
    """발표 3종 세트 갱신.

    기본적으로 None 은 '모름'이므로 기존 값을 덮어쓰지 않는다. 서로 다른 소스가
    각각 다른 필드를 채우기 때문이다 (FRED 는 실제값, 캘린더는 예측값).
    """
    now = utcnow()
    row = conn.execute(
        "SELECT release_date, actual, forecast, previous FROM releases"
        " WHERE series_id = ? AND ref_date = ?",
        (series_id, ref_date),
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO releases"
            " (series_id, ref_date, release_date, actual, forecast, previous, source, updated_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (series_id, ref_date, release_date, actual, forecast, previous, source, now),
        )
        return "inserted"

    def pick(new, old):
        if new is None and not overwrite_with_none:
            return old
        return new

    merged = (
        pick(release_date, row["release_date"]),
        pick(actual, row["actual"]),
        pick(forecast, row["forecast"]),
        pick(previous, row["previous"]),
    )
    current = (row["release_date"], row["actual"], row["forecast"], row["previous"])
    if merged == current:
        return "unchanged"

    conn.execute(
        "UPDATE releases SET release_date = ?, actual = ?, forecast = ?, previous = ?,"
        " source = ?, updated_at = ? WHERE series_id = ? AND ref_date = ?",
        (*merged, source, now, series_id, ref_date),
    )
    return "updated"


# ---------------------------------------------------------------------------
# calendar_events — 원본 보관
# ---------------------------------------------------------------------------
def event_key(title: str, country: str, event_time: str) -> str:
    raw = f"{title}|{country}|{event_time}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def upsert_calendar_event(
    conn: sqlite3.Connection,
    *,
    title: str,
    country: str,
    event_time: str,
    impact: Optional[str],
    actual_raw: Optional[str],
    forecast_raw: Optional[str],
    previous_raw: Optional[str],
) -> str:
    """캘린더 원본 저장.

    같은 이벤트를 매일 다시 보게 되는데, 발표 전에는 actual 이 비어 있다가
    발표 후 채워진다. 따라서 비어 있는 값으로 기존 값을 덮지 않는다.
    """
    now = utcnow()
    key = event_key(title, country, event_time)
    row = conn.execute(
        "SELECT actual_raw, forecast_raw, previous_raw FROM calendar_events WHERE event_key = ?",
        (key,),
    ).fetchone()

    if row is None:
        conn.execute(
            "INSERT INTO calendar_events (event_key, title, country, event_time, impact,"
            " actual_raw, forecast_raw, previous_raw, first_seen, last_seen)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (key, title, country, event_time, impact,
             actual_raw or None, forecast_raw or None, previous_raw or None, now, now),
        )
        return "inserted"

    merged = (
        actual_raw or row["actual_raw"],
        forecast_raw or row["forecast_raw"],
        previous_raw or row["previous_raw"],
    )
    conn.execute(
        "UPDATE calendar_events SET actual_raw = ?, forecast_raw = ?, previous_raw = ?,"
        " impact = COALESCE(?, impact), last_seen = ? WHERE event_key = ?",
        (*merged, impact, now, key),
    )
    changed = merged != (row["actual_raw"], row["forecast_raw"], row["previous_raw"])
    return "updated" if changed else "unchanged"


# ---------------------------------------------------------------------------
# fetch_log
# ---------------------------------------------------------------------------
def log_start(conn: sqlite3.Connection, source: str) -> int:
    cur = conn.execute(
        "INSERT INTO fetch_log (source, started_at, status) VALUES (?, ?, 'running')",
        (source, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def log_finish(
    conn: sqlite3.Connection,
    log_id: int,
    status: str,
    rows: int = 0,
    message: str = "",
) -> None:
    conn.execute(
        "UPDATE fetch_log SET finished_at = ?, status = ?, rows = ?, message = ? WHERE id = ?",
        (utcnow(), status, rows, message[:2000], log_id),
    )
    conn.commit()


def latest_status(conn: sqlite3.Connection) -> list[dict]:
    """소스별 최근 수집 결과 — UI 신선도 패널용."""
    rows = conn.execute(
        """
        SELECT source, status, started_at, finished_at, rows, message
        FROM fetch_log
        WHERE id IN (SELECT MAX(id) FROM fetch_log GROUP BY source)
        ORDER BY source
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 조회
# ---------------------------------------------------------------------------
def observations_for(
    conn: sqlite3.Connection, series_id: str, limit: Optional[int] = None
) -> list[sqlite3.Row]:
    sql = (
        "SELECT ref_date, value, source, updated_at FROM observations"
        " WHERE series_id = ? ORDER BY ref_date DESC"
    )
    params: tuple = (series_id,)
    if limit:
        sql += " LIMIT ?"
        params += (limit,)
    return conn.execute(sql, params).fetchall()


def releases_for(
    conn: sqlite3.Connection, series_id: str, limit: Optional[int] = None
) -> list[sqlite3.Row]:
    sql = (
        "SELECT ref_date, release_date, actual, forecast, previous, source, updated_at"
        " FROM releases WHERE series_id = ? ORDER BY ref_date DESC"
    )
    params: tuple = (series_id,)
    if limit:
        sql += " LIMIT ?"
        params += (limit,)
    return conn.execute(sql, params).fetchall()


def overrides_for(conn: sqlite3.Connection, series_id: str) -> dict[tuple[str, str], float]:
    rows = conn.execute(
        "SELECT ref_date, field, value FROM manual_overrides WHERE series_id = ?",
        (series_id,),
    ).fetchall()
    return {(r["ref_date"], r["field"]): r["value"] for r in rows}


def reconcile_event_releases(conn: sqlite3.Connection, max_days: int = 2) -> list[str]:
    """이벤트성 지표(FOMC·금통위)에서 하루 차이로 중복된 행을 병합한다.

    같은 FOMC 를 소스마다 다른 날짜로 준다:
        엑셀        2026-07-30   (한국 날짜. 주1은 '현지'라고 적혀 있지만 실제로는 KST)
        캘린더      2026-07-29   (미국 동부 14:00 발표)
    병합하지 않으면 한 번의 회의가 대시보드에 두 행으로 나온다.

    **더 이른 날짜로 모은다.** 정책 결정은 발표국 현지 시각에 일어나고,
    다른 표기(KST 등)는 항상 그보다 뒤이기 때문이다.
    """
    from .series import ALL_SERIES

    merged: list[str] = []
    event_ids = [s.id for s in ALL_SERIES if s.frequency == "event"]

    for series_id in event_ids:
        while True:
            rows = conn.execute(
                "SELECT ref_date, release_date, actual, forecast, previous, source"
                " FROM releases WHERE series_id = ? ORDER BY ref_date",
                (series_id,),
            ).fetchall()

            pair = None
            for a, b in zip(rows, rows[1:]):
                delta = (
                    date.fromisoformat(b["ref_date"][:10])
                    - date.fromisoformat(a["ref_date"][:10])
                ).days
                if 0 < delta <= max_days:
                    pair = (a, b)
                    break
            if pair is None:
                break

            keep, drop = pair  # keep 이 더 이른 날짜
            # 각 필드는 값이 있는 쪽을 살린다. 양쪽 다 있으면 keep 우선.
            def pick(field: str):
                return keep[field] if keep[field] is not None else drop[field]

            conn.execute(
                "UPDATE releases SET release_date = ?, actual = ?, forecast = ?,"
                " previous = ?, source = ?, updated_at = ? WHERE series_id = ? AND ref_date = ?",
                (
                    pick("release_date"), pick("actual"), pick("forecast"), pick("previous"),
                    f"{keep['source']}+{drop['source']}", utcnow(),
                    series_id, keep["ref_date"],
                ),
            )
            conn.execute(
                "DELETE FROM releases WHERE series_id = ? AND ref_date = ?",
                (series_id, drop["ref_date"]),
            )
            merged.append(
                f"{series_id}: {drop['ref_date']}({drop['source']}) "
                f"-> {keep['ref_date']}({keep['source']}) 병합"
            )

    conn.commit()
    return merged


def apply_overrides(conn: sqlite3.Connection) -> int:
    """수동 오버라이드를 releases 에 반영. 자동값보다 항상 우선한다."""
    rows = conn.execute("SELECT series_id, ref_date, field, value FROM manual_overrides").fetchall()
    n = 0
    for r in rows:
        if r["field"] not in ("actual", "forecast", "previous"):
            continue
        cur = conn.execute(
            f"UPDATE releases SET {r['field']} = ?, updated_at = ?"
            " WHERE series_id = ? AND ref_date = ?",
            (r["value"], utcnow(), r["series_id"], r["ref_date"]),
        )
        if cur.rowcount == 0:
            conn.execute(
                "INSERT INTO releases (series_id, ref_date, source, updated_at,"
                f" {r['field']}) VALUES (?, ?, 'manual', ?, ?)",
                (r["series_id"], r["ref_date"], utcnow(), r["value"]),
            )
        n += 1
    conn.commit()
    return n
