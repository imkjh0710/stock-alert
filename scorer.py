"""
점수(-15~+15) 및 등급 계산
"""
from indicators import extract_signals
import pandas as pd


def _score_vp(c: float, p: float, zones: list) -> float:
    """
    Volume Profile 기반 점수.
    각 신호는 여러 구간 중 처음 매칭되는 1개에만 적용.
    """
    if not zones:
        return 0.0

    score = 0.0
    done = {"resist": False, "support": False, "breakup": False, "breakdown": False}

    for z_lo, z_hi in zones:
        # 저항 임박: c가 zone 상단 5% 이내 아래에서 접근 중
        if not done["resist"] and z_hi * 0.95 <= c < z_hi:
            score -= 1
            done["resist"] = True

        # 지지 근접: c가 zone 하단 5% 이내 위에서 지지받는 중
        if not done["support"] and z_lo < c <= z_lo * 1.05:
            score += 1
            done["support"] = True

        # 상향 돌파: 어제 zone 상단 아래 → 오늘 zone 상단 위
        if not done["breakup"] and p < z_hi <= c:
            score += 2
            done["breakup"] = True

        # 하향 이탈: 어제 zone 하단 위 → 오늘 zone 하단 아래
        if not done["breakdown"] and p > z_lo >= c:
            score -= 2
            done["breakdown"] = True

    return score


def score_ticker(s: dict) -> tuple[float, str]:
    c = s["close"]
    p = s["prev_close"]
    if c is None or p is None or p == 0:
        return 0.0, "⚪ 관망"

    score = 0.0

    # ── 이동평균 상태 (매일) ──────────────────────────────────────────
    for key, pts in [("ma200", 2.0), ("ma60", 1.0), ("ma20", 0.5)]:
        ma = s[key]
        if ma is not None:
            score += pts if c > ma else -pts

    # ── 이동평균 돌파 이벤트 (오늘만) ──────────────────────────────────
    for key, prev_key, pts in [
        ("ma200", "ma200_prev", 3.0),
        ("ma60",  "ma60_prev",  2.0),
        ("ma20",  "ma20_prev",  1.0),
    ]:
        ma, ma_p = s[key], s[prev_key]
        if ma is not None and ma_p is not None:
            if p <= ma_p and c > ma:   # 상향 돌파
                score += pts
            elif p >= ma_p and c < ma: # 하향 돌파
                score -= pts

    # ── MACD 상태 ────────────────────────────────────────────────────
    macd, sig = s["macd"], s["macd_sig"]
    if macd is not None and sig is not None:
        score += 1 if macd > sig else -1

    # ── MACD 이벤트 (골든/데드크로스) ────────────────────────────────
    mp, sp = s["macd_prev"], s["macd_sig_prev"]
    if all(v is not None for v in [macd, sig, mp, sp]):
        if mp <= sp and macd > sig:   # 골든크로스
            score += 2
        elif mp >= sp and macd < sig: # 데드크로스
            score -= 2

    # ── RSI 상태 ──────────────────────────────────────────────────────
    rsi = s["rsi"]
    if rsi is not None:
        if rsi < 25:    score += 4
        elif rsi < 30:  score += 2
        elif rsi > 75:  score -= 4
        elif rsi > 70:  score -= 2

    # ── 거래량 이벤트 ─────────────────────────────────────────────────
    vol, vol_avg = s["volume"], s["vol_avg"]
    if vol is not None and vol_avg and vol_avg > 0:
        ratio = vol / vol_avg
        chg = (c - p) / p
        for threshold, pts in [(5, 4), (3, 3), (2, 2)]:
            if ratio >= threshold:
                if chg >= 0.02:    score += pts
                elif chg <= -0.02: score -= pts
                break

    # ── 52주 신고가/신저가 ────────────────────────────────────────────
    h252, l252 = s["high_252"], s["low_252"]
    if h252 is not None and c >= h252: score += 3
    if l252 is not None and c <= l252: score -= 3

    # ── 매물대 (Volume Profile) ───────────────────────────────────────
    score += _score_vp(c, p, s.get("vp_zones", []))

    score = max(-15.0, min(15.0, round(score, 1)))

    if score >= 8:    grade = "🟢🟢 매수 강력 추천"
    elif score >= 4:  grade = "🟢 매수 추천"
    elif score >= -3: grade = "⚪ 관망"
    elif score >= -7: grade = "🔴 매도 추천"
    else:             grade = "🔴🔴 매도 강력 추천"

    return score, grade


def score_all(data: dict) -> list[dict]:
    """
    {ticker: DataFrame} → 점수 계산 후 점수 내림차순 정렬된 list[dict] 반환
    """
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
            })
        except Exception:
            pass

    return sorted(results, key=lambda x: x["score"], reverse=True)
