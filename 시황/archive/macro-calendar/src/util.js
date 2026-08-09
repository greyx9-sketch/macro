// 시간대·숫자 처리 유틸.
// 발표 시각은 전부 "현지 벽시계 시간"으로 정의돼 있어서(미 동부 08:30 등)
// 서머타임을 포함해 UTC 로 정확히 변환하는 게 이 파일의 핵심입니다.

/** 특정 시점에서 해당 타임존의 UTC 오프셋(ms) */
function tzOffsetMs(ts, tz) {
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    hour12: false,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });
  const p = {};
  for (const part of dtf.formatToParts(ts)) {
    if (part.type !== 'literal') p[part.type] = part.value;
  }
  const asUTC = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
  return asUTC - ts;
}

/**
 * 특정 타임존의 벽시계 시간을 UTC 밀리초로 변환.
 * 오프셋이 시점에 따라 달라지므로(DST) 두 번 반복해 수렴시킵니다.
 */
export function zonedToUtc(year, month, day, hour, minute, tz) {
  const naive = Date.UTC(year, month - 1, day, hour, minute, 0);
  let ts = naive - tzOffsetMs(naive, tz);
  ts = naive - tzOffsetMs(ts, tz);
  return ts;
}

/** UTC 시각을 해당 타임존의 YYYY-MM-DD 로 */
export function toZonedDate(ts, tz) {
  const dtf = new Intl.DateTimeFormat('en-CA', {
    timeZone: tz, year: 'numeric', month: '2-digit', day: '2-digit',
  });
  return dtf.format(ts);
}

/** UTC 시각을 해당 타임존의 HH:mm 으로 */
export function toZonedTime(ts, tz) {
  const dtf = new Intl.DateTimeFormat('en-GB', {
    timeZone: tz, hour: '2-digit', minute: '2-digit', hour12: false,
  });
  return dtf.format(ts);
}

export const KST = 'Asia/Seoul';
export const ET = 'America/New_York';

/** 주말이면 다음 평일로 밀기 (한국·미국 공휴일까지는 반영하지 않습니다) */
export function nextWeekday(year, month, day) {
  const d = new Date(Date.UTC(year, month - 1, day));
  while (d.getUTCDay() === 0 || d.getUTCDay() === 6) {
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

/** 해당 월의 n번째 영업일 (1-based, 주말만 제외) */
export function nthBusinessDay(year, month, n) {
  const d = new Date(Date.UTC(year, month - 1, 1));
  let count = 0;
  while (true) {
    const dow = d.getUTCDay();
    if (dow !== 0 && dow !== 6) {
      count++;
      if (count === n) break;
    }
    d.setUTCDate(d.getUTCDate() + 1);
  }
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate() };
}

/** 'YYYY-MM' 에서 n개월 이동 */
export function shiftMonth(ym, delta) {
  const [y, m] = ym.split('-').map(Number);
  const d = new Date(Date.UTC(y, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
}

/** 'YYYY년 M월' 표기 */
export function periodLabelKo(period) {
  if (!period) return null;
  const parts = period.split('-');
  if (parts.length === 2) return `${parts[0]}년 ${Number(parts[1])}월`;
  return `${parts[0]}년 ${Number(parts[1])}월 ${Number(parts[2])}일`;
}

export function nowIso() {
  return new Date().toISOString();
}

/** 소수점 자릿수 맞춰 반올림 (부동소수 오차 정리용) */
export function round(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(value)) return null;
  const f = Math.pow(10, digits);
  return Math.round(value * f) / f;
}
