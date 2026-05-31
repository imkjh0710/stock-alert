"""
차트 패턴 감지 — scipy.signal.find_peaks 사용 (매수/관망/매도 분류 포함)
각 함수: (detected: bool, confidence: float) 반환
"""
import numpy as np
import pandas as pd

try:
    from scipy.signal import find_peaks as _find_peaks
    _SCIPY = True
except ImportError:
    _SCIPY = False


def _peaks(series: pd.Series, distance: int = 5) -> np.ndarray:
    if not _SCIPY:
        return np.array([], dtype=int)
    idx, _ = _find_peaks(series.values, distance=distance)
    return idx


def _troughs(series: pd.Series, distance: int = 5) -> np.ndarray:
    if not _SCIPY:
        return np.array([], dtype=int)
    idx, _ = _find_peaks(-series.values, distance=distance)
    return idx


def detect_double_bottom(df: pd.DataFrame, window: int = 60) -> tuple[bool, float]:
    """더블 바텀 — 비슷한 저점 2개 + 사이 반등 5%+"""
    sub   = df.tail(min(window, len(df)))
    lows  = sub["Low"].values
    trgs  = _troughs(sub["Low"], distance=5)
    if len(trgs) < 2:
        return False, 0.0
    t1, t2 = trgs[-2], trgs[-1]
    p1, p2 = lows[t1], lows[t2]
    if abs(p1 - p2) / max(p1, 1e-8) > 0.02:         return False, 0.0
    mid_hi = sub["High"].values[t1:t2+1].max() if t2 > t1 else 0
    if mid_hi < p1 * 1.05:                            return False, 0.0
    curr = sub["Close"].values[-1]
    if curr < (p1 + p2) / 2:                          return False, 0.0
    conf = round(min(1.0, 0.70 + (1 - abs(p1-p2)/max(p1,1e-8)/0.02)*0.25), 2)
    return True, conf


def detect_double_top(df: pd.DataFrame, window: int = 60) -> tuple[bool, float]:
    """더블 탑 — 비슷한 고점 2개 + 사이 하락 5%+"""
    sub   = df.tail(min(window, len(df)))
    highs = sub["High"].values
    pks   = _peaks(sub["High"], distance=5)
    if len(pks) < 2:
        return False, 0.0
    p1, p2 = pks[-2], pks[-1]
    h1, h2 = highs[p1], highs[p2]
    if abs(h1 - h2) / max(h1, 1e-8) > 0.02:          return False, 0.0
    mid_lo = sub["Low"].values[p1:p2+1].min() if p2 > p1 else 0
    if mid_lo > h1 * 0.95:                             return False, 0.0
    curr = sub["Close"].values[-1]
    if curr > (h1 + h2) / 2:                           return False, 0.0
    conf = round(min(1.0, 0.70 + (1 - abs(h1-h2)/max(h1,1e-8)/0.02)*0.25), 2)
    return True, conf


def detect_head_and_shoulders(df: pd.DataFrame, window: int = 60) -> tuple[bool, float]:
    """삼존 (H&S) — 3고점, 가운데 최고, 넥라인 이탈"""
    sub  = df.tail(min(window, len(df)))
    pks  = _peaks(sub["High"], distance=5)
    if len(pks) < 3:
        return False, 0.0
    ls, hd, rs = pks[-3], pks[-2], pks[-1]
    hi = sub["High"].values
    h_ls, h_hd, h_rs = hi[ls], hi[hd], hi[rs]
    if not (h_hd > h_ls and h_hd > h_rs):             return False, 0.0
    if abs(h_ls - h_rs) / max(h_hd, 1e-8) > 0.06:    return False, 0.0
    lo = sub["Low"].values
    neck = (lo[ls:hd+1].min() + lo[hd:rs+1].min()) / 2
    curr = sub["Close"].values[-1]
    if curr > neck * 1.01:                             return False, 0.0
    return True, 0.80


