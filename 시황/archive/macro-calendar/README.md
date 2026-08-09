# 매크로 캘린더

한국·미국 매크로 경제 지표의 **발표 일정을 캘린더로** 보고, **발표 수치를 자동으로 받아**
텔레그램으로 알림까지 보내는 개인용 웹앱입니다. 폰 브라우저에서 바로 쓰거나 홈화면에
추가해 앱처럼 쓸 수 있습니다.

## 구성

| | |
|---|---|
| 런타임 | Cloudflare Workers (무료 플랜) |
| DB | Cloudflare D1 |
| 프레임워크 | Hono. 프론트는 빌드 없는 순수 ES 모듈 |
| 알림 | 텔레그램 봇 |
| 데이터 | FRED (미국), 한국은행 ECOS (한국) |

## 수록 지표

### 미국 — FRED

| 지표 | 시리즈 | 대표값 | 발표 일정 |
|---|---|---|---|
| CPI | `CPILFESL` `CPIAUCSL` | 근원 YoY | FRED 공식 공표일정 |
| PPI | `PPIFIS` | 최종수요 YoY | 〃 |
| PCE | `PCEPILFE` `PCEPI` | 근원 YoY | 〃 |
| 비농업 고용 | `PAYEMS` | 전월비 증감 | 〃 |
| 실업률 | `UNRATE` | 레벨 | 〃 |
| 시간당 임금 | `CES0500000003` | YoY | 〃 |
| 신규 실업수당 | `ICSA` | 주간 청구건수 | 〃 (매주 목) |
| JOLTS 구인 | `JTSJOL` | 구인건수 | 〃 |
| FOMC 기준금리 | `DFEDTARU` | 상단금리 | 확정 일정 하드코딩 |
| 10Y-2Y | `T10Y2Y` `DGS10` `DGS2` | 스프레드 | 매 영업일 |
| ISM 제조업/서비스 PMI | — | PMI | 매월 1·3영업일 (수치는 수동) |

미국 발표 일정은 **하드코딩하지 않습니다.** FRED 의 `/release/dates` API 가 BLS·BEA 의
확정 공표일정을 그대로 갖고 있어서 그대로 씁니다. 매일 새벽 갱신되므로 일정이 바뀌어도
따라갑니다.

### 한국 — 한국은행 ECOS

| 지표 | 통계표 / 항목 | 대표값 | 발표 일정 |
|---|---|---|---|
| CPI | `901Y009` / `0` | 총지수 YoY | 익월 2일경 08:00 |
| PPI | `404Y014` / `*AA` | 총지수 YoY | 익월 22일경 12:00 |
| 실업률 | `901Y027` / `I61BC` | 레벨 | 익월 15일경 08:00 |
| 취업자수 | `901Y027` / `I61BA` | 전년동월비 증감 | 〃 |
| 기준금리 | `722Y001` / `0101000` | 레벨 | 금통위 확정 일정 |
| 10Y-2Y | `817Y002` / `010210000`·`010195000` | 스프레드 | 매 영업일 |

한국은 미국의 FRED 같은 통합 공표일정 API 가 없어서, 통계청·한은의 관행적 발표일을
규칙(`day_of_month`)으로 계산합니다. **±1~2일 오차가 날 수 있습니다.** 금통위만
확정 일정을 그대로 넣었습니다.

## 알아둘 한계

- **ISM PMI 는 수치가 자동으로 안 들어옵니다.** ISM 이 저작권을 이유로 데이터 배포를
  막아둬서 FRED 를 포함한 어떤 무료 API 에도 없습니다. 발표 **일정은** 정확히 계산해
  캘린더에 띄우고 알림도 가되, 숫자는 아래 수동 입력으로 채워야 합니다. 한국 PMI
  (S&P Global) 도 같은 이유로 빠져 있습니다.
- **예상치(컨센서스)가 없습니다.** 무료로 받을 수 있는 소스가 없습니다. 대신 실제값과
  **직전값**을 나란히 보여줍니다.
- **PCE·JOLTS·신규 실업수당은 미국 전용**입니다. 한국에 대응 통계가 없거나 API 가
  없어서 한국 쪽은 비어 있습니다. NFP 에 대응하는 건 `취업자수 증감`입니다.
- 주말 회피만 하고 **공휴일은 반영하지 않습니다.** 공휴일과 겹치면 하루 어긋날 수 있습니다.

## 로컬 실행

```bash
npm install
npm run db:local
npm run dev
```

`dev.cmd` 를 더블클릭해도 됩니다 (Node 경로를 직접 잡아주는 래퍼).

띄운 뒤 초기 데이터를 채웁니다. `ADMIN_TOKEN` 은 `.dev.vars` 값입니다.

```bash
curl -X POST -H "x-admin-token: $TOKEN" http://127.0.0.1:8788/api/admin/sync
```

