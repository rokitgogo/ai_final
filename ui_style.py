"""
NCS 포트폴리오 - 세련된 UI 스타일
최신 웹 서비스 느낌의 전문적 Color Palette & Spacing
"""

import streamlit as st

# ═══════════════════════════════════════════════════════════════════
# Color Palette (Slate + Indigo - 전문적이고 신뢰감)
# ═══════════════════════════════════════════════════════════════════
P = {
    "primary": "#1e3a5f",      # Deep Slate Blue - 메인 액센트
    "primary_hover": "#2d4a6f",
    "primary_muted": "rgba(30, 58, 95, 0.08)",
    "accent": "#0ea5e9",      # Sky - 강조, 링크, CTA
    "accent_soft": "#38bdf8",
    "accent_glow": "rgba(14, 165, 233, 0.12)",
    "bg": "#f1f5f9",          # Slate-100 기반
    "bg_deep": "#e8eef4",
    "bg_elevated": "#ffffff",  # 카드/패널
    "text": "#0f172a",        # Slate-900 - 본문
    "text_secondary": "#64748b",  # Slate-500
    "text_muted": "#94a3b8",  # Slate-400
    "border": "#e2e8f0",      # Slate-200
    "border_light": "#f1f5f9",  # Slate-100
    "success": "#059669",     # Emerald - 성공/긍정
    "shadow_sm": "0 1px 2px 0 rgb(15 23 42 / 0.04)",
    "shadow": "0 4px 14px -2px rgb(15 23 42 / 0.07), 0 2px 6px -2px rgb(15 23 42 / 0.05)",
    "shadow_lg": "0 12px 32px -8px rgb(15 23 42 / 0.12), 0 4px 12px -4px rgb(15 23 42 / 0.06)",
    "card_hover": "0 8px 24px -6px rgb(30 58 95 / 0.12)",
}

# Spacing Scale (px) - 일관된 여백 (넉넉한 여백으로 가독성 향상)
S = {
    "xs": "6px",
    "sm": "12px",
    "md": "20px",
    "lg": "28px",
    "xl": "36px",
    "2xl": "56px",
}


def render_app_footer() -> None:
    """모든 화면 하단 전문 워터마크 (회색 톤)."""
    st.markdown(
        """
        <div class="app-footer-watermark">용산철도고 NCS 직무 포트폴리오 시스템</div>
        """,
        unsafe_allow_html=True,
    )


