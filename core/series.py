# -*- coding: utf-8 -*-
"""17개 매크로 지표의 단일 정의(single source of truth).

엑셀 `매크로 머티리얼.xlsm`이 암묵적으로 지키던 규칙 — 어떤 열은 퍼센트를 소수로,
어떤 열은 천 단위로, 어떤 열은 bp로 — 을 여기서 명시적으로 선언한다.
수집기·임포터·프론트엔드가 모두 이 파일만 참조하므로 단위 버그가 한 곳에서만 발생한다.

핵심 주의사항
-------------
같은 '금융' 시트 안에서도 단위 규약이 다르다:
  - 기준금리는 비율(0.0375 == 3.75%)
  - 10Y-2Y 금리차는 %p 원값(0.36 == 0.36%p)  ← 비율이 아니다
이 불일치는 엑셀에 실재하며, 그대로 재현해야 기존 값과 대조가 가능하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# 단위 체계
# ---------------------------------------------------------------------------
# ratio    : 비율로 저장. 0.035 를 3.5% 로 표시     (CPI YoY, 실업률, 기준금리 …)
# index    : 지수 원값                              (CPI 지수, PPI 지수, ISM PMI)
# thousands: 천 단위                                (NFP, 신규 실업수당 청구)
# millions : 백만 단위                              (JOLTS)
# pp       : 퍼센트포인트 원값                      (10Y-2Y)
# bp       : 베이시스포인트                         (CDS)
Unit = Literal["ratio", "index", "thousands", "millions", "pp", "bp"]

Category = Literal["물가", "고용", "서베이", "금융"]
Frequency = Literal["monthly", "weekly", "daily", "event"]


@dataclass(frozen=True)
class Series:
    """지표 하나의 완전한 정의."""

    id: str
    name_ko: str
    category: Category
    unit: Unit
    frequency: Frequency
    decimals: int

    # --- 실제값 소스 -------------------------------------------------------
    # fred_id 가 있으면 FRED 에서 실제값을 가져온다.
    fred_id: Optional[str] = None
    # FRED 원값 -> 저장 단위 변환. None 이면 원값 그대로.
    #   'yoy'      전년동월비 비율
    #   'mom'      전월비 비율
    #   'diff'     전월차분 (NFP)
    #   'div100'   /100  (퍼센트로 오는 값을 비율로)
    #   'div1000'  /1000 (건 -> 천, 천 -> 백만)
    transform: Optional[str] = None

    # FRED 가 아닌 소스
    ecos_stat: Optional[tuple[str, str, str]] = None  # (통계표, 주기, 항목코드)
    cds_country: Optional[str] = None  # worldgovernmentbonds URL 슬러그

    # --- 컨센서스(예측) 소스 ----------------------------------------------
    # ForexFactory 이벤트 제목. None 이면 무료 컨센서스가 존재하지 않는 지표.
    ff_title: Optional[str] = None
    ff_country: str = "USD"

    # 발표월과 기준월의 간격(개월). 캘린더 이벤트의 발표일에서 기준월을 역산할 때 쓴다.
    # **frequency == 'monthly' 인 지표에만 적용된다.** 주간/일간/이벤트성 지표는
    # 발표일 자체가 기준시점이거나 별도 규칙(주간=직전 토요일)을 따르므로 0으로 둔다.
    # 대부분 1이지만 JOLTS 는 2개월 지연 발표다 — 엑셀에서도 확인된다
    # (발표 2026-08 / 기준 2026-06). 이 값을 틀리면 예측이 엉뚱한 달에 붙는다.
    ref_lag_months: int = 1

    # --- 표시 --------------------------------------------------------------
    # 값이 클수록 경제에 긍정적인가? 서프라이즈 해석에만 쓰이고 색상에는 쓰지 않는다.
    higher_is_better: Optional[bool] = None
    note: str = ""
    # 엑셀 대조 시 검증용 대체 후보. verify.py 가 어느 쪽이 맞는지 판정한다.
    fred_alternatives: tuple[str, ...] = field(default_factory=tuple)


# ---------------------------------------------------------------------------
# 물가
# ---------------------------------------------------------------------------
_PRICES = [
    Series(
        id="cpi_index",
        name_ko="CPI 지수",
        category="물가",
        unit="index",
        frequency="monthly",
        decimals=3,
        fred_id="CPIAUCNS",  # 엑셀 출처가 'cpi-index, n.s.a.' 이므로 계절조정 전 계열
        ff_title=None,  # ForexFactory 는 지수 레벨 컨센서스를 제공하지 않는다
        note="계절조정 전(NSA) 소비자물가지수. 1982-84=100.",
    ),
    Series(
        id="cpi_yoy",
        name_ko="CPI (% YoY)",
        category="물가",
        unit="ratio",
        frequency="monthly",
        decimals=3,
        fred_id="CPIAUCNS",
        transform="yoy",
        ff_title="CPI y/y",
        higher_is_better=False,
    ),
    Series(
        id="ppi_index",
        name_ko="PPI 지수",
        category="물가",
        unit="index",
        frequency="monthly",
        decimals=3,
        fred_id="PPIFIS",
        # PPIFIS(계절조정)와 WPSFD4(계절조정 전) 중 엑셀 값과 맞는 쪽을 verify.py 가 가린다.
        fred_alternatives=("WPSFD4", "PPIACO"),
        ff_title=None,
        note="최종수요 생산자물가지수.",
    ),
    Series(
        id="pce_yoy",
        name_ko="PCE (% YoY)",
        category="물가",
        unit="ratio",
        frequency="monthly",
        decimals=3,
        fred_id="PCEPI",
        transform="yoy",
        ff_title=None,  # FF 는 m/m 만 제공. y/y 컨센서스 없음.
        higher_is_better=False,
    ),
    Series(
        id="core_pce_yoy",
        name_ko="근원 PCE (% YoY)",
        category="물가",
        unit="ratio",
        frequency="monthly",
        decimals=3,
        fred_id="PCEPILFE",
        transform="yoy",
        ff_title=None,
        higher_is_better=False,
        note="식품·에너지 제외. 연준이 실질적으로 보는 물가 지표.",
    ),
]

# ---------------------------------------------------------------------------
# 고용
# ---------------------------------------------------------------------------
_EMPLOYMENT = [
    Series(
        id="nfp",
        name_ko="비농업 고용(NFP)",
        category="고용",
        unit="thousands",
        frequency="monthly",
        decimals=0,
        fred_id="PAYEMS",
        transform="diff",  # PAYEMS 는 수준(천 명), 발표되는 값은 전월차분
        ff_title="Non-Farm Employment Change",
        higher_is_better=True,
        note="일자리 창출. 발표 후 2회 개정된다 — 개정 이력은 vintages 로 추적.",
    ),
    Series(
        id="unemployment_rate",
        name_ko="실업률",
        category="고용",
        unit="ratio",
        frequency="monthly",
        decimals=3,
        fred_id="UNRATE",
        transform="div100",  # FRED 는 4.2 로 준다 -> 0.042
        ff_title="Unemployment Rate",
        higher_is_better=False,
    ),
    Series(
        id="avg_hourly_earnings_mom",
        name_ko="시간당 임금 (% MoM)",
        category="고용",
        unit="ratio",
        frequency="monthly",
        decimals=4,
        fred_id="CES0500000003",
        transform="mom",
        ff_title="Average Hourly Earnings m/m",
        higher_is_better=None,
        note="민간 전체 시간당 평균임금. 임금발 물가압력 지표.",
    ),
    Series(
        id="initial_claims",
        name_ko="신규 실업수당 청구",
        category="고용",
        unit="thousands",
        frequency="weekly",
        decimals=0,
        fred_id="ICSA",
        transform="div1000",  # FRED 는 건수(187000) -> 187 천 건
        ff_title="Unemployment Claims",
        ref_lag_months=0,  # 주간: 발표일(목)에서 직전 토요일을 기준시점으로 역산
        higher_is_better=False,
    ),
    Series(
        id="jolts",
        name_ko="JOLTS 구인",
        category="고용",
        unit="millions",
        frequency="monthly",
        decimals=3,
        fred_id="JTSJOL",
        transform="div1000",  # FRED 는 천 건(7594) -> 7.594 백만
        ff_title="JOLTS Job Openings",
        ref_lag_months=2,  # 유일하게 2개월 지연 발표
        higher_is_better=True,
        note="노동 수요. 2개월 지연 발표.",
    ),
]

# ---------------------------------------------------------------------------
# 서베이 — FRED 에 없다(ISM 이 2016년 제공 중단). ForexFactory 로만 수집.
# ---------------------------------------------------------------------------
_SURVEY = [
    Series(
        id="ism_manufacturing",
        name_ko="ISM 제조업 PMI",
        category="서베이",
        unit="index",
        frequency="monthly",
        decimals=1,
        fred_id=None,
        ff_title="ISM Manufacturing PMI",
        higher_is_better=True,
        note="50 기준. ISM 라이선스 정책상 FRED 에 없어 캘린더 피드로만 수집한다.",
    ),
    Series(
        id="ism_services",
        name_ko="ISM 서비스업 PMI",
        category="서베이",
        unit="index",
        frequency="monthly",
        decimals=1,
        fred_id=None,
        ff_title="ISM Services PMI",
        higher_is_better=True,
        note="50 기준. 매월 셋째 영업일 발표.",
    ),
]

# ---------------------------------------------------------------------------
# 금융
# ---------------------------------------------------------------------------
_FINANCE = [
    Series(
        id="fed_funds_upper",
        name_ko="미국 기준금리 상단",
        category="금융",
        unit="ratio",
        frequency="event",
        decimals=4,
        fred_id="DFEDTARU",
        transform="div100",
        ff_title="Federal Funds Rate",
        ref_lag_months=0,  # 이벤트성: 발표일이 곧 기준시점
        note="목표범위 상단. 발표일은 FOMC 결과일(현지). — 엑셀 주1",
    ),
    Series(
        id="bok_base_rate",
        name_ko="한국 기준금리",
        category="금융",
        unit="ratio",
        frequency="event",
        decimals=4,
        ecos_stat=("722Y001", "D", "0101000"),
        transform="div100",
        # ForexFactory 무료 피드는 주요 9개 통화(USD/EUR/GBP/JPY/AUD/CHF/CAD/CNY/NZD)만
        # 담고 KRW 은 아예 없다 — 실측으로 확인했다. 따라서 컨센서스 소스가 없다.
        # 엑셀 금융시트도 한국 기준금리에는 '예측' 열이 없으므로(실제/이전(수정)만) 문제되지 않는다.
        ff_title=None,
        ref_lag_months=0,
        note="금통위 결정. 예측 없이 실제·이전(수정) 기준. — 엑셀 주3",
    ),
    Series(
        id="t10y2y",
        name_ko="10Y-2Y 금리차",
        category="금융",
        unit="pp",  # 비율이 아니라 %p 원값. 엑셀과 동일.
        frequency="daily",
        decimals=2,
        fred_id="T10Y2Y",
        ff_title=None,
        ref_lag_months=0,
        note="장단기 금리차. 음수는 침체 신호로 해석된다. 출처 FRED T10Y2Y. — 엑셀 주2",
    ),
    Series(
        id="cds_us_5y",
        name_ko="미국 CDS 5년물",
        category="금융",
        unit="bp",
        frequency="daily",
        decimals=2,
        cds_country="united-states",
        ff_title=None,
        ref_lag_months=0,
        higher_is_better=False,
        note="1bp = 0.01%p. 국가 부도위험 프리미엄. — 엑셀 주4",
    ),
    Series(
        id="cds_kr_5y",
        name_ko="한국 CDS 5년물",
        category="금융",
        unit="bp",
        frequency="daily",
        decimals=2,
        cds_country="south-korea",
        ff_title=None,
        ref_lag_months=0,
        higher_is_better=False,
        note="1bp = 0.01%p. — 엑셀 주4",
    ),
]

ALL_SERIES: list[Series] = _PRICES + _EMPLOYMENT + _SURVEY + _FINANCE

BY_ID: dict[str, Series] = {s.id: s for s in ALL_SERIES}

CATEGORY_ORDER: list[Category] = ["물가", "고용", "서베이", "금융"]


def by_category(cat: Category) -> list[Series]:
    return [s for s in ALL_SERIES if s.category == cat]


def fred_series() -> list[Series]:
    return [s for s in ALL_SERIES if s.fred_id]


def ff_mapped_series() -> list[Series]:
    """ForexFactory 이벤트와 연결된 지표."""
    return [s for s in ALL_SERIES if s.ff_title]


# ---------------------------------------------------------------------------
# 표시 포맷 — 프론트엔드와 CLI 리포트가 동일한 규칙을 쓰도록 여기서 정의
# ---------------------------------------------------------------------------
def format_value(series: Series, value: Optional[float]) -> str:
    """엑셀 표기 규칙에 맞춰 문자열로. 미발표/결측은 엠대시."""
    if value is None:
        return "—"
    if series.unit == "ratio":
        return f"{value * 100:.{max(0, series.decimals - 2)}f}%"
    if series.unit == "thousands":
        return f"{value:,.{series.decimals}f}K"
    if series.unit == "millions":
        return f"{value:.{series.decimals}f}M"
    if series.unit == "bp":
        return f"{value:.{series.decimals}f}bp"
    if series.unit == "pp":
        return f"{value:.{series.decimals}f}%p"
    return f"{value:.{series.decimals}f}"


def sanity_range(series: Series) -> tuple[float, float]:
    """validate.py 가 쓰는 상식적 범위. 벗어나면 단위 변환 실수를 의심한다."""
    return {
        "ratio": (-0.5, 0.5),
        "index": (0.0, 1000.0),
        "thousands": (-2000.0, 2000.0),
        "millions": (0.0, 30.0),
        "pp": (-5.0, 5.0),
        "bp": (0.0, 1000.0),
    }[series.unit]
