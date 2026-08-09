# 인수인계 — 2026-08-09 (KST) 시점

이 문서는 다음 세션이 **처음부터 다시 조사하지 않아도 되게** 하려고 쓴다.
코드에 이미 적혀 있는 것(구조·주석)은 여기 다시 안 적는다.
**결정의 이유**, **측정으로 확인한 사실**, **아직 안 끝난 것**만 적는다.

- 저장소 `D:\d클로드 1` · GitHub `greyx9-sketch/macro` · 배포 https://greyx9-sketch.github.io/macro/
- 로컬 `main` = `origin/main` = `845759f` 기준으로 작업 시작

---

## 0. 파이프라인은 지금 건강하다 — 이전 라운드 미해결 항목 전부 해소

이전 인수인계(08-07)가 남긴 미확인 항목을 전부 실측으로 닫았다.

| 항목 | 판정 | 근거 |
|---|---|---|
| 배포 막힘 (러너 배정 실패) | **해소** | `27b7aa9` → `845759f`. 08-07~08-09 **5회 연속 성공**. 코드 수정 없이 풀렸다 — 진짜 GitHub 인프라 문제였다 |
| Actions IP 에서 Cloudflare 통과? | **통과** | `forexfactory_html` 8회 전부 `http 경로`. **Playwright 폴백은 한 번도 안 탔다** |
| ISM 2종 7월 값 | **들어옴** | 제조 55.6(08-03) / 서비스 54.1(08-05), `source=forexfactory` |
| ECOS 재시도 강화 효과 | **안정** | 08-06 타임아웃 1회 이후 **실패 0건** |
| 키 마스킹 | **유효** | `origin/main` 의 `fetch_log.csv`·`dashboard.json` 에서 키 **0건** |
| 정체 감지 | **정상 작동** | 라이브 22계열 중 `alarm=True` 는 `uom_sentiment` **1건뿐** |
| 라이브 배포 | **최신** | `generatedAt = 2026-08-09T05:30:04+00:00` |

> **`uom_sentiment` 알람은 고칠 버그가 아니다.** FRED 원본(`UMCSENT`)이 2026-06 에서 멈춰 있다.
> 배지가 제 역할을 한 것이다. 이전 라운드에 직접 받아서 확인했다.

### 주말 실행이 작아 보이는 것도 정상이다

08-09(일) 실행은 `원본 73건 / 매핑 4건`으로 평소(99/7)보다 작다. **정상이다** —
일요일에 공식 피드가 다음 주(8/10~)로 롤오버했고 그 주엔 ISM·NFP 발표가 없다.
같은 시각 `forexfactory_html` 은 여전히 이번 주를 보므로 99건이다. **두 소스가 서로 다른 주를 보는 건 설계대로다.**

---

## 1. 이번 라운드에 고친 것 — 백필이 만든 경고 잡음

### 증상

`data/fetch_log.csv` 의 `forexfactory` 행에서 ⚠ 개수를 세면 인과가 분명했다.

```
08-03 ~ 08-06   warn=0
08-06 15:51     백필 실행 (calendar_events 200행 → 15,564행)
08-07 ~ 08-08   warn=1   'Retail Sales m/m' → 'Core Retail Sales m/m'   4회 연속
08-09           warn=3   ISM Mfg PMI→'ISM Manufacturing Prices' 외 2건
```

**HANDOFF §2-5 가 정체 감지기에서 경계했던 실패 양식이 다른 감지기에서 그대로 재현된 것이다.**
"매번 울리면 아무도 안 본다." 경고를 없앤 게 아니라 **울릴 때만 울리게** 되돌렸다.

### 원인 1 — 유사 제목 제안의 후보 풀이 이력 전체였다

`suggest_mappings()` 가 `calendar_events` **전체**(USD/KRW 제목 127개)를 후보로 썼다.
백필 전엔 200행이라 사실상 이번 주치였고 무해했는데, 백필 후 영구 오탐이 됐다.
제안된 것들은 전부 **다른 지표**다 — `core/series.py` 는 `'ISM Manufacturing Prices'` 가
별칭이 아니라고(가격지불 하위지수) 이미 못 박아 뒀는데, 코드가 매번 그걸 다시 제안하고 있었다.

