"""
미국 주식 시그널 분석 시스템 — 메인 실행 파일
매일 미국장 마감 후(한국시간 기준 오전 6시~7시) 실행

실행 방법:
    venv\Scripts\python main.py
"""
import json
import os
from datetime import datetime

from config import CACHE_DIR, ETF_TICKERS
from universe import get_universe, get_etf_tickers
from fetcher import fetch_batch, apply_quality_filter
from scorer import score_all
from notifier import build_messages, send_message


def main():
    t0 = datetime.now()
    print(f"\n{'='*50}")
    print(f"  미국 주식 시그널 분석 시작  {t0:%Y-%m-%d %H:%M:%S}")
    print(f"{'='*50}\n")

    # ── 1. 종목 유니버스 로딩 ──────────────────────────────────────────
    print("▶ 종목 유니버스 로딩...")
    all_tickers, sp500_tickers = get_universe()
    etf_tickers = get_etf_tickers()
    sp500_set   = set(sp500_tickers)
    etf_set     = set(etf_tickers)
    print(f"  완료: 주식 {len(all_tickers)}개 / S&P 500 {len(sp500_tickers)}개 / ETF {len(etf_tickers)}개\n")

    # ── 2. 가격 데이터 다운로드 (주식 + ETF 통합) ────────────────────
    print("▶ 1년치 가격 데이터 다운로드 중 (10~20분 소요)...")
    download_tickers = sorted(set(all_tickers) | etf_set)
    raw_data = fetch_batch(download_tickers, period="1y", chunk_size=100)
    print(f"  다운로드 완료: {len(raw_data)}개\n")

    # ETF와 주식 데이터 분리 (ETF는 품질 필터 생략)
    etf_raw   = {t: df for t, df in raw_data.items() if t in etf_set}
    stock_raw = {t: df for t, df in raw_data.items() if t not in etf_set}

    # ── 3. 품질 필터 (주식만) ─────────────────────────────────────────
    print("▶ 품질 필터 적용 중 (주가 >$5, 평균 거래량 >50만)...")
    filtered = apply_quality_filter(stock_raw)
    removed  = len(stock_raw) - len(filtered)
    print(f"  필터 완료: {len(filtered)}개 통과 ({removed}개 제외)\n")

    # ── 4. 기술적 지표 계산 + 점수화 ──────────────────────────────────
    print("▶ 기술적 지표 계산 및 점수화 중...")
    results     = score_all(filtered,  "STOCK")
    etf_results = score_all(etf_raw,   "ETF")
    total_scored = len(results) + len(etf_results)
    print(f"  점수 계산 완료: 주식 {len(results)}개 / ETF {len(etf_results)}개\n")

    # 점수 분포 간단 출력
    all_scored = results + etf_results
    buy2  = sum(1 for r in all_scored if r["score"] >= 8)
    buy1  = sum(1 for r in all_scored if 4 <= r["score"] < 8)
    watch = sum(1 for r in all_scored if -3 < r["score"] < 4)
    sell1 = sum(1 for r in all_scored if -7 <= r["score"] <= -4)
    sell2 = sum(1 for r in all_scored if r["score"] < -7)
    print(f"  🟢🟢 {buy2}개  🟢 {buy1}개  ⚪ {watch}개  🔴 {sell1}개  🔴🔴 {sell2}개\n")

    # ── 5. S&P 500 / 외곽 분리 ────────────────────────────────────────
    sp500_results = [r for r in results if r["ticker"] in sp500_set]
    outer_results = [r for r in results if r["ticker"] not in sp500_set]
    print(f"  S&P 500: {len(sp500_results)}개 / 외곽: {len(outer_results)}개 / ETF: {len(etf_results)}개\n")

    # ── 5-1. 결과 캐시 저장 (app.py 표 표시용) ────────────────────────
    date_str = t0.strftime("%Y-%m-%d")
    os.makedirs(CACHE_DIR, exist_ok=True)
    cache_payload = {
        "date":       date_str,
        "total":      total_scored,
        "sp500_buy":  sorted([r for r in sp500_results if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)[:25],
        "sp500_sell": sorted([r for r in sp500_results if r["score"] < -3],  key=lambda r: r["score"])[:25],
        "etf_buy":    sorted([r for r in etf_results   if r["score"] >= 4],  key=lambda r: r["score"], reverse=True)[:10],
        "etf_sell":   sorted([r for r in etf_results   if r["score"] < -3],  key=lambda r: r["score"])[:10],
        "outer_buy":  sorted([r for r in outer_results  if r["score"] >= 4], key=lambda r: r["score"], reverse=True)[:15],
        "outer_sell": sorted([r for r in outer_results  if r["score"] < -3], key=lambda r: r["score"])[:15],
    }
    with open(os.path.join(CACHE_DIR, "last_results.json"), "w", encoding="utf-8") as f:
        json.dump(cache_payload, f, ensure_ascii=False)

    # ── 6. 텔레그램 전송 ──────────────────────────────────────────────
    print("▶ 텔레그램 메시지 전송 중...")
    messages = build_messages(date_str, total_scored, sp500_results, outer_results, etf_results)

    for i, msg in enumerate(messages, 1):
        ok = send_message(msg)
        status = "✅ 성공" if ok else "❌ 실패"
        print(f"  메시지 {i}/{len(messages)}: {status}")

    elapsed = int((datetime.now() - t0).total_seconds() // 60)
    print(f"\n{'='*50}")
    print(f"  완료!  총 소요 시간: {elapsed}분")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
