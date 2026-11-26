"""Bilder für die Einstiegsanleitung (docs/img/start/<lang>-NN-*.png) mit Markierungen.
Aufruf: python guide_shots.py <lang> <url_demo> <url_leer> <ausgabe>"""
import sys

from playwright.sync_api import sync_playwright

LANG, URL, EMPTY, OUT = sys.argv[1:5]
DE = LANG == "de"

MARK_JS = """([sel, n, idx, pad]) => {
  const els = [...document.querySelectorAll(sel)];
  const el = els[idx || 0];
  if (!el) return false;
  const r = el.getBoundingClientRect(), p = pad ?? 5, host = el.closest('dialog[open]') || document.body;
  const box = document.createElement('div');
  box.className = 'guide-mark';
  box.style.cssText = `position:fixed;z-index:99999;pointer-events:none;left:${r.left - p}px;top:${r.top - p}px;
    width:${r.width + 2 * p}px;height:${r.height + 2 * p}px;border:3px solid #FF9F1C;border-radius:8px;box-shadow:0 0 0 4px rgba(255,159,28,.25)`;
  const b = document.createElement('div');
  b.className = 'guide-mark';
  b.textContent = n;
  const bx = r.left - p - 14, by = r.top - p - 14;
  b.style.cssText = `position:fixed;z-index:100000;pointer-events:none;left:${Math.max(2, bx)}px;top:${Math.max(2, by)}px;width:28px;height:28px;
    border-radius:50%;background:#FF9F1C;color:#10131a;font:700 16px/28px system-ui,sans-serif;text-align:center;box-shadow:0 2px 6px rgba(0,0,0,.5)`;
  host.append(box, b);
  return true;
}"""


def mark(pg, sel, n, idx=0, pad=5):
    assert pg.evaluate(MARK_JS, [sel, str(n), idx, pad]), f"nicht gefunden: {sel}"


def clear(pg):
    pg.evaluate("document.querySelectorAll('.guide-mark').forEach(e => e.remove())")


def shot(pg, name, full=False, clip=None):
    pg.wait_for_timeout(350)
    pg.screenshot(path=f"{OUT}/{LANG}-{name}.png", full_page=full, clip=clip)
    clear(pg)


def lang(pg):
    """Sprache über den Umschalter in der Kopfzeile."""
    btn = pg.locator(f"button:text-is('{LANG.upper()}')").first
    if btn.count():
        btn.click()
        pg.wait_for_timeout(500)


errs = []
with sync_playwright() as p:
    import os
    b = p.chromium.launch(executable_path=os.environ.get("CHROME") or None, headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 800}, locale="de-DE" if DE else "en-GB")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: errs.append(str(e)))

    # 1. Ersteinrichtung (leere Installation)
    pg.goto(EMPTY + "/")
    pg.wait_for_selector("form#f")
    lang(pg)
    mark(pg, "form#f", 1, pad=10)
    shot(pg, "01-setup")

    # Anmelden in der Demo
    pg.goto(URL + "/")
    pg.wait_for_selector("form#f")
    pg.fill("input[name=email]", "admin@example.com")
    pg.fill("input[name=password]", "passwort123")
    pg.click("button.pri")
    pg.wait_for_selector(".card")
    lang(pg)
    pg.goto(URL + "/#/")
    pg.wait_for_selector(".card.new")

    # 2. Profile
    mark(pg, ".card.new", 1)
    shot(pg, "02-profiles")

    # 3. Netzscan
    pg.goto(URL + "/#/p/1/netzscan")
    pg.wait_for_selector("#runscan")
    mark(pg, "#nets", 1, pad=8)
    mark(pg, "#runscan", 2)
    shot(pg, "03-scan")

    # 4. Posteingang
    pg.goto(URL + "/#/p/1/posteingang")
    pg.wait_for_selector(".inrow")
    mark(pg, ".inrow .acts", 1, pad=6)
    mark(pg, "[data-bulk=confirm]", 2)
    shot(pg, "04-inbox")

    # 5. Gerät bearbeiten: Anschluss (wo hängt das Gerät?)
    pg.goto(URL + "/#/p/1/geraete")
    pg.wait_for_selector("#list table")
    pg.locator("#list tbody tr").filter(has=pg.locator("td:text-is('NAS')")).first.click()
    pg.wait_for_selector("dialog[open] select[name=medium]")
    pg.evaluate("document.querySelector('dialog[open] select[name=medium]').closest('.grid2').scrollIntoView({block:'center'})")
    pg.wait_for_timeout(300)
    mark(pg, "dialog[open] select[name=medium]", 1)
    mark(pg, "dialog[open] select[name=up_device]", 2)
    mark(pg, "dialog[open] select[name=up_port]", 3)
    shot(pg, "05-device")
    pg.keyboard.press("Escape")

    # 6. Integrationen
    pg.goto(URL + "/#/p/1/integrationen")
    pg.wait_for_selector("[data-add=fritzbox]")
    pg.wait_for_timeout(1200)
    pg.evaluate("document.querySelector('[data-add]').closest('.panel').scrollIntoView({block:'start'}); scrollBy(0, -12)")
    pg.wait_for_timeout(400)
    mark(pg, ".row:has(> [data-add])", 1, pad=6)
    mark(pg, ".integ", 2, pad=3)
    shot(pg, "06-integrations")
    pg.click("[data-add=fritzbox]")
    pg.wait_for_selector("dialog[open]")
    shot(pg, "07-integration-dialog")
    pg.keyboard.press("Escape")

    # 7. Topologie mit Durchsatz
    pg.goto(URL + "/#/p/1/topologie")
    pg.wait_for_selector("#tput")
    if not pg.evaluate("document.querySelector('#tput').classList.contains('on')"):
        pg.click("#tput")
    pg.wait_for_selector(".tplabel")
    pg.click("#expall")
    pg.wait_for_timeout(700)
    mark(pg, "#tput", 1)
    mark(pg, "#expall", 2)
    mark(pg, "#fs", 3)
    shot(pg, "08-topology")

    # 8. Detailansicht des Switches (Ports)
    pg.goto(URL + "/#/p/1/topologie/2")
    pg.wait_for_selector(".pcard")
    pg.locator(".port.conn").first.click()
    pg.wait_for_selector("#pinfo h4")
    mark(pg, ".port.conn", 1, pad=4)
    mark(pg, "#pinfo", 2, pad=4)
    shot(pg, "09-ports")

    # 9. Übersicht
    pg.set_viewport_size({"width": 1280, "height": 1560})
    pg.goto(URL + "/#/p/1")
    pg.wait_for_selector(".kpis")
    pg.wait_for_timeout(1500)
    shot(pg, "10-overview")
    b.close()
print("errors", errs)
