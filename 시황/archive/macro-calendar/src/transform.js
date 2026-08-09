// 원시 지수/레벨 시계열을 실제로 보고 싶은 형태(YoY %, MoM %, 증감)로 바꿉니다.
// FRED 도 ECOS 도 대부분 "지수" 원계열만 주기 때문에 이 변환이 필요합니다.

import { shiftMonth, round } from './util.js';

/**
 * @param obs     [{period, value}] 오름차순
 * @param kind    level | yoy | mom | diff | yoy_diff
 * @param opts    { monthly, scale }
 * @returns       [{period, value}] 변환 결과
 */
export function transform(obs, kind, { monthly = true, scale = 1 } = {}) {
  if (kind === 'level') {
    return obs.map((o) => ({ period: o.period, value: round(o.value * scale, 4) }));
  }

  const byPeriod = new Map(obs.map((o) => [o.period, o.value]));
  const prevOf = (period, back) => {
    if (monthly) return byPeriod.get(shiftMonth(period, -back));
    // 주간·일간은 달력 계산 대신 배열 인덱스로 뒤로 이동합니다
    const idx = obs.findIndex((o) => o.period === period);
    return idx - back >= 0 ? obs[idx - back].value : undefined;
  };

  const out = [];
  for (const o of obs) {
    let value = null;
    if (kind === 'yoy') {
      const base = prevOf(o.period, 12);
      if (base) value = ((o.value / base) - 1) * 100;
    } else if (kind === 'mom') {
      const base = prevOf(o.period, 1);
      if (base) value = ((o.value / base) - 1) * 100;
    } else if (kind === 'diff') {
      const base = prevOf(o.period, 1);
      if (base !== undefined) value = o.value - base;
    } else if (kind === 'yoy_diff') {
      const base = prevOf(o.period, 12);
      if (base !== undefined) value = o.value - base;
    } else {
      throw new Error(`알 수 없는 transform: ${kind}`);
    }

    if (value === null) continue;
    out.push({ period: o.period, value: round(value * scale, 4) });
  }
  return out;
}

/** 두 시계열의 차 (한국 10Y-2Y 처럼 스프레드를 직접 계산해야 할 때) */
export function subtract(aObs, bObs) {
  const bMap = new Map(bObs.map((o) => [o.period, o.value]));
  const out = [];
  for (const a of aObs) {
    const b = bMap.get(a.period);
    if (b === undefined) continue;
    out.push({ period: a.period, value: round(a.value - b, 4) });
  }
  return out;
}