**고침: 후보를 이번 주 피드로 되돌렸다.** 시그니처가 `suggest_mappings(feed_titles, missing_titles)` 로 바뀌었다.
근거는 **개명의 정의**다 — 개명은 "같은 주 안에서 정식 이름이 사라지고 비슷한 새 이름이 나타나는" 모습이다.
그러니 후보를 이번 주로 좁히면 **탐지력은 그대로면서 오탐만 사라진다**:
ISM 발표가 없는 주에는 `'ISM Manufacturing Prices'` 도 피드에 없다.

`unmapped_titles()` 는 **일부러 안 건드렸다** — 이력 전체를 훑는 게 그 함수의 목적이다.

### 원인 2 — `ff_aliases` 에 개명이 아닌 것이 섞여 있었다

`ff_aliases` 의 문서화된 의미는 "알려진 **옛** 이름"이고, 그걸로 잡히면 개명 의심 경고가 뜬다.
그런데 `uom_sentiment` 는 `'Prelim UoM Consumer Sentiment'` 를 거기 넣어 뒀다.
미시간대는 **매월 예비치(중순)·확정치(말)를 둘 다 정기 발표한다.** 개명이 아닌데 개명 경고가 매월 떴다.

**고침: `Series` 에 `ff_variants` 를 새로 뒀다.**

| 필드 | 뜻 | 매칭 | 경고 |
|---|---|---|---|
| `ff_aliases` | 알려진 **옛** 이름 (예: `ISM Non-Manufacturing PMI`) | O | **O** |
| `ff_variants` | **정기적으로 공존하는** 다른 표기 (예: UoM 예비치) | O | X |

`uom_sentiment` 만 옮겼다. ISM 2종의 별칭은 실제 개명 전례라 **그대로 뒀다.**

> **`_title_index()` 에서 `ff_variants` 를 절대 빠뜨리지 말 것.**
> `calendar_ff_html.py` 가 이 색인을 그대로 재사용한다. 빠지면 HTML 경로에서
> 미시간대 예비치 매칭이 **조용히** 끊긴다. 경고 여부를 가르는 건 `collect()` 지 색인이 아니다.

### 확인한 것

- dry-run: ⚠ 3건과 별칭 경고 1건이 사라졌고 **매핑 건수는 4로 동일**(값 계층 영향 없음)
- 개명 탐지 생존: 합성 피드로 `'ISM Services PMI'` 실종 + `'ISM Services Index'` 등장 → 경고 **정상 발생**
- `Retail Sales m/m` 오탐 재발 불가: 이력상 `Core Retail Sales m/m` 와 **3일 중 3일 항상 동반**,
  엇갈린 날 0. 같은 BLS 발표라 한쪽만 빠지는 일이 없다. 한쪽만 빠지면 그건 진짜 개명 신호다

---

## 2. 이전 라운드가 남긴 숙제의 답 — 낡은 전제는 파이썬 주석 6곳에 남아 있었다

`?week=mmmD.yyyy` 로 과거 주를 받을 수 있게 되면서 "놓친 주는 영원히 복구할 수 없다"는 **거짓이 됐다.**
이전 라운드가 README·워크플로는 고쳤지만 **코드 주석은 안 고쳤고**, 설계 판단 하나가 그 위에 서 있었다.

정정한 곳: `fetchers/calendar_ff.py` 모듈 docstring · `fetch_feed()` · `remap_from_stored()` ·
`suggest_mappings()`, `core/series.py` 의 `ff_aliases`, `fetchers/ecos.py`.

**정확한 표현은 "영구 손실"이 아니라 "자동으로는 안 메워지고 사람이 백필을 돌려야 한다"** 이다.

### 재시도 예산은 그대로 둔다 (사용자 결정)

`fetch_feed()` 의 재시도 6회·backoff 30초(최악 7.5분)는 "영구 손실" 전제로 정한 값이다.
**사용자 결정: 예산은 유지하고 근거만 정정한다.** 복구가 가능해도 사람 손을 빌리는 경로라 여전히 비싸다.

