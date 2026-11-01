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


# ── 도르마이어 거래량 점수 (Buff Dormeier, "Investing with Volume Analysis") ──
# 각 항목 + = 상승(매집) 신호, - = 하락(분산) 신호. 합계 -10 ~ +10
#   ① 급증일 종가 위치(CLV)       ±2  대량 거래에서 매수/매도 중 누가 흡수했나
#   ② VPCI (5/20)                ±2  거래량이 가격 추세를 확인하는가
#   ③ VWMA vs SMA, VW-MACD        ±2  거래량 가중 이평이 단순 이평 위인가
#   ④ 급증 이후 상승일/하락일 거래량 ±2  후속 거래량이 어느 쪽에 실리나
#   ⑤ 급증일 고가/저가 이탈        ±1  흡수 후 돌파(+) / 지지 붕괴(-)
#   ⑥ OBV 다이버전스 (20일)        ±1  가격은 그대로인데 OBV만 오르면 숨은 매집
VPA_LABELS = [(5, "🟢🟢 강한 매집"), (2, "🟢 매집 우세"), (-1.5, "⚪ 중립"), (-4.5, "🔴 분산 우세")]


def vpa_grade(score: float) -> str:
    for th, label in VPA_LABELS:
        if score >= th:
            return label
    return "🔴🔴 강한 분산"


def _vwma(close: pd.Series, vol: pd.Series, n: int) -> pd.Series:
    return (close * vol).rolling(n).sum() / vol.rolling(n).sum()


def _vpci(close: pd.Series, vol: pd.Series, short: int = 5, long: int = 20):
    vpc = _vwma(close, vol, long) - close.rolling(long).mean()
    vpr = _vwma(close, vol, short) / close.rolling(short).mean()
    vm  = vol.rolling(short).mean() / vol.rolling(long).mean()
    vpci = vpc * vpr * vm
    vpci_s = _vwma(vpci, vol, short)
    return vpci, vpci_s


def _market_state(df: pd.DataFrame) -> dict:
    """급증일과 무관한 현재 시점 지표 (②③⑥) — 종목당 1회 계산"""
    close, vol = df["Close"], df["Volume"]
    vpci, vpci_s = _vpci(close, vol)
    v, vs = vpci.iloc[-1], vpci_s.iloc[-1]
    if pd.isna(v):
        s_vpci = 0
    elif v > 0:
        s_vpci = 2 if (not pd.isna(vs) and v > vs) else 1
    else:
        s_vpci = -2 if (not pd.isna(vs) and v < vs) else -1

    s_vw = 0
    vw20, sma20 = _vwma(close, vol, 20).iloc[-1], close.rolling(20).mean().iloc[-1]
    if not pd.isna(vw20):
        s_vw += 1 if vw20 > sma20 else -1
    vw_macd = _vwma(close, vol, 12) - _vwma(close, vol, 26)
    hist = vw_macd - vw_macd.ewm(span=9, adjust=False).mean()
    if not pd.isna(hist.iloc[-1]):
        s_vw += 1 if hist.iloc[-1] > 0 else -1

    s_obv = 0
    if len(df) > 21:
        direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
        obv = (direction * vol).cumsum()
        obv_chg = (obv.iloc[-1] - obv.iloc[-21]) / max(vol.tail(20).mean(), 1)
        px_chg = (close.iloc[-1] / close.iloc[-21] - 1) * 100
        if obv_chg > 2 and px_chg <= 2:
            s_obv = 1
        elif obv_chg < -2 and px_chg >= -2:
            s_obv = -1
    return {"vpci": s_vpci, "vw": s_vw, "obv": s_obv}


