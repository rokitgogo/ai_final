"""BSR 구조 시각화 공용 유틸. [배경][해결][성과] 구간별 색상 하이라이트 + NCS 전문 용어 강조."""
import json
import os
import re

# 레이더 역량 축 (학생·교사 뷰 공통)
RADAR_AXES: list[str] = ["설계", "제작", "계측", "제어", "안전"]

_RADAR_KEYWORDS: dict[str, list[str]] = {
    "설계": ["설계", "회로도", "스키매틱", "시뮬레이션"],
    "제작": ["조립", "납땜", "배선", "배관", "장착"],
    "계측": ["측정", "멀티미터", "오실로스코프", "메거", "계측"],
    "제어": ["PLC", "인버터", "시퀀스", "프로그램", "모터제어"],
    "안전": ["안전", "접지", "감전", "보호구", "LOTO", "인터록"],
}

# 실습 기록 수가 적을 때 한 축이 과도하게 100점이 되지 않도록 max 정규화 분모에 바닥을 둔다.
RADAR_MIN_LOGS_FOR_FULL_SCALE = 5
RADAR_MIN_MAX_DENOMINATOR = 5


def resolve_google_api_key(explicit: str | None = None) -> str | None:
    """Streamlit secrets 우선, 없으면 환경 변수."""
    if explicit is not None and str(explicit).strip():
        return str(explicit).strip()
    try:
        import streamlit as st

        if hasattr(st, "secrets") and st.secrets.get("GOOGLE_API_KEY"):
            return str(st.secrets["GOOGLE_API_KEY"]).strip()
    except Exception:
        pass
    return os.environ.get("GOOGLE_API_KEY")


def radar_scores_from_logs(logs: list[dict]) -> tuple[list[str], list[float]]:
    """일지 목록에서 역량 레이다용 축과 점수(0~100) 추출. 키워드 빈도 정규화."""
    axes = list(RADAR_AXES)
    text_all = " ".join(str(r.get("bsr", "")) for r in logs)
    scores = [sum(text_all.count(k) for k in _RADAR_KEYWORDS[a]) for a in axes]
    if sum(scores) == 0:
        scores = [1, 1, 1, 1, 1]
    raw_max = max(scores)
    n_logs = len(logs)
    # 기록이 적을 때는 분모에 최소 기준(가상 '5회' 분량)을 두어 한 축이 쉽게 100점이 되지 않게 한다.
    if n_logs < RADAR_MIN_LOGS_FOR_FULL_SCALE:
        m = max(raw_max, RADAR_MIN_MAX_DENOMINATOR)
    else:
        m = max(raw_max, 1)
    values = [round(s / m * 100.0, 2) for s in scores]
    return axes, values


def extract_background_section(content: str) -> str:
    """[배경] 구간만 추출. 없으면 전체를 사용."""
    m = re.search(r"\[배경\]\s*(.*?)(?=\[해결\]|\[성과\]|\Z)", content or "", re.DOTALL)
    return (m.group(1).strip() if m else (content or "").strip())


def _parse_evidence_score_0_100(text: str | None) -> float | None:
    """모델 출력에서 0~100 점수 파싱."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)
    try:
        start = t.index("{")
        end = t.rindex("}") + 1
        obj = json.loads(t[start:end])
        s = obj.get("score")
        if s is not None:
            v = float(s)
            return min(100.0, max(0.0, v))
    except (ValueError, json.JSONDecodeError, KeyError):
        pass
    m = re.search(r"(?:score|점수)\s*[:=]\s*(\d{1,3})", t, re.I)
    if m:
        return min(100.0, max(0.0, float(m.group(1))))
    m2 = re.search(r"\b(\d{1,3})\b", t)
    if m2:
        v = int(m2.group(1))
        if 0 <= v <= 100:
            return float(v)
    return None


def check_evidence_validity(
    image_file,
    content: str,
    *,
    api_key: str | None = None,
) -> float:
    """
    실습 사진과 [배경] 글의 증거 적합성을 0~100으로 추정.
    API 실패·이미지 오류 시 중립값(75)을 반환해 UI가 과도하게 경고하지 않게 한다.
    """
    key = resolve_google_api_key(api_key)
    bg = extract_background_section(content)
    if not key or not bg.strip():
        return 75.0
    try:
        import io

        from PIL import Image

        image_file.seek(0)
        img_bytes = image_file.read()
        pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        return 75.0

    prompt = f"""당신은 공업고 전기·전자과 실습 평가를 돕는 조교이다.
