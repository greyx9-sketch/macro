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

/* ------------------------------------------------------------------- 툴팁 */

// `title` 속성은 **터치에서 절대 열리지 않는다.** 화면에 title 이 72곳 있었고,
// 그 중 ⓘ 표시는 '여기 설명이 있다' 고 약속까지 한다. 모바일 사용자에게는
// 약속만 있고 내용은 없는 상태였다.
//
// 그래서 마우스·키보드·터치 세 경로를 모두 여는 작은 팝오버를 둔다.
// 라이브러리는 쓰지 않는다 — 이 사이트는 빌드 체인이 없다.
// 마크업 쪽은 `data-tip="…"` 만 쓰면 된다.
let tipEl = null;
let tipOwner = null;

function tipNode() {
  if (!tipEl) {
    tipEl = document.createElement('div');
    tipEl.className = 'tip';
    tipEl.setAttribute('role', 'tooltip');
    tipEl.id = 'tip-bubble';
    document.body.appendChild(tipEl);
  }
  return tipEl;
}

function hideTip() {
  if (!tipEl) return;
  tipEl.classList.remove('on');
  if (tipOwner) tipOwner.removeAttribute('aria-describedby');
  tipOwner = null;
}

function showTip(el) {
  const text = el.dataset.tip;
  if (!text) return;
  const t = tipNode();
  t.textContent = text;
  t.classList.add('on');
  tipOwner = el;
  el.setAttribute('aria-describedby', t.id);

  // 좌우로 화면을 벗어나면 잘려서 못 읽는다. 뷰포트 안으로 밀어 넣는다.
  const M = 8;
  const r = el.getBoundingClientRect();
  const w = t.offsetWidth, h = t.offsetHeight;
  let x = r.left + r.width / 2 - w / 2;
  x = Math.max(M, Math.min(x, document.documentElement.clientWidth - w - M));
  // 위쪽에 자리가 없으면 아래에 붙인다.
  const above = r.top - h - 8 >= M;
  t.style.left = x + 'px';
  t.style.top = (above ? r.top - h - 8 : r.bottom + 8) + 'px';
}

function wireTips(root) {
  // 위임으로 처리한다. 카드·표는 매번 innerHTML 로 다시 그려지므로
  // 요소마다 리스너를 달면 새로 그릴 때마다 전부 다시 달아야 한다.
  const trigger = e => e.target.closest('[data-tip]');

  root.addEventListener('pointerover', e => {
    const el = trigger(e);
    if (el && e.pointerType === 'mouse') showTip(el);
  });
  root.addEventListener('pointerout', e => {
    if (trigger(e) && e.pointerType === 'mouse') hideTip();
  });
  root.addEventListener('focusin', e => { const el = trigger(e); if (el) showTip(el); });
  root.addEventListener('focusout', e => { if (trigger(e)) hideTip(); });

  // 터치. **캡처 단계여야 한다** — 버블 단계로 두면 카드의 클릭 처리기가 먼저 돌아
  // stopPropagation 이 이미 늦다 (실측: 팁을 눌렀는데 상세 패널이 함께 열렸다).
  root.addEventListener('click', e => {
    const el = trigger(e);
    if (!el) return;
    // 카드·타임라인 행 안의 팁은 가로채지 않는다. 그 안은 통째로 <button> 이고,
    // 눌렀을 때 열리는 상세 패널에 같은 설명이 본문으로 들어 있다.
    // 여기서 가로채면 '카드를 눌렀는데 아무 일도 안 일어나는' 죽은 구역이 생긴다.
    if (el.closest('button')) return;
    e.stopPropagation();
    e.preventDefault();
    if (tipOwner === el) hideTip(); else showTip(el);
  }, true);
}

document.addEventListener('click', e => {
  if (!e.target.closest('[data-tip]')) hideTip();
});
addEventListener('scroll', hideTip, true);
addEventListener('resize', hideTip);
addEventListener('keydown', e => { if (e.key === 'Escape') hideTip(); });

