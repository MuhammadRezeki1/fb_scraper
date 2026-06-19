"""
fb_debug_selector.py v2 — Cari panel komentar + struktur span Facebook
Setara dengan debug_selector.py v2 (Instagram) tapi untuk Facebook

Mencari:
  - Panel overflow (area komentar yang bisa discroll)
  - Ancestor chain dari username span
  - Ancestor chain dari komentar span
  - Struktur li & article
"""
import os
import time
import re
from colorama import Fore, init
from playwright.sync_api import sync_playwright

init(autoreset=True)

PROFILE_DIR = os.path.join(os.getcwd(), "fb_profile")


def main():
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "  FACEBOOK DEBUG SELECTOR v2")
    print(Fore.CYAN + "  Cari panel komentar + struktur span")
    print(Fore.CYAN + "=" * 60)

    url = input("\n🔗 URL post Facebook: ").strip()
    if not url:
        print(Fore.RED + "❌ URL kosong")
        return

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--start-maximized", "--disable-notifications", "--no-sandbox"],
            viewport={"width": 1366, "height": 768},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/148.0.0.0 Safari/537.36"
            ),
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            bypass_csp=True,
        )

        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url)
        print(Fore.YELLOW + "\n⏳ Tunggu 8 detik...")
        time.sleep(8)

        # Tutup popup
        for sel in [
            "div[aria-label='Tutup']", "div[aria-label='Close']",
            "button:has-text('Terima semua')", "button:has-text('Accept all')",
        ]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=2000)
                    time.sleep(0.5)
            except:
                pass

        # ── 1. Panel Overflow ──────────────────────────────────────────────
        print(Fore.CYAN + "\n=== 1. CEK PANEL OVERFLOW (area komentar) ===")
        panels = page.evaluate("""() => {
            const panels = [];
            for (const el of document.querySelectorAll('div')) {
                const s = window.getComputedStyle(el);
                if (
                    (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 100 &&
                    el.clientHeight > 80
                ) {
                    panels.push({
                        cls:      el.className.toString().slice(0, 80),
                        role:     el.getAttribute('role') || '',
                        scrollH:  el.scrollHeight,
                        clientH:  el.clientHeight,
                        children: el.children.length,
                        sample:   (el.innerText || '').slice(0, 200).replace(/\\n/g, ' | '),
                    });
                }
            }
            panels.sort((a, b) => b.scrollH - a.scrollH);
            return panels.slice(0, 8);
        }""")

        print(f"Panel overflow ditemukan: {len(panels)}")
        for p in panels:
            print(Fore.YELLOW + f"\n  scrollH={p['scrollH']} clientH={p['clientH']} "
                  f"role={p['role']} children={p['children']}")
            print(f"    cls=[{p['cls'][:70]}]")
            print(f"    sample={repr(p['sample'][:150])}")

        # ── 2. Scroll semua panel ─────────────────────────────────────────
        print(Fore.CYAN + "\n=== 2. SCROLL SEMUA PANEL + KLIK 'LIHAT LEBIH BANYAK' ===")
        page.evaluate("""() => {
            for (const el of document.querySelectorAll('*')) {
                const oy = window.getComputedStyle(el).overflowY;
                if (oy === 'scroll' || oy === 'auto') {
                    el.scrollTop += 1000;
                }
            }
        }""")
        page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
        time.sleep(3)

        # Klik load more / lihat lebih banyak
        load_more_selectors = [
            "div[role='button']:has-text('Lihat lebih banyak komentar')",
            "div[role='button']:has-text('View more comments')",
            "span:has-text('Lihat lebih banyak komentar')",
            "span:has-text('View more comments')",
            "div[role='button']:has-text('Lihat komentar sebelumnya')",
        ]
        for sel in load_more_selectors:
            try:
                btns = page.locator(sel)
                if btns.count() > 0:
                    btns.first.click(timeout=2000)
                    print(Fore.GREEN + f"  ✅ Klik: {sel[:50]}")
                    time.sleep(2)
            except:
                pass

        # ── 3. Sample span (10-200 char) ──────────────────────────────────
        print(Fore.CYAN + "\n=== 3. SAMPLE TEKS SEMUA SPAN (10-200 char) ===")
        spans = page.evaluate("""() => {
            const spans = document.querySelectorAll('span');
            const res = [];
            const seen = new Set();
            for (const sp of spans) {
                const t = (sp.innerText || '').trim();
                if (t.length < 10 || t.length > 200 || t.includes('\\n')) continue;
                if (seen.has(t)) continue;
                seen.add(t);

                const parent = sp.parentElement ? sp.parentElement.tagName : '';
                const gp     = sp.parentElement && sp.parentElement.parentElement
                               ? sp.parentElement.parentElement.tagName : '';
                const inArt  = !!sp.closest("[role='article']");
                const inA    = !!sp.closest('a');
                const dir    = sp.getAttribute('dir') || '';
                res.push({ t, parent, gp, inArt, inA, dir });
            }
            return res.slice(0, 50);
        }""")

        for s in spans:
            flag = Fore.GREEN + "✅" if (s["inArt"] and not s["inA"]) else "  "
            print(f"  {flag} inArt={s['inArt']} inA={s['inA']} dir={s['dir']} "
                  f"<{s['gp']}><{s['parent']}><span> {repr(s['t'][:80])}")

        # ── 4. [role='article'] dengan span bertumpuk ─────────────────────
        print(Fore.CYAN + "\n=== 4. [role='article'] DENGAN SPAN BERTUMPUK ===")
        arts = page.evaluate("""() => {
            const arts = document.querySelectorAll("[role='article']");
            const res = [];
            for (const art of arts) {
                const t = (art.innerText || '').trim();
                if (t.length < 5) continue;
                const spans = art.querySelectorAll('span');
                const spanTexts = Array.from(spans)
                    .map(s => (s.innerText || '').trim())
                    .filter(Boolean);
                const uniqueSpans = [...new Set(spanTexts)].slice(0, 8);
                res.push({
                    text:  t.replace(/\\n/g, ' | ').slice(0, 200),
                    spans: uniqueSpans,
                    cls:   art.className.slice(0, 80),
                });
            }
            return res.slice(0, 15);
        }""")

        print(f"Total [role='article'] dengan teks: {len(arts)}")
        for i, art in enumerate(arts):
            print(Fore.YELLOW + f"\n  ARTICLE[{i}]: {repr(art['text'][:100])}")
            for sp in art["spans"]:
                print(Fore.WHITE + f"    SPAN: {repr(sp[:80])}")

        # ── 5. Ancestor chain dari username ──────────────────────────────
        print(Fore.CYAN + "\n=== 5. CEK ANCESTOR CHAIN ===")
        print(Fore.YELLOW + "  Masukkan teks yang muncul sebagai username di komentar")
        print(Fore.YELLOW + "  (copy persis dari browser, misal: 'Figo' atau 'Alce Agansi')")

        username_sample = input(Fore.WHITE + "  Username sample: ").strip()
        comment_sample  = input(Fore.WHITE + "  Teks komentar sample (atau kosong): ").strip()

        if username_sample:
            chain = page.evaluate("""(username) => {
                const out = [];
                for (const sp of document.querySelectorAll('span, a')) {
                    const t = (sp.innerText || '').trim();
                    if (t !== username) continue;
                    if (sp.closest('a') && sp.tagName !== 'A') continue;  // skip jika nested di link

                    out.push('\\n🔍 Username span ditemukan: ' + t);
                    let el = sp;
                    for (let i = 0; i < 10; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        out.push(
                            '  up[' + i + ']: <' + el.tagName + '>' +
                            ' role=' + (el.getAttribute('role') || '') +
                            ' aria=' + (el.getAttribute('aria-label') || '').slice(0, 50) +
                            ' scrollH=' + el.scrollHeight +
                            ' clientH=' + el.clientHeight +
                            ' cls=[' + el.className.slice(0, 70) + ']'
                        );
                    }
                    break;  // ambil yang pertama saja
                }
                return out.join('\\n') || '❌ Username tidak ditemukan di DOM';
            }""", username_sample)
            print(chain)

        if comment_sample:
            chain2 = page.evaluate("""(commentText) => {
                const out = [];
                for (const sp of document.querySelectorAll('span, div')) {
                    const t = (sp.innerText || '').trim();
                    if (!t.includes(commentText)) continue;
                    if (t.length > 500) continue;  // skip container besar

                    out.push('\\n🔍 Komentar elemen ditemukan: ' + t.slice(0, 80));
                    let el = sp;
                    for (let i = 0; i < 10; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        out.push(
                            '  up[' + i + ']: <' + el.tagName + '>' +
                            ' role=' + (el.getAttribute('role') || '') +
                            ' aria=' + (el.getAttribute('aria-label') || '').slice(0, 50) +
                            ' scrollH=' + el.scrollHeight +
                            ' clientH=' + el.clientHeight +
                            ' cls=[' + el.className.slice(0, 70) + ']'
                        );
                    }
                    break;
                }
                return out.join('\\n') || '❌ Teks komentar tidak ditemukan di DOM';
            }""", comment_sample)
            print(chain2)

        # ── 6. Struktur article detail ────────────────────────────────────
        print(Fore.CYAN + "\n=== 6. DETAIL ARTIKEL PERTAMA (semua direct text nodes) ===")
        art_struct = page.evaluate("""() => {
            const art = document.querySelector("[role='article']");
            if (!art) return [{tag:'INFO', text:'TIDAK ADA ARTICLE', role:'', aria:'', dir:''}];

            const all = art.querySelectorAll('*');
            const res = [];
            for (const el of all) {
                const directText = Array.from(el.childNodes)
                    .filter(n => n.nodeType === 3)
                    .map(n => n.textContent.trim())
                    .filter(Boolean)
                    .join('');
                if (directText.length >= 3 && directText.length <= 300) {
                    res.push({
                        tag:  el.tagName,
                        text: directText.slice(0, 100),
                        dir:  el.getAttribute('dir') || '',
                        role: el.getAttribute('role') || '',
                        aria: (el.getAttribute('aria-label') || '').slice(0, 60),
                    });
                }
            }
            return res.slice(0, 40);
        }""")

        for a in art_struct:
            aria_str = f" aria={repr(a['aria'])}" if a["aria"] else ""
            role_str = f" role={a['role']}"        if a["role"] else ""
            dir_str  = f" dir={a['dir']}"          if a["dir"]  else ""
            print(f"  <{a['tag']}>{dir_str}{role_str}{aria_str}  → {repr(a['text'][:80])}")

        print(Fore.GREEN + "\n✅ Debug Selector selesai!")
        input(Fore.CYAN + "\nENTER untuk tutup browser...")
        ctx.close()


if __name__ == "__main__":
    main()