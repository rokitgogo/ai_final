import datetime
import io
import os
import re
import tempfile

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from bsr_utils import (
    check_evidence_validity,
    extract_background_section,
    get_ai_scaffolding,
    get_reflection_example_sentence,
    radar_scores_from_logs,
    render_bsr_highlighted,
    render_original_vs_refined,
    resolve_google_api_key,
)
from constants import (
    CHECKLIST,
    COLLOQUIAL_TO_NCS,
    DEFAULT_NCS_PROGRESS,
    ELECTRONICS_NCS_UNITS,
    GLOSSARY,
    NCS_DB,
    format_ncs_unit,
    ncs_unit_names_for_prompt,
)
from pathlib import Path

from db import add_log, clear_logs, delete_log, get_confirmed_portfolio_comment, list_logs, update_progress, seed_progress_if_missing
from ui_style import P

# 차트용 메인 컬러
_CHART_PRIMARY = P["primary"]
_CHART_ACCENT = P["accent"]

def _get_google_api_key() -> str | None:
    """Gemini API 키: st.secrets 우선, 없으면 환경 변수 (bsr_utils.resolve_google_api_key)."""
    return resolve_google_api_key()


SYSTEM_PROMPT = """본 시스템은 공업고등학교 전기·전자과 실습 지도용 AI임. 학생 제출 실습 사진을 분석하여 아래 3항목을 반드시 답변함.

**1. 사진 속 주요 장비·기기**
멀티미터, 납땜기, 오실로스코프, 브레드보드, PCB, 전원공급기, 부품·IC, PLC 등 사진에 보이는 장비를 식별하고, 각각 신뢰도(추정%)를 부여함. 예: 멀티미터 (90%), 납땜기 (85%)

**2. NCS 단위 매칭**
해당 실습 활동이 NCS 국가직무능력표준의 어떤 단위와 가장 관련 있는지 판단함.
**전기·전자과 특성상 회로·부품·PCB·계측·임베디드·통신에 해당하면 전자 분야 능력단위를 우선 선택한다.**
반드시 아래 단위명 중 **하나만** 정확히 기재함(앞쪽이 전자·회로 중심):
""" + ncs_unit_names_for_prompt() + """

**3. 안전 수칙 조언**
학생의 안전 보호구(고글, 장갑, 안전화 등) 착용 여부 및 작업 환경의 안전성을 점검하여 조언함. 개선점이 있으면 구체적으로 기재하고, 양호한 경우 해당 사항을 명시함.

반드시 다음 형식으로만 답변함. 다른 내용은 작성하지 않음.

[장비]
- 장비1 (신뢰도%)
- 장비2 (신뢰도%)

[NCS단위]
단위명

[안전조언]
조언 내용"""

def _parse_ai_response(text: str) -> tuple[list[dict], str, str]:
    """AI 응답에서 장비 목록, NCS 단위, 안전 조언을 파싱."""
    detected: list[dict] = []
    suggested_unit = "전자부품장착"  # 기본값
    safety_advice = ""

    # [장비] 섹션 파싱: "- xxx (yy%)" 패턴
    equip_match = re.search(r"\[장비\](.*?)(?=\[NCS단위\]|\Z)", text, re.DOTALL)
    if equip_match:
        for line in equip_match.group(1).strip().split("\n"):
            m = re.search(r"[-•*]\s*(.+?)\s*\((\d+%?)\)", line.strip())
            if m:
                detected.append({"객체": m.group(1).strip(), "신뢰도": m.group(2) if "%" in m.group(2) else m.group(2) + "%"})
            elif line.strip() and not line.strip().startswith("["):
                detected.append({"객체": line.strip().lstrip("-•* "), "신뢰도": "—"})

    # [NCS단위] 섹션 파싱 (공백 제거 후 매칭)
    ncs_match = re.search(r"\[NCS단위\]\s*\n?\s*([^\n\[]+)", text)
    if ncs_match:
        raw = ncs_match.group(1).strip().replace(" ", "")
        if raw in NCS_DB:
            suggested_unit = raw
        else:
            for key in NCS_DB:
                if key.replace(" ", "") == raw or key in raw or raw in key.replace(" ", ""):
                    suggested_unit = key
                    break

    # [안전조언] 섹션 파싱
    safety_match = re.search(r"\[안전조언\](.*)", text, re.DOTALL)
    if safety_match:
        safety_advice = safety_match.group(1).strip()

    if not detected:
        detected = [{"객체": "이미지 분석 완료", "신뢰도": "—"}]
    return detected, suggested_unit, safety_advice


# 시뮬레이션 모드: 키워드 기반 맥락 부여 샘플 (파일명·텍스트 기반)
_SIM_SAMPLES: dict[str, str] = {
    "PLC": """[장비]
- PLC (88%)
- 래더 프로그래머 (82%)
- 입출력 모듈 (78%)
- 시퀀스 릴레이 (75%)

[NCS단위]
PLC제어

[안전조언]
전원 차단 후 결선 작업함. E-STOP 및 인터록 동작을 사전 점검할 것.""",
    "납땜": """[장비]
- 인두기 (90%)
- PCB (85%)
- 멀티미터 (80%)
- 플럭스 (75%)

[NCS단위]
전자부품장착

[안전조언]
고글·환기 유지. 인두기 정리 및 열선 안전 확인할 것.""",
    "계측": """[장비]
- 멀티미터 (90%)
- 오실로스코프 (85%)
- 메거 (80%)
- 테스터 (75%)

[NCS단위]
전자회로조립

[안전조언]
계측 전 무전압 확인. 프로브 절연 상태 점검할 것.""",
    "인버터": """[장비]
- 인버터 (88%)
- 모터 (85%)
- 파라미터 설정기 (80%)

[NCS단위]
인버터제어

[안전조언]
모터 접촉 시 회전 위험. 파라미터 변경 전 백업 확인할 것.""",
    "통신": """[장비]
- RS-485 모듈 (85%)
- Ethernet 스위치 (82%)
- Modbus 어댑터 (78%)

[NCS단위]
산업통신

[안전조언]
통신 케이블 차폐·접지 확인. 노드 주소 충돌 방지할 것.""",
}

_DEFAULT_SIM = """[장비]
- 멀티미터 (85%)
- PCB (80%)
- 납땜기 (90%)
- 브레드보드 (75%)

[NCS단위]
전자부품장착

[안전조언]
작업 시 고글 및 보호구 착용을 권장함. 인두기 사용 후 정리 상태를 확인할 것."""


def _get_simulation_response(file_name: str, content: str) -> str:
    """파일명·텍스트 키워드 기반 시뮬레이션 응답 선정."""
    combined = f"{file_name or ''} {content or ''}".lower()
    scores: dict[str, int] = {}
    for kw, sample in _SIM_SAMPLES.items():
        scores[kw] = combined.count(kw.lower()) + (2 if kw in (file_name or "") else 0)
    best = max(scores, key=scores.get)
    return _SIM_SAMPLES[best] if scores.get(best, 0) > 0 else _DEFAULT_SIM


# 장비명 → 본문 매칭용 유사 표현 (한글 축약, 영문 약어 등)
_EQUIP_ALIASES: dict[str, list[str]] = {
    "멀티미터": ["멀티", "테스터", "전압", "측정"],
    "인두기": ["인두", "납땜", "솔더"],
    "납땜기": ["인두", "납땜", "솔더"],
    "PLC": ["플씨", "래더", "시퀀스"],
    "PCB": ["기판", "회로기판", "피씨비"],
    "오실로스코프": ["오실로", "파형", "주파수"],
    "브레드보드": ["브레드", "점퍼"],
    "전선": ["전선", "배선", "결선"],
    "릴레이": ["릴레이", "계전기"],
    "모터": ["모터", "전동기"],
}


def _build_polish_prompt(bsr_text: str, ncs_unit: str = "", ncs_element: str = "") -> str:
    """NCS 단위·요소를 반영한 다듬기 프롬프트 생성."""
    ncs_context = ""
    if ncs_unit and ncs_unit in NCS_DB:
        meta = NCS_DB[ncs_unit]
        kw = meta.get("keywords", [])[:12]
        elem = meta.get("elements", [])
        ncs_context = f"""
**참고: 이 실습은 NCS 능력단위 '{ncs_unit}'의 '{ncs_element or elem[0] if elem else ""}' 수행요소와 연관됩니다.**
- 활용할 키워드/직무용어: {", ".join(kw)}
- 수행요소 예: {", ".join(elem)}
위 키워드·수행요소를 참고하여 단순한 동작을 전문적 기술 행위로 묘사하세요.
"""
    return f"""당신은 공업고등학교 NCS(국가직무능력표준) 수행준거 작성 전문가이자 교육공학 전문가입니다.
학생이 작성한 일상적 말투의 실습 성찰(B-S-R)을 **NCS 수행준거 양식**의 격식 있는 문장으로 변환해 주세요.

**【말투 변환 규칙】**
- "~했어요", "~했음", "~했습니다" → "~할 수 있게 됨", "~를 확인하고 해결함", "~의 중요성을 인지함"
- "~해서", "~했더니" → "~를 수행한 결과", "~을 적용하여"
- 구어체·약어 → 공식적 NCS 직무표준 용어로 치환

**【내용 보강 규칙】**
- 단순한 동작("납땜함") → 전문적 기술 행위로 확장("회로도에 따른 부품 극성을 확인하고 접합부 냉땜 여부를 점검하며 납땜 작업을 완수함")
- 아래 NCS 단위 키워드·수행요소를 참고하여 원문 맥락에 맞게 구체화
{ncs_context}

**【구조 유지 규칙】**
- 반드시 [배경], [해결], [성과] 형식을 그대로 유지
- [체크리스트: …]가 있으면 그대로 유지
- 전문 용어(NCS·직무용어)는 정확히 보존
- 지나치게 길게 늘리지 말고, 핵심만 담음

**【입력 텍스트】**
---
{bsr_text}
---

위 내용을 NCS 수행준거 양식으로 다듬은 결과만 출력하세요. 설명·주석·마크다운 제목은 넣지 마세요."""


def _polish_bsr_with_gemini(bsr_text: str, ncs_unit: str = "", ncs_element: str = "") -> str | None:
    """Gemini API로 BSR 전체를 NCS 수행준거 양식으로 다듬기. ncs_unit/element로 내용 보강 참조. 실패 시 None."""
    api_key = _get_google_api_key()
    if not api_key:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = _build_polish_prompt(bsr_text, ncs_unit, ncs_element)
        response = model.generate_content(prompt, generation_config={"temperature": 0.3, "max_output_tokens": 2048})
        if response and response.text:
            return response.text.strip()
    except Exception:
        pass
    return None


