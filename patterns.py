"""
캔들 패턴 감지 — 직접 구현
각 함수: (detected: bool, confidence: float) 반환
"""
import numpy as np
import pandas as pd


def _atr14(df: pd.DataFrame) -> float:
    n = min(14, len(df) - 1)
    if n < 1:
        return float((df["High"] - df["Low"]).mean()) or 1e-8
    h, l, pc = df["High"].iloc[-n:], df["Low"].iloc[-n:], df["Close"].shift(1).iloc[-n:]
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return float(tr.mean()) or 1e-8


# ── 매수 패턴 ──────────────────────────────────────────────────────────

def detect_morning_star(df: pd.DataFrame) -> tuple[bool, float]:
    """샛별 (Morning Star) — 3봉 바닥 반전"""
    if len(df) < 3:
        return False, 0.0
    o1,c1 = df["Open"].iloc[-3], df["Close"].iloc[-3]
    o2,c2 = df["Open"].iloc[-2], df["Close"].iloc[-2]
    o3,c3 = df["Open"].iloc[-1], df["Close"].iloc[-1]
    atr   = _atr14(df)
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    if not (c1 < o1 and body1 > atr * 0.5):       return False, 0.0
    if not (body2 < body1 * 0.3 and max(o2,c2) < c1): return False, 0.0
    if not (c3 > o3 and c3 > (o1 + c1) / 2):      return False, 0.0
    recovery = (c3 - c1) / body1 if body1 > 0 else 0
    return True, round(min(1.0, 0.70 + recovery * 0.15), 2)


def detect_bullish_engulfing(df: pd.DataFrame) -> tuple[bool, float]:
    """양포형 (Bullish Engulfing) — 2봉"""
    if len(df) < 2:
        return False, 0.0
    o1,c1 = df["Open"].iloc[-2], df["Close"].iloc[-2]
    o2,c2 = df["Open"].iloc[-1], df["Close"].iloc[-1]
    if not (c1 < o1 and c2 > o2):          return False, 0.0
    if not (o2 <= c1 and c2 >= o1):        return False, 0.0
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    ratio = body2 / body1 if body1 > 1e-8 else 1.0
    return True, round(min(1.0, 0.65 + min(ratio - 1, 0.5) * 0.5), 2)


def detect_bullish_pin_bar(df: pd.DataFrame) -> tuple[bool, float]:
    """해머 / 핀바 (Bullish Pin Bar)"""
    if len(df) < 1:
        return False, 0.0
    o,c,h,l = df["Open"].iloc[-1], df["Close"].iloc[-1], df["High"].iloc[-1], df["Low"].iloc[-1]
    body  = max(abs(c - o), 1e-8)
    lower = min(o, c) - l
    upper = h - max(o, c)
    if not (lower >= body * 2.0 and upper <= body * 0.3):
        return False, 0.0
    return True, round(min(1.0, 0.60 + (lower / body - 2) * 0.08), 2)


def detect_three_white_soldiers(df: pd.DataFrame) -> tuple[bool, float]:
    """적삼병 (Three White Soldiers) — 3 연속 양봉"""
    if len(df) < 3:
        return False, 0.0
    opens  = [df["Open"].iloc[-3+i]  for i in range(3)]
    closes = [df["Close"].iloc[-3+i] for i in range(3)]
    if any(closes[i] <= opens[i] for i in range(3)):     return False, 0.0
    if not (closes[1] > closes[0] and closes[2] > closes[1]): return False, 0.0
    for i in range(1, 3):
        lo = min(opens[i-1], closes[i-1])
        hi = max(opens[i-1], closes[i-1])
        if not (lo <= opens[i] <= hi):                    return False, 0.0
    return True, 0.85


def detect_tweezer_bottom(df: pd.DataFrame) -> tuple[bool, float]:
    """저점쌍봉 (Tweezer Bottom)"""
    if len(df) < 2:
        return False, 0.0
    l1 = df["Low"].iloc[-2]; l2 = df["Low"].iloc[-1]
    c1 = df["Close"].iloc[-2]; o2 = df["Open"].iloc[-1]; c2 = df["Close"].iloc[-1]
    if abs(l1 - l2) / max(l1, 1e-8) > 0.005:  return False, 0.0
    if not (c1 < df["Open"].iloc[-2] and c2 > o2): return False, 0.0
    return True, 0.65


# ── 매도 패턴 ──────────────────────────────────────────────────────────

def detect_evening_star(df: pd.DataFrame) -> tuple[bool, float]:
    """저녁별 (Evening Star) — 3봉 천장 반전"""
    if len(df) < 3:
        return False, 0.0
    o1,c1 = df["Open"].iloc[-3], df["Close"].iloc[-3]
    o2,c2 = df["Open"].iloc[-2], df["Close"].iloc[-2]
    o3,c3 = df["Open"].iloc[-1], df["Close"].iloc[-1]
    atr   = _atr14(df)
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    if not (c1 > o1 and body1 > atr * 0.5):         return False, 0.0
    if not (body2 < body1 * 0.3 and min(o2,c2) > c1): return False, 0.0
    if not (c3 < o3 and c3 < (o1 + c1) / 2):        return False, 0.0
    drop = (c1 - c3) / body1 if body1 > 0 else 0
    return True, round(min(1.0, 0.70 + drop * 0.15), 2)