### 건드리지 않은 것

- `calendar_ff_html.py:11` 의 "구조적으로 영원히 안 들어왔다" — **이 수집기가 생기기 전의 과거 서술이라 정확하다**
- `prune_excel_actuals.py` · `export_json.py` · `README.md:630` 의 "복구 불가" — **다른 뜻**(로컬 데이터 삭제 사고)

---

## 3. 누적된 사실 — 다시 조사하지 말 것

### 3-1. ECOS 키는 과거 커밋에 **아직 남아 있다**

`fetchers/base.py` 가 실패 메시지에 URL 전문을 담았고 ECOS 는 인증키를 **경로에** 넣는다.
그 메시지가 `fetch_log.csv` → `dashboard.json` → 공개 사이트까지 흘렀다.

**사용자 결정: "키 재발급 안 받을 거야. 이 사이트는 나 말고는 아직 몰라. 그냥 안 보이게만 해."**

- git 히스토리도 다시 쓰지 않는다. **과거 커밋(`b4fa769` 등)과 이미 배포된 사본에는 키가 남아 있다.**
  마스킹은 앞으로만 막는다. **다음 세션이 "지웠다"고 착각하면 안 된다.**
- 앞으로의 유출은 3중 방어: `base.py:_safe_url()`(쿼리+호스트별 경로 세그먼트) ·
  `core/secrets.py:safe_message()`(환경변수 값 문자열 치환) · `core/db.py:log_finish()`(**저장 직전 마지막 관문**).
  3중인 이유는 1번이 우리가 만든 URL 만 알기 때문 — 타임아웃 예외 문자열처럼 1번이 못 보는 경로가 실재한다.

### 3-2. 공식 피드는 `actual` 을 주지 않는다 — ISM 이 두 달 죽어 있던 진짜 이유

```
ff_calendar_thisweek.json     99건 중 actual 있는 것 0건
ff_calendar_thisweek.xml/csv  <actual> 필드 자체가 없음
lastweek / nextweek / thismonth  전부 404
```

ISM 은 라이선스 때문에 FRED 에 없다(`fred_id=None`). 버그가 아니라 **소스에 대한 잘못된 가정**이었다.
무료·기계판독 대안 전부 사망 — FRED(계열 없음) · DBnomics(헤드라인 아님) · Trading Economics(410) ·
Nasdaq Data Link(봇 차단) · econdb(401) · fxstreet(401) · ismworld.org(SSO).

### 3-3. 유일하게 작동하는 경로 — FF 캘린더 **HTML** 의 임베드 JSON

`window.calendarComponentStates[N]` 의 `days` 배열이 공식 피드의 **상위집합**이다.

파싱 함정 두 개 (여기서 시간을 많이 썼다):
- 최상위가 `{ days: [...] }` 형태의 **JS 객체 리터럴**이라 키에 따옴표가 없다.
  통째로 `json.loads` 하면 깨진다 → `days:` 뒤에서 `json.JSONDecoder().raw_decode`.
- 시각이 UTC epoch 인데 기준시점 역산은 **미 동부 날짜** 기준이어야 한다.
  Windows 에 `tzdata` 가 없어 `ZoneInfo("America/New_York")` 가 터진다 → `_eastern_offset()` 으로 직접 구현.

**파서 정합성 교차 검증** (파서를 의심할 일이 생기면 이걸 다시 쓰면 된다):
- 신규 실업수당 청구 `199K` = FRED `ICSA` 의 `2026-08-01, 199000`
- `?week=jul6.2026` 의 ISM 서비스업 `A=54.0 F=54.2 P=54.5` = 엑셀 백필 `ism_services 2026-06-01` 3값 일치

### 3-4. 백필 결과 (측정치, 이미 완료 — 다시 돌릴 일 없음)

158주 요청, 실패 0. 실제값 139건 회수. **ISM 관측치 22 → 80건**(2019-12~2026-07). 빈 칸 814개 채움.
**기존 값 변경 0건.** 지금 ISM 2종은 160행 중 116행이 `source=forexfactory` 다.

