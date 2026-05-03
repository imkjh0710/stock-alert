"""
기술적 예상 범위 계산 (ATR 기반)
단기(20일) / 중기(60일) / 장기(90일) 예측 주가 범위 산출
ATR × √N (랜덤워크 스케일링)
"""
import math
import pandas as pd

# √N 스케일 팩터
_F20 = round(math.sqrt(20), 1)  # ≈ 4.5
_F60 = round(math.sqrt(60), 1)  # ≈ 7.7
_F90 = round(math.sqrt(90), 1)  # ≈ 9.5


def _atr(df: pd.DataFrame, period: int = 14) -> float:
    high       = df["High"]
    low        = df["Low"]
    prev_close = df["Close"].shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    val = tr.ewm(span=period, adjust=False).mean().iloc[-1]
    return float(val) if pd.notna(val) and val > 0 else 0.0


def predict_ranges(df: pd.DataFrame, signals: dict) -> dict:
    """
    ATR × √N 기반 20/60/90일 예상 가격 범위 반환.
    signals: extract_signals() 반환값
    """
    c = signals.get("close")
    if c is None or c <= 0:
        return {}

    atr = _atr(df)
    if atr <= 0:
        return {}

    # ── 20일 (단기) ────────────────────────────────────────────────────
    pred_20_lo = round(c - atr * _F20, 2)
    pred_20_hi = round(c + atr * _F20, 2)

    # ── 60일 (중기) ────────────────────────────────────────────────────
    pred_60_lo = round(c - atr * _F60, 2)
    pred_60_hi = round(c + atr * _F60, 2)

    # ── 90일 (장기) ────────────────────────────────────────────────────
    pred_90_lo = round(c - atr * _F90, 2)
    pred_90_hi = round(c + atr * _F90, 2)

    # R/R 비율 (60일 기준)
    rr = None
    ma_m = signals.get("ma_m")
    if ma_m and pred_60_lo < c < pred_60_hi:
        up   = pred_60_hi - c
        down = c - pred_60_lo
        if down > 0:
            rr = round(up / down, 1)

    return {
        "atr":        round(atr, 2),
        "pred_20_lo": pred_20_lo,
        "pred_20_hi": pred_20_hi,
        "pred_60_lo": pred_60_lo,
        "pred_60_hi": pred_60_hi,
        "pred_90_lo": pred_90_lo,
        "pred_90_hi": pred_90_hi,
        "rr":         rr,
    }
