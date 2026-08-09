// 지표 수치 동기화 — 외부 API → 변환 → D1 저장.

import { INDICATORS } from './indicators.js';
import { fetchSeries } from './fred.js';
import { fetchEcos, ecosRange } from './ecos.js';
import { transform, subtract } from './transform.js';
import { nowIso } from './util.js';

const HISTORY_START = '2018-01-01';   // FRED 조회 시작점 (YoY 계산에 최소 13개월 필요)

/** 지표 하나의 모든 시리즈를 가져와 [{series_key, obs}] 로 반환 */
async function loadIndicator(env, ind) {
  const results = [];
  const raw = {};   // derived 계산에 쓰려고 원계열을 들고 있습니다

  for (const s of ind.series) {
    if (s.derived) continue;

    let obs;
    if (s.fredId) {
      const monthly = (s.freq || 'M') === 'M';
      obs = await fetchSeries(env, s.fredId, { start: HISTORY_START, monthly });
    } else if (s.ecos) {
      const [start, end] = ecosRange(s.ecos.cycle, s.ecos.cycle === 'D' ? 6 : 40);
      obs = await fetchEcos(env, s.ecos, start, end);
    } else {
      continue;   // MANUAL 지표는 여기서 건너뜁니다
    }

    const monthly = s.ecos ? s.ecos.cycle === 'M' : (s.freq || 'M') === 'M';
    const values = transform(obs, s.transform, { monthly, scale: s.scale ?? 1 });
    raw[s.key] = values;
    results.push({ series_key: s.key, obs: values });
  }

  // derived 시리즈 (예: spread = y10 - y2)
  for (const s of ind.series) {
    if (!s.derived) continue;
    const [a, b] = s.derived.split('-');
    if (raw[a] && raw[b]) {
      results.push({ series_key: s.key, obs: subtract(raw[a], raw[b]) });
    }
  }

  return results;
}

/** 관측치를 D1 에 upsert. 최근 것만 넣어 쓸데없이 커지는 걸 막습니다. */
async function saveObservations(env, indicatorId, seriesResults, keepLast = 40) {
  const ts = nowIso();
  const stmts = [];

  for (const { series_key, obs } of seriesResults) {
    for (const o of obs.slice(-keepLast)) {
      stmts.push(
        env.DB.prepare(
          `INSERT INTO observations (indicator_id, series_key, period, value, fetched_at)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(indicator_id, series_key, period)
           DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at`
        ).bind(indicatorId, series_key, o.period, o.value, ts)
      );
    }
  }

  // D1 배치는 한 번에 너무 많이 보내면 거부되므로 잘라서 보냅니다
  for (let i = 0; i < stmts.length; i += 60) {
    await env.DB.batch(stmts.slice(i, i + 60));
  }
  return stmts.length;
}

/**
 * 전체 지표 동기화.
 * 한 지표가 실패해도 나머지는 계속 진행합니다 — 외부 API 하나 죽었다고
 * 대시보드 전체가 비면 안 되니까요.
 */
export async function syncAll(env, { only } = {}) {
  const report = { ok: [], failed: [], rows: 0 };

  for (const ind of INDICATORS) {
    if (only && ind.id !== only) continue;
    if (ind.source === 'MANUAL') continue;

    try {
      const series = await loadIndicator(env, ind);
      const n = await saveObservations(env, ind.id, series);
      report.rows += n;
      report.ok.push(ind.id);
    } catch (err) {
      console.error(`sync 실패 ${ind.id}:`, err.message);
      report.failed.push({ id: ind.id, error: err.message });
    }
  }

  await env.DB.prepare(
    `INSERT INTO state (key, value) VALUES ('last_sync', ?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value`
  ).bind(nowIso()).run();

  return report;
}

/** 특정 지표·기간의 저장된 값들을 {series_key: value} 로 */
export async function readValues(env, indicatorId, period) {
  const { results } = await env.DB.prepare(
    `SELECT series_key, value FROM observations
     WHERE indicator_id = ? AND period = ?`
  ).bind(indicatorId, period).all();

  if (!results.length) return null;
  return Object.fromEntries(results.map((r) => [r.series_key, r.value]));
}

/** 지표의 최근 n개 기간 값 (대시보드 스파크라인용) */
export async function readRecent(env, indicatorId, seriesKey, limit = 13) {
  const { results } = await env.DB.prepare(
    `SELECT period, value FROM observations
     WHERE indicator_id = ? AND series_key = ?
     ORDER BY period DESC LIMIT ?`
  ).bind(indicatorId, seriesKey, limit).all();

  return results.reverse();
}
