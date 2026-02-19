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
