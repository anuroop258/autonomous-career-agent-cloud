from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

from playwright.async_api import BrowserContext, Page

PROJECT_ROOT = Path(__file__).resolve().parents[2]
import sys
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from src.application.common.company_website_agent import CompanyWebsiteAgent


APPLY_RE = re.compile(r"\bapply(?:\s+now)?\b", re.I)
EASY_APPLY_RE = re.compile(r"\beasy\s+apply\b|\bapply\s+with\s+indeed\b", re.I)
EXTERNAL_RE = re.compile(
    r"\bapply\s+(?:on|via)\s+(?:the\s+)?(?:company|employer)\s+site\b|"
    r"\bapply\s+externally\b|\bexternal\s+application\b|"
    r"\bcompany\s+site\b|\bemployer\s+site\b",
    re.I,
)


class ApplicationFlow:
    """Small shared lifecycle used by the rebuilt Shine/TimesJobs/Glassdoor adapters."""

    @staticmethod
    async def label(page: Page, element) -> str:
        try:
            value = await element.evaluate(
                """e => [e.innerText || '', e.textContent || '', e.getAttribute('aria-label') || '',
                            e.getAttribute('value') || '', e.getAttribute('title') || '',
                            e.getAttribute('data-testid') || ''].join(' ')"""
            )
            return re.sub(r"\s+", " ", value or "").strip()
        except Exception:
            return ""

    @classmethod
    async def find_apply(cls, page: Page, *, external_only: bool = False, native_only: bool = False):
        controls = page.locator(
            "button:visible,a:visible,[role='button']:visible,input[type='button']:visible,input[type='submit']:visible"
        )
        try:
            count = min(await controls.count(), 400)
        except Exception:
            return None
        for index in range(count):
            element = controls.nth(index)
            try:
                if not await element.is_visible() or await element.is_disabled():
                    continue
                label = await cls.label(page, element)
                if not APPLY_RE.search(label):
                    continue
                if EASY_APPLY_RE.search(label) and external_only:
                    continue
                is_external = bool(EXTERNAL_RE.search(label))
                if not is_external:
                    for attr in ("href", "data-href", "data-url", "data-link"):
                        target = (await element.get_attribute(attr) or "").strip()
                        if target and not target.startswith(("#", "javascript:", "mailto:")):
                            joined = urljoin(page.url, target).lower()
                            if joined and not re.search(r"shine\.com|timesjobs\.com|glassdoor\.", joined):
                                is_external = True
                                break
                if native_only and (is_external or EASY_APPLY_RE.search(label) is False and re.search(r"employer|company", label, re.I)):
                    continue
                if external_only and not is_external:
                    continue
                return element
            except Exception:
                continue
        return None

    @staticmethod
    async def wait_for_destination(
        context: BrowserContext,
        source: Page,
        before_pages: Iterable[Page],
        source_domains: tuple[str, ...],
        timeout_ms: int = 60000,
    ) -> Page | None:
        before = set(before_pages)
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while asyncio.get_running_loop().time() < deadline:
            pages = [p for p in context.pages if not p.is_closed()]
            for candidate in reversed(pages):
                try:
                    url = (candidate.url or "").strip()
                    if candidate is not source and candidate not in before and url and url != "about:blank":
                        if not any(domain in url.lower() for domain in source_domains):
                            try:
                                await candidate.wait_for_load_state("domcontentloaded", timeout=2500)
                            except Exception:
                                pass
                            return candidate
                    if candidate is source and url and url != "about:blank" and not any(domain in url.lower() for domain in source_domains):
                        return candidate
                except Exception:
                    continue
            try:
                await source.wait_for_timeout(250)
            except Exception:
                await asyncio.sleep(0.25)
        return None

    @staticmethod
    async def wait_for_application_surface(page: Page, timeout_ms: int = 30000) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_ms / 1000
        while asyncio.get_running_loop().time() < deadline:
            try:
                body = re.sub(r"\s+", " ", await page.locator("body").inner_text(timeout=1200))
                if re.search(
                    r"review your application|submit your application|application questions|"
                    r"candidate information|resume|cv|work experience|education",
                    body,
                    re.I,
                ):
                    return True
                controls = page.locator(
                    "input:visible,textarea:visible,select:visible,[contenteditable='true']:visible"
                )
                if await controls.count() >= 3:
                    return True
                buttons = page.locator(
                    "button:visible,a:visible,[role='button']:visible,input[type='submit']:visible"
                )
                for index in range(min(await buttons.count(), 120)):
                    label = re.sub(r"\s+", " ", await ApplicationFlow.label(page, buttons.nth(index)))
                    if re.fullmatch(r"(continue|next|review|submit|apply|apply now|finish|done)", label, re.I):
                        return True
            except Exception:
                pass
            try:
                await page.wait_for_timeout(250)
            except Exception:
                await asyncio.sleep(0.25)
        return False

    @staticmethod
    async def run_company_site_form(page: Page, profile_path: str, resume_path: str | None, dry_run: bool = True):
        engine = CompanyWebsiteAgent(
            dry_run=dry_run,
            profile_path=profile_path,
            resume_path=resume_path,
        )
        return await engine.apply(page, page.url, application_opened=False)