학생이 제출한 **사진 한 장**과 **[배경] 텍스트**가 서로 **적절한 증거 관계**인지 평가하라.

[배경]에 서술된 활동·장비·상황이 사진에 보이는 내용과 논리적으로 맞는가?
(예: 본문은 PLC 실습인데 사진만 납땜이면 낮은 점수)

[학생 배경 글]
{bg[:6000]}

출력 규칙: **JSON 한 줄만** 출력한다.
형식: {{"score": 정수(0~100), "reason": "한 줄 한국어 이유"}}
score 기준: 80~100 매우 일치, 50~79 부분 일치, 0~49 사진이 본문 증거로 부적절"""

    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            [prompt, pil_img],
            generation_config={"temperature": 0.15, "max_output_tokens": 256},
        )
        raw = (response.text or "").strip() if response else ""
        parsed = _parse_evidence_score_0_100(raw)
        if parsed is not None:
            return parsed
    except Exception:
        pass
    return 75.0


def generate_seuteuk_from_bsr_logs(
    logs: list[dict],
    student_label: str,
    *,
    api_key: str | None = None,
) -> str | None:
    """
    BSR 로그(최대 10건)를 바탕으로 학교생활기록부용 세특(세부능력 및 특기사항) 서술 초안 생성.
    실패 시 None.
    """
    if not logs:
        return None
    rows = logs[:10]
    chunks: list[str] = []
    for i, r in enumerate(rows, 1):
        date = str(r.get("date", "") or "")
        unit = str(r.get("ncs_unit", "") or "")
        bsr = (r.get("bsr") or "").strip()
        if bsr:
            chunks.append(f"--- 실습 {i} ({date}, 능력단위: {unit}) ---\n{bsr[:4500]}")
    corpus = "\n\n".join(chunks)
    if not corpus.strip():
        return None

    prompt = f"""당신은 고등학교 전기·전자과 담임 및 현장교사를 돕는 기술사이다.
아래 실습 일지(BSR) 기록을 바탕으로 **학교생활기록부의 「세부능력 및 특기사항」**에 들어갈 서술형 문단을 작성하라.

학생: {student_label}

[실습 일지 원문 (최대 10건)]
{corpus}

