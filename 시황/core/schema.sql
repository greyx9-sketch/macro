-- 매크로 지표 저장소 스키마
--
-- 설계 원칙
--  1. 값이 없는 것(미발표/결측)은 NULL. 0 과 절대 섞지 않는다.
--  2. 원본은 버리지 않는다. ForexFactory 는 지난 주를 다시 주지 않으므로
--     매핑이 틀렸더라도 나중에 고칠 수 있도록 raw 이벤트를 전량 보관한다.
--  3. 값이 바뀌면 revisions 에 흔적을 남긴다. 조용한 덮어쓰기 금지.

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

-- 지표 메타데이터. core/series.py 에서 매 실행 시 동기화된다.
CREATE TABLE IF NOT EXISTS series (
    id          TEXT PRIMARY KEY,
    name_ko     TEXT    NOT NULL,
    category    TEXT    NOT NULL,
    unit        TEXT    NOT NULL,
    frequency   TEXT    NOT NULL,
    decimals    INTEGER NOT NULL,
    note        TEXT    NOT NULL DEFAULT ''
);

-- 기준시점별 실제값(현재 유효한 값 = 개정이 반영된 최신값).
CREATE TABLE IF NOT EXISTS observations (
    series_id   TEXT NOT NULL REFERENCES series(id),
    ref_date    TEXT NOT NULL,           -- 기준월은 해당 월 1일, 주간/일간은 실제 날짜
    value       REAL,                    -- NULL 허용: 미발표
    source      TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (series_id, ref_date)
);

CREATE INDEX IF NOT EXISTS idx_obs_series_date
    ON observations (series_id, ref_date DESC);

-- 개정 이력. 같은 기준시점의 값이 달라질 때마다 한 행씩 쌓인다.
-- 엑셀에는 없던 정보로, NFP 처럼 2회 개정되는 지표의 수정 폭을 볼 수 있다.
CREATE TABLE IF NOT EXISTS revisions (
    series_id   TEXT NOT NULL REFERENCES series(id),
    ref_date    TEXT NOT NULL,
    observed_at TEXT NOT NULL,           -- 우리가 변경을 감지한 시각
    old_value   REAL,
    new_value   REAL,
    source      TEXT NOT NULL,
    PRIMARY KEY (series_id, ref_date, observed_at)
);

-- 발표 이벤트: 엑셀의 (발표일, 기준월, 실제, 예측, 이전) 한 행에 대응.
CREATE TABLE IF NOT EXISTS releases (
    series_id    TEXT NOT NULL REFERENCES series(id),
    ref_date     TEXT NOT NULL,          -- 기준월/기준일
    release_date TEXT,                   -- 발표 시각(ISO8601, 타임존 포함)
    actual       REAL,
    forecast     REAL,
    previous     REAL,
    source       TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    PRIMARY KEY (series_id, ref_date)
);

CREATE INDEX IF NOT EXISTS idx_rel_series_date
    ON releases (series_id, ref_date DESC);
CREATE INDEX IF NOT EXISTS idx_rel_release_date
    ON releases (release_date DESC);

-- ForexFactory 캘린더 원본. 지표 매핑 여부와 무관하게 전량 적재한다.
-- 피드가 이번 주만 제공하므로 여기 없으면 영원히 복구 불가 -> 무조건 먼저 저장.
CREATE TABLE IF NOT EXISTS calendar_events (
    event_key    TEXT PRIMARY KEY,       -- sha1(title|country|event_time)
    title        TEXT NOT NULL,
    country      TEXT NOT NULL,
    event_time   TEXT NOT NULL,
    impact       TEXT,
    actual_raw   TEXT,                   -- '201K', '3.75%' 등 원문 그대로
    forecast_raw TEXT,
    previous_raw TEXT,
    first_seen   TEXT NOT NULL,
    last_seen    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cal_time  ON calendar_events (event_time DESC);
CREATE INDEX IF NOT EXISTS idx_cal_title ON calendar_events (country, title);

-- 소스별 수집 결과. UI 의 신선도 패널이 이걸 읽는다.
CREATE TABLE IF NOT EXISTS fetch_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    status      TEXT NOT NULL,           -- ok | failed | skipped
    rows        INTEGER NOT NULL DEFAULT 0,
    message     TEXT
);

CREATE INDEX IF NOT EXISTS idx_log_source ON fetch_log (source, started_at DESC);

-- 자동 수집이 불가능하거나 실패했을 때 사람이 채운 값.
-- observations/releases 보다 우선한다. UI 에 '수동' 표시가 붙는다.
CREATE TABLE IF NOT EXISTS manual_overrides (
    series_id  TEXT NOT NULL REFERENCES series(id),
    ref_date   TEXT NOT NULL,
    field      TEXT NOT NULL,            -- actual | forecast | previous
    value      REAL,
    reason     TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (series_id, ref_date, field)
);