def detect_inverse_head_and_shoulders(df: pd.DataFrame, window: int = 60) -> tuple[bool, float]:
    """역삼존 (Inv H&S) — 3저점, 가운데 최저, 넥라인 돌파"""
    sub  = df.tail(min(window, len(df)))
    trgs = _troughs(sub["Low"], distance=5)
    if len(trgs) < 3:
        return False, 0.0
    ls, hd, rs = trgs[-3], trgs[-2], trgs[-1]
    lo = sub["Low"].values
    l_ls, l_hd, l_rs = lo[ls], lo[hd], lo[rs]
    if not (l_hd < l_ls and l_hd < l_rs):             return False, 0.0
    if abs(l_ls - l_rs) / max(l_ls, 1e-8) > 0.06:    return False, 0.0
    hi = sub["High"].values
    neck = (hi[ls:hd+1].max() + hi[hd:rs+1].max()) / 2
    curr = sub["Close"].values[-1]
    if curr < neck * 0.99:                             return False, 0.0
    return True, 0.80


def detect_ascending_triangle(df: pd.DataFrame, window: int = 30) -> tuple[bool, float]:
    """상승삼각형 — 수평 저항 + 상승 지지 + 돌파"""
    sub  = df.tail(min(window, len(df)))
    pks  = _peaks(sub["High"], distance=3)
    trgs = _troughs(sub["Low"], distance=3)
    if len(pks) < 2 or len(trgs) < 2:                 return False, 0.0
    rec_hi = sub["High"].values[pks[-3:]] if len(pks) >= 3 else sub["High"].values[pks]
    if rec_hi.max() - rec_hi.min() > rec_hi.mean() * 0.015: return False, 0.0
    rec_lo = sub["Low"].values[trgs[-2:]]
    if rec_lo[-1] <= rec_lo[0]:                        return False, 0.0
    resistance = rec_hi.mean()
    curr = sub["Close"].values[-1]
    if curr < resistance * 1.003:                      return False, 0.0
    return True, 0.75


def detect_descending_triangle(df: pd.DataFrame, window: int = 30) -> tuple[bool, float]:
    """하강삼각형 — 수평 지지 + 하강 저항 + 이탈"""
    sub  = df.tail(min(window, len(df)))
    pks  = _peaks(sub["High"], distance=3)
    trgs = _troughs(sub["Low"], distance=3)
    if len(pks) < 2 or len(trgs) < 2:                 return False, 0.0
    rec_lo = sub["Low"].values[trgs[-3:]] if len(trgs) >= 3 else sub["Low"].values[trgs]
    if rec_lo.max() - rec_lo.min() > rec_lo.mean() * 0.015: return False, 0.0
    rec_hi = sub["High"].values[pks[-2:]]
    if rec_hi[-1] >= rec_hi[0]:                        return False, 0.0
    support = rec_lo.mean()
    curr = sub["Close"].values[-1]
    if curr > support * 0.997:                         return False, 0.0
    return True, 0.75


def detect_rising_flag(df: pd.DataFrame, window: int = 20) -> tuple[bool, float]:
    """상승 플래그 — 급등 후 완만한 하향 채널 (bullish continuation)"""
    if len(df) < window + 5:
        return False, 0.0
    pre  = df.iloc[-(window+5):-(window)]
    post = df.tail(window)
    pre_gain = (pre["Close"].iloc[-1] - pre["Close"].iloc[0]) / max(pre["Close"].iloc[0], 1e-8)
    if pre_gain < 0.05:                                return False, 0.0
    post_chg = (post["Close"].iloc[-1] - post["Close"].iloc[0]) / max(post["Close"].iloc[0], 1e-8)
    if not (-0.08 < post_chg < 0):                     return False, 0.0
    return True, 0.70


def detect_falling_flag(df: pd.DataFrame, window: int = 20) -> tuple[bool, float]:
    """하강 플래그 — 급락 후 완만한 상향 채널 (bearish continuation)"""
    if len(df) < window + 5:
        return False, 0.0
    pre  = df.iloc[-(window+5):-(window)]
    post = df.tail(window)
    pre_loss = (pre["Close"].iloc[0] - pre["Close"].iloc[-1]) / max(pre["Close"].iloc[0], 1e-8)
    if pre_loss < 0.05:                                return False, 0.0
    post_chg = (post["Close"].iloc[-1] - post["Close"].iloc[0]) / max(post["Close"].iloc[0], 1e-8)
    if not (0 < post_chg < 0.08):                      return False, 0.0
    return True, 0.70