작성 지침:
- 단순히 '무엇을 했다'는 활동 나열이 아니라, **오류·이상 징후·시운전 문제를 해결하는 과정**에서 드러난 **기술적 성장**과 **메타인지적 태도**(원인 가설, 점검 순서, 측정·대조, 개선)를 중심으로 서술한다.
- 전기·전자 실습에 맞는 용어(접지, 인터록, 파형, 쇼트 등)를 자연스럽게 쓴다.
- 2~5문장, 평서체·기재요령에 맞는 격식, 과장·미사여구 금지.
- 제목·번호·따옴표·글머리표 없이 본문만 출력한다."""

    return _gemini_text(prompt, api_key, temperature=0.42, max_tokens=900)


def extract_weak_radar_dimensions(values: list[float]) -> list[dict]:
    """
    5축 점수와 동일한 순서(RADAR_AXES)의 값.
    약점: 해당 축 < 30 이거나, 나머지 4축 평균의 80% 이하(20% 이상 낮음).
    """
    out: list[dict] = []
    n = len(RADAR_AXES)
    if len(values) != n:
        return out
    for j, ax in enumerate(RADAR_AXES):
        v = float(values[j])
        others = [float(values[k]) for k in range(n) if k != j]
        mean_o = sum(others) / len(others)
        if v < 30:
            out.append(
                {"axis": ax, "reason": "30점 미만", "value": v, "others_avg": mean_o}
            )
        elif mean_o > 0 and v <= mean_o * 0.8:
            out.append(
                {
                    "axis": ax,
                    "reason": "타 영역 평균 대비 20% 이상 낮음",
                    "value": v,
                    "others_avg": mean_o,
                }
            )
    return out


def _get_ncs_terms() -> set[str]:
    """constants에서 NCS 전문 용어 수집 (키워드·용어·NCS 표준명)."""
    try:
        from constants import GLOSSARY, NCS_DB, COLLOQUIAL_TO_NCS
    except ImportError:
        return set()
    terms: set[str] = set(GLOSSARY.keys())
    for meta in NCS_DB.values():
        terms.update(meta.get("keywords", []))
    for phrases, ncs_term, _ in COLLOQUIAL_TO_NCS:
        terms.add(ncs_term)
        terms.update(phrases)
    return {t for t in terms if t and len(t) >= 2}


def _highlight_ncs_terms(text: str, terms: set[str]) -> str:
    """텍스트 내 NCS 전문 용어를 <strong>으로 강조. 플레이스홀더로 중첩 방지."""
    if not text or not terms:
        return text.replace("<", "&lt;").replace(">", "&gt;")
    escaped = text.replace("<", "&lt;").replace(">", "&gt;")
    markers: list[tuple[str, str]] = []
    for i, term in enumerate(sorted(terms, key=len, reverse=True)):
        if len(term) < 2 or term not in escaped:
            continue
        ph = f"\x00NCS{i}\x00"
        markers.append((ph, f"<strong style='color:#334155;font-weight:600;border-bottom:1px dotted #94a3b8;'>{term}</strong>"))
        escaped = escaped.replace(term, ph)
    for ph, tag in markers:
        escaped = escaped.replace(ph, tag)
    return escaped


def render_original_vs_refined(original: str, refined: str) -> str:
    """
    다듬기 전(Original)과 다듬은 후(AI Refined)를 나란히 보여주는 HTML.
    메타인지적 성찰 유도: 학생이 일상 언어→전문 용어 치환 과정을 학습.
    """
    orig_html = render_bsr_highlighted(original) if original else "<p style='color:#94a3b8;font-style:italic;'>(내용 없음)</p>"
    ref_html = render_bsr_highlighted(refined) if refined else "<p style='color:#94a3b8;font-style:italic;'>(다듬기 전 내용을 입력한 뒤 'AI 전문 문장으로 다듬기' 버튼을 누르세요)</p>"
    return (
        "<div style='display:grid;grid-template-columns:1fr 1fr;gap:1.5rem;margin:1rem 0;'>"
        "<div style='border:1px solid #e2e8f0;border-radius:8px;padding:1rem;background:#f8fafc;'>"
        "<p style='margin:0 0 0.75rem;font-weight:600;color:#64748b;font-size:0.9em;'>다듬기 전 (Original)</p>"
        f"<div style='font-size:0.9em;'>{orig_html}</div></div>"
        "<div style='border:1px solid #1e3a5f;border-radius:8px;padding:1rem;background:#f0f9ff;'>"
        "<p style='margin:0 0 0.75rem;font-weight:600;color:#1e3a5f;font-size:0.9em;'>다듬은 후 (AI Refined)</p>"
        f"<div style='font-size:0.9em;'>{ref_html}</div></div></div>"
    )


def render_bsr_highlighted(bsr_text: str, highlight_terms: bool = True) -> str:
    """
    BSR 텍스트를 [배경][해결][성과] 구간별 색상 배지/강조로 HTML 변환.
    NCS 국가직무능력표준 기반 실무 중심 성찰 구조화 가시화용.
    highlight_terms=True일 때 NCS 전문 용어를 굵게·밑줄로 강조.
    """
    if not bsr_text:
        return ""
    escaped = lambda s: (s or "").replace("<", "&lt;").replace(">", "&gt;")
    ncs_terms = _get_ncs_terms() if highlight_terms else set()

    # 학술 보고서 스타일: 인라인만 사용, 출력 시 깨짐 방지 (단일 따옴표·이스케이프 고려)
    styles = {
        "[배경]": (
            "display:inline-block;background:#f8fafc;padding:4px 10px;border-radius:4px;"
            "border-left:3px solid #64748b;font-weight:600;font-size:0.9em;margin-right:6px;color:#475569"
        ),
        "[해결]": (
            "display:inline-block;background:#fffbeb;padding:4px 10px;border-radius:4px;"
            "border-left:3px solid #a16207;font-weight:600;font-size:0.9em;margin-right:6px;color:#78350f"
        ),
        "[성과]": (
            "display:inline-block;background:#f0fdf4;padding:4px 10px;border-radius:4px;"
            "border-left:3px solid #047857;font-weight:600;font-size:0.9em;margin-right:6px;color:#14532d"
        ),
        "[체크리스트:": (
            "display:inline-block;background:#f1f5f9;padding:4px 10px;border-radius:4px;"
            "border-left:3px solid #475569;font-weight:600;font-size:0.9em;margin-right:6px;color:#334155"
        ),
    }
    content_style = "color:#334155;line-height:1.8;font-size:0.95em;word-wrap:break-word"
    empty_placeholder = "<span style=\"color:#94a3b8;font-style:italic;font-size:0.9em;margin-left:4px\">(내용 없음)</span>"
    block_style = "display:block;margin-bottom:0.6rem;padding:0.4rem 0;border-bottom:1px solid #f1f5f9"
    parts = re.split(r"(\[배경\]|\[해결\]|\[성과\]|\[체크리스트:[^\]]*\])", bsr_text)
    result: list[str] = []
    i = 0
    while i < len(parts):
        p = parts[i]
        if p.startswith("[배경]"):
            content = (parts[i + 1] if i + 1 < len(parts) else "").strip()
            style = styles.get("[배경]", "")
            cnt = _highlight_ncs_terms(content, ncs_terms) if ncs_terms else escaped(content)
            if not cnt or not cnt.strip():
                cnt = empty_placeholder
            else:
                cnt = f"<span style='{content_style}'>{cnt}</span>"
            result.append(f"<div style='{block_style} border-bottom:1px dashed #e2e8f0;'>"
                         f"<span style='{style}'>[배경]</span>{cnt}</div>")
            i += 2
        elif p.startswith("[해결]"):
            content = (parts[i + 1] if i + 1 < len(parts) else "").strip()
            style = styles.get("[해결]", "")
            cnt = _highlight_ncs_terms(content, ncs_terms) if ncs_terms else escaped(content)
            if not cnt or not cnt.strip():
                cnt = empty_placeholder
            else:
                cnt = f"<span style='{content_style}'>{cnt}</span>"
            result.append(f"<div style='{block_style} border-bottom:1px dashed #e2e8f0;'>"
                         f"<span style='{style}'>[해결]</span>{cnt}</div>")
            i += 2
        elif p.startswith("[성과]"):
            content = (parts[i + 1] if i + 1 < len(parts) else "").strip()
            style = styles.get("[성과]", "")
            cnt = _highlight_ncs_terms(content, ncs_terms) if ncs_terms else escaped(content)
            if not cnt or not cnt.strip():
                cnt = empty_placeholder
            else:
                cnt = f"<span style='{content_style}'>{cnt}</span>"
            result.append(f"<div style='{block_style} border-bottom:1px dashed #e2e8f0;'>"
                         f"<span style='{style}'>[성과]</span>{cnt}</div>")
            i += 2
        elif p.startswith("[체크리스트:"):
            style = styles.get("[체크리스트:", "")
            result.append(f"<div style='{block_style}'><span style='{style}'>{escaped(p)}</span></div>")
            i += 1
        else:
            if p and p.strip():
                result.append(f"<span>{escaped(p)}</span>")
            i += 1
    return "<div style='line-height:1.9;'>" + "".join(result).replace("\n", "<br/>") + "</div>"


def _detected_tools_to_str(detected_tools: list[dict] | list[str] | None) -> str:
    """사진 분석 결과(장비 목록)를 프롬프트용 문자열로."""
    if not detected_tools:
        return "(인식된 장비 없음)"
    lines: list[str] = []
    for d in detected_tools[:12]:
        if isinstance(d, dict):
            lines.append(f"- {d.get('객체', '—')} (신뢰도 {d.get('신뢰도', '—')})")
        else:
            lines.append(f"- {d}")
    return "\n".join(lines)


def _parse_numbered_lines(text: str, max_items: int = 3) -> list[str]:
    """모델 출력에서 질문 줄만 추출 (번호·불릿 제거)."""
    out: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[\d]+[\.\)]\s*", "", line)
        line = re.sub(r"^[-•*]\s*", "", line)
        if len(line) >= 8:
            out.append(line)
        if len(out) >= max_items:
            break
    return out


def _gemini_text(prompt: str, api_key: str | None, *, temperature: float = 0.35, max_tokens: int = 768) -> str | None:
    key = resolve_google_api_key(api_key)
    if not key or not (prompt or "").strip():
        return None
    try:
        import google.generativeai as genai

        genai.configure(api_key=key)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        if response and response.text:
            return response.text.strip()
    except Exception:
        pass
    return None


def get_ai_scaffolding(
    content: str,
    detected_tools: list[dict] | list[str] | None,
    ncs_unit: str,
    *,
    stt_result: str | None = None,
    prior_radar_axes: list[str] | None = None,
    prior_radar_values: list[float] | None = None,
    api_key: str | None = None,
) -> list[str]:
    """
    학생 초안·인식 장비·(선택) 음성 STT·NCS 단위·(선택) 누적 레이더를 통합 문맥으로 역질문 3개 생성.
    RECOMMENDED_QA 고정 리스트 대신 Gemini 사용, 실패 시 휴리스틱 폴백.
    """
    key = resolve_google_api_key(api_key)
    tools_str = _detected_tools_to_str(detected_tools)
    unit = (ncs_unit or "").strip() or "(미선택)"
    body = (content or "").strip() or "(학생 입력 없음)"
    voice = (stt_result or "").strip()
    voice_block = (
        f"[음성으로 설명한 현상·절차]\n{voice}"
        if voice
        else "[음성 데이터 없음 — 아래 초안·장비만으로 질문을 구성한다]"
    )

    if (
        prior_radar_axes
        and prior_radar_values
        and len(prior_radar_axes) == len(prior_radar_values)
        and len(prior_radar_values) == len(RADAR_AXES)
    ):
        pairs = ", ".join(f"{a}: {v}점" for a, v in zip(prior_radar_axes, prior_radar_values))
        weak_info = extract_weak_radar_dimensions(list(prior_radar_values))
        weak_str = (
            ", ".join(
                f"{w['axis']}({w['reason']}, {w['value']:.0f}점)"
                for w in weak_info
            )
            if weak_info
            else "누적 기준으로 두드러진 상대 약점 없음 또는 기록 부족"
        )
        radar_block = f"""
