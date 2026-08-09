// 배포 자동화.
//
//   1) Cloudflare 로그인 확인 (안 돼 있으면 브라우저를 띄웁니다)
//   2) D1 데이터베이스 생성 + wrangler.jsonc 에 id 기록
//   3) 원격 DB 에 스키마 적용
//   4) .dev.vars 의 키들을 Cloudflare 시크릿으로 등록
//   5) 배포
//   6) 텔레그램 웹훅 연결
//   7) 초기 데이터 채우기
//
// 몇 번을 다시 돌려도 안전합니다 — 이미 된 단계는 건너뜁니다.

import { spawn } from 'node:child_process';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const CONFIG = join(root, 'wrangler.jsonc');
const DB_NAME = 'macro-db';
const SECRETS = ['FRED_API_KEY', 'ECOS_API_KEY', 'TELEGRAM_BOT_TOKEN', 'ADMIN_TOKEN'];

const c = {
  ok: (s) => `\x1b[32m${s}\x1b[0m`,
  warn: (s) => `\x1b[33m${s}\x1b[0m`,
  err: (s) => `\x1b[31m${s}\x1b[0m`,
  dim: (s) => `\x1b[90m${s}\x1b[0m`,
};

let step = 0;
const heading = (t) => console.log(`\n${c.dim(`[${++step}/7]`)} ${t}`);

/** wrangler 실행. interactive 면 로그인 프롬프트/브라우저가 뜰 수 있게 화면을 그대로 넘깁니다. */
function wrangler(args, { interactive = false, input } = {}) {
  return new Promise((resolve) => {
    const child = spawn(
      process.execPath,
      [join(root, 'node_modules', 'wrangler', 'bin', 'wrangler.js'), ...args],
      { cwd: root, stdio: interactive ? 'inherit' : ['pipe', 'pipe', 'pipe'] }
    );

    let out = '', errOut = '';
    if (!interactive) {
      child.stdout.on('data', (d) => { out += d; });
      child.stderr.on('data', (d) => { errOut += d; });
      if (input !== undefined) {
        child.stdin.write(input);
        child.stdin.end();
      }
    }

    child.on('close', (code) => resolve({ code, out, err: errOut }));
  });
}

function readDevVars() {
  const vars = {};
  try {
    for (const line of readFileSync(join(root, '.dev.vars'), 'utf8').split(/\r?\n/)) {
      const t = line.trim();
      if (!t || t.startsWith('#')) continue;
      const i = t.indexOf('=');
      if (i > 0) vars[t.slice(0, i).trim()] = t.slice(i + 1).trim();
    }
  } catch {
    console.error(c.err('.dev.vars 를 읽을 수 없습니다.'));
    process.exit(1);
  }
  return vars;
}

const vars = readDevVars();

// ── 1. 로그인 ────────────────────────────────────────────────
heading('Cloudflare 로그인 확인');

let who = await wrangler(['whoami']);
if (who.code !== 0 || /not authenticated|You are not/i.test(who.out + who.err)) {
  console.log(c.warn('  로그인이 필요합니다. 브라우저가 열리면 [Allow] 를 눌러주세요.'));
  const login = await wrangler(['login'], { interactive: true });
  if (login.code !== 0) {
    console.error(c.err('  로그인 실패. 다시 실행해 주세요.'));
    process.exit(1);
  }
  who = await wrangler(['whoami']);
}
const account = (who.out.match(/[\w.+-]+@[\w-]+\.[\w.]+/) || [])[0];
console.log(c.ok(`  로그인됨${account ? ` (${account})` : ''}`));

// ── 2. D1 생성 ───────────────────────────────────────────────
heading('D1 데이터베이스 준비');

let configText = readFileSync(CONFIG, 'utf8');

async function findDb() {
  const r = await wrangler(['d1', 'list', '--json']);
  try {
    const list = JSON.parse(r.out.slice(r.out.indexOf('[')));
    return list.find((d) => d.name === DB_NAME);
  } catch {
    return null;
  }
}

let db = await findDb();
if (!db) {
  console.log(c.dim(`  ${DB_NAME} 생성 중…`));
  const created = await wrangler(['d1', 'create', DB_NAME]);
  if (created.code !== 0) {
    console.error(c.err(`  생성 실패:\n${created.err || created.out}`));
    process.exit(1);
  }
  db = await findDb();
}

