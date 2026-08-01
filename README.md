# 매크로 지표 자동 수집 대시보드

`매크로 머티리얼.xlsm` 을 손으로 채우던 작업을 자동화한다.
미국·한국 거시지표 17종을 매일 수집해 정적 대시보드로 보여준다.

---

## 빠른 시작

```bash
# 1. API 키 발급 (무료)
#    FRED : https://fredaccount.stlouisfed.org/apikeys   (즉시)
#    ECOS : https://ecos.bok.or.kr/api/                  (승인까지 최대 1일)
set FRED_API_KEY=발급받은키
set ECOS_API_KEY=발급받은키

# 2. 엑셀 과거 데이터 백필 (최초 1회)
python scripts/import_excel.py "C:\Users\greyx\Desktop\매크로 머티리얼.xlsm"

# 3. 매핑이 맞는지 검증
python scripts/verify.py

# 4. 수집 + 화면용 JSON 생성
python scripts/collect.py
python scripts/export_json.py

# 5. 확인
python -m http.server 8000 -d site     # http://localhost:8000
```

필수 외부 패키지는 **없다**. CDS 5년물만 선택적으로 `playwright` 가 필요하다.

---

## 데이터 출처

엑셀에 적혀 있던 investing.com 링크 15개는 전부 폐기했다.
공개 API 가 없고, Cloudflare 봇 차단이 걸려 있으며, 이용약관이 자동 수집을 금지한다.
그 위에 만들면 반드시 깨진다.

| 구분 | 지표 | 출처 | 상태 |
|---|---|---|---|
| 물가 | CPI 지수 / CPI YoY / PPI 지수 / PCE YoY / 근원 PCE YoY | FRED | 완전 자동 |
| 고용 | NFP / 실업률 / 시간당 임금 / 신규 실업수당 / JOLTS | FRED | 완전 자동 |
| 서베이 | ISM 제조업·서비스업 PMI | ForexFactory 캘린더 | 자동 (FRED 에 없음) |
| 금융 | 미 기준금리 / 10Y-2Y | FRED | 완전 자동 |
| 금융 | 한국 기준금리 | 한국은행 ECOS | 완전 자동 |
| 금융 | 미·한 CDS 5년물 | worldgovernmentbonds (headless) | 취약 — 아래 참조 |
| 전 지표 | **예측(컨센서스)** | ForexFactory 캘린더 | 자동, 단 과거 백필 불가 |

### 컨센서스에 대해 반드시 알아야 할 것

`https://nfs.faireconomy.media/ff_calendar_thisweek.json` 는 **이번 주만** 준다.
`lastweek` / `nextweek` 는 404다. 즉:

- **한 주를 놓치면 그 주의 예측값은 영원히 복구할 수 없다.**
- 과거 예측은 엑셀 백필이 유일한 출처다.
- 그래서 워크플로가 하루 두 번 돌고, 매핑 성공 여부와 무관하게
  원본 이벤트를 `calendar_events` 테이블에 **전량 먼저** 저장한다.
  나중에 매핑이 틀렸다고 밝혀져도 `calendar_ff.remap_from_stored()` 로 복구할 수 있다.

무료 컨센서스가 없는 지표: CPI 지수·PPI 지수(지수 레벨 예측은 제공 안 함),
PCE YoY(m/m 만 제공), 10Y-2Y·CDS(원래 예측이 없는 지표), 한국 기준금리(피드에 KRW 없음).
엑셀도 이 중 상당수는 예측이 비어 있었다.

### CDS 가 취약한 이유

worldgovernmentbonds 페이지는 값이 전부 `data-async-variable=…>----</span>` 플레이스홀더인
클라이언트 렌더링이고, 내부 `wp-json/common/v1/historical` 은 nonce 없이 403 이다.
따라서 Playwright 로 실제 렌더링해야 한다.

수집기는 페이지가 내부적으로 부르는 historical 응답을 가로채 **전체 이력**을 얻는다
(한국 2007년~ 5,061건, 미국 2017년~ 3,254건). 가로채기가 실패하면 렌더링된 DOM 에서
최신값 1건만 읽는 2순위 경로로 내려간다. 둘 다 실패해도 나머지 16종 수집은 정상 완료되고
대시보드 신선도 패널에 실패가 표시된다. 값이 조용히 덮어써지는 일은 없다.