[누적 실습 기록 기준 최근 레이더 점수(0~100) — 개인화 참고]
- 축별 점수: {pairs}
- 상대적 약점 후보: {weak_str}
"""
    else:
        radar_block = "[누적 레이더 정보 없음 — 아래 '이전 약점 연계' 질문은 생략 가능]"

    prompt = f"""너는 공업고 전자과 교사다. 아래 **통합 문맥**(초안·사진 인식 장비·음성·누적 역량)을 하나의 실습 상황으로 해석하고, 기술적으로 구체적인 역질문을 정확히 3개만 작성해라.

[학생이 작성한 초안]
{body}

[사진에서 인식된 장비]
{tools_str}

{voice_block}

{radar_block}

[선택·매칭된 NCS 능력단위]
{unit}

핵심 지시:
- 학생이 업로드한 사진의 장비와 음성으로 설명한 현상·측정값·증상을 **서로 연결**해 질문을 만든다. (음성이 없으면 초안·장비만으로 연결한다.)
- 단순히 "무엇을 했는지"를 묻지 말고, **'왜 그런 파형·전압·동작이 나왔는지'**, **트러블슈팅 과정에서 어떤 기술적 판단을 했는지'**, **가설과 검증 순서는 어떻게 짰는지** 등 메타인지·원인 분석을 자극하는 질문을 포함한다.
- **학생의 이전 기록에서 점수가 낮았던 역량 축(예: 안전)이 있다면**, 오늘 실습 내용과 **연결하여 그 부분을 보완할 수 있는 질문을 1개 포함**한다. (예: 지난번엔 안전 점수가 낮았는데, 오늘 회로 시험 전 LOTO 체크는 어떻게 했나요?) — 누적 레이더 정보가 없거나 약점이 없으면 이 항목은 다른 기술 질문으로 채운다.
- 전자과 실습에 맞는 전문 용어(접지, 쇼트, 극성, 파형, 리플, 인터록, 래더, 입출력 등)를 상황에 맞게 사용한다.
- 오실로스코프·파형이 언급되면 전압·주기·노이즈·트리거·왜곡 등과 연결된 질문을 포함할 수 있다.
- 회로 조립·브레드보드·PCB·납땜이 있으면 배선·접지·쇼트·부품 방향·납땜 품질 관련 질문을 포함할 수 있다.
- PLC·제어 관련이면 시퀀스·인터록·입출력 대조·시운전 절차 관련 질문을 포함할 수 있다.
- 음성과 초안이 모두 있을 때는 **모순·보완 관계**를 짚어 한 가지 질문에 녹여도 좋다.
- 각 질문은 한 문장으로 끝낸다.
- 출력은 질문 3줄만. 번호나 기호 없이 한 줄에 질문 하나씩. 다른 설명·인사 금지."""

    raw = _gemini_text(prompt, key, temperature=0.35, max_tokens=512)
    qs = _parse_numbered_lines(raw or "", 3) if raw else []
    weak_hint: list[str] | None = None
    if prior_radar_values and len(prior_radar_values) == len(RADAR_AXES):
        weak_hint = [w["axis"] for w in extract_weak_radar_dimensions(list(prior_radar_values))]
        if not weak_hint:
            weak_hint = None
    if len(qs) >= 3:
        return qs[:3]
    return _fallback_scaffolding_questions(
        body, unit, detected_tools or [], qs, weak_axes_hint=weak_hint
    )


def _fallback_scaffolding_questions(
    content: str,
    ncs_unit: str,
    detected_tools: list,
    partial: list[str] | None = None,
    weak_axes_hint: list[str] | None = None,
) -> list[str]:
    """API 실패 또는 파싱 부족 시 보강."""
    c = content or ""
    lc = c.lower()
    u = (ncs_unit or "").lower()
    pool: list[str] = list(partial or [])

    def add(q: str) -> None:
        if q not in pool:
            pool.append(q)

    if weak_axes_hint:
        for ax in weak_axes_hint[:2]:
            if ax == "안전":
                add(
                    "누적 기록에서 안전 역량이 상대적으로 낮았다. 오늘 실습 전에 전원 차단·LOTO·보호구 확인을 어떤 순서로 수행했는가?"
                )
            elif ax == "제어":
                add(
                    "이전 기록에서 제어 역량이 상대적으로 낮았다. 오늘 시퀀스·인터록·입출력을 어떤 순서로 대조·검증했는가?"
                )
            elif ax == "계측":
                add(
                    "누적 기록에서 계측 역량이 상대적으로 낮았다. 오늘 측정값을 이론·시뮬과 어떻게 대조했고 불일치 시 원인을 어디부터 좁혔는가?"
                )
            elif ax == "설계":
                add(
                    "이전 기록에서 설계 역량이 상대적으로 낮았다. 오늘 회로도·사양과 실제 배선·부품 선정을 어떻게 일치시켰는가?"
                )
            elif ax == "제작":
                add(
                    "누적 기록에서 제작 역량이 상대적으로 낮았다. 오늘 납땜·배선 품질을 어떤 기준으로 점검했는가?"
                )

    if any(k in c for k in ["오실", "oscillo", "파형", "wave"]) or any(
        "오실" in str(d) for d in (detected_tools or [])
    ):
        add(
            "오실로스코프로 관측한 파형의 진폭·주파수·DC 바이어스는 이론값·시뮬값과 어떻게 대조했는가?"
        )
        add("측정 시 노이즈·리플·링잉이 보였다면 원인을 회로의 어느 부분과 연결해 분석했는가?")
    if any(k in c for k in ["브레드", "배선", "회로", "쇼트", "접지", "극성", "납땜", "PCB"]):
        add(
            "회로도와 실제 배선을 대조할 때 오배선·접지·부품 극성 오류를 어떤 순서로 점검했는가?"
        )
        add("쇼트 의심 구간을 좁히기 위해 전원 차단·저항 측정·시각 검사 중 어떤 절차를 우선했는가?")
    if "plc" in lc or "래더" in c or "인터록" in c or "plc" in u:
        add(
            "작성한 래더 논리에서 안전 인터록 조건은 무엇이며, 시운전 시 그 조건이 충족됐는지 어떻게 확인했는가?"
        )
        add("입력·출력 램프 또는 모니터링 값과 현장 동작이 일치하는지 어떻게 대조 검증했는가?")
    if len(pool) < 3:
        add(
            f"[{ncs_unit or '해당 단위'}] 실습 목표 대비 오늘 수행한 핵심 절차와 품질·안전 기준은 무엇이었는가?"
        )
    if len(pool) < 3:
        add("동일 실습을 다시 한다면 측정·점검 순서를 어떻게 바꾸고 싶은가, 그 이유는 무엇인가?")
    if len(pool) < 3:
        add("실습 중 가장 위험했거나 개선이 필요했던 요인 한 가지와, 이를 줄이기 위한 구체적 조치는 무엇인가?")
    out = pool[:3]
    while len(out) < 3:
        out.append("오늘 실습에서 측정·검증한 결과를 근거로, 다음 단계에서 보완할 점은 무엇인가?")
        out = out[:3]
    return out[:3]


def get_reflection_example_sentence(
    content: str,
    detected_tools: list[dict] | list[str] | None,
    ncs_unit: str,
    *,
    stt_result: str | None = None,
    api_key: str | None = None,
) -> str:
    """
    전자회로 실습 맥락에 맞는 NCS 수행준거 톤의 성찰 문장 1개(예시) 생성.
    사진 인식 장비와 음성 STT가 있으면 통합 문맥으로 반영한다.
    """
    key = resolve_google_api_key(api_key)
    tools_str = _detected_tools_to_str(detected_tools)
    unit = (ncs_unit or "").strip() or "(미선택)"
    body = (content or "").strip() or "(학생 입력 없음)"
    voice = (stt_result or "").strip()
    voice_note = (
        f"\n[음성으로 설명한 내용]\n{voice}"
        if voice
        else "\n[음성 없음 — 초안·장비 중심으로 문장을 작성한다]"
    )

    prompt = f"""너는 공업고 전자과 교사다. 아래 **통합 문맥**(초안·인식 장비·음성)을 반영해
