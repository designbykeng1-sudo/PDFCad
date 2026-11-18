"""PDF Cad smoke test — run before every push.

    pip install playwright && python -m playwright install chromium
    python dev/test_smoke.py path/to/any_drawing.pdf

Serves the repo root on http://localhost:8765, blocks every outside request
(the app must work offline), opens the PDF, uses the main tools in Thai-layout key
events, reloads (autosave), and saves both PDF modes into dev/out/.
"""
import asyncio, http.server, os, sys, threading, functools
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'dev', 'out'); os.makedirs(OUT, exist_ok=True)
PDF = sys.argv[1] if len(sys.argv) > 1 else None
PORT = 8765


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    h = functools.partial(Quiet, directory=ROOT)
    http.server.ThreadingHTTPServer(('localhost', PORT), h).serve_forever()


async def main():
    if not PDF: sys.exit('usage: python dev/test_smoke.py drawing.pdf')
    threading.Thread(target=serve, daemon=True).start()
    async with async_playwright() as p:
        exe = os.environ.get('CHROME')  # optional: path to Chrome
        b = await p.chromium.launch(executable_path=exe, args=['--no-sandbox']) if exe else await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 1366, 'height': 768}, accept_downloads=True)
        pg = await ctx.new_page(); errs, ext = [], []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        async def route(r):
            if not r.request.url.startswith(f'http://localhost:{PORT}'): ext.append(r.request.url); return await r.abort()
            await r.continue_()
        await pg.route('**/*', route)
        await pg.goto(f'http://localhost:{PORT}/'); await pg.set_input_files('#fPdf', PDF); await pg.wait_for_timeout(2500)
        ev = pg.evaluate
        print('pages', await ev('S.n'), '| tools fit', await ev("$('tools').scrollHeight <= $('tools').clientHeight"), '| top bar h', await ev("$('top').offsetHeight"))
        box = await pg.locator('#pagewrap').bounding_box(); X = lambda f: box['x'] + box['width'] * f; Y = lambda f: box['y'] + box['height'] * f
        key = lambda ch, code: ev(f"window.dispatchEvent(new KeyboardEvent('keydown', {{key: '{ch}', code: '{code}', bubbles: true}}))")
        await pg.mouse.click(X(.5), Y(.5))
        await key('ส', 'KeyL'); await pg.mouse.click(X(.2), Y(.3)); await pg.mouse.click(X(.4), Y(.3)); await key('Escape', 'Escape')   # line (Thai layout)
        await key('แ', 'KeyC'); await pg.mouse.click(X(.5), Y(.5)); await pg.mouse.click(X(.55), Y(.5))                               # circle
        await key('พ', 'KeyR'); await pg.mouse.click(X(.6), Y(.2)); await pg.mouse.click(X(.7), Y(.3))                                # rectangle
        await key('ป', 'KeyX'); await pg.mouse.click(X(.3), Y(.6))                                                                    # remove box
        await key('ะ', 'KeyT'); await pg.mouse.click(X(.3), Y(.7)); await pg.wait_for_timeout(100)
        await pg.keyboard.type('ทดสอบ'); await pg.keyboard.press('Shift+Enter'); await pg.keyboard.type('บรรทัด 2'); await pg.keyboard.press('Enter')
        n = await ev('S.anns.length'); print('items', n, await ev("S.anns.map(a=>a.type).join(',')"))
        await pg.wait_for_timeout(600); await pg.reload(); await pg.wait_for_timeout(2500)
        print('after reload (autosave)', await ev('S.anns.length'), '==', n)
        for bid in ['#bExportClean', '#bExport']:
            async with pg.expect_download() as dl:
                await pg.click(bid)
            d = await dl.value; await d.save_as(os.path.join(OUT, d.suggested_filename)); print('saved', d.suggested_filename)
        print('page errors:', errs or 'none'); print('outside requests:', ext or 'none')
        await b.close()
        if errs or ext: sys.exit(1)

asyncio.run(main())
