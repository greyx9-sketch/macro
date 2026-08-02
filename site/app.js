/* 매크로 지표 대시보드 — 프론트엔드
 *
 * 빌드 체인도 외부 라이브러리도 없다. dashboard.json 을 읽어 SVG 를 직접 그린다.
 * 몇 년 뒤에도 그대로 열리는 것이 이 선택의 목적이다.
 *
 * 표기 규칙은 파이썬 core/series.py 의 format_value() 와 반드시 일치해야 한다.
 * 둘이 어긋나면 같은 값이 화면과 CLI 에서 다르게 보인다.
 */
'use strict';

const DATA_URL = 'data/dashboard.json';

/* ------------------------------------------------------------------ 포맷 */

// core/series.py format_value() 와 동일한 규칙.
function fmt(unit, decimals, v) {
  if (v === null || v === undefined || Number.isNaN(v)) return '—';
  switch (unit) {
    case 'ratio':     return (v * 100).toFixed(Math.max(0, decimals - 2)) + '%';
    case 'thousands': return v.toLocaleString('ko-KR', {
                               minimumFractionDigits: decimals,
                               maximumFractionDigits: decimals }) + 'K';
    case 'millions':  return v.toFixed(decimals) + 'M';
    case 'bp':        return v.toFixed(decimals) + 'bp';
    case 'pp':        return v.toFixed(decimals) + '%p';
    default:          return v.toFixed(decimals);
  }
}

// 0 이 아닌 값이 반올림 때문에 '0.0' 으로 보이지 않도록 자릿수를 늘린다.
//
// 화살표는 '하락' 인데 숫자는 '0.0' 이면 서로 모순돼 보인다.
// 실제로 PCE 예측대비가 '▼ −0.0%p' 로 표시되고 있었다 (비율 계열은 소수 1자리라
// 0.05%p 미만이 전부 0.0 이 된다). 값이 살아날 때까지 자릿수를 최대 2자리 더 준다.
function precise(magnitude, decimals, scale = 1) {
  const v = magnitude * scale;
  for (let d = decimals; d <= decimals + 2; d++) {
    const s = v.toFixed(d);
    if (parseFloat(s) !== 0 || v === 0) return s;
  }
  return v.toExponential(1);
}

// 차이값 표기. 비율 계열은 %p 로 읽는 것이 맞다 (3.5% - 3.8% = -0.3%p).
function fmtDelta(unit, decimals, d) {
  if (d === null || d === undefined || Number.isNaN(d)) return '—';
  const sign = d > 0 ? '+' : (d < 0 ? '−' : '±');
  const a = Math.abs(d);
  switch (unit) {
    case 'ratio':     return sign + precise(a, Math.max(1, decimals - 2), 100) + '%p';
    case 'thousands': return sign + a.toLocaleString('ko-KR', { maximumFractionDigits: decimals }) + 'K';
    case 'millions':  return sign + precise(a, decimals) + 'M';
    case 'bp':        return sign + precise(a, decimals) + 'bp';
    case 'pp':        return sign + precise(a, decimals) + '%p';
    default:          return sign + precise(a, decimals);
  }
}

// 상승 빨강 / 하락 파랑 / 보합 검정 — 엑셀 주7.
// 색만으로 전달하지 않도록 기호를 함께 돌려준다.
const EPS = 1e-12;
function dirOf(d) {
  if (d === null || d === undefined || Number.isNaN(d)) return null;
  if (d > EPS)  return { cls: 'up',   mark: '▲' };
  if (d < -EPS) return { cls: 'down', mark: '▼' };
  return { cls: 'flat', mark: '—' };
}