def _event_state(df: pd.DataFrame, pos: int) -> dict:
    """급증일 기준 지표 (①④⑤)"""
    h, l, c = df["High"].iloc[pos], df["Low"].iloc[pos], df["Close"].iloc[pos]
    s_clv = 0
    if h > l:
        clv = ((c - l) - (h - c)) / (h - l)
        s_clv = 2 if clv >= 0.5 else 1 if clv >= 0.2 else -2 if clv <= -0.5 else -1 if clv <= -0.2 else 0

    s_follow = 0
    after = df.iloc[pos + 1:]
    if len(after) >= 2:
        chg = df["Close"].diff().iloc[pos + 1:]
        up_v, dn_v = after["Volume"][chg > 0].sum(), after["Volume"][chg < 0].sum()
        r = up_v / dn_v if dn_v > 0 else (9.9 if up_v > 0 else 1.0)
        s_follow = 2 if r >= 1.5 else 1 if r >= 1.1 else -2 if r <= 0.67 else -1 if r <= 0.9 else 0

    s_break = 0
    if len(after) >= 1:
        last = df["Close"].iloc[-1]
        s_break = 1 if last > h else -1 if last < l else 0
    return {"clv": s_clv, "follow": s_follow, "break": s_break}


def find_spikes(df: pd.DataFrame, ticker: str, group: str) -> list[dict]:
    if df is None or len(df) < AVG_WINDOW + 2:
        return []
    cols = [c for c in ("High", "Low", "Close", "Volume") if c in df.columns]
    df = df[cols].dropna()
    if len(df) < AVG_WINDOW + 2:
        return []
    has_hl = "High" in df.columns and "Low" in df.columns

    vol   = df["Volume"].astype(float)
    close = df["Close"].astype(float)
    avg_prev = vol.shift(1).rolling(AVG_WINDOW, min_periods=AVG_WINDOW).mean()
    ratio    = vol / avg_prev
    chg_pct  = close.pct_change() * 100

    recent = df.index[-LOOKBACK_DAYS:]
    hit = (ratio.loc[recent] >= MIN_RATIO) & (avg_prev.loc[recent] > 0)
    if not hit.any():
        return []

    mkt = _market_state(df.assign(Close=close, Volume=vol))
    last_close = float(close.iloc[-1])
    last_pos   = len(df) - 1
    events = []
    for dt in hit[hit].index:
        pos = df.index.get_loc(dt)
        c   = chg_pct.loc[dt]
        if pd.isna(c):
            continue
        ev_s = _event_state(df, pos) if has_hl else {"clv": 0, "follow": 0, "break": 0}
        parts = {**ev_s, **mkt}
        vpa = sum(parts.values())
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
            "vpa_score":   int(vpa),
            "vpa_grade":   vpa_grade(vpa),
            "vpa_parts":   parts,
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


def attach_scores(events: list[dict], tech: dict[str, dict], fund: dict[str, dict]) -> None:
    """기술적 점수(scorer.score_all)와 펀더멘털 점수(fundamentals)를 이벤트에 붙인다."""
    for e in events:
        t = tech.get(e["ticker"], {})
        f = fund.get(e["ticker"], {})
        e["tech_score"]  = t.get("score")
        e["long_score"]  = t.get("long_score")
        e["short_score"] = t.get("short_score")
        e["fund_score"]  = f.get("fundamental_score") if f.get("has_fundamental_data", True) else None
        e["fund_grade"]  = f.get("fundamental_grade")


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
    from fundamentals import fetch_fundamental_data
    from scorer import score_all
    spiked = {e["ticker"] for e in events}
    raw = fetch_batch(sorted(spiked), period="1y", chunk_size=100)
    tech: dict[str, dict] = {}
    for asset, subset in (("STOCK", {t: d for t, d in raw.items() if t not in etf_set}),
                          ("ETF",   {t: d for t, d in raw.items() if t in etf_set})):
        tech.update({r["ticker"]: r for r in score_all(subset, asset)})
    fund = fetch_fundamental_data(sorted(spiked), asset_types={t: ("ETF" if t in etf_set else "STOCK") for t in spiked})
    attach_scores(events, tech, fund)
    save(events, scanned, datetime.now().strftime("%Y-%m-%d"))


if __name__ == "__main__":
    main()
