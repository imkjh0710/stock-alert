"""
배당주 일일 분석 — 캐시 저장 전용
매일 오전 6:30 / 오후 11:00 (KST) 실행

실행 방법:
    venv/Scripts/python weekly_dividend.py
"""
import json
import os
from datetime import datetime

from config import CACHE_DIR
from universe import get_universe
from dividend_analyzer import analyze_dividends

try:
    from fetcher import fetch_batch
    from patterns import scan_candle_patterns
    from chart_patterns import scan_chart_patterns
    from scorer import _calc_pattern_scores
    from indicators import extract_signals
    _PAT_OK = True
except ImportError:
    _PAT_OK = False


def _load_holdings() -> list[str]:
    env = os.getenv("MY_HOLDINGS")
    if env:
        try:
            return [h["ticker"] for h in json.loads(env)]
        except Exception:
            pass
    if os.path.exists("holdings.json"):
        with open("holdings.json", encoding="utf-8") as f:
            return [h["ticker"] for h in json.load(f)]
    return []


def main():
    t0 = datetime.now()
    print(f"\n{'='*50}")
    print(f"  배당주 분석 시작  {t0:%Y-%m-%d %H:%M:%S}")
    print(f"{'='*50}\n")

    print("▶ 종목 유니버스 로딩...")
    all_tickers, _ = get_universe()
    print(f"  완료: {len(all_tickers)}개\n")

    holdings = _load_holdings()
    if holdings:
        print(f"  보유 종목: {len(holdings)}개\n")

    results  = analyze_dividends(all_tickers)
    date_str = t0.strftime("%Y-%m-%d")

    # ── 보유 종목: 필터 탈락·미포함 종목 별도 분석 (필터 없이) ──────
    held_set   = set(holdings)
    result_map = {r["ticker"]: r for r in results}
    missing    = [t for t in holdings if t not in result_map]
    if missing:
        print(f"▶ 보유 종목 {len(missing)}개 필터 없이 별도 분석 중...")
        extra = analyze_dividends(missing, apply_filter=False)
        for r in extra:
            result_map[r["ticker"]] = r
        print(f"  완료\n")

    # ── 카테고리 분류 ─────────────────────────────────────────────────
    growth_top = sorted(
        [r for r in results if not r.get("had_cut")],
        key=lambda r: (r.get("dgr_long") or r.get("dgr_short") or 0, r["score"]),
        reverse=True,
    )
    royalty = sorted(
        [r for r in results if r.get("consecutive_growth", 0) >= 25],
        key=lambda r: (r.get("consecutive_growth", 0), r["score"]), reverse=True,
    )
    high_yield = sorted(
        [r for r in results
         if (r.get("yield_ttm") or 0) >= 3
         and (r.get("payout_ratio") is None or (r.get("payout_ratio") or 1) < 0.80)],
        key=lambda r: r.get("yield_ttm") or 0, reverse=True,
    )
    risk = sorted(
        [r for r in results
         if r.get("had_cut")
         or (r.get("payout_ratio") is not None and (r.get("payout_ratio") or 0) > 0.9)],
        key=lambda r: r.get("payout_ratio") or 0, reverse=True,
    )

    # ── 패턴 분析 (최종 표시 종목 한정) ──────────────────────────────
    if _PAT_OK:
        display_set: set[str] = set()
        for r in growth_top[:15]:  display_set.add(r["ticker"])
        for r in royalty[:10]:     display_set.add(r["ticker"])
        for r in high_yield[:10]:  display_set.add(r["ticker"])
        for r in risk[:5]:         display_set.add(r["ticker"])
        for t in holdings:         display_set.add(t)
        display_set = {t for t in display_set if t in result_map}

        if display_set:
            print(f"▶ 패턴 분析 ({len(display_set)}개)...")
            ohlcv = fetch_batch(list(display_set), period="1y",
                                chunk_size=max(len(display_set), 1))
            for ticker, df in ohlcv.items():
                if ticker not in result_map:
                    continue
                try:
                    signals = extract_signals(df)
                    if signals is None:
                        continue
                    c_pats  = scan_candle_patterns(df)
                    ch_pats = scan_chart_patterns(df)
                    c_sc, ch_sc, ma_b, labels = _calc_pattern_scores(c_pats, ch_pats, signals)
                    result_map[ticker]["pattern_score"] = round(c_sc + ch_sc + ma_b, 1)
                    result_map[ticker]["patterns_str"]  = ", ".join(labels) or "—"
                except Exception:
                    pass
            print("  완료\n")

    # ── 캐시 저장 ─────────────────────────────────────────────────────
    def _clean(r: dict) -> dict:
        return {k: v for k, v in r.items() if isinstance(v, (str, int, float, bool, type(None)))}

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = {
        "date":          date_str,
        "total":         len(results),
        "growth_top":    [_clean(r) for r in growth_top[:15]],
        "royalty":       [_clean(r) for r in royalty[:10]],
        "high_yield":    [_clean(r) for r in high_yield[:10]],
        "risk":          [_clean(r) for r in risk[:5]],
        "holdings_data": [_clean(result_map[t]) for t in holdings if t in result_map],
    }
    with open(os.path.join(CACHE_DIR, "last_dividend.json"), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print("  캐시 저장 완료 (cache/last_dividend.json)\n")

    elapsed = int((datetime.now() - t0).total_seconds() // 60)
    print(f"\n{'='*50}")
    print(f"  완료!  소요 시간: {elapsed}분")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
