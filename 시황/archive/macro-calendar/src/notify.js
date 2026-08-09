// 발표 감지 + 알림. 5분마다 도는 크론이 여기를 호출합니다.
//
// 세 가지 일을 합니다:
//   1) 발표 N분 전  → "곧 발표됩니다" 알림
//   2) 발표 시각 이후 → 실제 수치가 올라왔는지 확인하고, 올라왔으면 결과 알림
//   3) 과거 발표 채우기 → 앱을 새로 띄웠거나 알림 창을 놓친 구간을 조용히 메꿉니다

import { BY_ID, SCHEDULED } from './indicators.js';
import { syncAll, readValues } from './sync.js';
import { freqOf, localDateOf } from './calendar.js';
import { broadcast, formatPre, formatPost, formatDigest } from './telegram.js';
import { shiftMonth, toZonedTime, periodLabelKo, nowIso, KST } from './util.js';

const PRE_MINUTES = 30;
const POST_WINDOW_MIN = 180;   // 발표 후 3시간까지만 실시간 결과를 추적합니다

// ─────────────────────────── 공통 ───────────────────────────

/** 직전 기간의 값 */
async function readPrevious(env, indicatorId, period) {
  if (!period) return null;

  if (period.length === 7) {
    return readValues(env, indicatorId, shiftMonth(period, -1));
  }
  const row = await env.DB.prepare(
    `SELECT period FROM observations WHERE indicator_id = ? AND period < ?
     ORDER BY period DESC LIMIT 1`
  ).bind(indicatorId, period).first();

  return row ? readValues(env, indicatorId, row.period) : null;
}

async function markReleased(env, release, period, actual, previous, { notified }) {
  await env.DB.prepare(
    `UPDATE releases SET
       status = 'released', period = ?, period_label = ?,
       actual_json = ?, previous_json = ?,
       notified_pre = ?, notified_post = ?, updated_at = ?
     WHERE id = ?`
  ).bind(
    period, periodLabelKo(period),
    JSON.stringify(actual), JSON.stringify(previous || {}),
    notified ? 1 : release.notified_pre, notified ? 1 : 0,
    nowIso(), release.id
  ).run();
}

/**
 * 이 발표에 해당하는 실제 수치를 찾습니다.
 *
 * 발표일에서 기간을 역산하는 대신 데이터에서 확정합니다 — JOLTS 처럼
 * 발표 간격이 드리프트하는 지표는 고정 시차가 맞지 않기 때문입니다.
 */
async function resolveActual(env, ind, release) {
  if (freqOf(ind) === 'D') {
    // 금리 결정: 발표 당일 값이 곧 결과
    const period = localDateOf(release.id);
    const actual = await readValues(env, ind.id, period);
    return actual && Object.keys(actual).length ? { period, actual } : null;
  }

  const latest = await env.DB.prepare(
    `SELECT period FROM observations WHERE indicator_id = ? ORDER BY period DESC LIMIT 1`
  ).bind(ind.id).first();
  if (!latest) return null;

  // 이미 확정된 마지막 발표보다 새로운 기간이 올라왔을 때만 새 발표로 인정합니다
  const lastDone = await env.DB.prepare(
    `SELECT period FROM releases
     WHERE indicator_id = ? AND status = 'released' AND period IS NOT NULL
     ORDER BY period DESC LIMIT 1`
  ).bind(ind.id).first();

  if (lastDone && latest.period <= lastDone.period) return null;

  const actual = await readValues(env, ind.id, latest.period);
  return actual && Object.keys(actual).length ? { period: latest.period, actual } : null;
}

// ─────────────────────── 1) 발표 예정 알림 ───────────────────────

async function notifyUpcoming(env, now) {
  const { results } = await env.DB.prepare(
    `SELECT * FROM releases
     WHERE status = 'scheduled' AND notified_pre = 0
       AND release_at > ? AND release_at <= ?
     ORDER BY release_at`
  ).bind(new Date(now).toISOString(), new Date(now + PRE_MINUTES * 60_000).toISOString()).all();

  let sent = 0;
  for (const r of results) {
    const ind = BY_ID[r.indicator_id];
    if (!ind) continue;

    const minutesLeft = Math.max(1, Math.round((Date.parse(r.release_at) - now) / 60_000));
    await broadcast(env, formatPre(r, ind, minutesLeft, toZonedTime(Date.parse(r.release_at), KST)), r.importance);
    await env.DB.prepare(`UPDATE releases SET notified_pre = 1 WHERE id = ?`).bind(r.id).run();
    sent++;
  }
  return sent;
}

