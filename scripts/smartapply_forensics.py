#!/usr/bin/env python3
"""
READ-ONLY Indeed SmartApply forensic debugger.

Connects to an already-running Chrome CDP session and inspects all open pages
and frames. It does not click, type, fill, submit, or change page state.

Use it to determine why the form engine sees:
    next_unanswered_field selected=None
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.async_api import async_playwright, Frame

DEFAULT_CDP = "http://127.0.0.1:9222"

SELECTORS = {
    "input": "input",
    "textarea": "textarea",
    "select": "select",
    "contenteditable": "[contenteditable='true']",
    "textbox": "[role='textbox']",
    "combobox": "[role='combobox']",
    "radio": "input[type='radio'], [role='radio']",
    "checkbox": "input[type='checkbox'], [role='checkbox']",
    "buttons": "button, [role='button'], input[type='button'], input[type='submit']",
    "forms": "form",
}

META_JS = r"""
(el) => {
  const clean = v => String(v || '').replace(/\s+/g, ' ').trim();
  const rect = el.getBoundingClientRect();
  const style = getComputedStyle(el);

  let label = '';
  try {
    if (el.labels && el.labels.length) {
      label = Array.from(el.labels)
        .map(x => clean(x.innerText || x.textContent))
        .filter(Boolean).join(' | ');
    }
  } catch {}

  let context = '';
  for (const c of [
    el.closest('label'),
    el.closest('fieldset'),
    el.closest('[role="group"]'),
    el.closest('form'),
    el.closest('section'),
    el.parentElement,
    el
  ].filter(Boolean)) {
    const t = clean(c.innerText || c.textContent);
    if (t) { context = t.slice(0, 1200); break; }
  }

  return {
    tag: (el.tagName || '').toLowerCase(),
    type: clean(el.getAttribute('type')).toLowerCase(),
    role: clean(el.getAttribute('role')),
    name: clean(el.getAttribute('name')),
    id: clean(el.id),
    placeholder: clean(el.getAttribute('placeholder')),
    ariaLabel: clean(el.getAttribute('aria-label')),
    ariaLabelledby: clean(el.getAttribute('aria-labelledby')),
    autocomplete: clean(el.getAttribute('autocomplete')),
    associatedLabel: label,
    value: clean(el.value),
    text: clean(el.innerText || el.textContent).slice(0, 500),
    context,
    disabled: !!el.disabled,
    readOnly: !!el.readOnly,
    required: !!el.required || el.getAttribute('aria-required') === 'true',
    contentEditable: !!el.isContentEditable,
    visible:
      style.display !== 'none' &&
      style.visibility !== 'hidden' &&
      style.opacity !== '0' &&
      rect.width > 0 && rect.height > 0,
    width: rect.width,
    height: rect.height
  };
}
"""

SUMMARY_JS = r"""
() => {
  const clean = v => String(v || '').replace(/\s+/g, ' ').trim();
  const body = clean(document.body?.innerText || document.body?.textContent);
  const forms = Array.from(document.querySelectorAll('form')).map((f, i) => ({
    index: i,
    action: f.getAttribute('action') || '',
    method: f.getAttribute('method') || '',
    text: clean(f.innerText || f.textContent).slice(0, 1200)
  }));
  return {
    title: document.title,
    url: location.href,
    bodyText: body.slice(0, 5000),
    formCount: forms.length,
    forms
  };
}
"""

SHADOW_JS = r"""
() => {
  const clean = v => String(v || '').replace(/\s+/g, ' ').trim();
  const out = [];
  const seen = new Set();

  const inspect = (root, path) => {
    if (!root || !root.querySelectorAll) return;
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) inspect(el.shadowRoot, `${path}${el.tagName.toLowerCase()} >>> `);

      if (el.matches?.(
        'input,textarea,select,button,[role="textbox"],[role="combobox"],' +
        '[role="radio"],[role="checkbox"],[contenteditable="true"]'
      )) {
        const key = `${path}|${el.tagName}|${el.id}|${el.getAttribute('name')}|${el.getAttribute('role')}`;
        if (seen.has(key)) continue;
        seen.add(key);

        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        out.push({
          shadowPath: path,
          tag: (el.tagName || '').toLowerCase(),
          type: clean(el.getAttribute('type')).toLowerCase(),
          role: clean(el.getAttribute('role')),
          name: clean(el.getAttribute('name')),
          id: clean(el.id),
          placeholder: clean(el.getAttribute('placeholder')),
          ariaLabel: clean(el.getAttribute('aria-label')),
          visible: s.display !== 'none' && s.visibility !== 'hidden' &&
                   s.opacity !== '0' && r.width > 0 && r.height > 0,
          width: r.width,
          height: r.height
        });
      }
    }
  };

  inspect(document, 'document >>> ');
  return out;
}
"""

async def inspect_frame(frame: Frame):
    result = {"url": frame.url, "name": frame.name, "main": frame.parent_frame is None,
              "selectors": {}, "shadow": [], "summary": None}

    try:
        result["summary"] = await frame.evaluate(SUMMARY_JS)
    except Exception as exc:
        result["summary_error"] = f"{type(exc).__name__}: {exc}"

    for name, selector in SELECTORS.items():
        data = {"selector": selector, "count": 0, "visible": 0, "elements": []}
        try:
            loc = frame.locator(selector)
            count = await loc.count()
            data["count"] = count
            for i in range(min(count, 100)):
                meta = await loc.nth(i).evaluate(META_JS)
                if meta.get("visible"):
                    data["visible"] += 1
                data["elements"].append(meta)
        except Exception as exc:
            data["error"] = f"{type(exc).__name__}: {exc}"
        result["selectors"][name] = data

    try:
        result["shadow"] = await frame.evaluate(SHADOW_JS)
    except Exception as exc:
        result["shadow_error"] = f"{type(exc).__name__}: {exc}"

    return result

def print_result(page_index, title, url, frames):
    print("\n" + "#" * 100)
    print(f"PAGE {page_index} | {title}")
    print(url)
    for fi, fr in enumerate(frames):
        print("\n" + "=" * 90)
        print(f"FRAME {fi} | main={fr.get('main')} | url={fr.get('url')}")
        for key in ["input", "textarea", "select", "contenteditable", "textbox",
                    "combobox", "radio", "checkbox"]:
            d = fr["selectors"].get(key, {})
            print(f"[{key}] total={d.get('count',0)} visible={d.get('visible',0)}")
            for meta in d.get("elements", [])[:30]:
                print(
                    f"  tag={meta.get('tag')!r} type={meta.get('type')!r} "
                    f"role={meta.get('role')!r} name={meta.get('name')!r} "
                    f"id={meta.get('id')!r}"
                )
                print(
                    f"     label={meta.get('associatedLabel')!r} "
                    f"aria={meta.get('ariaLabel')!r} "
                    f"placeholder={meta.get('placeholder')!r}"
                )
                print(
                    f"     visible={meta.get('visible')} disabled={meta.get('disabled')} "
                    f"readonly={meta.get('readOnly')} required={meta.get('required')}"
                )
                print(f"     context={meta.get('context')!r}")
        if fr.get("shadow"):
            print(f"[shadow-dom] relevant elements={len(fr['shadow'])}")
            for meta in fr["shadow"][:50]:
                print(
                    f"  path={meta.get('shadowPath')!r} "
                    f"tag={meta.get('tag')!r} type={meta.get('type')!r} "
                    f"role={meta.get('role')!r} label={meta.get('ariaLabel')!r} "
                    f"placeholder={meta.get('placeholder')!r} visible={meta.get('visible')}"
                )
        summary = fr.get("summary") or {}
        if summary:
            print(f"[BODY] {summary.get('bodyText','')[:2500]!r}")
            print(f"[FORMS] {summary.get('formCount',0)}")
            for form in summary.get("forms", [])[:20]:
                print(f"  form[{form['index']}] {form['text']!r}")

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cdp-url", default=DEFAULT_CDP)
    ap.add_argument("--out", default="debug-evidence/smartapply-forensics.json")
    args = ap.parse_args()

    out = Path(args.out)
    if not out.is_absolute():
        out = Path.cwd() / out
    out.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cdp_url": args.cdp_url,
        "pages": []
    }

    async with async_playwright() as p:
        print(f"Connecting to {args.cdp_url}")
        browser = await p.chromium.connect_over_cdp(args.cdp_url, timeout=15000)

        for ci, context in enumerate(browser.contexts):
            print(f"context {ci}: {len(context.pages)} pages")
            for pi, page in enumerate(context.pages):
                try:
                    title = await page.title()
                except Exception:
                    title = ""
                frames = []
                for frame in page.frames:
                    frames.append(await inspect_frame(frame))
                report["pages"].append({
                    "context": ci,
                    "page": pi,
                    "title": title,
                    "url": page.url,
                    "frames": frames
                })
                print_result(pi, title, page.url, frames)

        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print("\nDONE")
        print(f"Evidence: {out}")
        print("READ-ONLY: no clicks/fills/submits were performed.")
        await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
