// 텔레그램 알림 발송.

const FLAG = { US: '🇺🇸', KR: '🇰🇷' };

async function api(env, method, payload) {
  if (!env.TELEGRAM_BOT_TOKEN) {
    console.warn('TELEGRAM_BOT_TOKEN 미설정 — 알림을 건너뜁니다');
    return null;
  }
  const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const json = await res.json();
  if (!json.ok) console.error(`텔레그램 ${method} 실패:`, json.description);
  return json;
}

export function sendMessage(env, chatId, text) {
  return api(env, 'sendMessage', {
    chat_id: chatId,
    text,
    parse_mode: 'HTML',
    disable_web_page_preview: true,
  });
}

/** 활성 구독자 전체에게 발송. 중요도 필터를 각자 설정대로 적용합니다. */
export async function broadcast(env, text, importance = 3) {
  const { results } = await env.DB.prepare(
    `SELECT chat_id FROM subscribers WHERE active = 1 AND min_importance <= ?`
  ).bind(importance).all();

  const targets = results.map((r) => r.chat_id);

  // 구독자 테이블이 비어 있으면 환경변수의 기본 수신자로 폴백
  if (!targets.length && env.TELEGRAM_CHAT_ID) targets.push(env.TELEGRAM_CHAT_ID);

  for (const chatId of targets) {
    await sendMessage(env, chatId, text);
  }
  return targets.length;
}

const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

/** 발표 예정 알림 */
export function formatPre(release, ind, minutesLeft, kstTime) {
  return [
    `⏰ <b>${minutesLeft}분 후 발표</b>`,
    ``,
    `${FLAG[ind.country]} <b>${esc(ind.name)}</b> (${esc(ind.short)})`,
    `기준: ${esc(release.period_label || '-')}`,
    `시각: ${kstTime} KST`,
  ].join('\n');
}

/** 발표 결과 알림 */
export function formatPost(release, ind, actual, previous) {
  const lines = [
    `📊 <b>발표</b>  ${FLAG[ind.country]} ${esc(ind.name)}`,
    `<i>${esc(release.period_label || '-')}</i>`,
    ``,
  ];

  for (const s of ind.series) {
    const a = actual?.[s.key];
    if (a === undefined || a === null) continue;

    const p = previous?.[s.key];
    let line = `• ${esc(s.label)}: <b>${fmt(a, s)}</b>`;
    if (p !== undefined && p !== null) {
      const arrow = a > p ? '▲' : a < p ? '▼' : '=';
      line += `  (이전 ${fmt(p, s)} ${arrow})`;
    }
    lines.push(line);
  }

  return lines.join('\n');
}

/** 오늘의 일정 요약 */
export function formatDigest(rows, indexById) {
  if (!rows.length) return '📅 <b>오늘 예정된 매크로 발표가 없습니다.</b>';

  const lines = ['📅 <b>오늘의 매크로 일정</b> (KST)', ''];
  for (const r of rows) {
    const ind = indexById[r.indicator_id];
    if (!ind) continue;
    const time = new Date(r.release_at).toLocaleTimeString('en-GB', {
      timeZone: 'Asia/Seoul', hour: '2-digit', minute: '2-digit',
    });
    const stars = '★'.repeat(r.importance);
    lines.push(`${time}  ${FLAG[ind.country]} ${esc(ind.name)}  <i>${stars}</i>`);
  }
  return lines.join('\n');
}

function fmt(v, s) {
  const unit = s.unit || '';
  if (unit === '천명' || unit === '천건') {
    return `${Math.round(v).toLocaleString('ko-KR')}${unit}`;
  }
  return `${v.toFixed(2)}${unit}`;
}
