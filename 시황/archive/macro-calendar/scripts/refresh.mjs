// 데이터 갱신 스크립트.
//   1) sync     — 지표 수치 수집
//   2) calendar — 발표 일정 생성
//   3) backfill — 지난 발표에 실제 수치 채우기
//
// 사용: node scripts/refresh.mjs [base_url]
// 기본 대상은 로컬 개발 서버입니다.

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const base = (process.argv[2] || 'http://127.0.0.1:8788').replace(/\/$/, '');

function readToken() {
  try {
    const text = readFileSync(join(root, '.dev.vars'), 'utf8');
    const line = text.split(/\r?\n/).find((l) => l.startsWith('ADMIN_TOKEN='));
    return line?.slice('ADMIN_TOKEN='.length).trim();
  } catch {
    return null;
  }
}

const token = process.env.ADMIN_TOKEN || readToken();
if (!token) {
  console.error('ADMIN_TOKEN 을 찾을 수 없습니다 (.dev.vars 확인)');
  process.exit(1);
}

const steps = [
  ['지표 수치 수집', 'sync'],
  ['발표 일정 생성', 'calendar'],
  ['지난 발표 보정', 'backfill'],
];

console.log(`대상: ${base}\n`);

for (const [label, path] of steps) {
  process.stdout.write(`  ${label} … `);
  try {
    const res = await fetch(`${base}/api/admin/${path}`, {
      method: 'POST',
      headers: { 'x-admin-token': token },
    });
    const body = await res.json();

    if (!res.ok) {
      console.log(`실패 (${res.status}) ${JSON.stringify(body)}`);
      continue;
    }
    if (body.failed?.length) {
      console.log(`일부 실패: ${body.failed.map((f) => f.id).join(', ')}`);
    } else {
      console.log(JSON.stringify(body));
    }
  } catch (err) {
    console.log(`연결 실패 — 서버가 켜져 있나요? (${err.message})`);
    process.exit(1);
  }
}

const health = await fetch(`${base}/api/health`).then((r) => r.json()).catch(() => null);
if (health) {
  console.log(`\n완료. 발표 일정 ${health.releases}건, 관측치 ${health.observations}건`);
}
