"""
거래량 급증 + 주가 횡보 스캐너

1차: 최근 LOOKBACK_DAYS 거래일 중, 당일 거래량이 직전 AVG_WINDOW 거래일 평균의 MIN_RATIO배 이상
2차: 그날 주가 변동률(전일 종가 대비)이 ±MAX_CHANGE_PCT% 이내

캐시에는 1차 통과 이벤트를 전부 저장하고(변동률 무관), 2차 조건은 앱에서 슬라이더로 적용한다.
→ 퍼널(1차/2차 통과 수)을 보여줄 수 있고, 기준을 바꿔도 재분석이 필요 없다.

단독 실행(로컬 테스트):  python volume_spike.py
"""
import json
import os
from datetime import datetime

import pandas as pd

from config import CACHE_DIR

LOOKBACK_DAYS  = 21     # 최근 한 달 ≈ 21 거래일
AVG_WINDOW     = 20     # 비교 기준: 직전 20 거래일 평균 (당일 제외)
MIN_RATIO      = 3.0
MAX_CHANGE_PCT = 3.0    # 앱 기본값 (캐시 저장 시에는 미적용)

VOLUME_SPIKE_CACHE = os.path.join(CACHE_DIR, "volume_spike.json")


def find_spikes(df: pd.DataFrame, ticker: str, group: str) -> list[dict]:
    if df is None or len(df) < AVG_WINDOW + 2:
        return []
    df = df[["Close", "Volume"]].dropna()
    if len(df) < AVG_WINDOW + 2:
        return []

    vol   = df["Volume"].astype(float)
    close = df["Close"].astype(float)
    avg_prev = vol.shift(1).rolling(AVG_WINDOW, min_periods=AVG_WINDOW).mean()
    ratio    = vol / avg_prev
    chg_pct  = close.pct_change() * 100

    recent = df.index[-LOOKBACK_DAYS:]
    hit = (ratio.loc[recent] >= MIN_RATIO) & (avg_prev.loc[recent] > 0)
    if not hit.any():
        return []

    last_close = float(close.iloc[-1])
    last_pos   = len(df) - 1
    events = []
    for dt in hit[hit].index:
        pos = df.index.get_loc(dt)
        c   = chg_pct.loc[dt]
        if pd.isna(c):
            continue
        spike_close = float(close.loc[dt])
        events.append({
            "ticker":      ticker,
            "group":       group,
            "date":        dt.strftime("%Y-%m-%d"),
            "days_ago":    int(last_pos - pos),
            "volume":      int(vol.loc[dt]),
            "avg20":       int(avg_prev.loc[dt]),
            "ratio":       round(float(ratio.loc[dt]), 2),
            "change_pct":  round(float(c), 2),
            "spike_close": round(spike_close, 2),
            "last_close":  round(last_close, 2),
            "since_pct":   round((last_close / spike_close - 1) * 100, 2),
        })
    return events


def scan(data: dict[str, pd.DataFrame], group_of) -> list[dict]:
    """group_of: ticker -> 'S&P 500' / '외곽' / 'ETF'"""
    out: list[dict] = []
    for t, df in data.items():
        try:
            out.extend(find_spikes(df, t, group_of(t)))
        except Exception:
            pass
    return out


def save(events: list[dict], total_scanned: int, date_str: str) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    payload = {
        "date":           date_str,
        "total_scanned":  total_scanned,
        "lookback_days":  LOOKBACK_DAYS,
        "avg_window":     AVG_WINDOW,
        "min_ratio":      MIN_RATIO,
        "events":         sorted(events, key=lambda e: (e["date"], e["ratio"]), reverse=True),
    }
    with open(VOLUME_SPIKE_CACHE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    n2 = sum(1 for e in events if abs(e["change_pct"]) <= MAX_CHANGE_PCT)
    print(f"  거래량 급증: 1차 {len(events)}건 / 2차(±{MAX_CHANGE_PCT:g}%) {n2}건 → {VOLUME_SPIKE_CACHE}")


def main():
    from config import ETF_TICKERS
    from fetcher import apply_quality_filter, fetch_batch
    from universe import get_universe

    all_tickers, sp500 = get_universe()
    sp500_set, etf_set = set(sp500), set(ETF_TICKERS)
    group_of = lambda t: "ETF" if t in etf_set else ("S&P 500" if t in sp500_set else "외곽")

    tickers = sorted(set(all_tickers) | etf_set)
    events, scanned = [], 0
    for i in range(0, len(tickers), 100):
        raw = fetch_batch(tickers[i:i + 100], period="6mo", chunk_size=100)
        stocks = apply_quality_filter({t: d for t, d in raw.items() if t not in etf_set})
        etfs   = {t: d for t, d in raw.items() if t in etf_set}
        scanned += len(stocks) + len(etfs)
        events.extend(scan(stocks, group_of))
        events.extend(scan(etfs, group_of))
    save(events, scanned, datetime.now().strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main()
