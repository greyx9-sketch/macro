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

Category = Literal["물가", "고용", "경기", "서베이", "금융"]
Frequency = Literal["monthly", "quarterly", "weekly", "daily", "event"]


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

    # 이 계열이 반드시 만족해야 하는 계절조정 상태. 'SA' | 'NSA' | None.
    # 지정하면 수집기가 FRED 계열 메타데이터를 조회해 실제로 그런지 검증하고,
    # 다르면 해당 지표만 실패시킨다. 계절조정 여부는 값을 통째로 바꾸는 선택인데
    # 계열 ID 만 봐서는 알 수 없으므로, 믿음이 아니라 코드가 보장하게 한다.
    require_seasonal_adjustment: Optional[str] = None

    # FRED 가 아닌 소스
    ecos_stat: Optional[tuple[str, str, str]] = None  # (통계표, 주기, 항목코드)
    cds_country: Optional[str] = None  # worldgovernmentbonds URL 슬러그

    # --- 컨센서스(예측) 소스 ----------------------------------------------
    # ForexFactory 이벤트 제목. None 이면 무료 컨센서스가 존재하지 않는 지표.
    ff_title: Optional[str] = None
    ff_country: str = "USD"

    # 같은 이벤트의 다른 표기. ForexFactory 가 이벤트명을 바꾸면
    # (예: 'ISM Non-Manufacturing PMI' -> 'ISM Services PMI') 매칭이 조용히 끊기는데,
    # 피드는 지난 주를 다시 주지 않으므로 발견이 늦을수록 손실이 크다.
    # 알려진 옛 이름을 미리 등록해 두면 어느 쪽으로 와도 잡힌다.
    ff_aliases: tuple[str, ...] = field(default_factory=tuple)

    # 발표월과 기준월의 간격(개월). 캘린더 이벤트의 발표일에서 기준월을 역산할 때 쓴다.
    # **frequency == 'monthly' 인 지표에만 적용된다.** 주간/일간/이벤트성 지표는
    # 발표일 자체가 기준시점이거나 별도 규칙(주간=직전 토요일)을 따르므로 0으로 둔다.
    # 대부분 1이지만 JOLTS 는 2개월 지연 발표다 — 엑셀에서도 확인된다
    # (발표 2026-08 / 기준 2026-06). 이 값을 틀리면 예측이 엉뚱한 달에 붙는다.
    ref_lag_months: int = 1

    # 이 지표가 발표 후 개정되는 통상적인 폭(저장 단위 기준).
    # verify.py 가 '매핑 오류'와 '개정 차이'를 구분하는 데 쓴다.
    #   엑셀에는 *발표 당시* 값이 적혀 있고 FRED 는 *개정된 현재* 값을 준다.
    #   따라서 둘의 차이는 대부분 정상이며, 개정 폭 안에 들어오면 매핑은 옳은 것이다.
    # 0 = 개정되지 않는 지표(시장금리 등). 여기서 차이가 나면 진짜 문제다.
    revision_band: float = 0.0

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
        # 전 이력(1990~) 기준 |발표값-관측치| 99분위 0.10, 최대 0.20.
        # 엑셀 4년치만 보고 0.005 로 잡았다가 2000년대 개정에 전부 걸렸다.
        revision_band=0.15,
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
        revision_band=0.0005,  # 반올림 오차만
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
        # 계절조정된 값을 쓴다(사용자 요구). PPIFIS 가 SA 계열로 알려져 있지만
        # 계열 ID 만으로는 확인할 수 없으므로 수집 시 메타데이터로 검증한다.
        require_seasonal_adjustment="SA",
        # 계절조정 전 대응 계열은 PPIFID 다. verify.py 가 대안으로 시험한다.
        fred_alternatives=("PPIFID", "PPIACO"),
        revision_band=1.0,  # 발표 후 4개월간 개정. 전 이력 99분위 0.68, 최대 0.78
        ff_title=None,
        note="최종수요 생산자물가지수(계절조정).",
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
        revision_band=0.004,  # PCE 는 연례 개정 폭이 크다
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
        revision_band=0.004,
        ff_title=None,
        higher_is_better=False,
        note="식품·에너지 제외. 연준이 실질적으로 보는 물가 지표.",
    ),
    Series(
        id="core_pce_mom",
        name_ko="근원 PCE (% MoM)",
        category="물가",
        unit="ratio",
        frequency="monthly",
        decimals=4,
        fred_id="PCEPILFE",
        transform="mom",
        require_seasonal_adjustment="SA",
        # 연준이 실제로 반응하는 형태. YoY 와 달리 캘린더에 컨센서스가 들어온다.
        ff_title="Core PCE Price Index m/m",
        higher_is_better=False,
        note="연준이 가장 주시하는 물가 지표의 월간 변화. 예측이 존재하는 유일한 PCE 형태다.",
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
        revision_band=200.0,  # 2회 개정 + 연례 벤치마크 개정. 실측 최대 194천명
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
        revision_band=0.003,  # 계절조정계수 재추정. 전 이력 최대 0.3%p
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
        revision_band=0.002,  # 수준값 개정이 전월비에 그대로 반영된다
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
        # 매주 직전치가 수정된다. 전 이력 99분위 75천건.
        # 2020년 3~4월에는 최초발표와 개정치가 702천건까지 벌어졌는데,
        # 그건 실제 혼란이지 오류가 아니다 — 비율 기반 판정이 이를 걸러낸다.
        revision_band=112.0,
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
        revision_band=1.06,  # 표본 조사라 개정 폭이 크다. 전 이력 99분위 0.71
        ff_title="JOLTS Job Openings",
        ref_lag_months=2,  # 유일하게 2개월 지연 발표
        higher_is_better=True,
        note="노동 수요. 2개월 지연 발표.",
    ),
    Series(
        id="eci_qoq",
        name_ko="고용비용지수 (% QoQ)",
        category="고용",
        unit="ratio",
        frequency="quarterly",
        decimals=4,
        fred_id="ECIALLCIV",   # 지수(2005-12=100)라 전분기비로 환산한다
        transform="qoq",
        require_seasonal_adjustment="SA",
        ff_title="Employment Cost Index q/q",
        higher_is_better=False,  # 임금발 물가압력 관점. 근로자 관점과는 반대다
        note="전체 근로자 총보수 비용. 임금발 물가압력을 보는 지표라 연준이 분기마다 확인한다.",
    ),
]

