"""
배당주 주간 리포트 - 메인 실행 파일
매주 일요일 22:00 KST 실행

실행 방법:
    venv/Scripts/python weekly_dividend.py
"""
import json
import os
from datetime import datetime

from config import CACHE_DIR
from universe import get_universe
from dividend_analyzer import analyze_dividends
from notifier import send_message

_MAX_LEN = 4096

_DISCLAIMER = (
    "\n⚠️ 본 리포트는 과거 배당 데이터 기반이며 미래 배당 보장 아님. "
    "펀더멘털과 산업 환경 종합 검토 필요."
)


# ── 유틸 ─────────────────────────────────────────────────────────────────
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


def _fmt_dgr(dgr, estimated: bool) -> str:
    if dgr is None:
        return "N/A"
    flag = "~" if estimated else ""
    return f"{flag}{dgr:.0f}%"


def _accel_label(dgr5, dgr10) -> str:
    if dgr5 is None or dgr10 is None:
        return ""
    diff = dgr5 - dgr10
    if diff >= 2:
        return " (가속)"
    if diff <= -2:
        return " (둔화)"
    return ""


def _king_label(consec: int) -> str:
    if consec >= 50:
        return " 👑킹"
    if consec >= 25:
        return " 🏆귀족"
    if consec >= 10:
        return " ⭐챔피언"
    return ""


def _payout_str(payout) -> str:
    if payout is None:
        return "N/A"
    return f"{payout * 100:.0f}%"


# ── 메시지 행 생성 ──────────────────────────────────────────────────────
def _row(rank: int, r: dict) -> str:
    dgr10_s = _fmt_dgr(r.get("dgr10"), r.get("dgr10_estimated", False))
    dgr5_s  = _fmt_dgr(r.get("dgr5"),  r.get("dgr5_estimated",  False))
    accel   = _accel_label(r.get("dgr5"), r.get("dgr10"))
    consec  = r.get("consecutive_growth", 0)
    king    = _king_label(consec)
    cut_s   = " ✂컷" if r.get("had_cut") else ""
    yld     = r.get("yield_ttm") or 0
    payout  = _payout_str(r.get("payout_ratio"))

    line1 = (
        f"{rank}. <b>{r['ticker']}</b>  {r['score']:+.0f}  "
        f"10Y DGR {dgr10_s} / 5Y DGR {dgr5_s}{accel} / "
        f"{consec}년 연속{king}{cut_s}\n"
    )
    line2 = f"   Yield {yld:.1f}% / Payout {payout}\n"
    return line1 + line2


def _section(title: str, rows: list[dict], limit: int) -> str:
    if not rows:
        return f"\n{title}\n  (해당 종목 없음)\n"
    text = f"\n{title}\n"
    for i, r in enumerate(rows[:limit], 1):
        text += _row(i, r)
    return text


def _split_messages(text: str) -> list[str]:
    chunks, buf = [], ""
    for line in text.splitlines(keepends=True):
        if len(buf) + len(line) > _MAX_LEN:
            chunks.append(buf)
            buf = ""
        buf += line
    if buf:
        chunks.append(buf)
    return chunks


