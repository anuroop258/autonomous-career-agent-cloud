"""Adaptive form runtime helpers.

The module deliberately does not make browser decisions from an LLM.  It
provides the observe/act/verify primitives used by AIFormEngine:
- structured field snapshots
- frame-aware inspection
- local label/context resolution
- React/Vue-safe native value setting
- native and ARIA/custom select handling
- checkbox/radio helpers
"""
from __future__ import annotations

import asyncio
import re
from typing import Any


def norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class FormObserver:
    CONTROL_SELECTOR = (
        "input, textarea, select, button, "
        "[role='combobox'], [role='checkbox'], [role='radio'], "
        "[contenteditable='true']"
    )

    async def scopes(self, page):
        # Playwright's page.frames includes the main frame and nested frames.
        frames = getattr(page, "frames", None)
        if frames:
            try:
                return list(frames)
            except Exception:
                pass
        return [page]

    async def _label_for(self, scope, element):
        # Keep context local to the field.  Never read the entire form as a
        # label because that causes neighbouring labels to contaminate meaning.
        try:
            fid = await element.get_attribute("id")
            if fid:
                labels = scope.locator(f"label[for='{fid}']")
                if await labels.count():
                    text = clean(await labels.first.inner_text())
                    if text:
                        return text
        except Exception:
            pass
        try:
            labels = element.locator("xpath=ancestor::label[1]")
            if await labels.count():
                text = clean(await labels.first.inner_text())
                if text:
                    return text
        except Exception:
            pass
        try:
            labelled = await element.get_attribute("aria-labelledby")
            if labelled:
                texts = []
                for ident in labelled.split():
                    try:
                        node = scope.locator(f"#{ident}")
                        if await node.count():
                            texts.append(clean(await node.first.inner_text()))
                    except Exception:
                        continue
                text = clean(" ".join(x for x in texts if x))
                if text:
                    return text
        except Exception:
            pass
        # Closest local label-like node.  Do NOT use document-wide
        # preceding:: selectors here: two-column forms commonly render
        # [Email label][Email input][Age label][Age input], and a global
        # preceding label lookup can incorrectly assign "Email" to Age.
        # Oracle HCM/Redwood-style controls often keep the semantic label on
        # the custom wrapper (for example `label-hint="Current Location"`)
        # while the inspected input itself has no label/placeholder.  Walk a
        # small ancestor chain, including shadow-DOM hosts, and prefer explicit
        # semantic label attributes over surrounding text.
        try:
            text = await element.evaluate(
                r"""el => {
                    const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                    const seen = new Set();
                    let node = el;
                    for (let depth = 0; node && depth < 8; depth++) {
                        if (seen.has(node)) break;
                        seen.add(node);

                        for (const attr of ['label-hint', 'aria-label', 'title']) {
                            const value = clean(node.getAttribute?.(attr));
                            if (value && value.length <= 180) return value;
                        }

                        const nestedLabel = node.querySelector?.('label, .oj-label, [class*="oj-label"]');
                        if (nestedLabel) {
                            const value = clean(nestedLabel.innerText || nestedLabel.textContent);
                            if (value && value.length <= 180) return value;
                        }

                        const root = node.getRootNode?.();
                        node = node.parentElement || root?.host || null;
                    }
                    return '';
                }"""
            )
            text = clean(text)
            if text:
                return text
        except Exception:
            pass

        for xpath in (
            "xpath=preceding-sibling::label[1]",
            "xpath=preceding-sibling::*[@data-label][1]",
            "xpath=../label[1]",
            "xpath=../*[self::span or self::div][1]/label[1]",
        ):
            try:
                node = element.locator(xpath)
                if await node.count():
                    text = clean(await node.first.inner_text())
                    if text and len(text) <= 180:
                        return text
            except Exception:
                continue

        # Last-resort local DOM walk: find the nearest previous element in
        # the same wrapper whose own text looks like a label and which does
        # not contain another form control.  This stays inside a small local
        # ancestor window rather than searching the whole document.
        try:
            text = await element.evaluate(
                r"""el => {
                    const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                    let node = el;
                    for (let depth = 0; node && depth < 3; depth++, node = node.parentElement) {
                        let sib = node.previousElementSibling;
                        while (sib) {
                            const controls = sib.querySelectorAll(
                                'input, textarea, select, button, [role="combobox"], [contenteditable="true"]'
                            );
                            const label = sib.matches?.('label') ? sib : sib.querySelector?.('label');
                            if (label && controls.length === 0) {
                                const t = clean(label.innerText || label.textContent);
                                if (t && t.length <= 180) return t;
                            }
                            sib = sib.previousElementSibling;
                        }
                    }
                    return '';
                }"""
            )
            text = clean(text)
            if text:
                return text
        except Exception:
            pass

        for attr in ("aria-label", "title", "placeholder"):
            try:
                text = clean(await element.get_attribute(attr))
                if text:
                    return text
            except Exception:
                pass
        return ""

    async def _question_context(self, scope, element, attrs):
        """Resolve the semantic question for a control without page-wide text."""
        candidates = []
        try:
            described = attrs.get("aria-describedby") or ""
            for ident in described.split():
                node = scope.locator(f"#{ident}")
                if await node.count():
                    candidates.append(clean(await node.first.inner_text()))
        except Exception:
            pass
        try:
            labelled = attrs.get("aria-labelledby") or ""
            for ident in labelled.split():
                node = scope.locator(f"#{ident}")
                if await node.count():
                    candidates.append(clean(await node.first.inner_text()))
        except Exception:
            pass
        # Fieldset/radiogroup legends have higher semantic value than an
        # individual Yes/No option label.
        for selector in (
            "xpath=ancestor::fieldset[1]",
            "xpath=ancestor::*[@role='radiogroup'][1]",
            "xpath=ancestor::*[@role='group'][1]",
        ):
            try:
                parent = element.locator(selector)
                if await parent.count():
                    legend = parent.locator("legend").first
                    if await legend.count():
                        text = clean(await legend.inner_text())
                        if text: candidates.append(text)
                    aria = await parent.get_attribute("aria-label")
                    if aria: candidates.append(clean(aria))
                    al = await parent.get_attribute("aria-labelledby")
                    if al:
                        for ident in al.split():
                            node = scope.locator(f"#{ident}")
                            if await node.count():
                                candidates.append(clean(await node.first.inner_text()))
            except Exception:
                continue
        # Deduplicate while preserving order and keep the result bounded.
        out = []
        seen = set()
        for item in candidates:
            item = clean(item)
            if not item or item in seen:
                continue
            seen.add(item)
            if len(item) <= 300:
                out.append(item)
        return clean(" ".join(out))[:500]

    async def snapshot_scope(self, scope, frame_index: int = 0):
        fields = []
        try:
            controls = scope.locator(self.CONTROL_SELECTOR)
            count = await controls.count()
        except Exception:
            return fields

        for i in range(count):
            element = controls.nth(i)
            try:
                if not await element.is_visible():
                    continue
            except Exception:
                continue
            try:
                tag = norm(await element.evaluate("el => el.tagName"))
            except Exception:
                tag = ""
            attrs = {}
            for attr in (
                "id", "name", "type", "placeholder", "aria-label",
                "aria-labelledby", "aria-describedby", "aria-controls", "autocomplete", "role",
                "accept", "required", "aria-required", "readonly", "disabled",
            ):
                try:
                    attrs[attr] = await element.get_attribute(attr) or ""
                except Exception:
                    attrs[attr] = ""
            label = await self._label_for(scope, element)
            value = ""
            try:
                value = await element.input_value()
            except Exception:
                try:
                    value = await element.get_attribute("value") or ""
                except Exception:
                    pass
            checked = False
            if attrs["type"] in {"checkbox", "radio"} or attrs["role"] in {"checkbox", "radio"}:
                try:
                    checked = await element.is_checked()
                except Exception:
                    try:
                        checked = norm(await element.get_attribute("aria-checked")) == "true"
                    except Exception:
                        pass
            options = []
            if tag == "select":
                try:
                    options = await element.locator("option").evaluate_all(
                        "els => els.map(o => ({value:o.value, text:(o.innerText||o.textContent||'').trim(), disabled:o.disabled}))"
                    )
                except Exception:
                    options = []
            elif attrs["role"] == "combobox":
                try:
                    controls_id = attrs.get("aria-controls")
                    if controls_id:
                        opts = scope.locator(f"#{controls_id} [role='option']")
                    else:
                        opts = scope.locator("[role='option']:visible")
                    if await opts.count():
                        options = await opts.evaluate_all(
                            "els => els.map(o => ({value:o.getAttribute('data-value')||'', text:(o.innerText||o.textContent||'').trim()}))"
                        )
                except Exception:
                    pass
            try:
                context = clean(await element.evaluate("el => { const p=el.parentElement; return p ? (p.innerText||'').slice(0,500) : '' }"))
            except Exception:
                context = ""
            try:
                frame_url = scope.url
            except Exception:
                frame_url = ""

            # Prefer semantic group context over the immediate option label.
            # This is critical for radio/checkbox questions where the control
            # label is often just "Yes" or "No" while the actual question is
            # stored in a fieldset legend or ARIA group label.
            question_context = await self._question_context(scope, element, attrs)

            fields.append({
                "index": len(fields),
                "scope_index": frame_index,
                "element": element,
                "locator": element,
                "scope": scope,
                "tag": tag,
                "type": norm(attrs["type"]),
                "name": attrs["name"],
                "id": attrs["id"],
                "label": label,
                "placeholder": attrs["placeholder"],
                "aria_label": attrs["aria-label"],
                "aria_labelledby": attrs["aria-labelledby"],
                "aria_describedby": attrs["aria-describedby"],
                "aria_controls": attrs["aria-controls"],
                "question_context": question_context,
                "autocomplete": attrs["autocomplete"],
                "role": norm(attrs["role"]),
                "accept": attrs["accept"],
                "readonly": bool(attrs["readonly"]),
                "disabled": bool(attrs["disabled"]),
                "required": bool(attrs["required"]) or norm(attrs["aria-required"]) == "true",
                "value": value,
                "checked": checked,
                "options": options,
                "context": context,
                "frame_url": frame_url,
            })
        # Build semantic option sets for radio groups.  Every control retains
        # its own locator, but all members see the complete answer options and
        # the shared question context.
        radio_groups = {}
        for field in fields:
            if field.get("type") == "radio" or field.get("role") == "radio":
                key = (field.get("name") or field.get("question_context") or field.get("label") or "").strip()
                if key:
                    radio_groups.setdefault(key, []).append(field)
        for group in radio_groups.values():
            option_texts = []
            question = ""
            for member in group:
                question = question or member.get("question_context") or ""
                text = clean(member.get("label"))
                if text and text not in option_texts:
                    option_texts.append(text)
            if len(group) > 1:
                for member in group:
                    member["options"] = [{"value": text, "text": text, "disabled": False} for text in option_texts]
                    if question:
                        member["question_context"] = question
        return fields

    async def snapshot(self, page):
        result = []
        for idx, scope in enumerate(await self.scopes(page)):
            result.extend(await self.snapshot_scope(scope, idx))
        for idx, field in enumerate(result):
            field["index"] = idx
        return result


