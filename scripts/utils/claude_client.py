"""
AI API wrapper — Gemini only (google-genai SDK).

All pipeline scripts import from this module.
"""

from __future__ import annotations

import json
from typing import Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    get_logger,
)

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Gemini client (google-genai SDK)
# ---------------------------------------------------------------------------
_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai

        _client = genai.Client(api_key=GEMINI_API_KEY)
    return _client


def _generate_gemini(
    prompt: str,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.7,
    response_mime_type: str | None = None,
    use_search: bool = False,
) -> str:
    """Call Gemini API and return text.

    Args:
        use_search: Enable Google Search grounding for evidence-based tasks.
                    NOTE: Cannot be used with response_mime_type (JSON mode).
    """
    from google.genai import types

    client = _get_client()

    config_kwargs: dict[str, Any] = {
        "max_output_tokens": max_tokens,
        "temperature": temperature,
    }
    if system:
        config_kwargs["system_instruction"] = system
    if response_mime_type and not use_search:
        config_kwargs["response_mime_type"] = response_mime_type
    if use_search:
        config_kwargs["tools"] = [
            types.Tool(google_search=types.GoogleSearch())
        ]

    config = types.GenerateContentConfig(**config_kwargs)

    logger.info(f"Gemini API call: model={GEMINI_MODEL}, max_tokens={max_tokens}, search={use_search}")
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=config,
    )
    text = response.text
    logger.info(f"Gemini API response: {len(text)} chars")
    return text


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_text(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.7,
) -> str:
    """Send a prompt to Gemini and return the text response."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    return _generate_gemini(
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
    )


def generate_json(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.5,
    use_search: bool = False,
) -> dict | list:
    """Send a prompt to Gemini and parse the response as JSON.

    When use_search=True, disables JSON mode (incompatible with grounding)
    and relies on prompt to request JSON output.
    """
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set")

    raw = _generate_gemini(
        prompt=prompt,
        system=system,
        max_tokens=max_tokens,
        temperature=temperature,
        response_mime_type=None if use_search else "application/json",
        use_search=use_search,
    )
    return _parse_json_response(raw)


def generate_json_with_retry(
    prompt: str,
    system: str = "",
    model: str | None = None,
    max_tokens: int = 4096,
    temperature: float = 0.5,
    max_retries: int = 3,
    validator=None,
    use_search: bool = False,
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
                use_search=use_search,
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
        raise ValueError("Empty AI response for JSON generation")
    if cleaned.startswith("```"):
        first_newline = cleaned.index("\n")
        last_fence = cleaned.rfind("```")
        if last_fence > first_newline:
            cleaned = cleaned[first_newline + 1 : last_fence].strip()
    try:
        result = json.loads(cleaned)
        if result is None:
            raise ValueError("Parsed JSON is null")
        return result
    except json.JSONDecodeError as e:
        logger.error(f"JSON parse failed: {e} — raw response: {cleaned[:300]}")
        raise ValueError(f"JSON parse failed: {e}") from e
