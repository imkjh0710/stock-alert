import os

# 기술적 지표 파라미터
RSI_PERIOD = 14
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
MA_PERIODS = [20, 60, 200]
VOLUME_PERIOD = 20
LOOKBACK = 252  # 52주

# 품질 필터
MIN_PRICE = 5.0
MIN_VOLUME = 500_000
MIN_MARKET_CAP = 300_000_000

# 캐시
CACHE_DIR = "cache"
UNIVERSE_CACHE = os.path.join(CACHE_DIR, "universe.json")
UNIVERSE_REFRESH_DAYS = 7

# 데이터 소스 URL
SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"
SP600_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_600_companies"
IWV_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf"
    "/1467271812596.ajax?fileType=csv&fileName=IWV_holdings&dataType=fund"
)