class AdaptiveWidgetFiller:
    """Browser-side actions that are deterministic and verifiable."""

    @staticmethod
    async def safe_text(element, value):
        value = str(value)
        # Native setter is important for React/Vue controlled inputs.
        try:
            await element.evaluate(
                """(el, value) => {
                    const proto = el instanceof HTMLTextAreaElement
                      ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
                    if (setter) setter.call(el, value); else el.value = value;
                    el.dispatchEvent(new Event('input', {bubbles:true}));
                    el.dispatchEvent(new Event('change', {bubbles:true}));
                }""",
                value,
            )
            actual = await element.input_value()
            if actual == value:
                try: await element.blur()
                except Exception: pass
                return True
        except Exception:
            pass
        try:
            await element.fill(value)
            await element.dispatch_event("input")
            await element.dispatch_event("change")
            await element.blur()
            return (await element.input_value()) == value
        except Exception:
            return False

    @staticmethod
    async def select_native(element, wanted, options=None):
        wanted_raw = str(wanted or "").strip()
        wanted = norm(wanted_raw)
        options = options or []
        if not wanted:
            return False

        def numeric_range(text):
            text = norm(text)
            m = re.search(r"(\d+(?:\.\d+)?)\s*(?:-|–|—|−|to)\s*(\d+(?:\.\d+)?)", text)
            if m:
                return float(m.group(1)), float(m.group(2))
            m = re.search(r"(?:less than|under|below)\s*(\d+(?:\.\d+)?)", text)
            if m:
                return 0.0, float(m.group(1)) - 0.0001
            m = re.search(r"(\d+(?:\.\d+)?)\s*\+", text)
            if m:
                return float(m.group(1)), float("inf")
            return None

        try:
            target_nums = re.findall(r"\d+(?:\.\d+)?", wanted_raw)
            target = float(target_nums[0]) if target_nums else None
        except Exception:
            target = None

        ranked = []
        for index, opt in enumerate(options):
            text = norm(opt.get("text"))
            value = norm(opt.get("value"))
            if not text and not value:
                continue

            score = 0.0
            if wanted in {text, value}:
                score = 100.0
            elif wanted in text or text in wanted:
                score = 80.0

            if target is not None:
                if wanted in {"0", "0 years", "0 year", "fresher", "less than 1 year"} and any(
                    x in f"{text} {value}" for x in ("fresher", "no experience", "less than 1 year")
                ):
                    score = max(score, 100.0)

                bounds = numeric_range(f"{text} {value}")
                if bounds and bounds[0] <= target <= bounds[1]:
                    low, high = bounds
                    width = (high - low) if high != float("inf") else 9999.0
                    score = max(score, 80.0 + (20.0 if target == low else 0.0) - min(width, 20.0))

            if score > 0:
                ranked.append((score, -index, opt))

        if not ranked:
            return False

        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        chosen = ranked[0][2]
        try:
            await element.select_option(value=chosen.get("value", ""), timeout=3000)
        except Exception:
            try:
                await element.select_option(label=chosen.get("text", ""), timeout=3000)
            except Exception:
                return False

        try:
            actual = await element.input_value()
            return norm(actual) == norm(chosen.get("value")) or norm(actual) == norm(chosen.get("text"))
        except Exception:
            return False

    @staticmethod
    async def select_custom(scope, element, wanted):
        wanted = norm(wanted)
        if not wanted:
            return False
        try:
            await element.click(timeout=3000)
        except Exception:
            return False
        await asyncio.sleep(0.15)
        selectors = ["[role='option']:visible", "li[role='option']:visible", "option:checked"]
        candidates = []
        for sel in selectors:
            try:
                loc = scope.locator(sel)
                for i in range(await loc.count()):
                    node = loc.nth(i)
                    try:
                        if not await node.is_visible(): continue
                        text = clean(await node.inner_text())
                        if not text: continue
                        n = norm(text)
                        score = 100 if n == wanted else 80 if wanted in n or n in wanted else 0
                        if score: candidates.append((score, node, text))
                    except Exception: continue
            except Exception: continue
        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            try:
                await candidates[0][1].click(timeout=3000)
                return True
            except Exception:
                pass
        try:
            await element.press("ArrowDown")
            await element.press("Enter")
            return True
        except Exception:
            return False