def apply_advanced_ui() -> None:
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;500;600;700&family=DM+Sans:ital,opsz,wght@0,9..40,500;0,9..40,600;0,9..40,700&display=swap');

        .app-footer-watermark {{
            text-align: center;
            font-size: 0.8rem;
            color: {P["text_muted"]};
            padding: {S["xl"]} 0 {S["md"]};
            margin-top: {S["2xl"]};
            border-top: 1px solid {P["border_light"]};
            letter-spacing: 0.02em;
        }}

        /* ─── Base ─── */
        .stApp {{
            background:
                radial-gradient(ellipse 120% 80% at 100% -20%, rgba(14, 165, 233, 0.09) 0%, transparent 50%),
                radial-gradient(ellipse 90% 60% at -10% 30%, rgba(30, 58, 95, 0.06) 0%, transparent 45%),
                linear-gradient(180deg, {P["bg"]} 0%, {P["bg_deep"]} 55%, #eef2f7 100%);
            color: {P["text"]};
            font-family: 'Noto Sans KR', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            -webkit-font-smoothing: antialiased;
        }}

        /* 상단 툴바: 글래스 느낌 */
        header[data-testid="stHeader"] {{
            background: rgba(255, 255, 255, 0.72) !important;
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border-bottom: 1px solid {P["border_light"]};
        }}
        [data-testid="stToolbar"] {{
            background: transparent !important;
        }}

        /* ─── Layout & Spacing (학술·연구 UI: 여백 넉넉, 차분한 리듬) ─── */
        div.block-container {{
            padding-top: 2.25rem;
            padding-bottom: 3rem;
            padding-left: clamp(1.25rem, 4vw, 2.5rem);
            padding-right: clamp(1.25rem, 4vw, 2.5rem);
            max-width: 1180px;
        }}

        /* ─── Login (로그인 전용 셸) ─── */
        .login-page-outer {{
            max-width: 480px;
            margin: 0 auto 1.5rem;
            padding: {S["md"]} {S["sm"]};
        }}
        .login-page-card {{
            background: linear-gradient(165deg, rgba(255,255,255,0.95) 0%, rgba(248,250,252,0.98) 100%);
            border: 1px solid {P["border"]};
            border-radius: 18px;
            box-shadow: {P["shadow_lg"]};
            padding: {S["xl"]} {S["xl"]} {S["lg"]};
        }}
        /* Streamlit 컬럼이 카드 안에서 자연스럽게 보이도록 */
        .login-page-card [data-testid="column"] {{
            min-width: 0;
        }}
        h1.login-title {{
            font-family: 'Noto Sans KR', sans-serif !important;
            font-size: 1.65rem !important;
            font-weight: 700 !important;
            letter-spacing: -0.03em !important;
            color: {P["primary"]} !important;
            margin: 0 0 0.5rem !important;
            text-align: center;
            line-height: 1.3 !important;
        }}
        p.login-subtitle {{
            font-family: 'Noto Sans KR', sans-serif !important;
            font-size: 0.95rem !important;
            color: {P["text_secondary"]} !important;
            letter-spacing: -0.01em;
            margin: 0 auto !important;
            max-width: 28em;
            text-align: center;
            line-height: 1.55 !important;
        }}

        /* ─── Sidebar ─── */
        section[data-testid="stSidebar"] {{
            background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%) !important;
        }}
        section[data-testid="stSidebar"] > div {{
            background: transparent !important;
            border-right: 1px solid {P["border"]};
            box-shadow: {P["shadow"]};
            padding: {S["lg"]} {S["md"]};
        }}
        section[data-testid="stSidebar"] h3 {{
            font-size: 1.02rem !important;
            letter-spacing: -0.02em;
            padding-bottom: 0.35rem;
            border-bottom: 1px solid {P["border_light"]};
            margin-bottom: 0.65rem !important;
        }}
        section[data-testid="stSidebar"] .stMarkdown {{
            margin-bottom: {S["sm"]};
        }}
        section[data-testid="stSidebar"] [data-testid="stMetric"] {{
            padding: 0.65rem 0.85rem !important;
        }}

        /* ─── Cards (report-card) - 대시보드 스타일 (내부 여백 넉넉) ─── */
        .report-card {{
            background: linear-gradient(180deg, #ffffff 0%, #fcfdfe 100%);
            padding: 2rem 2.25rem;
            border-radius: 14px;
            border: 1px solid {P["border"]};
            box-shadow: {P["shadow"]};
            margin-bottom: {S["lg"]};
        }}
        /* 탭 내부 report-card: 일정한 간격 유지, 끊김 없는 레이아웃 */
        .report-card-tab {{
            margin-bottom: {S["lg"]};
            padding: {S["lg"]} {S["xl"]};
            transition: box-shadow 0.2s ease, border-color 0.2s ease;
            border-radius: 14px;
            border: 1px solid {P["border"]};
            background: {P["bg_elevated"]};
            box-shadow: {P["shadow_sm"]};
        }}
        .report-card-tab:hover {{
            box-shadow: {P["shadow"]};
            border-color: rgba(14, 165, 233, 0.22);
        }}
        .report-card-tab + .report-card-tab {{
            margin-top: 0;
        }}
        div[data-baseweb="tab-panel"] .report-card-tab {{
            margin-bottom: {S["lg"]};
        }}
        .report-card-inner {{
            padding: 1.25rem 1.35rem;
            font-size: 0.95rem;
            line-height: 1.7;
            background: rgba(248, 250, 252, 0.6);
            border-radius: 6px;
            margin-top: {S["sm"]};
        }}
        /* 섹션 구분용 (박스 없이 여백만) */
        .section-spacer {{
            margin-bottom: {S["lg"]};
        }}

        /* ─── Typography (가독성·학술 톤: 과장 없는 크기·행간) ─── */
        h1, h2, h3, h4 {{
            color: {P["primary"]};
            font-weight: 600;
            letter-spacing: -0.02em;
            line-height: 1.38;
        }}
        h1 {{ font-size: 1.65rem; margin-bottom: 1rem; margin-top: 0.25rem; }}
        h2 {{ font-size: 1.35rem; margin-bottom: 0.65rem; }}
        h3 {{ font-size: 1.12rem; margin-bottom: 0.5rem; }}
        h4 {{ font-size: 1rem; margin-bottom: 0.4rem; }}
        /* Streamlit 기본 헤딩 (st.title / st.header / st.subheader) */
        [data-testid="stHeader"] h1, div[data-testid="stDecoration"] + div h1 {{
            font-size: 1.55rem !important;
            font-weight: 600 !important;
            color: {P["primary"]} !important;
            letter-spacing: -0.02em !important;
        }}
        .main h1 {{ font-size: 1.55rem !important; }}
        .main h2 {{ font-size: 1.28rem !important; }}
        .main h3 {{ font-size: 1.08rem !important; }}
        .stMarkdown, .stText, .stCaption, .stTextInput label, .stTextArea label {{
            color: {P["text"]} !important;
            line-height: 1.65 !important;
        }}
        p, .stMarkdown p {{ color: {P["text"]}; line-height: 1.72; font-size: 1rem; }}
        .main a {{ color: {P["accent"]} !important; text-decoration: none; font-weight: 500; }}
        .main a:hover {{ text-decoration: underline; color: #0284c7 !important; }}

        /* ─── Buttons (눌리는 효과 + 로딩 피드백) ─── */
        .stButton > button {{
            border-radius: 12px;
            padding: {S["sm"]} {S["lg"]};
            font-weight: 600;
            letter-spacing: 0.01em;
            transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
        }}
        .stButton > button:active {{
            transform: scale(0.98);
        }}
        .stButton > button:disabled {{
            opacity: 0.7;
            cursor: not-allowed;
        }}
        .stButton > button[kind="secondary"] {{
            border: 1px solid {P["border"]} !important;
            background: {P["bg_elevated"]} !important;
            color: {P["primary"]} !important;
        }}
        .stButton > button[kind="secondary"]:hover:not(:disabled) {{
            border-color: rgba(14, 165, 233, 0.45) !important;
            background: {P["accent_glow"]} !important;
        }}
        .stButton > button[kind="primary"] {{
            background: linear-gradient(135deg, {P["primary"]} 0%, #2d4a6f 100%);
            border: none;
            color: white;
            box-shadow: 0 4px 14px rgba(30, 58, 95, 0.28);
        }}
        .stButton > button[kind="primary"]:hover:not(:disabled) {{
            background: linear-gradient(135deg, {P["primary_hover"]} 0%, #3d5a7f 100%);
            box-shadow: 0 6px 20px rgba(30, 58, 95, 0.25);
        }}

        /* ─── Inputs ─── */
        .stTextInput input, .stTextArea textarea {{
            border-radius: 12px;
            border: 1px solid {P["border"]};
            padding: 0.65rem 1rem;
            transition: border-color 0.15s ease, box-shadow 0.15s ease;
        }}
        .stTextInput input:focus, .stTextArea textarea:focus {{
            border-color: {P["accent"]};
            box-shadow: 0 0 0 3px rgba(14, 165, 233, 0.18);
            outline: none;
        }}

        /* ─── Select / Multiselect / File uploader ─── */
        [data-baseweb="select"] > div {{
            border-radius: 12px !important;
            border-color: {P["border"]} !important;
        }}
        [data-testid="stFileUploader"] section {{
            border-radius: 14px !important;
            border: 2px dashed rgba(30, 58, 95, 0.25) !important;
            background: {P["primary_muted"]} !important;
            padding: 1rem !important;
            transition: border-color 0.2s ease, background 0.2s ease;
        }}
        [data-testid="stFileUploader"]:hover section {{
            border-color: rgba(14, 165, 233, 0.45) !important;
            background: {P["accent_glow"]} !important;
        }}
        [data-testid="stAudioInput"] {{
            border-radius: 12px;
        }}

        /* ─── Checkbox / Radio ─── */
        .stCheckbox label, .stRadio label {{
            font-weight: 500;
        }}

        /* ─── NCS Tag ─── */
        .ncs-tag {{
            background: linear-gradient(135deg, {P["primary"]} 0%, {P["accent"]} 100%);
            color: white;
            padding: {S["xs"]} {S["md"]};
            border-radius: 9999px;
            font-size: 0.8125rem;
            font-weight: 600;
        }}

        /* ─── Progress Bar ─── */
        .stProgress > div > div > div > div {{
            background: linear-gradient(90deg, {P["primary"]} 0%, {P["accent"]} 100%);
        }}

        /* ─── Glossary Box ─── */
        .glossary-box {{
            background: linear-gradient(90deg, rgba(14, 165, 233, 0.06) 0%, transparent 100%);
            border-left: 4px solid {P["accent"]};
            padding: {S["md"]} {S["lg"]};
            margin: {S["md"]} 0;
            border-radius: 0 8px 8px 0;
            color: {P["text"]};
        }}

        /* ─── 역량 레이더·AI 정합성 경고 (시각적 정돈) ─── */
        div[data-testid="stAlert"] {{
            border-radius: 10px;
            border: 1px solid {P["border_light"]};
        }}
        .radar-chart-caption {{
            font-size: 0.8rem;
            color: {P["text_secondary"]};
            margin-top: 0.35rem;
        }}

        /* ─── 실습 맞춤형 AI 코칭 (전자과 상담 레이아웃) ─── */
        .ai-coaching-panel {{
            background: rgba(255, 255, 255, 0.92);
            border: 1px solid {P["border"]};
            border-radius: 10px;
            padding: {S["lg"]} {S["xl"]};
            margin: {S["md"]} 0 {S["lg"]} 0;
            box-shadow: {P["shadow_sm"]};
        }}
        ol.ai-coaching-qlist {{
            margin: 0.45rem 0 0.85rem 1.15rem;
            padding: 0;
            line-height: 1.68;
            color: {P["text"]};
            font-size: 0.94rem;
        }}
        ol.ai-coaching-qlist li {{
            margin-bottom: 0.4rem;
        }}
        .ai-coaching-reflection-label {{
            margin: 0.85rem 0 0.3rem 0;
            font-size: 0.8rem;
            color: {P["text_secondary"]};
            letter-spacing: 0.02em;
        }}
        .ai-coaching-reflection-box {{
            border-left: 3px solid {P["primary"]};
            background: #f8fafc;
            padding: 0.85rem 1rem;
            border-radius: 0 8px 8px 0;
            font-size: 0.94rem;
            line-height: 1.72;
            color: {P["text"]};
        }}

        /* ─── Logo ─── */
        .school-logo-container {{
            display: flex;
            justify-content: center;
            align-items: center;
            margin-bottom: {S["lg"]};
        }}
        .header-title {{
            font-size: 1.75rem;
            font-weight: 700;
            color: {P["primary"]};
            letter-spacing: -0.03em;
            margin-bottom: {S["sm"]};
        }}

        /* ─── Dividers & Metrics ─── */
        hr {{
            border: none;
            border-top: 1px solid {P["border_light"]};
            margin: {S["lg"]} 0;
            opacity: 0.85;
        }}

        /* ─── Tabs (세그먼트 스타일) ─── */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 6px;
            margin-bottom: 1.25rem;
            padding: 6px;
            background: {P["primary_muted"]};
            border-radius: 14px;
            border: none !important;
            border-bottom: none !important;
        }}
        .stTabs [data-baseweb="tab"] {{
            padding: 0.55rem 1.1rem;
            border-radius: 10px;
            font-weight: 600;
            font-size: 0.9rem;
            color: {P["text_secondary"]};
            border: none !important;
            margin: 0 !important;
        }}
        .stTabs [data-baseweb="tab"]:hover {{
            color: {P["primary"]};
            background: rgba(255, 255, 255, 0.65);
        }}
        .stTabs [aria-selected="true"] {{
            color: {P["primary"]} !important;
            background: #ffffff !important;
            box-shadow: {P["shadow_sm"]};
        }}
        div[data-baseweb="tab-panel"] {{
            padding-top: {S["md"]};
            min-height: 200px;
        }}

        /* ─── Expanders ─── */
        .streamlit-expanderHeader {{
            border-radius: 12px;
            font-weight: 600;
            background: {P["primary_muted"]};
            border: 1px solid {P["border_light"]};
        }}
        details[open] > summary .streamlit-expanderHeader {{
            border-bottom-left-radius: 0;
            border-bottom-right-radius: 0;
        }}

        /* ─── Caption ─── */
        .stCaption {{
            color: {P["text_secondary"]} !important;
            font-size: 0.8rem !important;
            line-height: 1.55 !important;
        }}

        /* ─── 스크롤바 (WebKit) ─── */
        ::-webkit-scrollbar {{
            width: 10px;
            height: 10px;
        }}
        ::-webkit-scrollbar-track {{
            background: {P["border_light"]};
            border-radius: 8px;
        }}
        ::-webkit-scrollbar-thumb {{
            background: #cbd5e1;
            border-radius: 8px;
        }}
        ::-webkit-scrollbar-thumb:hover {{
            background: #94a3b8;
        }}

        /* ─── Dataframes (메인 컬러 조화) ─── */
        .stDataFrame {{
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid rgba(30, 58, 95, 0.12);
            box-shadow: {P["shadow_sm"]};
        }}
        .stDataFrame thead th {{
            background: linear-gradient(180deg, {P["primary"]} 0%, #2d4a6f 100%) !important;
            color: white !important;
            font-weight: 600 !important;
            padding: 0.65rem 0.85rem !important;
        }}
        .stDataFrame tbody td {{
            padding: 0.5rem 0.75rem !important;
        }}

        /* Plotly 차트 영역 */
        [data-testid="stPlotlyChart"] {{
            border-radius: 14px;
            overflow: hidden;
            border: 1px solid {P["border_light"]};
            background: #ffffff;
            box-shadow: {P["shadow_sm"]};
        }}

        /* ─── Metrics (st.metric) ─── */
        [data-testid="stMetric"] {{
            padding: 1rem 1.15rem;
            border-radius: 12px;
            border: 1px solid {P["border_light"]};
            border-left: 4px solid {P["accent"]};
            background: linear-gradient(135deg, #ffffff 0%, #f8fafc 100%);
            box-shadow: {P["shadow_sm"]};
        }}
        [data-testid="stMetric"] label {{
            color: {P["text_secondary"]} !important;
            font-weight: 600 !important;
            font-size: 0.8rem !important;
            text-transform: none;
            letter-spacing: 0.02em;
        }}
        [data-testid="stMetric"] [data-testid="stMetricValue"] {{
            color: {P["primary"]} !important;
            font-weight: 700 !important;
            font-family: 'DM Sans', 'Noto Sans KR', sans-serif !important;
            font-variant-numeric: tabular-nums;
        }}

        /* ─── Info/Warning Boxes ─── */
        [data-testid="stAlert"] {{
            border-radius: 10px;
        }}

        /* ─── 포트폴리오 A4 인쇄용 ─── */
        .portfolio-print-wrapper {{
            margin: 0;
            padding: 0;
        }}
        .portfolio-a4-card {{
            background: #ffffff;
            padding: 2rem;
            border-radius: 4px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            margin: 1rem 0;
            max-width: 800px;
            margin-left: auto;
            margin-right: auto;
        }}
        .portfolio-watermark {{
            color: {P["text_muted"]};
            font-size: 0.85rem;
            margin: 0.25rem 0;
        }}
        .portfolio-title {{
            font-size: 1.5rem;
            color: {P["primary"]};
            margin: 0.5rem 0;
        }}
        .portfolio-subtitle {{
            color: {P["text_secondary"]};
            font-size: 0.9rem;
            margin: 0;
        }}
        .portfolio-section h3 {{
            font-size: 1.1rem;
            margin-top: 1.5rem;
            margin-bottom: 0.5rem;
            border-bottom: 2px solid {P["primary"]};
            padding-bottom: 0.25rem;
        }}
        .portfolio-hint {{
            font-size: 0.85rem;
            color: {P["text_muted"]};
            margin: 0;
        }}
        .portfolio-cover-page {{
            page-break-after: always;
        }}
        .portfolio-cover-stats {{
            display: flex;
            gap: 2rem;
            margin-bottom: 1.5rem;
            flex-wrap: wrap;
        }}
        .portfolio-radar {{
            flex: 1;
            min-width: 280px;
        }}
        .portfolio-stats-table {{
            flex: 0 0 220px;
        }}
        .portfolio-stat-label {{
            font-size: 0.85rem;
            color: {P["text_secondary"]};
            margin: 0.25rem 0;
        }}
        .portfolio-stat-value {{
            font-size: 1.25rem;
            font-weight: 700;
            color: {P["primary"]};
            margin: 0 0 0.5rem 0;
        }}
        .portfolio-ncs-table {{
            margin-top: 0.5rem;
            font-size: 0.9rem;
            width: 100%;
            border-collapse: collapse;
        }}
        .portfolio-ncs-table th, .portfolio-ncs-table td {{
            padding: 0.35rem 0.5rem;
            text-align: left;
            border-bottom: 1px solid {P["border_light"]};
        }}
        .portfolio-ncs-table th {{
            color: {P["primary"]};
        }}
        .portfolio-log-entry {{
            margin-bottom: 2rem;
            padding-bottom: 1.5rem;
            border-bottom: 1px dashed {P["border_light"]};
        }}
        .portfolio-log-entry:last-child {{
            border-bottom: none;
        }}
        .portfolio-log-item {{
            margin: 0 0 0.5rem;
            font-size: 0.95rem;
        }}
        .portfolio-evidence-badge {{
            display: inline-block;
            font-size: 0.75rem;
            padding: 0.2rem 0.5rem;
            background: rgba(30, 58, 95, 0.1);
            border-radius: 4px;
            color: {P["primary"]};
            margin-left: 0.5rem;
        }}
        .portfolio-bsr {{
            padding: 1rem;
            background: #f8fafc;
            border-radius: 6px;
            margin-bottom: 0;
            border-left: 4px solid {P["accent"]};
        }}
        /* 지도교사 종합의견: 권위·신뢰감 (따뜻한 네이비 톤) */
        .portfolio-comment {{
            padding: 1.35rem 1.5rem;
            background: linear-gradient(135deg, #f0f7ff 0%, #e8f4fc 50%, #f8fafc 100%);
            border-radius: 8px;
            border: 1px solid rgba(30, 58, 95, 0.18);
            border-left: 5px solid {P["primary"]};
            line-height: 1.75;
            box-shadow: 0 2px 8px rgba(30, 58, 95, 0.06);
        }}
        .portfolio-empty {{
            color: {P["text_muted"]};
            font-style: italic;
            padding: 1rem;
        }}
        .portfolio-footer {{
            margin-top: 2rem;
            padding-top: 1rem;
            border-top: 1px solid {P["border_light"]};
            text-align: center;
            color: {P["text_muted"]};
            font-size: 0.85rem;
        }}

        /* ─── @media print: 인쇄(PDF 저장) 시 페이지 깔끔하게 넘어가기 ─── */
        @media print {{
            .stApp, body {{
                background: #ffffff !important;
            }}
            .stSidebar {{ display: none !important; }}
            div.block-container {{
                padding: 0 !important;
                max-width: 100% !important;
            }}
            .portfolio-a4-card {{
                box-shadow: none !important;
                border: 1px solid #e2e8f0 !important;
                page-break-inside: auto;
            }}
            .portfolio-print-wrapper {{
                -webkit-print-color-adjust: exact;
                print-color-adjust: exact;
            }}
            .portfolio-cover-page {{
                page-break-after: always;
                page-break-inside: avoid;
            }}
            .portfolio-cover-stats {{
                page-break-inside: avoid;
            }}
            .portfolio-best-practices {{
                page-break-before: auto;
            }}
            .portfolio-log-entry {{
                page-break-inside: avoid;
                break-inside: avoid;
            }}
            .portfolio-log-entry[data-print-break="avoid"] {{
                break-inside: avoid;
            }}
            .portfolio-bsr {{
                break-inside: avoid;
            }}
            .portfolio-section {{
                page-break-after: avoid;
            }}
            .portfolio-section h3 {{
                page-break-after: avoid;
            }}
            [data-testid="stHorizontalBlock"] {{
                break-inside: avoid;
            }}
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
