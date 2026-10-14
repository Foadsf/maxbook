# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Foad S. Farimani
"""Take the documentation screenshots by driving the real Maxbook and Maxima.

    python -m pip install "playwright==1.63.0" pillow
    python docs/tools/screenshots.py [--channel msedge|chrome|chromium] [--only NAME ...]

Every picture comes from the actual program: a Maxbook server is started from
this checkout (with a fresh settings folder and a demo folder, so nothing
personal shows), a browser is driven with real key strokes, and the window or
a region of it is saved as WebP in docs/modules/ROOT/images.  The demo
folder's path and network addresses are shown as neutral placeholders.
Needs Maxima (found the usual way, or MAXBOOK_MAXIMA).
"""

from __future__ import annotations

import argparse
import getpass
import io
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "modules" / "ROOT" / "images"
VIEWPORT = {"width": 1280, "height": 800}
PRETTY_DIR = r"C:\Users\you\Documents" if sys.platform == "win32" else "/home/you/Documents"
PRETTY_IPS = ["192.168.1.20", "10.0.0.15", "172.20.0.1", "172.21.0.1", "172.22.0.1", "172.23.0.1"]


class Server:
    def __init__(self, work: Path):
        self.work = work
        self.proc: subprocess.Popen | None = None
        self.base = self.token = ""
        self.links: list[str] = []

    def start(self, *args: str, share: bool = False) -> Server:
        env = dict(os.environ, MAXBOOK_HOME=str(self.work / "home"), PYTHONPATH=str(ROOT))
        env.pop("ANTHROPIC_API_KEY", None)
        env.pop("ANTHROPIC_AUTH_TOKEN", None)
        cmd = [sys.executable, "-m", "maxbook", "--window", "none", *(["--share"] if share else []), *args]
        self.proc = subprocess.Popen(cmd, cwd=self.work / "Documents", env=env, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, text=True)
        assert self.proc.stdout
        for line in self.proc.stdout:
            m = re.match(r"\s+(http://\S+#token=\S+)", line)
            if m:
                self.links.append(m.group(1))
            m = re.search(r"Open this URL: (http://127\.0\.0\.1:\d+/)#token=([\w-]+)", line)
            if m:
                self.base, self.token = m.groups()
                return self
        raise SystemExit("maxbook did not start")

    @property
    def url(self) -> str:
        return f"{self.base}#token={self.token}"

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(20)
            except subprocess.TimeoutExpired:
                self.proc.kill()