```bash
curl -X POST -H "x-admin-token: $TOKEN" http://127.0.0.1:8788/api/admin/calendar
```

```bash
curl -X POST -H "x-admin-token: $TOKEN" http://127.0.0.1:8788/api/admin/backfill
```

## 배포

### 1. D1 생성

```bash
npx wrangler d1 create macro-db
```

출력된 `database_id` 를 `wrangler.jsonc` 의 `PLACEHOLDER_RUN_D1_CREATE` 자리에 넣고:

```bash
npm run db:remote
```

### 2. 시크릿 등록

`.dev.vars` 는 로컬 전용입니다. 배포본에는 따로 넣어야 합니다.

```bash
npx wrangler secret put FRED_API_KEY
```

`ECOS_API_KEY`, `TELEGRAM_BOT_TOKEN`, `ADMIN_TOKEN` 도 같은 방식으로 넣습니다.

### 3. 배포

```bash
npm run deploy
```

### 4. 초기 데이터

배포된 URL 에 대고 로컬에서 했던 `sync` → `calendar` → `backfill` 을 한 번씩 호출합니다.

### 5. 텔레그램 웹훅 연결

`<TOKEN>` 은 봇 토큰, `<ADMIN>` 은 `ADMIN_TOKEN`, `<HOST>` 는 배포된 워커 도메인입니다.

```bash
curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<HOST>/api/telegram/webhook/<ADMIN>"
```

그 다음 봇에게 `/start` 를 보내면 알림 수신자로 등록됩니다.

## 봇 명령

| 명령 | 동작 |
|---|---|
| `/start` | 알림 켜기 (수신자 등록) |
| `/stop` | 알림 끄기 |
| `/today` | 오늘 일정 |
| `/next` | 다음 발표 5건 |
| `/major` | ★★★ 만 받기 |
| `/all` | 전체 받기 |

## 크론

무료 플랜은 워커당 3개까지 쓸 수 있어서 딱 3개를 씁니다. 시각은 UTC 입니다.

| 크론 | KST | 하는 일 |
|---|---|---|
| `*/5 * * * *` | 5분마다 | 발표 30분 전 알림 + 발표 결과 감지·알림 |
| `10 20 * * *` | 05:10 | 전체 지표 동기화, 캘린더 갱신, 과거 발표 보정 |
| `0 22 * * *` | 07:00 | 오늘의 일정 요약 발송 |

## ISM PMI 수동 입력

발표 후 ISM 사이트에서 숫자를 확인해 넣습니다.

```bash
curl -X POST -H "x-admin-token: $TOKEN" -H "content-type: application/json" -d '{"indicator_id":"us_ism_mfg","series_key":"level","period":"2026-07","value":48.7}' https://<HOST>/api/admin/manual
```

`us_ism_svc` 도 동일합니다. `period` 는 발표 월이 아니라 **기준 월**입니다.

## 발표 기간을 어떻게 정하는가

이 앱에서 가장 까다로웠던 부분입니다.

발표일에서 기준 기간을 역산하는 방식(“9월 발표 = 8월분”)은 JOLTS 에서 깨집니다.
JOLTS 는 발표 간격이 드리프트해서 2026-09-01 발표는 7월분, 2026-09-29 발표는 8월분입니다.
같은 달에 두 번 발표되면서 시차가 달라집니다.

그래서 **데이터에서 거꾸로 확정**합니다. 지난 발표들을 시간순으로 늘어놓고, 실제 관측치
기간도 시간순으로 늘어놓은 뒤 **가장 최근 것부터 1:1 로 짝지어 올라갑니다**
(`notify.js` 의 `backfillPast`). 지표마다, 시기마다 시차가 달라도 규칙 없이 흡수됩니다.

실시간 감지(`resolveActual`)도 같은 원리입니다. “이미 확정된 마지막 발표보다 새로운
기간이 올라왔는가”만 봅니다.

## 파일 구조

```
src/
  index.js       워커 진입점 — 라우팅 + 크론
  indicators.js  지표 레지스트리 (여기만 고치면 전부 반영됨)
  fred.js        FRED 클라이언트 (수치 + 공표일정)
  ecos.js        한국은행 ECOS 클라이언트
  transform.js   지수 → YoY/MoM/증감 변환
  sync.js        수집 → 변환 → 저장
  calendar.js    발표 일정 생성
  notify.js      발표 감지, 알림, 과거 보정
  telegram.js    메시지 발송 및 포맷
  bot.js         봇 명령 처리
public/          대시보드 UI (빌드 없음)
schema.sql       D1 스키마
```

지표를 추가하려면 `src/indicators.js` 에 항목 하나만 넣으면 캘린더·대시보드·알림에
전부 반영됩니다.
