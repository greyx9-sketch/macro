// FRED (세인트루이스 연은) 클라이언트.
// 미국 지표의 수치와 "공식 발표 예정일"을 모두 여기서 가져옵니다.

const BASE = 'https://api.stlouisfed.org/fred';

async function fredGet(env, path, params) {
  const url = new URL(BASE + path);
  url.searchParams.set('api_key', env.FRED_API_KEY);
  url.searchParams.set('file_type', 'json');
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null) url.searchParams.set(k, String(v));
  }

  const res = await fetch(url, { cf: { cacheTtl: 60, cacheEverything: false } });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`FRED ${path} ${res.status}: ${body.slice(0, 200)}`);
  }
  return res.json();
}

/**
 * 시계열 관측치. 오름차순 [{ period, value }] 로 정규화해서 돌려줍니다.
 * period 는 월간이면 YYYY-MM, 그 외에는 YYYY-MM-DD.
 */
export async function fetchSeries(env, seriesId, { start, monthly = true } = {}) {
  const json = await fredGet(env, '/series/observations', {
    series_id: seriesId,
    observation_start: start,
    sort_order: 'asc',
  });

  const out = [];
  for (const o of json.observations || []) {
    if (o.value === '.' || o.value === '' || o.value == null) continue;  // FRED 의 결측 표기
    const value = Number(o.value);
    if (!Number.isFinite(value)) continue;
    out.push({ period: monthly ? o.date.slice(0, 7) : o.date, value });
  }
  return out;
}

/**
 * 지정한 릴리스들의 발표 예정일.
 * FRED 는 미국 통계기관의 확정 공표일정을 그대로 갖고 있어서
 * 직접 하드코딩할 필요가 없습니다.
 *
 * 전체 목록(/releases/dates)은 하루에 수백 건씩 쌓여 limit 에 걸리므로
 * 릴리스별 엔드포인트를 각각 부릅니다. 응답이 작아 이쪽이 훨씬 안전합니다.
 *
 * @returns Map<releaseId, string[]>  (YYYY-MM-DD, 미 동부 날짜 기준)
 */
export async function fetchReleaseDates(env, releaseIds, startDate, endDate) {
  const map = new Map();

  for (const id of [...new Set(releaseIds.map(Number))]) {
    const json = await fredGet(env, '/release/dates', {
      release_id: id,
      realtime_start: startDate,
      realtime_end: endDate,
      include_release_dates_with_no_data: 'true',
      limit: 1000,
      sort_order: 'asc',
    });

    const dates = (json.release_dates || [])
      .map((d) => d.date)
      .filter((d) => d >= startDate && d <= endDate);

    map.set(id, dates);
  }

  return map;
}
