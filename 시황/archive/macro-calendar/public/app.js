// 대시보드 프론트엔드. 빌드 도구 없이 그냥 도는 ES 모듈입니다.

const KST = 'Asia/Seoul';
const state = {
  cursor: startOfMonth(new Date()),
  view: 'calendar',
  country: 'ALL',
  minImportance: 1,
  releases: [],
};

// ─────────────────────────── 유틸 ───────────────────────────

function startOfMonth(d) {
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1));
}
function ymd(d) {
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, '0')}-${String(d.getUTCDate()).padStart(2, '0')}`;
}
function todayKst() {
  return new Date().toLocaleDateString('en-CA', { timeZone: KST });
}
function kstTime(iso) {
  return new Date(iso).toLocaleTimeString('en-GB', { timeZone: KST, hour: '2-digit', minute: '2-digit' });
}

/** 단위에 맞춘 숫자 표기 */
function fmtValue(v, unit) {
  if (v === null || v === undefined) return '–';
  if (unit === '천명' || unit === '천건') return Math.round(v).toLocaleString('ko-KR');
  return v.toFixed(2);
}

// ─────────────────────────── 데이터 ───────────────────────────

async function loadCalendar() {
  const first = state.cursor;
  const last = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + 1, 0));
  // 앞뒤 주를 넉넉히 포함해 그리드 가장자리도 채웁니다
  const from = ymd(new Date(first.getTime() - 7 * 864e5));
  const to = ymd(new Date(last.getTime() + 7 * 864e5));

  const res = await fetch(`/api/calendar?from=${from}&to=${to}`);
  state.releases = res.ok ? await res.json() : [];
}

async function loadDashboard() {
  const res = await fetch('/api/dashboard');
  if (!res.ok) return;
  const data = await res.json();
  renderStrip(data.indicators);

  const last = data.state?.last_sync;
  document.getElementById('syncinfo').textContent = last
    ? `마지막 갱신 ${new Date(last).toLocaleString('ko-KR', { timeZone: KST, dateStyle: 'short', timeStyle: 'short' })} KST`
    : '아직 동기화되지 않았습니다';
}

function visible(r) {
  if (state.country !== 'ALL' && r.country !== state.country) return false;
  return r.importance >= state.minImportance;
}

// ─────────────────────────── 요약 스트립 ───────────────────────────

const STRIP_IDS = ['us_t10y2y', 'kr_t10y2y', 'us_fedfunds', 'kr_base_rate'];

function renderStrip(indicators) {
  const byId = Object.fromEntries(indicators.map((i) => [i.id, i]));
  const el = document.getElementById('strip');
  el.innerHTML = '';

  for (const id of STRIP_IDS) {
    const d = byId[id];
    if (!d) continue;

    const flag = d.country === 'US' ? '🇺🇸' : '🇰🇷';
    const cls = d.change > 0 ? 'up' : d.change < 0 ? 'down' : 'flat';
    const arrow = d.change > 0 ? '▲' : d.change < 0 ? '▼' : '=';

    const tile = document.createElement('div');
    tile.className = 'tile';
    tile.innerHTML = `
      <div class="tile-label">${flag} ${d.short}</div>
      <div class="tile-value">${fmtValue(d.latest, d.unit)}<span class="unit">${d.unit || ''}</span></div>
      <div class="tile-meta">
        <span>${d.period || '–'}</span>
        ${d.change !== null && d.change !== undefined
          ? `<span class="delta ${cls}">${arrow} ${Math.abs(d.change).toFixed(2)}</span>` : ''}
      </div>
      ${sparkline(d.history, d.country === 'US' ? 'var(--us)' : 'var(--kr)')}
    `;
    el.appendChild(tile);
  }
}

/** 단일 계열 스파크라인. 계열이 하나뿐이라 범례는 두지 않습니다. */
function sparkline(values, color) {
  if (!values || values.length < 2) return '';
  const w = 100, h = 26, pad = 2;
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;

  const pts = values.map((v, i) => {
    const x = pad + (i / (values.length - 1)) * (w - pad * 2);
    const y = h - pad - ((v - min) / span) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });

  const lastX = pad + (w - pad * 2), lastY = pts[pts.length - 1].split(',')[1];
  return `<svg class="tile-spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" aria-hidden="true">
    <polyline points="${pts.join(' ')}" fill="none" stroke="${color}" stroke-width="2"
      stroke-linejoin="round" stroke-linecap="round" vector-effect="non-scaling-stroke" />
    <circle cx="${lastX}" cy="${lastY}" r="2.2" fill="${color}" />
  </svg>`;
}

// ─────────────────────────── 캘린더 ───────────────────────────

function renderCalendar() {
  const grid = document.getElementById('grid');
  grid.innerHTML = '';

  const first = state.cursor;
  const y = first.getUTCFullYear(), m = first.getUTCMonth();
  document.getElementById('monthlabel').textContent = `${y}년 ${m + 1}월`;

  const start = new Date(Date.UTC(y, m, 1 - new Date(Date.UTC(y, m, 1)).getUTCDay()));
  const today = todayKst();

  const byDate = {};
  for (const r of state.releases) {
    if (!visible(r)) continue;
    (byDate[r.release_date] ||= []).push(r);
  }

  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getTime() + i * 864e5);
    const key = ymd(d);
    const items = byDate[key] || [];

    const cell = document.createElement('button');
    cell.type = 'button';
    cell.className = 'cell';
    if (d.getUTCMonth() !== m) cell.classList.add('out');
    if (d.getUTCDay() === 0) cell.classList.add('sun');
    if (key === today) cell.classList.add('today');
    cell.dataset.date = key;

    // 좁은 화면일수록 칸이 작아 표시 가능한 칩 수가 줄어듭니다
    const maxChips = window.innerWidth < 561 ? 2 : 3;
    const shown = items.slice(0, maxChips);

    cell.innerHTML = `
      <span class="daynum">${d.getUTCDate()}</span>
      <div class="chips">
        ${shown.map((r) => `<span class="chip ${r.status === 'released' ? 'done' : ''}" style="--c:var(--${r.country.toLowerCase()})">${r.short}</span>`).join('')}
        ${items.length > maxChips ? `<span class="more">+${items.length - maxChips}</span>` : ''}
      </div>`;

    cell.addEventListener('click', () => openSheet(key, items));
    grid.appendChild(cell);
  }
}

// ─────────────────────────── 리스트 ───────────────────────────

function renderList() {
  const el = document.getElementById('list');
  el.innerHTML = '';

  const m = state.cursor.getUTCMonth(), y = state.cursor.getUTCFullYear();
  const items = state.releases.filter((r) => {
    if (!visible(r)) return false;
    const [ry, rm] = r.release_date.split('-').map(Number);
    return ry === y && rm === m + 1;
  });

  if (!items.length) {
    el.innerHTML = '<p class="empty">이 달에 표시할 일정이 없습니다.</p>';
    return;
  }

  const byDate = {};
  for (const r of items) (byDate[r.release_date] ||= []).push(r);

  for (const [date, rows] of Object.entries(byDate).sort()) {
    const d = new Date(date + 'T00:00:00Z');
    const dow = ['일', '월', '화', '수', '목', '금', '토'][d.getUTCDay()];

    const g = document.createElement('div');
    g.className = 'daygroup';
    g.innerHTML = `<h3>${d.getUTCMonth() + 1}월 ${d.getUTCDate()}일 (${dow})${date === todayKst() ? ' · 오늘' : ''}</h3>`
      + rows.map(rowHtml).join('');
    el.appendChild(g);
  }
}

function rowHtml(r) {
  const flag = r.country === 'US' ? '🇺🇸' : '🇰🇷';
  const stars = '★'.repeat(r.importance);
  return `
    <div class="row">
      <span class="time">${kstTime(r.release_at)}</span>
      <div class="who">
        <div class="nm"><i class="dot ${r.country.toLowerCase()}"></i>${flag} ${r.name}</div>
        <div class="sub">${r.period_label || ''}${r.primary_label ? ` · ${r.primary_label}` : ''} <span class="stars">${stars}</span></div>
      </div>
      <div class="vals">${valuesHtml(r)}</div>
    </div>`;
}

function valuesHtml(r) {
  if (r.status !== 'released' || !r.actual) return '<span class="prev">예정</span>';

  // 대표 시리즈를 우선 표시합니다 (CPI 라면 근원 YoY 같은 것)
  const k = r.primary_key && r.actual[r.primary_key] !== undefined
    ? r.primary_key
    : Object.keys(r.actual)[0];
  if (!k) return '<span class="prev">–</span>';

  const a = r.actual[k], p = r.previous?.[k];
  const cls = p == null ? 'flat' : a > p ? 'up' : a < p ? 'down' : 'flat';
  const arrow = p == null ? '' : a > p ? '▲' : a < p ? '▼' : '=';

  return `<b class="delta ${cls}">${fmtValue(a, r.unit)}${r.unit || ''} ${arrow}</b>`
    + (p != null ? `<span class="prev">이전 ${fmtValue(p, r.unit)}</span>` : '');
}

// ─────────────────────────── 상세 시트 ───────────────────────────

async function openSheet(date, items) {
  const sheet = document.getElementById('sheet');
  const d = new Date(date + 'T00:00:00Z');
  const dow = ['일', '월', '화', '수', '목', '금', '토'][d.getUTCDay()];

  document.getElementById('sheet-title').textContent =
    `${d.getUTCMonth() + 1}월 ${d.getUTCDate()}일 (${dow})`;

  document.getElementById('sheet-body').innerHTML = items.length
    ? items.map(rowHtml).join('')
    : '<p class="empty">예정된 발표가 없습니다.</p>';

  sheet.hidden = false;
}

document.getElementById('sheet').addEventListener('click', (e) => {
  if (e.target.dataset.close !== undefined) document.getElementById('sheet').hidden = true;
});

// ─────────────────────────── 컨트롤 ───────────────────────────

function render() {
  const cal = document.getElementById('calendar');
  const list = document.getElementById('list');
  cal.hidden = state.view !== 'calendar';
  list.hidden = state.view !== 'list';
  if (state.view === 'calendar') renderCalendar(); else renderList();
}

async function reload() {
  await loadCalendar();
  render();
}

document.querySelectorAll('.seg button').forEach((btn) => {
  btn.addEventListener('click', () => {
    btn.parentElement.querySelectorAll('button').forEach((b) => b.classList.remove('on'));
    btn.classList.add('on');

    if (btn.dataset.view) state.view = btn.dataset.view;
    if (btn.dataset.country) state.country = btn.dataset.country;
    if (btn.dataset.imp) state.minImportance = Number(btn.dataset.imp);
    render();
  });
});

document.getElementById('prev').addEventListener('click', () => {
  state.cursor = new Date(Date.UTC(state.cursor.getUTCFullYear(), state.cursor.getUTCMonth() - 1, 1));
  reload();
});
document.getElementById('next').addEventListener('click', () => {
  state.cursor = new Date(Date.UTC(state.cursor.getUTCFullYear(), state.cursor.getUTCMonth() + 1, 1));
  reload();
});
document.getElementById('today').addEventListener('click', () => {
  state.cursor = startOfMonth(new Date());
  reload();
});
document.getElementById('refresh').addEventListener('click', async () => {
  await Promise.all([loadDashboard(), reload()]);
});

// 화면 폭이 바뀌면 칸에 들어가는 칩 개수가 달라지므로 다시 그립니다
let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => { if (state.view === 'calendar') renderCalendar(); }, 150);
});

// 시작
loadDashboard();
reload();