참고: 엑셀(investing.com)과 worldgovernmentbonds 는 같은 CDS 를 하루씩 다른 날짜에
붙이는 경향이 있다. worldgovernmentbonds 가 훨씬 깊은 이력을 주므로 겹치는 구간은
그쪽으로 통일된다. 이 교체는 `revisions` 에 기록되지 않는다(위 약속 4).

---

## 구조

```
core/
  series.py     ★ 17개 지표 단일 정의 — 소스·단위·스케일·파생식·발표지연
  schema.sql      observations / releases / revisions / calendar_events / fetch_log
  db.py           업서트, 개정 이력 기록, 이벤트 발표일 병합
  store.py      ★ CSV ↔ SQLite. 커밋되는 영속 형식은 CSV 다 (아래 참조)
  transform.py    YoY · MoM · 전월차분 (달력 기준, 위치 기준 아님)
  validate.py     단위·범위·중복 검사
  xlsx.py         표준 라이브러리만으로 xlsx 읽기
fetchers/
  base.py         재시도, 실패 격리, 단위 파싱
  fred.py         12종 + 최초발표값(vintage)
  calendar_ff.py  예측 + ISM, 원본 전량 보관, 매핑 오타 탐지
  ecos.py         한국 기준금리
  cds.py          Playwright, best-effort
scripts/
  import_excel.py 엑셀 백필 + 오류 정정 리포트
  collect.py      일일 수집 진입점
  verify.py       엑셀 ↔ FRED 대조
  export_json.py  site/data/dashboard.json 생성
site/             빌드 체인 없는 정적 대시보드
data/*.csv        ★ 커밋 대상 — 영속 저장 형식
data/macro.sqlite   작업용. CSV 에서 재생성되는 파생물이라 커밋하지 않는다
```

### 왜 SQLite 가 아니라 CSV 를 커밋하는가

처음에는 `macro.sqlite` 를 커밋하려 했다. 그런데 CDS 전체 이력(8,300건)을 받고 나니
파일이 3.3 MB 가 됐고, **git 은 바이너리를 델타 압축하지 못해 커밋마다 전체 복사본을 저장한다.**
하루 두 번 × 1년이면 수백 MB 가 쌓인다.

CSV(합계 1.4 MB)로 저장하면 하루치 변경이 몇 줄 diff 로 남고, 무엇보다

```bash
git log -p data/observations.csv     # 사람이 읽는 수정치 감사 로그
```

가 성립한다. '개정 추적'이라는 원래 목표가 여기서 실제로 완성된다.
DB 가 비어 있으면 `db.connect()` 가 CSV 에서 자동 복원하므로, 저장소를 새로 클론하거나
Actions 러너처럼 매번 빈 상태로 시작해도 그대로 이어서 돌아간다.

### 설계상의 네 가지 약속

1. **결측은 `NULL`, 0 이 아니다.** 미발표와 "0%"를 절대 섞지 않는다.
2. **조용한 실패 금지.** 수집이 실패하면 직전 값을 유지하고 화면에 stale 배지를 띄운다.
3. **한 소스의 실패가 다른 소스를 막지 않는다.** 부분 실패 시 종료 코드는 0이다.
4. **개정과 출처 교체를 구분한다.** `revisions` 에는 *같은 소스가* 같은 기준시점의 값을
   바꾼 것만 남는다. 소스를 갈아탄 것(엑셀 CDS → worldgovernmentbonds)은 개정이 아니다 —
   구분하지 않으면 감사 로그가 출처 차이로만 가득 차 쓸모가 없어진다.

---

## 엑셀보다 나아진 점

- **개정(revision) 추적** — 같은 기준월의 값이 바뀌면 `revisions` 에 기록된다.
  NFP 처럼 두 번 개정되는 지표의 수정 폭이 보인다. 엑셀은 덮어쓰면 끝이었다.
- **발표일과 기준월의 분리** — 엑셀은 둘이 섞여 아래 오류가 생겼다.
- **이벤트 발표일 병합** — 같은 FOMC 를 엑셀은 한국 날짜(07-30),
  캘린더는 미국 현지(07-29 14:00 ET)로 준다. 더 이른 날짜로 자동 병합한다.

### 대조 검증 결과 (2026-08-01, FRED 전량 수집 후)

```bash
python scripts/verify.py --offline     # API 키 없이 커밋된 데이터로 검증
```

FRED 계열 12종 중 **11종의 매핑이 확인**되었다.