def _check_evidence_content_match(equip_names: list[str], content: str) -> bool:
    """
    탐지된 장비와 학생 본문의 연관성을 검사. 연관성이 너무 낮으면 False.
    (증거-텍스트 교차 검증용)
    """
    if not equip_names or not (content or "").strip():
        return True  # 판단 불가 시 통과
    text_raw = content.strip()
    text_lower = text_raw.lower()
    for eq in equip_names:
        eq_clean = (eq or "").strip()
        if len(eq_clean) < 2:
            continue
        if eq_clean in text_raw or eq_clean.lower() in text_lower:
            return True
        for alias in _EQUIP_ALIASES.get(eq_clean, []):
            if alias in text_raw or alias in text_lower:
                return True
        if len(eq_clean) >= 3 and (eq_clean[:3] in text_raw or eq_clean[:3] in text_lower):
            return True
        for token in eq_clean.replace("-", " ").split():
            if len(token) >= 2 and (token in text_raw or token in text_lower):
                return True
    return False


def _semantic_evidence_mismatch(equip_names: list[str], content: str, suggested_unit: str) -> bool:
    """
    사진·NCS 단위가 시사하는 직무 영역과 본문 키워드가 명백히 엇갈릴 때 True.
    (예: 사진·단위는 PLC인데 본문은 인버터만 서술)
    """
    text = (content or "").strip()
    if len(text) < 12:
        return False
    blob = " ".join(equip_names or []) + " " + (suggested_unit or "")
    # PLC 계열 신호
    plc_photo = any(
        k in blob
        for k in ("PLC", "래더", "시퀀스", "프로그래머", "입출력", "PLC제어")
    )
    plc_text = sum(1 for k in ("PLC", "래더", "시퀀스", "입출력", "프로그램") if k in text)
    inv_text = sum(1 for k in ("인버터", "VFD", "VF", "주파수 변환") if k in text)
    if plc_photo and inv_text >= 1 and plc_text == 0:
        return True
    # 인버터 계열 사진인데 본문만 PLC
    inv_photo = "인버터" in blob or "인버터제어" in (suggested_unit or "")
    if inv_photo and plc_text >= 1 and inv_text == 0:
        return True
    return False


def analyze_image(image_file, use_real_api: bool = True, content: str = "", file_name: str = "") -> tuple[list[dict], str, str]:
    """
    실습 사진 분석. use_real_api=False이거나 Quota 초과 시 시뮬레이션 모드로 자동 전환.
    반환: (탐지된 장비 목록, 추천 NCS 단위, 안전 조언)
    """
    use_sim_key = "analyze_force_sim_mode"
    if st.session_state.get(use_sim_key, False):
        use_real_api = False
    if not use_real_api:
        sim_text = _get_simulation_response(
            file_name or getattr(image_file, "name", ""),
            content,
        )
        return _parse_ai_response(sim_text)

    api_key = _get_google_api_key()
    if not api_key:
        st.error(
            "**Google AI API 키가 설정되지 않았습니다.**\n\n"
            "`.streamlit/secrets.toml`에 `GOOGLE_API_KEY = \"your-key\"` 를 추가하거나, "
            "환경 변수 `GOOGLE_API_KEY`를 설정해 주세요. "
            "**관리자에게 API 설정을 확인하세요.**\n\n"
            "[Google AI Studio](https://aistudio.google.com/apikey)에서 API 키를 발급받을 수 있습니다."
        )
        return (
            [{"객체": "API 키 미설정", "신뢰도": "—"}],
            "전자부품장착",
            "API 키를 설정한 후 다시 시도해 주세요.",
        )

    try:
        import google.generativeai as genai
        from PIL import Image

        image_file.seek(0)
        img_bytes = image_file.read()
        try:
            pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        except (OSError, ValueError) as img_err:
            st.warning(
                "이미지를 불러오지 못했습니다. 파일이 손상되었거나 지원하지 않는 형식일 수 있습니다. "
                "JPG·PNG 이미지로 다시 업로드해 주세요."
            )
            return (
                [{"객체": "이미지 로드 실패", "신뢰도": "—"}],
                "전자부품장착",
                "이미지 파일을 열 수 없습니다. 다른 파일로 시도해 주세요.",
            )

        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")

        response = model.generate_content(
            [SYSTEM_PROMPT, pil_img],
            generation_config={"temperature": 0.2, "max_output_tokens": 1024},
        )

        if not response.text:
            return (
                [{"객체": "분석 결과 없음", "신뢰도": "—"}],
                "전자부품장착",
                "AI가 답변을 생성하지 못했습니다. 다른 사진으로 시도해 보세요.",
            )

        detected, suggested_unit, safety_advice = _parse_ai_response(response.text)
        return detected, suggested_unit, safety_advice

    except Exception as e:
        err_msg = str(e).lower()
        st.error(
            "**이미지 분석 API를 사용할 수 없습니다.**\n\n"
            "할당량 초과·네트워크 오류·인증 오류 등으로 요청이 완료되지 않았을 수 있습니다. "
            "**관리자에게 API 설정을 확인하세요.**"
        )
        # API 실패 시 견고한 방어: 시뮬레이션 모드로 전환해 시연 연속성 확보
        if (
            "quota" in err_msg
            or "resource exhausted" in err_msg
            or "network" in err_msg
            or "connection" in err_msg
            or "timeout" in err_msg
            or "429" in err_msg
            or "503" in err_msg
        ):
            st.session_state["analyze_force_sim_mode"] = True
            st.info("안정적인 시연을 위해 로컬 분석 모드로 전환합니다.")
            sim_text = _get_simulation_response(
                getattr(image_file, "name", ""), content
            )
            return _parse_ai_response(sim_text)
        st.session_state["analyze_force_sim_mode"] = True
        st.info("안정적인 시연을 위해 로컬 분석 모드로 전환합니다.")
        sim_text = _get_simulation_response(
            getattr(image_file, "name", ""), content
        )
        return _parse_ai_response(sim_text)


def _detect_ncs_unit(content: str, image_hint: str | None = None) -> str:
    """텍스트 키워드로 NCS 매칭. 텍스트가 비거나 매칭 없으면 image_hint(사진 분석) 사용. 동점 시 전자 능력단위 우선."""
    text = (content or "").strip()
    scores: dict[str, int] = {}
    for unit, meta in NCS_DB.items():
        scores[unit] = 0
        for kw in meta.get("keywords", []):
            if kw and kw in text:
                scores[unit] += 1

    best_score = max(scores.values()) if scores else 0

    # 텍스트가 비었거나, 키워드 매칭이 없을 때 → 사진이 있으면 사진 힌트 사용
    if (not text or best_score == 0) and image_hint and image_hint in NCS_DB:
        return image_hint
    if best_score == 0:
        return "전자회로조립"  # 힌트도 없으면 전자 실습 기본값

    candidates = [u for u, s in scores.items() if s == best_score]
    if len(candidates) == 1:
        return candidates[0]
    for u in ELECTRONICS_NCS_UNITS:
        if u in candidates:
            return u
    return sorted(candidates)[0]


def _detect_element(unit: str, content: str) -> str:
    """NCS 능력단위별 세부 요소(Element) 매칭. 용산철도고 교과 범위 반영."""
    text = content or ""
    if unit == "PLC제어":
        if any(k in text for k in ["결선", "배선", "I/O", "입출력", "입출력결선"]):
            return "입출력 결선하기"
        if any(k in text for k in ["시운전", "테스트", "동작", "디버깅", "트러블"]):
            return "시운전하기"
        return "프로그램 작성하기"

    if unit == "전자부품장착":
        if any(k in text for k in ["납땜", "솔더", "솔더링"]):
            return "납땜하기"
        if any(k in text for k in ["검사", "불량", "테스터", "멀티미터", "측정", "수리", "고쳤", "핸드폰", "폰", "도통", "연속성"]):
            return "부품 검사하기"
        return "장착 상태 점검하기"

    if unit == "인버터제어":
        if any(k in text for k in ["파라미터", "설정", "주파수", "가감속", "VFD"]):
            return "파라미터 설정하기"
        if any(k in text for k in ["배선", "통신", "RS485", "Modbus", "연결"]):
            return "배선/통신 연결하기"
        return "운전 튜닝하기"

    if unit == "산업통신":
        if any(k in text for k in ["네트워크", "노드", "주소", "IP", "토폴로지"]):
            return "네트워크 구성하기"
        if any(k in text for k in ["장애", "타임아웃", "프레임", "오류"]):
            return "통신 장애 분석하기"
        return "장비 통신 설정하기"

    if unit == "모터제어":
        if any(k in text for k in ["회로", "결선", "MC", "OLR", "Y-Δ", "스타델타"]):
            return "회로 구성하기"
        if any(k in text for k in ["시퀀스", "운전", "정역", "역전"]):
            return "시퀀스 운전하기"
        return "보호장치 적용하기"

    if unit == "센서응용":
        if any(k in text for k in ["선정", "근접", "포토", "엔코더", "NPN", "PNP"]):
            return "센서 선정하기"
        if any(k in text for k in ["배선", "설치", "0-10V", "4-20mA"]):
            return "배선/설치하기"
        return "신호 점검하기"

    if unit == "마이크로컨트롤러":
        if any(k in text for k in ["GPIO", "PWM", "입출력", "LED"]):
            return "입출력 제어하기"
        if any(k in text for k in ["UART", "I2C", "SPI", "통신", "시리얼"]):
            return "통신 구현하기"
        return "디버깅하기"

    if unit == "전기안전":
        if any(k in text for k in ["위험", "파악", "LOTO", "차단"]):
            return "위험요인 파악하기"
        if any(k in text for k in ["PPE", "보호구", "고글", "장갑"]):
            return "안전조치 수행하기"
        return "점검 기록하기"

    if unit == "전기설비시공":
        if any(k in text for k in ["배관", "배선", "전선", "덕트", "트레이"]):
            return "배관·배선하기"
        if any(k in text for k in ["절연", "접지", "메거", "절연저항"]):
            return "절연·접지 점검하기"
        return "기기 설치하기"

    if unit == "전기설비유지보수":
        if any(k in text for k in ["정기", "점검", "열화상", "일정"]):
            return "정기 점검하기"
        if any(k in text for k in ["고장", "진단", "트러블", "이상"]):
            return "고장 진단하기"
        return "부품 교체하기"

    if unit == "전자회로조립":
        if any(k in text for k in ["준비", "부품", "극성", "데이터시트"]):
            return "부품 준비하기"
        if any(k in text for k in ["기능", "점검", "측정", "전압"]):
            return "기능 점검하기"
        return "회로 조립하기"

    if unit == "전자회로설계":
        if any(k in text for k in ["해석", "회로도", "이득", "주파수"]):
            return "회로 해석하기"
        if any(k in text for k in ["시뮬레이션", "SPICE", "검증"]):
            return "시뮬레이션/검증하기"
        return "회로 설계하기"

    if unit == "PCB설계":
        if any(k in text for k in ["배치", "부품 배치", "레이아웃"]):
            return "부품 배치하기"
        if any(k in text for k in ["라우팅", "패턴", "GND", "비아"]):
            return "패턴 라우팅하기"
        return "DRC/제조데이터 출력하기"

    if unit == "임베디드하드웨어설계":
        if any(k in text for k in ["사양", "정의", "요구사항"]):
            return "시스템 사양 정의하기"
        if any(k in text for k in ["레이아웃", "검증"]):
            return "레이아웃 검증하기"
        if any(k in text for k in ["회로", "스키매틱", "센서", "MCU"]):
            return "회로 설계하기"
        return "회로 설계하기"

    if unit == "임베디드소프트웨어개발":
        if any(k in text for k in ["디버깅", "검증"]):
            return "디버깅·검증하기"
        if any(k in text for k in ["코드", "구현", "C", "드라이버"]):
            return "코드 구현하기"
        return "펌웨어 설계하기"

    if unit == "반도체제조":
        if any(k in text for k in ["웨이퍼", "준비"]):
            return "웨이퍼 준비하기"
        if any(k in text for k in ["검사", "측정", "품질"]):
            return "품질 검사하기"
        if any(k in text for k in ["공정", "포토", "에칭", "박막", "리소그래피"]):
            return "공정 수행하기"
        return "공정 수행하기"

    if unit == "통신기기하드웨어개발":
        if any(k in text for k in ["RF", "안테나", "기저대역"]):
            return "RF/기저대역 구현하기"
        if any(k in text for k in ["회로", "통신"]):
            return "통신 회로 설계하기"
        return "통신 회로 설계하기"

    if unit == "디지털방송기기개발":
        if any(k in text for k in ["인코딩", "디코딩", "부호화"]):
            return "인코딩/디코딩 구현하기"
        if any(k in text for k in ["신호", "방송"]):
            return "방송 신호 처리 설계하기"
        return "방송 신호 처리 설계하기"

    if unit == "스마트가전기기개발":
        if any(k in text for k in ["인터페이스", "설계"]):
            return "IoT 인터페이스 설계하기"
        if any(k in text for k in ["연동", "검증", "센서", "IoT"]):
            return "연동 검증하기"
        return "IoT 인터페이스 설계하기"

    return NCS_DB.get(unit, {}).get("elements", ["해당 요소"])[0]