// 발표일은 정밀도가 두 가지다. 'YYYY-MM' 은 엑셀 '발표월'에서 온 월 단위 정보로,
// 날짜처럼 보여주면 그 달 1일에 발표된다는 거짓 정보가 된다.
function fmtDate(iso) {
  if (!iso) return '—';
  if (iso.length <= 7) return iso + ' 중';
  return iso.slice(0, 10);
}
function fmtMonth(iso, freq) {
  if (!iso) return '—';
  return freq === 'monthly' ? iso.slice(0, 7) : iso.slice(0, 10);
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ------------------------------------------------------------------ 차트 */

function pathFor(points, x, y) {
  return points.map((p, i) => (i ? 'L' : 'M') + x(i).toFixed(2) + ' ' + y(p.v).toFixed(2)).join(' ');
}

/** 카드용 스파크라인. 축·눈금 없이 형태만 전달한다. */
function sparkline(obs, maxPoints) {
  const pts = obs.slice(-maxPoints);
  if (pts.length < 2) {
    return '<svg class="spark" role="img" aria-label="추이 데이터 부족"></svg>';
  }
  const W = 260, H = 34, PAD = 3;
  const vals = pts.map(p => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (hi === lo) { hi += 1; lo -= 1; }
  const x = i => PAD + (i / (pts.length - 1)) * (W - PAD * 2);
  const y = v => H - PAD - ((v - lo) / (hi - lo)) * (H - PAD * 2);

  const last = pts[pts.length - 1];
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none"
               role="img" aria-label="최근 ${pts.length}개 관측치 추이">
    <path d="${pathFor(pts, x, y)}" fill="none" stroke="var(--series-1)"
          stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"
          vector-effect="non-scaling-stroke"/>
    <circle cx="${x(pts.length - 1).toFixed(2)}" cy="${y(last.v).toFixed(2)}" r="2.4"
            fill="var(--series-1)" stroke="var(--surface)" stroke-width="1.4"/>
  </svg>`;
}

// 차트 좌표계. viewBox 를 화면 폭에 맞춰 고른다.
//
// 고정 viewBox(820x240) 에 CSS height 를 240px 로 박아두면, 좁은 화면에서
// preserveAspectRatio 가 종횡비를 지키며 축소하는 바람에 위아래로 거대한 빈 공간이 생긴다.
// 실제로 390px 모바일에서 차트 영역의 절반 이상이 여백이었다.
function chartBox() {
  const narrow = Math.min(window.innerWidth, document.documentElement.clientWidth) < 560;
  return narrow
    ? { W: 360, H: 240, L: 44, R: 8, T: 10, B: 24 }
    : { W: 820, H: 240, L: 56, R: 12, T: 12, B: 26 };
}

/** 상세 패널용 선 차트. 축 + 크로스헤어 툴팁 포함. */
function lineChart(series, obs) {
  if (obs.length < 2) {
    return '<p style="color:var(--text-muted);font-size:13px">추이를 그리기에 관측치가 부족합니다.</p>';
  }
  const { W, H, L, R, T, B } = chartBox();
  const vals = obs.map(p => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || Math.abs(hi || 1) * 0.08;
  lo -= pad; hi += pad;

  const x = i => L + (i / (obs.length - 1)) * (W - L - R);
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  // 눈금 5개
  const ticks = [];
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * (i / 4);
    ticks.push({ v, y: y(v) });
  }

  const grid = ticks.map(t => `
    <line x1="${L}" x2="${W - R}" y1="${t.y.toFixed(1)}" y2="${t.y.toFixed(1)}"
          stroke="var(--gridline)" stroke-width="1"/>
    <text x="${L - 8}" y="${(t.y + 3.5).toFixed(1)}" text-anchor="end"
          font-size="10.5" fill="var(--text-muted)">${esc(fmt(series.unit, series.decimals, t.v))}</text>`
  ).join('');

  // x축 라벨 (처음/중간/끝)
  const xi = [0, Math.floor((obs.length - 1) / 2), obs.length - 1];
  const xlab = xi.map(i => `
    <text x="${x(i).toFixed(1)}" y="${H - 8}" text-anchor="${i === 0 ? 'start' : i === obs.length - 1 ? 'end' : 'middle'}"
          font-size="10.5" fill="var(--text-muted)">${esc(fmtMonth(obs[i].d, series.frequency))}</text>`
  ).join('');

  // 0 기준선 — 음수가 될 수 있는 계열(NFP, 10Y-2Y)에서 의미가 크다
  const zero = (lo < 0 && hi > 0)
    ? `<line x1="${L}" x2="${W - R}" y1="${y(0).toFixed(1)}" y2="${y(0).toFixed(1)}"
             stroke="var(--baseline)" stroke-width="1" stroke-dasharray="3 3"/>` : '';

  return `<div class="chart-holder">
    <svg class="chart" id="d-chart" viewBox="0 0 ${W} ${H}" role="img"
         aria-label="${esc(series.name)} 추이 ${obs.length}개 관측치">
      ${grid}${zero}
      <path d="${pathFor(obs, x, y)}" fill="none" stroke="var(--series-1)"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      <line id="d-cross" x1="0" x2="0" y1="${T}" y2="${H - B}"
            stroke="var(--baseline)" stroke-width="1" opacity="0"/>
      <circle id="d-dot" r="4" fill="var(--series-1)" stroke="var(--surface)"
              stroke-width="2" opacity="0"/>
      <rect id="d-hit" x="${L}" y="${T}" width="${W - L - R}" height="${H - T - B}"
            fill="transparent" style="cursor:crosshair"/>
      ${xlab}
    </svg>
    <div class="tooltip" id="d-tip"></div>
  </div>`;
}

function wireChartHover(series, obs) {
  const svg = document.getElementById('d-chart');
  if (!svg) return;
  const hit = document.getElementById('d-hit');
  const cross = document.getElementById('d-cross');
  const dot = document.getElementById('d-dot');
  const tip = document.getElementById('d-tip');
  const holder = svg.parentElement;

  // lineChart() 와 같은 좌표계를 써야 크로스헤어가 선 위에 정확히 붙는다.
  const { W, H, L, R, T, B } = chartBox();
  const vals = obs.map(p => p.v);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const pad = (hi - lo) * 0.08 || Math.abs(hi || 1) * 0.08;
  lo -= pad; hi += pad;
  const x = i => L + (i / (obs.length - 1)) * (W - L - R);
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  function move(ev) {
    const rect = svg.getBoundingClientRect();
    const sx = ((ev.clientX - rect.left) / rect.width) * W;
    const frac = (sx - L) / (W - L - R);
    let i = Math.round(frac * (obs.length - 1));
    i = Math.max(0, Math.min(obs.length - 1, i));
    const p = obs[i];

    cross.setAttribute('x1', x(i)); cross.setAttribute('x2', x(i));
    cross.setAttribute('opacity', '1');
    dot.setAttribute('cx', x(i)); dot.setAttribute('cy', y(p.v));
    dot.setAttribute('opacity', '1');

    tip.innerHTML = `<div class="t-date">${esc(fmtMonth(p.d, series.frequency))}</div>
                     <div class="t-val">${esc(fmt(series.unit, series.decimals, p.v))}</div>`;
    tip.classList.add('on');
    const px = (x(i) / W) * rect.width;
    const py = (y(p.v) / H) * rect.height;
    const tw = tip.offsetWidth;
    tip.style.left = Math.max(0, Math.min(holder.clientWidth - tw, px - tw / 2)) + 'px';
    tip.style.top = Math.max(0, py - tip.offsetHeight - 10) + 'px';
  }

  hit.addEventListener('mousemove', move);
  hit.addEventListener('touchmove', e => { if (e.touches[0]) move(e.touches[0]); }, { passive: true });
  const off = () => {
    cross.setAttribute('opacity', '0');
    dot.setAttribute('opacity', '0');
    tip.classList.remove('on');
  };
  hit.addEventListener('mouseleave', off);
  hit.addEventListener('touchend', off);
}

/* ------------------------------------------------------------------ 카드 */

function card(s) {
  const L = s.latest;
  const chips = [];

  if (L) {
    // 예측 대비 서프라이즈 — 컨센서스가 있는 지표에서만 의미가 있다.
    if (L.surprise !== null && L.surprise !== undefined) {
      const d = dirOf(L.surprise);
      chips.push(`<span class="chip ${d.cls}"><span class="lbl">예측대비</span>${d.mark} ${esc(fmtDelta(s.unit, s.decimals, L.surprise))}</span>`);
    }
    // 직전 발표 대비 변화
    if (L.previous !== null && L.previous !== undefined && L.actual !== null) {
      const d0 = L.actual - L.previous;
      const d = dirOf(d0);
      chips.push(`<span class="chip ${d.cls}"><span class="lbl">이전대비</span>${d.mark} ${esc(fmtDelta(s.unit, s.decimals, d0))}</span>`);
    }
  }
  if (!chips.length) {
    chips.push(`<span class="chip plain">${L ? '비교값 없음' : '발표 대기'}</span>`);
  }

  const valueTxt = L ? fmt(s.unit, s.decimals, L.actual) : '—';
  const nextTxt = s.upcoming && s.upcoming.releaseDate
    ? '다음 ' + fmtDate(s.upcoming.releaseDate)
    : '';

  return `<button class="card" data-id="${esc(s.id)}" type="button"
                  aria-label="${esc(s.name)} 상세 보기">
    <div class="card-head">
      <span class="card-name">${esc(s.name)}</span>
      <span class="card-ref">${esc(L ? fmtMonth(L.refDate, s.frequency) : '—')}</span>
    </div>
    <div class="card-value${L && L.actual !== null ? '' : ' missing'}">${esc(valueTxt)}</div>
    <div class="chips">${chips.join('')}</div>
    ${sparkline(s.observations, s.frequency === 'daily' || s.frequency === 'weekly' ? 90 : 24)}
    <div class="card-foot"><span>${esc(nextTxt)}</span><span>${s.observations.length}개 관측</span></div>
  </button>`;
}

/* ------------------------------------------------------------------ 상세 */

function sliceByRange(obs, key) {
  if (key === 'all' || obs.length === 0) return obs;
  const months = key === '1y' ? 12 : key === '3y' ? 36 : 60;
  const last = new Date(obs[obs.length - 1].d);
  const cut = new Date(last); cut.setMonth(cut.getMonth() - months);
  const iso = cut.toISOString().slice(0, 10);
  const out = obs.filter(p => p.d >= iso);
  return out.length >= 2 ? out : obs;
}

function releaseTable(s) {
  const rows = s.releases.map(r => {
    const dPrev = (r.actual !== null && r.previous !== null) ? r.actual - r.previous : null;
    const d = dirOf(dPrev);
    const surprise = (r.actual !== null && r.forecast !== null) ? r.actual - r.forecast : null;
    const ds = dirOf(surprise);
    const cell = (v) => v === null || v === undefined
      ? '<td class="na">—</td>'
      : `<td>${esc(fmt(s.unit, s.decimals, v))}</td>`;
    return `<tr>
      <td>${esc(fmtDate(r.releaseDate))}</td>
      <td>${esc(fmtMonth(r.refDate, s.frequency))}${r.manual ? '<span class="tag-manual">수동</span>' : ''}</td>
      ${cell(r.actual)}${cell(r.forecast)}${cell(r.previous)}
      <td class="${ds ? ds.cls : 'na'}">${ds ? ds.mark + ' ' + esc(fmtDelta(s.unit, s.decimals, surprise)) : '—'}</td>
      <td class="${d ? d.cls : 'na'}">${d ? d.mark + ' ' + esc(fmtDelta(s.unit, s.decimals, dPrev)) : '—'}</td>
    </tr>`;
  }).join('');

  return `<div class="table-scroll"><table class="rel">
    <thead><tr>
      <th>발표일</th><th>기준시점</th><th>실제</th><th>예측</th><th>이전</th>
      <th>예측대비</th><th>이전대비</th>
    </tr></thead>
    <tbody>${rows || '<tr><td colspan="7" class="na">데이터 없음</td></tr>'}</tbody>
  </table></div>`;
}

function openDetail(s) {
  const dlg = document.getElementById('detail');
  document.getElementById('d-title').textContent = s.name;

  const notes = [];
  if (s.note) notes.push(s.note);
  if (!s.hasForecastSource) notes.push('무료 컨센서스 소스가 없어 예측은 엑셀 백필분만 존재합니다.');
  if (s.observationsFromReleases) notes.push('※ 차트는 발표값 기반입니다(수집기 미실행 또는 API 키 미설정).');
  document.getElementById('d-note').textContent = notes.join(' ');

  const body = document.getElementById('d-body');

  function render(rangeKey) {
    const obs = sliceByRange(s.observations, rangeKey);
    const revs = s.revisions.length
      ? `<h3 class="sub">개정 이력 (엑셀에는 없던 정보)</h3>
         <div class="table-scroll"><table class="rel">
           <thead><tr><th>기준시점</th><th>감지 시각</th><th>이전 값</th><th>수정 값</th></tr></thead>
           <tbody>${s.revisions.map(r => `<tr>
             <td>${esc(fmtMonth(r.refDate, s.frequency))}</td>
             <td>${esc(r.observedAt.slice(0, 16).replace('T', ' '))}</td>
             <td>${esc(fmt(s.unit, s.decimals, r.from))}</td>
             <td>${esc(fmt(s.unit, s.decimals, r.to))}</td></tr>`).join('')}</tbody>
         </table></div>`
      : '';

    body.innerHTML = `
      <div class="range-row">
        ${['1y', '3y', '5y', 'all'].map(k =>
          `<button class="ghost" data-range="${k}" aria-pressed="${k === rangeKey}">${
            k === 'all' ? '전체' : k.toUpperCase()}</button>`).join('')}
      </div>
      ${lineChart(s, obs)}
      <h3 class="sub">발표 내역</h3>
      ${releaseTable(s)}
      ${revs}`;

    wireChartHover(s, obs);
    body.querySelectorAll('[data-range]').forEach(b =>
      b.addEventListener('click', () => render(b.dataset.range)));
  }

  render(s.observations.length > 60 ? '1y' : 'all');
  dlg.showModal();
}

/* ---------------------------------------------------------------- 신선도 */

function freshness(data) {
  if (!data.sources.length) {
    return `<div class="freshness"><h2>수집 상태</h2>
      <div class="src-row"><span class="src-msg">아직 자동 수집을 실행하지 않았습니다.
      현재 데이터는 엑셀 백필분입니다.</span></div></div>`;
  }
  const now = Date.now();
  const rows = data.sources.map(s => {
    const when = s.finished_at || s.started_at;
    const ageH = when ? (now - Date.parse(when)) / 36e5 : Infinity;
    let cls = 'ok', label = '정상';
    if (s.status !== 'ok') { cls = 'fail'; label = '실패'; }
    else if (ageH > 48)    { cls = 'stale'; label = '오래됨'; }
    const ageTxt = Number.isFinite(ageH)
      ? (ageH < 1 ? '방금 전' : ageH < 48 ? Math.round(ageH) + '시간 전' : Math.round(ageH / 24) + '일 전')
      : '기록 없음';
    // 검증 경고가 수십 건 붙으면 메시지가 화면을 뒤덮어 정작 상태를 못 읽게 된다.
    // 요약만 보여주고 전문은 title 속성으로 넘긴다.
    const full = s.message || '';
    const short = full.length > 160 ? full.slice(0, 160) + ' …' : full;
    return `<div class="src-row">
      <span class="src-name">${esc(s.source)}</span>
      <span class="badge ${cls}">${label}</span>
      <span class="src-when">${esc(ageTxt)}</span>
      <span class="src-msg" title="${esc(full)}">${esc(short)}</span>
    </div>`;
  }).join('');
  return `<div class="freshness"><h2>수집 상태</h2>${rows}</div>`;
}

/* ------------------------------------------------------------------ 조립 */

function render(data) {
  const app = document.getElementById('app');
  const gen = new Date(data.generatedAt);
  document.getElementById('subtitle').textContent =
    `지표 ${data.counts.series}종 · 발표 ${data.counts.releases.toLocaleString('ko-KR')}건 · ` +
    `갱신 ${gen.toLocaleString('ko-KR')}`;

  const failed = data.sources.filter(s => s.status !== 'ok');
  const banner = failed.length
    ? `<div class="warn-banner"><strong>${failed.map(f => esc(f.source)).join(', ')}</strong> 수집이
       실패했습니다. 해당 지표는 마지막 성공 값을 그대로 보여주고 있습니다 — 최신이 아닐 수 있습니다.</div>`
    : '';

  const upcoming = data.upcoming.length ? `
    <div class="upcoming">
      <h2>다가오는 발표</h2>
      <div class="upcoming-list">
        ${data.upcoming.map(u => `<div class="upcoming-item">
          <div class="upcoming-date">${esc(fmtDate(u.releaseDate))}</div>
          <div class="upcoming-name">${esc(u.name)}</div>
          <div class="upcoming-fc">예측 ${esc(u.forecast === null || u.forecast === undefined ? '—'
            : fmt(data.series.find(s => s.id === u.seriesId).unit,
                  data.series.find(s => s.id === u.seriesId).decimals, u.forecast))}</div>
        </div>`).join('')}
      </div>
    </div>` : '';

  const sections = data.categories.map(cat => {
    const list = data.series.filter(s => s.category === cat);
    if (!list.length) return '';
    return `<section class="cat">
      <h2>${esc(cat)}</h2>
      <div class="grid">${list.map(card).join('')}</div>
    </section>`;
  }).join('');

  app.innerHTML = banner + upcoming + sections + freshness(data);

  const byId = Object.fromEntries(data.series.map(s => [s.id, s]));
  app.querySelectorAll('.card').forEach(btn =>
    btn.addEventListener('click', () => openDetail(byId[btn.dataset.id])));
}

/* ------------------------------------------------------------------- 시작 */

document.getElementById('d-close').addEventListener('click', () =>
  document.getElementById('detail').close());

document.getElementById('theme-toggle').addEventListener('click', () => {
  const cur = document.documentElement.getAttribute('data-theme');
  const prefersDark = matchMedia('(prefers-color-scheme: dark)').matches;
  const next = cur ? (cur === 'dark' ? 'light' : 'dark') : (prefersDark ? 'light' : 'dark');
  document.documentElement.setAttribute('data-theme', next);
  try { localStorage.setItem('macro-theme', next); } catch (e) { /* 사생활 모드 */ }
});
try {
  const saved = localStorage.getItem('macro-theme');
  if (saved) document.documentElement.setAttribute('data-theme', saved);
} catch (e) { /* 무시 */ }

fetch(DATA_URL, { cache: 'no-cache' })
  .then(r => {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  })
  .then(render)
  .catch(err => {
    // 로컬 개발 안내는 로컬에서만 보여준다.
    // 배포된 사이트에서 네트워크 오류를 만난 사용자에게 'http.server 로 띄우세요' 는
    // 아무 도움이 되지 않고 오히려 혼란만 준다.
    const isLocal = location.protocol === 'file:' ||
                    /^(localhost|127\.0\.0\.1|\[::1\])$/.test(location.hostname);
    const hint = isLocal
      ? '파일을 직접 열지 말고 <code>python -m http.server -d site</code> 로 띄우세요.'
      : '잠시 후 새로고침해 주세요. 계속되면 데이터 파일이 아직 배포되지 않았을 수 있습니다.';
    document.getElementById('app').innerHTML =
      `<div class="error">데이터를 불러오지 못했습니다: ${esc(err.message)}<br>
       <span style="color:var(--text-secondary);font-size:13px">${hint}</span></div>`;
  });
