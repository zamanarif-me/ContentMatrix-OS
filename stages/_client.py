"""
Hybrid LLM client — Anthropic Claude + Google Gemini.

Provider is auto-detected from the model ID:
  "claude-*"  -> Anthropic
  "gemini-*"  -> Google

Two entry points:
  call_text()       -> returns raw text (use for prose: section bodies, intros, FAQs)
  call_structured() -> returns a parsed Pydantic model (use for outlines, reports)

NEW (this version):
  - Auto-retry on Gemini 429 RESOURCE_EXHAUSTED with parsed retryDelay
  - Auto-fallback to Claude when Gemini quota is exhausted:
      gemini-flash → claude-haiku-4-5
      gemini-pro   → claude-sonnet-4-6
  - Better error messages for production debugging
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Literal, Optional, TypeVar

from anthropic import Anthropic
from google import genai as google_genai
from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)

# ── Model constants (2026 IDs) ────────────────────────────────────────────────

CLAUDE_OPUS_4_7   = "claude-opus-4-7"
CLAUDE_SONNET_4_6 = "claude-sonnet-4-6"
CLAUDE_HAIKU_4_5  = "claude-haiku-4-5"
GEMINI_2_5_PRO    = "gemini-2.5-pro"
GEMINI_2_0_FLASH  = "gemini-2.0-flash"

DEFAULT_MODEL      = CLAUDE_SONNET_4_6
DEFAULT_MAX_TOKENS = 8000

Provider = Literal["anthropic", "gemini"]


# ── Client builders ──────────────────────────────────────────────────────────

def get_anthropic_client() -> Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. "
            "Add to .env locally, or to Streamlit Cloud Secrets in production."
        )
    return Anthropic(api_key=key)


def get_gemini_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. "
            "Add to .env locally, or to Streamlit Cloud Secrets in production."
        )
    return google_genai.Client(api_key=key)


def detect_provider(model: str) -> Provider:
    if model.startswith("gemini"):
        return "gemini"
    return "anthropic"


# ── Prompt loader ─────────────────────────────────────────────────────────────

PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

_HOUSE_RULES_CACHE: Optional[str] = None


def _house_rules() -> str:
    """Lazy-load and cache the universal house rules."""
    global _HOUSE_RULES_CACHE
    if _HOUSE_RULES_CACHE is None:
        path = PROMPTS_DIR / "_house_rules.txt"
        _HOUSE_RULES_CACHE = path.read_text(encoding="utf-8") if path.exists() else ""
    return _HOUSE_RULES_CACHE


def load_prompt(name: str, include_house_rules: bool = True) -> str:
    """
    Load a system prompt file from /prompts.
    By default, prepends the universal house rules from `_house_rules.txt`.
    """
    path = PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    body = path.read_text(encoding="utf-8")
    if include_house_rules:
        return _house_rules() + "\n\n" + body
    return body


# ── JSON extraction ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> str:
    """Strip markdown fences. Returns the first JSON object found."""
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        return fence.group(1)
    first = text.find("{")
    last = text.rfind("}")
    if first == -1 or last == -1 or last < first:
        raise ValueError(f"No JSON object found. Got:\n{text[:400]}")
    return text[first : last + 1]


# ── Error classification & retry helpers ─────────────────────────────────────

def _is_quota_error(exc: Exception) -> bool:
    """Detect Gemini 429 RESOURCE_EXHAUSTED or Anthropic rate-limit errors."""
    s = str(exc)
    return (
        "429" in s
        or "RESOURCE_EXHAUSTED" in s
        or "rate_limit" in s.lower()
        or "quota" in s.lower()
    )


def _parse_retry_delay(exc: Exception, default: float = 5.0) -> float:
    """Pull `retryDelay: Xs` from a Gemini error message, capped at 30s."""
    s = str(exc)
    match = re.search(r"retryDelay['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)s", s)
    if match:
        try:
            return min(float(match.group(1)) + 0.5, 30.0)
        except ValueError:
            pass
    match = re.search(r"retry in (\d+(?:\.\d+)?)s", s)
    if match:
        try:
            return min(float(match.group(1)) + 0.5, 30.0)
        except ValueError:
            pass
    return default


def _claude_fallback_for(model: str) -> str | None:
    """Map a Gemini model → equivalent Claude model for emergency fallback."""
    if model.startswith("gemini"):
        if "flash" in model:
            return CLAUDE_HAIKU_4_5
        return CLAUDE_SONNET_4_6
    return None


# ── call_text — for prose generation ──────────────────────────────────────────

def call_text(
    system_prompt: str,
    user_message: str,
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = 3,
    stage: str = "unknown",
    temperature: float = 0.7,
    allow_fallback: bool = True,
) -> str:
    """
    Call an LLM and return raw text.
    Retry strategy:
      - Transient errors: exponential backoff (2, 4, 8s)
      - Gemini 429: parse retryDelay, sleep, retry
      - Persistent Gemini quota: auto-fallback to Claude
    """
    provider = detect_provider(model)
    last_err: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            if provider == "anthropic":
                return _call_anthropic_text(system_prompt, user_message, model, max_tokens, stage, temperature)
            return _call_gemini_text(system_prompt, user_message, model, stage, temperature, max_tokens)
        except Exception as e:
            last_err = e

            if _is_quota_error(e):
                if attempt < max_retries:
                    delay = _parse_retry_delay(e)
                    print(
                        f"[_client] {stage} hit quota on {model}. "
                        f"Retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                if allow_fallback and provider == "gemini":
                    fallback = _claude_fallback_for(model)
                    if fallback:
                        print(
                            f"[_client] {stage} exhausted on {model} → "
                            f"falling back to {fallback}",
                            flush=True,
                        )
                        return _call_anthropic_text(
                            system_prompt, user_message, fallback,
                            max_tokens, f"{stage}_fallback", temperature,
                        )
                raise RuntimeError(
                    f"Gemini quota exhausted after {max_retries+1} attempts. "
                    f"Either upgrade to paid tier (https://ai.google.dev/pricing) "
                    f"or set ANTHROPIC_API_KEY for auto-fallback. "
                    f"Original: {str(e)[:200]}"
                )

            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError(f"Unreachable. Last error: {last_err}")


# ── call_structured — for outlines, QA reports ───────────────────────────────

def call_structured(
    system_prompt: str,
    user_message: str,
    response_model: type[T],
    *,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_retries: int = 3,
    stage: str = "unknown",
    temperature: float = 0.3,
    allow_fallback: bool = True,
) -> T:
    """
    Call an LLM and parse JSON response into a Pydantic model.
    Same retry/fallback strategy as call_text + JSON re-prompt on validation failure.
    """
    last_err: Exception | None = None
    msg = user_message
    active_model = model

    for attempt in range(max_retries + 1):
        try:
            if detect_provider(active_model) == "anthropic":
                text = _call_anthropic_text(system_prompt, msg, active_model, max_tokens, stage, temperature)
            else:
                text = _call_gemini_text(system_prompt, msg, active_model, stage, temperature, max_tokens)
            data = json.loads(_extract_json(text))
            return response_model.model_validate(data)

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            last_err = e
            if attempt < max_retries:
                msg = (
                    user_message
                    + f"\n\nIMPORTANT: previous response failed validation: "
                    + f"{type(e).__name__}: {str(e)[:200]}. "
                    + "Return ONLY valid JSON — no fences, no commentary."
                )
                continue
            raise RuntimeError(f"Failed after {max_retries + 1} attempts: {e}") from e

        except Exception as e:
            last_err = e

            if _is_quota_error(e):
                if attempt < max_retries:
                    delay = _parse_retry_delay(e)
                    print(
                        f"[_client] {stage} hit quota on {active_model}. "
                        f"Retrying in {delay:.1f}s (attempt {attempt+1}/{max_retries})",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue
                if allow_fallback and detect_provider(active_model) == "gemini":
                    fallback = _claude_fallback_for(active_model)
                    if fallback:
                        print(
                            f"[_client] {stage} exhausted on {active_model} → "
                            f"falling back to {fallback}",
                            flush=True,
                        )
                        active_model = fallback
                        continue
                raise RuntimeError(
                    f"Gemini quota exhausted after {max_retries+1} attempts. "
                    f"Either upgrade to paid tier or ensure ANTHROPIC_API_KEY is set for fallback. "
                    f"Original: {str(e)[:200]}"
                )

            if attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            raise

    raise RuntimeError(f"Unreachable. Last error: {last_err}")


# ── Provider-specific text calls ─────────────────────────────────────────────

def _call_anthropic_text(
    system_prompt: str,
    user_message: str,
    model: str,
    max_tokens: int,
    stage: str,
    temperature: float,
) -> str:
    from stages.cost_tracker import tracker
    client = get_anthropic_client()
    resp = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        temperature=temperature,
        messages=[{"role": "user", "content": user_message}],
    )
    u = resp.usage
    tracker.log_llm_call(
        stage=stage, model=model,
        input_tokens=u.input_tokens, output_tokens=u.output_tokens,
    )
    return resp.content[0].text


def _call_gemini_text(
    system_prompt: str,
    user_message: str,
    model: str,
    stage: str,
    temperature: float,
    max_tokens: int,
) -> str:
    from stages.cost_tracker import tracker
    client = get_gemini_client()
    resp = client.models.generate_content(
        model=model,
        contents=user_message,
        config=google_genai.types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    try:
        meta = resp.usage_metadata
        tracker.log_llm_call(
            stage=stage, model=model,
            input_tokens=meta.prompt_token_count or 0,
            output_tokens=meta.candidates_token_count or 0,
        )
    except Exception:
        pass
    return resp.text