def detect_triple_top(df: pd.DataFrame, window: int = 80) -> tuple[bool, float]:
    """삼중천정 — 비슷한 고점 3개 + 현재가 하락 (강한 매도 신호)"""
    sub   = df.tail(min(window, len(df)))
    highs = sub["High"].values
    pks   = _peaks(sub["High"], distance=5)
    if len(pks) < 3:
        return False, 0.0
    a, b, c = pks[-3], pks[-2], pks[-1]
    h = highs[[a, b, c]]
    if (h.max() - h.min()) / max(h.mean(), 1e-8) > 0.03:   return False, 0.0
    curr = sub["Close"].values[-1]
    if curr > h.mean():                                     return False, 0.0
    conf = round(min(1.0, 0.75 + (1 - (h.max()-h.min())/max(h.mean(),1e-8)/0.03)*0.20), 2)
    return True, conf


def detect_triple_bottom(df: pd.DataFrame, window: int = 80) -> tuple[bool, float]:
    """삼중바닥 — 비슷한 저점 3개 + 현재가 반등 (강한 매수 신호)"""
    sub  = df.tail(min(window, len(df)))
    lows = sub["Low"].values
    trgs = _troughs(sub["Low"], distance=5)
    if len(trgs) < 3:
        return False, 0.0
    a, b, c = trgs[-3], trgs[-2], trgs[-1]
    l = lows[[a, b, c]]
    if (l.max() - l.min()) / max(l.mean(), 1e-8) > 0.03:   return False, 0.0
    curr = sub["Close"].values[-1]
    if curr < l.mean():                                     return False, 0.0
    conf = round(min(1.0, 0.75 + (1 - (l.max()-l.min())/max(l.mean(),1e-8)/0.03)*0.20), 2)
    return True, conf


def detect_rising_wedge(df: pd.DataFrame, window: int = 30) -> tuple[bool, float]:
    """상승쐐기 — 고점·저점 모두 상승하나 저점이 더 가파르게 수렴 (약세 반전)"""
    if len(df) < window:
        return False, 0.0
    post = df.tail(window)
    hi, lo = post["High"].values, post["Low"].values
    x = np.arange(len(hi))
    hi_slope = float(np.polyfit(x, hi, 1)[0])
    lo_slope = float(np.polyfit(x, lo, 1)[0])
    if not (hi_slope > 0 and lo_slope > 0):                 return False, 0.0
    if lo_slope <= hi_slope:                                return False, 0.0   # 저점이 더 가파름 = 수렴
    width_start = hi[0] - lo[0]
    width_end   = hi[-1] - lo[-1]
    if width_start <= 0 or width_end >= width_start * 0.75: return False, 0.0
    return True, 0.72


def detect_falling_wedge(df: pd.DataFrame, window: int = 30) -> tuple[bool, float]:
    """하강쐐기 — 고점·저점 모두 하락하나 고점이 더 가파르게 수렴 (강세 반전)"""
    if len(df) < window:
        return False, 0.0
    post = df.tail(window)
    hi, lo = post["High"].values, post["Low"].values
    x = np.arange(len(hi))
    hi_slope = float(np.polyfit(x, hi, 1)[0])
    lo_slope = float(np.polyfit(x, lo, 1)[0])
    if not (hi_slope < 0 and lo_slope < 0):                 return False, 0.0
    if hi_slope >= lo_slope:                                return False, 0.0   # 고점이 더 가파름 = 수렴
    width_start = hi[0] - lo[0]
    width_end   = hi[-1] - lo[-1]
    if width_start <= 0 or width_end >= width_start * 0.75: return False, 0.0
    return True, 0.72


