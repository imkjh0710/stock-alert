"""
점수(-25~+25) 및 등급 계산
장타(200MA·60MA·52주)/단타(20MA·RSI·MACD·거래량·매물대·캔들패턴) 분리
차트패턴 → 장타에 반영
"""
from indicators import extract_signals
from predictor  import predict_ranges
from config import (
    RSI_OVERBOUGHT, RSI_OVERBOUGHT_STRONG,
    RSI_OVERSOLD,   RSI_OVERSOLD_STRONG,
    VOLUME_THRESHOLDS, VOLUME_POINTS,
    PER_CHEAP_STRONG, PER_CHEAP, PER_PRICEY, PER_PRICEY_STRONG,
    PBR_CHEAP, PBR_PRICEY, PBR_PRICEY_STRONG,
)

try:
    from patterns      import scan_candle_patterns
    from chart_patterns import scan_chart_patterns
    _PATTERNS_OK = True
except ImportError:
    _PATTERNS_OK = False

# ── 캔들 패턴 점수 테이블 (단독 발생 시) ─────────────────────────────
_CANDLE_PTS = {
    "morning_star":         3.0,
    "bullish_engulfing":    3.0,
    "bullish_pin_bar":      2.0,
    "three_white_soldiers": 5.0,
    "tweezer_bottom":       2.0,
    "evening_star":        -3.0,
    "bearish_engulfing":   -3.0,
    "shooting_star":       -2.0,
    "three_black_crows":   -5.0,
    "tweezer_top":         -2.0,
    "dark_cloud_cover":    -2.0,
}

# ── 차트 패턴 점수 테이블 ────────────────────────────────────────────
_CHART_PTS = {
    "double_bottom":          4.0,
    "double_top":            -4.0,
    "inv_head_and_shoulders": 4.0,
    "head_and_shoulders":    -4.0,
    "ascending_triangle":     3.0,
    "descending_triangle":   -3.0,
    "rising_flag":            3.0,
    "falling_flag":          -3.0,
    "pennant":                2.0,   # 방향은 context에서 결정
}

# ── 패턴 한글명 ──────────────────────────────────────────────────────
_PAT_KR = {
    "morning_star":           "샛별",
    "bullish_engulfing":      "양포형",
    "bullish_pin_bar":        "해머",
    "three_white_soldiers":   "적삼병",
    "tweezer_bottom":         "저점쌍봉",
    "evening_star":           "저녁별",
    "bearish_engulfing":      "음포형",
    "shooting_star":          "별똥별",
    "three_black_crows":      "흑삼병",
    "tweezer_top":            "고점쌍봉",
    "dark_cloud_cover":       "다크클라우드",
    "double_bottom":          "더블바텀",
    "double_top":             "더블탑",
    "inv_head_and_shoulders": "역삼존",
    "head_and_shoulders":     "삼존(H&S)",
    "ascending_triangle":     "상승삼각형",
    "descending_triangle":    "하강삼각형",
    "rising_flag":            "상승플래그",
    "falling_flag":           "하강플래그",
    "pennant":                "페넌트",
}

def _stars(pts: float) -> str:
    n = min(5, max(1, round(abs(pts))))
    return "★" * n + "☆" * (5 - n)

def _score_tag(eff: float) -> str:
    return f"{eff:+.1f}"


# ── 9-way 추천 매트릭스 ─────────────────────────────────────────────
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
    if   total >= 13:  return "🟢🟢 매수 강력 추천"
    elif total >=  6:  return "🟢 매수 추천"
    elif total >= -5:  return "⚪ 관망"
    elif total >= -12: return "🔴 매도 추천"
    else:              return "🔴🔴 매도 강력 추천"


def score_fundamentals(per: float | None, pbr: float | None) -> float:
    score = 0.0
    if per is not None:
        if   per < 0:                    score -= 1
        elif per <= PER_CHEAP_STRONG:    score += 2
        elif per <= PER_CHEAP:           score += 1
        elif per <= PER_PRICEY:          score += 0
        elif per <= PER_PRICEY_STRONG:   score -= 1
        else:                            score -= 2
    if pbr is not None and pbr > 0:
        if   pbr < PBR_CHEAP:            score += 1
        elif pbr <= PBR_PRICEY:          score += 0
        elif pbr <= PBR_PRICEY_STRONG:   score -= 1
        else:                            score -= 2
    return round(max(-3.0, min(3.0, score)), 1)


