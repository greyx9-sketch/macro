// 텔레그램 봇 명령 처리.
// 봇에게 /start 만 보내면 알림 수신자로 등록되도록 해서,
// 채팅 ID 를 직접 찾아 입력하는 번거로움을 없앴습니다.

import { BY_ID } from './indicators.js';
import { sendMessage, formatDigest } from './telegram.js';
import { nowIso, KST } from './util.js';

const HELP = [
  '<b>매크로 캘린더 봇</b>',
  '',
  '/start — 알림 받기 시작',
  '/stop — 알림 끄기',
  '/today — 오늘 일정',
  '/next — 다음 발표 5건',
  '/major — 중요도 ★★★ 만 받기',
  '/all — 전체 받기',
].join('\n');

export async function handleUpdate(env, update) {
  const msg = update.message || update.edited_message;
  const text = msg?.text?.trim();
  const chatId = msg?.chat?.id;
  if (!chatId || !text) return;

  const cmd = text.split(/\s+/)[0].replace(/@.*$/, '').toLowerCase();

  switch (cmd) {
    case '/start': {
      await env.DB.prepare(
        `INSERT INTO subscribers (chat_id, label, created_at) VALUES (?, ?, ?)
         ON CONFLICT(chat_id) DO UPDATE SET active = 1`
      ).bind(String(chatId), msg.chat.first_name || null, nowIso()).run();

      await sendMessage(env, chatId,
        '✅ 알림이 켜졌습니다.\n\n발표 30분 전과 발표 직후에 메시지를 보냅니다.\n\n' + HELP);
      break;
    }

    case '/stop':
      await env.DB.prepare(`UPDATE subscribers SET active = 0 WHERE chat_id = ?`)
        .bind(String(chatId)).run();
      await sendMessage(env, chatId, '🔕 알림을 껐습니다. /start 로 다시 켤 수 있습니다.');
      break;

    case '/major':
      await env.DB.prepare(`UPDATE subscribers SET min_importance = 3 WHERE chat_id = ?`)
        .bind(String(chatId)).run();
      await sendMessage(env, chatId, '★★★ 중요 지표만 보냅니다.');
      break;

    case '/all':
      await env.DB.prepare(`UPDATE subscribers SET min_importance = 1 WHERE chat_id = ?`)
        .bind(String(chatId)).run();
      await sendMessage(env, chatId, '전체 지표를 보냅니다.');
      break;

    case '/today': {
      const today = new Date().toLocaleDateString('en-CA', { timeZone: KST });
      const { results } = await env.DB.prepare(
        `SELECT * FROM releases WHERE release_date = ? ORDER BY release_at`
      ).bind(today).all();
      await sendMessage(env, chatId, formatDigest(results, BY_ID));
      break;
    }

    case '/next': {
      const { results } = await env.DB.prepare(
        `SELECT * FROM releases WHERE release_at > ? ORDER BY release_at LIMIT 5`
      ).bind(nowIso()).all();

      const lines = ['📌 <b>다음 발표</b> (KST)', ''];
      for (const r of results) {
        const ind = BY_ID[r.indicator_id];
        const when = new Date(r.release_at).toLocaleString('ko-KR', {
          timeZone: KST, month: 'numeric', day: 'numeric',
          hour: '2-digit', minute: '2-digit', hour12: false,
        });
        lines.push(`${when}  ${ind?.country === 'US' ? '🇺🇸' : '🇰🇷'} ${ind?.name ?? r.indicator_id}`);
      }
      await sendMessage(env, chatId, lines.join('\n'));
      break;
    }

    default:
      await sendMessage(env, chatId, HELP);
  }
}
