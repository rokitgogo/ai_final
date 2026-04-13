import datetime
import html
import io
import json
import re
import textwrap
from collections import Counter, defaultdict

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from bsr_utils import (
    RADAR_AXES,
    extract_weak_radar_dimensions,
    generate_seuteuk_from_bsr_logs,
    generate_teacher_learning_guidance,
    radar_scores_from_logs,
    render_bsr_highlighted,
    resolve_google_api_key,
)
from constants import DEFAULT_NCS_PROGRESS, format_ncs_unit, GLOSSARY, NCS_DB
from db import (
    add_researcher_log,
    get_portfolio_comment,
    list_logs,
    list_researcher_logs,
    list_users,
    save_portfolio_comment,
    seed_progress_if_missing,
)
from ui_style import P

# 종합 대시보드 Plotly 히트맵: 학생(1~11번) × NCS 핵심 단위 실습 빈도 (전자 능력단위 중심)
CORE_NCS_HEATMAP_UNITS: list[str] = [
    "전자부품장착",
    "전자회로조립",
    "전자회로설계",
    "PCB설계",
    "마이크로컨트롤러",
    "임베디드하드웨어설계",
    "센서응용",
    "산업통신",
    "통신기기하드웨어개발",
    "PLC제어",
    "인버터제어",
    "전기안전",
]


def _heatmap_frequency_matrix(_students: list[dict]) -> tuple[list[str], list[str], list[list[int]]]:
    """행: 1~11번 학생 전원, 열: 핵심 NCS 단위, 값: 해당 단위 일지 건수."""
    col_units = CORE_NCS_HEATMAP_UNITS
    row_labels: list[str] = []
    z: list[list[int]] = []
    for i in range(1, 12):
        uid = f"S{i:02d}"
        row_labels.append(_student_label(uid))
        logs = list_logs(uid)
        counts = {u: 0 for u in col_units}
        for r in logs:
            unit = _resolve_ncs_unit(r.get("ncs_unit", "") or "")
            if unit in counts:
                counts[unit] += 1
        z.append([counts[u] for u in col_units])
    col_display = [format_ncs_unit(u) for u in col_units]
    return row_labels, col_display, z


def _student_label(uid: str) -> str:
    try:
        num = int(uid[1:])
        return f"{num}번 학생"
    except Exception:
        return uid


def _student_sort_key(uid: str) -> int:
    """1번~11번 순서 정렬용"""
    try:
        return int(uid[1:])
    except Exception:
        return 999


def _extract_keywords_from_bsr(bsr_text: str) -> tuple[list[str], list[str]]:
    """BSR 원문에서 NCS_DB·GLOSSARY 키워드 추출. (ncs_keywords, glossary_terms) 반환."""
    if not bsr_text:
        return [], []
    text_lower = bsr_text.lower()
    ncs_found: list[str] = []
    glossary_found: list[str] = []
    for unit, meta in NCS_DB.items():
        for kw in meta.get("keywords", []):
            if kw in bsr_text or (len(kw) >= 2 and kw.lower() in text_lower):
                ncs_found.append(kw)
    for term in GLOSSARY:
        if term in bsr_text:
            glossary_found.append(term)
    return ncs_found, glossary_found


def _resolve_ncs_unit(unit_or_code: str) -> str:
    """능력단위명 또는 코드를 정규 단위명으로 변환. 데이터 매칭 정확도 향상."""
    if not unit_or_code:
        return ""
    if unit_or_code in NCS_DB:
        return unit_or_code
    for u, meta in NCS_DB.items():
        if meta.get("code") == unit_or_code:
            return u
    return unit_or_code


def _filter_terms_for_unit(used_terms: list[str], unit_type: str) -> list[str]:
    """단위별 관련 키워드만 필터링."""
    sets = {
        "plc": {"래더", "PLC", "시퀀스", "로직", "접점", "모터", "입출력", "시운전"},
        "solder": {"납땜", "솔더링", "쇼트", "PCB", "극성", "저항", "콘덴서", "인두"},
        "safety": {"접지", "보호구", "LOTO", "ELB", "차단", "MCB", "메거", "절연"},
    }
    s = sets.get(unit_type, set())
    return [t for t in used_terms if t in s][:3]


