# -*- coding: utf-8 -*-
"""수집기 공통 기반.

설계 원칙: **한 소스가 죽어도 나머지는 반드시 수집된다.**
CDS 어댑터(가장 취약)가 실패해도 FRED 12종은 정상 커밋되어야 하므로,
모든 수집기는 예외를 밖으로 던지지 않고 FetchResult 로 감싸 돌려준다.
"""

from __future__ import annotations

import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

USER_AGENT = "macro-dashboard/1.0 (+personal research tool)"
DEFAULT_TIMEOUT = 30


@dataclass
class FetchResult:
    source: str
    ok: bool
    rows: int = 0
    message: str = ""
    issues: list[str] = field(default_factory=list)

    @classmethod
    def failure(cls, source: str, exc: BaseException) -> "FetchResult":
        return cls(source=source, ok=False, message=f"{type(exc).__name__}: {exc}")


class FetchError(RuntimeError):
    pass


def http_get(
    url: str,
    params: Optional[dict[str, Any]] = None,
    *,
    headers: Optional[dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT,
    retries: int = 3,
    backoff: float = 2.0,
) -> bytes:
    """표준 라이브러리만 사용하는 GET.

    requests 를 쓰지 않는 이유: 이 프로젝트의 유일한 필수 외부 의존성을
    openpyxl 하나로 줄여 GitHub Actions 환경에서 깨질 여지를 없애기 위해서다.
    """
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"

    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json, text/plain, */*"}
    if headers:
        hdrs.update(headers)

    last_exc: Optional[BaseException] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            # 4xx 는 재시도해도 소용없다. 단 429(rate limit)만 예외.
            if exc.code == 429 or exc.code >= 500:
                last_exc = exc
            else:
                raise FetchError(f"HTTP {exc.code} {exc.reason} :: {url}") from exc
        except Exception as exc:  # 타임아웃, DNS, TLS 등
            last_exc = exc

        if attempt < retries - 1:
            time.sleep(backoff * (attempt + 1))

    raise FetchError(f"{retries}회 재시도 실패 :: {url} :: {last_exc}")


def guarded(source: str) -> Callable:
    """수집기 함수를 감싸 예외를 FetchResult 로 변환하는 데코레이터."""

    def decorator(fn: Callable[..., FetchResult]) -> Callable[..., FetchResult]:
        def wrapper(*args, **kwargs) -> FetchResult:
            try:
                return fn(*args, **kwargs)
            except BaseException as exc:  # noqa: BLE001 — 격리가 목적
                return FetchResult.failure(source, exc)

        wrapper.__name__ = fn.__name__
        return wrapper

    return decorator


def parse_raw_number(raw: Optional[str]) -> Optional[tuple[float, bool]]:
    """캘린더 피드의 '201K', '3.75%', '-100.3B', '' 를 (기본단위 값, 퍼센트여부)로.

    **항상 '개' 단위로 환산해서 돌려준다.** '201K' -> 201000.0.
    목표 단위(천/백만/지수)로의 변환은 지표 정의를 아는 to_series_unit() 이 맡는다.
    이 둘을 한 함수에서 처리하면 '201K'(천 건)와 '7.59M'(백만 건)을
    같은 규칙으로 나눠 버리는 단위 버그가 난다.

    해석 불가하면 None. 절대 0 으로 대체하지 않는다.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text in {"—", "-", "--", "N/A", "n/a"}:
        return None

    text = text.replace(",", "").replace("<", "").replace(">", "").replace("~", "")

    if text.endswith("%"):
        try:
            return float(text[:-1]), True
        except ValueError:
            return None

    multiplier = 1.0
    if text[-1:] in "KkMmBbTt":
        multiplier = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}[text[-1].upper()]
        text = text[:-1]

    try:
        return float(text) * multiplier, False
    except ValueError:
        return None


# 저장 단위 1 이 '개' 단위로 몇에 해당하는가.
_UNIT_DIVISOR = {
    "thousands": 1e3,
    "millions": 1e6,
    "index": 1.0,
    "pp": 1.0,
    "bp": 1.0,
    "ratio": 1.0,
}


def to_series_unit(unit: str, parsed: Optional[tuple[float, bool]]) -> Optional[float]:
    """parse_raw_number 결과를 지표의 저장 단위로 변환."""
    if parsed is None:
        return None
    value, is_percent = parsed

    if is_percent:
        # 퍼센트 표기는 언제나 비율로 저장한다. 4.2% -> 0.042
        return value / 100.0

    if unit == "ratio":
        # 퍼센트 기호 없이 온 비율 계열 — 캘린더에서는 사실상 없지만 방어적으로 처리
        return value / 100.0

    return value / _UNIT_DIVISOR[unit]
