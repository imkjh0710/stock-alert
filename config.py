import json
import os

# ── ETF 유니버스 ──────────────────────────────────────────────────────
ETF_TICKERS = [
    # 시장지수
    "SPY", "QQQ", "DIA", "IWM", "VTI", "VOO", "IVV", "VEA", "VWO", "EFA",
    # 섹터 SPDR
    "XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB", "XLRE", "XLC",
    # 테마
    "ARKK", "SMH", "SOXX", "IBB", "XBI", "GDX", "JETS", "KWEB", "CIBR", "ICLN",
    "LIT", "URA", "DRIV", "ROBO",
    # 채권
    "TLT", "IEF", "AGG", "BND", "HYG", "LQD", "TIP", "MBB", "EMB", "SHY",
    # 한국 인기 (레버리지 포함)
    "TQQQ", "SOXL", "TSLL", "NVDL", "NVDU", "FNGU", "BULZ", "BITX", "MSTU", "BITO",
    # 원자재/통화
    "GLD", "SLV", "IAU", "USO", "UNG", "DBC", "UUP", "FXY", "FXE",
]

# ── 데이터 소스 ───────────────────────────────────────────────────────
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
SP600_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
IWV_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf"
    "/1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund"
)

# ── 고정 품질 필터 ────────────────────────────────────────────────────
MIN_PRICE     = 5.0
MIN_VOLUME    = 500_000
VOLUME_PERIOD = 20
LOOKBACK      = 252

# ── 캐시 ─────────────────────────────────────────────────────────────
CACHE_DIR             = "cache"
UNIVERSE_CACHE        = os.path.join(CACHE_DIR, "universe.json")
UNIVERSE_REFRESH_DAYS = 7

# ── settings.json에서 읽어오는 사용자 설정 ────────────────────────────
_DEFAULTS = {
    "rsi_overbought":        70,
    "rsi_overbought_strong": 75,
    "rsi_oversold":          30,
    "rsi_oversold_strong":   25,
    "macd_fast":             12,
    "macd_slow":             26,
    "macd_signal":            9,
    "ma_short":              20,
    "ma_mid":                60,
    "ma_long":              200,
    "volume_t1":              2,
    "volume_t2":              3,
    "volume_t3":              5,
    "vp_window":             90,
    # ── PER/PBR 밸류에이션 ───────────────────────────────────────────
    "per_cheap_strong":      15,   # ≤ → +2 (저PER 강한)
    "per_cheap":             25,   # ≤ → +1 (저PER)
    "per_pricey":            50,   # >  → -1 (고PER)
    "per_pricey_strong":    100,   # >  → -2 (고PER 강한)
    "pbr_cheap":              1,   # <  → +1 (저PBR)
    "pbr_pricey":             5,   # >  → -1 (고PBR)
    "pbr_pricey_strong":     15,   # >  → -2 (고PBR 강한)
}


def _load() -> dict:
    d = _DEFAULTS.copy()
    try:
        if os.path.exists("settings.json"):
            with open("settings.json", encoding="utf-8") as f:
                d.update(json.load(f))
    except Exception:
        pass
    return d


_s = _load()

RSI_PERIOD = 14
MACD_FAST   = int(_s["macd_fast"])
MACD_SLOW   = int(_s["macd_slow"])
MACD_SIGNAL = int(_s["macd_signal"])
MA_SHORT    = int(_s["ma_short"])
MA_MID      = int(_s["ma_mid"])
MA_LONG     = int(_s["ma_long"])
VP_WINDOW   = int(_s["vp_window"])

RSI_OVERBOUGHT        = float(_s["rsi_overbought"])
RSI_OVERBOUGHT_STRONG = float(_s["rsi_overbought_strong"])
RSI_OVERSOLD          = float(_s["rsi_oversold"])
RSI_OVERSOLD_STRONG   = float(_s["rsi_oversold_strong"])

PER_CHEAP_STRONG  = int(_s.get("per_cheap_strong",     15))
PER_CHEAP         = int(_s.get("per_cheap",             25))
PER_PRICEY        = int(_s.get("per_pricey",            50))
PER_PRICEY_STRONG = int(_s.get("per_pricey_strong",    100))
PBR_CHEAP         = int(_s.get("pbr_cheap",              1))
PBR_PRICEY        = int(_s.get("pbr_pricey",             5))
PBR_PRICEY_STRONG = int(_s.get("pbr_pricey_strong",     15))

# 내림차순 정렬 (가장 높은 배수부터 검사)
_thresholds = sorted(
    [int(_s["volume_t1"]), int(_s["volume_t2"]), int(_s["volume_t3"])],
    reverse=True,
)
VOLUME_THRESHOLDS = _thresholds          # e.g. [5, 3, 2]
VOLUME_POINTS     = [4, 3, 2]           # 각 배수에 대응하는 점수