def _evaluate_seungwa_reflection(bsr_logs: list[dict]) -> tuple[str, str]:
    """
    BSR 로그에서 [성과] 부분을 추출해 성찰 수준(높음/보통/낮음)을 평가.
    반환: (수준, 코멘트).
    """
    high_words = {"깨달음", "성찰", "과정", "이유", "개선", "다음에는", "배운", "어려웠던", "스스로", "이해", "알게", "생각", "판단", "고민"}
    medium_words = {"확인", "점검", "수행", "적용", "이해함", "배웠"}
    low_patterns = ["했다", "됐다", "완료", "끝냄", "했다."]

    scores: list[int] = []
    extracts: list[str] = []
    for row in bsr_logs:
        bsr = (row.get("bsr") or "").strip()
        m = re.search(r"\[성과\]\s*(.*?)(?=\[|$)", bsr, re.DOTALL)
        if m:
            seg = m.group(1).strip()
            extracts.append(seg)
            score = 0
            seg_lower = seg.lower()
            if len(seg) >= 50:
                score += 2
            elif len(seg) >= 20:
                score += 1
            for w in high_words:
                if w in seg:
                    score += 2
                    break
            for w in medium_words:
                if w in seg:
                    score += 1
                    break
            for p in low_patterns:
                if p in seg and len(seg) < 30:
                    score -= 1
                    break
            scores.append(max(0, score))

    if not scores:
        return "—", "[성과] 구간이 없어 성찰 수준을 평가할 수 없습니다."
    avg = sum(scores) / len(scores)
    if avg >= 3:
        level, comment = "높음", "학생이 과정·이유·개선점을 구체적으로 서술하여 메타인지적 성찰 수준이 높습니다."
    elif avg >= 1.5:
        level, comment = "보통", "기본적인 수행 중심 기술에 일부 성찰 요소가 포함되어 있습니다."
    else:
        level, comment = "낮음", "결과 중심의 간단한 서술 위주이며, 성찰 키워드 보완을 권장합니다."
    return level, comment


def _extract_seungwa_from_bsr(bsr_text: str) -> str:
    """BSR 텍스트에서 [성과] 구간만 추출."""
    if not bsr_text:
        return ""
    m = re.search(r"\[성과\]\s*(.*?)(?=\[|$)", str(bsr_text), re.DOTALL)
    return (m.group(1).strip() if m else "").strip()


