"""PDF Cad Layout test — run before every push that touches layout.html.

    pip install playwright && python -m playwright install chromium
    python dev/test_layout.py            (CHROME=/usr/bin/google-chrome optional)

Uses dev/layout_assets/ (A3 template PDF, DXF plan 1:100, DBK BIM bundle = manifest + 2 PNG scenes).
Serves the repo on localhost:8766, blocks outside requests, then: new A3 document from template,
draws on two layers (one shared), page add/duplicate/move/delete, DXF import + OSNAP on DXF lines,
SketchUp bundle import + re-import (update), Claude JSON paste, autosave reload, both PDF exports,
.pclayout save + reopen. Screenshots + PDFs go to dev/out/.
"""
import asyncio, http.server, os, sys, threading, functools, json
from playwright.async_api import async_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, 'dev', 'layout_assets')
OUT = os.path.join(ROOT, 'dev', 'out'); os.makedirs(OUT, exist_ok=True)
PORT = 8766
fails = []


def check(name, ok, extra=''):
    print(('PASS ' if ok else 'FAIL ') + name + (f'  [{extra}]' if extra != '' else ''))
    if not ok: fails.append(name)


def serve():
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a): pass
    http.server.ThreadingHTTPServer(('localhost', PORT), functools.partial(Quiet, directory=ROOT)).serve_forever()


