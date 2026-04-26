"""
기술적 지표 계산 (외부 라이브러리 없이 직접 구현)
"""
import numpy as np
import pandas as pd

from config import RSI_PERIOD, MACD_FAST, MACD_SLOW, MACD_SIGNAL, VOLUME_PERIOD, LOOKBACK


def _rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _macd(close: pd.Series):
    ema_f = close.ewm(span=MACD_FAST, adjust=False).mean()
    ema_s = close.ewm(span=MACD_SLOW, adjust=False).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=MACD_SIGNAL, adjust=False).mean()
    return macd, sig


def _val(series: pd.Series, idx: int = -1):
    """iloc[idx] 값을 float 으로 반환, NaN 이면 None"""
    v = series.iloc[idx]
    return float(v) if pd.notna(v) else None


def calc_volume_profile(
    df: pd.DataFrame, days: int = 90, n_bins: int = 20, top_n: int = 5
) -> list[tuple[float, float]]:
    """
    최근 90영업일 Volume Profile → 거래량 상위 top_n 구간의 (low, high) 반환.
    각 봉의 거래량을 High-Low 범위 기준으로 해당 구간에 비례 배분.
    """
    recent = df.tail(days)
    lo_all = float(recent["Low"].min())
    hi_all = float(recent["High"].max())
    if hi_all <= lo_all:
        return []

    bin_size = (hi_all - lo_all) / n_bins
    bin_vols = np.zeros(n_bins)

    for _, row in recent.iterrows():
        lo, hi, vol = float(row["Low"]), float(row["High"]), float(row["Volume"])
        if hi <= lo or vol <= 0 or np.isnan(vol):
            continue
        span = hi - lo
        for i in range(n_bins):
            b_lo = lo_all + i * bin_size
            b_hi = b_lo + bin_size
            overlap = min(hi, b_hi) - max(lo, b_lo)
            if overlap > 0:
                bin_vols[i] += vol * overlap / span

    top_idx = np.argsort(bin_vols)[::-1][:top_n]
    return [
        (round(lo_all + i * bin_size, 4), round(lo_all + (i + 1) * bin_size, 4))
        for i in top_idx
    ]


def extract_signals(df: pd.DataFrame) -> dict | None:
    """
    OHLCV DataFrame → 점수 계산에 필요한 당일/전일 값 dict 반환.
    데이터가 200봉 미만이면 None 반환.
    """
    if len(df) < 200:
        return None

    close = df["Close"]
    volume = df["Volume"]

    ma20 = close.rolling(20).mean()
    ma60 = close.rolling(60).mean()
    ma200 = close.rolling(200).mean()
    rsi = _rsi(close)
    macd, macd_sig = _macd(close)
    vol_avg = volume.rolling(VOLUME_PERIOD).mean()
    high_252 = close.rolling(LOOKBACK).max()
    low_252 = close.rolling(LOOKBACK).min()

    return {
        "close":          _val(close),
        "prev_close":     _val(close,    -2),
        "volume":         _val(volume),
        "vol_avg":        _val(vol_avg),
        "ma20":           _val(ma20),
        "ma60":           _val(ma60),
        "ma200":          _val(ma200),
        "ma20_prev":      _val(ma20,     -2),
        "ma60_prev":      _val(ma60,     -2),
        "ma200_prev":     _val(ma200,    -2),
        "rsi":            _val(rsi),
        "macd":           _val(macd),
        "macd_sig":       _val(macd_sig),
        "macd_prev":      _val(macd,     -2),
        "macd_sig_prev":  _val(macd_sig, -2),
        "high_252":       _val(high_252),
        "low_252":        _val(low_252),
        "vp_zones":       calc_volume_profile(df),
    }
