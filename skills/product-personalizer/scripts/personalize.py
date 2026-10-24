#!/usr/bin/env python3
"""Drive a product page's personalizer in headless Chromium and capture the preview.

Two modes:
  probe  Open the page, dismiss pop-ups, screenshot it, and list the personalization
         form's fields (inputs, uploads, radios, swatches, selects, buttons, canvases).
  run    Execute an action plan (JSON) written from the probe: fill text, upload a photo,
         choose options, wait for the preview, and capture it.

Usage:
  python3 personalize.py probe --url URL [--out DIR]
  python3 personalize.py run --plan plan.json

Safety: never adds to cart, checks out, logs in or submits payment details. Clicks on
elements whose text looks like a purchase action are refused.
"""
import argparse
import base64
import json
import os
import re
import sys
import time

FORBIDDEN = re.compile(r"add to cart|add to bag|buy now|checkout|check out|place order|pay now|"
                       r"subscribe|sign up|log ?in|sign in|apple pay|google pay|paypal|shop pay", re.I)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def out(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    sys.exit(code)


def fail(message, code=2, **extra):
    out({"ok": False, "error": message, **extra}, code)


def launch():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        fail("Playwright missing: run bash /mnt/skills/product-personalizer/scripts/ensure-deps.sh first")
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(args=["--disable-blink-features=AutomationControlled"])
    except Exception as error:
        pw.stop()
        fail(f"Chromium failed to start: {str(error)[:400]}. Run ensure-deps.sh.")
    context = browser.new_context(viewport={"width": 1280, "height": 1600}, user_agent=UA,
                                  locale="en-US", device_scale_factor=1)
    page = context.new_page()
    page.set_default_timeout(15000)
    return pw, browser, page


def open_page(page, url):
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1")):
        fail("--url must start with https://")
    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    status = response.status if response else None
    if status == 429:
        fail("The site answered 429 Too Many Requests. Stop and wait several minutes; do not retry in a loop.", 1)
    if status and status >= 400:
        fail(f"Page returned HTTP {status}", 1)
    try:
        page.wait_for_load_state("networkidle", timeout=20000)
    except Exception:
        pass  # busy pages never go fully idle; continue with what has loaded
    page.wait_for_timeout(2000)
    dismiss_popups(page)
    return status


def dismiss_popups(page):
    """Best effort: close newsletter/discount/cookie overlays without accepting anything paid."""
    closed = []
    for _ in range(2):
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    candidates = page.locator("[aria-label*='close' i], [aria-label*='dismiss' i], button[class*='close' i], "
                              "[class*='popup' i] [class*='close' i], [class*='modal' i] [class*='close' i]")
    for i in range(min(candidates.count(), 10)):
        el = candidates.nth(i)
        try:
            if el.is_visible():
                text = (el.inner_text(timeout=500) or "").strip()
                if FORBIDDEN.search(text):
                    continue
                el.click(timeout=1500)
                closed.append(text or el.get_attribute("aria-label") or "close")
                page.wait_for_timeout(400)
        except Exception:
            continue
    return closed


PROBE_JS = r"""
() => {
  const vis = el => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const css = el => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = []; let e = el;
    while (e && e.nodeType === 1 && parts.length < 5) {
      let p = e.tagName.toLowerCase();
      if (e.classList.length) p += '.' + [...e.classList].slice(0, 2).map(c => CSS.escape(c)).join('.');
      const sib = e.parentElement ? [...e.parentElement.children].filter(x => x.tagName === e.tagName) : [];
      if (sib.length > 1) p += `:nth-of-type(${sib.indexOf(e) + 1})`;
      parts.unshift(p); e = e.parentElement;
    }
    return parts.join(' > ');
  };
  const labelFor = el => {
    if (el.id) { const l = document.querySelector(`label[for="${CSS.escape(el.id)}"]`); if (l) return l.innerText.trim(); }
    const l = el.closest('label'); if (l) return l.innerText.trim().slice(0, 120);
    const box = el.closest('.ant-form-item, .form-group, .field, [class*="option"], [class*="field"]');
    if (box) { const t = box.querySelector('label, .ant-form-item-label, legend, [class*="label"]'); if (t) return t.innerText.trim().slice(0, 120); }
    return '';
  };
  const forms = [...document.querySelectorAll('form')].map(f => ({selector: css(f), classes: f.className, fields: f.querySelectorAll('input, select, textarea').length}));
  const inputs = [...document.querySelectorAll('input, textarea, select')].filter(el => el.type !== 'hidden' || el.type === 'file').map(el => ({
    tag: el.tagName.toLowerCase(), type: el.type || '', name: el.name || '', id: el.id || '',
    placeholder: el.placeholder || '', maxlength: el.maxLength > 0 ? el.maxLength : null,
    accept: el.accept || '', value: el.type === 'radio' || el.type === 'checkbox' ? el.value : '',
    checked: !!el.checked, visible: vis(el), label: labelFor(el), selector: css(el),
    options: el.tagName === 'SELECT' ? [...el.options].map(o => o.text.trim()).slice(0, 30) : undefined,
  })).filter(x => !/search|email|newsletter|quantity|qty/i.test(x.name + x.placeholder + x.id));
  const radios = {};
  inputs.filter(x => x.type === 'radio').forEach(r => { (radios[r.name] = radios[r.name] || []).push({value: r.value, label: r.label, checked: r.checked, selector: r.selector}); });
  // Option tile groups: prefer real .swatch-container blocks inside the personalization form, in page order.
  const pform = document.querySelector('form.personalized-form') || document;
  let groups = [...pform.querySelectorAll('.swatch-container')];
  if (!groups.length) groups = [...document.querySelectorAll('.swatch-container, [class*="swatch"]')];
  const swatches = groups.slice(0, 12).map((c, gi) => {
    const box = c.closest('.ant-form-item, .form-group, [class*="field"]');
    const lab = box ? box.querySelector('label, .ant-form-item-label') : null;
    const tiles = [...c.children].filter(vis);
    return {group_index: gi, label: lab ? lab.innerText.trim().slice(0, 60) : '', container: css(c), tile_count: tiles.length,
      tile_selector_pattern: `div.swatch-container >> nth=${gi} >> div:nth-of-type(N)`,
      items: tiles.slice(0, 20).map((x, ti) => { const img = x.querySelector('img'); return {n: ti + 1,
        title: x.getAttribute('title') || x.getAttribute('aria-label') || (img && (img.alt || '')) || '',
        image: img ? (img.currentSrc || img.src || '').slice(0, 160) : '',
        background: getComputedStyle(x.querySelector('*') || x).backgroundColor, active: /active|selected|checked/.test(x.innerHTML.slice(0, 400)) }; }) };
  });
  const buttons = [...document.querySelectorAll('button, [role="button"], .ant-btn, a[class*="btn" i], div[class*="btn" i], span[class*="btn" i]')].filter(vis).map(b => ({text: b.innerText.trim().replace(/\s+/g, ' ').slice(0, 60), selector: css(b)})).filter(b => b.text && b.text.length < 40).slice(0, 80);
  const preview_controls = [...document.querySelectorAll('body *')].filter(e => vis(e) && e.children.length <= 2 && /^\s*preview\s*$/i.test(e.innerText || '')).slice(0, 5).map(e => ({tag: e.tagName.toLowerCase(), selector: css(e), hint: "use selector 'text=Preview >> visible=true'"}));
  const ant_selects = [...pform.querySelectorAll('.ant-select')].filter(vis).map(e => {
    const box = e.closest('.ant-form-item'); const lab = box ? box.querySelector('label, .ant-form-item-label') : null;
    return {label: lab ? lab.innerText.trim().slice(0, 60) : '', selector: css(e), open_with: css(e) + ' .ant-select-selector'}; });
  const canvases = [...document.querySelectorAll('canvas')].map(c => ({selector: css(c), classes: c.className, width: c.width, height: c.height, visible: vis(c)}));
  const prices = [...document.querySelectorAll('[class*="price" i]')].filter(vis).map(p => p.innerText.trim().replace(/\s+/g, ' ')).filter(t => /\d/.test(t)).slice(0, 8);
  const h1 = document.querySelector('h1');
  const gallery = [...document.querySelectorAll('[class*="gallery" i] img, [class*="product-media" i] img, [class*="product__media" i] img, [class*="thumbnail" i] img, [class*="slider" i] img, .product-single__photo img, [class*="carousel" i] img')]
    .map(i => (i.currentSrc || i.src || i.getAttribute('data-src') || '').replace(/(_\d+x\d*)?(\.(jpg|jpeg|png|webp))/i, '$2'))
    .filter(u => /^https?:/.test(u) && !/logo|icon|flag|payment|badge/i.test(u))
    .filter((u, i, a) => a.indexOf(u) === i).slice(0, 12);
  const guide = [...document.querySelectorAll('a, button, span, div')].filter(e => vis(e) && /photo guide/i.test(e.innerText || '') && (e.innerText || '').length < 40).slice(0, 2).map(e => ({selector: css(e), text: e.innerText.trim()}));
  return {title: document.title, product_name: h1 ? h1.innerText.trim() : '', prices, forms, inputs, radio_groups: radios, swatches, ant_selects, preview_controls, buttons, canvases, gallery_images: gallery, photo_guide_controls: guide};
}
"""


def probe(args):
    os.makedirs(args.out, exist_ok=True)
    pw, browser, page = launch()
    try:
        status = open_page(page, args.url)
        info = page.evaluate(PROBE_JS)
        # Custom (Ant Design) dropdowns render their options only when opened: open each, read, close.
        for sel in info.get("ant_selects", []):
            try:
                page.locator(sel["open_with"]).first.click(timeout=5000)
                page.wait_for_timeout(700)
                sel["options"] = [t.strip() for t in page.locator(".ant-select-dropdown:visible .ant-select-item-option-content").all_inner_texts()]
                page.keyboard.press("Escape")
                page.wait_for_timeout(300)
            except Exception as error:
                sel["options_error"] = str(error)[:200]
        # Product gallery images: material / pattern / lifestyle photos used later as Seedance texture references.
        info["gallery_files"] = []
        for i, url in enumerate(info.get("gallery_images", [])[:8], 1):
            try:
                resp = page.request.get(url, timeout=20000)
                if resp.ok and resp.headers.get("content-type", "").startswith("image/"):
                    ext = ".png" if "png" in resp.headers.get("content-type", "") else ".jpg"
                    dest = os.path.join(args.out, f"gallery_{i:02d}{ext}")
                    with open(dest, "wb") as fh:
                        fh.write(resp.body())
                    info["gallery_files"].append({"file": dest, "url": url})
            except Exception as error:
                info.setdefault("gallery_errors", []).append(str(error)[:120])
        # Photo guide (photo-upload products): open it, keep its text and a screenshot, close it.
        info["photo_guide"] = None
        for ctrl in info.get("photo_guide_controls", []):
            try:
                page.locator(ctrl["selector"]).first.click(timeout=4000)
                page.wait_for_timeout(1200)
                dialog = page.locator("[role='dialog'], .ant-modal, [class*='modal' i]").filter(has_text="").first
                shot = os.path.join(args.out, "probe_photo_guide.png")
                try:
                    dialog.screenshot(path=shot, timeout=4000)
                    text = dialog.inner_text(timeout=2000)
                except Exception:
                    page.screenshot(path=shot)
                    text = ""
                info["photo_guide"] = {"screenshot": shot, "text": text.strip()[:1500]}
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                dismiss_popups(page)
                break
            except Exception as error:
                info["photo_guide"] = {"error": str(error)[:160]}
        shots = {"page_top": os.path.join(args.out, "probe_page_top.png"),
                 "page_full": os.path.join(args.out, "probe_page_full.png")}
        page.screenshot(path=shots["page_top"])
        page.screenshot(path=shots["page_full"], full_page=True)
        form_shot = None
        for sel in ["form.personalized-form", "form[class*='personal' i]", "[class*='personaliz' i] form", "form[action*='cart']"]:
            loc = page.locator(sel)
            if loc.count() and loc.first.is_visible():
                form_shot = os.path.join(args.out, "probe_form.png")
                loc.first.screenshot(path=form_shot)
                info["personalization_form_selector"] = sel
                break
        result = {"ok": True, "url": args.url, "http_status": status, **info,
                  "screenshots": {**shots, "form": form_shot}}
        path = os.path.join(args.out, "probe.json")
        with open(path, "w") as fh:
            json.dump(result, fh, indent=2, ensure_ascii=False)
        summary = {k: result[k] for k in ("ok", "url", "http_status", "title", "product_name", "prices")}
        summary.update({"probe_json": path, "screenshots": result["screenshots"],
                        "counts": {"inputs": len(info["inputs"]), "radio_groups": len(info["radio_groups"]),
                                   "swatch_groups": len(info["swatches"]), "canvases": len(info["canvases"])},
                        "option_groups": [{"label": g["label"], "tiles": g["tile_count"], "pattern": g["tile_selector_pattern"]} for g in info["swatches"]],
                        "dropdowns": [{"label": d["label"], "open_with": d["open_with"], "options": d.get("options")} for d in info["ant_selects"]],
                        "preview_controls": info["preview_controls"],
                        "gallery_files": [g["file"] for g in info.get("gallery_files", [])],
                        "photo_guide": info.get("photo_guide"),
                        "next": "Look at the screenshots, the gallery files and the photo guide, then write an action plan (see references/action_plan.md)."})
        out(summary)
    finally:
        browser.close()
        pw.stop()


def guard_click(page, selector):
    el = page.locator(selector).first
    text = ""
    try:
        text = (el.inner_text(timeout=1000) or "") + " " + (el.get_attribute("value") or "") + " " + (el.get_attribute("aria-label") or "")
    except Exception:
        pass
    if FORBIDDEN.search(text) or FORBIDDEN.search(selector):
        fail(f"Refused to click a purchase/account control: {selector!r} ({text.strip()[:60]!r})")
    return el


CLICK_CAP_MS = 20000   # an element that is there is clickable within seconds; long timeouts only waste minutes
CONFIRM_TEXT = re.compile(r"^\s*(apply|done|save|confirm|ok|crop|use (this )?photo|continue)\s*$", re.I)
SELECTED_JS = r"""
(el) => {
  const hit = (e) => {
    const c = (typeof e.className === 'string' ? e.className : '') || '';
    return /(^|[\s_-])(active|selected|checked)($|[\s_-])/i.test(c) || ['aria-checked', 'aria-selected', 'aria-pressed'].some(a => e.getAttribute && e.getAttribute(a) === 'true')
      || (e.matches && e.matches('input:checked'));
  };
  if (hit(el) || [...el.querySelectorAll('*')].slice(0, 40).some(hit)) return true;
  // a small inner element (text span) whose tile/pill carries the state: up to 2 ancestors of similar size
  const r = el.getBoundingClientRect(); let p = el.parentElement;
  for (let i = 0; i < 2 && p; i++, p = p.parentElement) {
    const q = p.getBoundingClientRect();
    if (q.width * q.height > 4 * Math.max(1, r.width * r.height)) break;
    if (hit(p)) return true;
  }
  return false;
}
"""
# A photo editor/crop dialog opened by an upload: a confirm button (Apply, Done, ...) on top of the page, inside a box
# about the photo, never inside anything that offers Add to cart. The button is marked so Python can click it.
EDITOR_JS = r"""
(pattern) => {
  const re = new RegExp(pattern, 'i');
  document.querySelectorAll('[data-pz-confirm]').forEach(e => e.removeAttribute('data-pz-confirm'));
  for (const b of document.querySelectorAll('button, [role="button"], a, div, span')) {
    const t = (b.innerText || '').trim();
    if (!t || t.length > 20 || !re.test(t) || b.querySelector('button')) continue;
    const r = b.getBoundingClientRect();
    if (r.width < 20 || r.height < 14) continue;
    const top = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
    if (!top || !(top === b || b.contains(top) || top.contains(b))) continue;
    let p = b.parentElement, about = false;
    for (let i = 0; i < 7 && p; i++, p = p.parentElement) {
      const pt = p.innerText || '';
      if (/add to cart|checkout|buy now/i.test(pt)) break;  // reached the page (or a purchase dialog) first: not an editor
      if (/edit photo|crop|adjust|edit image|replace photo/i.test(pt)) { about = true; break; }
    }
    if (about) { b.setAttribute('data-pz-confirm', '1'); return t; }
  }
  return null;
}
"""


def norm_selector(sel):
    """Fix common slips in hand-written selectors (Python-style booleans in Playwright pseudo-selectors)."""
    if not sel:
        return sel
    return re.sub(r"(visible\s*=\s*)(True|TRUE|False|FALSE)\b", lambda m: m.group(1) + m.group(2).lower(), sel)


def confirm_photo_editor(page, wait_ms=0):
    """Confirm a photo-editor dialog (Apply/Done) if one is open. Returns the button text, or None if there is none."""
    deadline = time.time() + wait_ms / 1000
    while True:
        try:
            text = page.evaluate(EDITOR_JS, CONFIRM_TEXT.pattern)
        except Exception:
            text = None
        if text and not FORBIDDEN.search(text):
            try:
                page.locator("[data-pz-confirm='1']").first.click(timeout=5000)
                page.wait_for_timeout(1500)
                return text
            except Exception:
                pass
        if time.time() >= deadline:
            return None
        page.wait_for_timeout(500)


def is_selected(loc):
    try:
        return bool(loc.evaluate(SELECTED_JS))
    except Exception:
        return None


def text_of_selector(sel):
    m = re.match(r"\s*text\s*=\s*[\"']?(.+?)[\"']?\s*(>>|$)", sel or "")
    return m.group(1).strip() if m else None


def click_target(page, step):
    """The locator a click/click_text step points at."""
    if step.get("action") == "click_text":
        scope = page.locator(norm_selector(step["selector"])).first if step.get("selector") else page
        return scope.get_by_text(step["text"], exact=step.get("exact", True)).first
    return guard_click(page, norm_selector(step["selector"]))


def alternatives(page, step):
    """Other ways to find the same control when the first locator does not resolve (text controls only)."""
    text = step.get("text") if step.get("action") == "click_text" else text_of_selector(step.get("selector"))
    if not text:
        return []
    return [page.get_by_role("button", name=text, exact=True).first, page.get_by_role("link", name=text, exact=True).first,
            page.get_by_text(text, exact=True).locator("visible=true").first,
            page.get_by_text(text, exact=False).locator("visible=true").first]


def do_click(page, step, timeout_ms):
    el = click_target(page, step)
    el.wait_for(state="attached", timeout=min(timeout_ms, 8000))  # a selector that matches nothing fails in seconds
    el.scroll_into_view_if_needed(timeout=timeout_ms)
    el.click(timeout=timeout_ms)
    return el


def close_preview_dialog(page):
    """Close the site's preview dialog via its Close control or Escape, never its Add to cart button."""
    for cand in ["[role='dialog']:visible button:has-text('Close')", "[class*='modal' i]:visible button:has-text('Close')",
                 ".ant-modal-close:visible", "[aria-label='Close']:visible", "text=Close >> visible=true"]:
        try:
            el = page.locator(cand).first
            if el.is_visible(timeout=800):
                guard_click(page, cand)
                el.click(timeout=3000)
                page.wait_for_timeout(500)
                return True
        except Exception:
            continue
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return False


def capture(page, step, out_dir):
    """Save the preview. Order: canvas export (works even when a dialog covers the canvas), element screenshot,
    element screenshot after closing a covering dialog, then a viewport screenshot (flagged so the agent checks it)."""
    target = norm_selector(step.get("selector"))
    path = os.path.join(out_dir, step.get("file", "preview.png"))
    loc = page.locator(target).first
    notes = []
    try:
        loc.wait_for(state="attached", timeout=min(int(step.get("timeout_ms", 15000)), CLICK_CAP_MS))
    except Exception as error:
        notes.append(f"not found: {str(error)[:120]}")
    if not notes and step.get("method", "auto") in ("auto", "canvas"):
        try:
            if loc.evaluate("e => e.tagName") == "CANVAS":
                data = base64.b64decode(loc.evaluate("c => c.toDataURL('image/png')").split(",", 1)[1])
                if len(data) > 3000:  # an empty canvas encodes to a few hundred bytes
                    with open(path, "wb") as fh:
                        fh.write(data)
                    return {"file": path, "method": "canvas_export"}
                notes.append("canvas is empty")
        except Exception as error:
            notes.append(f"canvas export: {str(error)[:120]}")  # tainted canvas (cross-origin images)
    for attempt in range(2):
        try:
            loc.screenshot(path=path, timeout=8000)
            return {"file": path, "method": "element_screenshot", **({"notes": notes} if notes else {})}
        except Exception as error:
            notes.append(f"element screenshot: {str(error)[:120]}")
            if attempt == 0:
                close_preview_dialog(page)
    page.screenshot(path=path)
    return {"file": path, "method": "viewport_fallback", "notes": notes,
            "warning": "The preview element could not be captured; this is a viewport screenshot. Open it and crop if usable."}


def is_option_step(step):
    """Clicks that choose a product option (tile, pill, swatch): verified after the click and re-checked later."""
    if "option" in step:
        return bool(step["option"])
    if step.get("action") not in ("click", "click_text"):
        return False
    label = (step.get("text") or text_of_selector(step.get("selector")) or step.get("selector") or "")
    return not re.search(r"preview|close|apply|done|save|confirm|cancel|edit|ok\b|continue|crop", label, re.I)


def reassert_options(page, options, log_entry):
    """Re-click any chosen option the page has since reset (an upload can reset the background, for example)."""
    for opt in options:
        if opt["selected"] is not True:
            continue  # state not readable on this site: nothing to compare
        try:
            loc = click_target(page, opt["step"])
            if is_selected(loc) is False:
                loc.scroll_into_view_if_needed(timeout=8000)
                loc.click(timeout=8000)
                page.wait_for_timeout(1500)
                opt["reapplied"] = opt.get("reapplied", 0) + 1
                log_entry.setdefault("reapplied_options", []).append(opt["label"])
                if is_selected(loc) is False:
                    opt["selected"] = False
        except SystemExit:
            raise
        except Exception as error:
            log_entry.setdefault("notes", []).append(f"recheck {opt['label']}: {str(error)[:100]}")


def run(args):
    try:
        with open(args.plan) as fh:
            plan = json.load(fh)
    except (OSError, json.JSONDecodeError) as error:
        fail(f"Cannot read plan: {error}")
    url, steps = plan.get("url"), plan.get("steps")
    out_dir = plan.get("out", "/mnt/session/outputs/personalizer")
    if not url or not isinstance(steps, list) or not steps:
        fail("Plan needs 'url' and a non-empty 'steps' list")
    for i, step in enumerate(steps):
        if step.get("action") == "upload" and not os.path.isfile(step.get("file", "")):
            fail(f"steps[{i}]: upload file not found: {step.get('file')}")
    os.makedirs(out_dir, exist_ok=True)
    pw, browser, page = launch()
    log, captures, options = [], [], []
    editor_pending = False  # an upload happened and its photo editor (if the site has one) is not confirmed yet
    run_started = time.time()
    try:
        status = open_page(page, url)
        for i, step in enumerate(steps):
            action, sel = step.get("action"), norm_selector(step.get("selector"))
            interactive = action in ("fill", "click", "click_text", "select", "capture", "capture_dialog", "screenshot")
            limit = min(int(step.get("timeout_ms", 15000)), CLICK_CAP_MS) if interactive else int(step.get("timeout_ms", 30000))
            page.set_default_timeout(limit)
            started = time.time()
            entry = {"step": i + 1, "action": action, "ok": True}
            label = step.get("text") or text_of_selector(sel) or sel or ""
            try:
                if interactive:
                    confirmed = confirm_photo_editor(page)  # a photo editor left open blocks every other control
                    if confirmed:
                        entry["auto_confirmed_editor"] = confirmed
                        editor_pending = False
                if action in ("click", "click_text") and CONFIRM_TEXT.match(label):
                    # the plan's own "Apply"/"Done" for a photo editor: wait for it; fine if it was already confirmed
                    text = entry.get("auto_confirmed_editor") or (
                        confirm_photo_editor(page, wait_ms=min(int(step.get("timeout_ms", 15000)), CLICK_CAP_MS)) if editor_pending else None)
                    entry["confirmed_editor"] = text or "no editor dialog open (already confirmed)"
                    editor_pending = False
                elif action == "confirm_editor":
                    entry["confirmed_editor"] = confirm_photo_editor(page, wait_ms=int(step.get("timeout_ms", 15000)) if editor_pending else 0) or "no editor dialog open"
                    editor_pending = False
                elif action == "fill":
                    loc = page.locator(sel).first
                    loc.scroll_into_view_if_needed()
                    loc.fill(str(step["value"]))
                    loc.press("Tab")
                elif action == "upload":
                    page.locator(sel).first.set_input_files(step["file"])
                    editor_pending = True
                elif action in ("click", "click_text"):
                    if action == "click_text" and FORBIDDEN.search(step["text"]):
                        fail(f"Refused to click purchase/account text {step['text']!r}")
                    if re.search(r"preview", label, re.I):
                        reassert_options(page, options, entry)  # the preview must show every chosen option
                    before = [(o, is_selected(click_target(page, o["step"]))) for o in options] if is_option_step(step) else []
                    try:
                        el = do_click(page, {**step, "selector": sel}, limit)
                    except SystemExit:
                        raise
                    except Exception as first_error:
                        # one recovery: confirm a photo editor, close overlays, then try the same control another way
                        entry["recovered_from"] = str(first_error).split("\n")[0][:160]
                        confirm_photo_editor(page)
                        dismiss_popups(page)
                        el = None
                        for alt in [click_target(page, {**step, "selector": sel})] + alternatives(page, step):
                            try:
                                if alt.is_visible(timeout=2000):
                                    txt = (alt.inner_text(timeout=1000) or "")
                                    if FORBIDDEN.search(txt):
                                        continue
                                    alt.scroll_into_view_if_needed(timeout=5000)
                                    alt.click(timeout=5000)
                                    el = alt
                                    break
                            except Exception:
                                continue
                        if el is None:
                            raise first_error
                    if is_option_step(step):
                        state = None
                        for _ in range(4):  # the selected mark can take a moment to appear
                            page.wait_for_timeout(400)
                            state = is_selected(el)
                            if state:
                                break
                        if state is False and not any(o["selected"] is True for o in options):
                            state = None  # no option on this page has shown a readable selected state yet: unknown
                        # an earlier choice this click deselected (another tile of the same group) is replaced, not lost
                        replaced = [o for o, was in before if was is True and is_selected(click_target(page, o["step"])) is False]
                        if replaced:
                            options[:] = [o for o in options if o not in replaced]
                            entry["replaces"] = [o["label"] for o in replaced]
                        options.append({"label": label[:60], "step": {**step, "selector": sel}, "selected": state})
                        entry["selected"] = state
                elif action == "select":
                    page.locator(sel).first.select_option(label=step["label"])
                elif action == "wait":
                    page.wait_for_timeout(min(int(step.get("ms", 1000)), 90000))
                elif action == "wait_for":
                    page.locator(sel).first.wait_for(state=step.get("state", "visible"), timeout=step.get("timeout_ms", 60000))
                elif action == "wait_text_gone":
                    notice = page.get_by_text(step["text"]).first
                    try:  # the notice can appear a moment after the upload: wait for it first, briefly
                        notice.wait_for(state="visible", timeout=int(step.get("appear_ms", 4000)))
                    except Exception:
                        entry["note"] = "text never appeared"
                    notice.wait_for(state="hidden", timeout=step.get("timeout_ms", 90000))
                elif action == "dismiss_popups":
                    dismiss_popups(page)
                elif action == "capture_dialog":
                    captures.append(capture_dialog(page, step, sel, out_dir, i))
                elif action == "close_dialog":
                    close_preview_dialog(page)
                elif action == "capture":
                    reassert_options(page, options, entry)
                    captures.append(capture(page, {**step, "selector": sel}, out_dir))
                elif action == "screenshot":
                    path = os.path.join(out_dir, step.get("file", f"step_{i + 1:02d}.png"))
                    (page.locator(sel).first.screenshot(path=path) if sel else page.screenshot(path=path, full_page=step.get("full_page", False)))
                    captures.append({"file": path, "method": "screenshot"})
                else:
                    fail(f"steps[{i}]: unknown action {action!r}")
            except SystemExit:
                raise
            except Exception as error:
                shot = os.path.join(out_dir, f"error_step_{i + 1:02d}.png")
                try:
                    page.screenshot(path=shot)
                except Exception:
                    shot = None
                if step.get("optional"):
                    entry.update({"ok": False, "skipped": True, "error": str(error).split("\n")[0][:200], "screenshot": shot})
                else:
                    log.append({**entry, "ok": False, "error": str(error)[:400], "screenshot": shot,
                                "seconds": round(time.time() - started, 1)})
                    out({"ok": False, "url": url, "http_status": status, "failed_step": i + 1, "log": log, "captures": captures,
                         "options": option_report(options), "seconds": round(time.time() - run_started, 1),
                         "hint": "Look at the error screenshot, fix that step (or mark it \"optional\": true) and rerun the whole plan."}, 1)
            entry["seconds"] = round(time.time() - started, 1)
            if step.get("snapshot"):
                snap = os.path.join(out_dir, f"after_step_{i + 1:02d}.png")
                page.screenshot(path=snap)
                entry["screenshot"] = snap
            log.append(entry)
        report = option_report(options)
        lost = [o["label"] for o in report if o["selected"] is False]
        out({"ok": True, "url": url, "http_status": status, "seconds": round(time.time() - run_started, 1),
             "log": log, "captures": captures, "options": report,
             **({"warning": f"These options did not stay selected: {lost}. Check the captures before using them."} if lost else {}),
             "next": "Open every captured image and confirm the personalization (name, photo, options) is visible and correct."})
    finally:
        browser.close()
        pw.stop()


def option_report(options):
    return [{"label": o["label"], "selected": o["selected"], **({"reapplied": o["reapplied"]} if o.get("reapplied") else {})}
            for o in options]


def capture_dialog(page, step, sel, out_dir, i):
    """Screenshot of the site's preview dialog ("Looks Good to Go?"), used for the options montage.
    First choice: the smallest visible box that holds the dialog heading AND its Close/Add to cart controls (the card,
    not the canvas behind it nor the full-screen overlay). Fallback: the visible dialog element."""
    path = os.path.join(out_dir, step.get("file", f"dialog_{i + 1:02d}.png"))
    heading = step.get("text") or "Looks Good"
    deadline = time.time() + min(int(step.get("timeout_ms", 15000)), CLICK_CAP_MS) / 1000
    rect = None
    while True:
        rect = page.evaluate("""(h) => {
            const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el);
                return r.width > 200 && r.height > 250 && cs.visibility !== 'hidden' && cs.display !== 'none' && cs.opacity !== '0'; };
            let best = null;
            for (const el of document.querySelectorAll('div, section, aside, dialog')) {
                const t = el.innerText || '';
                if (!t.includes(h) || !(/Close/i.test(t) || /Add to cart/i.test(t)) || !vis(el)) continue;
                const r = el.getBoundingClientRect();
                if (r.width >= window.innerWidth * 0.98 && r.height >= window.innerHeight * 0.98) continue;  // overlay
                if (!best || r.width * r.height < best.w * best.h) best = {x: r.left, y: r.top, w: r.width, h: r.height};
            }
            return best; }""", heading)
        if rect or time.time() >= deadline:
            break
        page.wait_for_timeout(500)
    if rect:
        page.wait_for_timeout(int(step.get("settle_ms", 800)))  # let the dialog's image finish drawing
        page.screenshot(path=path, clip={"x": max(0, rect["x"]), "y": max(0, rect["y"]), "width": rect["w"], "height": rect["h"]})
        return {"file": path, "method": "dialog_card", "box": rect}
    # Visible dialogs only: the page keeps hidden modal containers (div.content-modal) that match first otherwise.
    default_sel = "[role='dialog']:visible, .ant-modal-content:visible, [class*='modal' i][class*='content' i]:visible, [class*='modal' i]:visible"
    dialog = page.locator(sel or default_sel)
    if step.get("text"):
        dialog = dialog.filter(has_text=step["text"])
    dialog = dialog.first
    dialog.wait_for(state="visible", timeout=3000)
    # The matched element is often the full-screen overlay: descend to the dialog box itself.
    vw = page.viewport_size["width"] if page.viewport_size else 1280
    box = dialog.bounding_box() or {"width": vw}
    target = dialog
    if box["width"] > 0.9 * vw:
        kids = dialog.locator(":scope > *")
        for k in range(min(kids.count(), 8)):
            kb = kids.nth(k).bounding_box()
            if kb and 0.2 * vw < kb["width"] < 0.9 * vw and kb["height"] > 100:
                target = kids.nth(k)
                break
    target.screenshot(path=path)
    return {"file": path, "method": "dialog_screenshot"}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("probe")
    p.add_argument("--url", required=True)
    p.add_argument("--out", default="/mnt/session/outputs/personalizer")
    r = sub.add_parser("run")
    r.add_argument("--plan", required=True)
    args = parser.parse_args()
    probe(args) if args.mode == "probe" else run(args)


if __name__ == "__main__":
    main()
