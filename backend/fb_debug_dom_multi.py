"""
fb_debug_dom_multi.py — Inspeksi struktur DOM untuk MULTIPLE tipe konten sekaligus
(reels, group, page, post biasa) — dengan dump RAW HTML (bukan cuma innerText) untuk
area metrics (like/comment/share/views) dan area komentar.
"""
import os
import time
import json
from datetime import datetime
from colorama import Fore, init
from playwright.sync_api import sync_playwright, Page

init(autoreset=True)

PROFILE_DIR = os.path.join(os.getcwd(), "fb_profile")
OUTPUT_DIR  = os.path.join(os.getcwd(), "fb_dom_debug_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ── Tuning ─────────────────────────────────────────────────────────────────
# Ganti "networkidle" → "commit": FB tidak pernah benar-benar idle
# karena ada background analytics/polling terus-menerus.
GOTO_WAIT_UNTIL   = "commit"   # options: "commit" | "domcontentloaded" | "load"
GOTO_TIMEOUT_MS   = 60_000     # 60 detik — jarang butuh lebih dari ini

# Setelah goto(), tunggu elemen ini muncul dulu sebelum lanjut ke poll konten
ANCHOR_SELECTORS = [
    "[role='main']",
    "[role='feed']",
    "[role='article']",
    "div[data-pagelet]",
]
ANCHOR_TIMEOUT_MS = 30_000   # tunggu anchor max 30 detik

# Poll konten: cek apakah article + teks metric sudah ada
POLL_INTERVAL_SEC = 3        # cek tiap 3 detik
POLL_MAX_ATTEMPTS = 10       # max 10x → 30 detik total polling

TYPES_TO_ASK = [
    ("posts",  "📝 URL Post biasa (timeline/feed)"),
    ("videos", "🎥 URL Reels/Video"),
    ("groups", "👥 URL Post di dalam Group"),
    ("pages",  "📄 URL Post di Page (bukan profil pribadi)"),
]


# ── JS: extract semua kandidat elemen metrics dengan RAW HTML ──────────────
_JS_EXTRACT_METRICS_RAW = r"""
() => {
    const candidates = [];
    const all = document.querySelectorAll('span, div, a');
    const seen = new Set();

    for (const el of all) {
        const text = (el.innerText || '').trim();
        if (!text || text.length > 60) continue;
        if (seen.has(text + '|' + el.tagName)) continue;

        const hasDigit = /\d/.test(text);
        const hasKeyword = /(suka|like|reaksi|reaction|komentar|comment|tayang|view|ditonton|bagikan|share|rb|jt|k\b|m\b)/i.test(text);
        if (!hasDigit && !hasKeyword) continue;

        seen.add(text + '|' + el.tagName);

        const article = el.closest('[role="article"]');
        const ariaLabel = el.getAttribute('aria-label') || '';
        const parentAria = el.parentElement ? (el.parentElement.getAttribute('aria-label') || '') : '';

        candidates.push({
            tag: el.tagName,
            text: text,
            ariaLabel: ariaLabel,
            parentAria: parentAria,
            className: (el.className || '').toString().slice(0, 150),
            inArticle: !!article,
            outerHTML: el.outerHTML.slice(0, 500),
            parentOuterHTML: el.parentElement ? el.parentElement.outerHTML.slice(0, 600) : '',
        });
    }
    return candidates.slice(0, 80);
}
"""

# ── JS: extract struktur komentar mendalam ────────────────────────────────
_JS_EXTRACT_COMMENTS_RAW = r"""
() => {
    const result = {
        commentContainers: [],
        sampleCommentBlocks: [],
        replyIndicators: [],
    };

    const possibleContainers = document.querySelectorAll('ul, div[role="list"], div');
    const containerCandidates = [];
    for (const el of possibleContainers) {
        const childCount = el.children.length;
        if (childCount < 2 || childCount > 200) continue;
        const text = (el.innerText || '');
        if (text.length < 30) continue;
        const hasTimeWords = /(menit|jam|hari|minggu|bulan|lalu|ago|balas|reply)/i.test(text);
        if (!hasTimeWords) continue;
        containerCandidates.push({
            tag: el.tagName,
            role: el.getAttribute('role') || '',
            className: (el.className || '').toString().slice(0, 150),
            childCount: childCount,
            sampleText: text.slice(0, 200),
        });
    }
    result.commentContainers = containerCandidates.slice(0, 15);

    const replyButtons = document.querySelectorAll('[aria-label*="alas" i], [aria-label*="eply" i]');
    for (const btn of replyButtons) {
        const block = btn.closest('li') || btn.closest('div[role="article"]') || btn.parentElement;
        if (!block) continue;
        result.sampleCommentBlocks.push({
            buttonAria: btn.getAttribute('aria-label') || '',
            buttonOuterHTML: btn.outerHTML.slice(0, 300),
            blockTag: block.tagName,
            blockClassName: (block.className || '').toString().slice(0, 150),
            blockOuterHTML: block.outerHTML.slice(0, 800),
        });
        if (result.sampleCommentBlocks.length >= 10) break;
    }

    const allDivs = document.querySelectorAll('div');
    let count = 0;
    for (const el of allDivs) {
        const style = el.getAttribute('style') || '';
        if (/margin-left:\s*[2-9]\d|padding-left:\s*[2-9]\d/.test(style)) {
            const text = (el.innerText || '').trim();
            if (text.length > 5 && text.length < 200) {
                result.replyIndicators.push({
                    style: style.slice(0, 100),
                    sampleText: text.slice(0, 100),
                    className: (el.className || '').toString().slice(0, 100),
                });
                count++;
                if (count >= 10) break;
            }
        }
    }

    return result;
}
"""

# ── JS: extract [role='article'] ──────────────────────────────────────────
_JS_EXTRACT_ARTICLES = r"""
() => {
    const arts = document.querySelectorAll("[role='article']");
    const res = [];
    for (const art of arts) {
        const text = (art.innerText || '').trim().replace(/\n/g, ' | ');
        const links = art.querySelectorAll('a[href*="facebook.com"]');
        const btnArias = Array.from(art.querySelectorAll('[aria-label]'))
            .map(el => el.getAttribute('aria-label'))
            .filter(Boolean)
            .slice(0, 8);
        res.push({
            cls: art.className.toString().slice(0, 100),
            text: text.slice(0, 200),
            linkCount: links.length,
            btnArias,
            childCount: art.children.length,
            outerHTMLSnippet: art.outerHTML.slice(0, 400),
        });
    }
    return res.slice(0, 6);
}
"""

# ── JS: cek seberapa "matang" konten di halaman ───────────────────────────
_JS_CHECK_CONTENT_LOADED = r"""
() => {
    const articles   = document.querySelectorAll("[role='article']").length;
    const bodyText   = document.body.innerText || '';
    const hasReact   = /(suka|like|reaksi|reaction)/i.test(bodyText);
    const hasComment = /(komentar|comment)/i.test(bodyText);
    const hasTime    = /(menit|jam|hari|minggu|lalu|ago)/i.test(bodyText);
    return { articles, hasReact, hasComment, hasTime };
}
"""


def _write_section(f, title, content):
    f.write(f"\n{'=' * 70}\n{title}\n{'=' * 70}\n")
    if isinstance(content, (dict, list)):
        f.write(json.dumps(content, ensure_ascii=False, indent=2))
    else:
        f.write(str(content))
    f.write("\n")


def _close_popups(page: Page):
    for sel in [
        "div[aria-label='Tutup']", "div[aria-label='Close']",
        "button:has-text('Terima semua')", "button:has-text('Accept all')",
    ]:
        try:
            if page.locator(sel).count() > 0:
                page.locator(sel).first.click(timeout=2000)
                time.sleep(0.4)
        except Exception:
            pass


def _wait_for_anchor(page: Page):
    """
    Tunggu salah satu elemen struktural FB muncul (role=main / article / dll).
    Ini tanda bahwa React sudah mulai render — bukan cuma blank loading screen.
    """
    for sel in ANCHOR_SELECTORS:
        try:
            page.wait_for_selector(sel, timeout=ANCHOR_TIMEOUT_MS)
            print(Fore.GREEN + f"   ✅ Anchor ditemukan: {sel}")
            return
        except Exception:
            continue
    print(Fore.YELLOW + "   ⚠️  Tidak ada anchor yang ditemukan dalam batas waktu — lanjut polling.")


def _poll_until_content_ready(page: Page) -> bool:
    """
    Poll secara berkala: cek apakah article + teks metric/comment sudah ada.
    Return True kalau konten sudah siap, False kalau habis batas polling.
    Tidak ada scroll otomatis di sini — biarkan FB render secara alami.
    """
    for attempt in range(1, POLL_MAX_ATTEMPTS + 1):
        _close_popups(page)
        status = page.evaluate(_JS_CHECK_CONTENT_LOADED)
        arts     = status.get("articles", 0)
        has_r    = status.get("hasReact", False)
        has_c    = status.get("hasComment", False)
        has_t    = status.get("hasTime", False)

        # Tampilkan progress bar sederhana
        score = sum([arts > 0, has_r, has_c, has_t])
        bar   = "█" * score + "░" * (4 - score)
        print(Fore.CYAN +
              f"   [{bar}] attempt {attempt:02d}/{POLL_MAX_ATTEMPTS} | "
              f"articles={arts} | react={has_r} | comment={has_c} | time={has_t}")

        if arts > 0 and (has_r or has_c):
            return True

        if attempt < POLL_MAX_ATTEMPTS:
            time.sleep(POLL_INTERVAL_SEC)

    return False


def _debug_one_url(page: Page, type_key: str, url: str, output_path: str):
    print(Fore.CYAN + f"\n🌐 [{type_key}] Navigasi ke: {url[:80]}")

    # ── Step 1: goto dengan "commit" — tidak tunggu idle, cukup response header ──
    # FB tidak pernah networkidle karena background analytics terus berjalan.
    page.goto(url, wait_until=GOTO_WAIT_UNTIL, timeout=GOTO_TIMEOUT_MS)
    print(Fore.GREEN + "   ✅ Response diterima (commit), menunggu render...")

    # ── Step 2: tunggu anchor struktural FB muncul ──────────────────────────────
    _wait_for_anchor(page)
    _close_popups(page)

    # ── Step 3: poll sampai konten metric/comment muncul (tanpa scroll otomatis) ─
    print(Fore.YELLOW + f"   ⏳ Polling konten (max {POLL_MAX_ATTEMPTS * POLL_INTERVAL_SEC}s)...")
    ready = _poll_until_content_ready(page)

    if ready:
        print(Fore.GREEN + "   ✅ Konten terdeteksi siap!")
    else:
        print(Fore.YELLOW + "   ⚠️  Konten mungkin belum penuh — scroll manual di browser kalau perlu.")

    # ── Step 4: serahkan kontrol ke user ────────────────────────────────────────
    print()
    input(
        Fore.CYAN
        + f"✋ [{type_key}] Pastikan konten + komentar sudah muncul & stabil.\n"
        + "   Kalau ada yang belum muncul, scroll perlahan di browser dulu.\n"
        + "   Tekan ENTER saat tampilan sudah siap untuk di-capture: "
    )

    # ── Step 5: capture DOM ─────────────────────────────────────────────────────
    print(Fore.CYAN + "   📦 Mengambil data DOM...")

    metrics_raw   = page.evaluate(_JS_EXTRACT_METRICS_RAW)
    comments_raw  = page.evaluate(_JS_EXTRACT_COMMENTS_RAW)
    articles_raw  = page.evaluate(_JS_EXTRACT_ARTICLES)
    full_html_len = page.evaluate("document.documentElement.outerHTML.length")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"FB DOM DEBUG — type={type_key}\n")
        f.write(f"URL: {url}\n")
        f.write(f"Captured at: {datetime.now().isoformat()}\n")
        f.write(f"Full page HTML length: {full_html_len} chars\n")

        _write_section(f, "1. KANDIDAT ELEMEN METRICS (like/comment/share/view) — RAW HTML", metrics_raw)
        _write_section(f, "2. STRUKTUR AREA KOMENTAR (container + sample block + reply indicator)", comments_raw)
        _write_section(f, "3. [role='article'] DITEMUKAN DI HALAMAN", articles_raw)

    print(Fore.GREEN + f"   ✅ Disimpan ke: {output_path}")
    print(Fore.CYAN + f"      - {len(metrics_raw)} kandidat elemen metrics")
    print(Fore.CYAN + f"      - {len(comments_raw.get('commentContainers', []))} kandidat container komentar")
    print(Fore.CYAN + f"      - {len(comments_raw.get('sampleCommentBlocks', []))} sample comment block (dgn tombol balas)")
    print(Fore.CYAN + f"      - {len(comments_raw.get('replyIndicators', []))} indikasi nested reply")
    print(Fore.CYAN + f"      - {len(articles_raw)} [role='article'] ditemukan")

    return {
        "type": type_key,
        "url": url,
        "metrics_candidates": len(metrics_raw),
        "comment_containers": len(comments_raw.get("commentContainers", [])),
        "sample_comment_blocks": len(comments_raw.get("sampleCommentBlocks", [])),
        "reply_indicators": len(comments_raw.get("replyIndicators", [])),
        "articles_found": len(articles_raw),
        "output_file": output_path,
    }