# ── 리포트 빌드 ─────────────────────────────────────────────────────────
def build_report(
    date_str: str, results: list[dict], holdings: list[str]
) -> list[str]:
    total = len(results)

    # ── 카테고리 분류 ────────────────────────────────────────────────
    # 1. 배당 성장 매력: DGR 10Y 기준 정렬, 배당 컷 없는 종목
    growth_top = sorted(
        [r for r in results if r.get("dgr10") is not None and not r.get("had_cut")],
        key=lambda r: (r.get("dgr10") or 0, r["score"]),
        reverse=True,
    )

    # 2. 배당 킹/귀족: 연속 25년+
    royalty = sorted(
        [r for r in results if r.get("consecutive_growth", 0) >= 25],
        key=lambda r: (r.get("consecutive_growth", 0), r["score"]),
        reverse=True,
    )

    # 3. 고배당: yield >= 3%, payout < 80%
    high_yield = sorted(
        [
            r for r in results
            if (r.get("yield_ttm") or 0) >= 3
            and (r.get("payout_ratio") is None or (r.get("payout_ratio") or 1) < 0.80)
        ],
        key=lambda r: r.get("yield_ttm") or 0,
        reverse=True,
    )

    # 4. 배당 컷 위험: 최근 컷 or payout > 90%
    risk = sorted(
        [
            r for r in results
            if r.get("had_cut")
            or (r.get("payout_ratio") is not None and (r.get("payout_ratio") or 0) > 0.9)
        ],
        key=lambda r: r.get("payout_ratio") or 0,
        reverse=True,
    )

    # 5. 보유 종목
    held_set     = set(holdings)
    held_results = [r for r in results if r["ticker"] in held_set]

    # ── 통계 ────────────────────────────────────────────────────────
    kings       = sum(1 for r in results if r.get("consecutive_growth", 0) >= 50)
    aristocrats = sum(1 for r in results if 25 <= r.get("consecutive_growth", 0) < 50)
    hi_cnt      = sum(1 for r in results if (r.get("yield_ttm") or 0) >= 3)

    header = (
        f"📊 <b>배당주 주간 리포트</b>\n"
        f"📅 {date_str}  |  분석: {total:,}개 배당 종목\n"
        f"👑 킹 {kings}개  🏆 귀족 {aristocrats}개  💰 고배당(3%+) {hi_cnt}개\n"
    )

    body = (
        _section("━━━ 🚀 <b>배당 성장 매력 TOP 15</b> ━━━", growth_top, 15)
        + _section("━━━ 🏆 <b>배당 킹/귀족 TOP 10</b> ━━━",  royalty,    10)
        + _section("━━━ 💰 <b>고배당 매력 TOP 10</b> ━━━",   high_yield, 10)
        + _section("━━━ ⚠️ <b>배당 컷 위험 TOP 5</b> ━━━",   risk,        5)
    )

    if held_results:
        body += _section(
            "━━━ ⭐ <b>내 보유 종목 배당 현황</b> ━━━",
            held_results,
            len(held_results),
        )

    body += _DISCLAIMER
    return _split_messages(header + body)


# ── 메인 ─────────────────────────────────────────────────────────────────
def main():
    t0 = datetime.now()
    print(f"\n{'='*50}")
    print(f"  배당주 주간 리포트 시작  {t0:%Y-%m-%d %H:%M:%S}")
    print(f"{'='*50}\n")

    print("▶ 종목 유니버스 로딩...")
    all_tickers, _ = get_universe()
    print(f"  완료: {len(all_tickers)}개\n")

    holdings = _load_holdings()
    if holdings:
        print(f"  보유 종목: {len(holdings)}개\n")

    results  = analyze_dividends(all_tickers)
    date_str = t0.strftime("%Y-%m-%d")

    # ── 캐시 저장 (app.py 표시용) ──────────────────────────────────────
    held_set = set(holdings)
    os.makedirs(CACHE_DIR, exist_ok=True)
    # 직렬화 불가 필드 제거 후 저장
    def _clean(r: dict) -> dict:
        return {k: v for k, v in r.items() if isinstance(v, (str, int, float, bool, type(None)))}

    cache = {
        "date":       date_str,
        "total":      len(results),
        "growth_top": [_clean(r) for r in sorted(
            [r for r in results if r.get("dgr10") is not None and not r.get("had_cut")],
            key=lambda r: (r.get("dgr10") or 0, r["score"]), reverse=True)[:15]],
        "royalty":    [_clean(r) for r in sorted(
            [r for r in results if r.get("consecutive_growth", 0) >= 25],
            key=lambda r: (r.get("consecutive_growth", 0), r["score"]), reverse=True)[:10]],
        "high_yield": [_clean(r) for r in sorted(
            [r for r in results if (r.get("yield_ttm") or 0) >= 3
             and (r.get("payout_ratio") is None or (r.get("payout_ratio") or 1) < 0.80)],
            key=lambda r: r.get("yield_ttm") or 0, reverse=True)[:10]],
        "risk":       [_clean(r) for r in sorted(
            [r for r in results if r.get("had_cut")
             or (r.get("payout_ratio") is not None and (r.get("payout_ratio") or 0) > 0.9)],
            key=lambda r: r.get("payout_ratio") or 0, reverse=True)[:5]],
        "holdings_data": [_clean(r) for r in results if r["ticker"] in held_set],
    }
    with open(os.path.join(CACHE_DIR, "last_dividend.json"), "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    print("  캐시 저장 완료 (cache/last_dividend.json)\n")

    messages = build_report(date_str, results, holdings)

    print(f"▶ 텔레그램 전송 중... (총 {len(messages)}개 메시지)")
    for i, msg in enumerate(messages, 1):
        ok     = send_message(msg)
        status = "✅ 성공" if ok else "❌ 실패"
        print(f"  메시지 {i}/{len(messages)}: {status}")

    elapsed = int((datetime.now() - t0).total_seconds() // 60)
    print(f"\n{'='*50}")
    print(f"  완료!  소요 시간: {elapsed}분")
    print(f"{'='*50}\n")


if __name__ == "__main__":
    main()
