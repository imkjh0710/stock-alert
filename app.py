"""
주식 시그널 분석 Streamlit 앱
실행: streamlit run app.py
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd
import streamlit as st
import yfinance as yf

# ── 경로 설정 ─────────────────────────────────────────────────────────
BASE_DIR     = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR))

SETTINGS_FILE   = BASE_DIR / "settings.json"
HOLDINGS_FILE   = BASE_DIR / "holdings.json"
LOGS_DIR        = BASE_DIR / "logs"
LAST_RESULTS    = BASE_DIR / "cache" / "last_results.json"
LAST_DIVIDEND   = BASE_DIR / "cache" / "last_dividend.json"

# ── 기본 설정값 ───────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "rsi_overbought":        70,
    "rsi_overbought_strong": 75,
    "rsi_oversold":          30,
    "rsi_oversold_strong":   25,
    "macd_fast":             12,
    "macd_slow":             26,
    "macd_signal":            9,
    "ma_short":              20,
    "ma_mid":                60,
    "ma_long":              200,
    "volume_t1":              2,
    "volume_t2":              3,
    "volume_t3":              5,
    "vp_window":             90,
}

# ── 유틸 함수 ─────────────────────────────────────────────────────────
def load_settings() -> dict:
    if SETTINGS_FILE.exists():
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return {**DEFAULT_SETTINGS, **json.load(f)}
    return DEFAULT_SETTINGS.copy()

def save_settings(s: dict):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(s, f, indent=2, ensure_ascii=False)

def load_holdings() -> list:
    if HOLDINGS_FILE.exists():
        with open(HOLDINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_holdings(h: list):
    with open(HOLDINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(h, f, indent=2, ensure_ascii=False)


# ══════════════════════════════════════════════════════════════════════
# 앱 전역 설정
# ══════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="📊 주식 시그널 분석",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── 봉차트 팝업 다이얼로그 ─────────────────────────────────────────────
@st.dialog("📈 봉차트 (최근 100일)", width="large")
def _show_chart(ticker: str):
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        st.error("plotly 패키지가 필요합니다: pip install plotly")
        return

    with st.spinner(f"{ticker} 데이터 로딩 중..."):
        try:
            raw = yf.download(ticker, period="8mo", auto_adjust=True, progress=False)
            if isinstance(raw.columns, pd.MultiIndex):
                try:
                    df = raw.xs(ticker, axis=1, level=1)
                except KeyError:
                    df = raw.xs(ticker, axis=1, level=0)
            else:
                df = raw
            df = df.dropna(how="all").tail(100)
        except Exception as e:
            st.error(f"데이터 로딩 실패: {e}")
            return

    if df.empty or len(df) < 5:
        st.warning("차트를 그릴 데이터가 부족합니다.")
        return

    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.03,
    )

    # 캔들스틱
    fig.add_trace(go.Candlestick(
        x=df.index,
        open=df["Open"], high=df["High"],
        low=df["Low"],   close=df["Close"],
        increasing_line_color="#26a69a",
        decreasing_line_color="#ef5350",
        name=ticker,
    ), row=1, col=1)

    # 이동평균선 (추세선)
    for n, color, dash, label in [
        (20,  "#ff9800", "solid", "MA20"),
        (60,  "#42a5f5", "solid", "MA60"),
        (200, "#ec407a", "dash",  "MA200"),
    ]:
        ma = df["Close"].rolling(n).mean()
        if ma.notna().sum() >= 5:
            fig.add_trace(go.Scatter(
                x=df.index, y=ma,
                line=dict(color=color, width=1.3, dash=dash),
                name=label, opacity=0.9,
            ), row=1, col=1)

    # 거래량
    vol_colors = [
        "#26a69a" if float(c) >= float(o) else "#ef5350"
        for c, o in zip(df["Close"], df["Open"])
    ]
    fig.add_trace(go.Bar(
        x=df.index, y=df["Volume"],
        marker_color=vol_colors,
        name="거래량", showlegend=False,
    ), row=2, col=1)

    fig.update_layout(
        xaxis_rangeslider_visible=False,
        height=530,
        margin=dict(l=0, r=0, t=8, b=0),
        legend=dict(orientation="h", y=1.02, x=0, font=dict(size=11)),
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font=dict(color="#e0e0e0"),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#2a2a3a", zeroline=False)

    st.markdown(f"**{ticker}** — 최근 {len(df)}거래일  |  MA20 🟠 MA60 🔵 MA200 🩷")
    st.plotly_chart(fig, use_container_width=True)


with st.sidebar:
    st.markdown("## 📊 주식 시그널 분석")
    st.markdown("---")
    page = st.radio(
        "페이지",
        ["⚙️ 지표 설정", "📋 보유 종목", "🚀 분석 실행", "💰 배당 분석", "📁 리포트 기록"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("Russell 3000 + S&P 500 기반\n매일 오전 6:30 자동 실행")


# ══════════════════════════════════════════════════════════════════════
# 1. 지표 설정
# ══════════════════════════════════════════════════════════════════════
if page == "⚙️ 지표 설정":
    st.title("⚙️ 지표 설정")
    st.caption("변경 후 저장하면 다음 분석 실행부터 반영됩니다.")

    settings = load_settings()
    new: dict = {}

    h1, h2, h3 = st.columns([5, 2, 4])
    h1.markdown("**지표명**")
    h2.markdown("**현재 값**")
    h3.markdown("**변경 입력**")
    st.markdown('<hr style="margin:6px 0 10px">', unsafe_allow_html=True)

    def row(label: str, key: str, lo: int, hi: int, step: int = 1):
        c1, c2, c3 = st.columns([5, 2, 4])
        c1.write(label)
        c2.markdown(f"`{settings[key]}`")
        new[key] = int(c3.number_input(
            label, value=int(settings[key]),
            min_value=lo, max_value=hi, step=step,
            key=f"s_{key}", label_visibility="collapsed",
        ))

    st.markdown("#### RSI 임계값")
    row("과매수 기준  →  매도 -2점",       "rsi_overbought",        60, 99)
    row("과매수 강한 기준  →  매도 -4점",  "rsi_overbought_strong", 60, 99)
    row("과매도 기준  →  매수 +2점",       "rsi_oversold",           1, 40)
    row("과매도 강한 기준  →  매수 +4점",  "rsi_oversold_strong",    1, 40)

    st.markdown("#### MACD")
    row("Fast EMA 기간",  "macd_fast",    2,  50)
    row("Slow EMA 기간",  "macd_slow",    5, 100)
    row("Signal 기간",    "macd_signal",  2,  30)

    st.markdown("#### 이동평균선")
    row("단기 MA",  "ma_short",   5,  50)
    row("중기 MA",  "ma_mid",    20, 120)
    row("장기 MA",  "ma_long",   50, 500)

    st.markdown("#### 거래량 임계 배수  (가격 ±2% 조건 함께 충족 시)")
    row("1단계 배수  →  ±2점",  "volume_t1",  1, 10)
    row("2단계 배수  →  ±3점",  "volume_t2",  2, 20)
    row("3단계 배수  →  ±4점",  "volume_t3",  3, 30)

    st.markdown("#### 매물대 (Volume Profile)")
    row("분석 윈도우 (영업일)",  "vp_window",  20, 252)

    st.markdown("---")
    c_save, c_reset, _ = st.columns([2, 2, 6])

    if c_save.button("💾 저장", type="primary", use_container_width=True):
        save_settings(new)
        st.success("✅ 저장 완료. 다음 분석부터 반영됩니다.")

    if c_reset.button("🔄 기본값 초기화", use_container_width=True):
        save_settings(DEFAULT_SETTINGS)
        for k in DEFAULT_SETTINGS:
            st.session_state.pop(f"s_{k}", None)
        st.success("✅ 기본값으로 초기화했습니다.")
        st.rerun()


# ══════════════════════════════════════════════════════════════════════
# 2. 보유 종목
# ══════════════════════════════════════════════════════════════════════
elif page == "📋 보유 종목":
    st.title("📋 보유 종목 관리")
    holdings = load_holdings()

    # 현재 점수 조회
    scores: dict = {}
    if holdings:
        with st.spinner("보유 종목 최신 점수 조회 중..."):
            try:
                from fetcher import fetch_batch, apply_quality_filter
                from scorer import score_all
                tickers = [h["ticker"] for h in holdings]
                raw      = fetch_batch(tickers, period="1y", chunk_size=max(len(tickers), 1))
                filtered = apply_quality_filter(raw)
                scores   = {r["ticker"]: r for r in score_all(filtered)}
            except Exception:
                pass

    # 배당 캐시 로드
    div_map: dict = {}
    if LAST_DIVIDEND.exists():
        try:
            with open(LAST_DIVIDEND, encoding="utf-8") as f:
                _dc = json.load(f)
            for _r in _dc.get("holdings_data", []):
                div_map[_r["ticker"]] = _r
            for _cat in ("growth_top", "royalty", "high_yield", "risk"):
                for _r in _dc.get(_cat, []):
                    if _r["ticker"] not in div_map:
                        div_map[_r["ticker"]] = _r
        except Exception:
            pass

    # 종목 목록
    if not holdings:
        st.info("등록된 보유 종목이 없습니다. 아래에서 추가해주세요.")
    else:
        st.caption("티커 옆 📊 버튼을 누르면 봉차트 팝업이 열립니다.")
        st.markdown(f"**총 {len(holdings)}개 종목**")
        for col, label in zip(
            st.columns([2, 5, 4, 3, 1, 1]),
            ["**티커**", "**종목명**", "**등급**", "**점수**", "", ""],
        ):
            col.markdown(label)
        st.divider()

        delete_idx = None
        for i, h in enumerate(holdings):
            sc = scores.get(h["ticker"])
            c1, c2, c3, c4, c5, c6 = st.columns([2, 5, 4, 3, 1, 1])
            c1.write(h["ticker"])
            c2.write(h.get("name", "—"))
            c3.write(sc["grade"] if sc else "—")
            c4.write(f"{sc['score']:+.1f}" if sc else "—")
            if c5.button("📊", key=f"chart_{i}", help="봉차트 보기"):
                _show_chart(h["ticker"])
            if c6.button("🗑️", key=f"del_{i}", help="삭제"):
                delete_idx = i

        if delete_idx is not None:
            holdings.pop(delete_idx)
            save_holdings(holdings)
            st.rerun()

        # 배당 현황 테이블
        st.markdown("---")
        st.markdown("#### 💰 보유 종목 배당 현황")
        if not div_map:
            st.caption("배당 데이터 없음 — 매일 22:00 KST 자동 업데이트됩니다.")
        else:
            div_records = []
            for h in holdings:
                t  = h["ticker"]
                dr = div_map.get(t)
                if dr is None:
                    div_records.append({
                        "티커": t, "배당등급": "—", "배당점수": "—",
                        "배당률(TTM)": "—", "10Y DGR": "—", "5Y DGR": "—",
                        "연속증가": "—", "Payout": "—", "배당컷": "—",
                    })
                    continue
                consec = dr.get("consecutive_growth", 0)
                if   consec >= 50: king = "👑킹"
                elif consec >= 25: king = "🏆귀족"
                elif consec >= 10: king = "⭐챔피언"
                else:              king = ""
                dgr10  = dr.get("dgr10")
                dgr5   = dr.get("dgr5")
                payout = dr.get("payout_ratio")
                div_records.append({
                    "티커":        t,
                    "배당등급":    dr.get("grade", "—"),
                    "배당점수":    f"{dr['score']:+.0f}",
                    "배당률(TTM)": f"{dr.get('yield_ttm', 0):.1f}%",
                    "10Y DGR":    f"{dgr10:.0f}%" if dgr10 is not None else "N/A",
                    "5Y DGR":     f"{dgr5:.0f}%"  if dgr5  is not None else "N/A",
                    "연속증가":    f"{consec}년 {king}".strip(),
                    "Payout":     f"{payout*100:.0f}%" if payout is not None else "N/A",
                    "배당컷":      "✂컷" if dr.get("had_cut") else "—",
                })
            if div_records:
                st.caption("행을 클릭하면 해당 종목 봉차트가 열립니다.")
                evt = st.dataframe(
                    pd.DataFrame(div_records),
                    use_container_width=True, hide_index=True,
                    on_select="rerun", selection_mode="single-row",
                    key="hold_div_tbl",
                )
                if evt.selection.rows:
                    _show_chart(div_records[evt.selection.rows[0]]["티커"])
            else:
                st.caption("보유 종목이 배당 데이터에 없습니다.")

    # 종목 추가
    st.markdown("---")
    st.markdown("#### ➕ 종목 추가")
    c1, c2 = st.columns([4, 1])
    ticker_in = c1.text_input("티커 입력 (예: AAPL, NVDA)", key="add_ticker").strip().upper()

    if c2.button("추가", type="primary", use_container_width=True):
        if not ticker_in:
            st.warning("티커를 입력해주세요.")
        elif any(h["ticker"] == ticker_in for h in holdings):
            st.warning(f"**{ticker_in}** 은(는) 이미 등록되어 있습니다.")
        else:
            with st.spinner(f"{ticker_in} 정보 조회 중..."):
                try:
                    info  = yf.Ticker(ticker_in).info
                    name  = info.get("longName") or info.get("shortName") or ticker_in
                    price = info.get("regularMarketPrice") or info.get("currentPrice") or info.get("previousClose")
                    if price:
                        holdings.append({"ticker": ticker_in, "name": name})
                        save_holdings(holdings)
                        st.success(f"✅ **{ticker_in}** ({name}) 추가됨")
                        st.rerun()
                    else:
                        st.error(f"❌ **{ticker_in}**: 유효하지 않은 티커입니다.")
                except Exception as e:
                    st.error(f"❌ 조회 실패: {e}")


# ══════════════════════════════════════════════════════════════════════
# 3. 분석 실행
# ══════════════════════════════════════════════════════════════════════
elif page == "🚀 분석 실행":
    st.title("🚀 분석 실행")
    st.caption("Russell 3000 전체 종목을 분석해 텔레그램으로 전송합니다.")

    c1, c2 = st.columns([2, 8])
    run_btn = c1.button("▶ 지금 분석 돌리기", type="primary", use_container_width=True)
    c2.info("⏱ 첫 실행 ~20분  /  캐시 있을 때 ~2분  /  실행 중 페이지 이동 시 중단됩니다.")

    if run_btn:
        log_box = st.empty()
        lines: list[str] = []
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

        proc = subprocess.Popen(
            [sys.executable, str(BASE_DIR / "main.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            bufsize=1,
            cwd=str(BASE_DIR),
            env=env,
        )
        t0 = time.time()
        for line in proc.stdout:
            lines.append(line)
            log_box.code("".join(lines[-40:]), language="")
        proc.wait()
        elapsed = int(time.time() - t0)

        if proc.returncode == 0:
            st.success(f"✅ 분석 완료! (소요 {elapsed // 60}분 {elapsed % 60}초)")
            st.rerun()
        else:
            st.error("❌ 오류 발생. 위 로그를 확인해주세요.")

    # 마지막 분석 결과 표
    if LAST_RESULTS.exists():
        st.markdown("---")
        st.markdown("### 📊 마지막 분석 결과")
        with open(LAST_RESULTS, encoding="utf-8") as f:
            last = json.load(f)

        st.caption(
            f"분석일: **{last.get('date', '—')}**  |  "
            f"분석 종목: **{last.get('total', 0):,}개**  |  "
            "행을 클릭하면 봉차트 팝업이 열립니다."
        )

        tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs(
            ["🏆 S&P 500 매수 TOP 25", "🔻 S&P 500 매도 TOP 25",
             "📊 ETF 매수 TOP 10",     "🔻 ETF 매도 TOP 10",
             "💎 외곽 매수 TOP 15",    "🔻 외곽 매도 TOP 15"]
        )
        for tab, key in zip(
            [tab1, tab2, tab3, tab4, tab5, tab6],
            ["sp500_buy", "sp500_sell", "etf_buy", "etf_sell", "outer_buy", "outer_sell"],
        ):
            with tab:
                rows = last.get(key, [])
                if rows:
                    records = []
                    for r in rows:
                        pred = r.get("prediction") or {}
                        lo   = pred.get("short_lo_68")
                        hi   = pred.get("short_hi_68")
                        week = f"${lo:.0f}~${hi:.0f}" if lo is not None and hi is not None else "—"
                        records.append({
                            "티커":    r["ticker"],
                            "합산":    f"{r['score']:+.1f}",
                            "장타":    f"{r.get('long_score',  0):+.0f}",
                            "단타":    f"{r.get('short_score', 0):+.0f}",
                            "추천":    r.get("recommendation", "—"),
                            "등급":    r["grade"],
                            "종가($)": r["close"],
                            "등락(%)": f"{r['change_pct']:+.1f}%",
                            "1주범위": week,
                        })
                    evt = st.dataframe(
                        pd.DataFrame(records),
                        use_container_width=True, hide_index=True,
                        on_select="rerun", selection_mode="single-row",
                        key=f"tbl_{key}",
                    )
                    if evt.selection.rows:
                        _show_chart(records[evt.selection.rows[0]]["티커"])
                else:
                    st.info("해당 항목 없음 (관망 구간에 속하는 종목만 있거나 데이터 없음)")
    else:
        st.info("아직 분석 기록이 없습니다. 위 버튼을 눌러 첫 분석을 실행해보세요.")


# ══════════════════════════════════════════════════════════════════════
# 4. 배당 분석
# ══════════════════════════════════════════════════════════════════════
elif page == "💰 배당 분석":
    st.title("💰 배당주 일일 리포트")

    if not LAST_DIVIDEND.exists():
        st.info("아직 배당 분석 기록이 없습니다. 매일 22:00 KST에 자동 실행됩니다.")
    else:
        with open(LAST_DIVIDEND, encoding="utf-8") as f:
            div_data = json.load(f)

        st.caption(
            f"분석일: **{div_data.get('date', '—')}**  |  "
            f"배당 지급 종목: **{div_data.get('total', 0):,}개**  |  "
            "행을 클릭하면 봉차트 팝업이 열립니다."
        )

        def _div_table(rows: list, tbl_key: str) -> None:
            if not rows:
                st.info("해당 항목 없음")
                return
            records = []
            for r in rows:
                consec = r.get("consecutive_growth", 0)
                if   consec >= 50: king = "👑킹"
                elif consec >= 25: king = "🏆귀족"
                elif consec >= 10: king = "⭐챔피언"
                else:              king = ""
                dgr10  = r.get("dgr10")
                dgr5   = r.get("dgr5")
                payout = r.get("payout_ratio")
                records.append({
                    "티커":         r["ticker"],
                    "등급":         r.get("grade", "—"),
                    "점수":         f"{r['score']:+.0f}",
                    "10Y DGR":     f"{dgr10:.0f}%" if dgr10 is not None else "N/A",
                    "5Y DGR":      f"{dgr5:.0f}%"  if dgr5  is not None else "N/A",
                    "연속증가":     f"{consec}년 {king}".strip(),
                    "배당률(TTM)": f"{r.get('yield_ttm', 0):.1f}%",
                    "Payout":      f"{payout*100:.0f}%" if payout is not None else "N/A",
                    "배당컷":       "✂컷" if r.get("had_cut") else "—",
                })
            evt = st.dataframe(
                pd.DataFrame(records),
                use_container_width=True, hide_index=True,
                on_select="rerun", selection_mode="single-row",
                key=tbl_key,
            )
            if evt.selection.rows:
                _show_chart(records[evt.selection.rows[0]]["티커"])

        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "🚀 배당 성장 TOP 15",
            "🏆 킹/귀족 TOP 10",
            "💰 고배당 TOP 10",
            "⚠️ 배당 컷 위험",
            "⭐ 내 보유 종목",
        ])
        with tab1:
            _div_table(div_data.get("growth_top", []), "div_growth")
        with tab2:
            _div_table(div_data.get("royalty", []),    "div_royalty")
        with tab3:
            _div_table(div_data.get("high_yield", []), "div_yield")
        with tab4:
            _div_table(div_data.get("risk", []),       "div_risk")
        with tab5:
            held = div_data.get("holdings_data", [])
            if held:
                _div_table(held, "div_held")
            else:
                st.info("보유 종목 배당 데이터가 없습니다. 보유 종목을 등록하거나 배당 분석을 실행해주세요.")


# ══════════════════════════════════════════════════════════════════════
# 5. 리포트 기록
# ══════════════════════════════════════════════════════════════════════
elif page == "📁 리포트 기록":
    st.title("📁 리포트 기록")

    LOGS_DIR.mkdir(exist_ok=True)
    log_files = sorted(LOGS_DIR.glob("*.log"), reverse=True)

    if not log_files:
        st.info("저장된 로그 파일이 없습니다. 분석을 실행하면 logs/ 폴더에 자동 저장됩니다.")
    else:
        c1, c2 = st.columns([1, 3])
        with c1:
            st.markdown(f"**{len(log_files)}개 파일**")
            selected = st.radio(
                "날짜 선택",
                [f.name for f in log_files],
                label_visibility="collapsed",
            )
        with c2:
            content = (LOGS_DIR / selected).read_text(encoding="utf-8", errors="replace")
            st.markdown(f"#### 📄 {selected}")
            st.code(content, language="")
