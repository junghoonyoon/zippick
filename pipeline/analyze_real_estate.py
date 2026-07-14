"""부동산 유튜브 자막에서 검색 대상에 대한 의견만 분석한다."""
import json
import re
import time

import requests

import config

_client = None
_working = None
_GEMINI_CANDIDATES = ["gemini-2.0-flash", "gemini-2.5-flash", "gemini-flash-latest"]
LAST_GENERATION_PROVIDER = None

_STANCE_ALIASES = {
    "상승": "상승기대",
    "상승기대": "상승기대",
    "긍정": "상승기대",
    "매수": "상승기대",
    "관망": "관망",
    "중립": "관망",
    "조건부": "관망",
    "주의": "주의",
    "부정": "주의",
    "하락": "주의",
    "위험": "주의",
    "단순언급": "단순언급",
    "단순 언급": "단순언급",
}

_OPINION_PROMPT = """다음은 부동산 유튜브 자막 중 '{target}' 관련 문맥입니다.
화자가 이 지역·단지·정책·개발 이슈에 대해 실제로 어떤 의견을 냈는지 아래 JSON으로만 답하세요.

{{
  "mentioned": true,
  "stance": "상승기대|관망|주의|단순언급 중 하나",
  "summary": "판단: 화자가 어떻게 보는지 결론만 1문장으로 압축",
  "evidence": "근거: 그 판단을 뒷받침한 자막 속 가격·입지·수요·공급·정책·거래량 맥락을 1문장으로 설명"
}}

규칙:
- '{target}' 또는 별칭({aliases})이 부동산 의미로 언급되지 않았다면 mentioned=false로 답하세요.
- 창호·인테리어·리모델링 시공·가구·가전·자재·광고·매물 소개처럼 제품/시공/홍보가 주제이고, 가격·입지·수요·공급·정책·거래량·전망 판단이 없다면 mentioned=false로 답하세요.
- 전체 부동산 시장 분위기를 검색 대상 의견으로 복사하지 마세요.
- 상승기대: 가격 상승, 수요 증가, 입지 개선, 개발 호재, 저평가, 매수 우호를 명시.
- 관망: 가격 부담, 금리, 공급, 거래량, 정책, 입주 물량 확인이 필요하다고 말함.
- 주의: 하락 가능성, 미분양, 공급 과잉, 전세 리스크, 고평가, 추격매수 위험을 명시.
- 단순언급: 이름은 나왔지만 부동산 시장/입지/가격 판단이 아주 약함. 제품 시공 소개나 광고는 단순언급이 아니라 mentioned=false입니다.
- 자막에 없는 내용을 추측하지 마세요.
- summary는 20~50자 안팎의 자연스러운 한국어 존댓말로 쓰세요.
- evidence는 summary를 반복하지 말고 구체적 근거를 설명하세요.

자막 문맥:
{context}
"""


def _extract_json(text):
    text = (text or "").strip()
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    return json.loads(match.group(1) if match else text)


def _client_lazy():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


def _is_transient(message):
    message = message.lower()
    return any(token in message for token in ("503", "unavailable", "429", "resource_exhausted", "overloaded"))


def _generate_gemini(prompt):
    global _working
    if not config.GEMINI_API_KEY:
        raise RuntimeError("Gemini API 키가 없어요.")
    order = []
    for name in [_working, config.GEMINI_MODEL] + _GEMINI_CANDIDATES:
        if name and name not in order:
            order.append(name)
    last = None
    for name in order:
        for attempt in range(4):
            try:
                response = _client_lazy().models.generate_content(model=name, contents=prompt)
                _working = name
                return response.text
            except Exception as exc:
                last = exc
                if _is_transient(str(exc)) and attempt < 3:
                    time.sleep(3 * (2 ** attempt))
                    continue
                break
    raise last


def _generate_ollama(prompt):
    response = requests.post(
        f"{config.OLLAMA_URL.rstrip('/')}/api/chat",
        json={
            "model": config.OLLAMA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "format": "json",
            "think": False,
            "options": {"temperature": 0},
        },
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = (response.json().get("message") or {}).get("content", "")
    if not text.strip():
        raise RuntimeError("Ollama가 빈 응답을 반환했어요.")
    _extract_json(text)
    return text


def _generate_openrouter(prompt):
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OpenRouter API 키가 없어요.")
    headers = {
        "Authorization": f"Bearer {config.OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "X-Title": config.OPENROUTER_TITLE,
    }
    if config.OPENROUTER_REFERER:
        headers["HTTP-Referer"] = config.OPENROUTER_REFERER
    response = requests.post(
        f"{config.OPENROUTER_BASE_URL.rstrip('/')}/chat/completions",
        headers=headers,
        json={
            "model": config.OPENROUTER_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        timeout=config.OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    text = ((response.json().get("choices") or [{}])[0].get("message") or {}).get("content", "")
    if not text.strip():
        raise RuntimeError("OpenRouter가 빈 응답을 반환했어요.")
    _extract_json(text)
    return text


def _validate_opinion_text(text):
    data = _extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("mentioned"), bool):
        raise ValueError("부동산 의견 결과 형식이 잘못됐어요.")
    if data.get("mentioned"):
        stance = _STANCE_ALIASES.get(str(data.get("stance", "")).strip())
        if stance not in config.STANCES:
            raise ValueError("부동산 의견 방향이 잘못됐어요.")
        if not str(data.get("summary", "")).strip():
            raise ValueError("부동산 의견 요약이 없어요.")


def _generate(prompt, validator=None):
    global LAST_GENERATION_PROVIDER
    provider = config.ANALYSIS_PROVIDER.lower()
    errors = []

    if provider in ("local-first", "ollama"):
        try:
            text = _generate_ollama(prompt)
            if validator:
                validator(text)
            LAST_GENERATION_PROVIDER = f"ollama:{config.OLLAMA_MODEL}"
            return text
        except Exception as exc:
            errors.append(f"Ollama: {str(exc)[:180]}")
            if provider == "ollama":
                raise RuntimeError(errors[-1]) from exc

    if provider in ("local-first", "gemini"):
        try:
            text = _generate_gemini(prompt)
            if validator:
                validator(text)
            LAST_GENERATION_PROVIDER = f"gemini:{_working or config.GEMINI_MODEL}"
            return text
        except Exception as exc:
            errors.append(f"Gemini: {str(exc)[:180]}")

    if provider == "openrouter":
        try:
            text = _generate_openrouter(prompt)
            if validator:
                validator(text)
            LAST_GENERATION_PROVIDER = f"openrouter:{config.OPENROUTER_MODEL}"
            return text
        except Exception as exc:
            errors.append(f"OpenRouter: {str(exc)[:180]}")

    LAST_GENERATION_PROVIDER = None
    raise RuntimeError(" / ".join(errors) or f"지원하지 않는 분석 방식: {provider}")


def analyze_opinion(target, aliases, context):
    data = _extract_json(_generate(
        _OPINION_PROMPT.format(
            target=target,
            aliases=", ".join(aliases),
            context=context[:config.SEARCH_CONTEXT_MAX_CHARS],
        ),
        validator=_validate_opinion_text,
    ))
    if not data.get("mentioned"):
        return {"mentioned": False, "stance": "단순언급", "summary": "", "evidence": ""}
    stance = _STANCE_ALIASES.get(str(data.get("stance", "")).strip(), data.get("stance"))
    return {
        "mentioned": True,
        "stance": stance,
        "summary": str(data.get("summary", "")).strip(),
        "evidence": str(data.get("evidence", "")).strip(),
    }
