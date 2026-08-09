// 지표 레지스트리 — 이 파일이 앱 전체의 단일 진실 공급원입니다.
// 지표를 추가하려면 여기에 항목 하나만 넣으면 캘린더·대시보드·알림에 전부 반영됩니다.
//
// schedule.type
//   fred_release  : FRED 의 릴리스 일정 API 를 그대로 사용 (미국 공식 확정 일정)
//   fixed_dates   : 사전 공표된 확정 날짜 목록 (FOMC, 금통위)
//   day_of_month  : 매월 n일 (주말이면 다음 평일로) — 한국 통계청/한은 관행
//   nth_bday      : 매월 n번째 영업일 — ISM 등
//
// series[].transform
//   level  : 값 그대로
//   yoy    : 전년동월 대비 %
//   mom    : 전월 대비 %
//   diff   : 전기 대비 절대 증감

import { ET, KST } from './util.js';

export const INDICATORS = [
  // ─────────────────────────── 미국 ───────────────────────────
  {
    id: 'us_cpi',
    country: 'US',
    name: '소비자물가지수',
    short: 'CPI',
    importance: 3,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 10, time: '08:30', tz: ET },
    series: [
      { key: 'core_yoy',     label: '근원 YoY',   fredId: 'CPILFESL', transform: 'yoy', unit: '%', primary: true },
      { key: 'headline_yoy', label: '헤드라인 YoY', fredId: 'CPIAUCSL', transform: 'yoy', unit: '%' },
      { key: 'core_mom',     label: '근원 MoM',   fredId: 'CPILFESL', transform: 'mom', unit: '%' },
      { key: 'headline_mom', label: '헤드라인 MoM', fredId: 'CPIAUCSL', transform: 'mom', unit: '%' },
    ],
  },
  {
    id: 'us_ppi',
    country: 'US',
    name: '생산자물가지수',
    short: 'PPI',
    importance: 2,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 46, time: '08:30', tz: ET },
    series: [
      { key: 'yoy', label: '최종수요 YoY', fredId: 'PPIFIS', transform: 'yoy', unit: '%', primary: true },
      { key: 'mom', label: '최종수요 MoM', fredId: 'PPIFIS', transform: 'mom', unit: '%' },
    ],
  },
  {
    id: 'us_pce',
    country: 'US',
    name: '개인소비지출 물가지수',
    short: 'PCE',
    importance: 3,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 54, time: '08:30', tz: ET },
    series: [
      { key: 'core_yoy',     label: '근원 YoY',   fredId: 'PCEPILFE', transform: 'yoy', unit: '%', primary: true },
      { key: 'headline_yoy', label: '헤드라인 YoY', fredId: 'PCEPI',    transform: 'yoy', unit: '%' },
      { key: 'core_mom',     label: '근원 MoM',   fredId: 'PCEPILFE', transform: 'mom', unit: '%' },
    ],
  },
  {
    id: 'us_nfp',
    country: 'US',
    name: '비농업 고용자수',
    short: 'NFP',
    importance: 3,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 50, time: '08:30', tz: ET },
    series: [
      { key: 'change', label: '전월 대비 증감', fredId: 'PAYEMS', transform: 'diff', unit: '천명', primary: true },
    ],
  },
  {
    id: 'us_unrate',
    country: 'US',
    name: '실업률',
    short: '실업률',
    importance: 3,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 50, time: '08:30', tz: ET },
    series: [
      { key: 'level', label: '실업률', fredId: 'UNRATE', transform: 'level', unit: '%', primary: true },
    ],
  },
  {
    id: 'us_ahe',
    country: 'US',
    name: '시간당 평균임금',
    short: '시간당임금',
    importance: 2,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 50, time: '08:30', tz: ET },
    series: [
      { key: 'yoy', label: 'YoY', fredId: 'CES0500000003', transform: 'yoy', unit: '%', primary: true },
      { key: 'mom', label: 'MoM', fredId: 'CES0500000003', transform: 'mom', unit: '%' },
    ],
  },
  {
    id: 'us_claims',
    country: 'US',
    name: '신규 실업수당 청구',
    short: '실업수당',
    importance: 2,
    source: 'FRED',
    schedule: { type: 'fred_release', releaseId: 180, time: '08:30', tz: ET },
    series: [
      { key: 'level', label: '신규 청구건수', fredId: 'ICSA', freq: 'W', transform: 'level', unit: '천건', scale: 0.001, primary: true },
    ],
  },
  {
    id: 'us_jolts',
    country: 'US',
    name: 'JOLTS 구인건수',
    short: 'JOLTS',
    importance: 2,
    source: 'FRED',
    // JOLTS 는 다른 지표와 달리 2개월 시차로 발표됩니다 (9월 발표분 = 7월 기준)
    schedule: { type: 'fred_release', releaseId: 192, time: '10:00', tz: ET, periodOffset: -2 },
    series: [
      { key: 'level', label: '구인건수', fredId: 'JTSJOL', transform: 'level', unit: '천건', primary: true },
    ],
  },
  {
    id: 'us_ism_mfg',
    country: 'US',
    name: 'ISM 제조업 PMI',
    short: 'ISM제조',
    importance: 3,
    // ISM 은 저작권 때문에 FRED·공개 API 어디에도 없습니다. 일정만 계산하고
    // 수치는 수동 입력(/api/manual) 으로 채웁니다. 자세한 사정은 README 참고.
    source: 'MANUAL',
    schedule: { type: 'nth_bday', n: 1, time: '10:00', tz: ET },
    series: [
      { key: 'level', label: 'PMI', transform: 'level', unit: '', primary: true },
    ],
  },
  {
    id: 'us_ism_svc',
    country: 'US',
    name: 'ISM 서비스업 PMI',
    short: 'ISM서비스',
    importance: 2,
    source: 'MANUAL',
    schedule: { type: 'nth_bday', n: 3, time: '10:00', tz: ET },
    series: [
      { key: 'level', label: 'PMI', transform: 'level', unit: '', primary: true },
    ],
  },
  {
    id: 'us_fedfunds',
    country: 'US',
    name: 'FOMC 기준금리',
    short: 'FOMC',
    importance: 3,
    source: 'FRED',
    schedule: {
      type: 'fixed_dates', time: '14:00', tz: ET,
      dates: [
        // 2026년 (연준 공표 확정 일정, 2일차 기준)
        '2026-01-28', '2026-03-18', '2026-04-29', '2026-06-17',
        '2026-07-29', '2026-09-16', '2026-10-28', '2026-12-09',
        // 2027년 잠정 일정 — 확정되면 갱신 필요
        '2027-01-27', '2027-03-17', '2027-04-28', '2027-06-16',
        '2027-07-28', '2027-09-22', '2027-11-03', '2027-12-15',
      ],
    },
    series: [
      { key: 'level', label: '상단금리', fredId: 'DFEDTARU', freq: 'D', transform: 'level', unit: '%', primary: true },
    ],
  },
  {
    id: 'us_t10y2y',
    country: 'US',
    name: '미국 10Y-2Y 금리차',
    short: '10Y-2Y',
    importance: 1,
    source: 'FRED',
    // 매 영업일 갱신이라 캘린더에는 올리지 않고 대시보드에만 띄웁니다.
    schedule: { type: 'daily' },
    series: [
      { key: 'spread', label: '장단기 스프레드', fredId: 'T10Y2Y', freq: 'D', transform: 'level', unit: '%p', primary: true },
      { key: 'y10',    label: '10년물',        fredId: 'DGS10',  freq: 'D', transform: 'level', unit: '%' },
      { key: 'y2',     label: '2년물',         fredId: 'DGS2',   freq: 'D', transform: 'level', unit: '%' },
    ],
  },

  // ─────────────────────────── 한국 ───────────────────────────
  {
    id: 'kr_cpi',
    country: 'KR',
    name: '소비자물가지수',
    short: 'CPI',
    importance: 3,
    source: 'ECOS',
    // 통계청 소비자물가동향: 익월 2일경 08:00 발표
    schedule: { type: 'day_of_month', day: 2, time: '08:00', tz: KST },
    series: [
      { key: 'yoy', label: '총지수 YoY', ecos: { stat: '901Y009', cycle: 'M', item1: '0' }, transform: 'yoy', unit: '%', primary: true },
      { key: 'mom', label: '총지수 MoM', ecos: { stat: '901Y009', cycle: 'M', item1: '0' }, transform: 'mom', unit: '%' },
    ],
  },
  {
    id: 'kr_ppi',
    country: 'KR',
    name: '생산자물가지수',
    short: 'PPI',
    importance: 2,
    source: 'ECOS',
    // 한국은행 생산자물가지수: 익월 하순(약 22일) 12:00 발표
    schedule: { type: 'day_of_month', day: 22, time: '12:00', tz: KST },
    series: [
      { key: 'yoy', label: '총지수 YoY', ecos: { stat: '404Y014', cycle: 'M', item1: '*AA' }, transform: 'yoy', unit: '%', primary: true },
      { key: 'mom', label: '총지수 MoM', ecos: { stat: '404Y014', cycle: 'M', item1: '*AA' }, transform: 'mom', unit: '%' },
    ],
  },
  {
    id: 'kr_unrate',
    country: 'KR',
    name: '실업률',
    short: '실업률',
    importance: 3,
    source: 'ECOS',
    // 통계청 고용동향: 익월 중순(약 15일) 08:00 발표
    schedule: { type: 'day_of_month', day: 15, time: '08:00', tz: KST },
    series: [
      { key: 'level', label: '실업률', ecos: { stat: '901Y027', cycle: 'M', item1: 'I61BC' }, transform: 'level', unit: '%', primary: true },
    ],
  },
  {
    id: 'kr_employment',
    country: 'KR',
    name: '취업자수 증감',
    short: '취업자',
    importance: 3,
    source: 'ECOS',
    // 미국 NFP 에 대응하는 한국 지표. 고용동향에서 같이 발표됩니다.
    schedule: { type: 'day_of_month', day: 15, time: '08:00', tz: KST },
    series: [
      { key: 'yoy_change', label: '전년동월 대비 증감', ecos: { stat: '901Y027', cycle: 'M', item1: 'I61BA' }, transform: 'yoy_diff', unit: '천명', primary: true },
    ],
  },
  {
    id: 'kr_base_rate',
    country: 'KR',
    name: '한국은행 기준금리',
    short: '금통위',
    importance: 3,
    source: 'ECOS',
    schedule: {
      type: 'fixed_dates', time: '09:55', tz: KST,
      dates: [
        // 2026년 통화정책방향 결정회의 (한국은행 공표 확정 일정)
        '2026-01-15', '2026-02-26', '2026-04-10', '2026-05-28',
        '2026-07-16', '2026-08-27', '2026-10-22', '2026-11-26',
      ],
    },
    series: [
      { key: 'level', label: '기준금리', ecos: { stat: '722Y001', cycle: 'M', item1: '0101000' }, transform: 'level', unit: '%', primary: true },
    ],
  },
  {
    id: 'kr_t10y2y',
    country: 'KR',
    name: '한국 10Y-2Y 금리차',
    short: '10Y-2Y',
    importance: 1,
    source: 'ECOS',
    schedule: { type: 'daily' },
    series: [
      { key: 'y10', label: '국고채 10년', ecos: { stat: '817Y002', cycle: 'D', item1: '010210000' }, transform: 'level', unit: '%' },
      { key: 'y2',  label: '국고채 2년',  ecos: { stat: '817Y002', cycle: 'D', item1: '010195000' }, transform: 'level', unit: '%' },
      // spread 는 y10 - y2 로 계산해서 채웁니다 (derived).
      { key: 'spread', label: '장단기 스프레드', derived: 'y10-y2', transform: 'level', unit: '%p', primary: true },
    ],
  },
];

export const BY_ID = Object.fromEntries(INDICATORS.map((i) => [i.id, i]));

/** 캘린더에 표시되는(= 발표 일정이 있는) 지표만 */
export const SCHEDULED = INDICATORS.filter((i) => i.schedule.type !== 'daily');

/** 대시보드 상단 요약에 띄울 지표 */
export const DAILY = INDICATORS.filter((i) => i.schedule.type === 'daily');

export function primarySeries(indicator) {
  return indicator.series.find((s) => s.primary) || indicator.series[0];
}