def _build_bsr_string(background: str, haegyul: str, seungwa: str, checked_items: list[str]) -> str:
    """표준 BSR 문자열 조합: [배경][해결][성과][체크리스트]"""
    parts = [f"[배경] {background or ''}"]
    if haegyul:
        parts.append(f"[해결] {haegyul}")
    if seungwa:
        parts.append(f"[성과] {seungwa}")
    if checked_items:
        parts.append(f"[체크리스트: {'; '.join(checked_items)}]")
    return " ".join(parts)


def _convert_to_ncs_terms(text: str) -> list[tuple[str, str, str]]:
    """학생이 쉽게 말한 구어를 NCS 직무표준 용어로 변환하여 (구어, NCS용어, 설명) 반환."""
    if not (t := (text or "").strip()):
        return []
    t_lower = t.lower()
    found: list[tuple[str, str, str]] = []
    for phrases, ncs_term, desc in COLLOQUIAL_TO_NCS:
        for p in phrases:
            if p in t or p.lower() in t_lower:
                found.append((p, ncs_term, desc))
                break
    return found


def _rewrite_to_ncs_terms_fallback(text: str) -> str:
    """사전 치환 기반 폴백 (API 실패 시)."""
    if not (t := (text or "").strip()):
        return ""
    t_lower = t.lower()
    replacements: list[tuple[str, str]] = []
    for phrases, ncs_term, _ in COLLOQUIAL_TO_NCS:
        for p in phrases:
            if not p:
                continue
            if p in t:
                replacements.append((p, ncs_term))
                break
            if p.lower() in t_lower:
                idx = t_lower.find(p.lower())
                actual = t[idx : idx + len(p)]
                replacements.append((actual, ncs_term))
                break
    replacements.sort(key=lambda x: -len(x[0]))
    result = t
    for phrase, ncs_term in replacements:
        result = result.replace(phrase, ncs_term)
    return result


REWRITE_NCS_PROMPT = """당신은 공업고등학교 NCS(국가직무능력표준) 수행준거 작성 전문가입니다.
학생의 구어체 실습 기록을 **NCS 수행준거 양식(~할 수 있다, ~함)**과 전문 기술 용어를 사용하여 격식 있는 전문가 톤으로 다듬어라.

규칙:
1. 없는 사실을 지어내지 말고, 학생이 쓴 핵심 동작(예: 납땜, 패턴도 확인, PLC 프로그래밍 등)은 반드시 포함한다.
2. 출력 형식: [능력단위명(NCS코드)] ... 내용 ... 형태로 시작. 예: [전자부품장착(1902020101_16v3)] 설계된 패턴도를 분석하여 회로의 연결성을 확인하고, 규격에 맞는 납땜 작업을 통해 부품 장착을 완료함.
3. 능력단위·코드는 입력 내용에서 추론(납땜·PCB·전자→전자부품장착 1902020101_16v3, PLC·래더→PLC제어 1902050106_14v1 등). 확실하지 않으면 전자부품장착 등 보수적으로 선택.
4. ~함, ~완료함, ~확인함 등 수행준거 표현 사용. 짧은 입력이면 1문장으로 완결.
5. 입력에 [배경][해결][성과] 구조가 있으면 각 구간을 유지하며 다듬되, 원문에 없는 내용은 추가하지 말 것.

입력 (학생 구어체):
---
{text}
---

다듬은 결과만 출력. 설명·주석 없음."""


def _rewrite_to_ncs_terms_with_gemini(text: str) -> str | None:
    """Gemini API로 구어체를 NCS 전문가 톤 1문장으로 변환. 실패 시 None."""
    api_key = _get_google_api_key()
    if not api_key or not (t := (text or "").strip()) or len(t) < 5:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = REWRITE_NCS_PROMPT.format(text=t)
        response = model.generate_content(
            prompt, generation_config={"temperature": 0.3, "max_output_tokens": 512}
        )
        if response and response.text:
            return response.text.strip()
    except Exception:
        pass
    return None


def _rewrite_to_ncs_terms(text: str, use_gemini: bool = True) -> str:
    """실습 기록을 NCS 표준용어로 풀어써서 반환. use_gemini=True이면 Gemini AI 활용, 실패 시 사전 치환 폴백."""
    if not (t := (text or "").strip()):
        return ""
    if use_gemini:
        result = _rewrite_to_ncs_terms_with_gemini(t)
        if result:
            return result
    return _rewrite_to_ncs_terms_fallback(t)


STT_PROMPT = """이 오디오는 공업고등학교 학생이 오늘 한 실습 내용을 설명하는 음성이야. 학생의 말을 정확하게 텍스트로 받아쓰기(Transcription) 해줘. 잡음은 제외하고 핵심 내용만 정리해."""


def _transcribe_audio_with_gemini(audio_bytes: bytes, mime_type: str = "audio/wav") -> str | None:
    """Gemini API로 오디오를 텍스트로 변환(STT). 실패 시 None."""
    api_key = _get_google_api_key()
    if not api_key or not audio_bytes:
        return None
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        # BytesIO 또는 tempfile로 업로드 (패키지 버전에 따라 지원 다름)
        try:
            uploaded = genai.upload_file(path=io.BytesIO(audio_bytes), mime_type=mime_type)
        except (TypeError, ValueError):
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(audio_bytes)
                tmp_path = tmp.name
            try:
                uploaded = genai.upload_file(path=tmp_path, mime_type=mime_type)
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        response = model.generate_content(
            [STT_PROMPT, uploaded],
            generation_config={"temperature": 0.1, "max_output_tokens": 1024},
        )
        if response and response.text:
            return response.text.strip()
    except Exception:
        return None
    return None


AI_GROWTH_PROMPT = """당신은 공업고등학교 NCS 직무 역량 코치입니다. 학생의 실습 BSR(배경-해결-성과) 이력을 분석하여 맞춤형 성장 조언을 작성해 주세요.

다음 3가지를 **전문가 톤**으로 조언해 주세요. 각 항목당 2~3문장.
1. 현재 가장 뛰어난 직무 강점 (구체적 사례 기반)
2. 보완이 필요한 성찰 포인트 (메타인지·과정 서술 강화 방향)
3. 다음 실습 시 도전해볼 '미션' (구체적 행동 제안 1가지)

BSR 이력:
---
{bsr_history}
---

조언만 출력. 마크다운 제목·번호 없이 본문만."""


def _get_ai_growth_report(bsr_logs: list[dict]) -> str | None:
    """Gemini API로 BSR 이력 기반 AI 맞춤형 성장 총평 생성. 실패 시 None."""
    if not bsr_logs:
        return None
    api_key = _get_google_api_key()
    if not api_key:
        return None
    history = "\n\n".join(
        f"[{r.get('date','')}] {r.get('ncs_unit','')}\n{str(r.get('bsr',''))[:800]}"
        for r in bsr_logs[:15]
    )
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = AI_GROWTH_PROMPT.format(bsr_history=history)
        response = model.generate_content(
            prompt, generation_config={"temperature": 0.5, "max_output_tokens": 1024}
        )
        if response and response.text:
            return response.text.strip()
    except Exception:
        pass
    return None


def _seungwa_char_count(bsr: str) -> int:
    """[성과] 구간 글자 수 (성찰 깊이 근사)."""
    m = re.search(r"\[성과\]\s*(.*?)(?=\[|$)", (bsr or ""), re.DOTALL)
    return len(m.group(1).strip()) if m else 0


def _professional_term_hits(bsr: str) -> int:
    """BSR에 등장하는 서로 다른 GLOSSARY·NCS 키워드 개수(빈도 근사)."""
    t = bsr or ""
    seen: set[str] = set()
    for term in GLOSSARY:
        if term in t:
            seen.add(term)
    for meta in NCS_DB.values():
        for kw in meta.get("keywords", []):
            if kw and len(kw) >= 2 and kw in t:
                seen.add(kw)
    return min(len(seen), 50)


