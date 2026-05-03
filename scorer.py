"""
점수(-15~+15) 및 등급 계산
장타(200MA·60MA·52주)/단타(20MA·RSI·MACD·거래량·매물대) 분리
"""
from indicators import extract_signals
from predictor  import predict_ranges
from config import (
    RSI_OVERBOUGHT, RSI_OVERBOUGHT_STRONG,
    RSI_OVERSOLD,   RSI_OVERSOLD_STRONG,
    VOLUME_THRESHOLDS, VOLUME_POINTS,
)

# ── 9-way 추천 매트릭스 ────────────────────────────────────────────────
_RECOMMENDATION = {
    ("buy",     "buy"):     "🌟 장단기 모두 매수",
    ("buy",     "neutral"): "📈 장기 매수, 단기 대기",
    ("buy",     "sell"):    "⚠️ 장기 매수, 단기 조정",
    ("neutral", "buy"):     "📊 단기 반등 시도",
    ("neutral", "neutral"): "⚪ 방향 탐색 중",
    ("neutral", "sell"):    "📉 단기 약세",
    ("sell",    "buy"):     "↩️ 장기 약세, 단기 반등",
    ("sell",    "neutral"): "📉 장기 약세, 관망",
    ("sell",    "sell"):    "🔴 장단기 모두 매도",
}

_REC_SHORT = {
    "🌟 장단기 모두 매수":    "매수",
    "📈 장기 매수, 단기 대기": "장기매수",
    "⚠️ 장기 매수, 단기 조정": "조정주의",
    "📊 단기 반등 시도":       "단기반등",
    "⚪ 방향 탐색 중":         "관망",
    "📉 단기 약세":            "단기약세",
    "↩️ 장기 약세, 단기 반등": "반등시도",
    "📉 장기 약세, 관망":      "장기약세",
    "🔴 장단기 모두 매도":     "매도",
}


def _score_vp(c: float, p: float, zones: list) -> float:
    if not zones:
        return 0.0
    score = 0.0
    done = {"resist": False, "support": False, "breakup": False, "breakdown": False}
    for z_lo, z_hi in zones:
        if not done["resist"] and z_hi * 0.95 <= c < z_hi:
            score -= 1; done["resist"] = True
        if not done["support"] and z_lo < c <= z_lo * 1.05:
            score += 1; done["support"] = True
        if not done["breakup"] and p < z_hi <= c:
            score += 2; done["breakup"] = True
        if not done["breakdown"] and p > z_lo >= c:
            score -= 2; done["breakdown"] = True
    return score


def grade_from_score(total: float) -> str:
    if total >= 8:    return "🟢🟢 매수 강력 추천"
    elif total >= 4:  return "🟢 매수 추천"
    elif total >= -3: return "⚪ 관망"
    elif total >= -7: return "🔴 매도 추천"
    else:             return "🔴🔴 매도 강력 추천"


def score_fundamentals(per: float | None, pbr: float | None) -> float:
    """PER/PBR 밸류에이션 추가 점수 (-3 ~ +3).
    기술적 점수에 더해 최종 합산에 반영됨.
    """
    score = 0.0

    if per is not None:
        if   per < 0:    score -= 1   # 적자
        elif per <= 15:  score += 2   # 저PER — 저평가
        elif per <= 25:  score += 1   # 적정
        # 25~50: 중립
        elif per <= 100: score -= 1   # 고평가
        else:            score -= 2   # 극고평가

    if pbr is not None and pbr > 0:
        if   pbr < 1:   score += 1   # 청산가 이하
        elif pbr <= 5:  score += 0   # 적정
        elif pbr <= 15: score -= 1   # 높은 편
        else:           score -= 2   # 극고평가

    return round(max(-3.0, min(3.0, score)), 1)