def _calc_pattern_scores(
    candle_pats: dict, chart_pats: dict, s: dict
) -> tuple[float, float, float, list[str]]:
    """
    Returns (candle_score, chart_score, ma_bonus, found_labels)
    candle_score → 단타에 합산 (cap ±5)
    chart_score  → 장타에 합산 (cap ±5)
    ma_bonus     → 장타 보너스 (±1)
    """
    c     = s.get("close") or 0
    ma_l  = s.get("ma_l")
    vol   = s.get("volume") or 0
    vol_a = s.get("vol_avg") or 1
    vol_ratio = vol / vol_a if vol_a > 0 else 0

    found_labels: list[str] = []
    candle_raw = 0.0
    chart_raw  = 0.0

    # ── 캔들 패턴 ──────────────────────────────────────────────────
    # 조합 보너스: 샛별 + 핀바
    ms_ok,  ms_c  = candle_pats.get("morning_star",       (False, 0))
    pb_ok,  pb_c  = candle_pats.get("bullish_pin_bar",    (False, 0))
    es_ok,  es_c  = candle_pats.get("evening_star",       (False, 0))
    bc_ok,  bc_c  = candle_pats.get("three_black_crows",  (False, 0))

    combo_bull = ms_ok and pb_ok
    combo_bear = es_ok and bc_ok

    for name, pts in _CANDLE_PTS.items():
        det, conf = candle_pats.get(name, (False, 0))
        if not det:
            continue
        # 신뢰도 < 0.7 이면 절반만
        eff = pts if conf >= 0.7 else pts * 0.5
        # 조합 보너스
        if name == "morning_star" and combo_bull:
            eff = 5.0 if conf >= 0.7 else 2.5
        if name == "evening_star" and combo_bear:
            eff = -5.0 if conf >= 0.7 else -2.5
        candle_raw += eff
        kr = _PAT_KR.get(name, name)
        found_labels.append(f"{kr}({_score_tag(eff)})")

    # 거래량 2배+ 보너스
    if vol_ratio >= 2:
        if candle_raw > 0:   candle_raw += 1.0
        elif candle_raw < 0: candle_raw -= 1.0

    # ── 차트 패턴 ──────────────────────────────────────────────────
    # 페넌트 방향 결정 (현재가 vs 20MA)
    ma_s = s.get("ma_s")
    pennant_dir = 1.0 if (ma_s and c > ma_s) else -1.0

    for name, pts in _CHART_PTS.items():
        det, conf = chart_pats.get(name, (False, 0))
        if not det:
            continue
        if name == "pennant":
            pts = abs(pts) * pennant_dir
        eff = pts if conf >= 0.7 else pts * 0.5
        # 조합 보너스: 더블바텀 + 샛별
        if name == "double_bottom" and ms_ok:
            eff = 5.0 if conf >= 0.7 else 2.5
        if name == "head_and_shoulders" and bc_ok:
            eff = -5.0 if conf >= 0.7 else -2.5
        chart_raw += eff
        kr = _PAT_KR.get(name, name)
        found_labels.append(f"{kr}({_score_tag(eff)})")

    if vol_ratio >= 2:
        if chart_raw > 0:   chart_raw += 1.0
        elif chart_raw < 0: chart_raw -= 1.0

    # ── 200MA 보너스 ─────────────────────────────────────────────
    ma_bonus = 0.0
    if ma_l is not None and c > 0:
        total_pat = candle_raw + chart_raw
        if total_pat > 0 and c > ma_l:   ma_bonus =  1.0
        elif total_pat < 0 and c < ma_l: ma_bonus = -1.0

    # ── 캡 ±5 ─────────────────────────────────────────────────────
    candle_score = round(max(-5.0, min(5.0, candle_raw)), 1)
    chart_score  = round(max(-5.0, min(5.0, chart_raw)),  1)

    return candle_score, chart_score, ma_bonus, found_labels