---

## 4. 절대 어기면 안 되는 규칙 (누적)

1. **엑셀 파일은 "무엇을 추적할지"의 명세지 재현할 데이터가 아니다.**
   값이 충돌하면 **항상 권위 소스(FRED/ECOS)가 이긴다.**
2. **`forecast`(예측) · `previous`(이전)는 절대 건드리지 않는다.**
   이걸 어겨서 사고가 났다 — `remap_from_stored` 를 테스트로 돌렸다가 엑셀 예측·이전 169건을 덮었다.
   그래서 이 함수는 **기본이 fill-only** 다. 덮으려면 `overwrite=True` 를 명시해야 한다.
3. **권위 소스가 있는 계열의 기존 `actual` 을 캘린더 값으로 덮지 않는다.**
   FF 는 반올림 값을 준다 — JOLTS 2026-06 이 `7.359 → 7.36` 으로 뭉개졌었다.
   `calendar_ff_html.store_week()` 의 `authoritative` 가드가 막는다. 빈 칸 채우기는 계속 허용.
4. **PPI 는 계절조정 값을 쓴다.**
5. **Python 은 `/c/Users/greyx/AppData/Local/Programs/Python/Python312/python.exe`.**
   PATH 의 `python` 은 깨진 Windows Store 스텁이다.
   콘솔이 cp949 라 한글·⚠ 출력 시 `PYTHONIOENCODING=utf-8` 을 붙여야 한다.
6. **Cloudflare 감지 문자열을 넓게 잡지 말 것.**
   `challenge-platform` 은 **정상 페이지에도 전부 들어있다.** 마커는 `cf_chl_opt` / `Just a moment...` 로 좁게.
7. **감지기를 추가할 땐 "정상일 때 몇 번 울리는지"를 먼저 세어 볼 것.**
   매번 울리는 경고는 없는 것보다 나쁘다 — 진짜 신호까지 같이 묻는다.
   **이 규칙을 어긴 사례가 이 저장소에 다섯 번 있었다.** 추측하지 말고 `verify.py --noise` 로 측정할 것.
8. **`issues` 와 `notes` 를 섞지 말 것.** 기준은 하나다 — **사람이 보고 할 일이 있는가.**
   `issues` 는 `fetch_log.csv` 에 영구 보관되고 사이트에도 나간다. `notes` 는 콘솔에만 찍힌다.
   통과 확인·커버리지 보고를 `issues` 에 넣으면 고장 났을 때 읽어야 할 파일이 오염된다.
   판단 기준은 `fetchers/base.py` 의 `FetchResult` 주석에 박아 뒀다.

---

## 4-1. 감지기 전수 조사 결과 (2026-08-10) — 다시 조사하지 말 것

규칙 7 을 세 번 어긴 뒤 남은 감지기를 전부 실측했다. 판정은 `fetch_log.csv` 의 발생 빈도다.

| 감지기 | 정상일 때 | 조치 |
|---|---|---|
| `fetchers/fred.py` 계절조정 확인됨 | 매 실행 **5건** | `notes` 로 옮기고 1줄로 합침 |
| `fetchers/calendar_ff.py` 커버리지 목록 | 매 실행 **1건** | `notes` 로 |
| `fetchers/calendar_ff_html.py` 실제값 0건 | 12회 중 4회 | 판정을 페이지 전체 표본으로 (§1-3) |
| `calendar_ff.suggest_mappings` | 48회 중 7회 | 후보를 이번 주 피드로 (§1) |
| `calendar_ff` 별칭 경고 | 매월 예비치 주 | `ff_variants` 신설 (§1) |
| `core/validate.py` range 검사 | 46회 중 **1회**(초기 임포트) | **정상. 건드리지 말 것** |
| `scripts/collect.py:cross_check` | **0건** | **정상** |
| `scripts/collect.py:staleness_check` | 1건(`uom_sentiment` 진짜 정체) | **정상** |
| `fetchers/cds.py` | **0건** | **정상** |
| `calendar_ff` 발표시각 파싱 실패 | **0건** | **정상** |

