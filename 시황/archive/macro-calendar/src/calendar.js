// 발표 일정(캘린더) 생성.
// 미국은 FRED 가 갖고 있는 공식 공표일정을 그대로 쓰고,
// 한국은 확정 일정(금통위)과 관행적 발표일(통계청/한은)을 규칙으로 계산합니다.

import { SCHEDULED, primarySeries } from './indicators.js';
import { fetchReleaseDates } from './fred.js';
import {
  zonedToUtc, toZonedDate, nextWeekday, nthBusinessDay,
  shiftMonth, periodLabelKo, nowIso, KST,
} from './util.js';

/** 이 지표의 기준 시계열 주기 (M | W | D) */
function freqOf(ind) {
  const s = primarySeries(ind);
  if (s.ecos) return s.ecos.cycle;
  return s.freq || 'M';
}

/**
 * 발표일로부터 "어느 기간의 수치인지" 추정.
 *
 * 어디까지나 추정입니다 — JOLTS 처럼 발표 주기가 드리프트하는 지표는
 * 고정 시차가 맞지 않습니다(9/1 발표는 7월분, 9/29 발표는 8월분).
 * 발표가 확정되면 notify.js 가 실제 데이터에서 기간을 다시 잡습니다.
 */
export function estimatePeriod(ind, localDate) {
  const freq = freqOf(ind);
  if (freq === 'W') return null;          // 주간물은 발표 시점에 최신 주차로 확정
  if (freq === 'D') return localDate;     // 금리 결정처럼 당일 값이 곧 결과

  const releaseMonth = localDate.slice(0, 7);
  const offset = ind.schedule.periodOffset ?? (ind.schedule.type === 'fixed_dates' ? 0 : -1);
  return shiftMonth(releaseMonth, offset);
}

/** 이 지표의 기준 시계열 주기를 외부에서도 쓰기 위해 노출 */
export { freqOf };

/** 지표 하나의 발표 예정일 목록 (현지 날짜 문자열) */
async function datesFor(env, ind, fredDates, months) {
  const sch = ind.schedule;

  if (sch.type === 'fred_release') {
    return fredDates.get(sch.releaseId) || [];
  }

  if (sch.type === 'fixed_dates') {
    const first = months[0], last = months[months.length - 1];
    return sch.dates.filter((d) => d.slice(0, 7) >= first && d.slice(0, 7) <= last);
  }

  if (sch.type === 'day_of_month') {
    return months.map((ym) => {
      const [y, m] = ym.split('-').map(Number);
      const d = nextWeekday(y, m, sch.day);
      return `${d.year}-${String(d.month).padStart(2, '0')}-${String(d.day).padStart(2, '0')}`;
    });
  }

  if (sch.type === 'nth_bday') {
    return months.map((ym) => {
      const [y, m] = ym.split('-').map(Number);
      const d = nthBusinessDay(y, m, sch.n);
      return `${d.year}-${String(d.month).padStart(2, '0')}-${String(d.day).padStart(2, '0')}`;
    });
  }

  return [];
}

/** 대상 기간의 YYYY-MM 목록 */
function monthWindow(monthsBack, monthsAhead) {
  const now = new Date();
  const cur = `${now.getUTCFullYear()}-${String(now.getUTCMonth() + 1).padStart(2, '0')}`;
  const out = [];
  for (let i = -monthsBack; i <= monthsAhead; i++) out.push(shiftMonth(cur, i));
  return out;
}

/**
 * 캘린더 재생성.
 * 이미 'released' 로 확정된 행은 건드리지 않습니다 (발표된 수치를 덮어쓰면 안 되니까).
 */
export async function buildCalendar(env, { monthsBack = 2, monthsAhead = 4 } = {}) {
  const months = monthWindow(monthsBack, monthsAhead);
  const rangeStart = `${months[0]}-01`;
  const rangeEnd = `${shiftMonth(months[months.length - 1], 1)}-01`;

  // FRED 릴리스 일정은 한 번에 모아서 가져옵니다
  const releaseIds = SCHEDULED
    .filter((i) => i.schedule.type === 'fred_release')
    .map((i) => i.schedule.releaseId);
  const fredDates = await fetchReleaseDates(env, releaseIds, rangeStart, rangeEnd);

  const stmts = [];
  let count = 0;

  for (const ind of SCHEDULED) {
    const dates = await datesFor(env, ind, fredDates, months);

    for (const localDate of dates) {
      const [y, m, d] = localDate.split('-').map(Number);
      const [hh, mm] = ind.schedule.time.split(':').map(Number);
      const atUtc = zonedToUtc(y, m, d, hh, mm, ind.schedule.tz);

      // 캘린더는 한국시간 기준으로 그립니다. 미국 밤 발표가 한국 날짜로는
      // 다음날이 되는 경우가 많아서 이 변환이 꼭 필요합니다.
      const kstDate = toZonedDate(atUtc, KST);
      const period = estimatePeriod(ind, localDate);
      const id = `${ind.id}:${localDate}`;

      stmts.push(
        env.DB.prepare(
          `INSERT INTO releases
             (id, indicator_id, country, release_date, release_at, period, period_label,
              importance, status, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'scheduled', ?)
           ON CONFLICT(id) DO UPDATE SET
             release_date = excluded.release_date,
             release_at   = excluded.release_at,
             period       = excluded.period,
             period_label = excluded.period_label,
             updated_at   = excluded.updated_at
           WHERE releases.status = 'scheduled'`
        ).bind(
          id, ind.id, ind.country, kstDate, new Date(atUtc).toISOString(),
          period, period ? periodLabelKo(period) : '주간', ind.importance, nowIso()
        )
      );
      count++;
    }
  }

  for (let i = 0; i < stmts.length; i += 60) {
    await env.DB.batch(stmts.slice(i, i + 60));
  }

  await env.DB.prepare(
    `INSERT INTO state (key, value) VALUES ('last_calendar_build', ?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value`
  ).bind(nowIso()).run();

  return { releases: count, months: months.length };
}

/** 발표 id 에서 현지 발표일 추출 */
export function localDateOf(releaseId) {
  return releaseId.split(':')[1];
}
