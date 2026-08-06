# -*- coding: utf-8 -*-
"""비밀값 가리기.

왜 core 에 있는가
-----------------
수집 실패 메시지는 `fetch_log` 에 저장되고, CSV 로 커밋되고, `dashboard.json` 을
거쳐 **공개 사이트에 그대로 실린다.** 실제로 한국은행 ECOS 인증키가 이 경로로
새어 나갔다 — 타임아웃 메시지에 URL 전체가 들어 있었고, ECOS 는 키를
쿼리가 아니라 **경로 세그먼트**에 넣는다.

    https://ecos.bok.or.kr/api/StatisticSearch/{KEY}/json/kr/1/10000/...

그래서 가리는 지점을 두 곳에 둔다.
  1) URL 을 만들 때        — `fetchers/base.py:_safe_url`
  2) 기록으로 남기기 직전  — 이 모듈의 `safe_message`, `core/db.py:log_finish` 에서 호출

fetchers 가 아니라 core 에 두는 이유는 저장 계층(`core/db.py`)이 써야 하기 때문이다.
core 가 fetchers 를 import 하면 의존 방향이 뒤집힌다.
"""

from __future__ import annotations

import os
import re

MASK = "***"

# 환경변수 이름 — 값이 메시지 어딘가에 그대로 박혀 있으면 통째로 지운다.
SECRET_ENV_NAMES = ("FRED_API_KEY", "ECOS_API_KEY")

# 환경변수를 못 읽는 곳(로컬 점검, 과거 기록 정리)에서도 ECOS 키 자리를 가린다.
# '/api/{서비스명}/{16자 이상 영숫자}/' 형태만 좁게 잡는다.
_ECOS_KEY_IN_PATH = re.compile(r"(/api/[A-Za-z]+/)[A-Za-z0-9]{16,}(/)")


def scrub_secrets(text: str) -> str:
    """환경변수에 든 키 문자열이 보이면 지운다.

    URL 마스킹이 놓치는 경로가 있다 — 서드파티 예외 메시지, 응답 본문 조각,
    앞으로 추가될 소스의 새로운 URL 형태. 저장 직전에 한 번 더 훑는다.
    """
    if not text:
        return text
    for name in SECRET_ENV_NAMES:
        val = os.environ.get(name)
        # 짧은 값은 우연히 본문과 겹칠 수 있어 건드리지 않는다.
        if val and len(val) >= 8:
            text = text.replace(val, MASK)
    return text


def safe_message(text: str) -> str:
    """기록에 남기기 전 마지막 정제."""
    if not text:
        return text
    return _ECOS_KEY_IN_PATH.sub(r"\1" + MASK + r"\2", scrub_secrets(text))
