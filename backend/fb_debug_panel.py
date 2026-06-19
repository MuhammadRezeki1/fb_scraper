"""
fb_debug_panel.py — Cari class panel komentar Facebook yang benar
Setara dengan debug_panel.py (Instagram) tapi untuk Facebook

Menginspeksi:
  - Scrollable div (panel komentar)
  - Ancestor chain dari span username
  - Ancestor chain dari span teks komentar
  - Struktur reaction/like count per komentar
"""
import os
import time
from colorama import Fore, init
from playwright.sync_api import sync_playwright

init(autoreset=True)

PROFILE_DIR = os.path.join(os.getcwd(), "fb_profile")


def main():
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "  FACEBOOK DEBUG PANEL")
    print(Fore.CYAN + "  Cari class panel + ancestor chain komentar")
    print(Fore.CYAN + "=" * 60)

    url = input("\n🔗 URL post/photo Facebook: ").strip()
    if not url:
        print(Fore.RED + "❌ URL kosong")
        return

    print(Fore.YELLOW + "\nMasukkan contoh teks dari komentar yang terlihat di browser:")
    username_1  = input("  Username ke-1 (misal: Figo): ").strip()
    username_2  = input("  Username ke-2 (misal: Alce Agansi): ").strip()
    comment_txt = input("  Penggalan teks komentar (misal: lanjutkan mulut): ").strip()

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
        print(Fore.YELLOW + "\n⏳ Tunggu 7 detik...")
        time.sleep(7)

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

        input(Fore.CYAN + "\n✋ Pastikan komentar sudah tampil di browser, lalu ENTER...")

        # ── Jalankan semua debug dalam satu JS call ────────────────────────
        result = page.evaluate("""(u1, u2, commentTxt) => {
            const out = [];

            // =========================================================
            // BAGIAN 1: Scrollable DIVs (terbesar dulu)
            // =========================================================
            out.push('\\n======================================================');
            out.push('BAGIAN 1: SCROLLABLE DIVS (terbesar dulu)');
            out.push('======================================================');
            const panels = [];
            for (const el of document.querySelectorAll('div')) {
                const s = window.getComputedStyle(el);
                if (
                    (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 100 &&
                    el.clientHeight > 80
                ) {
                    panels.push({
                        cls:     el.className.toString(),
                        role:    el.getAttribute('role') || '',
                        scrollH: el.scrollHeight,
                        clientH: el.clientHeight,
                        sample:  (el.innerText || '').slice(0, 200).replace(/\\n/g, ' | '),
                    });
                }
            }
            panels.sort((a, b) => b.scrollH - a.scrollH);
            for (const p of panels.slice(0, 6)) {
                out.push('scrollH=' + p.scrollH + ' clientH=' + p.clientH + ' role=' + p.role);
                out.push('  cls=[' + p.cls.slice(0, 100) + ']');
                out.push('  sample: ' + p.sample.slice(0, 150));
                out.push('');
            }

            // =========================================================
            // BAGIAN 2: Ancestor chain dari span USERNAME
            // =========================================================
            out.push('\\n======================================================');
            out.push('BAGIAN 2: ANCESTOR CHAIN dari USERNAME SPAN');
            out.push('======================================================');
            const usernames = [u1, u2].filter(Boolean);
            for (const username of usernames) {
                let found = false;
                for (const el of document.querySelectorAll('span, a')) {
                    const t = (el.innerText || '').trim();
                    if (t !== username) continue;
                    found = true;
                    out.push('\\nUsername "' + username + '" ditemukan di <' + el.tagName + '>');
                    let cur = el;
                    for (let i = 0; i < 10; i++) {
                        cur = cur.parentElement;
                        if (!cur) break;
                        out.push(
                            '  up[' + i + ']: <' + cur.tagName + '>' +
                            ' role=' + (cur.getAttribute('role') || '-') +
                            ' aria=[' + (cur.getAttribute('aria-label') || '').slice(0, 50) + ']' +
                            ' scrollH=' + cur.scrollHeight +
                            ' clientH=' + cur.clientHeight +
                            ' cls=[' + cur.className.slice(0, 80) + ']'
                        );
                    }
                    break;
                }
                if (!found) {
                    out.push('❌ Username "' + username + '" tidak ditemukan di DOM');
                }
            }

            // =========================================================
            // BAGIAN 3: Ancestor chain dari span KOMENTAR
            // =========================================================
            out.push('\\n======================================================');
            out.push('BAGIAN 3: ANCESTOR CHAIN dari TEKS KOMENTAR');
            out.push('======================================================');
            if (commentTxt) {
                let found = false;
                for (const el of document.querySelectorAll('span, div')) {
                    const t = (el.innerText || '').trim();
                    if (!t.includes(commentTxt)) continue;
                    if (t.length > 500) continue;
                    found = true;
                    out.push('\\nKomentar "' + t.slice(0, 60) + '" ditemukan di <' + el.tagName + '>');
                    let cur = el;
                    for (let i = 0; i < 10; i++) {
                        cur = cur.parentElement;
                        if (!cur) break;
                        out.push(
                            '  up[' + i + ']: <' + cur.tagName + '>' +
                            ' role=' + (cur.getAttribute('role') || '-') +
                            ' aria=[' + (cur.getAttribute('aria-label') || '').slice(0, 50) + ']' +
                            ' scrollH=' + cur.scrollHeight +
                            ' clientH=' + cur.clientHeight +
                            ' cls=[' + cur.className.slice(0, 80) + ']'
                        );
                    }
                    break;
                }
                if (!found) out.push('❌ Teks komentar tidak ditemukan di DOM');
            }

            // =========================================================
            // BAGIAN 4: Struktur REACTION / LIKE COUNT per komentar
            // =========================================================
            out.push('\\n======================================================');
            out.push('BAGIAN 4: STRUKTUR REACTION / LIKE COUNT per KOMENTAR');
            out.push('======================================================');
            const articles = document.querySelectorAll("[role='article']");
            out.push('Total [role=article] ditemukan: ' + articles.length);

            for (let idx = 0; idx < Math.min(articles.length, 5); idx++) {
                const art = articles[idx];
                const artText = (art.innerText || '').trim().slice(0, 80).replace(/\\n/g, ' | ');
                out.push('\\n── Article #' + (idx+1) + ': ' + artText);

                // a. Semua aria-label di dalam article
                const ariaEls = art.querySelectorAll('[aria-label]');
                out.push('  [aria-label] count: ' + ariaEls.length);
                for (const el of ariaEls) {
                    const aria = el.getAttribute('aria-label') || '';
                    const txt  = (el.innerText || '').trim().slice(0, 30);
                    out.push(
                        '  <' + el.tagName + '> aria=[' + aria.slice(0, 80) + ']' +
                        ' text=' + JSON.stringify(txt)
                    );
                }

                // b. Semua span dengan angka murni (kemungkinan like count)
                const spanNums = art.querySelectorAll('span');
                const numSpans = [];
                for (const sp of spanNums) {
                    const t = (sp.innerText || '').trim();
                    if (/^\\d+$/.test(t) && parseInt(t) < 100000) {
                        const parentAria = sp.closest('[aria-label]')
                            ? sp.closest('[aria-label]').getAttribute('aria-label')
                            : '';
                        numSpans.push({
                            val: t,
                            cls: sp.className.slice(0, 60),
                            parentAria: parentAria.slice(0, 80),
                        });
                    }
                }
                if (numSpans.length > 0) {
                    out.push('  Span angka ditemukan (' + numSpans.length + '):');
                    for (const ns of numSpans) {
                        out.push(
                            '    val=' + ns.val +
                            ' parentAria=[' + ns.parentAria + ']' +
                            ' cls=[' + ns.cls + ']'
                        );
                    }
                } else {
                    out.push('  ⚠️  Tidak ada span angka ditemukan');
                }

                // c. Elemen dengan teks mengandung "reaksi" / "reaction"
                const allEls = art.querySelectorAll('*');
                const reactionEls = [];
                for (const el of allEls) {
                    const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                    const txt  = (el.innerText  || '').toLowerCase();
                    if (aria.includes('reaksi') || aria.includes('reaction') ||
                        txt.includes('reaksi')  || txt.includes('reaction')) {
                        const raw = (el.innerText || '').trim().slice(0, 60);
                        if (raw.length < 80) {
                            reactionEls.push({
                                tag:  el.tagName,
                                aria: (el.getAttribute('aria-label') || '').slice(0, 80),
                                txt:  raw,
                                cls:  el.className.slice(0, 60),
                            });
                        }
                    }
                }
                // Dedup
                const seen = new Set();
                const deduped = reactionEls.filter(r => {
                    const k = r.aria + r.txt;
                    if (seen.has(k)) return false;
                    seen.add(k);
                    return true;
                });
                if (deduped.length > 0) {
                    out.push('  Elemen "reaksi/reaction" (' + deduped.length + '):');
                    for (const r of deduped.slice(0, 8)) {
                        out.push(
                            '    <' + r.tag + '> aria=[' + r.aria + ']' +
                            ' txt=' + JSON.stringify(r.txt)
                        );
                    }
                } else {
                    out.push('  ⚠️  Tidak ada elemen "reaksi" ditemukan');
                }

                // d. Cari div[role=button] dalam article (tombol like, reply, dll)
                const btns = art.querySelectorAll("div[role='button'], span[role='button']");
                if (btns.length > 0) {
                    out.push('  Buttons ([role=button]) count: ' + btns.length);
                    for (const btn of btns) {
                        const aria = (btn.getAttribute('aria-label') || '').slice(0, 60);
                        const txt  = (btn.innerText || '').trim().slice(0, 40);
                        out.push('    aria=[' + aria + '] txt=' + JSON.stringify(txt));
                    }
                }
            }

            // =========================================================
            // BAGIAN 5: Ringkasan selector yang valid
            // =========================================================
            out.push('\\n======================================================');
            out.push('BAGIAN 5: RINGKASAN SELECTOR KANDIDAT');
            out.push('======================================================');

            const candidates = [
                { sel: "[role='article']",                           label: 'Article (komentar container)' },
                { sel: "[role='complementary']",                     label: 'Complementary panel' },
                { sel: "div[data-ad-preview='message']",             label: 'Message preview div' },
                { sel: "[aria-label*='reaksi']",                     label: 'Reaksi aria-label' },
                { sel: "[aria-label*='reaction']",                   label: 'Reaction aria-label' },
                { sel: "div[dir='auto']",                            label: 'Dir auto (teks komentar)' },
                { sel: "span[dir='auto']",                           label: 'Span dir auto' },
                { sel: "a[href*='profile.php']",                     label: 'Link profil' },
                { sel: "div[role='button']:has-text('Lihat')",       label: 'Load more button (ID)' },
                { sel: "div[role='button']:has-text('View')",        label: 'Load more button (EN)' },
                { sel: "ul > li",                                    label: 'List item (komentar list?)' },
            ];

            for (const c of candidates) {
                try {
                    const count = document.querySelectorAll(c.sel).length;
                    const visible = count > 0 ?
                        Array.from(document.querySelectorAll(c.sel))
                            .filter(el => el.offsetParent !== null).length : 0;
                    out.push(
                        '  ' + (count > 0 ? '✅' : '⚪') +
                        ' [' + c.sel.slice(0, 45).padEnd(45) + ']' +
                        ' total=' + String(count).padStart(4) +
                        ' visible=' + String(visible).padStart(4) +
                        '  // ' + c.label
                    );
                } catch(e) {
                    out.push('  ❌ [' + c.sel.slice(0, 45) + '] error: ' + e.message);
                }
            }

            return out.join('\\n');
        }""", username_1, username_2, comment_txt)

        print(result)

        # ── Simpan output ke file ──────────────────────────────────────────
        output_file = "fb_debug_panel_output.txt"
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(result)
        print(Fore.GREEN + f"\n✅ Output disimpan ke: {output_file}")
        print(Fore.GREEN + "✅ Debug Panel selesai!")
        input(Fore.CYAN + "\nENTER untuk tutup browser...")
        ctx.close()


if __name__ == "__main__":
    main()