def score_ticker(s: dict) -> tuple[float, str, float, float, str]:
    """
    Returns: (total_score, grade, long_score, short_score, recommendation)
    """
    c = s["close"]
    p = s["prev_close"]
    if c is None or p is None or p == 0:
        return 0.0, "⚪ 관망", 0.0, 0.0, "⚪ 방향 탐색 중"

    long_score  = 0.0
    short_score = 0.0

    # ── 장타: 200MA · 60MA 상태 ──────────────────────────────────────
    ma_l = s["ma_l"]
    ma_m = s["ma_m"]
    if ma_l is not None:
        long_score += 2.0 if c > ma_l else -2.0
    if ma_m is not None:
        long_score += 1.0 if c > ma_m else -1.0

    # ── 장타: 200MA · 60MA 돌파 이벤트 ──────────────────────────────
    ma_l_p = s["ma_l_prev"]
    ma_m_p = s["ma_m_prev"]
    if ma_l is not None and ma_l_p is not None:
        if p <= ma_l_p and c > ma_l:   long_score += 3.0
        elif p >= ma_l_p and c < ma_l: long_score -= 3.0
    if ma_m is not None and ma_m_p is not None:
        if p <= ma_m_p and c > ma_m:   long_score += 2.0
        elif p >= ma_m_p and c < ma_m: long_score -= 2.0

    # ── 장타: 52주 신고가/신저가 ─────────────────────────────────────
    h252, l252 = s["high_252"], s["low_252"]
    if h252 is not None and c >= h252: long_score += 3.0
    if l252 is not None and c <= l252: long_score -= 3.0

    # ── 단타: 20MA 상태 + 돌파 ────────────────────────────────────────
    ma_s   = s["ma_s"]
    ma_s_p = s["ma_s_prev"]
    if ma_s is not None:
        short_score += 0.5 if c > ma_s else -0.5
    if ma_s is not None and ma_s_p is not None:
        if p <= ma_s_p and c > ma_s:   short_score += 1.0
        elif p >= ma_s_p and c < ma_s: short_score -= 1.0

    # ── 단타: MACD 상태 + 이벤트 ─────────────────────────────────────
    macd, sig = s["macd"], s["macd_sig"]
    if macd is not None and sig is not None:
        short_score += 1 if macd > sig else -1
    mp, sp = s["macd_prev"], s["macd_sig_prev"]
    if all(v is not None for v in [macd, sig, mp, sp]):
        if mp <= sp and macd > sig:   short_score += 2
        elif mp >= sp and macd < sig: short_score -= 2

    # ── 단타: RSI ─────────────────────────────────────────────────────
    rsi = s["rsi"]
    if rsi is not None:
        if rsi < RSI_OVERSOLD_STRONG:     short_score += 4
        elif rsi < RSI_OVERSOLD:          short_score += 2
        elif rsi > RSI_OVERBOUGHT_STRONG: short_score -= 4
        elif rsi > RSI_OVERBOUGHT:        short_score -= 2

    # ── 단타: 거래량 이벤트 ───────────────────────────────────────────
    vol, vol_avg = s["volume"], s["vol_avg"]
    if vol is not None and vol_avg and vol_avg > 0:
        ratio = vol / vol_avg
        chg   = (c - p) / p
        for threshold, pts in zip(VOLUME_THRESHOLDS, VOLUME_POINTS):
            if ratio >= threshold:
                if chg >= 0.02:    short_score += pts
                elif chg <= -0.02: short_score -= pts
                break

    # ── 단타: 매물대 ──────────────────────────────────────────────────
    short_score += _score_vp(c, p, s.get("vp_zones", []))

    # ── 합산 + 클리핑 ─────────────────────────────────────────────────
    long_score  = round(long_score,  1)
    short_score = round(short_score, 1)
    total = max(-15.0, min(15.0, round(long_score + short_score, 1)))

    grade = grade_from_score(total)

    # ── 9-way 추천 텍스트 ─────────────────────────────────────────────
    long_dir  = "buy"  if long_score  >= 2 else ("sell" if long_score  <= -2 else "neutral")
    short_dir = "buy"  if short_score >= 2 else ("sell" if short_score <= -2 else "neutral")
    recommendation = _RECOMMENDATION[(long_dir, short_dir)]

    return total, grade, long_score, short_score, recommendation


def score_all(data: dict, asset_type: str = "STOCK") -> list[dict]:
    results = []
    for ticker, df in data.items():
        signals = extract_signals(df)
        if signals is None:
            continue
        try:
            total, grade, long_score, short_score, recommendation = score_ticker(signals)
            c, p = signals["close"], signals["prev_close"]
            change_pct = (c - p) / p * 100 if p else 0.0
            prediction = predict_ranges(df, signals)
            results.append({
                "ticker":         ticker,
                "score":          total,
                "grade":          grade,
                "long_score":     long_score,
                "short_score":    short_score,
                "recommendation": recommendation,
                "close":          c,
                "change_pct":     change_pct,
                "rsi":            signals["rsi"],
                "high_252":       signals["high_252"],
                "low_252":        signals["low_252"],
                "asset_type":     asset_type,
                "prediction":     prediction,
            })
        except Exception:
            pass
    return sorted(results, key=lambda x: x["score"], reverse=True)
