"""
보유 종목 전용 분析 — GitHub Actions daily-alert.yml에서 매일 실행
결과: cache/holdings_analysis.json

실행 방법:
    venv/Scripts/python analyze_holdings.py
"""
import gc
import json
import os
from datetime import datetime

from config import CACHE_DIR
from fetcher import fetch_batch, fetch_fundamentals
from scorer import score_all, score_fundamentals, grade_from_score
from dividend_analyzer import analyze_dividends


def _clean(r: dict) -> dict:
    return {k: v for k, v in r.items() if isinstance(v, (str, int, float, bool, type(None)))}


def main():
    if not os.path.exists("holdings.json"):
        print("holdings.json 없음 — 보유 종목 분析 건너뜀")
        return
    with open("holdings.json", encoding="utf-8") as f:
        holdings = json.load(f)
    tickers = [h["ticker"] for h in holdings]
    if not tickers:
        print("보유 종목 없음 — 건너뜀")
        return

    t0 = datetime.now()
    print(f"\n{'='*50}")
    print(f"  보유 종목 분析 시작  {t0:%Y-%m-%d %H:%M:%S}  ({len(tickers)}개)")
    print(f"{'='*50}\n")

    # ── 1. OHLCV + 기술적 분析 (패턴 포함) ───────────────────────────
    print("▶ OHLCV 다운로드 + 기술적 분析...")
    raw = fetch_batch(tickers, period="1y", chunk_size=max(len(tickers), 1))
    scored_list = score_all(raw)
    scored: dict[str, dict] = {}
    for r in scored_list:
        # list 필드를 문자열로 변환해 JSON 직렬화 호환
        r["patterns_str"] = ", ".join(r.get("patterns", [])) or "—"
        r.pop("patterns",   None)
        r.pop("prediction", None)
        scored[r["ticker"]] = r
    del raw, scored_list
    gc.collect()
    print(f"  완료: {len(scored)}개\n")

    # ── 2. PER / PBR ─────────────────────────────────────────────────
    print("▶ PER/PBR 조회...")
    fund_map = fetch_fundamentals(tickers)
    for t, r in scored.items():
        fd              = fund_map.get(t, {})
        r["per"]        = fd.get("per")
        r["pbr"]        = fd.get("pbr")
        r["fund_score"] = score_fundamentals(r["per"], r["pbr"])
        new_total       = max(-15.0, min(15.0, r["score"] + r["fund_score"]))
        r["score"]      = round(new_total, 1)
        r["grade"]      = grade_from_score(new_total)
    del fund_map
    print("  완료\n")

    # ── 3. 배당 분析 ─────────────────────────────────────────────────
    print("▶ 배당 분析...")
    div_results = analyze_dividends(tickers, apply_filter=False)
    # 패턴 점수를 배당 결과에도 병합
    for r in div_results:
        sc = scored.get(r["ticker"], {})
        r["pattern_score"] = sc.get("pattern_score", 0)
        r["patterns_str"]  = sc.get("patterns_str", "—")
    print(f"  완료: {len(div_results)}개\n")

    # ── 4. 캐시 저장 ─────────────────────────────────────────────────
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = {
        "date":      t0.strftime("%Y-%m-%d"),
        "scores":    {t: _clean(r) for t, r in scored.items()},
        "dividends": [_clean(r) for r in div_results],
    }
    out = os.path.join(CACHE_DIR, "holdings_analysis.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)

    elapsed = int((datetime.now() - t0).total_seconds() // 60)
    print(f"  저장 완료: {out}")
    print(f"\n{'='*50}")
    print(f"  완료!  소요 시간: {elapsed}분")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