if (!db?.uuid) {
  console.error(c.err('  데이터베이스 id 를 확인하지 못했습니다.'));
  process.exit(1);
}

if (configText.includes('PLACEHOLDER_RUN_D1_CREATE')) {
  configText = configText.replace('PLACEHOLDER_RUN_D1_CREATE', db.uuid);
  writeFileSync(CONFIG, configText);
  console.log(c.ok(`  생성 완료, wrangler.jsonc 에 id 기록 (${db.uuid.slice(0, 8)}…)`));
} else {
  console.log(c.ok(`  이미 준비됨 (${db.uuid.slice(0, 8)}…)`));
}

// ── 3. 스키마 ────────────────────────────────────────────────
heading('원격 DB 스키마 적용');

const schema = await wrangler(['d1', 'execute', DB_NAME, '--remote', '--file=./schema.sql', '-y']);
if (schema.code !== 0) {
  console.error(c.err(`  실패:\n${schema.err || schema.out}`));
  process.exit(1);
}
console.log(c.ok('  적용 완료'));

// ── 4. 시크릿 ────────────────────────────────────────────────
heading('API 키 등록');

for (const name of SECRETS) {
  const value = vars[name];
  if (!value) {
    console.log(c.warn(`  ${name} 건너뜀 (.dev.vars 에 값이 없습니다)`));
    continue;
  }
  const r = await wrangler(['secret', 'put', name], { input: value + '\n' });
  console.log(r.code === 0 ? c.ok(`  ${name}`) : c.err(`  ${name} 실패`));
}

// ── 5. 배포 ──────────────────────────────────────────────────
heading('배포');

const dep = await wrangler(['deploy']);
if (dep.code !== 0) {
  console.error(c.err(`  실패:\n${dep.err || dep.out}`));
  process.exit(1);
}

const url = (`${dep.out}${dep.err}`.match(/https:\/\/[a-z0-9.-]*workers\.dev/i) || [])[0];
if (!url) {
  console.error(c.err('  배포는 됐는데 주소를 찾지 못했습니다. 아래 출력을 확인하세요:'));
  console.log(dep.out + dep.err);
  process.exit(1);
}
console.log(c.ok(`  ${url}`));

// ── 6. 텔레그램 웹훅 ─────────────────────────────────────────
heading('텔레그램 웹훅 연결');

if (vars.TELEGRAM_BOT_TOKEN && vars.ADMIN_TOKEN) {
  const hook = `${url}/api/telegram/webhook/${vars.ADMIN_TOKEN}`;
  const res = await fetch(
    `https://api.telegram.org/bot${vars.TELEGRAM_BOT_TOKEN}/setWebhook`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ url: hook, allowed_updates: ['message'] }),
    }
  ).then((r) => r.json()).catch((e) => ({ ok: false, description: e.message }));

  console.log(res.ok ? c.ok('  연결 완료') : c.err(`  실패: ${res.description}`));
} else {
  console.log(c.warn('  건너뜀 (봇 토큰이 없습니다)'));
}

// ── 7. 초기 데이터 ───────────────────────────────────────────
heading('초기 데이터 채우기 (1~3분)');

for (const [label, path] of [
  ['지표 수치', 'sync'],
  ['발표 일정', 'calendar'],
  ['지난 발표 보정', 'backfill'],
]) {
  process.stdout.write(c.dim(`  ${label} … `));
  try {
    const r = await fetch(`${url}/api/admin/${path}`, {
      method: 'POST',
      headers: { 'x-admin-token': vars.ADMIN_TOKEN },
    });
    const body = await r.json();
    console.log(r.ok ? c.ok(JSON.stringify(body)) : c.err(`실패 ${r.status}`));
  } catch (err) {
    console.log(c.err(err.message));
  }
}

// ── 완료 ────────────────────────────────────────────────────
console.log(`
${c.ok('배포 완료')}

  주소   ${url}
  폰에서 이 주소를 열고 [공유] → [홈 화면에 추가] 하면 앱처럼 쓸 수 있습니다.

  알림   텔레그램에서 봇에게 /start 를 보내면 등록됩니다.

  이제 PC 를 꺼도 동작하고, 발표 30분 전과 발표 직후에 알림이 옵니다.
`);