// 팁을 다는 표식. 키보드로 닿아야 하므로 초점을 받을 수 있어야 한다.
function tipMark(text, glyph = 'ⓘ', cls = 'tip-mark') {
  return `<span class="${cls}" data-tip="${esc(text)}" tabindex="0"
                role="button" aria-label="설명 보기">${glyph}</span>`;
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

// 전기 대비. '이전' 열(컨센서스 피드의 발표 당시 값)이 아니라
// **우리 계열의 직전 기준시점 실제값**과 뺀다.
//
// '이전' 은 0.1%p 로 반올림돼 있고 그 뒤 개정되지 않은 값이다. 실제값은 전체
// 정밀도의 현재 개정치다. 둘을 그대로 빼면 발표된 변화도, 우리 계열의 변화도
// 아닌 숫자가 나온다 (시간당 임금 2026-06: 표시 +0.05%p, 실제 변화 +0.08%p).
function prevDelta(r) {
  const ok = v => v !== null && v !== undefined;
  return (ok(r.actual) && ok(r.prevActual)) ? r.actual - r.prevActual : null;
}

// 반올림 전 값을 툴팁으로 남긴다 — 정밀 기준 차이를 버리지는 않는다.
function surpriseTitle(s, r) {
  if (r.surpriseRaw === null || r.surpriseRaw === undefined) return '';
  if (r.surprise === r.surpriseRaw) return '';
  return ` data-tip="컨센서스 해상도 기준입니다. 정밀 기준으로는 ${
    fmtDelta(s.unit, s.decimals, r.surpriseRaw)}."`;
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
  if (freq === 'quarterly') {
    return `${iso.slice(0, 4)} Q${Math.floor((parseInt(iso.slice(5, 7), 10) - 1) / 3) + 1}`;
  }
  return freq === 'monthly' ? iso.slice(0, 7) : iso.slice(0, 10);
}

// 서프라이즈 해석 — 사실을 먼저, 해석은 그 다음.
//
// 1차는 언제나 사실 진술이다: 예상 상회 / 하회 / 부합.
// 2차는 higherIsBetter 가 정의된 지표에서만 붙는 성격 표시다.
// 실업률이 예상보다 높은 것과 고용이 예상보다 많은 것은 둘 다 '상회' 지만
// 경제활동 관점의 방향은 반대이므로, 그 구분을 사실과 섞지 않고 따로 둔다.
//
// **색은 여기에 관여하지 않는다.** 상승 빨강·하락 파랑은 방향 표기이고,
// 좋고 나쁨은 다른 축이다. 둘을 색으로 섞으면 둘 다 못 읽게 된다.
function readSurprise(surprise, higherIsBetter) {
  if (surprise === null || surprise === undefined || Number.isNaN(surprise)) return null;
  const beat = surprise > EPS, miss = surprise < -EPS;
  const fact = beat ? '예상 상회' : miss ? '예상 하회' : '예상 부합';
  let tone = null;
  if (higherIsBetter !== null && higherIsBetter !== undefined && (beat || miss)) {
    tone = (beat === higherIsBetter) ? '경기에 우호적' : '경기에 비우호적';
  }
  return { fact, tone };
}
function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

/* ------------------------------------------------------------------ 차트 */

function pathFor(points, x, y) {
  return points.map((p, i) => (i ? 'L' : 'M') + x(i).toFixed(2) + ' ' + y(p.v).toFixed(2)).join(' ');
}

// 기준시점이 건너뛰어진 구간을 실선으로 이으면 **없는 데이터를 그린 것**이 된다.
// (2025-10 은 CPI 발표 자체가 없었다)
//
// x 축이 값의 순번이라 빠진 달만큼 간격이 벌어지지도 않는다. 그래서 선을 끊는 대신
// 그 구간만 **점선**으로 잇는다 — 이어져 보이되 '여기는 관측이 없다' 가 드러난다.
//
// 월간·분기만 판정한다. 주간·일간 계열은 MAX_POINTS 다운샘플링을 거치므로
// 간격이 벌어진 것이 결측인지 솎아낸 것인지 화면 쪽에서는 구분할 수 없다.
const GAP_PERIOD_DAYS = { monthly: 31 * 1.6, quarterly: 92 * 1.6 };

function pathSegments(points, x, y, frequency) {
  const limit = GAP_PERIOD_DAYS[frequency];
  const at = i => x(i).toFixed(2) + ' ' + y(points[i].v).toFixed(2);
  if (!limit) return { solid: pathFor(points, x, y), dashed: '' };

  const solid = [];
  const dashed = [];
  let run = ['M' + at(0)];
  for (let i = 1; i < points.length; i++) {
    const days = (Date.parse(points[i].d) - Date.parse(points[i - 1].d)) / 864e5;
    if (days > limit) {
      if (run.length > 1) solid.push(run.join(' '));
      dashed.push('M' + at(i - 1) + ' L' + at(i));
      run = ['M' + at(i)];
    } else {
      run.push('L' + at(i));
    }
  }
  if (run.length > 1) solid.push(run.join(' '));
  return { solid: solid.join(' '), dashed: dashed.join(' ') };
}

// 스파크라인이 덮는 기간. **개수가 아니라 시간으로 자른다.**
//
// 예전에는 월간 24점 / 일간·주간 90점이었는데, 그러면 같은 카테고리 안에서
// 덮는 기간이 제각각인 카드가 같은 크기로 나란히 놓인다. 실측으로 금융 카테고리는
// 미국 CDS 0.7년 · 한국 기준금리 4.3년이었고, 고용은 1.9년~5.7년이었다.
// 폭이 같은데 기간이 다르면 **기울기 비교가 거짓말이 된다.**
const SPARK_YEARS = 2;
const SPARK_MAX_POINTS = 120;

function sparkWindow(obs) {
  if (!obs.length) return [];
  const cut = new Date(obs[obs.length - 1].d);
  cut.setFullYear(cut.getFullYear() - SPARK_YEARS);
  const iso = cut.toISOString().slice(0, 10);
  let pts = obs.filter(p => p.d >= iso);
  // 2년치가 통째로 없는 계열(ISM 22개월)은 있는 만큼만 쓴다.
  if (pts.length < 2) pts = obs.slice(-2);
  if (pts.length > SPARK_MAX_POINTS) {
    const step = pts.length / SPARK_MAX_POINTS;
    const picked = [];
    for (let i = 0; i < SPARK_MAX_POINTS; i++) picked.push(pts[Math.floor(i * step)]);
    picked[picked.length - 1] = pts[pts.length - 1];   // 최신값은 절대 잃지 않는다
    pts = picked;
  }
  return pts;
}

/** 카드용 스파크라인. 축·눈금 없이 형태만 전달한다. */
function sparkline(pts) {
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
      ${(() => {
        const seg = pathSegments(obs, x, y, series.frequency);
        return `${seg.dashed ? `<path d="${seg.dashed}" fill="none" stroke="var(--series-1)"
            stroke-width="2" stroke-dasharray="3 4" opacity="0.55"/>` : ''}
      <path d="${seg.solid}" fill="none" stroke="var(--series-1)"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>`;
      })()}
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

/** 최신 발표의 요약 칩. **카드와 상세 헤더가 같은 함수를 쓴다** —
 *  같은 칩을 두 벌의 코드로 만들면 언젠가 값이 갈린다. 그게 qoq 버그의 구조였다. */
function latestChips(s) {
  const L = s.latest;
  const chips = [];

  if (L) {
    // 예측 대비 서프라이즈 — 컨센서스가 있는 지표에서만 의미가 있다.
    if (L.surprise !== null && L.surprise !== undefined) {
      const d = dirOf(L.surprise);
      chips.push(`<span class="chip ${d.cls}"${surpriseTitle(s, L)}><span class="lbl">예측대비</span>${d.mark} ${esc(fmtDelta(s.unit, s.decimals, L.surprise))}</span>`);
      const read = readSurprise(L.surprise, s.higherIsBetter);
      if (read && read.tone) {
        const good = read.tone === '경기에 우호적';
        chips.push(`<span class="chip tone ${good ? 'tone-pos' : 'tone-neg'}"
          data-tip="값이 클수록 경제활동에 우호적인지를 지표별로 표시한 단순 기준입니다. 투자 판단이 아닙니다."
          >${esc(read.fact)} · ${esc(good ? '우호적' : '비우호적')}</span>`);
      } else if (read) {
        chips.push(`<span class="chip tone">${esc(read.fact)}</span>`);
      }
    }
    // 직전 기준시점 대비 변화
    const d0 = prevDelta(L);
    if (d0 !== null) {
      const d = dirOf(d0);
      chips.push(`<span class="chip ${d.cls}"
        data-tip="직전 기준시점의 현재 확정치와 비교한 값입니다."
        ><span class="lbl">이전대비</span>${d.mark} ${esc(fmtDelta(s.unit, s.decimals, d0))}</span>`);
    }
  }
  if (!chips.length) {
    chips.push(`<span class="chip plain">${L ? '비교값 없음' : '발표 대기'}</span>`);
  }
  return chips;
}

function card(s) {
  const L = s.latest;

  // 아직 한 번도 수집되지 않은 지표(새로 추가한 직후)는 빈 카드가 된다.
  // 그대로 두면 고장난 것처럼 보이므로 상태를 분명히 밝힌다.
  if (!L && !s.observations.length) {
    return `<button class="card pending" data-id="${esc(s.id)}" type="button"
                    aria-label="${esc(s.name)} — 아직 수집 전">
      <div class="card-head"><span class="card-name">${esc(s.name)}</span></div>
      <div class="card-value missing">—</div>
      <div class="chips"><span class="chip plain">첫 수집 대기</span></div>
      <div class="card-foot"><span>다음 실행에서 채워집니다</span><span></span></div>
    </button>`;
  }

  const chips = latestChips(s);
  const valueTxt = L ? fmt(s.unit, s.decimals, L.actual) : '—';
  const nxt = nextReleaseLabel(s);
  const pts = sparkWindow(s.observations);
  // 오른쪽 칸에는 스파크라인이 덮는 기간을 적었다. 그런데 그 기간을 전 지표
  // '최근 2년' 으로 통일한 순간, 22장이 사실상 같은 문자열을 반복하게 됐다 —
  // 정보량 0. 규칙은 카드마다가 아니라 화면에 한 번만 적으면 된다(격자 위 한 줄).

  return `<button class="card${nxt.overdue ? ' overdue' : ''}" data-id="${esc(s.id)}" type="button"
                  aria-label="${esc(s.name)} 상세 보기">
    <div class="card-head">
      <span class="card-name">${esc(s.name)}</span>
      <span class="card-ref">${esc(L ? fmtMonth(L.refDate, s.frequency) : '—')}</span>
    </div>
    <div class="card-value${L && L.actual !== null ? '' : ' missing'}">${esc(valueTxt)}</div>
    ${contextChip(s)}
    <div class="chips">${chips.join('')}</div>
    ${sparkline(pts)}
    <div class="card-foot"><span class="${nxt.overdue ? 'overdue-txt' : ''}">${nxt.html}</span></div>
  </button>`;
}

// '5년 상위 37%' 와 '5년 하위 20%' 가 섞여 있었다. 둘 다 작은 숫자를 쓰려고
// 50% 에서 말을 뒤집은 것인데, 그러면 카드 여덟 장을 훑으며 눈으로 비교할 수가 없다 —
// 매번 단어를 읽고 머릿속에서 뒤집어야 한다.
//
// 한 방향으로만 말한다. 0 = 5년 최저, 100 = 5년 최고. '위치' 에는 상·하 함의가
// 없으므로, 바닥에 있는 값이 '상위 98%' 로 읽히던 정반대 오독도 생기지 않는다.
function rankText(c) { return `5년 내 위치 ${c.pct5y}/100`; }
const RANK_TIP = '최근 1년 최저~최고와, 최근 5년 관측치 중 현재 값의 위치입니다. '
  + '0 이면 5년 최저, 100 이면 5년 최고입니다.';

/** 카드용 맥락 한 줄. '지금 3.5% 가 높은 건가' 에 대한 답. */
function contextChip(s) {
  const c = s.context;
  if (!c || c.lo1y === null || c.hi1y === null) return '';
  return `<div class="ctx" data-tip="${esc(RANK_TIP)} (${c.n5y}개 관측)"
    >1년 ${esc(fmt(s.unit, s.decimals, c.lo1y))}~${esc(fmt(s.unit, s.decimals, c.hi1y))} · ${esc(rankText(c))}</div>`;
}

// '다음 발표' 라는 개념 자체가 없는 계열들. 빈 칸으로 두면 수집이 고장난 것처럼
// 보이는데, 이유는 지표마다 다르다 — 하나는 시장 데이터고 하나는 정책 회의다.
const MARKET_DAILY = new Set(['t10y2y', 'cds_us_5y', 'cds_kr_5y']);
const POLICY_MEETING = new Set(['fed_funds_upper', 'bok_base_rate']);

// 다음 발표를 언제 보면 되나. 확정 > 추정 > 아무것도 없음 순.
//
// 추정 구간이 **이미 지났는데 값이 안 들어왔으면** 그건 그 자체로 신호다 —
// 발표는 났는데 우리가 못 받았다는 뜻이다. 지금까지는 조용히 지난 달 값을 보여줬다.
// 확정 발표일이 '월' 단위뿐이면 우리 추정 구간이 더 많은 것을 말한다.
// export_json.build() 의 '다가오는 발표' 와 **같은 규칙**이어야 한다 —
// 카드가 '2026-08 중' 이라 하는데 위 목록은 '08/09~08/15' 라고 하면 둘 다 못 믿는다.
function useEstimate(s) {
  const c = s.upcoming, e = s.estimatedNext;
  if (!e) return false;
  if (!c || !c.releaseDate) return true;
  return c.releaseDate.length <= 7 && e.median.slice(0, 7) === c.releaseDate.slice(0, 7);
}

function nextReleaseLabel(s) {
  const today = new Date().toISOString().slice(0, 10);

  // 갱신이 멈춘 것이 가장 중요한 사실이다 — 다음 발표일보다 먼저 말한다.
  //
  // **경보일 때만 적는다.** 월간 지표는 그 달 발표 전까지 늘 1주기쯤 뒤에 있어서,
  // 밀린 정도를 늘 적으면 20장이 '1.2개월' 을 달고 있게 되고 진짜 신호가 묻힌다.
  const st = s.staleness;
  if (st && st.alarm) {
    return {
      html: `<span data-tip="최신 기준시점이 ${esc(st.latestRef)} 입니다. 발표 지연을 감안하고도 ${st.behind}${st.unit}치가 밀렸습니다 — 원본이 늦거나 수집이 끊겼을 수 있습니다.">${st.behind}${esc(st.unit)}째 갱신 없음</span>`,
      overdue: true,
    };
  }

  if (s.upcoming && s.upcoming.releaseDate && !useEstimate(s)) {
    const rd = s.upcoming.releaseDate;
    // '2026-08-07' 보다 '3일 뒤' 가 먼저 읽힌다. 확정 일정에만 붙인다 —
    // 추정은 구간이라 D-day 라는 개념이 없다.
    const gap = rd.length > 7 ? gapLabel(dayGap(rd, today)) : null;
    return {
      html: '다음 ' + esc(fmtDate(rd)) + (gap ? ` · ${esc(gap)}` : ''),
      overdue: false,
    };
  }

  const e = s.estimatedNext;
  if (!e) {
    if (MARKET_DAILY.has(s.id)) {
      return { html: '<span data-tip="발표 일정이 있는 통계가 아니라 매 영업일 갱신되는 시장 데이터입니다.">매 영업일 갱신</span>', overdue: false };
    }
    if (POLICY_MEETING.has(s.id)) {
      // 카드 안에 <a> 를 넣지 않는다 — <button> 안의 링크는 유효하지 않은 HTML 이고
      // Chrome 이 포커스를 버튼으로 되돌린다. 공식 일정 링크는 상세 각주에 이미 있다.
      return { html: '<span data-tip="정기 발표가 아니라 정책 회의에서 결정됩니다. 공식 일정 링크는 상세 패널 맨 아래에 있습니다.">정책회의에서 결정</span>', overdue: false };
    }
    // 빈 칸으로 두면 수집이 고장난 것처럼 보인다. 모른다는 것을 모른다고 적는다.
    return {
      html: '<span data-tip="캘린더에 확정 일정이 없고, 과거 발표 시점의 편차가 커서(구간 폭 3주 초과) 추정하지 않았습니다. 없는 규칙을 있는 척하지 않습니다.">다음 발표일 미정</span>',
      overdue: false,
    };
  }

  const md = iso => iso.slice(5).replace('-', '/');
  if (e.to < today) {
    return {
      html: `<span data-tip="과거 ${e.sample}회 기준 ${e.from} ~ ${e.to} 에 나왔어야 하는데 아직 값이 없습니다. 발표가 늦어졌거나 수집이 밀렸을 수 있습니다."
             >발표 예정일 경과</span>`,
      overdue: true,
    };
  }
  return {
    html: `<span data-tip="캘린더에 확정 일정이 없어 과거 ${e.sample}회의 발표 시점에서 추정했습니다 (그중 ${e.inBand}회가 이 구간)."
           >다음 ${md(e.from)}~${md(e.to)} 예상</span>`,
    overdue: false,
  };
}

/* ------------------------------------------------------- 다가오는 발표 */

const WEEKDAY_KO = ['일', '월', '화', '수', '목', '금', '토'];

/** 그 날짜가 속한 주의 월요일. 주차 묶음의 기준선이다. */
function weekStartOf(iso) {
  const d = new Date(iso.slice(0, 10) + 'T00:00:00Z');
  const shift = (d.getUTCDay() + 6) % 7;          // 월=0 … 일=6
  d.setUTCDate(d.getUTCDate() - shift);
  return d.toISOString().slice(0, 10);
}

/** 오늘이 며칠 뒤인지 — '2026-08-07' 보다 '3일 뒤' 가 먼저 읽힌다. */
function dayGap(iso, todayIso) {
  const a = Date.parse(iso.slice(0, 10) + 'T00:00:00Z');
  const b = Date.parse(todayIso + 'T00:00:00Z');
  return Math.round((a - b) / 86400000);
}
function gapLabel(n) {
  if (n === 0) return '오늘';
  if (n === 1) return '내일';
  if (n < 0) return null;
  return `${n}일 뒤`;
}

// 가로로 늘어놓으면 12개 중 4개가 화면 밖으로 나가고, 8/07 다음이 곧장 10/25 인
// **2.5개월 구멍이 균일한 카드 줄**로 표현된다. 세로로 흐르는 주차 묶음이라야
// 구멍이 구멍으로 보인다.
//
// 묶음 기준은 sortKey 다. 정렬키와 같아야 그룹이 목록 안에서 **연속**하고,
// 추정 항목(구간)도 확정 항목과 같은 자로 재게 된다.
function upcomingSection(data) {
  // 이미 지난 추정 구간은 뺀다. '다가오는 발표' 맨 앞에 지난 날짜가 놓이면
  // 목록 전체를 못 믿게 된다. 그 지표는 카드 쪽에서 '발표 예정일 경과' 로 따로 알린다.
  // JSON 이 만들어진 날이 아니라 **보는 날** 기준이어야 해서 여기서 거른다.
  const todayIso = new Date().toISOString().slice(0, 10);
  const list = (data.upcoming || []).filter(u => !(u.estimated && u.to < todayIso));
  if (!list.length) return '';

  const byId = Object.fromEntries(data.series.map(s => [s.id, s]));
  const thisWeek = weekStartOf(todayIso);
  const nextWeek = weekStartOf(new Date(Date.parse(thisWeek + 'T00:00:00Z') + 7 * 86400000)
    .toISOString().slice(0, 10));

  const bucketOf = u => {
    const w = weekStartOf(u.sortKey);
    if (w <= thisWeek) return 0;
    if (w === nextWeek) return 1;
    return 2;
  };
  const TITLES = ['이번 주', '다음 주', '그 이후'];

  const md = iso => iso.slice(5).replace('-', '/');
  let lastDay = null;

  const row = u => {
    const s = byId[u.seriesId];
    const gap = u.estimated ? null : gapLabel(dayGap(u.releaseDate, todayIso));
    let when, tip = '';
    if (u.estimated) {
      when = `${md(u.from)}~${md(u.to)} 예상`;
      tip = ` data-tip="캘린더에 확정 일정이 없어 과거 ${u.sample}회의 발표 시점에서 추정했습니다 (그중 ${u.inBand}회가 이 구간)." tabindex="0"`;
    } else if (u.releaseDate.length <= 7) {
      when = fmtDate(u.releaseDate);
    } else {
      const day = u.releaseDate.slice(0, 10);
      const wd = WEEKDAY_KO[new Date(day + 'T00:00:00Z').getUTCDay()];
      // 같은 날 여러 건이면 날짜는 첫 줄에만 — 타임라인과 같은 규칙이다.
      when = day === lastDay ? '' : `${md(day)} ${wd}`;
      lastDay = day;
    }

    const fc = u.forecast === null || u.forecast === undefined
      ? (s && u.previous !== null && u.previous !== undefined
          ? '이전 ' + fmt(s.unit, s.decimals, u.previous) : '')
      : '예측 ' + fmt(s.unit, s.decimals, u.forecast);

    return `<div class="up-row${u.estimated ? ' est' : ''}"${tip}>
      <span class="up-when">${esc(when)}</span>
      <span class="up-name">${esc(u.name)}</span>
      <span class="up-fc">${esc(fc)}</span>
      <span class="up-gap">${esc(gap || '')}</span>
    </div>`;
  };

  // 헤더와 행을 **한 grid 안에** 형제로 놓는다. 그룹마다 따로 격자를 만들면
  // '08/09~08/15 예상' 이 있는 그룹과 '08/03 월' 뿐인 그룹의 첫 열 폭이 갈린다 —
  // 최근 발표 목록에서 subgrid 로 고쳤던 것과 같은 문제다.
  const groups = TITLES.map((title, i) => {
    const items = list.filter(u => bucketOf(u) === i);
    if (!items.length) return '';       // 빈 구간은 헤더째 생략한다
    lastDay = null;                     // 그룹이 바뀌면 날짜를 다시 적는다
    return `<h3 class="up-head">${title}</h3>${items.map(row).join('')}`;
  }).join('');

  return `<div class="upcoming">
    <h2>다가오는 발표</h2>
    <div class="up-list">${groups}</div>
  </div>`;
}

/* -------------------------------------------------------------- 타임라인 */

// '이번 주에 뭐 나왔고 어땠나' 를 카테고리 가로질러 시간순으로 한 곳에.
// 카드는 카테고리별로 묶여 있어 이 질문에 답하려면 화면을 훑어야 했다.
function timelineSection(data, byId) {
  if (!data.timeline || !data.timeline.length) return '';

  let lastDay = null;
  const rows = data.timeline.map(t => {
    const s = byId[t.seriesId];
    // 서프라이즈는 export 가 한 번만 계산한다. 여기서 다시 빼면 표·카드·막대와
    // 값이 갈릴 수 있다 — 계산이 여러 벌로 흩어지는 것이 qoq 버그의 구조였다.
    const surprise = t.surprise ?? null;
    const d = dirOf(surprise);
    const read = readSurprise(surprise, s.higherIsBetter);
    const day = t.releaseDate.slice(0, 10);
    const dayLabel = day === lastDay ? '' : day;
    lastDay = day;

    const surpriseCell = d
      ? `<span class="tl-sur ${d.cls}"${surpriseTitle(s, t)}>${d.mark} ${esc(fmtDelta(s.unit, s.decimals, surprise))}</span>`
      : '<span class="tl-sur na">예측 없음</span>';
    // 예측이 없으면 이 칸과 서프라이즈 칸이 나란히 '예측이 없다'고 두 번 말한다.
    // 셀은 남기고 내용만 비운다 — 트랙 수가 줄면 subgrid 열 정렬이 도로 깨진다.
    const fcCell = t.forecast === null || t.forecast === undefined
      ? ''
      : `예측 ${esc(fmt(s.unit, s.decimals, t.forecast))}`;
    const toneCell = read && read.tone
      ? `<span class="tl-tone ${read.tone === '경기에 우호적' ? 'tone-pos' : 'tone-neg'}"
           data-tip="값이 클수록 경제활동에 우호적인지를 지표별로 표시한 단순 기준입니다. 투자 판단이 아닙니다."
           >${esc(read.tone === '경기에 우호적' ? '우호적' : '비우호적')}</span>`
      : '';

    return `<button class="tl-row" data-id="${esc(t.seriesId)}" type="button"
              aria-label="${esc(s.name)} 상세 보기">
      <span class="tl-day">${esc(dayLabel)}</span>
      <span class="tl-name">${esc(t.name)}</span>
      <span class="tl-ref">${esc(fmtMonth(t.refDate, s.frequency))}</span>
      <span class="tl-actual">${esc(fmt(s.unit, s.decimals, t.actual))}</span>
      <span class="tl-fc">${fcCell}</span>
      ${surpriseCell}${toneCell}
    </button>`;
  }).join('');

  // 색 규칙이 카드 22장 **아래** 푸터에만 있었다. 색을 처음 마주치는 곳에 적는다.
  return `<section class="timeline">
    <h2>최근 발표 <span class="legend">▲ 상승 · ▼ 하락 — 방향이지 좋고 나쁨이 아닙니다</span></h2>
    <div class="tl-list">${rows}</div>
  </section>`;
}

/** 서프라이즈 추이 막대 — 예측을 계속 상회/하회하는 편향은 이력으로만 보인다. */
function surpriseBars(series) {
  const h = series.surpriseHistory || [];
  if (h.length < 2) return '';

  // 왼쪽은 '상회/하회' 라벨 자리라 오른쪽보다 넓다.
  const W = 820, H = 92, LPAD = 36, RPAD = 18, GAP = 3;
  const span = W - LPAD - RPAD;
  const vals = h.map(p => p.value);
  const mx = Math.max(...vals.map(Math.abs)) || 1;
  const mid = H / 2;
  const bw = span / h.length - GAP;
  const scale = (H / 2 - 16) / mx;

  const bars = h.map((p, i) => {
    const x = LPAD + i * (span / h.length);
    const hgt = Math.max(1, Math.abs(p.value) * scale);
    const y = p.value >= 0 ? mid - hgt : mid;
    const cls = dirOf(p.value).cls;
    // SVG <title> 은 마우스 전용이다 — title 속성 108곳을 data-tip 으로 바꾼 이유가
    // 그것인데 여기만 남아 있었다. 같은 팝오버를 쓰면 터치에서도 열린다.
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}"
              height="${hgt.toFixed(1)}" rx="2" class="sbar ${cls}"
              data-tip="${esc(fmtMonth(p.refDate, series.frequency))} ${esc(fmtDelta(series.unit, series.decimals, p.value))}"/>`;
  }).join('');

  // 어느 막대가 언제인지 말해 주는 것이 없었다. 첫·중간·마지막 셋만 적는다.
  const at = i => LPAD + i * (span / h.length) + bw / 2;
  const xi = h.length >= 3 ? [0, Math.floor((h.length - 1) / 2), h.length - 1] : [0, h.length - 1];
  const xlab = [...new Set(xi)].map((i, k, arr) =>
    `<text x="${at(i).toFixed(1)}" y="${H - 1}" font-size="10" fill="var(--text-muted)"
       text-anchor="${k === 0 ? 'start' : k === arr.length - 1 ? 'end' : 'middle'}"
       >${esc(fmtMonth(h[i].refDate, series.frequency))}</text>`).join('');

  const beats = h.filter(p => p.value > 0).length;
  return `<h3 class="sub">서프라이즈 추이 <span class="sub-note">최근 ${h.length}회 중 ${beats}회 예상 상회</span></h3>
    <svg class="sbars" viewBox="0 0 ${W} ${H}" role="img"
         aria-label="최근 ${h.length}회 서프라이즈. ${beats}회 예상 상회">
      <line x1="${LPAD}" x2="${W - RPAD}" y1="${mid}" y2="${mid}"
            stroke="var(--baseline)" stroke-width="1"/>
      <text x="${LPAD - 6}" y="${(mid - 5).toFixed(1)}" font-size="10" text-anchor="end"
            fill="var(--text-muted)">상회</text>
      <text x="${LPAD - 6}" y="${(mid + 12).toFixed(1)}" font-size="10" text-anchor="end"
            fill="var(--text-muted)">하회</text>
      ${bars}${xlab}
    </svg>`;
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

// '이전' 셀 — 발표 당시 공표된 값을 그대로 보여주되, 그 뒤 개정돼 현재 계열값과
// 달라졌으면 표식을 단다. 표식이 없으면 바로 아랫줄 '실제' 와 어긋난 이유를
// 알 길이 없어 표가 자기모순을 일으키는 것처럼 보인다.
function previousCell(s, r) {
  const ok = v => v !== null && v !== undefined;
  if (!ok(r.previous)) return '<td class="na">—</td>';
  const shown = fmt(s.unit, s.decimals, r.previous);
  if (!ok(r.prevActual)) return `<td>${esc(shown)}</td>`;

  // 컨센서스 자릿수로 맞춰 봐도 다르면 개정된 것이다.
  const d = s.consensusDecimals;
  const p = 10 ** (d === null || d === undefined ? 10 : d);
  if (Math.round(r.prevActual * p) === Math.round(r.previous * p)) {
    return `<td>${esc(shown)}</td>`;
  }
  return `<td>${esc(shown)}<span class="tag-revised"
    data-tip="발표 당시 ${esc(shown)} → 현재 ${esc(fmt(s.unit, s.decimals, r.prevActual))} (개정)" tabindex="0" role="button" aria-label="개정 내역 보기"
    >↻</span></td>`;
}

// 기준시점 사이가 한 주기보다 벌어지면 그 사이 기간에는 발표가 없었다는 뜻이다.
// 2025-10 CPI 가 그렇다 — 그 달은 아예 발표되지 않아 행 자체가 없고,
// 표는 12-18 에서 10-24 로 조용히 건너뛴다. 사용자에게는 데이터가 깨진 것처럼 보인다.
//
// **이유는 쓰지 않는다.** 우리가 아는 것은 '그 기준시점의 발표가 없다' 까지다.
// 셧다운이라고 단정하면 다른 사유일 때 거짓말이 된다.
function missingRefs(s, newerRef, olderRef) {
  const step = { monthly: 1, quarterly: 3 }[s.frequency];
  if (!step) return [];                       // 주간·일간·이벤트는 주기가 고르지 않다
  const out = [];
  const d = new Date(olderRef + 'T00:00:00Z');
  for (let i = 0; i < 24; i++) {              // 폭주 방지
    d.setUTCMonth(d.getUTCMonth() + step);
    const iso = d.toISOString().slice(0, 10);
    if (iso >= newerRef) break;
    out.push(iso);
  }
  return out.reverse();                       // 표는 최신순이다
}

/** 기간 버튼과 같은 자로 발표 내역을 자른다.
 *
 *  지금까지 1Y 를 눌러도 표는 60행·2021년까지 그대로였다 — 기간 선택이
 *  차트에만 걸려 있어서, 패널이 3.3화면짜리가 됐다. `sliceByRange` 와
 *  **같은 컷 날짜**를 써야 차트와 표가 같은 구간을 말한다. */
function sliceReleases(s, key) {
  if (key === 'all' || !s.releases.length) return s.releases;
  const months = key === '1y' ? 12 : key === '3y' ? 36 : 60;
  const newest = s.releases[0].refDate;        // 표는 최신순이다
  const cut = new Date(newest + 'T00:00:00Z');
  cut.setUTCMonth(cut.getUTCMonth() - months);
  const iso = cut.toISOString().slice(0, 10);
  const out = s.releases.filter(r => r.refDate >= iso);
  return out.length >= 2 ? out : s.releases;   // sliceByRange 와 같은 방어
}

function releaseTable(s, rangeKey) {
  const gapRow = ref => `<tr class="gap-row"><td colspan="7">
      ${esc(fmtMonth(ref, s.frequency))} — 발표 없음</td></tr>`;

  const shown = sliceReleases(s, rangeKey);
  const rows = shown.map((r, i) => {
    const prevRow = shown[i + 1];              // 한 칸 아래 = 더 오래된 기준시점
    const gaps = prevRow ? missingRefs(s, r.refDate, prevRow.refDate) : [];
    const dPrev = prevDelta(r);
    const d = dirOf(dPrev);
    const ds = dirOf(r.surprise ?? null);
    const cell = (v) => v === null || v === undefined
      ? '<td class="na">—</td>'
      : `<td>${esc(fmt(s.unit, s.decimals, v))}</td>`;
    return `<tr>
      <td>${esc(fmtDate(r.releaseDate))}</td>
      <td>${esc(fmtMonth(r.refDate, s.frequency))}${r.manual ? '<span class="tag-manual">수동</span>' : ''}</td>
      ${cell(r.actual)}${cell(r.forecast)}${previousCell(s, r)}
      <td class="${ds ? ds.cls : 'na'}"${surpriseTitle(s, r)}>${ds ? ds.mark + ' ' + esc(fmtDelta(s.unit, s.decimals, r.surprise)) : '—'}</td>
      <td class="${d ? d.cls : 'na'}">${d ? d.mark + ' ' + esc(fmtDelta(s.unit, s.decimals, dPrev)) : '—'}</td>
    </tr>${gaps.map(gapRow).join('')}`;
  }).join('');

  return `<div class="table-scroll"><table class="rel">
    <thead><tr>
      <th>발표일</th><th>기준시점</th><th>실제</th><th>예측</th>
      <th>이전 ${tipMark('발표 당시 공표된 직전 값입니다. 컨센서스 소스에서 오며 반올림돼 있고, 이후 개정으로 현재 계열값과 다를 수 있습니다.')}</th>
      <th>예측대비 ${tipMark("컨센서스와 같은 자릿수로 맞춰 계산합니다. 발표된 값과 예측이 같으면 '부합'이 됩니다.")}</th>
      <th>이전대비 ${tipMark("직전 기준시점의 현재 확정치와 비교한 값입니다. 위의 '이전'(발표 당시 값)이 아닙니다.")}</th>
    </tr></thead>
    <tbody>${rows || '<tr><td colspan="7" class="na">데이터 없음</td></tr>'}</tbody>
  </table></div>
  <p class="table-foot">${shown.length === s.releases.length
    ? `전체 ${s.releases.length}건`
    : `${rangeKey === 'all' ? '전체' : rangeKey.toUpperCase()} 기준 ${shown.length}건 · 전체 ${s.releases.length}건`}</p>`;
}

function openDetail(s) {
  if (!s) return;
  const dlg = document.getElementById('detail');
  document.getElementById('d-title').textContent = s.name;

  const L = s.latest;
  document.getElementById('d-now').innerHTML = L
    ? `<span class="d-now-val">${esc(fmt(s.unit, s.decimals, L.actual))}</span>
       <span class="d-now-ref">${esc(fmtMonth(L.refDate, s.frequency))}</span>
       <span class="chips">${latestChips(s).join('')}</span>`
    : '<span class="d-now-ref">아직 수집된 발표가 없습니다</span>';

  const notes = [];
  if (s.note) notes.push(s.note);
  if (!s.hasForecastSource) notes.push('무료 컨센서스 소스가 없어 예측은 엑셀 백필분만 존재합니다.');
  if (s.observationsFromReleases) notes.push('※ 차트는 발표값 기반입니다(수집기 미실행 또는 API 키 미설정).');
  document.getElementById('d-note').textContent = notes.join(' ');

  const body = document.getElementById('d-body');

  function render(rangeKey, resetScroll) {
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
      ${contextLine(s)}
      ${nextLine(s)}
      ${surpriseBars(s)}
      <h3 class="sub">발표 내역</h3>
      ${releaseTable(s, rangeKey)}
      ${revs}
      ${detailFoot(s)}`;

    wireChartHover(s, obs);
    body.querySelectorAll('[data-range]').forEach(b =>
      b.addEventListener('click', () => render(b.dataset.range, false)));

    // 열 때만 맨 위로 올린다. 기간 버튼으로 다시 그릴 때도 위로 튀면
    // 표를 보다가 기간을 바꾼 사람에게는 그것도 똑같은 버그다.
    //
    // **showModal() 뒤에 해야 한다.** 닫혀 있는 dialog 는 display:none 이라
    // scrollTop 대입이 통째로 무시되고, 열리는 순간 이전 위치가 되살아난다.
    if (resetScroll) {
      if (!dlg.open) dlg.showModal();
      body.scrollTop = 0;
    }
  }

  render(s.observations.length > 60 ? '1y' : 'all', true);
  if (!dlg.open) dlg.showModal();
}

/** 현재 값이 최근 이력의 어디쯤인가 — 차트만으로는 답이 안 나오는 질문. */
function contextLine(s) {
  const c = s.context;
  if (!c) return '';
  const parts = [];
  if (c.lo1y !== null && c.hi1y !== null) {
    parts.push(`최근 1년 ${esc(fmt(s.unit, s.decimals, c.lo1y))} ~ ${esc(fmt(s.unit, s.decimals, c.hi1y))}`);
  }
  // pct5y 는 '현재값보다 낮은 관측치의 비율' 이다. 0 = 5년 최저, 100 = 5년 최고.
  parts.push(`${rankText(c)} (0 = 5년 최저, 100 = 5년 최고 · ${c.n5y}개 관측)`);
  return `<p class="ctx-line">${parts.join(' · ')}</p>`;
}

/** 다음 발표 안내 — 카드 쪽 팁은 마우스 전용이므로 여기서는 본문으로 적는다. */
function nextLine(s) {
  const st = s.staleness;
  if (st && st.alarm) {
    return `<p class="next-line warn">최신 기준시점이 <strong>${esc(st.latestRef)}</strong> 입니다 —
      발표 지연을 감안하고도 <strong>${st.behind}${esc(st.unit)}치</strong>가 밀려 있습니다.
      원본이 늦거나 수집 경로가 끊겼다는 뜻이므로, 지금 보이는 값은 최신이 아닙니다.</p>`;
  }
  if (s.upcoming && s.upcoming.releaseDate && !useEstimate(s)) {
    return `<p class="next-line">다음 발표 <strong>${esc(fmtDate(s.upcoming.releaseDate))}</strong>
      — 캘린더 확정 일정입니다.</p>`;
  }
  const e = s.estimatedNext;
  if (!e) {
    if (MARKET_DAILY.has(s.id)) {
      return `<p class="next-line">발표 일정이 있는 통계가 아니라 <strong>매 영업일 갱신</strong>되는
        시장 데이터입니다. 그래서 예측·서프라이즈도 없습니다.</p>`;
    }
    if (POLICY_MEETING.has(s.id)) {
      return `<p class="next-line">정기 발표가 아니라 <strong>정책 회의에서 결정</strong>됩니다.
        회의 일정은 아래 공식 링크에서 확인할 수 있습니다.</p>`;
    }
    return `<p class="next-line">다음 발표일을 <strong>적지 않습니다</strong> — 캘린더에 확정 일정이 없고,
      과거 발표 시점의 편차가 커서(구간 폭 3주 초과) 구간으로도 말할 수 없습니다.
      없는 규칙을 있는 것처럼 적는 것보다 낫습니다.</p>`;
  }
  const today = new Date().toISOString().slice(0, 10);
  if (e.to < today) {
    return `<p class="next-line warn">과거 ${e.sample}회 기준으로 <strong>${esc(e.from)} ~ ${esc(e.to)}</strong>
      에 나왔어야 하는데 아직 값이 없습니다. 발표가 늦어졌거나 수집이 밀렸을 수 있습니다.</p>`;
  }
  return `<p class="next-line">다음 발표 <strong>${esc(e.from)} ~ ${esc(e.to)}</strong> 예상
    — 캘린더에 확정 일정이 없어 과거 ${e.sample}회의 발표 시점에서 추정했습니다
    (그중 ${e.inBand}회가 이 구간). 날짜를 단정할 수 없어 구간으로 적습니다.</p>`;
}

/** 상세 패널 각주 — 전체 관측 수와 공식 일정 링크. */
function detailFoot(s) {
  const bits = [`전체 관측 ${s.observations.length}개`];
  if (s.scheduleUrl) {
    bits.push(`<a href="${esc(s.scheduleUrl)}" target="_blank" rel="noopener noreferrer"
                  >공식 발표 일정 ↗</a>`);
  }
  return `<p class="detail-foot">${bits.join(' · ')}</p>`;
}

/* ------------------------------------------------------------------ 비교 */

const COMPARE_MAX = 4;
const compareSel = [];            // 선택된 지표 id (선택 순서)
const compareSlot = new Map();    // id -> 색 슬롯. 선택을 바꿔도 유지된다.

// 색은 순위가 아니라 지표에 붙는다.
// 하나를 빼도 남은 지표의 색이 바뀌면 "색 = 그 지표" 라는 약속이 깨져
// 이전 화면과 비교할 수 없게 된다.
function slotFor(id) {
  if (compareSlot.has(id)) return compareSlot.get(id);
  const used = new Set(compareSlot.values());
  for (let i = 1; i <= COMPARE_MAX; i++) {
    if (!used.has(i)) { compareSlot.set(id, i); return i; }
  }
  return 1;
}
function releaseSlot(id) { compareSlot.delete(id); }

const dayNum = iso => Date.parse(iso.slice(0, 10) + 'T00:00:00Z') / 86400000;

/** 여러 계열을 한 좌표계에 그린다. 단위가 같을 때만 쓴다. */
function overlayChart(list, byId) {
  const { W, H, L, R, T, B } = chartBox();
  const all = list.flatMap(s => s.observations);
  if (all.length < 2) return '<p class="c-empty">그릴 데이터가 부족합니다.</p>';

  const x0 = Math.min(...all.map(p => dayNum(p.d)));
  const x1 = Math.max(...all.map(p => dayNum(p.d)));
  let lo = Math.min(...all.map(p => p.v));
  let hi = Math.max(...all.map(p => p.v));
  const pad = (hi - lo) * 0.08 || Math.abs(hi || 1) * 0.08;
  lo -= pad; hi += pad;

  const X = iso => L + ((dayNum(iso) - x0) / (x1 - x0 || 1)) * (W - L - R);
  const Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  const unit = list[0].unit, dec = Math.max(...list.map(s => s.decimals));
  const ticks = [];
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * (i / 4);
    ticks.push(`<line x1="${L}" x2="${W - R}" y1="${Y(v).toFixed(1)}" y2="${Y(v).toFixed(1)}"
                  stroke="var(--gridline)" stroke-width="1"/>
                <text x="${L - 8}" y="${(Y(v) + 3.5).toFixed(1)}" text-anchor="end"
                  font-size="10.5" fill="var(--text-muted)">${esc(fmt(unit, dec, v))}</text>`);
  }
  const zero = (lo < 0 && hi > 0)
    ? `<line x1="${L}" x2="${W - R}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}"
         stroke="var(--baseline)" stroke-width="1" stroke-dasharray="3 3"/>` : '';

  const lines = list.map(s => {
    const pts = s.observations;
    if (pts.length < 2) return '';
    const d = pts.map((p, i) => (i ? 'L' : 'M') + X(p.d).toFixed(2) + ' ' + Y(p.v).toFixed(2)).join(' ');
    const last = pts[pts.length - 1];
    const c = `var(--series-${slotFor(s.id)})`;
    // 마지막 점에 직접 라벨 — 범례와 선을 눈으로 잇는 수고를 없앤다.
    return `<path d="${d}" fill="none" stroke="${c}" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round"/>
            <circle cx="${X(last.d).toFixed(2)}" cy="${Y(last.v).toFixed(2)}" r="3.5"
              fill="${c}" stroke="var(--surface)" stroke-width="2"/>`;
  }).join('');

  const xi = [x0, (x0 + x1) / 2, x1];
  const xlab = xi.map((d, i) => {
    const iso = new Date(d * 86400000).toISOString().slice(0, 10);
    const px = L + ((d - x0) / (x1 - x0 || 1)) * (W - L - R);
    return `<text x="${px.toFixed(1)}" y="${H - 8}" font-size="10.5" fill="var(--text-muted)"
              text-anchor="${i === 0 ? 'start' : i === 2 ? 'end' : 'middle'}">${iso.slice(0, 7)}</text>`;
  }).join('');

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
            aria-label="${esc(list.map(s => s.name).join(', '))} 비교">
    ${ticks.join('')}${zero}${lines}${xlab}
  </svg>`;
}

/** 단위가 섞이면 작은 차트를 나란히. 축이 각자 하나씩이라 이중 축이 생기지 않는다. */
function smallMultiples(list) {
  const all = list.flatMap(s => s.observations);
  const x0 = Math.min(...all.map(p => dayNum(p.d)));
  const x1 = Math.max(...all.map(p => dayNum(p.d)));
  const SW = 820, SL = 62, SR = 10;

  const panels = list.map(s => {
    const W = SW, H = 92, L = SL, R = SR, T = 8, B = 16;
    const pts = s.observations;
    if (pts.length < 2) return '';
    let lo = Math.min(...pts.map(p => p.v)), hi = Math.max(...pts.map(p => p.v));
    const pad = (hi - lo) * 0.1 || Math.abs(hi || 1) * 0.1;
    lo -= pad; hi += pad;
    const X = iso => L + ((dayNum(iso) - x0) / (x1 - x0 || 1)) * (W - L - R);
    const Y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
    const d = pts.map((p, i) => (i ? 'L' : 'M') + X(p.d).toFixed(2) + ' ' + Y(p.v).toFixed(2)).join(' ');
    const c = `var(--series-${slotFor(s.id)})`;
    const last = pts[pts.length - 1];
    return `<div class="sm-row">
      <div class="sm-head"><span class="sm-dot" style="background:${c}"></span>
        <span class="sm-name">${esc(s.name)}</span>
        <span class="sm-last">${esc(fmt(s.unit, s.decimals, last.v))}</span></div>
      <svg class="sm-chart" viewBox="0 0 ${W} ${H}" role="img"
           aria-label="${esc(s.name)} 추이">
        <line x1="${L}" x2="${W - R}" y1="${Y(hi).toFixed(1)}" y2="${Y(hi).toFixed(1)}"
              stroke="var(--gridline)" stroke-width="1"/>
        <line x1="${L}" x2="${W - R}" y1="${Y(lo).toFixed(1)}" y2="${Y(lo).toFixed(1)}"
              stroke="var(--gridline)" stroke-width="1"/>
        <text x="${L - 8}" y="${(Y(hi) + 4).toFixed(1)}" text-anchor="end" font-size="10"
              fill="var(--text-muted)">${esc(fmt(s.unit, s.decimals, hi))}</text>
        <text x="${L - 8}" y="${(Y(lo) + 4).toFixed(1)}" text-anchor="end" font-size="10"
              fill="var(--text-muted)">${esc(fmt(s.unit, s.decimals, lo))}</text>
        <path d="${d}" fill="none" stroke="${c}" stroke-width="1.8"
              stroke-linecap="round" stroke-linejoin="round"/>
      </svg>
    </div>`;
  }).join('');

  // x 도메인은 이미 패널 전체가 공유하는데(x0/x1), **그 사실이 화면에 안 보였다.**
  // 축 텍스트가 y 최소·최대 둘뿐이라, 이력이 짧은 계열(ISM 2024-09~)이
  // 오른쪽 끝에 몰려 그려지는 것이 렌더링 오류처럼 읽혔다.
  //
  // 축은 **맨 아래에 하나만** 그린다. 패널마다 반복하면 시끄럽고,
  // 하나면 '이 x 는 모든 패널에 같다' 가 그림 자체로 말해진다.
  const AH = 18;
  const axis = [0, 0.5, 1].map((f, i, arr) => {
    const iso = new Date((x0 + (x1 - x0) * f) * 86400000).toISOString().slice(0, 7);
    const px = SL + f * (SW - SL - SR);
    return `<text x="${px.toFixed(1)}" y="12" font-size="10.5" fill="var(--text-muted)"
      text-anchor="${i === 0 ? 'start' : i === arr.length - 1 ? 'end' : 'middle'}">${esc(iso)}</text>`;
  }).join('');

  return panels + `<svg class="sm-axis" viewBox="0 0 ${SW} ${AH}" role="img"
      aria-label="가로축: ${esc(new Date(x0 * 86400000).toISOString().slice(0, 7))}부터
                  ${esc(new Date(x1 * 86400000).toISOString().slice(0, 7))}까지">
      <line x1="${SL}" x2="${SW - SR}" y1="1" y2="1" stroke="var(--gridline)" stroke-width="1"/>
      ${axis}
    </svg>
    <p class="sm-note">가로축은 모든 패널이 같습니다. 선이 없는 구간은 그 지표의 데이터가 없는 기간입니다.</p>`;
}

// 비교 보기는 언제나 전 구간(1990~)을 그렸다. 36년을 한 화면에 넣으면
// 최근 몇 년의 움직임이 선 굵기 안으로 사라진다. 상세 패널과 같은 기간 선택을 준다.
// 기본을 '전체' 로 두면 COVID 스파이크가 화면을 지배해 최근 몇 년의 움직임이
// 선 굵기 안으로 사라진다. 36년을 보고 싶은 사람은 버튼 하나만 더 누르면 된다.
let compareRange = '5y';

function renderCompare(data, byId) {
  const body = document.getElementById('c-body');
  const note = document.getElementById('c-note');

  const picker = data.categories.map(cat => {
    const items = data.series.filter(s => s.category === cat && s.observations.length > 1);
    if (!items.length) return '';
    return `<div class="c-group"><span class="c-cat">${esc(cat)}</span>${items.map(s => {
      const on = compareSel.includes(s.id);
      const full = compareSel.length >= COMPARE_MAX && !on;
      return `<label class="c-item${on ? ' on' : ''}${full ? ' full' : ''}">
        <input type="checkbox" data-id="${esc(s.id)}" ${on ? 'checked' : ''} ${full ? 'disabled' : ''}>
        ${on ? `<span class="c-dot" style="background:var(--series-${slotFor(s.id)})"></span>` : ''}
        ${esc(s.name)}</label>`;
    }).join('')}</div>`;
  }).join('');

  // 기간을 자른 사본을 넘긴다. 차트 함수들은 s.observations 만 보므로 손댈 곳이 없다.
  const list = compareSel.map(id => byId[id]).filter(Boolean).map(s =>
    ({ ...s, observations: sliceByRange(s.observations, compareRange) }));
  const rangeRow = `<div class="range-row">${
    ['1y', '3y', '5y', 'all'].map(k =>
      `<button class="ghost" data-crange="${k}" aria-pressed="${k === compareRange}">${
        k === 'all' ? '전체' : k.toUpperCase()}</button>`).join('')}</div>`;

  let chart, legend = '', explain = '';

  if (!list.length) {
    chart = '<p class="c-empty">지표를 골라 주세요. 최대 4개까지 비교합니다.</p>';
  } else {
    const units = new Set(list.map(s => s.unit));
    // ★ 이중 축을 만들지 않는다 ★
    //   스케일이 다른 두 계열을 한 축에 억지로 얹으면 없는 상관관계가 눈에 보인다.
    //   단위가 같을 때만 겹쳐 그리고, 섞이면 각자 축을 가진 작은 차트로 나눈다.
    if (units.size === 1) {
      chart = overlayChart(list, byId);
      explain = `단위가 같아(${esc(list[0].unit)}) 한 축에 겹쳐 그렸습니다.`;
    } else {
      chart = `<div class="sm-wrap">${smallMultiples(list)}</div>`;
      explain = '단위가 서로 달라 축을 각각 둔 작은 차트로 나눴습니다. '
              + '스케일이 다른 계열을 한 축에 얹으면 없는 상관관계가 보이기 때문입니다.';
    }
    if (list.length >= 2) {
      legend = `<div class="c-legend">${list.map(s =>
        `<span class="c-leg"><span class="c-dot" style="background:var(--series-${slotFor(s.id)})"></span>${esc(s.name)}</span>`
      ).join('')}</div>`;
    }
  }

  note.textContent = explain;
  body.innerHTML = `<div class="c-picker">${picker}</div>${rangeRow}${legend}${chart}`;

  // 선택이 바뀌면 주소도 따라가야 링크가 지금 보이는 것을 가리킨다.
  // pushState 가 아니라 replaceState 다 — 체크 한 번마다 히스토리가 쌓이면
  // 뒤로가기가 체크 되돌리기가 돼 버려서 '닫기' 로 쓸 수 없게 된다.
  const syncHash = () => {
    const h = '#compare=' + compareSel.join(',');
    if (location.hash !== h) history.replaceState(null, '', h);
  };

  body.querySelectorAll('.c-picker input').forEach(inp =>
    inp.addEventListener('change', () => {
      const id = inp.dataset.id;
      const i = compareSel.indexOf(id);
      if (i >= 0) { compareSel.splice(i, 1); releaseSlot(id); }
      else if (compareSel.length < COMPARE_MAX) { compareSel.push(id); slotFor(id); }
      syncHash();
      renderCompare(data, byId);
    }));

  body.querySelectorAll('[data-crange]').forEach(b =>
    b.addEventListener('click', () => {
      compareRange = b.dataset.crange;
      renderCompare(data, byId);
    }));
}

/* ---------------------------------------------------------------- 신선도 */

function freshness(data) {
  if (!data.sources.length) {
    return `<div class="freshness"><h2>수집 상태</h2>
      <div class="src-row"><span class="src-msg">아직 자동 수집을 실행하지 않았습니다.
      현재 데이터는 엑셀 백필분입니다.</span></div></div>`;
  }
  const now = Date.now();
  const graded = data.sources.map(s => {
    const when = s.finished_at || s.started_at;
    const ageH = when ? (now - Date.parse(when)) / 36e5 : Infinity;
    let cls = 'ok', label = '정상';
    if (s.status !== 'ok') { cls = 'fail'; label = '실패'; }
    else if (ageH > 48)    { cls = 'stale'; label = '오래됨'; }
    const ageTxt = Number.isFinite(ageH)
      ? (ageH < 1 ? '방금 전' : ageH < 48 ? Math.round(ageH) + '시간 전' : Math.round(ageH / 24) + '일 전')
      : '기록 없음';
    return { ...s, cls, label, ageTxt, ageH };
  });

  const rows = graded.map(s => `<div class="src-row">
      <span class="src-name">${esc(s.source)}</span>
      <span class="badge ${s.cls}">${esc(s.label)}</span>
      <span class="src-when">${esc(s.ageTxt)}</span>
      <span class="src-msg">${esc(s.message || '')}</span>
    </div>`).join('');

  // 소비자에게 필요한 것은 '지금 믿어도 되나' 하나다. 나머지는 접어 둔다.
  // title 이 아니라 <details> 인 이유는 터치에서도 열려야 하기 때문이다.
  //
  // 예전에는 여기서 수집기 로그 원문을 접어 감췄다 —
  //   `17/17 계열, 관측치 22808건, 개정 감지 0건 | PPI 지수: 계절조정 'SA' 확인됨 | …`
  // 소비자가 「계절조정 'SAAR' 확인됨」으로 할 수 있는 일이 없기 때문이었다.
  // 그건 **표시로 덮은 것이지 고친 게 아니었다.** fetch_log.csv 는 계속 오염됐고,
  // 정작 고장을 조사할 때 읽는 파일이 거기다.
  // 지금은 원본에서 갈랐다 — 통과 확인·커버리지 보고는 FetchResult.notes 로 가고
  // 콘솔에만 찍힌다(FetchResult 주석 참조). 그래서 아래 메시지는 이미 깨끗하다.
  // 이 접기는 이제 노이즈 감추기가 아니라 순수한 UI 판단으로 남긴 것이다.
  const bad = graded.filter(s => s.cls !== 'ok');
  const newest = Math.min(...graded.map(s => s.ageH));
  const headline = bad.length
    ? `<span class="badge fail">확인 필요</span> ${esc(bad.map(s => s.source).join(', '))} —
       해당 지표는 마지막 성공 값을 그대로 보여줍니다`
    : `<span class="badge ok">정상</span> ${graded.length}개 소스 모두 수집됨 ·
       ${esc(Number.isFinite(newest) ? (newest < 1 ? '방금 전' : Math.round(newest) + '시간 전') : '기록 없음')}`;

  return `<div class="freshness">
    <h2>수집 상태</h2>
    <p class="src-headline">${headline}</p>
    <details class="src-detail"${bad.length ? ' open' : ''}>
      <summary>소스별 자세히</summary>
      ${rows}
    </details>
  </div>`;
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

  const upcoming = upcomingSection(data);

  const sections = data.categories.map((cat, i) => {
    const list = data.series.filter(s => s.category === cat);
    if (!list.length) return '';
    // 스파크라인 규칙은 카드마다 22번 적을 것이 아니라 화면에 한 번 적으면 된다.
    const note = i === 0
      ? '<span class="cat-note">카드의 작은 그래프는 모두 최근 2년입니다</span>' : '';
    return `<section class="cat"${i === 0 ? ' id="cards"' : ''}>
      <h2>${esc(cat)}${note}</h2>
      <div class="grid">${list.map(card).join('')}</div>
    </section>`;
  }).join('');

  const byId = Object.fromEntries(data.series.map(s => [s.id, s]));
  app.innerHTML = banner + upcoming + timelineSection(data, byId) + sections + freshness(data);

  // 클릭은 주소만 바꾼다. 실제로 여는 것은 applyRoute() 한 곳이다.
  app.querySelectorAll('.card, .tl-row').forEach(btn =>
    btn.addEventListener('click', () => navigate(hashFor(btn.dataset.id))));

  document.getElementById('compare-open').addEventListener('click', () => {
    if (!compareSel.length) {
      // 처음 열면 빈 화면 대신 대표 지표 둘을 미리 골라 둔다.
      ['cpi_yoy', 'unemployment_rate'].forEach(id => {
        if (byId[id] && compareSel.length < COMPARE_MAX) { compareSel.push(id); slotFor(id); }
      });
    }
    navigate('#compare=' + compareSel.join(','));
  });

  ROUTE_DATA = { data, byId };
  applyRoute();   // #cpi_yoy 로 직접 들어온 사람에게 그 패널을 열어 준다
}

/* --------------------------------------------------------------- 주소 연결 */

// 지금까지 상세 패널을 열어도 URL 이 그대로였다. 결과적으로
//   - 특정 지표를 가리키는 링크를 남에게 보낼 수 없고
//   - 모바일에서 뒤로가기를 누르면 패널이 닫히는 게 아니라 **사이트를 떠난다**
// 해시 하나로 둘 다 해결된다. 서버 설정이 필요 없어 GitHub Pages 에서도 그대로 된다.
//
// 상태 전이는 오직 해시가 만든다. 열기는 pushState 로 해시를 바꾸고,
// 실제 표시는 popstate/hashchange 를 받는 applyRoute() 한 곳에서만 한다.
// 그래야 '뒤로가기로 닫기' 와 '닫기 버튼' 이 서로 다른 경로로 갈라지지 않는다.
let ROUTE_DATA = null;
// 우리가 직접 쌓은 히스토리 항목인가.
//
// 닫을 때 무조건 history.back() 하면 **딥링크로 바로 들어온 사람은 사이트를 떠난다** —
// 고치려던 바로 그 증상이다. 우리가 쌓은 항목일 때만 뒤로 가고,
// 아니면 주소에서 해시만 지운다.
let pushedByUs = false;

function hashFor(id) { return '#' + encodeURIComponent(id); }

function navigate(hash) {
  if (location.hash === hash) { applyRoute(); return; }
  // pushState 는 popstate 도 hashchange 도 발생시키지 않는다. 주소만 바뀌고
  // 화면은 그대로인 상태가 되므로, 여기서 직접 경로를 적용해야 한다.
  history.pushState(null, '', hash || location.pathname + location.search);
  pushedByUs = true;
  applyRoute();
}

function applyRoute() {
  if (!ROUTE_DATA) return;
  const detail = document.getElementById('detail');
  const compare = document.getElementById('compare');
  const raw = decodeURIComponent(location.hash.slice(1));

  if (raw.startsWith('compare=')) {
    const ids = raw.slice(8).split(',').filter(id => ROUTE_DATA.byId[id]);
    if (ids.length) {
      compareSel.length = 0;
      ids.slice(0, COMPARE_MAX).forEach(id => { compareSel.push(id); slotFor(id); });
      if (detail.open) detail.close();
      renderCompare(ROUTE_DATA.data, ROUTE_DATA.byId);
      if (!compare.open) compare.showModal();
      return;
    }
  }

  const s = ROUTE_DATA.byId[raw];
  if (s) {
    if (compare.open) compare.close();
    openDetail(s);
    return;
  }
  // 해시가 없거나 모르는 값이면 대시보드로. 없는 id 로 들어와도 조용히 넘어간다.
  if (detail.open) detail.close();
  if (compare.open) compare.close();
}

// 닫힐 때 주소를 되돌린다.
//
// dialog 의 `close` 이벤트 하나로 모으는 편이 깔끔해 보이지만 그렇게 하지 않았다.
// 검증 중에 이 환경에서 `close` 가 관측되지 않는 경우를 만났고, 확인할 수 없는 것 위에
// 주소 동기화를 얹을 수는 없다. 닫는 경로 셋(닫기 버튼·Esc·백드롭)을 모두
// 이 함수로 직접 모은다 — 경로가 늘면 여기에 붙이면 된다.
function closeDialogs() {
  const d = document.getElementById('detail');
  const c = document.getElementById('compare');
  if (d.open) d.close();
  if (c.open) c.close();
  if (!location.hash) return;
  if (pushedByUs) {
    pushedByUs = false;
    history.back();                 // 우리가 쌓은 항목 → 원래 보던 대시보드로
  } else {
    // 딥링크로 바로 들어온 경우. 뒤로 가면 사이트를 떠나므로 해시만 지운다.
    history.replaceState(null, '', location.pathname + location.search);
  }
}

/* ------------------------------------------------------------------- 시작 */

document.getElementById('d-close').addEventListener('click', closeDialogs);
document.getElementById('c-close').addEventListener('click', closeDialogs);

// 백드롭(패널 바깥 어두운 영역) 클릭. 이벤트 대상이 dialog 자신이면 바깥이다.
['detail', 'compare'].forEach(id => {
  const dlg = document.getElementById(id);
  dlg.addEventListener('click', e => { if (e.target === dlg) closeDialogs(); });
});

// Esc. 네이티브 동작이 dialog 를 닫아 버리므로 주소도 여기서 같이 맞춘다.
// keydown 은 기본 동작보다 먼저 오므로 열려 있는지 판정할 수 있다.
addEventListener('keydown', e => {
  if (e.key !== 'Escape') return;
  const open = document.getElementById('detail').open || document.getElementById('compare').open;
  if (open) closeDialogs();
}, true);

addEventListener('popstate', applyRoute);
addEventListener('hashchange', applyRoute);
wireTips(document.body);

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
