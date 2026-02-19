"""
Form auto-submitter — fill and submit web contact forms using Playwright.

Supports dry-run mode (fills form but doesn't submit).
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import YOUR_NAME, YOUR_EMAIL, YOUR_COMPANY_NAME, get_logger

logger = get_logger(__name__)

# Field detection patterns (label/name/placeholder text → field type)
FIELD_PATTERNS = {
    "name": [r"名前", r"お名前", r"氏名", r"name", r"full.?name"],
    "email": [r"メール", r"email", r"e-mail", r"mail"],
    "company": [r"会社", r"企業", r"法人", r"組織", r"company", r"organization"],
    "phone": [r"電話", r"tel", r"phone"],
    "message": [r"内容", r"本文", r"メッセージ", r"お問い合わせ", r"message", r"inquiry", r"body", r"comment"],
}


async def submit_form(
    form_url: str,
    message: str,
    company_name: str = "",
    dry_run: bool = True,
    sender_name: str = "",
    sender_email: str = "",
    sender_company: str = "",
) -> dict:
    """Fill and submit a contact form.

    Args:
        form_url: URL of the contact/inquiry form page
        message: The sales message body
        company_name: Optional override for sender company name
        dry_run: If True, fill form but don't click submit
        sender_name: Override sender name (from settings)
        sender_email: Override sender email (from settings)
        sender_company: Override sender company (from settings)

    Returns:
        {"status": "success"|"failed"|"dry_run", "detail": str}
    """
    from playwright.async_api import async_playwright

    result = {"status": "failed", "detail": ""}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(form_url, timeout=15000)
            await page.wait_for_load_state("domcontentloaded")

            # Collect all input/textarea elements
            inputs = await page.query_selector_all("input, textarea, select")

            for el in inputs:
                el_type = (await el.get_attribute("type") or "text").lower()
                el_name = (await el.get_attribute("name") or "").lower()
                el_placeholder = (await el.get_attribute("placeholder") or "").lower()
                el_id = (await el.get_attribute("id") or "").lower()
                tag = await el.evaluate("el => el.tagName.toLowerCase()")

                # Build searchable text
                search_text = f"{el_name} {el_placeholder} {el_id}"

                # Try to find associated label
                label_text = ""
                if el_id:
                    label = await page.query_selector(f"label[for='{el_id}']")
                    if label:
                        label_text = (await label.inner_text()).lower()
                search_text += f" {label_text}"

                # Skip hidden/submit/button
                if el_type in ("hidden", "submit", "button", "image", "file"):
                    continue

                # Match field type
                field_type = _match_field_type(search_text)
                if not field_type:
                    continue

                # Fill value
                value = _get_value(field_type, message, company_name, sender_name, sender_email, sender_company)
                if not value:
                    continue

                if tag == "textarea":
                    await el.fill(value)
                elif tag == "select":
                    # Try first non-empty option
                    options = await el.query_selector_all("option")
                    for opt in options[1:]:
                        opt_val = await opt.get_attribute("value")
                        if opt_val:
                            await el.select_option(opt_val)
                            break
                else:
                    await el.fill(value)

                logger.info(f"Filled {field_type}: {el_name or el_id}")

            if dry_run:
                result = {"status": "dry_run", "detail": "Form filled but not submitted"}
                logger.info(f"Dry run complete for {form_url}")
            else:
                # Find and click submit button
                submit_btn = await _find_submit_button(page)
                if submit_btn:
                    await submit_btn.click()
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    result = {"status": "success", "detail": "Form submitted"}
                    logger.info(f"Form submitted at {form_url}")
                else:
                    result = {"status": "failed", "detail": "Submit button not found"}
                    logger.warning(f"No submit button found at {form_url}")

        except Exception as e:
            result = {"status": "failed", "detail": str(e)}
            logger.error(f"Form submission error at {form_url}: {e}")
        finally:
            await browser.close()

    return result


def _match_field_type(search_text: str) -> str | None:
    """Match input field text to a known field type."""
    for field_type, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, search_text, re.IGNORECASE):
                return field_type
    return None


def _get_value(
    field_type: str,
    message: str,
    company_name: str,
    sender_name: str = "",
    sender_email: str = "",
    sender_company: str = "",
) -> str:
    """Get the value to fill for a given field type."""
    values = {
        "name": sender_name or YOUR_NAME,
        "email": sender_email or YOUR_EMAIL,
        "company": sender_company or company_name or YOUR_COMPANY_NAME,
        "phone": "",  # Don't auto-fill phone
        "message": message,
    }
    return values.get(field_type, "")


async def _find_submit_button(page):
    """Find the submit button on the page."""
    selectors = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('送信')",
        "button:has-text('確認')",
        "button:has-text('Submit')",
        "input[value='送信']",
        "input[value='確認']",
    ]
    for sel in selectors:
        btn = await page.query_selector(sel)
        if btn:
            return btn
    return None
