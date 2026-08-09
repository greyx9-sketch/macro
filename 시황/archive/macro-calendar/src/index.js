// 워커 진입점 — API 라우팅 + 크론 핸들러.

import { Hono } from 'hono';
import { INDICATORS, BY_ID, DAILY, primarySeries } from './indicators.js';
import { syncAll, readRecent, readValues } from './sync.js';
import { buildCalendar } from './calendar.js';
import { runNotifications, sendDailyDigest, backfillPast } from './notify.js';
import { sendMessage } from './telegram.js';
import { handleUpdate } from './bot.js';
import { nowIso, KST } from './util.js';

const app = new Hono();

// ───────────────────────────── 조회 API ─────────────────────────────

/** 지표 메타데이터 (프론트가 이름·단위·중요도를 알기 위해) */
app.get('/api/indicators', (c) =>
  c.json(INDICATORS.map((i) => ({
    id: i.id, country: i.country, name: i.name, short: i.short,
    importance: i.importance, source: i.source,
    series: i.series.map((s) => ({ key: s.key, label: s.label, unit: s.unit, primary: !!s.primary })),
  })))
);

/** 캘린더 — 기간 내 발표 일정 전부 */
app.get('/api/calendar', async (c) => {
  const from = c.req.query('from');
  const to = c.req.query('to');
  if (!from || !to) return c.json({ error: 'from, to 파라미터가 필요합니다 (YYYY-MM-DD)' }, 400);

  const { results } = await c.env.DB.prepare(
    `SELECT id, indicator_id, country, release_date, release_at, period, period_label,
            importance, status, actual_json, previous_json
     FROM releases
     WHERE release_date >= ? AND release_date <= ?
     ORDER BY release_at`
  ).bind(from, to).all();

  return c.json(results.map((r) => {
    const ind = BY_ID[r.indicator_id];
    const ps = ind ? primarySeries(ind) : null;
    return {
      ...r,
      name: ind?.name ?? r.indicator_id,
      short: ind?.short ?? r.indicator_id,
      // 프론트가 여러 시리즈 중 무엇을 대표로 보여줄지 알아야 합니다
      primary_key: ps?.key ?? null,
      primary_label: ps?.label ?? null,
      unit: ps?.unit ?? '',
      actual: r.actual_json ? JSON.parse(r.actual_json) : null,
      previous: r.previous_json ? JSON.parse(r.previous_json) : null,
      actual_json: undefined, previous_json: undefined,
    };
  }));
});

/** 대시보드 — 지표별 최신값 한 줄 요약 */
app.get('/api/dashboard', async (c) => {
  const out = [];

  for (const ind of INDICATORS) {
    const s = primarySeries(ind);
    const history = await readRecent(c.env, ind.id, s.key, 13);
    if (!history.length) {
      out.push({ id: ind.id, country: ind.country, name: ind.name, short: ind.short,
                 unit: s.unit, label: s.label, latest: null, history: [] });
      continue;
    }

    const latest = history[history.length - 1];
    const prev = history.length > 1 ? history[history.length - 2] : null;

    out.push({
      id: ind.id, country: ind.country, name: ind.name, short: ind.short,
      importance: ind.importance, unit: s.unit, label: s.label,
      latest: latest.value, period: latest.period,
      previous: prev ? prev.value : null,
      change: prev ? Number((latest.value - prev.value).toFixed(3)) : null,
      history: history.map((h) => h.value),
      daily: DAILY.some((d) => d.id === ind.id),
    });
  }

  const state = await c.env.DB.prepare(`SELECT key, value FROM state`).all();
  return c.json({
    indicators: out,
    state: Object.fromEntries(state.results.map((r) => [r.key, r.value])),
  });
});

/** 지표 상세 — 전 시리즈 시계열 */
app.get('/api/indicator/:id', async (c) => {
  const ind = BY_ID[c.req.param('id')];
  if (!ind) return c.json({ error: '없는 지표입니다' }, 404);

  const series = [];
  for (const s of ind.series) {
    series.push({
      key: s.key, label: s.label, unit: s.unit, primary: !!s.primary,
      data: await readRecent(c.env, ind.id, s.key, 36),
    });
  }
  return c.json({ id: ind.id, country: ind.country, name: ind.name, source: ind.source, series });
});

// ───────────────────────────── 관리 API ─────────────────────────────