// ─────────────────────── 2) 발표 결과 감지 ───────────────────────

async function notifyReleased(env, now) {
  const { results } = await env.DB.prepare(
    `SELECT * FROM releases
     WHERE status = 'scheduled' AND notified_post = 0
       AND release_at <= ? AND release_at >= ?
     ORDER BY release_at`
  ).bind(
    new Date(now).toISOString(),
    new Date(now - POST_WINDOW_MIN * 60_000).toISOString()
  ).all();

  if (!results.length) return 0;

  // 발표 대상 지표만 다시 당겨옵니다 (전체 동기화는 낭비라서)
  for (const id of new Set(results.map((r) => r.indicator_id))) {
    try {
      await syncAll(env, { only: id });
    } catch (err) {
      console.error(`발표 감지용 동기화 실패 ${id}:`, err.message);
    }
  }

  let sent = 0;
  for (const r of results) {
    const ind = BY_ID[r.indicator_id];
    if (!ind) continue;

    const found = await resolveActual(env, ind, r);
    if (!found) continue;   // 아직 안 올라옴 → 다음 크론에서 재시도

    const previous = await readPrevious(env, ind.id, found.period);
    await broadcast(env, formatPost({ ...r, period_label: periodLabelKo(found.period) }, ind, found.actual, previous), r.importance);
    await markReleased(env, r, found.period, found.actual, previous, { notified: true });
    sent++;
  }
  return sent;
}

// ─────────────────── 3) 과거 발표 채우기 (알림 없음) ───────────────────

/**
 * 이미 지난 발표들에 실제 수치를 채웁니다.
 *
 * 과거 발표를 발표일과 1:1 로 짝지을 때, 발표일에서 기간을 계산하지 않고
 * "가장 최근 발표 ↔ 가장 최근 데이터" 부터 거꾸로 맞춰 나갑니다.
 * 지표마다 시차가 다르고 같은 지표도 시기에 따라 달라지는 문제를
 * 이 방식이면 규칙 없이 흡수합니다.
 */
export async function backfillPast(env) {
  const now = new Date().toISOString();
  let filled = 0;

  for (const ind of SCHEDULED) {
    if (ind.source === 'MANUAL') continue;

    // 짝을 맞추려면 이미 확정된 것까지 포함해 과거 발표 전체가 필요합니다
    const { results: past } = await env.DB.prepare(
      `SELECT id, status, notified_pre FROM releases
       WHERE indicator_id = ? AND release_at < ?
       ORDER BY release_at`
    ).bind(ind.id, now).all();
    if (!past.length) continue;

    if (freqOf(ind) === 'D') {
      for (const r of past) {
        if (r.status === 'released') continue;
        const period = localDateOf(r.id);
        const actual = await readValues(env, ind.id, period);
        if (!actual || !Object.keys(actual).length) continue;
        await markReleased(env, r, period, actual, await readPrevious(env, ind.id, period), { notified: true });
        filled++;
      }
      continue;
    }

    const { results: periods } = await env.DB.prepare(
      `SELECT DISTINCT period FROM observations WHERE indicator_id = ? ORDER BY period`
    ).bind(ind.id).all();
    if (!periods.length) continue;

    const n = Math.min(past.length, periods.length);
    for (let i = 1; i <= n; i++) {
      const r = past[past.length - i];
      if (r.status === 'released') continue;

      const period = periods[periods.length - i].period;
      const actual = await readValues(env, ind.id, period);
      if (!actual || !Object.keys(actual).length) continue;

      await markReleased(env, r, period, actual, await readPrevious(env, ind.id, period), { notified: true });
      filled++;
    }
  }

  return { filled };
}

// ─────────────────────────── 진입점 ───────────────────────────

export async function runNotifications(env) {
  const now = Date.now();
  const pre = await notifyUpcoming(env, now);
  const post = await notifyReleased(env, now);
  return { pre, post };
}

/** 아침에 보내는 오늘 일정 요약 */
export async function sendDailyDigest(env) {
  const todayKst = new Date().toLocaleDateString('en-CA', { timeZone: KST });

  const { results } = await env.DB.prepare(
    `SELECT * FROM releases
     WHERE release_date = ? AND importance >= 2
     ORDER BY release_at`
  ).bind(todayKst).all();

  await broadcast(env, formatDigest(results, BY_ID), 3);
  return results.length;
}