async def main():
    threading.Thread(target=serve, daemon=True).start()
    async with async_playwright() as p:
        exe = os.environ.get('CHROME')
        b = await p.chromium.launch(executable_path=exe, args=['--no-sandbox']) if exe else await p.chromium.launch()
        ctx = await b.new_context(viewport={'width': 1366, 'height': 768}, accept_downloads=True)
        await ctx.grant_permissions(['clipboard-read', 'clipboard-write'], origin=f'http://localhost:{PORT}')
        pg = await ctx.new_page(); errs, ext = [], []
        pg.on('pageerror', lambda e: errs.append(str(e)))
        pg.on('dialog', lambda d: asyncio.ensure_future(d.accept()))
        async def route(r):
            if not r.request.url.startswith(f'http://localhost:{PORT}'): ext.append(r.request.url); return await r.abort()
            await r.continue_()
        await pg.route('**/*', route)
        ev = pg.evaluate
        await pg.goto(f'http://localhost:{PORT}/layout.html'); await pg.wait_for_timeout(800)
        await pg.screenshot(path=os.path.join(OUT, 'layout_0_start.png'))

        # --- new document: A3 landscape, 2 pages, template
        await pg.fill('#ndName', 'บ้านทดสอบ'); await pg.fill('#ndN', '2')
        await pg.set_input_files('#fTpl', os.path.join(A, 'a3_template.pdf')); await pg.wait_for_timeout(200)
        await pg.click('#ndCreate'); await pg.wait_for_timeout(2000)
        info = await ev("({n:S.n, w:S.pages[1].w/PT_PER_MM, h:S.pages[1].h/PT_PER_MM, tpl:!!S.tpl, name:pageName(1), den:denOf(1)})")
        check('new doc A3 x2 from template', info['n'] == 2 and abs(info['w'] - 420) < 1 and info['tpl'], info)
        check('tools fit 1366x768', await ev("$('tools').scrollHeight <= $('tools').clientHeight"))
        check('top bar one row', await ev("$('top').offsetHeight < 50"), await ev("$('top').offsetHeight"))

        box = await pg.locator('#pagewrap').bounding_box(); X = lambda f: box['x'] + box['width'] * f; Y = lambda f: box['y'] + box['height'] * f
        key = lambda ch, code: ev(f"window.dispatchEvent(new KeyboardEvent('keydown', {{key: '{ch}', code: '{code}', bubbles: true}}))")
        await key('ส', 'KeyL'); await pg.mouse.click(X(.2), Y(.3)); await pg.mouse.click(X(.4), Y(.3)); await key('Escape', 'Escape')
        # shared layer: title text with auto fields
        await ev("S.curLayer='L2'; renderLayers();")
        await key('ะ', 'KeyT'); await pg.mouse.click(X(.9), Y(.9)); await pg.wait_for_timeout(100)
        await pg.keyboard.type('{ชื่อหน้า} {มาตราส่วน}'); await pg.keyboard.press('Enter'); await key('Escape', 'Escape')
        await ev("S.curLayer='L1'; renderLayers();")
        sh = await ev("S.anns.filter(a=>a.page===0).length")
        check('shared layer item on page 0', sh == 1, sh)
        await ev("goPage(2)"); await pg.wait_for_timeout(500)
        check('shared item visible on page 2', await ev("S.anns.some(a=>a.page===0 && onPg(a))"))
        check('auto text', await ev("autoText('{ชื่อหน้า}|{หน้า}/{จำนวนหน้า}|{มาตราส่วน}', 2)") == 'หน้า 2|2/2|1 : 100')

        # --- pages
        await ev("goPage(1)"); await pg.wait_for_timeout(300)
        await pg.click('#pgAdd'); await pg.wait_for_timeout(900)
        check('add page', await ev('S.n') == 3 and await ev('S.page') == 2)
        await ev("goPage(1)"); await pg.wait_for_timeout(300)
        await pg.click('#pgDup'); await pg.wait_for_timeout(900)
        dup = await ev("({n:S.n, p2:S.anns.filter(a=>a.page===2).length, p1:S.anns.filter(a=>a.page===1).length, nm:pageName(2)})")
        check('duplicate page copies items', dup['n'] == 4 and dup['p2'] == dup['p1'] == 1, dup)
        await pg.click('#pgDn'); await pg.wait_for_timeout(900)
        check('move page down', await ev('S.page') == 3 and 'สำเนา' in await ev('pageName(3)'))
        await pg.click('#pgDel'); await pg.wait_for_timeout(900)
        check('delete page', await ev('S.n') == 3, await ev('S.n'))
        check('shared item survives page ops', await ev("S.anns.filter(a=>a.page===0).length") == 1)

        # --- DXF import (1:100) on page 1
        await ev("goPage(1)"); await pg.wait_for_timeout(400)
        await pg.set_input_files('#fDxf', os.path.join(A, 'plan_1to100.dxf')); await pg.wait_for_timeout(400)
        await pg.fill('#mText', '100'); await pg.click('#mOk'); await pg.wait_for_timeout(800)
        vp = await ev("(()=>{const a=S.anns.find(a=>a.type==='vp'); const M=a&&S.media[a.mid]; return a&&{w:a.w/PT_PER_MM,h:a.h/PT_PER_MM,pl:M.pl.length,tx:M.tx.map(t=>t[4]),den:a.den}})()")
        check('DXF viewport 8x6 m at 1:100 = 80x60 mm (+cols)', vp and abs(vp['w'] - 82) < 2 and abs(vp['h'] - 62) < 2, vp)
        check('DXF Thai text', vp and any('ห้องนอน' in t for t in vp['tx']), vp and vp['tx'])
        snap = await ev("(()=>{const a=S.anns.find(a=>a.type==='vp'); const [ox,oy,f]=vpOrigin(a); const px=ox+4800*f, py=oy+(-3000)*f; S.snapEnd=true; const r=osnapFind(px+1.5, py+1, 8, null); return r && [r[2], Math.hypot(r[0]-px, r[1]-py)]})()")
        check('OSNAP on DXF arc end', bool(snap) and snap[0] == 'end' and snap[1] < 0.2, snap)
        await ev("(()=>{const a=S.anns.find(a=>a.type==='vp'); setSel([a.id]); syncPanel(); setVpDen(50);})()")
        check('viewport scale change sets page scale', await ev("denOf(1)") == 50 and await ev("S.anns.find(a=>a.type==='vp').den") == 50)
        await ev("(()=>{undo();})()")
        await pg.screenshot(path=os.path.join(OUT, 'layout_1_dxf.png'))

        # --- SketchUp bundle (DBK BIM): manifest + 2 PNG
        files = [os.path.join(A, f) for f in ('test-house_dbklayout.json', 'plan_1.png', 'sec_a.png')]
        await pg.set_input_files('#fSkp', files); await pg.wait_for_timeout(2500)
        sk = await ev("({n:S.n, vps:S.anns.filter(a=>a.type==='vp'&&S.media[a.mid].type==='img').map(a=>[a.page,a.name,+(a.w/PT_PER_MM).toFixed(1)]), names:[pageName(4),pageName(5)], den:denOf(4)})")
        check('SketchUp scenes -> 2 new pages', sk['n'] == 5 and len(sk['vps']) == 2 and sk['names'] == ['แปลนพื้นชั้น 1', 'รูปตัด A-A'], sk)
        check('SketchUp scale 8 m @1:100 ~ 80 mm', sk['vps'] and abs(sk['vps'][0][2] - 80) < 3, sk['vps'])
        await ev("goPage(4)"); await pg.wait_for_timeout(800)
        await pg.screenshot(path=os.path.join(OUT, 'layout_2_skp.png'))
        await pg.set_input_files('#fSkp', files); await pg.wait_for_timeout(2500)
        check('re-import updates in place (no new pages)', await ev('S.n') == 5)
        # furniture sheet: 4 views (3 at 1:20 + perspective) on ONE page, 2x2
        await pg.set_input_files('#fSkp', [os.path.join(A, f) for f in ('f01_dbklayout.json', 'f01_front.png', 'f01_side.png', 'f01_top.png', 'f01_persp.png')]); await pg.wait_for_timeout(2500)
        fs = await ev("(()=>{const v=S.anns.filter(a=>a.type==='vp'&&a.page===S.n); return {n:S.n, name:pageName(S.n), den:denOf(S.n), k:v.length, w:v.map(a=>+(a.w/PT_PER_MM).toFixed(1)), persp:v.filter(a=>a.persp).length, cells:v.map(a=>[Math.round(a.x),Math.round(a.y)])}})()")
        check('furniture sheet = 1 page with 4 views', fs['n'] == 6 and fs['k'] == 4 and fs['persp'] == 1 and fs['name'] == 'แบบเฟอร์นิเจอร์ F01 ตู้เสื้อผ้า' and fs['den'] == 20, fs)
        check('front view 1.2 m @1:20 = 60 mm', abs(fs['w'][0] - 60) < 2, fs['w'])
        await ev("goPage(S.n)"); await pg.wait_for_timeout(800)
        await pg.screenshot(path=os.path.join(OUT, 'layout_2b_furniture.png'))

        # --- Claude bridge
        await pg.click('#bDocMenu'); await pg.click('#mAiCopy'); await pg.wait_for_timeout(300)
        clip = await ev("navigator.clipboard.readText()")
        check('Claude copy text', clip.startswith('PDFCAD-LAYOUT/1') and 'REPLY' in clip, clip[:80])
        await pg.click('#bDocMenu'); await pg.click('#mAiPaste'); await pg.wait_for_timeout(200)
        await pg.fill('#mText', '```json\n{"units":"mm","items":[{"type":"rect","x":30,"y":30,"w":60,"h":40},{"type":"pl","pts":[[30,80],[90,80],[90,100]],"closed":true},{"type":"text","x":32,"y":32,"text":"ห้องครัว","size":4},{"type":"dim","x1":30,"y1":120,"x2":90,"y2":120}]}\n```')
        n0 = await ev('S.anns.length'); await pg.click('#mOk'); await pg.wait_for_timeout(300)
        check('Claude paste draws 6 items', await ev('S.anns.length') - n0 == 6, await ev('S.anns.length') - n0)

        # --- autosave reload
        before = await ev("({a:S.anns.length,n:S.n,m:Object.keys(S.media).length,l:S.layers.length,nm:pageName(4)})")
        await pg.wait_for_timeout(700); await pg.reload(); await pg.wait_for_timeout(3500)
        after = await ev("({a:S.anns.length,n:S.n,m:Object.keys(S.media).length,l:S.layers.length,nm:pageName(4)})")
        check('autosave reload restores everything', before == after, f'{before} -> {after}')

        # --- exports
        for bid in ['#bExportClean', '#bExport']:
            async with pg.expect_download() as dl:
                await pg.click(bid)
            d = await dl.value; fn = os.path.join(OUT, 'layout_' + d.suggested_filename); await d.save_as(fn); print('saved', fn)
        async with pg.expect_download() as dl:
            await pg.click('#bDocMenu'); await pg.click('#mSaveProj')
        d = await dl.value; proj = os.path.join(OUT, 'layout_' + d.suggested_filename); await d.save_as(proj)
        check('project file', os.path.getsize(proj) > 10000, os.path.getsize(proj))

        # --- reopen project in a fresh browser profile
        ctx2 = await b.new_context(viewport={'width': 1366, 'height': 768}); pg2 = await ctx2.new_page()
        pg2.on('pageerror', lambda e: errs.append('ctx2: ' + str(e)))
        await pg2.route('**/*', route)
        await pg2.goto(f'http://localhost:{PORT}/layout.html'); await pg2.wait_for_timeout(600)
        await pg2.set_input_files('#fProj', proj); await pg2.wait_for_timeout(3000)
        re = await pg2.evaluate("({a:S.anns.length,n:S.n,m:Object.keys(S.media).length,l:S.layers.length,nm:pageName(4)})")
        check('reopen .pclayout', re == after, re)
        await pg2.screenshot(path=os.path.join(OUT, 'layout_3_reopen.png'))
        print('page errors:', errs or 'none'); print('outside requests:', ext or 'none')
        await b.close()
        if errs or ext or fails: print('FAILED:', fails); sys.exit(1)
        print('ALL PASS')

asyncio.run(main())