def _log_competency_scores(bsr_text: str) -> dict[str, float]:
    """BSR 텍스트에서 역량 차원 점수 추출 (구체성, 전문용어, 안전, 성찰)."""
    text = (bsr_text or "").strip()
    length = min(5, max(0, (len(text) // 30) + 1))
    all_kw = set(GLOSSARY.keys())
    for meta in NCS_DB.values():
        all_kw.update(meta.get("keywords", []))
    term = min(5, max(0, sum(1 for w in all_kw if w in text) + 1))
    safety = min(5, max(0, sum(text.count(k) for k in ["안전", "접지", "감전", "보호구", "LOTO", "ELB", "차단기"]) + 1))
    high_w = ["깨달음", "성찰", "과정", "이유", "개선", "다음에는", "배운", "스스로", "이해", "알게"]
    reflection = min(5, max(0, sum(2 for w in high_w if w in text) + 1))
    return {"구체성": length, "전문용어": term, "안전": safety, "성찰": min(reflection, 5)}


def _evaluate_seungwa_level(seungwa_text: str) -> str:
    """[성과] 답변의 성찰 수준을 높음/보통/낮음으로 평가 (휴리스틱 기반)."""
    t = (seungwa_text or "").strip()
    if not t or len(t) < 5:
        return "낮음"
    # 성찰적·메타인지적 표현 (높음)
    high_keywords = ["깨달", "성찰", "과정", "이유", "개선", "다음에는", "배운 점", "어려웠던", "스스로", "생각", "이해", "교훈", "반성", "차후"]
    # 보통 수준 표현
    mid_keywords = ["확인", "점검", "수행", "완료", "작동", "연결", "설정"]
    high_cnt = sum(1 for k in high_keywords if k in t)
    mid_cnt = sum(1 for k in mid_keywords if k in t)
    length_bonus = 1 if len(t) >= 50 else (0.5 if len(t) >= 25 else 0)
    score = high_cnt * 2 + mid_cnt * 0.5 + length_bonus
    if score >= 3:
        return "높음"
    if score >= 1:
        return "보통"
    return "낮음"


def _make_seuteuk_keyword_fallback(uid: str, logs: list[dict]) -> str:
    """Gemini 세특 생성 실패 시 사용하는 키워드 기반 요약."""
    logs_sorted = logs[:10]
    units = [_resolve_ncs_unit(row.get("ncs_unit", "")) for row in logs_sorted]
    unit_counter = Counter(u for u in units if u)
    top_units = ", ".join(f"{format_ncs_unit(u)}({c}회)" for u, c in unit_counter.most_common(3))
    total_cnt = len(logs_sorted)

    # BSR 전체 텍스트에서 키워드 추출 (학생이 실제 사용한 용어 반영)
    all_bsr = " ".join((r.get("bsr") or "") for r in logs_sorted)
    ncs_kw, gl_kw = _extract_keywords_from_bsr(all_bsr)
    used_terms = list(dict.fromkeys(ncs_kw + gl_kw))[:12]

    safety_cnt = sum(_resolve_ncs_unit(r.get("ncs_unit") or "") == "전기안전" for r in logs_sorted)
    plc_cnt = sum("PLC" in _resolve_ncs_unit(r.get("ncs_unit") or "") for r in logs_sorted)
    solder_cnt = sum(_resolve_ncs_unit(r.get("ncs_unit") or "") == "전자부품장착" for r in logs_sorted)

    parts: list[str] = []
    parts.append(
        f"{_student_label(uid)}은(는) 한 학기 동안 전공 실습에 성실히 참여하여 "
        f"{top_units} 영역에서 총 {total_cnt}회 이상의 실습 활동을 수행하였다."
    )

    plc_kw = _filter_terms_for_unit(used_terms, "plc")
    solder_kw = _filter_terms_for_unit(used_terms, "solder")
    safety_kw = _filter_terms_for_unit(used_terms, "safety")

    if plc_cnt:
        if plc_kw:
            kw_str = "·".join(plc_kw[:3])
            base = f"PLC 제어 실습에서는 {kw_str} 기기를 활용하여 래더 로직 작성·입출력 결선·시운전 등 핵심 공정을 수행하며"
        else:
            base = "PLC 제어 실습에서는 입출력 결선 및 시퀀스 제어를 단계적으로 수행하며"
        parts.append(base + " 오동작 원인을 스스로 분석하고 수정하는 경험을 쌓았다.")
    if solder_cnt:
        if solder_kw:
            kw_str = "·".join(solder_kw[:3])
            base = f"전자부품장착 실습에서는 {kw_str} 기기를 활용하여 부품 극성 확인·납땜 품질·쇼트 여부 점검 등 핵심 공정을 수행하며"
        else:
            base = "전자부품장착 관련 실습에서는 회로도에 따라 부품 극성을 확인하고 납땜 품질과 쇼트 여부를 점검하는 등"
        parts.append(base + " 기본기 향상에 노력하였다.")
    if safety_cnt:
        if safety_kw:
            kw_str = "·".join(safety_kw[:3])
            base = f"전기안전 영역에서는 {kw_str} 등 기초 안전수칙(전원 차단·보호구 착용)을 준수하며"
        else:
            base = "전기안전 영역에서는 작업 전 위험요인을 사전에 파악하고 전원 차단·보호구 착용 등"
        parts.append(base + " 위험요인을 사전에 파악하려는 태도를 보였다.")

    text = " ".join(parts)
    return textwrap.shorten(text, width=480, placeholder=" …")


def _make_seuteuk(uid: str, logs: list[dict]) -> str:
    if not logs:
        return "선택한 기간에 해당 학생의 실습 기록이 없습니다."

    api_key = resolve_google_api_key()
    gemini_text = generate_seuteuk_from_bsr_logs(
        logs, _student_label(uid), api_key=api_key
    )
    if gemini_text and len(gemini_text.strip()) >= 40:
        return textwrap.shorten(gemini_text.strip(), width=520, placeholder=" …")

    return _make_seuteuk_keyword_fallback(uid, logs)


def show_teacher() -> None:
    st.header("통합 관리 시스템")

    # ─── 데이터 수집 (탭 전역 사용) ───
    students = sorted(
        [u for u in list_users() if u["uid"].startswith("S")],
        key=lambda u: _student_sort_key(u["uid"]),
    )
    all_logs_flat = []
    total_logs = 0
    prog_sum = 0
    prog_cnt = 0
    for s in students:
        logs = list_logs(s["uid"])
        total_logs += len(logs)
        all_logs_flat.extend(logs)
        prog = seed_progress_if_missing(s["uid"], DEFAULT_NCS_PROGRESS)
        prog_sum += sum(prog.values())
        prog_cnt += sum(1 for _ in prog)
    avg_prog = round(prog_sum / max(prog_cnt, 1), 1) if prog_cnt else 0

    rows = []
    for s in students:
        uid = s["uid"]
        logs = list_logs(uid)
        refl_scores = [_log_competency_scores(r.get("bsr") or "").get("성찰", 0.0) for r in logs]
        avg_refl = (
            round(sum(refl_scores) / len(refl_scores), 2) if refl_scores else 0.0
        )
        rows.append(
            {
                "학생": _student_label(uid),
                "일지수": len(logs),
                "성찰(평균)": avg_refl,
            }
        )
    df = pd.DataFrame(rows)

    def _style_reflection_low(row: pd.Series) -> list[str]:
        styles: list[str] = []
        for _ in row.index:
            if row.get("성찰(평균)", 99) < 2.0:
                styles.append("background-color: #fff9c4; color: #334155")
            else:
                styles.append("")
        return styles

    all_units = sorted({_resolve_ncs_unit(row.get("ncs_unit", "")) for u in students for row in list_logs(u["uid"]) if row.get("ncs_unit")})
    heat_rows = []
    for s in students:
        uid = s["uid"]
        logs = list_logs(uid)
        counter = {u: 0 for u in all_units}
        for r in logs:
            unit = _resolve_ncs_unit(r.get("ncs_unit", ""))
            if unit and unit in counter:
                counter[unit] += 1
        row = {"학생": _student_label(uid)}
        row.update(counter)
        heat_rows.append(row)

    # ─── 3개 탭으로 목적별 정보 구성 ───
    tab1, tab2, tab3 = st.tabs([
        "종합 현황 대시보드",
        "개별 일지 및 성찰 분석",
        "교수학습 지원 및 연구",
    ])

    with tab1:
        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("핵심 지표")
        ncs_ratios = [r.get("ncs_term_ratio") or 0 for s in students for r in list_logs(s["uid"])]
        avg_ncs_ratio = round(sum(ncs_ratios) / max(len(ncs_ratios), 1), 1)
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("전체 학생", f"{len(students)}명", help="등록된 도제생 수")
        with m2:
            st.metric("평균 NCS 진도", f"{avg_prog}%", help="학생별 NCS 단위 평균 진행률")
        with m3:
            st.metric("총 실습일지", f"{total_logs}건", help="전체 저장된 일지 수")
        with m4:
            st.metric("NCS 용어 변환률", f"{avg_ncs_ratio}%", help="구어체 대비 NCS 표준 용어 사용 비율 평균")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("전체 학생 역량 도달도")
        st.caption("성찰(평균)이 2.0 미만인 학생은 노란색으로 표시됩니다.")
        try:
            styled_df = df.style.apply(_style_reflection_low, axis=1)
            st.dataframe(styled_df, width="stretch", hide_index=True)
        except Exception:
            st.dataframe(df, width="stretch", hide_index=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("학생별 실습일지 작성 현황")
        if not df.empty:
            df_chart = df.copy()
            df_chart["_ord"] = df_chart["학생"].str.extract(r"(\d+)", expand=False).fillna(999).astype(int)
            df_chart = df_chart.sort_values("_ord", ascending=True).drop(columns=["_ord"])
            fig = px.bar(
                df_chart,
                x="학생",
                y="일지수",
                color_discrete_sequence=[P.get("primary", "#1e3a5f")],
                category_orders={"학생": df_chart["학생"].tolist()},
            )
            fig.update_layout(
                margin=dict(l=40, r=40, t=30, b=80),
                xaxis_tickangle=-45,
                showlegend=False,
                paper_bgcolor="rgba(255,255,255,0)",
                plot_bgcolor="rgba(255,255,255,0)",
                height=320,
            )
            st.plotly_chart(fig, width="stretch")
        else:
            st.info("아직 작성된 실습일지가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("직무 도달도 히트맵 (핵심 NCS 단위)")
        st.caption(
            "전체 학생(1~11번)과 주요 능력단위별 **실습 일지 빈도**입니다. "
            "색이 옅은 칸은 해당 단위 실습이 적어 직무 경험이 소외되었을 수 있음을 시사합니다."
        )
        h_rows, h_cols, h_z = _heatmap_frequency_matrix(students)
        fig_hm = go.Figure(
            data=go.Heatmap(
                z=h_z,
                x=h_cols,
                y=h_rows,
                colorscale=[
                    [0.0, "#f1f5f9"],
                    [0.35, "#bae6fd"],
                    [0.65, "#38bdf8"],
                    [1.0, P["primary"]],
                ],
                colorbar=dict(title="일지 수"),
                hovertemplate="학생: %{y}<br>단위: %{x}<br>실습 횟수: %{z}<extra></extra>",
            )
        )
        fig_hm.update_layout(
            margin=dict(l=100, r=40, t=20, b=120),
            xaxis_tickangle=-35,
            height=max(380, 28 * len(h_rows)),
            paper_bgcolor="rgba(255,255,255,0)",
            plot_bgcolor="rgba(255,255,255,0)",
            yaxis=dict(autorange="reversed"),
        )
        st.plotly_chart(fig_hm, width="stretch")

        with st.expander("그 외 NCS 단위까지 포함한 상세 표", expanded=False):
            if heat_rows:
                heat_df = pd.DataFrame(heat_rows).set_index("학생")
                heat_df = heat_df.rename(columns={c: format_ncs_unit(c) for c in heat_df.columns})
                try:
                    from matplotlib.colors import LinearSegmentedColormap
                    _cmap = LinearSegmentedColormap.from_list(
                        "ncs_accent", ["#f8fafc", P["accent_soft"], P["accent"], P["primary"]], N=128
                    )
                    styled = heat_df.style.background_gradient(cmap=_cmap, axis=None)
                    st.dataframe(styled, width="stretch")
                except Exception:
                    st.dataframe(heat_df, width="stretch")
            else:
                st.caption("아직 일지에 기록된 NCS 단위가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab' style='margin-top:1rem;'>", unsafe_allow_html=True)
        st.subheader("AI 기반 교수학습 가이드")
        st.caption(
            "BSR 키워드 기반 레이더(설계·제작·계측·제어·안전)로 전원 점수를 집계하고, "
            "30점 미만이거나 나머지 네 영역 평균 대비 20% 이상 낮은 축을 자동 추출합니다."
        )
        radar_rows: list[dict] = []
        flag_cases: list[dict] = []
        for s in students:
            uid = s["uid"]
            logs = list_logs(uid)
            axes, vals = radar_scores_from_logs(logs)
            row: dict = {"학생": _student_label(uid), "uid": uid}
            for a, v in zip(axes, vals):
                row[a] = v
            radar_rows.append(row)
            for w in extract_weak_radar_dimensions(vals):
                flag_cases.append(
                    {
                        "student_label": _student_label(uid),
                        "uid": uid,
                        "axis": w["axis"],
                        "reason": w["reason"],
                        "value": round(float(w["value"]), 2),
                        "others_avg": round(float(w["others_avg"]), 2),
                        "scores": dict(zip(axes, [round(float(x), 2) for x in vals])),
                    }
                )
        if radar_rows:
            tbl_radar = pd.DataFrame(radar_rows)
            st.markdown("**전체 학생 레이더 점수**")
            st.dataframe(tbl_radar, width="stretch", hide_index=True)
            plot_df = tbl_radar.set_index("학생")[RADAR_AXES]
            fig_radar = px.imshow(
                plot_df,
                labels={"x": "역량 축", "y": "학생", "color": "점수"},
                aspect="auto",
                color_continuous_scale="Blues",
                zmin=0,
                zmax=100,
            )
            fig_radar.update_layout(height=max(240, min(520, 32 * len(plot_df))))
            st.plotly_chart(fig_radar, width="stretch")
            st.markdown(
                '<p class="radar-chart-caption">BSR 키워드 기반 정규화 점수(0~100). '
                "실습 기록이 적을 때는 분모 보정으로 과도한 만점을 완화합니다.</p>",
                unsafe_allow_html=True,
            )
        else:
            st.info("등록된 학생이 없어 레이더 데이터를 표시할 수 없습니다.")

        if flag_cases:
            st.markdown("**자동 추출: 지도가 필요한 약점 축**")
            disp_weak = pd.DataFrame(
                [
                    {
                        "학생": c["student_label"],
                        "uid": c["uid"],
                        "약점 축": c["axis"],
                        "사유": c["reason"],
                        "점수": c["value"],
                        "타 영역 평균": c["others_avg"],
                    }
                    for c in flag_cases
                ]
            )
            st.dataframe(disp_weak, width="stretch", hide_index=True)
            api_k = resolve_google_api_key()
            if not api_k:
                st.warning(
                    "Gemini 가이드를 생성하려면 `.streamlit/secrets.toml`에 `GOOGLE_API_KEY`를 설정하세요. "
                    "관리자에게 API 설정을 확인하세요."
                )
            if st.button("Gemini로 교수학습 가이드 생성", key="teacher_radar_guidance_btn"):
                with st.spinner("교수학습 가이드를 생성하는 중..."):
                    guide = generate_teacher_learning_guidance(flag_cases, api_key=api_k)
                if guide:
                    st.markdown(guide)
                else:
                    st.warning("가이드를 생성하지 못했습니다. API 키·할당량을 확인하거나 잠시 후 다시 시도하세요.")
            st.caption("추출된 사례를 바탕으로 Gemini 2.0 Flash가 교사용 지도·비계 문장을 생성합니다.")
        else:
            st.success("현재 자동 추출 기준에 해당하는 약점 축이 없습니다.")

        st.markdown("</div>", unsafe_allow_html=True)

    with tab2:
        # 역량 성장 비교 레이다 차트 (최초 3개 vs 최근 3개)
        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("역량 성장 비교 (스캐폴딩 효과)")
        st.caption("최초 3개 일지 vs 최근 3개 일지 — 성찰의 성장을 시각화")
        if students:
            radar_uid = st.selectbox(
                "학생 선택",
                options=[s["uid"] for s in students],
                format_func=lambda u: next((f"{_student_label(x['uid'])} ({x['uid']})" for x in students if x["uid"] == u), u),
                key="radar_student",
            )
            radar_logs = list_logs(radar_uid)
            if len(radar_logs) >= 2:
                reversed_logs = list(reversed(radar_logs))
                first3 = reversed_logs[:3]
                recent3 = radar_logs[:3]
                dims = ["구체성", "전문용어", "안전", "성찰"]
                def avg_scores(log_list):
                    if not log_list:
                        return [0] * 4
                    by_dim = {d: [] for d in dims}
                    for row in log_list:
                        s = _log_competency_scores(row.get("bsr") or "")
                        for d in dims:
                            by_dim[d].append(s.get(d, 0))
                    return [sum(by_dim[d]) / max(len(by_dim[d]), 1) for d in dims]
                first_vals = avg_scores(first3)
                recent_vals = avg_scores(recent3)
                fig_radar = go.Figure()
                fig_radar.add_trace(go.Scatterpolar(
                    r=first_vals + [first_vals[0]], theta=dims + [dims[0]], fill="toself",
                    name="최초 3개 일지", line={"color": P.get("accent", "#3b82f6")}
                ))
                fig_radar.add_trace(go.Scatterpolar(
                    r=recent_vals + [recent_vals[0]], theta=dims + [dims[0]], fill="toself",
                    name="최근 3개 일지", line={"color": P.get("primary", "#1e3a5f")}
                ))
                fig_radar.update_layout(
                    polar={"radialaxis": {"visible": True, "range": [0, 5]}},
                    showlegend=True,
                    height=400,
                    margin=dict(l=80, r=80),
                )
                st.plotly_chart(fig_radar, width="stretch")
                st.markdown(
                    '<p class="radar-chart-caption">일지별 구체성·전문용어·안전·성찰 평균(0~5). '
                    "최초 3개와 최근 3개 일지를 비교합니다.</p>",
                    unsafe_allow_html=True,
                )
            else:
                st.info("일지가 2개 이상일 때 역량 성장 비교가 표시됩니다.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("실습일지 BSR 구조화 상세")
        st.caption("[배경] [해결] [성과] 구간별 시각화 — 실무 중심 실체 가시화")
        if students:
            t_options = {s["uid"]: f"{_student_label(s['uid'])} ({s['uid']})" for s in students}
            t_uid = st.selectbox(
                "학생 선택",
                options=list(t_options.keys()),
                format_func=lambda u: t_options[u],
                key="bsr_student_select",
            )
            t_logs = list_logs(t_uid)
            if t_logs:
                t_detail_opts = [(r.get("id"), f"#{r.get('id')} [{r.get('date','')}] {format_ncs_unit(r.get('ncs_unit',''))}") for r in t_logs]
                t_sel_id = st.selectbox(
                    "일지 선택",
                    options=[o[0] for o in t_detail_opts],
                    format_func=lambda x: next((o[1] for o in t_detail_opts if o[0] == x), str(x)),
                    key="bsr_log_select",
                )
                t_row = next((r for r in t_logs if r.get("id") == t_sel_id), None)
                if t_row and t_row.get("bsr"):
                    bsr_html = render_bsr_highlighted(str(t_row["bsr"]))
                    st.markdown(
                        f"<div class='report-card-inner'>{bsr_html}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("해당 학생의 저장된 실습일지가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("연구 데이터 분석")
        st.markdown("##### 전문가 타당도 검토용 데이터 집계")
        st.caption(
            "일지별로 증거 사진 메모, 학생 성찰(BSR), 휴리스틱·역량 점수 기반 AI 분석, "
            "교사 확정 종합의견을 한 번에 내려받을 수 있습니다."
        )
        export_rows: list[dict[str, object]] = []
        for s in students:
            suid = s["uid"]
            pc_row = get_portfolio_comment(suid)
            t_teacher = (pc_row.get("comment_text") or "") if pc_row else ""
            t_conf = "Y" if (pc_row and int(pc_row.get("is_confirmed") or 0)) else "N"
            for row in list_logs(suid):
                bsr_t = str(row.get("bsr") or "")
                scores = _log_competency_scores(bsr_t)
                export_rows.append(
                    {
                        "학생UID": suid,
                        "일지ID": row.get("id", ""),
                        "날짜": row.get("date", ""),
                        "NCS단위": row.get("ncs_unit", ""),
                        "증거사진_메모": row.get("image_note") or "",
                        "학생성찰_BSR": bsr_t,
                        "AI분석_역량점수_JSON": json.dumps(scores, ensure_ascii=False),
                        "교사최종의견": t_teacher,
                        "교사의견_확정여부": t_conf,
                    }
                )
        if export_rows:
            df_exp = pd.DataFrame(export_rows)
            csv_bytes = df_exp.to_csv(index=False).encode("utf-8-sig")
            c_dl1, c_dl2 = st.columns(2)
            with c_dl1:
                st.download_button(
                    "CSV 다운로드 (UTF-8 BOM, Excel 호환)",
                    data=csv_bytes,
                    file_name="research_validity_export.csv",
                    mime="text/csv",
                    key="research_validity_csv_main",
                    width="stretch",
                )
            with c_dl2:
                try:
                    buf = io.BytesIO()
                    with pd.ExcelWriter(buf, engine="openpyxl") as wr:
                        df_exp.to_excel(wr, index=False, sheet_name="data")
                    st.download_button(
                        "Excel 다운로드 (.xlsx)",
                        data=buf.getvalue(),
                        file_name="research_validity_export.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="research_validity_xlsx_main",
                        width="stretch",
                    )
                except Exception:
                    st.caption("Excel은 `pip install openpyxl` 후 사용할 수 있습니다.")
        else:
            st.info("내보낼 실습일지가 없습니다.")
        st.divider()

        REFLECTION_KEYWORDS = ["깨달음", "해결", "다음에는", "배운", "이해", "개선", "어려웠던", "스스로", "성찰", "과정", "이유", "알게"]
        REFLECTION_TIMELINE_KW = ["깨달음", "해결", "다음에는"]

        st.markdown("##### [성찰 성장 타임라인]")
        st.caption("주차별 성찰 키워드(깨달음, 해결, 다음에는) 사용 횟수 추이")
        if all_logs_flat:
            week_counts: dict[str, dict[str, int]] = defaultdict(lambda: {k: 0 for k in REFLECTION_TIMELINE_KW})
            for row in all_logs_flat:
                bsr = (row.get("bsr") or "").strip()
                d_str = row.get("date", "")
                if not d_str:
                    continue
                try:
                    dt = datetime.datetime.strptime(d_str, "%Y-%m-%d")
                    wk = f"{dt.year}-W{dt.isocalendar()[1]:02d}"
                except (ValueError, TypeError):
                    wk = d_str[:7] if len(d_str) >= 7 else d_str
                for kw in REFLECTION_TIMELINE_KW:
                    if kw in bsr:
                        week_counts[wk][kw] += 1
            if week_counts:
                weeks_sorted = sorted(week_counts.keys())
                tl_data = [{"주차": w, **week_counts[w]} for w in weeks_sorted]
                df_tl = pd.DataFrame(tl_data)
                fig_tl = go.Figure()
                for kw in REFLECTION_TIMELINE_KW:
                    fig_tl.add_trace(
                        go.Scatter(x=df_tl["주차"], y=df_tl[kw], name=kw, mode="lines+markers", line=dict(width=2))
                    )
                fig_tl.update_layout(
                    height=280, margin=dict(l=50, r=30, t=30, b=80),
                    xaxis_tickangle=-45, legend=dict(orientation="h", yanchor="bottom", y=1.02),
                    paper_bgcolor="rgba(255,255,255,0)", plot_bgcolor="rgba(255,255,255,0)",
                )
                st.plotly_chart(fig_tl, width="stretch")
            else:
                st.info("주차별 데이터가 없습니다.")
        else:
            st.info("분석할 실습일지가 없습니다.")

        st.markdown("##### 성찰 키워드 빈도")
        st.caption("전체 일지에서 메타인지적 성찰 키워드 사용 빈도 (날짜별)")
        if all_logs_flat:
            date_counts: dict[str, dict[str, int]] = defaultdict(lambda: {k: 0 for k in REFLECTION_KEYWORDS})
            for row in all_logs_flat:
                bsr = (row.get("bsr") or "").strip()
                d = row.get("date", "")
                if not d:
                    continue
                for kw in REFLECTION_KEYWORDS:
                    if kw in bsr:
                        date_counts[d][kw] += 1
            dates_sorted = sorted(date_counts.keys())
            if dates_sorted:
                chart_data = []
                for d in dates_sorted:
                    row_data = {"날짜": d}
                    for kw in REFLECTION_KEYWORDS:
                        row_data[kw] = date_counts[d][kw]
                    chart_data.append(row_data)
                df_kw = pd.DataFrame(chart_data)
                fig_kw = px.bar(
                    df_kw,
                    x="날짜",
                    y=REFLECTION_KEYWORDS,
                    barmode="stack",
                    color_discrete_sequence=[P.get("primary", "#1e3a5f"), P.get("accent", "#3b82f6"), "#64748b", "#94a3b8", "#cbd5e1", "#e2e8f0", "#475569", "#334155", "#1e293b", "#0f172a", "#f1f5f9", "#f8fafc"][:12],
                    category_orders={"날짜": dates_sorted},
                )
                fig_kw.update_layout(
                    margin=dict(l=50, r=30, t=40, b=100),
                    xaxis_tickangle=-45,
                    height=360,
                    paper_bgcolor="rgba(255,255,255,0)",
                    plot_bgcolor="rgba(255,255,255,0)",
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                )
                st.plotly_chart(fig_kw, width="stretch")
            else:
                st.info("날짜별 데이터가 없습니다.")
        else:
            st.info("분석할 실습일지가 없습니다.")
        st.markdown("</div>", unsafe_allow_html=True)

    with tab3:
        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("교수학습 기록 지원 도구")
        if not students:
            st.info("등록된 학생이 없습니다.")
        else:
            options = {s["uid"]: f"{_student_label(s['uid'])} ({s['uid']})" for s in students}
            selected_uid = st.selectbox(
                "학생 선택",
                options=list(options.keys()),
                format_func=lambda u: options[u],
            )
            mode = st.radio(
                "범위 선택",
                options=["전체 기간", "최근 10개 활동"],
                horizontal=True,
            )

            all_logs = list_logs(selected_uid)
            logs_for_use = all_logs if mode == "전체 기간" else all_logs[:10]

            teacher_key = f"teacher_portfolio_{selected_uid}"
            ai_key = f"ai_seuteuk_{selected_uid}"
            if st.session_state.get("_seuteuk_prev_uid") != selected_uid:
                st.session_state["_seuteuk_prev_uid"] = selected_uid
                pc_load = get_portfolio_comment(selected_uid)
                st.session_state[teacher_key] = (pc_load.get("comment_text") or "") if pc_load else ""

            if st.button("초안 생성", width="stretch", key="btn_seuteuk_draft"):
                draft = _make_seuteuk(selected_uid, logs_for_use)
                level, comment = _evaluate_seungwa_reflection(logs_for_use)
                st.session_state["seuteuk_draft"] = draft
                st.session_state["seuteuk_reflection"] = (level, comment)
                st.session_state["seuteuk_uid"] = selected_uid
                st.session_state[ai_key] = draft
                st.session_state[teacher_key] = draft

            st.caption(
                "초안 생성은 AI 제안만 갱신합니다. 학생 포트폴리오에는 우측 「최종 승인」 후에만 반영됩니다."
            )
            col_ai, col_teacher = st.columns([1, 1])
            with col_ai:
                st.markdown("##### AI 생성 세특 초안")
                st.caption("참고용 초안입니다. 수정·확정은 우측 교사 영역에서만 수행합니다.")
                ai_text = st.session_state.get(ai_key, "")
                if ai_text:
                    safe_ai = html.escape(str(ai_text)).replace("\n", "<br/>")
                    st.markdown(
                        f"<div class='report-card-inner' style='max-height:300px;overflow-y:auto;font-size:0.92rem;line-height:1.65;'>{safe_ai}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.info("「초안 생성」을 실행하면 AI 초안이 이 영역에 표시됩니다.")

            with col_teacher:
                st.markdown("##### 교사 수정 및 승인")
                st.caption("본문을 검토·수정한 뒤 「최종 승인」을 눌러야 학생 포트폴리오에 확정 저장됩니다.")
                st.text_area(
                    "교사 확정본 (수정 가능)",
                    height=240,
                    key=teacher_key,
                    placeholder="초안 생성 또는 직접 입력 후 최종 승인하세요.",
                )
                if st.button("최종 승인", key="save_portfolio_comment", width="stretch", type="primary"):
                    body = (st.session_state.get(teacher_key) or "").strip()
                    lv, cmt = st.session_state.get("seuteuk_reflection", ("—", ""))
                    if not body:
                        st.warning("승인할 내용을 입력해 주세요.")
                    else:
                        combined = f"{body}\n\n[성찰 수준: {lv}] {cmt}"
                        save_portfolio_comment(selected_uid, combined, lv, confirmed=True)
                        st.success("학생 포트폴리오에 지도교사 의견이 확정 반영되었습니다.")
            if "seuteuk_reflection" in st.session_state and st.session_state.get("seuteuk_uid") == selected_uid:
                lv, cmt = st.session_state["seuteuk_reflection"]
                st.info(f"**성찰의 수준 (초안 생성 시 참고)**: {lv} — {cmt}")
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("연구자 성찰 로그")
        st.caption("매일의 지도 경험과 지원 효과를 기록 (질적 연구 데이터 확보용)")
        with st.form(key="researcher_log_form", clear_on_submit=True):
            r_date = st.date_input("기록일", value=datetime.date.today(), key="researcher_log_date")
            r_note = st.text_area(
                "성찰 내용 (지도 경험, 지원 효과, 발견된 패턴 등)",
                placeholder="예: 오늘 S03 학생의 BSR 구조화가 전주보다 구체적이었음. 역질문 답변이 해결 과정을 잘 서술함. 납땜/PCB 등 NCS 매칭 정확도 향상.",
                height=120,
                key="researcher_log_note",
            )
            if st.form_submit_button("연구자 로그 저장"):
                if r_note and r_note.strip():
                    add_researcher_log(log_date=str(r_date), note=r_note.strip())
                    st.success("연구자 성찰 로그가 저장되었습니다.")
                else:
                    st.warning("성찰 내용을 입력해 주세요.")
        r_logs = list_researcher_logs()
        if r_logs:
            with st.expander("저장된 연구자 로그 보기", expanded=False):
                for r in r_logs[:20]:
                    st.markdown(f"**{r.get('log_date', '')}**")
                    st.write((r.get("note") or "").replace("\n", " "))
                    st.divider()
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("연구 데이터 내보내기 안내")
        st.caption(
            "전문가 타당도 검토용 통합 CSV·Excel은 「개별 일지 및 성찰 분석」 탭의 "
            "「연구 데이터 분석」 상단에서 내려받을 수 있습니다."
        )
        st.markdown("</div>", unsafe_allow_html=True)

