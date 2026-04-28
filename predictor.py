"""
기술적 예상 범위 계산 (ATR 기반)
단기(1주) 및 중기(1~3개월) 가격 목표 산출
"""
import numpy as np
import pandas as pd


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
    ATR 기반 단기/중기 예상 범위 반환.
    signals: extract_signals() 반환값
    """
    c        = signals.get("close")
    ma_s     = signals.get("ma_s")
    ma_m     = signals.get("ma_m")
    ma_l     = signals.get("ma_l")
    vp_zones = signals.get("vp_zones", [])

    if c is None or c <= 0:
        return {}

    atr = _atr(df)
    if atr <= 0:
        return {}

    # ── 단기 (1주) ATR 범위 ────────────────────────────────────────────
    s_lo_68 = round(c - atr,     2)
    s_hi_68 = round(c + atr,     2)
    s_lo_95 = round(c - 2 * atr, 2)
    s_hi_95 = round(c + 2 * atr, 2)

    # 단기 저항: max(20MA + ATR,  현재가 위 매물대 상단,  최근 5일 고점)
    r5_high = float(df["High"].tail(5).max())
    resist  = [r5_high]
    if ma_s is not None:
        resist.append(ma_s + atr)
    vp_above = [z[1] for z in vp_zones if z[1] > c]
    if vp_above:
        resist.append(min(vp_above))
    short_resistance = round(max(resist), 2)

    # 단기 지지: min(20MA - ATR,  현재가 아래 매물대 하단,  최근 5일 저점)
    r5_low  = float(df["Low"].tail(5).min())
    support = [r5_low]
    if ma_s is not None:
        support.append(ma_s - atr)
    vp_below = [z[0] for z in vp_zones if z[0] < c]
    if vp_below:
        support.append(max(vp_below))
    short_support = round(min(support), 2)

    # ── 중기 (1~3개월) 목표 ──────────────────────────────────────────
    # 상승 목표: 60MA × 1.15  또는  현재가 위 매물대 상단 중 큰 값
    mid_upside = (ma_m * 1.15) if ma_m else None
    vp_up_cands = [z[1] for z in vp_zones if z[1] > c * 1.02]
    if vp_up_cands:
        vp_up = min(vp_up_cands) * 1.05
        if mid_upside is None or vp_up > mid_upside:
            mid_upside = vp_up

    # 하방 위험: max(60MA × 0.85,  200MA)
    down_cands = []
    if ma_m: down_cands.append(ma_m * 0.85)
    if ma_l: down_cands.append(ma_l)
    mid_downside = max(down_cands) if down_cands else None

    # R/R 비율
    rr = None
    if (mid_upside and mid_downside
            and mid_downside < c < mid_upside):
        rr = round((mid_upside - c) / (c - mid_downside), 1)

    return {
        "atr":             round(atr, 2),
        "short_lo_68":     s_lo_68,
        "short_hi_68":     s_hi_68,
        "short_lo_95":     s_lo_95,
        "short_hi_95":     s_hi_95,
        "short_resistance": short_resistance,
        "short_support":   short_support,
        "mid_upside":      round(mid_upside, 2)   if mid_upside   else None,
        "mid_downside":    round(mid_downside, 2) if mid_downside else None,
        "rr":              rr,
    }
