"""
10개 종목으로 전체 파이프라인 테스트
S&P 500 5개 + 외곽 5개
"""
from datetime import datetime
from fetcher import fetch_batch, apply_quality_filter
from scorer import score_all
from notifier import build_messages, send_message

TEST_SP500  = ["AAPL", "NVDA", "MSFT", "AMZN", "TSLA"]
TEST_OUTER  = ["PLTR", "SMCI", "COIN", "MSTR", "RIVN"]
ALL_TICKERS = TEST_SP500 + TEST_OUTER
SP500_SET   = set(TEST_SP500)

print(f"\n{'='*50}")
print(f"  10종목 파이프라인 테스트  {datetime.now():%H:%M:%S}")
print(f"  종목: {', '.join(ALL_TICKERS)}")
print(f"{'='*50}\n")

print("▶ 데이터 다운로드...")
raw = fetch_batch(ALL_TICKERS, period="1y", chunk_size=10)
print(f"  {len(raw)}개 완료\n")

print("▶ 품질 필터...")
filtered = apply_quality_filter(raw)
print(f"  {len(filtered)}개 통과\n")

print("▶ 점수 계산...")
results = score_all(filtered)
print()

sp500_results = [r for r in results if r["ticker"] in SP500_SET]
outer_results  = [r for r in results if r["ticker"] not in SP500_SET]

print("── 전체 결과 ──────────────────────────────────────────────")
print(f"  {'종목':<6} {'점수':>6}  {'등급':<20}  {'종가':>8}  {'등락':>7}  VP구간수")
for r in results:
    tag = "S&P" if r["ticker"] in SP500_SET else "외곽"
    vp  = r.get("vp_zone_count", "?")
    print(
        f"  [{tag}] {r['ticker']:<5} {r['score']:>+6.1f}점  "
        f"{r['grade']:<22}  ${r['close']:>7.2f}  "
        f"{r['change_pct']:>+6.1f}%"
    )
print()

print("▶ 텔레그램 전송 (새 양식)...")
date_str = datetime.now().strftime("%Y-%m-%d")
messages = build_messages(
    f"{date_str} [10종목 테스트]",
    len(results),
    sp500_results,
    outer_results,
)
for i, msg in enumerate(messages, 1):
    ok = send_message(msg)
    print(f"  메시지 {i}/{len(messages)}: {'✅ 성공' if ok else '❌ 실패'}")

print(f"\n{'='*50}\n")
