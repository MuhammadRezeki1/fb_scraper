"""
fb_debug_dom.py — Inspeksi struktur DOM komentar Facebook secara detail
Setara dengan debug_dom.py (Instagram) tapi untuk Facebook

FIX:
  - channel="chrome" + no_viewport (samakan dengan scraper utama)
  - Tunggu redirect stabil sebelum lanjut
  - Polling aktif sampai [role="article"] BUKAN skeleton "Memuat..." lagi
  - Deteksi redirect ke feed/homepage + auto-klik timestamp post pertama
  - Guard page.is_closed() di setiap section agar tidak crash TargetClosedError

Jalankan, masukkan URL post Facebook, tunggu polling selesai, lalu ENTER untuk debug
"""
import os
import re
import time
from colorama import Fore, init
from playwright.sync_api import sync_playwright

init(autoreset=True)

PROFILE_DIR = os.path.join(os.getcwd(), "fb_profile")


def main():
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "  FACEBOOK DEBUG DOM — Struktur Komentar")
    print(Fore.CYAN + "=" * 60)

    url = input("\n🔗 URL post Facebook: ").strip()
    if not url:
        print(Fore.RED + "❌ URL kosong")
        return

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            channel="chrome",
            headless=False,
            args=["--start-maximized", "--disable-notifications"],
            no_viewport=True,
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

        # ── GOTO ─────────────────────────────────────────────────────────
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(Fore.YELLOW + f"⚠️  goto warning: {e}")

        # ── TUNGGU REDIRECT STABIL ───────────────────────────────────────
        print(Fore.CYAN + "\n⏳ Menunggu redirect selesai...")
        stable_count = 0
        prev_url = ""
        for _ in range(20):
            time.sleep(0.5)
            if page.is_closed():
                break
            cur_url = page.url
            if cur_url == prev_url:
                stable_count += 1
                if stable_count >= 4:
                    break
            else:
                stable_count = 0
                prev_url = cur_url

        if page.is_closed():
            print(Fore.RED + "❌ Page tertutup! Membuka tab baru...")
            page = ctx.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(7)

        print(Fore.CYAN + f"   URL final: {page.url[:90]}")

        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass

        # ── TUTUP POPUP ───────────────────────────────────────────────────
        for sel in [
            "div[aria-label='Tutup']", "div[aria-label='Close']",
            "button:has-text('Terima semua')", "button:has-text('Accept all')",
        ]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=2000)
                    time.sleep(0.5)
            except Exception:
                pass

        # ── POLLING: TUNGGU KONTEN ASLI (BUKAN SKELETON "Memuat...") ──────
        print(Fore.CYAN + "\n⏳ Menunggu konten asli termuat (bukan skeleton 'Memuat...')...")
        content_ready = False
        for attempt in range(15):  # max ~30 detik
            time.sleep(2)
            if page.is_closed():
                print(Fore.RED + "❌ Page tertutup saat polling!")
                break
            try:
                content_ready = page.evaluate("""() => {
                    const arts = document.querySelectorAll('[role="article"]');
                    if (arts.length === 0) return false;
                    for (const a of arts) {
                        const aria = a.getAttribute('aria-label') || '';
                        if (aria === 'Memuat...' || aria === 'Loading...') continue;
                        if ((a.innerText || '').trim().length > 20) return true;
                    }
                    return false;
                }""")
            except Exception:
                content_ready = False
            if content_ready:
                print(Fore.GREEN + f"   ✅ Konten termuat (percobaan {attempt+1}/15, ~{(attempt+1)*2}s)")
                break
            print(Fore.YELLOW + f"   ⏳ Masih skeleton 'Memuat...' ... ({attempt+1}/15)")

        if not content_ready and not page.is_closed():
            print(Fore.RED + "   ⚠️  Konten tidak termuat dalam ~30s. Kemungkinan:")
            print(Fore.RED + "       1) URL redirect ke feed dan post tidak ditemukan/tidak accessible")
            print(Fore.RED + "       2) Koneksi lambat / perlu scroll manual")

        # ── DETEKSI REDIRECT KE FEED/HOMEPAGE ────────────────────────────
        is_feed = bool(re.match(r"^https://www\.facebook\.com/?(\?.*)?$", page.url)) if not page.is_closed() else False
        if is_feed:
            print(Fore.YELLOW + "\n⚠️  URL berada di FEED (bukan halaman post standalone).")
            print(Fore.YELLOW + "   Mencoba klik timestamp post pertama yang sudah termuat...")

            clicked = False
            try:
                clicked = page.evaluate("""() => {
                    const arts = document.querySelectorAll('[role="article"]');
                    for (const a of arts) {
                        const aria = a.getAttribute('aria-label') || '';
                        if (aria === 'Memuat...' || aria === 'Loading...') continue;
                        const links = a.querySelectorAll('a[href*="/posts/"], a[href*="/videos/"], a[href*="/permalink"], a[aria-label]');
                        for (const lnk of links) {
                            const txt = (lnk.innerText || '').trim();
                            if (/jam|menit|hari|minggu|detik|^\\d+\\s*[a-z]+$/i.test(txt) && txt.length < 15) {
                                lnk.click();
                                return true;
                            }
                        }
                    }
                    return false;
                }""")
            except Exception:
                pass

            if clicked:
                print(Fore.GREEN + "   ✅ Klik timestamp — menunggu modal post terbuka...")
                time.sleep(4)
                try:
                    page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                print(Fore.CYAN + f"   URL setelah klik: {page.url[:90]}")
            else:
                print(Fore.RED + "   ❌ Tidak ketemu timestamp post yang sudah termuat.")
                print(Fore.YELLOW + "   💡 Scroll/buka post secara manual di browser sebelum ENTER,")
                print(Fore.YELLOW + "       atau post memang tidak accessible (privasi/link invalid).")

        input(Fore.CYAN + "\n✋ Pastikan komentar sudah muncul di browser, lalu tekan ENTER...")

        # ── 1. Semua <a> yang href-nya profil user ─────────────────────────
        print(Fore.CYAN + "\n\n=== 1. SEMUA <a href=profil> ===")
        if page.is_closed():
            print(Fore.RED + "❌ Page tertutup, skip section ini")
            anchors = []
        else:
            try:
                anchors = page.evaluate("""() => {
                    const res = [];
                    for (const a of document.querySelectorAll('a[href]')) {
                        const href = a.href || '';
                        const isProfile = (
                            href.includes('facebook.com/') &&
                            !href.includes('/posts/') &&
                            !href.includes('/photos/') &&
                            !href.includes('/videos/') &&
                            !href.includes('/groups/') &&
                            !href.includes('l.facebook') &&
                            !href.includes('login') &&
                            !href.includes('help') &&
                            !href.includes('about') &&
                            (href.includes('profile.php') || /facebook\\.com\\/[a-zA-Z0-9._-]{3,50}(\\/?$|\\?|#)/.test(href))
                        );
                        if (!isProfile) continue;

                        const aText = (a.innerText || '').trim().slice(0, 60);
                        if (!aText || aText.length < 2) continue;

                        const li = a.closest('li');
                        const article = a.closest('[role="article"]');
                        res.push({
                            href: href.slice(0, 100),
                            aText,
                            inLi:      !!li,
                            inArticle: !!article,
                            parentTag: a.parentElement ? a.parentElement.tagName : '',
                            parentCls: a.parentElement ? a.parentElement.className.slice(0, 60) : '',
                        });
                    }
                    return res.slice(0, 30);
                }""")
            except Exception as e:
                print(Fore.RED + f"❌ Evaluate error: {e}")
                anchors = []

        if anchors:
            for a in anchors:
                flag = Fore.GREEN + "✅" if a["inArticle"] else "  "
                print(f"  {flag} inArticle={a['inArticle']} inLi={a['inLi']} "
                      f"aText={repr(a['aText'][:40])} | parent={a['parentTag']}.{a['parentCls'][:40]}")
                print(f"      href={a['href'][:80]}")
        else:
            print(Fore.RED + "  ❌ Tidak ada anchor profil ditemukan")

        # ── 2. Inspect [role='article'] ────────────────────────────────────
        print(Fore.CYAN + "\n=== 2. SEMUA [role='article'] (max 10) ===")
        if page.is_closed():
            print(Fore.RED + "❌ Page tertutup, skip section ini")
            articles = []
        else:
            try:
                articles = page.evaluate("""() => {
                    const arts = document.querySelectorAll("[role='article']");
                    const res = [];
                    for (const art of arts) {
                        const text = (art.innerText || '').trim().replace(/\\n/g, ' | ');
                        const links = art.querySelectorAll('a[href*="facebook.com"]');
                        const btnArias = Array.from(art.querySelectorAll('[aria-label]'))
                            .map(el => el.getAttribute('aria-label'))
                            .filter(Boolean)
                            .slice(0, 5);
                        res.push({
                            cls:       art.className.slice(0, 80),
                            text:      text.slice(0, 150),
                            linkCount: links.length,
                            btnArias,
                            childCount: art.children.length,
                        });
                    }
                    return res.slice(0, 10);
                }""")
            except Exception as e:
                print(Fore.RED + f"❌ Evaluate error: {e}")
                articles = []

        if articles:
            for i, art in enumerate(articles):
                print(f"\n  Article #{i+1} (children={art['childCount']} links={art['linkCount']})")
                print(f"    cls={art['cls'][:70]}")
                print(f"    text={repr(art['text'][:100])}")
                if art["btnArias"]:
                    print(f"    aria-labels: {art['btnArias']}")
        else:
            print(Fore.RED + "  ❌ Tidak ada [role='article'] ditemukan")

        # ── 3. Scrollable panels ───────────────────────────────────────────
        print(Fore.CYAN + "\n=== 3. SCROLLABLE PANELS (area komentar) ===")
        if page.is_closed():
            print(Fore.RED + "❌ Page tertutup, skip section ini")
            panels = []
        else:
            try:
                panels = page.evaluate("""() => {
                    const res = [];
                    for (const el of document.querySelectorAll('*')) {
                        const s = window.getComputedStyle(el);
                        if (
                            (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                            el.scrollHeight > el.clientHeight + 50 &&
                            el.clientHeight > 80
                        ) {
                            res.push({
                                tag:     el.tagName,
                                role:    el.getAttribute('role') || '',
                                cls:     el.className.toString().slice(0, 80),
                                scrollH: el.scrollHeight,
                                clientH: el.clientHeight,
                                sample:  (el.innerText || '').slice(0, 120).replace(/\\n/g, ' | '),
                            });
                        }
                    }
                    res.sort((a, b) => b.scrollH - a.scrollH);
                    return res.slice(0, 8);
                }""")
            except Exception as e:
                print(Fore.RED + f"❌ Evaluate error: {e}")
                panels = []

        if panels:
            for p in panels:
                print(f"\n  <{p['tag']}> role={p['role']} scrollH={p['scrollH']} clientH={p['clientH']}")
                print(f"    cls={p['cls'][:70]}")
                print(f"    sample={repr(p['sample'][:100])}")
        else:
            print(Fore.YELLOW + "  ⚠️  Tidak ada panel scrollable ditemukan")

        # ── 4. Span teks komentar ──────────────────────────────────────────
        print(Fore.CYAN + "\n=== 4. SPAN DENGAN TEKS KOMENTAR (5-300 char) ===")
        if page.is_closed():
            print(Fore.RED + "❌ Page tertutup, skip section ini")
            spans = []
        else:
            try:
                spans = page.evaluate("""() => {
                    const res = [];
                    const seen = new Set();
                    for (const sp of document.querySelectorAll('span')) {
                        const t = (sp.innerText || '').trim();
                        if (t.length < 5 || t.length > 300) continue;
                        if (seen.has(t)) continue;
                        seen.add(t);

                        const parent  = sp.parentElement;
                        const gp      = parent  ? parent.parentElement  : null;
                        const article = sp.closest("[role='article']");
                        res.push({
                            text:      t,
                            parentTag: parent ? parent.tagName : '',
                            gpTag:     gp ? gp.tagName : '',
                            inArticle: !!article,
                            inA:       !!sp.closest('a'),
                            dir:       sp.getAttribute('dir') || '',
                        });
                    }
                    return res.slice(0, 40);
                }""")
            except Exception as e:
                print(Fore.RED + f"❌ Evaluate error: {e}")
                spans = []

        for s in spans:
            flag = Fore.GREEN + "📝" if (s["inArticle"] and not s["inA"]) else "  "
            print(f"  {flag} inArticle={s['inArticle']} inA={s['inA']} dir={s['dir']} "
                  f"{s['gpTag']}>{s['parentTag']}><span>  {repr(s['text'][:80])}")

        # ── 5. Struktur dalam article pertama ────────────────────────────
        print(Fore.CYAN + "\n=== 5. DETAIL DALAM [role='article'] PERTAMA ===")
        if page.is_closed():
            print(Fore.RED + "❌ Page tertutup, skip section ini")
            art_detail = []
        else:
            try:
                art_detail = page.evaluate("""() => {
                    const art = document.querySelector("[role='article']");
                    if (!art) return [{tag:'', text:'TIDAK ADA ARTICLE', dir:'', role:'', aria:''}];

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
            except Exception as e:
                print(Fore.RED + f"❌ Evaluate error: {e}")
                art_detail = []

        for a in art_detail:
            aria_str = f" aria={repr(a['aria'])}" if a['aria'] else ""
            print(f"  <{a['tag']}> dir={a['dir']} role={a['role']}{aria_str}  → {repr(a['text'][:80])}")

        print(Fore.GREEN + "\n✅ Debug DOM selesai!")
        if not page.is_closed():
            input(Fore.CYAN + "\nENTER untuk tutup browser...")
        ctx.close()


if __name__ == "__main__":
    main()