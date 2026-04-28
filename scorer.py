"""
점수(-15~+15) 및 등급 계산
모든 임계값은 config.py(settings.json)에서 읽어옴
"""
from indicators import extract_signals
from config import (
    RSI_OVERBOUGHT, RSI_OVERBOUGHT_STRONG,
    RSI_OVERSOLD,   RSI_OVERSOLD_STRONG,
    VOLUME_THRESHOLDS, VOLUME_POINTS,
)


def _score_vp(c: float, p: float, zones: list) -> float:
    """Volume Profile 기반 점수 (각 신호는 최초 1회만 적용)"""
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


def score_ticker(s: dict) -> tuple[float, str]:
    c = s["close"]
    p = s["prev_close"]
    if c is None or p is None or p == 0:
        return 0.0, "⚪ 관망"

    score = 0.0

    # ── 이동평균 상태 (매일) ──────────────────────────────────────────
    for key, pts in [("ma_l", 2.0), ("ma_m", 1.0), ("ma_s", 0.5)]:
        ma = s[key]
        if ma is not None:
            score += pts if c > ma else -pts

    # ── 이동평균 돌파 이벤트 ─────────────────────────────────────────
    for key, prev_key, pts in [
        ("ma_l", "ma_l_prev", 3.0),
        ("ma_m", "ma_m_prev", 2.0),
        ("ma_s", "ma_s_prev", 1.0),
    ]:
        ma, ma_p = s[key], s[prev_key]
        if ma is not None and ma_p is not None:
            if p <= ma_p and c > ma:   score += pts
            elif p >= ma_p and c < ma: score -= pts

    # ── MACD 상태 ────────────────────────────────────────────────────
    macd, sig = s["macd"], s["macd_sig"]
    if macd is not None and sig is not None:
        score += 1 if macd > sig else -1

    # ── MACD 이벤트 ──────────────────────────────────────────────────
    mp, sp = s["macd_prev"], s["macd_sig_prev"]
    if all(v is not None for v in [macd, sig, mp, sp]):
        if mp <= sp and macd > sig:   score += 2
        elif mp >= sp and macd < sig: score -= 2

    # ── RSI (config 임계값 사용) ─────────────────────────────────────
    rsi = s["rsi"]
    if rsi is not None:
        if rsi < RSI_OVERSOLD_STRONG:         score += 4
        elif rsi < RSI_OVERSOLD:              score += 2
        elif rsi > RSI_OVERBOUGHT_STRONG:     score -= 4
        elif rsi > RSI_OVERBOUGHT:            score -= 2

    # ── 거래량 이벤트 (config 배수 사용) ─────────────────────────────
    vol, vol_avg = s["volume"], s["vol_avg"]
    if vol is not None and vol_avg and vol_avg > 0:
        ratio = vol / vol_avg
        chg   = (c - p) / p
        for threshold, pts in zip(VOLUME_THRESHOLDS, VOLUME_POINTS):
            if ratio >= threshold:
                if chg >= 0.02:    score += pts
                elif chg <= -0.02: score -= pts
                break

    # ── 52주 신고가/신저가 ────────────────────────────────────────────
    h252, l252 = s["high_252"], s["low_252"]
    if h252 is not None and c >= h252: score += 3
    if l252 is not None and c <= l252: score -= 3

    # ── 매물대 ────────────────────────────────────────────────────────
    score += _score_vp(c, p, s.get("vp_zones", []))

    score = max(-15.0, min(15.0, round(score, 1)))

    if score >= 8:    grade = "🟢🟢 매수 강력 추천"
    elif score >= 4:  grade = "🟢 매수 추천"
    elif score >= -3: grade = "⚪ 관망"
    elif score >= -7: grade = "🔴 매도 추천"
    else:             grade = "🔴🔴 매도 강력 추천"

    return score, grade


def score_all(data: dict, asset_type: str = "STOCK") -> list[dict]:
    results = []
    for ticker, df in data.items():
        signals = extract_signals(df)
        if signals is None:
            continue
        try:
            score, grade = score_ticker(signals)
            c, p = signals["close"], signals["prev_close"]
            change_pct = (c - p) / p * 100 if p else 0.0
            results.append({
                "ticker":     ticker,
                "score":      score,
                "grade":      grade,
                "close":      c,
                "change_pct": change_pct,
                "rsi":        signals["rsi"],
                "high_252":   signals["high_252"],
                "low_252":    signals["low_252"],
                "asset_type": asset_type,
            })
        except Exception:
            pass
    return sorted(results, key=lambda x: x["score"], reverse=True)