def detect_bearish_engulfing(df: pd.DataFrame) -> tuple[bool, float]:
    """음포형 (Bearish Engulfing) — 2봉"""
    if len(df) < 2:
        return False, 0.0
    o1,c1 = df["Open"].iloc[-2], df["Close"].iloc[-2]
    o2,c2 = df["Open"].iloc[-1], df["Close"].iloc[-1]
    if not (c1 > o1 and c2 < o2):          return False, 0.0
    if not (o2 >= c1 and c2 <= o1):        return False, 0.0
    body1 = abs(c1 - o1)
    body2 = abs(c2 - o2)
    ratio = body2 / body1 if body1 > 1e-8 else 1.0
    return True, round(min(1.0, 0.65 + min(ratio - 1, 0.5) * 0.5), 2)


def detect_shooting_star(df: pd.DataFrame) -> tuple[bool, float]:
    """별똥별 (Shooting Star) — 상단 긴 꼬리"""
    if len(df) < 1:
        return False, 0.0
    o,c,h,l = df["Open"].iloc[-1], df["Close"].iloc[-1], df["High"].iloc[-1], df["Low"].iloc[-1]
    body  = max(abs(c - o), 1e-8)
    upper = h - max(o, c)
    lower = min(o, c) - l
    if not (upper >= body * 2.0 and lower <= body * 0.3):
        return False, 0.0
    return True, round(min(1.0, 0.60 + (upper / body - 2) * 0.08), 2)


def detect_three_black_crows(df: pd.DataFrame) -> tuple[bool, float]:
    """흑삼병 (Three Black Crows) — 3 연속 음봉"""
    if len(df) < 3:
        return False, 0.0
    opens  = [df["Open"].iloc[-3+i]  for i in range(3)]
    closes = [df["Close"].iloc[-3+i] for i in range(3)]
    if any(closes[i] >= opens[i] for i in range(3)):      return False, 0.0
    if not (closes[1] < closes[0] and closes[2] < closes[1]): return False, 0.0
    for i in range(1, 3):
        lo = min(opens[i-1], closes[i-1])
        hi = max(opens[i-1], closes[i-1])
        if not (lo <= opens[i] <= hi):                     return False, 0.0
    return True, 0.85


def detect_tweezer_top(df: pd.DataFrame) -> tuple[bool, float]:
    """고점쌍봉 (Tweezer Top)"""
    if len(df) < 2:
        return False, 0.0
    h1 = df["High"].iloc[-2]; h2 = df["High"].iloc[-1]
    c1 = df["Close"].iloc[-2]; o2 = df["Open"].iloc[-1]; c2 = df["Close"].iloc[-1]
    if abs(h1 - h2) / max(h1, 1e-8) > 0.005:  return False, 0.0
    if not (c1 > df["Open"].iloc[-2] and c2 < o2): return False, 0.0
    return True, 0.65


def detect_dark_cloud_cover(df: pd.DataFrame) -> tuple[bool, float]:
    """다크클라우드 (Dark Cloud Cover) — 2봉"""
    if len(df) < 2:
        return False, 0.0
    o1,c1 = df["Open"].iloc[-2], df["Close"].iloc[-2]
    o2,c2 = df["Open"].iloc[-1], df["Close"].iloc[-1]
    if not (c1 > o1):                        return False, 0.0
    body1 = abs(c1 - o1)
    mid1  = o1 + body1 * 0.5
    if not (o2 > c1 and c2 < mid1 and c2 > o1): return False, 0.0
    pen = (c1 - c2) / body1 if body1 > 0 else 0
    return True, round(min(1.0, 0.65 + pen * 0.3), 2)


# ── 통합 스캐너 ────────────────────────────────────────────────────────

def scan_candle_patterns(df: pd.DataFrame) -> dict[str, tuple[bool, float]]:
    """모든 캔들 패턴 스캔. 반환: {name: (detected, confidence)}"""
    if len(df) < 3:
        return {}
    try:
        return {
            "morning_star":         detect_morning_star(df),
            "bullish_engulfing":    detect_bullish_engulfing(df),
            "bullish_pin_bar":      detect_bullish_pin_bar(df),
            "three_white_soldiers": detect_three_white_soldiers(df),
            "tweezer_bottom":       detect_tweezer_bottom(df),
            "evening_star":         detect_evening_star(df),
            "bearish_engulfing":    detect_bearish_engulfing(df),
            "shooting_star":        detect_shooting_star(df),
            "three_black_crows":    detect_three_black_crows(df),
            "tweezer_top":          detect_tweezer_top(df),
            "dark_cloud_cover":     detect_dark_cloud_cover(df),
        }
    except Exception:
        return {}
