-- 매크로 캘린더 스키마
-- 적용: npm run db:local  (로컬) / npm run db:remote (배포본)

DROP TABLE IF EXISTS observations;
DROP TABLE IF EXISTS releases;
DROP TABLE IF EXISTS subscribers;
DROP TABLE IF EXISTS state;

-- 지표 시계열 관측치. (지표, 시리즈, 기간) 단위로 유일.
CREATE TABLE observations (
  indicator_id TEXT NOT NULL,
  series_key   TEXT NOT NULL,   -- 예: headline_yoy, core_mom
  period       TEXT NOT NULL,   -- 기준 기간. 월간=YYYY-MM, 주간/일간=YYYY-MM-DD
  value        REAL,
  fetched_at   TEXT NOT NULL,
  PRIMARY KEY (indicator_id, series_key, period)
);

CREATE INDEX idx_obs_lookup ON observations (indicator_id, series_key, period DESC);

-- 발표 일정. 캘린더의 각 칸이 여기 한 행에 해당합니다.
CREATE TABLE releases (
  id             TEXT PRIMARY KEY,   -- {indicator_id}:{release_date}
  indicator_id   TEXT NOT NULL,
  country        TEXT NOT NULL,      -- US | KR
  release_date   TEXT NOT NULL,      -- 한국시간 기준 날짜 YYYY-MM-DD
  release_at     TEXT NOT NULL,      -- 발표 시각 UTC ISO8601
  period         TEXT,               -- 기준 기간 YYYY-MM 또는 YYYY-MM-DD.
                                     -- 발표 전에는 추정치, 발표 후 실제 데이터로 확정됩니다.
  period_label   TEXT,               -- 화면 표시용. 예: 2026년 6월
  importance     INTEGER NOT NULL DEFAULT 2,
  status         TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | released
  actual_json    TEXT,               -- 발표된 수치 {series_key: value}
  previous_json  TEXT,               -- 직전 수치 {series_key: value}
  notified_pre   INTEGER NOT NULL DEFAULT 0,
  notified_post  INTEGER NOT NULL DEFAULT 0,
  updated_at     TEXT
);

CREATE INDEX idx_rel_date    ON releases (release_date);
CREATE INDEX idx_rel_pending ON releases (status, release_at);

-- 텔레그램 알림 수신자
CREATE TABLE subscribers (
  chat_id     TEXT PRIMARY KEY,
  label       TEXT,
  pre_minutes INTEGER NOT NULL DEFAULT 30,   -- 발표 몇 분 전에 알릴지
  min_importance INTEGER NOT NULL DEFAULT 2, -- 이 중요도 이상만 알림
  active      INTEGER NOT NULL DEFAULT 1,
  created_at  TEXT NOT NULL
);

-- 잡다한 상태 저장 (마지막 동기화 시각 등)
CREATE TABLE state (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
