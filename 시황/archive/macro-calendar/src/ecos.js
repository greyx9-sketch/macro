// 한국은행 ECOS 클라이언트.
// 한국 지표 전부(소비자물가·생산자물가·고용·기준금리·국고채)를 여기서 가져옵니다.

const BASE = 'https://ecos.bok.or.kr/api/StatisticSearch';

/**
 * ECOS 통계 조회.
 * URL 이 경로 파라미터 방식이라 순서가 중요합니다:
 *   /인증키/json/kr/시작행/끝행/통계표코드/주기/시작시점/종료시점/항목1[/항목2...]
 */
export async function fetchEcos(env, { stat, cycle, item1, item2, item3 }, start, end) {
  const parts = [
    env.ECOS_API_KEY, 'json', 'kr', '1', '10000',
    stat, cycle, start, end, item1,
  ];
  if (item2) parts.push(item2);
  if (item3) parts.push(item3);

  const res = await fetch(`${BASE}/${parts.map(encodeURIComponent).join('/')}`);
  if (!res.ok) throw new Error(`ECOS ${stat} HTTP ${res.status}`);

  const json = await res.json();

  // ECOS 는 에러도 200 으로 내려주고 본문에 RESULT 를 담습니다.
  if (json.RESULT) {
    const { CODE, MESSAGE } = json.RESULT;
    // INFO-200 = 해당 기간 데이터 없음. 정상 상황이라 빈 배열로 처리합니다.
    if (CODE === 'INFO-200') return [];
    throw new Error(`ECOS ${stat} ${CODE}: ${MESSAGE}`);
  }

  const rows = json.StatisticSearch?.row || [];
  const out = [];
  for (const r of rows) {
    const value = Number(r.DATA_VALUE);
    if (!Number.isFinite(value)) continue;
    out.push({ period: normalizePeriod(r.TIME, cycle), value });
  }
  out.sort((a, b) => (a.period < b.period ? -1 : 1));
  return out;
}

/** ECOS 의 TIME 표기(202607 / 20260726)를 ISO 형태로 */
function normalizePeriod(time, cycle) {
  const t = String(time);
  if (cycle === 'M') return `${t.slice(0, 4)}-${t.slice(4, 6)}`;
  if (cycle === 'D') return `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)}`;
  if (cycle === 'Q') return `${t.slice(0, 4)}-Q${t.slice(4, 6)}`;
  if (cycle === 'A') return t.slice(0, 4);
  return t;
}

/** ECOS 조회용 시작/종료 문자열 생성 */
export function ecosRange(cycle, monthsBack = 30) {
  const now = new Date();
  const end = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 0));
  const startD = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - monthsBack, 1));

  const ym = (d) => `${d.getUTCFullYear()}${String(d.getUTCMonth() + 1).padStart(2, '0')}`;
  const ymd = (d) => `${ym(d)}${String(d.getUTCDate()).padStart(2, '0')}`;

  if (cycle === 'D') return [ymd(startD), ymd(end)];
  return [ym(startD), ym(end)];
}
