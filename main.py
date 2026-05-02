"""
미국 주식 시그널 분석 시스템 — 메인 실행 파일
매일 오전 6:30 / 오후 11:00 (KST) 자동 실행

실행 방법:
    venv\Scripts\python main.py
"""
import gc
import json
import os
from datetime import datetime

from config import CACHE_DIR, ETF_TICKERS
from universe import get_universe, get_etf_tickers
from fetcher import fetch_batch, apply_quality_filter, fetch_fundamentals
from scorer import score_all

CHUNK_SIZE = 100


def main():
    t0 = datetime.now()
    print(f"\n{'='*50}")
    print(f"  미국 주식 시그널 분석 시작  {t0:%Y-%m-%d %H:%M:%S}")
    print(f"{'='*50}\n")

    # ── 1. 종목 유니버스 로딩 ─────────────────────────────────────────
    print("▶ 종목 유니버스 로딩...")
    all_tickers, sp500_tickers = get_universe()
    etf_tickers = get_etf_tickers()
    sp500_set   = set(sp500_tickers)
    etf_set     = set(etf_tickers)
    print(f"  완료: 주식 {len(all_tickers)}개 / S&P 500 {len(sp500_tickers)}개 / ETF {len(etf_tickers)}개\n")

    # ── 2. 청크별 스트리밍 다운로드 + 점수화 (메모리 최적화) ─────────
    download_tickers = sorted(set(all_tickers) | etf_set)
    total_chunks = (len(download_tickers) + CHUNK_SIZE - 1) // CHUNK_SIZE
    print(f"▶ 1년치 데이터 다운로드 + 점수화 (총 {total_chunks}청크, 청크당 {CHUNK_SIZE}개)...")

    results: list[dict]     = []
    etf_results: list[dict] = []
    passed = removed = 0

    for i in range(0, len(download_tickers), CHUNK_SIZE):
        chunk    = download_tickers[i : i + CHUNK_SIZE]
        chunk_no = i // CHUNK_SIZE + 1
        print(f"  [{chunk_no}/{total_chunks}] {len(chunk)}개 처리 중...")

        raw_chunk = fetch_batch(chunk, period="1y", chunk_size=CHUNK_SIZE)

        etf_raw   = {t: df for t, df in raw_chunk.items() if t in etf_set}
        stock_raw = {t: df for t, df in raw_chunk.items() if t not in etf_set}
        del raw_chunk

        if stock_raw:
            filtered  = apply_quality_filter(stock_raw)
            removed  += len(stock_raw) - len(filtered)
            passed   += len(filtered)
            del stock_raw
            results.extend(score_all(filtered, "STOCK"))
            del filtered
        else:
            del stock_raw

        if etf_raw:
            etf_results.extend(score_all(etf_raw, "ETF"))
            del etf_raw

        gc.collect()

    print(f"  완료: 주식 {len(results)}개 / ETF {len(etf_results)}개 "
          f"(품질필터 통과 {passed}개 / 제외 {removed}개)\n")

    # ── 3. 점수 분포 출력 ─────────────────────────────────────────────
    all_scored = results + etf_results
    buy2  = sum(1 for r in all_scored if r["score"] >= 8)
    buy1  = sum(1 for r in all_scored if 4 <= r["score"] < 8)
    watch = sum(1 for r in all_scored if -3 < r["score"] < 4)
    sell1 = sum(1 for r in all_scored if -7 <= r["score"] <= -4)
    sell2 = sum(1 for r in all_scored if r["score"] < -7)
    print(f"  🟢🟢 {buy2}개  🟢 {buy1}개  ⚪ {watch}개  🔴 {sell1}개  🔴🔴 {sell2}개\n")
    del all_scored

    # ── 4. S&P 500 / 외곽 분리 ────────────────────────────────────────
    sp500_results = [r for r in results if r["ticker"] in sp500_set]
    outer_results = [r for r in results if r["ticker"] not in sp500_set]
    del results
    gc.collect()
    print(f"  S&P 500: {len(sp500_results)}개 / 외곽: {len(outer_results)}개 / ETF: {len(etf_results)}개\n")

    # ── 5. 결과 캐시 저장 ─────────────────────────────────────────────
    date_str     = t0.strftime("%Y-%m-%d")
    total_scored = len(sp500_results) + len(outer_results) + len(etf_results)
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_payload = {
        "date":       date_str,
        "total":      total_scored,
        "sp500_buy":  sorted([r for r in sp500_results if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)[:25],
        "sp500_sell": sorted([r for r in sp500_results if r["score"] < -3],  key=lambda r: r["score"])[:25],
        "etf_buy":    sorted([r for r in etf_results   if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)[:10],
        "etf_sell":   sorted([r for r in etf_results   if r["score"] < -3],  key=lambda r: r["score"])[:10],
        "outer_buy":  sorted([r for r in outer_results if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)[:15],
        "outer_sell": sorted([r for r in outer_results if r["score"] < -3],  key=lambda r: r["score"])[:15],
    }
    del sp500_results, outer_results, etf_results
    gc.collect()

    # ── 6. 상위 결과 PER/PBR 조회 ────────────────────────────────────
    top_tickers = {
        r["ticker"]
        for key, rows in cache_payload.items()
        if isinstance(rows, list)
        for r in rows
    }
    print(f"▶ 상위 결과 PER/PBR 조회 ({len(top_tickers)}개)...")
    fund_map = fetch_fundamentals(list(top_tickers))
    for key in ("sp500_buy", "sp500_sell", "etf_buy", "etf_sell", "outer_buy", "outer_sell"):
        for r in cache_payload[key]:
            fd       = fund_map.get(r["ticker"], {})
            r["per"] = fd.get("per")
            r["pbr"] = fd.get("pbr")
    del fund_map
    print("  완료\n")

    with open(os.path.join(CACHE_DIR, "last_results.json"), "w", encoding="utf-8") as f:
        json.dump(cache_payload, f, ensure_ascii=False)

    # 날짜별 아카이브 저장 (위클리 집계용)
    daily_dir = os.path.join(CACHE_DIR, "daily")
    os.makedirs(daily_dir, exist_ok=True)
    with open(os.path.join(daily_dir, f"{date_str}.json"), "w", encoding="utf-8") as f:
        json.dump(cache_payload, f, ensure_ascii=False)
    print(f"  일별 캐시 저장: cache/daily/{date_str}.json\n")

    elapsed = int((datetime.now() - t0).total_seconds() // 60)
    print(f"\n{'='*50}")
    print(f"  완료!  총 소요 시간: {elapsed}분")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