| 판정 | 지표 | 의미 |
|---|---|---|
| 정확 일치 100% | CPI 지수, CPI YoY, 미국 기준금리 | 완전 일치 |
| 개정 차이 | PPI, PCE, 근원 PCE, NFP, 실업률, 시간당 임금, 신규 실업수당, JOLTS | 매핑 정상 |
| **조사 필요** | 10Y-2Y 금리차 | 아래 참조 |

**'개정 차이'는 정상이다.** 엑셀에는 *발표 당시* 값이, FRED 에는 *개정된 현재* 값이 들어 있다.
NFP 는 두 번 개정되므로 정확 일치율이 2% 인 게 오히려 맞다 — 차이의 중앙값이 67천명으로
통상 개정 폭(`revision_band=200`) 안에 있으므로 매핑은 옳다.
`verify.py` 는 정확 일치율만 보지 않고 이 폭과 비교해 판정한다.

**10Y-2Y 만 개정으로 설명되지 않는다.** 시장금리는 개정되지 않기 때문이다(`revision_band=0`).
원인을 추적한 결과 **엑셀 쪽 날짜가 어긋나 있다**:
엑셀에는 2026-07-03, 2026-06-19 에 값이 있는데 이 날들은 미국 휴장일이라 FRED 에 호가 자체가 없다.
엑셀의 값들은 FRED 에 존재하지만 라벨과 다른 날짜에 붙어 있다. 겹치는 구간은 FRED 가 맞다.

### 임포트가 실제로 잡아낸 원본 오류

| 위치 | 문제 | 처리 |
|---|---|---|
| 물가 A8 | 발표월에 일련번호 `46204` | `2026-07` 로 변환 |
| 고용 S7·S8 | 발표월에 일련번호 `46240`·`46233` | 날짜로 변환 |
| 금융 L7 | 날짜에 일련번호 `46227` | `2026-07-24` 로 변환 |
| 고용 T9·U8·V8·V9 | 숫자 열에 `'187K'`·`'201K'`·`'209K'` 문자열 | 숫자로 변환 |
| 고용 S열 | 기준주 `2025-11-15` 중복 (셧다운 시기 불규칙 발표) | 리포트에 표시 |

`python scripts/import_excel.py --dry-run` 으로 DB 를 건드리지 않고 확인할 수 있다.

---

## GitHub Actions 배포

이 폴더는 아직 git 저장소가 아니다. 먼저 초기화하고 올린다.

```bash
git init
git add .
git commit -m "매크로 지표 대시보드 초기 구성"
git remote add origin https://github.com/<계정>/<저장소>.git
git push -u origin main
```

그다음:

1. 저장소 Settings → Secrets and variables → Actions 에 `FRED_API_KEY`, `ECOS_API_KEY` 등록
2. Settings → Pages → Source 를 **GitHub Actions** 로 설정
3. `.github/workflows/collect.yml` 이 하루 두 번(09:10 / 21:10 UTC = 18:10 / 06:10 KST)
   수집 → CSV 커밋 → Pages 배포

Actions 러너는 매번 빈 상태로 시작하지만, `db.connect()` 가 커밋된 CSV 에서 자동 복원하므로
이력이 끊기지 않는다.

수동 실행은 Actions 탭에서 `workflow_dispatch` 로. 특정 소스만 돌리거나 CDS 를 건너뛸 수 있다.

---

## 자동 수집이 실패했을 때

`manual_overrides` 테이블에 넣은 값이 자동 수집값보다 항상 우선한다.

```sql
INSERT INTO manual_overrides (series_id, ref_date, field, value, reason, created_at)
VALUES ('ism_manufacturing', '2026-07-01', 'actual', 53.3, 'ISM 사이트에서 직접 확인', datetime('now'));
```

`scripts/collect.py` 가 마지막 단계에서 반영하며, 대시보드 표에 `수동` 태그가 붙는다.

---

## 알려진 한계

- 컨센서스 과거 백필 불가 (위 참조). 이력은 오늘부터 쌓인다.
- ISM 이 ForexFactory 피드에 실제로 잡히는지는 **매월 1·3영업일 발표 후 확인이 필요하다.**
  이벤트명이 바뀌면 `calendar_ff.suggest_mappings()` 가 유사 제목을 제시해 경고한다.
- CDS 는 페이지 구조 변경에 취약하다. 실패는 화면에 표시되며 수동 입력으로 메울 수 있다.
- ForexFactory 는 비공식 피드다. 형식이 바뀌면 수집이 실패하고 값은 갱신되지 않는다
  (잘못된 값이 들어가지는 않는다).