const requireAdmin = async (c, next) => {
  const token = c.req.header('x-admin-token') || c.req.query('token');
  if (!c.env.ADMIN_TOKEN || token !== c.env.ADMIN_TOKEN) {
    return c.json({ error: '인증 실패' }, 401);
  }
  await next();
};

app.post('/api/admin/sync', requireAdmin, async (c) =>
  c.json(await syncAll(c.env, { only: c.req.query('only') })));

app.post('/api/admin/calendar', requireAdmin, async (c) =>
  c.json(await buildCalendar(c.env)));

app.post('/api/admin/notify', requireAdmin, async (c) =>
  c.json(await runNotifications(c.env)));

app.post('/api/admin/backfill', requireAdmin, async (c) =>
  c.json(await backfillPast(c.env)));

app.post('/api/admin/digest', requireAdmin, async (c) =>
  c.json({ count: await sendDailyDigest(c.env) }));

/** ISM PMI 처럼 API 로 못 받는 지표를 손으로 넣습니다 */
app.post('/api/admin/manual', requireAdmin, async (c) => {
  const { indicator_id, series_key, period, value } = await c.req.json();
  if (!indicator_id || !series_key || !period || value === undefined) {
    return c.json({ error: 'indicator_id, series_key, period, value 가 모두 필요합니다' }, 400);
  }
  await c.env.DB.prepare(
    `INSERT INTO observations (indicator_id, series_key, period, value, fetched_at)
     VALUES (?, ?, ?, ?, ?)
     ON CONFLICT(indicator_id, series_key, period)
     DO UPDATE SET value = excluded.value, fetched_at = excluded.fetched_at`
  ).bind(indicator_id, series_key, period, Number(value), nowIso()).run();

  return c.json({ ok: true });
});

/** 텔레그램 수신자 등록 */
app.post('/api/admin/subscribe', requireAdmin, async (c) => {
  const { chat_id, label } = await c.req.json();
  await c.env.DB.prepare(
    `INSERT INTO subscribers (chat_id, label, created_at) VALUES (?, ?, ?)
     ON CONFLICT(chat_id) DO UPDATE SET active = 1, label = excluded.label`
  ).bind(String(chat_id), label || null, nowIso()).run();

  await sendMessage(c.env, chat_id, '✅ 매크로 캘린더 알림이 연결됐습니다.');
  return c.json({ ok: true });
});

/**
 * 텔레그램 웹훅.
 * 경로에 시크릿을 넣어 아무나 호출하지 못하게 합니다.
 * 등록: setWebhook 을 이 URL 로 한 번만 호출하면 됩니다 (README 참고).
 */
app.post('/api/telegram/webhook/:secret', async (c) => {
  if (c.req.param('secret') !== c.env.ADMIN_TOKEN) return c.json({ error: '인증 실패' }, 401);

  try {
    await handleUpdate(c.env, await c.req.json());
  } catch (err) {
    console.error('웹훅 처리 실패:', err.message);
  }
  return c.json({ ok: true });   // 텔레그램에는 항상 200 을 줘야 재시도 폭주를 막습니다
});

app.get('/api/health', async (c) => {
  const rel = await c.env.DB.prepare(`SELECT COUNT(*) n FROM releases`).first();
  const obs = await c.env.DB.prepare(`SELECT COUNT(*) n FROM observations`).first();
  return c.json({ ok: true, releases: rel.n, observations: obs.n, now: nowIso() });
});

// 그 외 경로는 정적 파일(대시보드)로
app.all('*', (c) => c.env.ASSETS.fetch(c.req.raw));

// ───────────────────────────── 크론 ─────────────────────────────

export default {
  fetch: app.fetch,

  async scheduled(event, env, ctx) {
    const job = (async () => {
      switch (event.cron) {
        case '*/5 * * * *':
          console.log('알림 체크:', JSON.stringify(await runNotifications(env)));
          break;

        case '10 20 * * *':
          console.log('일일 동기화:', JSON.stringify(await syncAll(env)));
          console.log('캘린더 갱신:', JSON.stringify(await buildCalendar(env)));
          console.log('과거 발표 보정:', JSON.stringify(await backfillPast(env)));
          break;

        case '0 22 * * *':
          console.log('일정 요약 발송:', await sendDailyDigest(env));
          break;

        default:
          console.warn('알 수 없는 크론:', event.cron);
      }
    })();

    ctx.waitUntil(job);
    await job;
  },
};