def score_ticker(s: dict, df=None) -> tuple[float, str, float, float, str, list[str], float]:
    """
    Returns: (total_score, grade, long_score, short_score, recommendation, patterns, pattern_score)
    """
    c = s["close"]
    p = s["prev_close"]
    if c is None or p is None or p == 0:
        return 0.0, "⚪ 관망", 0.0, 0.0, "⚪ 방향 탐색 중", [], 0.0

    long_score  = 0.0
    short_score = 0.0

    # ── 장타: 200MA · 60MA 상태 ──────────────────────────────────────
    ma_l = s["ma_l"]; ma_m = s["ma_m"]
    if ma_l is not None: long_score += 2.0 if c > ma_l else -2.0
    if ma_m is not None: long_score += 1.0 if c > ma_m else -1.0

    # ── 장타: 200MA · 60MA 돌파 ──────────────────────────────────────
    ma_l_p = s["ma_l_prev"]; ma_m_p = s["ma_m_prev"]
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

    # ── 장타: OBV 추세 (매집/분산) ───────────────────────────────────
    # OBV slope > 0.05 AND 가격이 60MA 위 → 매집 확인 (+1)
    # OBV slope < -0.05 AND 가격이 60MA 아래 → 분산 확인 (-1)
    obv_slope = s.get("obv_slope") or 0.0
    if obv_slope > 0.05 and ma_m is not None and c > ma_m:
        long_score += 1.0
    elif obv_slope < -0.05 and ma_m is not None and c < ma_m:
        long_score -= 1.0

    # ── 단타: 20MA 상태 + 돌파 ───────────────────────────────────────
    ma_s = s["ma_s"]; ma_s_p = s["ma_s_prev"]
    if ma_s is not None:
        short_score += 0.5 if c > ma_s else -0.5
    if ma_s is not None and ma_s_p is not None:
        if p <= ma_s_p and c > ma_s:   short_score += 1.0
        elif p >= ma_s_p and c < ma_s: short_score -= 1.0

    # ── 단타: MACD ───────────────────────────────────────────────────
    macd, sig = s["macd"], s["macd_sig"]
    if macd is not None and sig is not None:
        short_score += 1 if macd > sig else -1
    mp, sp = s["macd_prev"], s["macd_sig_prev"]
    if all(v is not None for v in [macd, sig, mp, sp]):
        if mp <= sp and macd > sig:   short_score += 2
        elif mp >= sp and macd < sig: short_score -= 2

    # ── 단타: RSI ────────────────────────────────────────────────────
    rsi = s["rsi"]
    if rsi is not None:
        if rsi < RSI_OVERSOLD_STRONG:     short_score += 4
        elif rsi < RSI_OVERSOLD:          short_score += 2
        elif rsi > RSI_OVERBOUGHT_STRONG: short_score -= 4
        elif rsi > RSI_OVERBOUGHT:        short_score -= 2

    # ── 단타: 거래량 ──────────────────────────────────────────────────
    vol, vol_avg = s["volume"], s["vol_avg"]
    if vol is not None and vol_avg and vol_avg > 0:
        ratio = vol / vol_avg
        chg   = (c - p) / p
        for threshold, pts in zip(VOLUME_THRESHOLDS, VOLUME_POINTS):
            if ratio >= threshold:
                if chg >= 0.02:    short_score += pts
                elif chg <= -0.02: short_score -= pts
                break

    # ── 단타: 매물대 ─────────────────────────────────────────────────
    short_score += _score_vp(c, p, s.get("vp_zones", []))

    # ── 패턴 점수 ─────────────────────────────────────────────────────
    found_patterns: list[str] = []
    pattern_score = 0.0
    if _PATTERNS_OK and df is not None:
        try:
            candle_pats = scan_candle_patterns(df)
            chart_pats  = scan_chart_patterns(df)
            c_score, ch_score, ma_bonus, found_patterns = _calc_pattern_scores(
                candle_pats, chart_pats, s
            )
            short_score   += c_score
            long_score    += ch_score + ma_bonus
            pattern_score  = round(c_score + ch_score + ma_bonus, 1)
        except Exception:
            pass

    # ── 합산 + 클리핑 ─────────────────────────────────────────────────
    long_score  = round(long_score,  1)
    short_score = round(short_score, 1)
    total = max(-25.0, min(25.0, round(long_score + short_score, 1)))

    grade = grade_from_score(total)

    # ── 9-way 추천 (새 임계값 ±6) ────────────────────────────────────
    long_dir  = "buy"  if long_score  >= 6 else ("sell" if long_score  <= -6 else "neutral")
    short_dir = "buy"  if short_score >= 6 else ("sell" if short_score <= -6 else "neutral")
    recommendation = _RECOMMENDATION[(long_dir, short_dir)]

    return total, grade, long_score, short_score, recommendation, found_patterns, pattern_score


def score_all(data: dict, asset_type: str = "STOCK") -> list[dict]:
    results = []
    for ticker, df in data.items():
        signals = extract_signals(df)
        if signals is None:
            continue
        try:
            total, grade, long_score, short_score, recommendation, patterns, pattern_score = score_ticker(signals, df)
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
                "patterns":       patterns,
                "pattern_score":  pattern_score,
            })
        except Exception:
            pass
    return sorted(results, key=lambda x: x["score"], reverse=True)