class Tour:
    def __init__(self, browser, work: Path):
        self.browser = browser
        self.work = work
        self.docs = work / "Documents"

    # ------------------------------------------------------------ browser helpers
    def page(self, url: str, *, dark: bool = False, viewport=None) -> Page:
        # bypass_csp: Maxbook's page forbids eval, which Playwright's wait helpers use
        ctx = self.browser.new_context(viewport=viewport or VIEWPORT, device_scale_factor=2,
                                       color_scheme="dark" if dark else "light", bypass_csp=True)
        page = ctx.new_page()
        page.on("dialog", lambda d: d.accept(d.default_value or "") if d.type == "prompt" else d.accept())
        page.goto(url)
        page.wait_for_selector(".mbk-doc")
        self.wait_idle(page)
        return page

    @staticmethod
    def wait_idle(page: Page, timeout: float = 120) -> None:
        page.wait_for_selector('#kernel[data-status="idle"]', timeout=timeout * 1000)

    def mask(self, page: Page) -> None:
        page.evaluate("""([dirs, pretty, fakeIps, hostRe]) => {
            const seen = (window.__mbxIps = window.__mbxIps || {});
            const fakeIp = (m) => seen[m] || (seen[m] = fakeIps[Object.keys(seen).length % fakeIps.length]);
            const host = new RegExp(hostRe, 'gi');
            const fix = (s) => {
                for (const d of dirs) s = s.split(d).join(pretty);
                s = s.replace(host, 'my-computer');
                return s.replace(/\\b(?:\\d{1,3}\\.){3}\\d{1,3}\\b/g, (m) => m.startsWith('127.') ? m : fakeIp(m));
            };
            const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            for (let n; (n = walk.nextNode());) {
                const v = fix(n.nodeValue);
                if (v !== n.nodeValue) n.nodeValue = v;
            }
            for (const el of document.querySelectorAll('input, textarea')) {
                const v = fix(el.value);
                if (v !== el.value) el.value = v;
            }
        }""", [[str(self.docs), str(self.docs.resolve())], PRETTY_DIR, PRETTY_IPS, re.escape(socket.gethostname())])

    def shot(self, page: Page, name: str, *selectors: str, pad: int = 18, settle: float = 0.35,
             full: bool = False) -> None:
        time.sleep(settle)
        self.mask(page)
        text = page.evaluate("document.body.innerText + [...document.querySelectorAll('input,textarea')]"
                             ".map(e => e.value).join(' ')")
        for secret in {socket.gethostname(), getpass.getuser()}:
            if secret and len(secret) > 2 and secret.lower() in text.lower():
                raise SystemExit(f"{name}: the page still shows {secret!r}; not saving it")
        clip = None
        if selectors:
            rects = ("els => els.map(e => { const r = e.getBoundingClientRect(); "
                     "return [r.left, r.top, r.right, r.bottom] })")
            boxes = [b for s in selectors for b in page.locator(s).evaluate_all(rects) if b[2] > b[0] and b[3] > b[1]]
            if not boxes:
                raise SystemExit(f"{name}: nothing matches {selectors}")
            vw, vh = page.viewport_size["width"], page.viewport_size["height"]
            x0 = max(0, min(b[0] for b in boxes) - pad)
            y0 = max(0, min(b[1] for b in boxes) - pad)
            x1 = min(vw, max(b[2] for b in boxes) + pad)
            y1 = min(vh, max(b[3] for b in boxes) + pad)
            clip = {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}
        png = page.screenshot(clip=clip, full_page=full)
        img = Image.open(io.BytesIO(png)).convert("RGB")
        OUT.mkdir(parents=True, exist_ok=True)
        target = OUT / f"{name}.webp"
        img.save(target, "WEBP", quality=86, method=6)
        print(f"  {target.name:34} {img.width}x{img.height}  {target.stat().st_size // 1024} kB")

    @staticmethod
    def keys(page: Page, *parts: str, delay: int = 25) -> None:
        """Type text; {Key} presses a key (ArrowRight, Escape, Shift+Enter...)."""
        for part in parts:
            for token in re.split(r"(\{[^}]+\})", part):
                if not token:
                    continue
                if token.startswith("{") and token.endswith("}"):
                    page.keyboard.press(token[1:-1])
                    time.sleep(0.08)
                else:
                    page.keyboard.type(token, delay=delay)

    @staticmethod
    def wait_math(page: Page) -> None:
        page.wait_for_function("document.activeElement && document.activeElement.tagName === 'MATH-FIELD'")
        time.sleep(0.15)

    def formula(self, page: Page, *parts: str, finish: str = "{Escape}") -> None:
        """Open an inline formula with $ and type it (MathLive key strokes)."""
        self.keys(page, "$")
        self.wait_math(page)
        self.keys(page, *parts)
        if finish:
            if page.locator(".popover").count():
                page.keyboard.press("Escape")  # dismiss the template search first
            self.keys(page, finish)
            time.sleep(0.3)

    @staticmethod
    def show_last_image(page: Page) -> None:
        """Scroll to the newest plot (lazy images have no size until near the view)."""
        try:
            page.wait_for_selector(".out-image img", state="attached", timeout=20000)
        except Exception:
            print("DEBUG blocks:", page.evaluate(
                "[...document.querySelectorAll('.mbk-block')].map(b => b.innerText.slice(0, 300))"))
            raise
        page.evaluate("""() => { const imgs = document.querySelectorAll('.out-image img');
            imgs[imgs.length - 1].closest('.mbk-block').scrollIntoView({block: 'start', behavior: 'instant'}) }""")
        page.wait_for_function("""() => { const imgs = document.querySelectorAll('.out-image img');
            const i = imgs[imgs.length - 1]; return i.complete && i.naturalWidth > 0 }""")
        page.evaluate("document.querySelector('.main').scrollBy({top: -40, behavior: 'instant'})")

    @staticmethod
    def wait_result(page: Page, count: int = 1) -> None:
        """Wait until ``count`` compute-in-place results are shown."""
        try:
            page.wait_for_function(f"document.querySelectorAll('.mbk-result:not(.mbk-defined)').length >= {count}",
                                   timeout=30000)
        except Exception:
            print("DEBUG toast:", page.locator("#toast").text_content(), "| field:",
                  page.evaluate("(document.querySelector('math-field') || {}).value"))
            raise

    @staticmethod
    def wait_done(page: Page, timeout: float = 120) -> None:
        page.wait_for_function("!document.querySelector('.mbk-block.running')", timeout=timeout * 1000)
        Tour.wait_idle(page, timeout)

    # ------------------------------------------------------------ scenarios
    def first_notebook(self) -> None:
        srv = Server(self.work).start(str(self.docs / "free-fall.maxbook"))
        try:
            page = self.page(srv.url)
            self.shot(page, "first-new")
            page.click(".mbk-doc h1", click_count=3)
            self.keys(page, "Free fall{ArrowDown}A stone dropped from rest falls a distance ")
            self.formula(page, "d=1/2{ArrowRight}gt^2")
            self.keys(page, " after ")
            self.formula(page, "t")
            self.keys(page, " seconds.")
            self.shot(page, "first-text", ".mbk-doc h1", ".mbk-doc p")
            self.keys(page, "{Enter}On Earth, ")
            self.formula(page, "g:=9.81", finish="{Tab}")
            page.wait_for_selector(".mbk-defined")
            self.keys(page, ", so after three seconds the stone has fallen ")
            self.formula(page, "1/2{ArrowRight}g*3^2{ArrowRight}=", finish="")
            self.shot(page, "first-inline-formula", ".mbk-doc p:nth-of-type(2)", pad=28)
            self.keys(page, "{Tab}")
            self.wait_result(page)
            self.keys(page, " metres.")
            self.shot(page, "first-compute", ".mbk-doc p:nth-of-type(2)", pad=28)
            self.keys(page, "{Enter}How long does a fall from 20 metres take?{Enter}>> ")
            page.wait_for_selector(".mbk-maxima textarea:focus")
            self.keys(page, "t_fall(h) := sqrt(2*h/g)$\nt_fall(20);{Shift+Enter}", delay=12)
            self.wait_done(page)
            self.shot(page, "first-maxima-block", ".mbk-maxima")
            self.keys(page, "The distance over the first three seconds:{Enter}>> ")
            page.wait_for_selector(".mbk-maxima textarea:focus")
            self.keys(page, "iplot2d(g*t^2/2, [t, 0, 3])${Shift+Enter}", delay=12)
            self.wait_done(page)
            self.show_last_image(page)
            self.shot(page, "first-plot", ".mbk-maxima:last-of-type")
            self.keys(page, "{Control+s}")
            page.wait_for_selector("#toast.show")
            page.evaluate("document.querySelector('.main').scrollTop = 0")
            self.shot(page, "first-saved", settle=0.2)
            assert (self.docs / "free-fall.maxbook").exists()
        finally:
            srv.stop()


    def run_all(self, page: Page) -> None:
        page.click('[data-cmd="run-all"]')
        page.get_by_role("button", name="no", exact=True).click(timeout=120000)
        page.wait_for_function("(document.querySelector('#toast').textContent || '').startsWith('Computed')",
                               timeout=120000)
        self.wait_idle(page)
        page.wait_for_selector("#toast.show", state="detached", timeout=10000)  # let the toast fade

    def overview(self) -> None:
        srv = Server(self.work).start(str(self.docs / "welcome.maxbook"))
        try:
            for dark in (False, True):
                page = self.page(srv.url, dark=dark)
                self.run_all(page)
                page.evaluate("document.querySelector('.main').scrollTop = 0")
                self.shot(page, "overview-dark" if dark else "overview-light", settle=1.0)
                if not dark:
                    # symbols: hover card on f, then the panel
                    sym = page.locator(".mbk-mathblock .mbk-sym.mbk-function").first
                    sym.scroll_into_view_if_needed()
                    sym.hover()
                    page.wait_for_selector(".sym-card")
                    self.shot(page, "symbols-hover", ".mbk-mathblock:has(.mbk-function)", ".sym-card", pad=24)
                    page.mouse.move(5, 400)
                    self.shot(page, "symbols-panel", "#objects", pad=0)
                    page.locator(".obj-row", has_text="Symbol").first  # noqa: B018 - keep layout settled
                    row = page.locator(".obj-row").filter(has=page.locator(".sym-chip.mbk-free")).last
                    row.click()
                    self.shot(page, "symbols-highlight", settle=0.4)
                    page.keyboard.press("F1")
                    page.wait_for_selector(".modal .kbd-help")
                    self.shot(page, "keyboard-help", ".modal", pad=10)
                    page.keyboard.press("Escape")
                page.context.close()
        finally:
            srv.stop()

    def formulas(self) -> None:
        srv = Server(self.work).start()
        try:
            page = self.page(srv.url)
            page.click(".mbk-doc h1", click_count=3)
            self.keys(page, "Formulas{ArrowDown}A display formula, with the template search:")
            self.keys(page, "{Enter}$")
            self.wait_math(page)
            self.keys(page, "$")
            try:
                page.wait_for_selector(".mbk-mathblock math-field", timeout=10000)
            except Exception:
                print("DEBUG", page.evaluate("""() => ({blocks: document.querySelectorAll('.mbk-mathblock').length,
                    inline: document.querySelectorAll('.mbk-math-inline').length,
                    html: document.querySelector('.mbk-doc').innerHTML.slice(0, 600)})"""))
                raise
            self.wait_math(page)
            self.keys(page, "int")
            page.wait_for_selector(".popover")
            self.shot(page, "formulas-search", ".mbk-mathblock", ".popover", pad=20)
            self.keys(page, "{Enter}x^2{Tab}x")
            time.sleep(0.8)  # the Maxima translation updates as you type
            self.shot(page, "formulas-display", ".mbk-mathblock")
            self.keys(page, "{Shift+Enter}")
            self.wait_done(page)
            self.shot(page, "formulas-evaluated", ".mbk-mathblock")
            self.keys(page, "The Basel problem: ")
            self.formula(page, "sum", finish="")
            # MathLive visits the boxes top limit first: upper, index, start, body
            self.keys(page, "{Enter}oo{Tab}k{Tab}1{Tab}1/k^2{ArrowRight}{ArrowRight}=")
            self.shot(page, "formulas-sum-typing", '.mbk-doc p:has-text("Basel")', pad=26)
            self.keys(page, "{Tab}")
            self.wait_result(page)
            self.keys(page, ", which Maxima finds with ")
            page.keyboard.press("Backquote")
            self.keys(page, "simpsum")
            page.keyboard.press("Backquote")
            self.keys(page, ".")
            self.shot(page, "formulas-sum", '.mbk-doc p:has-text("Basel")', pad=26)
        finally:
            srv.stop()

    def maxima_blocks(self) -> None:
        srv = Server(self.work).start()
        try:
            page = self.page(srv.url)
            page.click(".mbk-doc h1", click_count=3)
            self.keys(page, "Maxima blocks{ArrowDown}>> ")
            page.wait_for_selector(".mbk-maxima textarea:focus")
            self.keys(page, "integrate(x^a, x);{Shift+Enter}", delay=12)
            page.wait_for_selector(".out-question input")
            self.shot(page, "blocks-question", ".mbk-maxima")
            page.get_by_role("button", name="no", exact=True).click()
            self.wait_done(page)
            self.shot(page, "blocks-answered", ".mbk-maxima")
            page.click(".mbk-doc p:last-of-type")
            self.keys(page, ">> ")
            page.wait_for_selector(".mbk-maxima textarea:focus")
            self.keys(page, "keep: 42$\nfor i: 1 thru 10^9 do s: i^2;{Shift+Enter}", delay=12)
            time.sleep(2.5)
            self.shot(page, "blocks-running", ".topbar", ".mbk-maxima:last-of-type", pad=0)
            page.click('[data-cmd="interrupt"]')
            self.wait_done(page)
            page.click(".mbk-doc p:last-of-type")
            self.keys(page, ">> ")
            page.wait_for_selector(".mbk-maxima textarea:focus")
            self.keys(page, "keep;{Shift+Enter}", delay=12)
            self.wait_done(page)
            self.shot(page, "blocks-stopped", ".mbk-maxima:nth-of-type(2)", ".mbk-maxima:last-of-type")
            page.click(".mbk-doc p:last-of-type")
            self.keys(page, ">> ")
            page.wait_for_selector(".mbk-maxima textarea:focus")
            self.keys(page, "iplot3d(sin(x)*cos(y), [x, -3, 3], [y, -3, 3])${Shift+Enter}", delay=12)
            self.wait_done(page)
            self.show_last_image(page)
            self.shot(page, "blocks-plot3d", ".mbk-maxima:last-of-type")
        finally:
            srv.stop()

    def menus(self) -> None:
        srv = Server(self.work).start()
        try:
            page = self.page(srv.url)
            page.click(".mbk-doc h1", click_count=3)
            self.keys(page, "Menus{ArrowDown}")
            page.get_by_role("button", name="Calculus ▾").click()
            page.wait_for_selector(".menu-pop")
            self.shot(page, "menus-calculus", ".formatbar", ".menu-pop", pad=6)
            page.locator(".menu-pop .menu-item", has_text="Taylor series").click()
            page.wait_for_selector(".modal .dlg-form")
            self.keys(page, "exp(x)*cos(x)")
            self.shot(page, "menus-dialog", ".modal", pad=10)
            page.get_by_role("button", name="Insert and run").click()
            self.wait_done(page)
            self.shot(page, "menus-result", ".mbk-maxima")
            page.keyboard.press("Control+k")
            page.wait_for_selector(".palette-input")
            self.keys(page, "matrix")
            self.shot(page, "menus-palette", ".modal", pad=10)
            page.keyboard.press("Escape")
            page.get_by_role("button", name="AI ▾").click()
            page.wait_for_selector(".menu-pop")
            self.shot(page, "ai-menu", ".formatbar", ".menu-pop", pad=6)
        finally:
            srv.stop()

    def files(self) -> None:
        (self.docs / "kinematics.wxm").write_text(
            "/* [wxMaxima batch file version 1] [ DO NOT EDIT BY HAND! ]*/\n"
            "/* [wxMaxima: comment start ]\nKinematics\n   [wxMaxima: comment end   ] */\n\n"
            "/* [wxMaxima: input   start ] */\nv(t) := diff(s(t), t)$\n"
            "/* [wxMaxima: input   end   ] */\n", encoding="utf-8")
        srv = Server(self.work).start(str(self.docs / "welcome.maxbook"))
        try:
            page = self.page(srv.url)
            page.click('[data-cmd="open"]')
            page.wait_for_selector(".modal .files li")
            page.locator(".modal .files li", has_text="kinematics.wxm").click()
            self.shot(page, "files-open", ".modal", pad=10)
            page.keyboard.press("Escape")
            page.click('[data-cmd="export"]')
            page.wait_for_selector(".modal .palette-list li")
            self.shot(page, "files-export", ".modal", pad=10)
            page.keyboard.press("Escape")
        finally:
            srv.stop()

    def together(self) -> None:
        srv = Server(self.work).start(str(self.docs / "welcome.maxbook"), share=True)
        try:
            host = self.page(srv.url)
            host.click("#share-btn")
            host.wait_for_selector(".modal .share-row")
            self.shot(host, "together-share", ".modal", pad=10)
            host.keyboard.press("Escape")
            token = srv.links[0].split("#token=")[1]
            ctx = self.browser.new_context(viewport=VIEWPORT, device_scale_factor=2, bypass_csp=True)
            guest = ctx.new_page()
            guest.on("dialog", lambda d: d.accept("Ada"))
            guest.goto(f"{srv.base}#token={token}")
            guest.wait_for_selector(".mbk-doc")
            guest.wait_for_selector(".role-badge:not([hidden])")
            guest.click(".mbk-doc h1")
            guest.keyboard.press("End")
            self.keys(guest, "{Enter}Ada: I added a note here, and the host sees it at once.")
            time.sleep(1.5)
            guest.evaluate("document.activeElement.blur()")  # no spell-check squiggles
            self.shot(guest, "together-guest")
            host.wait_for_selector("#users .avatar")
            self.shot(host, "together-host", ".topbar", pad=0)
            ctx.close()
        finally:
            srv.stop()


SCENARIOS = ["first_notebook", "overview", "formulas", "maxima_blocks", "menus", "files", "together"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--channel", default="msedge" if sys.platform == "win32" else None,
                        help="browser to drive (default: msedge on Windows, Playwright's Chromium elsewhere)")
    parser.add_argument("--only", nargs="*", choices=SCENARIOS, help="run only these scenarios")
    parser.add_argument("--show", action="store_true", help="show the browser while it works")
    args = parser.parse_args()
    work = Path(tempfile.mkdtemp(prefix="maxbook-tour-"))
    (work / "Documents").mkdir()
    (work / "home").mkdir()
    shutil.copy(ROOT / "examples" / "welcome.maxbook", work / "Documents" / "welcome.maxbook")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel=args.channel, headless=not args.show)
            tour = Tour(browser, work)
            for name in args.only or SCENARIOS:
                print(name)
                getattr(tour, name)()
            browser.close()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
