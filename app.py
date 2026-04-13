import streamlit as st
import datetime
from pathlib import Path

from ui_style import apply_advanced_ui, render_app_footer
from student_view import show_student
from teacher_view import show_teacher
from constants import DEFAULT_NCS_PROGRESS
from db import ensure_default_users, get_user, seed_progress_if_missing

# 학교 로고 경로 (assets/school_logo.png 있으면 사용, 없으면 placeholder)
_APP_DIR = Path(__file__).resolve().parent
LOGO_PATH = _APP_DIR / "assets" / "school_logo.png"
LOGO_PLACEHOLDER = _APP_DIR / "assets" / "school_logo_placeholder.svg"


# 1. 시스템 초기화
def init_data():
    ensure_default_users()
    if "user" not in st.session_state:
        st.session_state.user = None
    if "ncs_progress" not in st.session_state:
        st.session_state.ncs_progress = {}
    if "skills" not in st.session_state:
        st.session_state.skills = {d: 3.0 for d in ["회로", "PLC", "설계", "센서", "안전"]}

def _logo_path():
    """학교 로고 경로: school_logo.png 있으면 사용, 없으면 placeholder SVG 사용"""
    return str(LOGO_PATH) if LOGO_PATH.exists() else str(LOGO_PLACEHOLDER)


# --- [페이지] 로그인 ---
def show_login():
    logo_path = _logo_path()
    st.markdown(
        '<div class="login-page-outer">'
        '<div class="login-page-card">',
        unsafe_allow_html=True,
    )
    _, col_center, _ = st.columns([1, 2.2, 1])
    with col_center:
        st.image(logo_path, width=128)
        st.markdown(
            "<h1 class='login-title'>NCS 직무 포트폴리오</h1>"
            "<p class='login-subtitle'>용산철도고등학교 · 산학일체형 도제학교 · 전기·전자 실습 기록</p>",
            unsafe_allow_html=True,
        )
    st.divider()

    col1, col2, col3 = st.columns([1, 1.25, 1])
    with col2:
        uid = st.text_input("아이디 (S01~S11 / admin)")
        upw = st.text_input("비밀번호", type="password")
        if st.button("통합인증 로그인", width="stretch"):
            user = get_user(uid)
            if user and user["pw"] == upw:
                st.session_state.user = uid
                if uid != "admin":
                    # 최초 로그인 시에는 모든 진도를 0으로 시작하고,
                    # 실습일지가 저장될 때마다 증가시키도록 설정.
                    st.session_state.ncs_progress = seed_progress_if_missing(
                        uid,
                        DEFAULT_NCS_PROGRESS,
                    )
                st.rerun()
            else:
                st.error("로그인 정보가 일치하지 않습니다.")
    st.markdown("</div></div>", unsafe_allow_html=True)
    render_app_footer()


# 실행부
st.set_page_config(
    page_title="NCS 직무 포트폴리오",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_advanced_ui()
init_data()

if st.session_state.user is None:
    show_login()
else:
    with st.sidebar:
        st.image(_logo_path(), width=120)
        st.divider()
        uid = st.session_state.user
        st.markdown("### 접속 정보")
        st.write(f"**사용자**: {uid}")
        today = datetime.date.today()
        st.write(f"**날짜**: {today}")

        if uid != "admin":
            st.divider()
            st.markdown("### 오늘의 학습 요약")
            from db import list_logs

            logs = list_logs(uid)
            logs_count = len(logs)
            prog = st.session_state.ncs_progress or {}
            avg_prog = round(sum(prog.values()) / max(len(prog), 1), 1)

            # 날짜 기준 집계
            today_str = today.isoformat()
            week_start = today - datetime.timedelta(days=today.weekday())
            month_start = today.replace(day=1)

            today_cnt = sum(1 for r in logs if r.get("date") == today_str)
            week_cnt = sum(
                1
                for r in logs
                if r.get("date")
                and week_start
                <= datetime.date.fromisoformat(str(r["date"]))
                <= today
            )
            month_cnt = sum(
                1
                for r in logs
                if r.get("date")
                and month_start
                <= datetime.date.fromisoformat(str(r["date"]))
                <= today
            )

            st.metric("오늘 작성 일지", today_cnt)
            st.metric("이번 주 작성 일지", week_cnt)
            st.metric("이번 달 작성 일지", month_cnt)

            st.divider()
            st.markdown("### 진행 현황")
            st.metric("누적 실습일지", logs_count)
            st.metric("평균 NCS 진도(%)", avg_prog)
            st.caption("팁: ‘NCS 매칭’은 전공 키워드를 많이 쓸수록 더 정확해집니다.")
        else:
            st.divider()
            st.markdown("### 메뉴")
            st.caption("교사용 대시보드에서 전체 현황을 확인하세요.")

        if st.button("로그아웃", width="stretch"):
            st.session_state.user = None
            st.rerun()
    if st.session_state.user == "admin":
        show_teacher()
    else:
        show_student(st.session_state.user)
    render_app_footer()