전자회로 실습에 적합한 **성찰 문장 예시**를 딱 1문장만 작성해라.

형식: NCS 수행준거 스타일로 '~함', '~확인함', '~검토함' 등으로 끝낸다.
내용: 측정·배선·점검 등을 구체적으로 반영하고, 음성에서 드러난 현상·판단이 있으면 한 문장에 녹인다. 전문 용어를 자연스럽게 쓴다.
인용부호 없이 문장만 출력한다.

[학생 초안]
{body}

[인식 장비]
{tools_str}
{voice_note}

[NCS 능력단위]
{unit}"""

    raw = _gemini_text(prompt, key, temperature=0.4, max_tokens=256)
    one = (raw or "").strip().splitlines()
    line = one[0].strip() if one else ""
    line = line.strip().strip('"\'「」')
    if len(line) >= 20:
        return line
    return _fallback_reflection_example(body, unit, detected_tools or [])


def _fallback_reflection_example(content: str, ncs_unit: str, detected_tools: list) -> str:
    if "오실" in content or "파형" in content:
        return (
            "회로도와 실제 브레드보드 배선을 대조하며 오배선 여부를 꼼꼼히 확인하고, 오실로스코프로 파형의 왜곡을 측정하여 회로의 안정성을 검토함."
        )
    if "PLC" in content or "래더" in content:
        return (
            "래더 다이어그램의 인터록 조건을 운전 순서도와 대조하여 검증하고, 시운전 시 입·출력 상태를 단계별로 확인하여 오동작 원인을 점검함."
        )
    return (
        f"{ncs_unit or '전자 실습'} 맥락에서 부품 극성·배선·접지 상태를 순차적으로 점검하고, "
        "측정 결과를 근거로 회로 동작의 적합성을 성찰함."
    )


def generate_teacher_learning_guidance(
    case_records: list[dict],
    *,
    api_key: str | None = None,
) -> str | None:
    """
    레이더 약점 자동 추출 결과를 바탕으로 교사용 지도·비계 문장을 생성.
    case_records: student_label, uid, axis, reason, value, others_avg, scores(선택) 등.
    """
    if not case_records:
        return None
    payload = json.dumps(case_records, ensure_ascii=False, indent=2)
    prompt = f"""당신은 공업고등학교 전기·전자과 실습 지도 교사를 돕는 멘토입니다.
아래는 학생별 BSR 키워드 기반 레이더(설계·제작·계측·제어·안전, 0~100)에서 자동 추출된 '주의 필요' 구간입니다.

데이터:
{payload}

각 사례에 대해 **교사가 다음 실습이나 성찰 활동에서 적용할 수 있는 지도 방안**을 한 문장씩 제안하세요.
- 약점 영역과 상대적으로 강한 영역(others_avg)을 대비하여 구체적으로 서술합니다.
- 예시 형식: "S05 학생은 [제어] 영역 실습은 활발하나 [안전] 영역 점수가 낮습니다. 다음 실습 성찰 시 LOTO(에너지 차단) 절차나 개인보호구(PPE) 확인 여부를 묻는 비계를 설정해 보세요."
- 실무 키워드(LOTO, PPE, 비계, 인터록, 접지, 쇼트, 파형 등)를 상황에 맞게 포함할 수 있습니다.
- 한국어로만 출력합니다. 서론·요약 없이 각 사례별로 한 문단 또는 번호 목록으로 작성합니다."""

    return _gemini_text(prompt, api_key, temperature=0.4, max_tokens=2048)