def _build_last3_meta_stats_block(logs: list[dict]) -> str:
    """최근 3개 일지의 성찰·용어 지표를 Gemini용 텍스트로 정리."""
    recent = logs[:3]
    lines: list[str] = []
    for i, row in enumerate(recent, start=1):
        bsr = str(row.get("bsr") or "")
        date = row.get("date", "")
        unit = row.get("ncs_unit", "")
        sc = _seungwa_char_count(bsr)
        th = _professional_term_hits(bsr)
        lines.append(
            f"일지 {i} [{date}] 능력단위:{unit}\n"
            f"  - [성과] 구간 글자 수(성찰 깊이 근사): {sc}자\n"
            f"  - 전문 용어 매칭 빈도(근사): {th}\n"
            f"  - BSR 앞부분 요약: {(bsr[:200] + '…') if len(bsr) > 200 else bsr}"
        )
    return "\n\n".join(lines)


AI_META_COACH_PROMPT = """당신은 공업고등학교 NCS 직무 역량을 지도하는 교육·메타인지 코치입니다.

아래는 한 학생의 **최근 3개 실습 일지**에 대해 산출한 지표입니다. 각 일지마다 [성과] 구간 글자 수(성찰 깊이 근사)와 전문 용어 매칭 빈도를 비교할 수 있습니다.

---
{stats_block}
---

**작성 지침**
1. 세 일지를 비교하여 **성장한 점**을 구체적으로 칭찬하세요 (성찰의 깊이, 전문 용어 사용 측면).
2. **보완할 점**을 구체적으로 제시하세요. 특히 [성과] 구간이 짧거나 메타인지적 표현(이유, 깨달음, 다음에는 등)이 부족한 경우를 짚어 주세요.
3. 전문가 톤, 2~4문단. 번호·마크다운 제목 없이 본문만 서술하세요."""


def _get_ai_meta_coach_comment(logs: list[dict]) -> str | None:
    """최근 3개 일지 기반 메타인지·성장 코멘트 (Gemini). 실패 시 None."""
    if not logs:
        return None
    api_key = _get_google_api_key()
    if not api_key:
        return None
    stats_block = _build_last3_meta_stats_block(logs)
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        prompt = AI_META_COACH_PROMPT.format(stats_block=stats_block)
        response = model.generate_content(
            prompt, generation_config={"temperature": 0.45, "max_output_tokens": 1200}
        )
        if response and response.text:
            return response.text.strip()
    except Exception:
        pass
    return None


def _log_competency_scores(bsr_text: str) -> dict[str, float]:
    """BSR 텍스트에서 역량 차원 점수 (구체성, 전문용어, 안전, 성찰)."""
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


def _evaluate_seungwa_reflection(bsr_logs: list[dict]) -> tuple[str, str]:
    """BSR 로그에서 성찰 수준(높음/보통/낮음)과 코멘트 반환."""
    high_words = {"깨달음", "성찰", "과정", "이유", "개선", "다음에는", "배운", "어려웠던", "스스로", "이해", "알게", "생각", "판단", "고민"}
    medium_words = {"확인", "점검", "수행", "적용", "이해함", "배웠"}
    low_patterns = ["했다", "됐다", "완료", "끝냄", "했다."]
    scores: list[int] = []
    for row in bsr_logs:
        bsr = (row.get("bsr") or "").strip()
        m = re.search(r"\[성과\]\s*(.*?)(?=\[|$)", bsr, re.DOTALL)
        if m:
            seg = m.group(1).strip()
            score = 0
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
        return "높음", "과정·이유·개선점을 구체적으로 서술하여 메타인지적 성찰 수준이 높습니다."
    if avg >= 1.5:
        return "보통", "기본적인 수행 중심 기술에 일부 성찰 요소가 포함되어 있습니다."
    return "낮음", "결과 중심의 간단한 서술 위주이며, 성찰 키워드 보완을 권장합니다."


def _extract_used_professional_terms(logs: list[dict]) -> list[str]:
    """일지에서 사용된 NCS·GLOSSARY 매칭 전문 용어 목록 (중복 제거, 사용 빈도순)."""
    all_terms: set[str] = set(GLOSSARY.keys())
    for meta in NCS_DB.values():
        all_terms.update(k for k in meta.get("keywords", []) if k and len(k) >= 2)
    for _, ncs_term, _ in COLLOQUIAL_TO_NCS:
        if ncs_term and len(ncs_term) >= 2:
            all_terms.add(ncs_term)
    used: dict[str, int] = {}
    for row in logs:
        text = (row.get("bsr") or "").strip()
        for term in sorted(all_terms, key=len, reverse=True):
            if term in text:
                used[term] = used.get(term, 0) + 1
    return [t for t, _ in sorted(used.items(), key=lambda x: -x[1])]


def _compute_ncs_term_ratio(bsr_text: str) -> float:
    """BSR 내 구어체 대비 NCS 표준 용어 사용 비율(0~100)."""
    if not (t := (bsr_text or "").strip()):
        return 0.0
    all_ncs: set[str] = set(GLOSSARY.keys())
    for meta in NCS_DB.values():
        all_ncs.update(k for k in meta.get("keywords", []) if k and len(k) >= 2)
    for _, ncs_term, _ in COLLOQUIAL_TO_NCS:
        if ncs_term and len(ncs_term) >= 2:
            all_ncs.add(ncs_term)
    ncs_found = sum(1 for term in all_ncs if term in t)
    word_count = max(1, len([w for w in re.sub(r"[^\w\s]", " ", t).split() if len(w) >= 2]))
    return min(100.0, round(100.0 * ncs_found / min(25, word_count), 1))