def main():
    print(Fore.CYAN + "=" * 70)
    print(Fore.CYAN + "  FACEBOOK DEBUG DOM (MULTI-TYPE) — Metrics + Komentar Raw HTML")
    print(Fore.CYAN + "=" * 70)
    print(Fore.YELLOW + "\nMasukkan URL untuk tiap tipe konten. Kosongkan (Enter) untuk skip.\n")

    urls = {}
    for key, label in TYPES_TO_ASK:
        u = input(f"{label}: ").strip()
        if u:
            urls[key] = u

    if not urls:
        print(Fore.RED + "❌ Tidak ada URL yang dimasukkan. Keluar.")
        return

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    summary   = []

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

        for key, url in urls.items():
            output_path = os.path.join(OUTPUT_DIR, f"{timestamp}_{key}.txt")
            try:
                result = _debug_one_url(page, key, url, output_path)
                summary.append(result)
            except Exception as e:
                print(Fore.RED + f"   ❌ Gagal debug tipe '{key}': {e}")
                summary.append({"type": key, "url": url, "error": str(e)})

        print(Fore.CYAN + "\n✋ Semua tipe selesai diproses.")
        input(Fore.CYAN + "ENTER untuk tutup browser...")
        ctx.close()

    summary_path = os.path.join(OUTPUT_DIR, f"{timestamp}_SUMMARY.txt")
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("FB DOM DEBUG — SUMMARY SEMUA TIPE\n")
        f.write(f"Captured at: {datetime.now().isoformat()}\n\n")
        f.write(json.dumps(summary, ensure_ascii=False, indent=2))

    print(Fore.GREEN + f"\n✅ Selesai! Summary disimpan di: {summary_path}")
    print(Fore.CYAN + f"Semua file ada di folder: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()