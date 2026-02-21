"""
AI API wrapper — text generation with Gemini (primary) and Claude (fallback).

All pipeline scripts import from this module. Fallback is transparent to callers.
"""

from __future__ import annotations

import json
from typing import Any, Union

import anthropic

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    CLAUDE_API_KEY,
    CLAUDE_MODEL,
    GEMINI_API_KEY,
    GEMINI_MODEL,
    get_logger,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Claude client (fallback)
# ---------------------------------------------------------------------------
_claude_client: anthropic.Anthropic | None = None


def _get_claude_client() -> anthropic.Anthropic:
    global _claude_client
    if _claude_client is None:
        _claude_client = anthropic.Anthropic(api_key=CLAUDE_API_KEY)
    return _claude_client


def _generate_claude(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """Call Claude API and return text."""
    client = _get_claude_client()
    messages = [{"role": "user", "content": prompt}]

    kwargs: dict[str, Any] = {
        "model": model or CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": messages,
        "temperature": temperature,
    }
    if system:
        kwargs["system"] = system

    logger.info(f"Claude API call: model={kwargs['model']}, max_tokens={max_tokens}")
    response = client.messages.create(**kwargs)
    text = response.content[0].text
    logger.info(f"Claude API response: {len(text)} chars, usage={response.usage}")
    return text


# ---------------------------------------------------------------------------
# Gemini client (primary)
# ---------------------------------------------------------------------------
_gemini_model = None


def _get_gemini_model():
    global _gemini_model
    if _gemini_model is None:
        import google.generativeai as genai

        genai.configure(api_key=GEMINI_API_KEY)
        _gemini_model = genai.GenerativeModel(GEMINI_MODEL)
    return _gemini_model


def _generate_gemini(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    response_mime_type: str | None = None,
) -> str:
    """Call Gemini API and return text."""
    import google.generativeai as genai

    model = _get_gemini_model()

    # Gemini doesn't have a separate system param — prepend to prompt
    full_prompt = f"{system}\n\n{prompt}" if system else prompt

    generation_config = genai.GenerationConfig(
        max_output_tokens=max_tokens,
        temperature=temperature,
    )
    if response_mime_type:
        generation_config = genai.GenerationConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
            response_mime_type=response_mime_type,
        )

    logger.info(f"Gemini API call: model={GEMINI_MODEL}, max_tokens={max_tokens}")
    response = model.generate_content(full_prompt, generation_config=generation_config)
    text = response.text
    logger.info(f"Gemini API response: {len(text)} chars")
    return text


# ---------------------------------------------------------------------------
# Public API (unchanged interface)
# ---------------------------------------------------------------------------

def generate_text(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """Send a prompt to an AI model and return the text response.

    Tries Gemini first, falls back to Claude on failure.
    """
    # 1. Try Gemini (primary)
    if GEMINI_API_KEY:
        try:
            return _generate_gemini(
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as e:
            logger.warning(f"Gemini API failed: {e}")
            if not CLAUDE_API_KEY:
                raise

    # 2. Fallback to Claude
    if CLAUDE_API_KEY:
        logger.info("Falling back to Claude API")
        return _generate_claude(
            prompt=prompt,
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    raise RuntimeError("No AI API available — set GEMINI_API_KEY or CLAUDE_API_KEY")


def generate_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.5,
) -> dict | list:
    """Send a prompt to an AI model and parse the response as JSON.

    Tries Gemini (with JSON mode) first, falls back to Claude on failure.
    """
    # 1. Try Gemini with JSON mode (primary)
    if GEMINI_API_KEY:
        try:
            raw = _generate_gemini(
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                response_mime_type="application/json",
            )
            return _parse_json_response(raw)
        except Exception as e:
            logger.warning(f"Gemini API failed for JSON generation: {e}")
            if not CLAUDE_API_KEY:
                raise

    # 2. Fallback to Claude
    if CLAUDE_API_KEY:
        logger.info("Falling back to Claude API for JSON generation")
        raw = _generate_claude(
            prompt=prompt,
            system=system,
            model=model,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return _parse_json_response(raw)

    raise RuntimeError("No AI API available — set GEMINI_API_KEY or CLAUDE_API_KEY")


def generate_json_with_retry(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.5,
    max_retries: int = 3,
    validator=None,
) -> dict | list:
    """Generate JSON with automatic retry and optional validation.

    On failure, appends a correction hint and lowers temperature.
    If a validator callable is provided, it must return a ValidationResult
    with .valid (bool) and .data (corrected data, or None).
    """
    last_errors: list[str] = []

    for attempt in range(1, max_retries + 1):
        # Progressive temperature reduction: 0.5 → 0.4 → 0.3
        temp = max(temperature - 0.1 * (attempt - 1), 0.2)

        # On retry, append correction context
        retry_prompt = prompt
        if attempt > 1 and last_errors:
            correction = (
                f"\n\n---\n前回の出力にエラーがありました。以下を修正してください:\n"
                + "\n".join(f"- {e}" for e in last_errors[:5])
                + "\n正しいJSON配列で出力してください。"
            )
            retry_prompt = prompt + correction

        logger.info(
            f"generate_json_with_retry: attempt {attempt}/{max_retries}, "
            f"temperature={temp}"
        )

        try:
            result = generate_json(
                prompt=retry_prompt,
                system=system,
                model=model,
                max_tokens=max_tokens,
                temperature=temp,
            )
        except Exception as e:
            logger.warning(f"API call failed on attempt {attempt}: {e}")
            last_errors = [str(e)]
            if attempt == max_retries:
                raise
            continue

        # Check for parse failure (empty list returned by _parse_json_response)
        if result == [] and attempt < max_retries:
            last_errors = ["JSONパースエラー: 空のリストが返却されました"]
            continue

        # Run validator if provided
        if validator is not None:
            vr = validator(result)
            if not vr.valid:
                last_errors = vr.errors
                logger.warning(
                    f"Validation failed (attempt {attempt}): {vr.errors}"
                )
                if attempt < max_retries:
                    continue
                # On final attempt, return what we have with warnings logged
                logger.error(
                    f"Validation still failing after {max_retries} attempts. "
                    f"Returning best-effort result."
                )
                return vr.data if vr.data is not None else result
            # Valid — return corrected data if available
            return vr.data if vr.data is not None else result

        return result

    # Should not reach here, but just in case
    raise ValueError(f"generate_json_with_retry failed after {max_retries} attempts")


def _parse_json_response(raw: str) -> dict | list:
    """Strip markdown fences and parse JSON."""
    cleaned = raw.strip()
    if not cleaned:
        logger.warning("Empty AI response — returning empty list")
        return []
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n")
        last_fence = cleaned.rfind("```")
        cleaned = cleaned[first_newline + 1 : last_fence].strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e} — raw response: {cleaned[:200]}")
        return []