def show_student(uid: str) -> None:
    st.header(f"{int(uid[1:])}번 도제생 직무 역량 관리")

    # NCS 이수 현황 (Progress + 그래프)
    st.subheader("실시간 NCS 이수 현황")
    prog = st.session_state.ncs_progress or {}
    logs_for_chart = list_logs(uid)

    if not logs_for_chart:
        st.info("저장된 실습일지가 없음. 일지를 저장하면 NCS 진행률 및 그래프가 표시됨.")
    else:
        for unit, val in prog.items():
            st.write(f"{format_ncs_unit(unit)} ({val}%)")
            st.progress(val / 100)

        if prog:
            col_bar, col_radar = st.columns(2)

            with col_bar:
                st.caption("단위별 진행률 막대 그래프")
                bar_df = pd.DataFrame(
                    {"단위": [format_ncs_unit(u) for u in prog.keys()], "진행률(%)": list(prog.values())}
                )
                bar_fig = px.bar(
                    bar_df,
                    x="단위",
                    y="진행률(%)",
                    color_discrete_sequence=[_CHART_PRIMARY],
                )
                bar_fig.update_layout(
                    margin=dict(l=40, r=40, t=30, b=40),
                    showlegend=False,
                    xaxis_title="",
                    yaxis_title="진행률(%)",
                    paper_bgcolor="rgba(255,255,255,0)",
                    plot_bgcolor="rgba(255,255,255,0)",
                    height=320,
                )
                bar_fig.update_traces(marker_line_width=0)
                st.plotly_chart(bar_fig, width="stretch")

            with col_radar:
                st.caption("직무 영역 레이더 차트 (설계/제작/계측/제어/안전)")
                text_all = " ".join(str(r.get("bsr", "")) for r in logs_for_chart)
                axes = ["설계", "제작", "계측", "제어", "안전"]
                keywords = {
                    "설계": ["설계", "회로도", "스키매틱", "시뮬레이션"],
                    "제작": ["조립", "납땜", "배선", "배관", "장착"],
                    "계측": ["측정", "멀티미터", "오실로스코프", "메거", "계측"],
                    "제어": ["PLC", "인버터", "시퀀스", "프로그램", "모터제어"],
                    "안전": ["안전", "접지", "감전", "보호구", "LOTO", "인터록"],
                }
                scores = []
                for a in axes:
                    s = sum(text_all.count(k) for k in keywords[a])
                    scores.append(s)
                if sum(scores) == 0:
                    scores = [1, 1, 1, 1, 1]

                values = np.array(scores, dtype=float)
                values = values / values.max() * 100.0
                r_vals = list(values) + [values[0]]
                theta_vals = axes + [axes[0]]

                # 프로페셔널 역량 보고서 스타일: 가이드라인(25,50,75) + 그라데이션 느낌
                fig = go.Figure()
                for ring in [25, 50, 75]:
                    fig.add_trace(
                        go.Scatterpolar(
                            r=[ring] * (len(axes) + 1),
                            theta=theta_vals,
                            fill="toself",
                            fillcolor="rgba(30, 58, 95, 0.04)",
                            line=dict(color="rgba(30, 58, 95, 0.2)", width=1, dash="dot"),
                            name="",
                            showlegend=False,
                        )
                    )
                fig.add_trace(
                    go.Scatterpolar(
                        r=r_vals,
                        theta=theta_vals,
                        fill="toself",
                        line=dict(color=_CHART_PRIMARY, width=2),
                        fillcolor="rgba(30, 58, 95, 0.15)",
                        showlegend=False,
                    )
                )
                fig.update_layout(
                    polar=dict(
                        radialaxis=dict(
                            visible=True,
                            range=[0, 100],
                            tickvals=[0, 25, 50, 75, 100],
                            tickfont=dict(size=11, color="#64748b"),
                            gridcolor="rgba(30, 58, 95, 0.12)",
                            linecolor="rgba(30, 58, 95, 0.15)",
                        ),
                        angularaxis=dict(
                            tickfont=dict(size=12, color=P["text"]),
                            gridcolor="rgba(30, 58, 95, 0.12)",
                        ),
                        bgcolor="rgba(248, 250, 252, 0.6)",
                    ),
                    paper_bgcolor="rgba(255,255,255,0)",
                    plot_bgcolor="rgba(255,255,255,0)",
                    margin=dict(l=70, r=70, t=50, b=50),
                    showlegend=False,
                    height=340,
                )
                st.plotly_chart(fig, width="stretch")
            st.caption("본 수치는 NCS 직무수행태도 및 수행준거에 기반하여 산출됨")

    tab1, tab2, tab3, tab4 = st.tabs(
        ["실습 일지 작성", "실습 이력 관리", "AI 성장 진단", "NCS 종합 직무 포트폴리오"]
    )

    with tab1:
        st.markdown(
            "<div class='report-card'><h3 style='margin-top:0;'>오늘의 실습 성찰 및 증거 제출</h3>",
            unsafe_allow_html=True,
        )
        # 하이브리드 분석: 체크 해제 시 샘플 답변 사용(API 호출 없음)
        use_real_ai = st.checkbox(
            "AI 실제 분석 사용 (체크 해제 시 시뮬레이션 모드, API 미호출)",
            value=True,
            key=f"use_real_ai_{uid}",
        )
        st.caption("좌측에 [배경]·[해결]·[성찰]을 작성하고, 우측에서 장비 인식·NCS 용어 미리보기를 확인하세요.")
        col_bg, col_ev = st.columns([1, 1])
        with col_bg:
            content = st.text_area(
                "[배경] 오늘의 실습 상황",
                height=150,
                placeholder="예: 오늘은 PLC 래더 로직을 작성하고, 입출력 결선 후 시운전했습니다. 멀티미터로 전압을 측정했고, 접지 상태도 점검했습니다.",
                key=f"content_{uid}",
            )
        with col_ev:
            img = st.file_uploader("실습 증거 사진 업로드", type=["jpg", "png"])
            if img:
                force_sim = st.session_state.get("analyze_force_sim_mode", False)
                with st.spinner(
                    "실습 사진 분석 및 NCS 단위 매칭 진행 중..."
                    if (use_real_ai and not force_sim)
                    else "시뮬레이션 모드로 표시 중..."
                ):
                    result = analyze_image(
                        img,
                        use_real_api=use_real_ai and not force_sim,
                        content=content or "",
                        file_name=getattr(img, "name", ""),
                    )
                detected, suggested_unit = result[:2]
                safety_advice = result[2] if len(result) > 2 else ""
                st.session_state[f"img_result_{uid}"] = (detected, suggested_unit, safety_advice)
                semantic_low = False
                if (
                    content
                    and content.strip()
                    and use_real_ai
                    and not force_sim
                    and _get_google_api_key()
                    and extract_background_section(content).strip()
                ):
                    try:
                        img.seek(0)
                        ev = check_evidence_validity(img, content, api_key=_get_google_api_key())
                        semantic_low = ev < 40.0
                    except Exception:
                        semantic_low = False
                if semantic_low:
                    st.warning("증거 사진과 본문의 연관성이 낮습니다. 사진을 확인해 주세요.")
                elif content and content.strip():
                    equip_names = [d.get("객체", "") for d in detected if d.get("객체")]
                    _evidence_text_match = _check_evidence_content_match(equip_names, content)
                    _domain_mismatch = _semantic_evidence_mismatch(equip_names, content, suggested_unit)
                    if not _evidence_text_match or _domain_mismatch:
                        st.warning(
                            "**증거 사진과 내용의 연관성이 낮아 보입니다.** "
                            "사진에 보이는 장비·활동과 본문이 잘 맞는지 확인해 주세요."
                        )
                safety_score = min(
                    5,
                    1 + sum(1 for k in ["접지", "보호구", "안전", "LOTO"] if safety_advice and k in safety_advice),
                )
                st.image(img, width="stretch")
                st.markdown("#### 실습 분석 결과")
                st.markdown(
                    "<div class='report-card' style='padding:1rem; margin-bottom:0.75rem;'>"
                    "<b>인식된 장비</b><br/>" + "<br/>".join(
                        f"• {d['객체']} ({d.get('신뢰도', '—')})" for d in detected[:6]
                    ) + "</div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='report-card' style='padding:1rem; margin-bottom:0.75rem;'>"
                    f"<b>추천 NCS 단위</b><br/><span style='color:#1e3a5f; font-weight:600;'>{format_ncs_unit(suggested_unit)}</span></div>",
                    unsafe_allow_html=True,
                )
                st.markdown(
                    f"<div class='report-card' style='padding:1rem; margin-bottom:0.75rem;'>"
                    f"<b>안전 점검</b><br/><span style='color:#059669; font-weight:600;'>{safety_score}/5</span>"
                    + (
                        f"<br/><small>{safety_advice[:80]}…</small>"
                        if safety_advice and len(safety_advice) > 80
                        else f"<br/><small>{safety_advice or '—'}</small>"
                    )
                    + "</div>",
                    unsafe_allow_html=True,
                )
            else:
                img = None
                st.caption("증거 사진을 업로드하면 장비 인식·NCS 추천·안전 코멘트가 표시됩니다.")

        # 음성 입력 (녹음) → Gemini STT
        audio = st.audio_input("음성으로 실습 설명하기 (선택)")
        if audio:
            st.audio(audio, format="audio/wav")
            stt_key = f"stt_result_{uid}"
            if st.button("음성을 텍스트로 변환", key=f"stt_btn_{uid}", width="stretch"):
                audio.seek(0)
                audio_bytes = audio.read()
                if audio_bytes:
                    with st.spinner("음성을 텍스트로 변환하는 중..."):
                        transcribed = _transcribe_audio_with_gemini(audio_bytes, mime_type="audio/wav")
                    if transcribed:
                        st.session_state[stt_key] = transcribed
                        st.success("변환이 완료되었습니다. 아래 내용을 확인한 뒤 '실습 입력창에 적용'을 누르세요.")
                    else:
                        st.error("변환에 실패했습니다. 오디오 형식을 확인하거나 API 키를 설정해 주세요.")
                else:
                    st.warning("오디오 데이터를 읽을 수 없습니다.")
            if stt_key in st.session_state:
                transcribed_text = st.session_state[stt_key]
                st.markdown("**음성 분석 결과**")
                st.text_area("변환된 텍스트", value=transcribed_text, height=100, key=f"stt_display_{uid}", disabled=True)
                col_a, col_b = st.columns(2)
                with col_a:
                    if st.button("실습 입력창에 적용", key=f"stt_apply_{uid}", width="stretch"):
                        content_key = f"content_{uid}"
                        current = st.session_state.get(content_key, "")
                        merged = (current + "\n" + transcribed_text).strip() if current else transcribed_text
                        st.session_state[content_key] = merged
                        st.toast("실습 입력창에 적용되었습니다.")
                        st.rerun()
                with col_b:
                    if st.button("결과 지우기", key=f"stt_clear_{uid}", width="stretch"):
                        del st.session_state[stt_key]
                        st.rerun()

        stt_text = (st.session_state.get(f"stt_result_{uid}") or "").strip()

        col_bsr, col_live = st.columns([1, 1])
        with col_bsr:
            draft_key = f"draft_{uid}"
            if draft_key not in st.session_state:
                st.session_state[draft_key] = None

            if st.button("역량 단위 자동 분류 및 역질문", width="stretch"):
                # 캐시된 분석 결과 우선 사용 (API 중복 호출 방지)
                cached = st.session_state.get(f"img_result_{uid}")
                force_sim = st.session_state.get("analyze_force_sim_mode", False)
                image_hint = cached[1] if cached and img else (
                    analyze_image(img, use_real_api=use_real_ai and not force_sim, content=content or "", file_name=getattr(img, "name", ""))[1]
                    if img else None
                )
                matched_unit = _detect_ncs_unit(content, image_hint=image_hint)
                matched_element = _detect_element(matched_unit, content)
                detected_list = list(cached[0]) if cached else []
                api_k = _get_google_api_key()
                recent_logs = list_logs(uid)[:10]
                r_axes, r_vals = radar_scores_from_logs(recent_logs)
                with st.spinner("실습 내용에 맞춘 역질문·성찰 예시를 생성하는 중..."):
                    questions = get_ai_scaffolding(
                        content or "",
                        detected_list,
                        matched_unit,
                        stt_result=stt_text or None,
                        prior_radar_axes=r_axes,
                        prior_radar_values=r_vals,
                        api_key=api_k,
                    )
                    reflection_ex = get_reflection_example_sentence(
                        content or "",
                        detected_list,
                        matched_unit,
                        stt_result=stt_text or None,
                        api_key=api_k,
                    )
                st.session_state[draft_key] = {
                    "content": content,
                    "unit": matched_unit,
                    "element": matched_element,
                    "questions": questions,
                    "reflection_example": reflection_ex,
                }

            draft = st.session_state.get(draft_key)
            if draft:
                st.markdown(
                    f"<span class='ncs-tag'>매칭됨: {format_ncs_unit(draft['unit'])} > {draft['element']}</span>",
                    unsafe_allow_html=True,
                )
                # 오늘 한 일 NCS 용어로 정리 (학생 확인용)
                draft_ncs = _convert_to_ncs_terms(draft.get("content", "") or "")
                if draft_ncs:
                    ncs_summary = ", ".join(f"{n}" for (_, n, __) in draft_ncs)
                    st.info(f"**오늘 한 일 (NCS 용어로)**: {ncs_summary}")
                st.divider()
                st.markdown("<div class='ai-coaching-panel'>", unsafe_allow_html=True)
                st.markdown("### [실습 내용 맞춤형 AI 코칭]", unsafe_allow_html=True)
                st.caption(
                    "입력한 [배경] 초안·인식 장비·매칭 NCS 단위를 반영해 역질문과 성찰 문장 예시를 생성합니다. "
                    "내용을 고친 뒤 아래에서 다시 생성할 수 있습니다."
                )
                with st.expander("코칭의 교육적 목적 (비계·메타인지)", expanded=False):
                    st.write(
                        "맞춤 역질문은 비계 설정(Scaffolding)에 따라 학생의 메타인지적 성찰을 유도합니다. "
                        "Vygotsky의 발달근접영역(ZPD) 개념에 맞춰, 실습 상황에 붙는 구체적 질문으로 사고를 확장합니다."
                    )
                qs_list: list[str] = draft.get("questions") or []
                if not qs_list and draft.get("question"):
                    qs_list = [str(draft["question"])]
                if not qs_list:
                    qs_list = ["「역량 단위 자동 분류 및 역질문」을 누르면 여기에 맞춤 역질문이 표시됩니다."]
                q_html = "<ol class='ai-coaching-qlist'>" + "".join(
                    f"<li>{(q or '').replace('<', '&lt;').replace('>', '&gt;')}</li>" for q in qs_list[:5]
                ) + "</ol>"
                st.markdown("**맞춤 역질문**", unsafe_allow_html=True)
                st.markdown(q_html, unsafe_allow_html=True)
                ref_ex = (draft.get("reflection_example") or "").strip()
                if not ref_ex:
                    _img_c = st.session_state.get(f"img_result_{uid}")
                    _det = list(_img_c[0]) if _img_c and _img_c[0] else []
                    ref_ex = get_reflection_example_sentence(
                        content or "",
                        _det,
                        draft.get("unit") or "",
                        stt_result=stt_text or None,
                        api_key=None,
                    )
                safe_ref = ref_ex.replace("<", "&lt;").replace(">", "&gt;")
                st.markdown(
                    "<p class='ai-coaching-reflection-label'><strong>전자회로 실습 전용 성찰 문장 예시</strong></p>"
                    f"<div class='ai-coaching-reflection-box'>{safe_ref}</div>",
                    unsafe_allow_html=True,
                )
                c_rf1, c_rf2 = st.columns([1, 1])
                with c_rf1:
                    if st.button(
                        "맞춤 코칭 다시 생성",
                        key=f"refresh_coaching_{uid}",
                        width="stretch",
                        help="현재 [배경] 초안과 사진 인식 결과를 반영해 역질문·성찰 예시를 다시 만듭니다.",
                    ):
                        cached_r = st.session_state.get(f"img_result_{uid}")
                        det_r = list(cached_r[0]) if cached_r and cached_r[0] else []
                        api_k = _get_google_api_key()
                        recent_logs_r = list_logs(uid)[:10]
                        r_ax_r, r_val_r = radar_scores_from_logs(recent_logs_r)
                        with st.spinner("맞춤 코칭을 갱신하는 중..."):
                            nq = get_ai_scaffolding(
                                content or "",
                                det_r,
                                draft["unit"],
                                stt_result=stt_text or None,
                                prior_radar_axes=r_ax_r,
                                prior_radar_values=r_val_r,
                                api_key=api_k,
                            )
                            nr = get_reflection_example_sentence(
                                content or "",
                                det_r,
                                draft["unit"],
                                stt_result=stt_text or None,
                                api_key=api_k,
                            )
                        st.session_state[draft_key] = {
                            **draft,
                            "questions": nq,
                            "reflection_example": nr,
                        }
                        st.rerun()
                with c_rf2:
                    st.caption("배경 문구를 수정한 뒤 누르면 입력에 맞게 갱신됩니다.")
                st.markdown("</div>", unsafe_allow_html=True)

                # NCS 수행준거 기반 체크리스트
                cl_items = CHECKLIST.get((draft["unit"], draft["element"]), [])
                checked_items: list[str] = []
                if cl_items:
                    st.markdown("#### NCS 수행준거 기반 체크리스트")
                    for idx, item in enumerate(cl_items):
                        if st.checkbox(
                            item,
                            key=f"{uid}_cl_{draft['unit']}_{draft['element']}_{idx}",
                        ):
                            checked_items.append(item)

                # 폼 밖에 둠 → 입력 시마다 미리보기가 즉시 갱신됨 (메타인지 성찰 유도)
                ans = st.text_area(
                    "역질문에 대한 답변 ([해결] — 과정·해결 방법)",
                    placeholder="예: 먼저 운전 순서도를 정리한 뒤, 비상정지와 인터록 조건을 래더에 반영했습니다.",
                    height=80,
                    key=f"ans_haegyul_{uid}",
                )
                seungwa = st.text_area(
                    "성찰 결과 ([성과] — 배운 점·느낀 점)",
                    placeholder="예: 인터록 조건을 먼저 정의하면 오동작을 예방할 수 있다는 것을 알게 되었습니다.",
                    height=80,
                    key=f"ans_seungwa_{uid}",
                )
                # BSR 미리보기: 저장 직전 메타인지적 성찰 유도 (입력 시마다 실시간 반영)
                bsr_preview = _build_bsr_string(
                    draft.get("content", "") or "",
                    (ans or "").strip(),
                    (seungwa or "").strip(),
                    checked_items,
                )
                if (ans or "").strip() or (seungwa or "").strip():
                    st.markdown("#### BSR 구조 미리보기 (저장될 형태)")
                    st.caption("작성한 내용이 아래와 같은 구조로 저장됩니다. 'AI 전문 문장으로 다듬기'로 일상 언어를 NCS 수행준거 양식으로 변환할 수 있습니다.")
                    polish_key = f"polish_bsr_{uid}"
                    # AI 전문 문장으로 다듬기 (NCS 수행준거 양식) — 저장 직전
                    if st.button("AI 전문 문장으로 다듬기", key=f"polish_btn_{uid}", width="stretch"):
                        with st.spinner("NCS 수행준거 양식으로 문장을 다듬는 중..."):
                            polished = _polish_bsr_with_gemini(
                                bsr_preview,
                                ncs_unit=draft.get("unit", ""),
                                ncs_element=draft.get("element", ""),
                            )
                        if polished:
                            st.session_state[polish_key] = polished
                            st.success("다듬기가 완료되었습니다. 아래에서 원본과 다듬은 내용을 비교한 뒤 저장하세요.")
                        else:
                            st.warning("API 키를 확인하거나, 잠시 후 다시 시도해 주세요.")
                    # 다듬기 전 vs 다듬은 후 나란히 비교 (메타인지적 성찰 유도)
                    polished_val = st.session_state.get(polish_key, "")
                    comparison_html = render_original_vs_refined(bsr_preview, polished_val)
                    st.markdown(comparison_html, unsafe_allow_html=True)
                    if polished_val:
                        use_polished = st.checkbox(
                            "다듬은 내용(AI Refined)으로 저장",
                            value=True,
                            key=f"use_polished_{uid}",
                            help="체크 시 AI 고도화 문장이 DB에 저장됩니다(세특 초안 품질 향상). 내용 수정 후에는 다시 'AI 전문 문장으로 다듬기'를 눌러 주세요.",
                        )

                submitted = st.button("최종 승인 및 저장", key=f"save_btn_{uid}", width="stretch")

                if submitted:
                    # 다듬은 내용 사용 여부
                    use_polished = st.session_state.get(f"use_polished_{uid}", False)
                    polished_bsr = st.session_state.get(f"polish_bsr_{uid}", "")
                    if use_polished and polished_bsr:
                        bsr_final = polished_bsr
                        base_text = polished_bsr
                    else:
                        haegyul = (ans or "").strip()
                        seungwa_val = (seungwa or "").strip() or haegyul
                        bsr_final = _build_bsr_string(
                            draft.get("content", "") or "",
                            haegyul,
                            seungwa_val,
                            checked_items,
                        )
                        base_text = (draft.get("content", "") or "") + " " + (ans or "") + " " + (seungwa or "")
                    # 실습 구체성: 30자당 1점 (기존 60자→완화)
                    length_score = min(5, max(1, (len(base_text) // 30) + 1))
                    # 전문 용어: NCS+GLOSSARY+구어체 키워드 모두 인정
                    all_kw = set(GLOSSARY.keys())
                    for meta in NCS_DB.values():
                        all_kw.update(meta.get("keywords", []))
                    for phrases, _, _ in COLLOQUIAL_TO_NCS:
                        all_kw.update(phrases)
                    term_hits = sum(1 for w in all_kw if w in base_text)
                    term_score = min(5, max(1, term_hits + 1))
                    # 안전 요소
                    safety_hits = sum(
                        base_text.count(k)
                        for k in ["안전", "접지", "감전", "보호구", "LOTO", "ELB", "차단기"]
                    )
                    safety_score = min(5, max(1, safety_hits + 1))

                    log = {
                        "date": str(datetime.date.today()),
                        "bsr": bsr_final,
                        "ncs": draft["unit"],
                    }
                    ncs_ratio = _compute_ncs_term_ratio(bsr_final)
                    add_log(
                        uid=uid,
                        date=log["date"],
                        ncs_unit=log["ncs"],
                        bsr=log["bsr"],
                        image_note="사진 업로드됨" if img else None,
                        audio_note="음성 녹음됨" if audio else None,
                        ncs_term_ratio=ncs_ratio,
                    )
                    # 진행률 차등 지급: 피드백 점수(구체성·용어·안전)에 따라 2~8% 차등
                    progress_gain = min(8, max(2, (length_score + term_score + safety_score) // 2))
                    current = int((st.session_state.ncs_progress or {}).get(draft["unit"], 0))
                    new_val = min(current + progress_gain, 100)
                    st.session_state.ncs_progress[draft["unit"]] = new_val
                    update_progress(uid, draft["unit"], new_val)
                    st.session_state[draft_key] = None
                    st.success("데이터가 성공적으로 저장되었습니다.")
        with col_live:
            st.markdown("#### 장비·NCS 용어 실시간 미리보기")
            st.caption(
                "좌측에서 입력한 [배경]·[해결]·[성과]를 합쳐 사전 기반 NCS 매핑을 표시합니다. "
                "증거 사진을 분석한 경우 인식 장비·추천 능력단위를 함께 보여 줍니다."
            )
            img_cached = st.session_state.get(f"img_result_{uid}")
            if img_cached:
                detected, suggested_unit = img_cached[0], img_cached[1]
                st.markdown("**인식된 장비·기기**")
                if detected:
                    equip_lines = "<br/>".join(
                        f"• {d.get('객체', '—')} ({d.get('신뢰도', '—')})" for d in detected[:8]
                    )
                    st.markdown(
                        f"<div class='report-card' style='padding:0.75rem;font-size:0.9rem;'>{equip_lines}</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("—")
                st.markdown(f"**추천 NCS 능력단위**  \n{format_ncs_unit(suggested_unit)}")
            else:
                st.caption("증거 사진을 업로드·분석하면 이 영역에 장비·추천 단위가 표시됩니다.")

            bg = st.session_state.get(f"content_{uid}", "") or ""
            hg = st.session_state.get(f"ans_haegyul_{uid}") or ""
            sw = st.session_state.get(f"ans_seungwa_{uid}") or ""
            preview_text = _build_bsr_string(bg, hg.strip(), sw.strip(), [])
            if not preview_text.strip():
                preview_text = bg
            if not (preview_text or "").strip():
                st.info("좌측 [배경]과 역질문에 대한 [해결]·[성과]를 입력하면 이곳에 NCS 용어 전환이 표시됩니다.")
            else:
                hits = _convert_to_ncs_terms(preview_text)
                if hits:
                    st.markdown("**구어체 → NCS 수행준거 용어 (사전 매칭)**")
                    for colloq, ncs_t, desc in hits[:20]:
                        st.markdown(
                            f"- **{colloq}** → `{ncs_t}`  \n  <small style='color:#64748b;'>{desc}</small>",
                            unsafe_allow_html=True,
                        )
                else:
                    st.caption("등록된 구어체 표현이 감지되지 않았습니다. 전문 용어를 사용하면 매핑이 표시됩니다.")
                fb = _rewrite_to_ncs_terms_fallback(preview_text)
                if fb and fb.strip() and fb.strip() != preview_text.strip():
                    st.markdown("**사전 치환 미리보기**")
                    safe_fb = fb.replace("<", "&lt;").replace(">", "&gt;").replace(chr(10), "<br/>")
                    st.markdown(
                        f"<div style='border-left:3px solid #0ea5e9;padding:0.75rem 1rem;background:#f8fafc;"
                        f"border-radius:6px;font-size:0.9rem;line-height:1.6;'>{safe_fb}</div>",
                        unsafe_allow_html=True,
                    )
        st.markdown("</div>", unsafe_allow_html=True)

    with tab2:
        st.markdown("<div class='report-card'>", unsafe_allow_html=True)
        st.subheader("저장된 실습일지")

        logs = list_logs(uid)
        if not logs:
            st.info("저장된 실습일지 없음. 실습 일지 작성 탭에서 작성 후 저장할 것.")
        else:
            st.caption("불필요한 기록은 본 화면에서 삭제 가능.")

            options = []
            for i, row in enumerate(logs):
                date = row.get("date", "")
                ncs = row.get("ncs_unit", "")
                bsr = (row.get("bsr", "") or "").replace("\n", " ")
                snippet = (bsr[:40] + "…") if len(bsr) > 40 else bsr
                options.append((row.get("id"), f"#{row.get('id')} [{date}] {format_ncs_unit(ncs)} - {snippet}"))

            col_a, col_b = st.columns([3, 1])
            with col_a:
                selected = st.selectbox(
                    "삭제할 기록 선택",
                    options=options,
                    format_func=lambda x: x[1],
                )
            with col_b:
                with st.form(key=f"delete_one_{uid}", clear_on_submit=True):
                    ok = st.form_submit_button("선택 삭제")
                if ok and selected:
                    log_id = int(selected[0])
                    delete_log(uid, log_id)
                    st.success("선택한 기록을 삭제했습니다.")
                    st.rerun()

            with st.expander("전체 삭제", expanded=False):
                st.warning("모든 실습일지가 삭제됨. 복구 불가.")
                confirm = st.checkbox("전체 삭제를 확인함", key=f"confirm_clear_{uid}")
                if st.button("전체 삭제 실행", disabled=not confirm, key=f"clear_all_{uid}"):
                    clear_logs(uid)
                    st.success("모든 기록을 삭제했습니다.")
                    st.rerun()

            display_logs = [{**r, "ncs_unit": format_ncs_unit(r.get("ncs_unit", ""))} for r in logs]
            df = st.dataframe(
                display_logs,
                width="stretch",
                hide_index=True,
            )

            # BSR 구조화 상세 보기 (배경/해결/성과 색상 하이라이트)
            st.markdown("---")
            st.caption("성찰 일지 BSR 구조화 상세")
            detail_options = [(r.get("id"), f"#{r.get('id')} [{r.get('date','')}] {format_ncs_unit(r.get('ncs_unit',''))}") for r in logs]
            if detail_options:
                selected_id = st.selectbox(
                    "상세 보기할 기록 선택",
                    options=[o[0] for o in detail_options],
                    format_func=lambda x: next((o[1] for o in detail_options if o[0] == x), str(x)),
                    key=f"bsr_detail_{uid}",
                )
                selected_row = next((r for r in logs if r.get("id") == selected_id), None)
                if selected_row and selected_row.get("bsr"):
                    bsr_raw = str(selected_row["bsr"])
                    bsr_html = render_bsr_highlighted(bsr_raw)
                    st.markdown(
                        f"<div class='report-card' style='padding:1rem; font-size:0.95rem; line-height:1.7;'>{bsr_html}</div>",
                        unsafe_allow_html=True,
                    )
                    # NCS 표준용어로 풀어쓴 버전 (AI 전문가 톤)
                    bsr_cache_key = f"ncs_rewrite_bsr_{uid}"
                    if bsr_cache_key not in st.session_state:
                        st.session_state[bsr_cache_key] = {}
                    bsr_cache = st.session_state[bsr_cache_key]
                    bsr_cached = bsr_cache.get(bsr_raw)
                    if st.button("AI로 NCS 전문가 톤 변환", key=f"ncs_bsr_btn_{uid}_{selected_id}", width="stretch"):
                        with st.spinner("AI 변환 중..."):
                            bsr_ai = _rewrite_to_ncs_terms_with_gemini(bsr_raw)
                        if bsr_ai:
                            bsr_cache[bsr_raw] = bsr_ai
                            bsr_cached = bsr_ai
                    rewritten = bsr_cached if bsr_cached else _rewrite_to_ncs_terms_fallback(bsr_raw)
                    if rewritten and rewritten.strip():
                        safe_rew = rewritten.replace(chr(10), "<br/>").replace("<", "&lt;").replace(">", "&gt;")
                        st.caption("NCS 표준용어 버전" + (" (AI 전문가 톤)" if bsr_cached else " (기본 치환)"))
                        st.markdown(
                            f"<div class='glossary-box' style='border-left:4px solid #1e3a5f; padding:1rem; margin-top:0.5rem; border-radius:6px;'>"
                            f"<span style='color:#334155; line-height:1.7;'>{safe_rew}</span></div>",
                            unsafe_allow_html=True,
                        )

            csv_bytes = (
                "id,date,ncs_unit,bsr\n"
                + "\n".join(
                    f"\"{row.get('id','')}\",\"{row.get('date','')}\",\"{row.get('ncs_unit','')}\",\"{(row.get('bsr','') or '').replace('\"','\"\"')}\""
                    for row in logs
                )
            ).encode("utf-8-sig")
            st.download_button(
                "CSV 다운로드",
                data=csv_bytes,
                file_name=f"{uid}_logs.csv",
                mime="text/csv",
            )
        st.markdown("</div>", unsafe_allow_html=True)

    with tab3:
        st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
        st.subheader("AI 기반 개인별 성장 진단 및 코칭")

        logs = list_logs(uid)
        if not logs:
            st.info("저장된 실습일지가 없습니다. 일지를 작성·저장하면 맞춤형 성장 진단이 표시됩니다.")
        else:
            # ─── 1. AI 맞춤형 성장 총평 ───
            st.markdown("#### 1. AI 맞춤형 성장 총평")
            growth_key = f"ai_growth_{uid}"
            if st.button("성장 총평 새로고침", key=f"growth_refresh_{uid}", width="stretch"):
                with st.spinner("AI가 실습 이력을 분석하고 있습니다..."):
                    report = _get_ai_growth_report(logs)
                if report:
                    st.session_state[growth_key] = report
                    st.success("분석이 완료되었습니다.")
                else:
                    st.warning("API를 사용할 수 없습니다. API 키를 확인해 주세요.")
            report = st.session_state.get(growth_key)
            if report:
                st.info(report)
            else:
                st.caption("위 '성장 총평 새로고침' 버튼을 눌러 AI 맞춤형 성장 분석을 받으세요.")

            # ─── 2. AI 성장 코멘트 (메타인지 코칭 · 최근 3개 일지) ───
            st.markdown("---")
            st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
            st.markdown("#### 2. AI 성장 코멘트")
            st.caption("최근 3개 일지의 성찰 깊이([성과] 분량)와 전문 용어 빈도를 비교해 성장을 격려하고 보완점을 제안합니다.")
            meta_key = f"ai_meta_coach_{uid}"
            if len(logs) >= 1:
                if st.button("최근 3개 일지 기반 코멘트 생성", key=f"meta_coach_btn_{uid}", width="stretch"):
                    with st.spinner("최근 일지를 분석해 메타인지 코멘트를 작성하는 중..."):
                        mc = _get_ai_meta_coach_comment(logs)
                    if mc:
                        st.session_state[meta_key] = mc
                        st.success("코멘트가 준비되었습니다.")
                    else:
                        st.warning("API를 사용할 수 없습니다. API 키를 확인해 주세요.")
                meta_text = st.session_state.get(meta_key)
                if meta_text:
                    st.info(meta_text)
                else:
                    st.caption("버튼을 누르면 Gemini가 최근 3개 일지 지표를 비교한 코멘트를 생성합니다.")
            else:
                st.info("일지가 저장되면 이용할 수 있습니다.")
            st.markdown("</div>", unsafe_allow_html=True)

            # ─── 3. 내 성찰의 변화 가시화 (역량 성장 레이다) ───
            st.markdown("---")
            st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
            st.markdown("#### 3. 내 성찰의 변화 가시화")
            st.caption("최초 3개 일지 vs 최근 3개 일지 — 성찰의 깊이·전문 용어 활용 변화")
            if len(logs) >= 2:
                reversed_logs = list(reversed(logs))
                first3 = reversed_logs[:3]
                recent3 = logs[:3]

                def _avg_scores(log_list: list[dict]) -> list[float]:
                    if not log_list:
                        return [0.0] * 4
                    by_dim: dict[str, list[float]] = {"구체성": [], "전문용어": [], "안전": [], "성찰": []}
                    for row in log_list:
                        s = _log_competency_scores(row.get("bsr") or "")
                        for d in by_dim:
                            by_dim[d].append(s.get(d, 0))
                    return [sum(by_dim[d]) / max(len(by_dim[d]), 1) for d in by_dim]

                first_vals = _avg_scores(first3)
                recent_vals = _avg_scores(recent3)
                dims = ["구체성", "전문용어", "안전", "성찰"]
                fig_radar = go.Figure()
                fig_radar.add_trace(go.Scatterpolar(
                    r=first_vals + [first_vals[0]], theta=dims + [dims[0]], fill="toself",
                    name="최초 3개 일지", line={"color": _CHART_ACCENT}
                ))
                fig_radar.add_trace(go.Scatterpolar(
                    r=recent_vals + [recent_vals[0]], theta=dims + [dims[0]], fill="toself",
                    name="최근 3개 일지", line={"color": _CHART_PRIMARY}
                ))
                fig_radar.update_layout(
                    polar={"radialaxis": {"visible": True, "range": [0, 5]}},
                    showlegend=True, height=360, margin=dict(l=80, r=80),
                    paper_bgcolor="rgba(255,255,255,0)", plot_bgcolor="rgba(255,255,255,0)",
                )
                st.plotly_chart(fig_radar, width="stretch")
                if sum(recent_vals) > sum(first_vals):
                    st.success("최근 일지에서 성찰·전문 용어 점수가 향상되었습니다.")
            else:
                st.info("일지가 2개 이상일 때 역량 성장 비교가 표시됩니다.")
            st.markdown("</div>", unsafe_allow_html=True)

            # ─── 4. 메타인지 자가 진단 가이드 ───
            st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
            st.markdown("#### 4. 성찰 수준 자가 진단")
            level, comment = _evaluate_seungwa_reflection(logs)
            if level == "높음":
                st.success(f"**현재 수준: 높음** — {comment}")
            elif level == "보통":
                st.info(f"**현재 수준: 보통** — {comment}")
            else:
                st.warning(f"**현재 수준: 낮음** — {comment}")
            st.caption("'높음' 단계로 가기 위해 다음 키워드를 성찰에 활용해 보세요:")
            recommend_kw = ["이유", "깨달음", "다음에는", "과정", "개선", "스스로", "이해", "알게"]
            st.markdown(" ".join(f"`{k}`" for k in recommend_kw))
            st.markdown("</div>", unsafe_allow_html=True)

            # ─── 5. 직무 용어 갤러리 ───
            st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
            st.markdown("#### 5. 내가 마스터한 전문 용어")
            used_terms = _extract_used_professional_terms(logs)
            if used_terms:
                tags_html = " ".join(
                    f"<span style='display:inline-block;background:rgba(30,58,95,0.12);color:#1e3a5f;padding:0.3rem 0.6rem;margin:0.2rem;border-radius:999px;font-size:0.9rem;'>{t}</span>"
                    for t in used_terms[:40]
                )
                st.markdown(f"<div style='line-height:2.2;'>{tags_html}</div>", unsafe_allow_html=True)
                st.caption(f"지금까지 일지에서 사용한 NCS·직무 전문 용어 {len(used_terms)}개")
            else:
                st.caption("아직 매칭된 전문 용어가 없습니다. NCS 직무 용어를 활용해 보세요.")
            st.markdown("</div>", unsafe_allow_html=True)

            # 요약 메트릭 (상단 참고용)
            st.markdown("<div class='report-card report-card-tab'>", unsafe_allow_html=True)
            st.caption("역량 점수 요약")
            length_list = []
            term_list = []
            safety_list = []
            for row in logs:
                s = _log_competency_scores(str(row.get("bsr", "")))
                length_list.append(s["구체성"])
                term_list.append(s["전문용어"])
                safety_list.append(s["안전"])
            avg_len = round(sum(length_list) / max(len(length_list), 1), 1)
            avg_term = round(sum(term_list) / max(len(term_list), 1), 1)
            avg_safe = round(sum(safety_list) / max(len(safety_list), 1), 1)
            c1, c2, c3 = st.columns(3)
            c1.metric("실습 구체성", f"{avg_len}/5")
            c2.metric("전문 용어 활용", f"{avg_term}/5")
            c3.metric("안전 요소", f"{avg_safe}/5")
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

    with tab4:
        _show_digital_portfolio(uid)


def _logo_base64() -> str:
    """로고를 base64로 인코딩하여 HTML img src에 사용."""
    _APP_DIR = Path(__file__).resolve().parent
    for name in ["school_logo.png", "school_logo_placeholder.svg"]:
        p = _APP_DIR / "assets" / name
        if p.exists():
            try:
                import base64
                data = p.read_bytes()
                enc = base64.b64encode(data).decode()
                mime = "image/svg+xml" if name.endswith(".svg") else "image/png"
                return f"data:{mime};base64,{enc}"
            except Exception:
                pass
    return ""


def _show_digital_portfolio(uid: str) -> None:
    """디지털 직무 포트폴리오 화면 (A4 인쇄용)."""

    logs = list_logs(uid)
    prog = seed_progress_if_missing(uid, DEFAULT_NCS_PROGRESS)
    avg_prog = round(sum(prog.values()) / max(len(prog), 1), 1) if prog else 0

    # 베스트 실습 큐레이션 (체크박스로 포트폴리오 본문 구성)
    st.markdown("<p class='portfolio-watermark'>NCS 국가직무능력표준 기반 인증</p>", unsafe_allow_html=True)
    st.markdown("<h3>베스트 실습으로 선택</h3>", unsafe_allow_html=True)
    st.caption("포트폴리오 본문에 포함할 실습을 체크하세요. 선택한 항목만 NCS 기반 종합 포트폴리오에 반영됩니다.")
    selected_ids: list[int] = []
    for row in logs:
        lid = row.get("id")
        date = row.get("date", "")
        ncs = row.get("ncs_unit", "")
        snippet = ((row.get("bsr") or "")[:50] + "…") if len(row.get("bsr") or "") > 50 else (row.get("bsr") or "")
        if st.checkbox(f"[{date}] {format_ncs_unit(ncs)} — {snippet}", key=f"port_sel_{uid}_{lid}"):
            selected_ids.append(lid)
    selected_logs = [r for r in logs if r.get("id") in selected_ids]
    summary_logs = selected_logs if selected_ids else []

    logo_b64 = _logo_base64()
    logo_img = f"<img src='{logo_b64}' alt='로고' style='height:70px;' />" if logo_b64 else ""
    comment = get_confirmed_portfolio_comment(uid)
    comment_txt = (comment.get("comment_text") or "").strip() if comment else ""

    # A4 카드 래퍼 — NCS 기반 종합 직무 포트폴리오
    parts: list[str] = []
    parts.append("<div class='portfolio-print-wrapper'><div class='portfolio-a4-card'>")

    # Cover Page: NCS 직무 역량 종합 리포트
    parts.append("<div class='portfolio-cover-page'>")
    parts.append(
        "<div class='portfolio-header' style='display:flex;align-items:center;gap:1.5rem;margin-bottom:1.5rem;'>"
        f"<div class='portfolio-logo'>{logo_img}</div>"
        "<div class='portfolio-header-text'>"
        "<p class='portfolio-watermark' style='margin:0;'>NCS 국가직무능력표준 기반 인증</p>"
        "<h2 class='portfolio-title' style='margin:0.5rem 0;'>NCS 기반 종합 직무 포트폴리오</h2>"
        f"<p class='portfolio-subtitle'>{uid} · 용산철도고등학교 산학일체형 도제학교</p>"
        "</div></div>"
    )
    parts.append("<div class='portfolio-section'><h3>NCS 직무 역량 종합 리포트</h3></div>")

    # 1) 역량 레이다 2) 누적 실습 횟수·NCS 단위별 달성률 3) [지도교사 종합의견]
    if logs:
        axes, values = radar_scores_from_logs(logs)
        r_vals = values + [values[0]]
        theta_vals = axes + [axes[0]]
        fig = go.Figure()
        fig.add_trace(
            go.Scatterpolar(
                r=r_vals, theta=theta_vals, fill="toself",
                line=dict(color=_CHART_PRIMARY, width=2),
                fillcolor="rgba(30, 58, 95, 0.15)",
            )
        )
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
            showlegend=False, height=260,
            paper_bgcolor="rgba(255,255,255,0)", plot_bgcolor="rgba(255,255,255,0)",
        )
        radar_html = fig.to_html(full_html=False, include_plotlyjs="cdn")
        prog_rows = "".join(
            f"<tr><td>{format_ncs_unit(u)}</td><td>{v}%</td></tr>"
            for u, v in sorted(prog.items(), key=lambda x: -x[1])
        )
        total_practice = len(logs)
        parts.append(
            "<div class='portfolio-cover-stats'>"
            "<div class='portfolio-radar'>" + radar_html + "</div>"
            "<div class='portfolio-stats-table'>"
            f"<p class='portfolio-stat-label'>누적 실습 횟수</p><p class='portfolio-stat-value'>{total_practice}회</p>"
            f"<p class='portfolio-stat-label'>평균 NCS 진도율</p><p class='portfolio-stat-value'>{avg_prog}%</p>"
            f"<p class='portfolio-stat-label'>NCS 코드별 이수 현황</p>"
        f"<table class='portfolio-ncs-table'><thead><tr><th>능력단위 (코드)</th><th>달성률</th></tr></thead><tbody>{prog_rows}</tbody></table>"
            "</div></div>"
        )
    else:
        parts.append("<p class='portfolio-empty'>저장된 일지가 없어 역량 요약을 표시할 수 없습니다.</p>")

    parts.append("<div class='portfolio-section'><h3>[지도교사 종합의견]</h3></div>")
    if comment_txt:
        txt_esc = comment_txt.replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br/>")
        parts.append(f"<div class='portfolio-comment'>{txt_esc}</div>")
    else:
        parts.append(
            "<p class='portfolio-empty'>지도교사가 교사 화면에서 [최종 승인]으로 확정하면 여기에 표시됩니다.</p>"
        )
    parts.append("</div>")  # portfolio-cover-page

    # 베스트 실습 선정 사례 (정제된 BSR + 증거 사진 배지만)
    parts.append("<div class='portfolio-best-practices'>")
    parts.append("<div class='portfolio-section'><h3>베스트 실습 선정 사례</h3></div>")
    if selected_logs:
        for idx, row in enumerate(selected_logs):
            bsr_raw = str(row.get("bsr", ""))
            bsr_html = render_bsr_highlighted(bsr_raw)  # 전문 용어(OrCAD, PCB 등) 강조
            ncs_display = format_ncs_unit(row.get("ncs_unit", ""))
            evidence_badge = ""
            if row.get("image_note"):
                evidence_badge = "<span class='portfolio-evidence-badge'>증거 사진 첨부</span>"
            parts.append(
                f"<div class='portfolio-log-entry' data-print-break='avoid'>"
                f"<div class='portfolio-log-item'>"
                f"<strong>[{row.get('date','')}] {ncs_display}</strong> {evidence_badge}"
                f"</div>"
                f"<div class='portfolio-bsr'>{bsr_html}</div>"
                f"</div>"
            )
    else:
        parts.append("<p class='portfolio-empty'>위에서 베스트 실습으로 포함할 항목을 선택하세요.</p>")
    parts.append("</div>")

    parts.append(
        "<div class='portfolio-footer'><p>용산철도고등학교 · NCS 국가직무능력표준 기반 인증</p></div>"
        "</div></div>"
    )

    html_doc = "".join(parts)
    st.download_button(
        label="포트폴리오 HTML 다운로드 (브라우저 인쇄·PDF 저장)",
        data=(
            "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'/>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'/>"
            "<title>포트폴리오</title></head><body style='font-family:Noto Sans KR,sans-serif;'>"
            + html_doc
            + "</body></html>"
        ).encode("utf-8"),
        file_name=f"{uid}_portfolio.html",
        mime="text/html",
        key=f"portfolio_html_dl_{uid}",
    )
    st.caption("HTML을 저장한 뒤 브라우저에서 열고 인쇄 대화상자에서 PDF로 저장할 수 있습니다.")

    st.markdown(html_doc, unsafe_allow_html=True)