def detect_symmetric_triangle(df: pd.DataFrame, window: int = 30) -> tuple[bool, float]:
    """대칭삼각형 수렴 — 고점 하락 + 저점 상승, 돌파 전 (관망)"""
    if len(df) < window:
        return False, 0.0
    post = df.tail(window)
    hi, lo = post["High"].values, post["Low"].values
    x = np.arange(len(hi))
    hi_slope = float(np.polyfit(x, hi, 1)[0])
    lo_slope = float(np.polyfit(x, lo, 1)[0])
    if not (hi_slope < 0 and lo_slope > 0):                 return False, 0.0
    width_start = hi[0] - lo[0]
    width_end   = hi[-1] - lo[-1]
    if width_start <= 0 or width_end >= width_start * 0.70: return False, 0.0
    # 아직 돌파/이탈 전이어야 관망
    curr = post["Close"].values[-1]
    if curr > hi[-1] or curr < lo[-1]:                      return False, 0.0
    return True, 0.70


def detect_box_range(df: pd.DataFrame, window: int = 30) -> tuple[bool, float]:
    """박스권 — 수평 저항·수평 지지 사이 횡보, 돌파 전 (관망)"""
    if len(df) < window:
        return False, 0.0
    post = df.tail(window)
    hi, lo = post["High"].values, post["Low"].values
    x = np.arange(len(hi))
    hi_slope = abs(float(np.polyfit(x, hi, 1)[0]))
    lo_slope = abs(float(np.polyfit(x, lo, 1)[0]))
    res, sup = hi.mean(), lo.mean()
    band = (res - sup) / max(res, 1e-8)
    if band < 0.02 or band > 0.20:                          return False, 0.0   # 너무 좁거나 넓으면 제외
    # 기울기가 밴드 폭 대비 완만해야 수평
    if hi_slope * len(hi) > (res - sup) * 0.5:              return False, 0.0
    if lo_slope * len(lo) > (res - sup) * 0.5:              return False, 0.0
    curr = post["Close"].values[-1]
    if curr > res * 1.005 or curr < sup * 0.995:            return False, 0.0   # 돌파/이탈 시 관망 아님
    return True, 0.68


def detect_pennant(df: pd.DataFrame, window: int = 20) -> tuple[bool, float]:
    """페넌트 — 급등/급락 후 수렴하는 삼각형"""
    if len(df) < window + 5:
        return False, 0.0
    post = df.tail(window)
    hi = post["High"].values
    lo = post["Low"].values
    hi_slope = float(np.polyfit(range(len(hi)), hi, 1)[0])
    lo_slope = float(np.polyfit(range(len(lo)), lo, 1)[0])
    if not (hi_slope < 0 and lo_slope > 0):           return False, 0.0
    if (hi[-1] - lo[-1]) >= (hi[0] - lo[0]) * 0.70:  return False, 0.0
    return True, 0.70


def scan_chart_patterns(df: pd.DataFrame) -> dict[str, tuple[bool, float]]:
    """모든 차트 패턴 스캔. scipy 없으면 빈 dict 반환."""
    if not _SCIPY or len(df) < 20:
        return {}
    try:
        return {
            "double_bottom":              detect_double_bottom(df),
            "double_top":                 detect_double_top(df),
            "triple_bottom":              detect_triple_bottom(df),
            "triple_top":                 detect_triple_top(df),
            "head_and_shoulders":         detect_head_and_shoulders(df),
            "inv_head_and_shoulders":     detect_inverse_head_and_shoulders(df),
            "ascending_triangle":         detect_ascending_triangle(df),
            "descending_triangle":        detect_descending_triangle(df),
            "rising_wedge":               detect_rising_wedge(df),
            "falling_wedge":              detect_falling_wedge(df),
            "symmetric_triangle":         detect_symmetric_triangle(df),
            "box_range":                  detect_box_range(df),
            "rising_flag":                detect_rising_flag(df),
            "falling_flag":               detect_falling_flag(df),
            "pennant":                    detect_pennant(df),
        }
    except Exception:
        return {}