# ---------------------------------------------------------------------------
# 경기 — 실물 활동. 기존 4개 시트에는 없던 축이라 새로 만든다.
# ---------------------------------------------------------------------------
_ACTIVITY = [
    Series(
        id="gdp_qoq",
        name_ko="실질 GDP (% QoQ 연율)",
        category="경기",
        unit="ratio",
        frequency="quarterly",
        decimals=3,
        # 이미 '전기대비 연율 %' 로 제공되는 계열이라 별도 파생이 필요 없다.
        fred_id="A191RL1Q225SBEA",
        transform="div100",
        # 'SA' 를 요구하면 'SAAR'(연율 환산 계절조정)도 통과한다 — 접두 일치로 본다.
        # 'NSA' 는 'SA' 로 시작하지 않으므로 여전히 걸러진다.
        require_seasonal_adjustment="SA",
        ff_title="Advance GDP q/q",
        higher_is_better=True,
        note="전기대비 연율 환산 실질 성장률. 속보치·잠정치·확정치로 세 번 발표되며 개정 폭이 크다.",
    ),
    Series(
        id="retail_sales_mom",
        name_ko="소매판매 (% MoM)",
        category="경기",
        unit="ratio",
        frequency="monthly",
        decimals=4,
        fred_id="RSAFS",
        transform="mom",
        require_seasonal_adjustment="SA",
        ff_title="Retail Sales m/m",
        higher_is_better=True,
        note="소매·요식업 매출. 미국 경제의 소비 부문을 가장 빠르게 보여준다.",
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
        # 'ISM Manufacturing Prices' 는 별칭이 아니다 — 가격지불 하위지수라
        # 헤드라인 PMI 와 다른 값이다. 별칭에 넣으면 엉뚱한 값이 들어간다.
        ff_aliases=("ISM Mfg PMI",),
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
        # ForexFactory 가 실제로 개명한 전례가 있는 항목이다.
        # 엑셀의 출처 URL(ism-non-manufacturing-pmi-176)도 옛 이름을 쓴다.
        ff_aliases=("ISM Non-Manufacturing PMI",),
        higher_is_better=True,
        note="50 기준. 매월 셋째 영업일 발표.",
    ),
    Series(
        id="uom_sentiment",
        name_ko="미시간대 소비자심리",
        category="서베이",
        unit="index",
        frequency="monthly",
        decimals=1,
        fred_id="UMCSENT",
        # 계절조정 여부를 단정할 근거가 없어 검증을 걸지 않는다.
        # 잘못 걸면 멀쩡한 계열이 실패한다 — 모르면 주장하지 않는 편이 낫다.
        require_seasonal_adjustment=None,
        # 같은 달을 두 번 발표한다: 중순 예비치, 말일 확정치.
        # 둘 다 같은 기준월이므로 확정치가 예비치를 덮어쓴다.
        ff_title="Revised UoM Consumer Sentiment",
        ff_aliases=("Prelim UoM Consumer Sentiment", "UoM Consumer Sentiment"),
        ref_lag_months=0,   # 당월 조사를 당월에 발표한다
        higher_is_better=True,
        note="가계 심리. 예비치(중순)와 확정치(말일)로 같은 달을 두 번 발표한다.",
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
        # 시장금리는 개정되지 않는다. 그래서 0 으로 둔다 —
        # 여기서 차이가 나면 개정이 아니라 진짜 문제(날짜 어긋남)라는 뜻이다.
        revision_band=0.0,
        ff_title=None,
        ref_lag_months=0,
        note="장단기 금리차. 음수는 침체 신호로 해석된다. 출처 FRED T10Y2Y. — 엑셀 주2 "
             "※ 엑셀의 주간 스냅샷은 날짜가 어긋나 있어(휴장일에도 값이 있음) "
             "겹치는 구간은 FRED 일간 값이 맞다.",
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

ALL_SERIES: list[Series] = _PRICES + _EMPLOYMENT + _ACTIVITY + _SURVEY + _FINANCE

BY_ID: dict[str, Series] = {s.id: s for s in ALL_SERIES}

CATEGORY_ORDER: list[Category] = ["물가", "고용", "경기", "서베이", "금융"]


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
    """validate.py 가 쓰는 상식적 범위. 벗어나면 단위 변환 실수를 의심한다.

    범위는 '평시 기준'이 아니라 '실제 관측된 극단값을 포함하되 단위 오류는 잡는' 선으로
    잡아야 한다. 처음에 thousands 를 ±2,000 으로 뒀더니 2020년 COVID 실측치가
    전부 경고로 잡혔다 — NFP 2020-04 는 진짜로 -20,469천명이고
    신규 실업수당은 6,137천건까지 갔다. 진짜 값이 경고를 채우면 경고를 안 보게 된다.

    ±25,000 으로 넓혀도 실제 단위 오류는 그대로 잡힌다:
      - ICSA 를 변환 없이 넣으면 187,000 -> 범위 밖 ✓
      - NFP 를 차분하지 않고 수준값으로 넣으면 ~160,000 -> 범위 밖 ✓
    """
    return {
        "ratio": (-0.5, 0.5),          # 물가·금리 비율. 1970년대 인플레도 0.15 수준
        "index": (0.0, 1000.0),
        "thousands": (-25_000.0, 25_000.0),
        "millions": (0.0, 30.0),
        "pp": (-5.0, 5.0),
        "bp": (0.0, 2000.0),           # 한국 CDS 2008년 고점이 약 700bp
    }[series.unit]