> **range 검사의 12건은 전부 2020년 3~6월 COVID 값이다** — NFP `-20,469K`,
> 실업수당 `5,946K`. 단위 오류가 아니라 **진짜 역사적 값**이고, 새 값이 들어올 때만
> 도는 감지기라 초기 임포트 때 1회 울리고 끝났다. 상식 범위를 넓히지 말 것.

---

## 5. 검증 명령 (회귀 확인용)

```bash
PY=/c/Users/greyx/AppData/Local/Programs/Python/Python312/python.exe
export PYTHONIOENCODING=utf-8

$PY scripts/verify.py --offline              # 단위·범위 ('개정 차이' 는 정상)
$PY scripts/verify.py --bls                  # BLS 대조
$PY scripts/verify.py --stale                # uom_sentiment 1건이 정상
$PY scripts/verify.py --noise                # 정상일 때 반복해 우는 경고 (DB·네트워크 불필요)
$PY scripts/collect.py --dry-run --only forexfactory   # 캘린더만 빠르게
$PY scripts/collect.py --dry-run             # 전체
$PY scripts/export_json.py
```

> **`--noise` 는 감지기를 건드린 뒤 며칠 지나서 돌려야 뜻이 있다.** `fetch_log.csv`
> 누적을 보기 때문이다. 방금 고쳤다면 옛 기록이 그대로 잡히는 게 정상이다 —
> 고친 뒤 실행이 쌓여야 발생률이 내려간다.

키 마스킹 확인:

```bash
git show origin/main:data/fetch_log.csv | grep -c '2S5JQ0TP'   # 0 이어야 한다
curl -s https://greyx9-sketch.github.io/macro/data/dashboard.json | grep -c '2S5JQ0TP'
```

**경고 잡음 회귀 확인 — dry-run 출력에 `⚠ ff_title 확인 필요` 가 뜨면 의심하라.**
정상적으로는 발표가 없는 주라도 "이번 주 피드에 없던 지표" 줄만 나오고 ⚠ 는 안 나온다.

---

## 6. 다음에 할 일

1. **[관찰] 다음 미시간대 예비치 주(매월 중순)에 별칭 경고가 안 뜨는지 확인.**
   이번 수정의 효과가 실제 발표 주에 나타나는지 보는 것 — 지금은 합성 테스트로만 확인했다.
2. **[관찰] 다음 ISM 발표 주(월 첫 주)에 ⚠ 가 0인지 확인.** 오탐 3건이 나던 조건이다.
3. **[보류] `revision` 필드를 개정 이력 패널에 반영.**
   FF HTML 이 직전값 개정을 준다(청구 `197K→198K`). 지금은 `calendar_events` 에 **원본만 보관**하고
   값 계층에는 안 쓴다. 반영하려면 `revision_raw` 컬럼이 필요하다 — 값 계산에 손대는 일이라 별도 라운드.
   (참고: `previous_raw` 에 `197K→198K` 를 인코딩해 뒀던 적이 있는데 `parse_raw_number` 가 `None` 을
   반환해서 재매핑 시 `previous` 가 조용히 사라졌다. 3,897행이 영향받았고 인코딩을 제거했다. **다시 하지 말 것.**)

---

## 7. 하지 않기로 한 것 (다시 제안하지 말 것)

- **ECOS 키 재발급 · git 히스토리 재작성** — 사용자 결정
- **`fetch_feed()` 재시도 예산 단축** — 사용자 결정. 근거 주석만 정정했다
- **공식 JSON 피드를 HTML 스크레이핑으로 대체** — 예측·이전은 계속 공식 피드가 주소스.
  스크레이핑은 `actual` 보충일 뿐이고, 깨져도 컨센서스 수집은 살아 있어야 한다
- **전 지표 6년치 주간 백필** — ISM 에 필요한 월 첫 두 주만. 나머지는 FRED 가 권위 소스라 얻을 게 없다
- **ISM 을 상시 수동 입력으로 전환** — `manual_overrides` 는 3단 폴백이 전부 실패할 때의 마지막 수단
