# ============================================================
# FB SCRAPER DEBUG TOOL
# Tujuan: Capture screenshot + DOM snapshot di setiap tahap
# untuk menemukan akar masalah:
#   1. Pop-up muncul lalu hilang
#   2. Komentar cuma sedikit
#   3. Tombol "Lihat lebih banyak" tidak ketemu
# ============================================================

import os
import re
import json
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────
FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
DEBUG_DIR         = "debug_output"
Path(DEBUG_DIR).mkdir(exist_ok=True)

TS = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = os.path.join(DEBUG_DIR, f"debug_log_{TS}.txt")

# ── LOGGER ────────────────────────────────────────────────────
def log(msg: str, also_print=True):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    if also_print:
        print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")

# ── SCREENSHOT ───────────────────────────────────────────────
def screenshot(page, label: str):
    fname = os.path.join(DEBUG_DIR, f"{TS}_{label}.png")
    try:
        page.screenshot(path=fname, full_page=False)  # viewport only (lebih cepat)
        log(f"📸 Screenshot: {fname}")
    except Exception as e:
        log(f"⚠️  Screenshot gagal ({label}): {e}")
    return fname

# ── DOM SNAPSHOT ─────────────────────────────────────────────
def dom_snapshot(page, label: str):
    """Simpan info DOM penting ke log"""
    fname = os.path.join(DEBUG_DIR, f"{TS}_{label}_dom.json")
    try:
        data = page.evaluate("""() => {
            // ── 1. Semua role=article ──
            const articles = document.querySelectorAll('[role="article"]');
            const articleInfo = [];
            articles.forEach((a, i) => {
                if (i > 30) return;  // Batasi output
                const links = [...a.querySelectorAll('a[href]')]
                    .map(l => l.href)
                    .filter(h => h.includes('facebook.com') || h.includes('profile.php'))
                    .slice(0, 3);
                const text = a.innerText?.trim().slice(0, 200) || '';
                articleInfo.push({ index: i, textPreview: text, links });
            });

            // ── 2. Semua tombol yang mungkin "load more" ──
            const allButtons = [];
            document.querySelectorAll('[role="button"]').forEach(btn => {
                const txt = btn.innerText?.trim();
                if (txt && txt.length < 120) {
                    allButtons.push({
                        text: txt,
                        ariaLabel: btn.getAttribute('aria-label') || '',
                        visible: btn.offsetParent !== null,
                        tagName: btn.tagName,
                    });
                }
            });

            // ── 3. Semua span/div yang mengandung kata kunci komentar ──
            const keywords = ['komentar', 'comment', 'balasan', 'reply', 'lihat', 'view', 'muat', 'load'];
            const keywordMatches = [];
            document.querySelectorAll('span, div').forEach(el => {
                const txt = el.innerText?.trim().toLowerCase();
                if (txt && txt.length < 100 && keywords.some(k => txt.includes(k))) {
                    const role = el.getAttribute('role') || el.parentElement?.getAttribute('role') || '';
                    if (role === 'button' || el.tagName === 'SPAN') {
                        keywordMatches.push({
                            tag: el.tagName,
                            role,
                            text: el.innerText?.trim(),
                            visible: el.offsetParent !== null,
                        });
                    }
                }
            });

            // ── 4. Overlay / dialog / popup ──
            const overlays = [];
            document.querySelectorAll('[role="dialog"], [role="alertdialog"], [data-overlay="true"]').forEach(el => {
                overlays.push({
                    role: el.getAttribute('role'),
                    ariaLabel: el.getAttribute('aria-label') || '',
                    visible: el.offsetParent !== null,
                    textPreview: el.innerText?.trim().slice(0, 150) || '',
                });
            });

            // ── 5. Current URL + page title ──
            return {
                url: window.location.href,
                title: document.title,
                articleCount: articles.length,
                articles: articleInfo,
                allButtonsCount: allButtons.length,
                buttons: allButtons.filter(b => b.visible).slice(0, 50),
                keywordElements: keywordMatches.filter(k => k.visible).slice(0, 30),
                overlays,
                bodyTextLength: document.body.innerText?.length || 0,
            };
        }""")
        
        with open(fname, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        # Print ringkasan ke log
        log(f"📋 DOM [{label}]: {data['articleCount']} articles | {data['allButtonsCount']} buttons | overlays: {len(data['overlays'])}")
        log(f"   URL: {data['url'][:80]}")
        
        # Log tombol yang menarik
        for btn in data['buttons']:
            txt_lower = btn['text'].lower()
            if any(k in txt_lower for k in ['komentar', 'comment', 'lihat', 'view', 'muat', 'load', 'balasan', 'reply']):
                log(f"   🔘 BUTTON [{btn['tagName']}][role={btn['role']}]: \"{btn['text'][:80]}\"")
        
        # Log overlays
        for ov in data['overlays']:
            log(f"   🔲 OVERLAY [role={ov['role']}] visible={ov['visible']}: {ov['textPreview'][:80]}")
        
        log(f"   📁 DOM detail: {fname}")
        
    except Exception as e:
        log(f"⚠️  DOM snapshot gagal ({label}): {e}")

# ── NETWORK MONITOR ─────────────────────────────────────────
network_requests = []

def setup_network_monitor(page):
    """Monitor request/response yang relevan"""
    def on_request(request):
        url = request.url
        # Hanya log GraphQL dan API calls
        if any(k in url for k in ['graphql', 'api/graphql', 'comments', 'story', 'feedback']):
            network_requests.append({
                'time': datetime.now().strftime('%H:%M:%S.%f')[:-3],
                'method': request.method,
                'url': url[:120],
                'type': request.resource_type,
            })
    
    def on_response(response):
        url = response.url
        if any(k in url for k in ['graphql', 'api/graphql']):
            log(f"   🌐 GraphQL response: {response.status} | {url[:80]}", also_print=False)
    
    page.on("request", on_request)
    page.on("response", on_response)

# ── MAIN DEBUG FLOW ──────────────────────────────────────────
def run_debug(url: str, max_comments: int = 30):
    log("=" * 60)
    log("🔍 FB SCRAPER DEBUG TOOL")
    log(f"URL: {url}")
    log(f"Max comments: {max_comments}")
    log("=" * 60)

    playwright = sync_playwright().start()
    
    args = [
        "--window-size=1920,1080",
        "--disable-blink-features=AutomationControlled",
        "--disable-notifications",
        "--mute-audio",
    ]
    
    context = playwright.chromium.launch_persistent_context(
        FB_CHROME_PROFILE,
        channel="chrome",
        headless=False,
        args=args,
        no_viewport=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
        locale="id-ID",
        timezone_id="Asia/Jakarta",
    )
    
    page = context.pages[0] if context.pages else context.new_page()
    setup_network_monitor(page)

    try:
        # ── TAHAP 1: Homepage ──────────────────────────────────
        log("\n▶ TAHAP 1: Buka homepage Facebook")
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        screenshot(page, "01_homepage")
        dom_snapshot(page, "01_homepage")

        # ── TAHAP 2: Navigasi ke post ─────────────────────────
        log(f"\n▶ TAHAP 2: Navigasi ke post")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            log("⚠️  Timeout goto, lanjut...")
        
        time.sleep(2)
        screenshot(page, "02_post_immediate")
        dom_snapshot(page, "02_post_immediate")
        log(f"   URL setelah goto: {page.url[:80]}")

        # ── TAHAP 3: Tunggu redirect selesai ─────────────────
        log(f"\n▶ TAHAP 3: Tunggu redirect stabil")
        prev_url = ""
        for i in range(20):
            time.sleep(0.5)
            cur = page.url
            if cur == prev_url:
                log(f"   URL stabil setelah {i} iterasi: {cur[:80]}")
                break
            prev_url = cur
            log(f"   [{i}] URL berubah: {cur[:80]}")
        
        screenshot(page, "03_after_redirect")
        dom_snapshot(page, "03_after_redirect")

        # ── TAHAP 4: Cek overlay/popup yang mungkin muncul ───
        log(f"\n▶ TAHAP 4: Cek dan tangani popup/overlay")
        _check_and_dismiss_popups(page)
        screenshot(page, "04_after_popup_dismiss")
        dom_snapshot(page, "04_after_popup_dismiss")

        # ── TAHAP 5: Tunggu artikel muncul ───────────────────
        log(f"\n▶ TAHAP 5: Tunggu [role=article] muncul")
        try:
            page.wait_for_selector("[role='article']", timeout=15000)
            count = page.locator("[role='article']").count()
            log(f"   ✅ Article ditemukan: {count}")
        except PlaywrightTimeout:
            log("   ❌ TIMEOUT: [role=article] tidak muncul dalam 15 detik!")
        
        screenshot(page, "05_articles_loaded")
        dom_snapshot(page, "05_articles_loaded")

        # ── TAHAP 6: Scroll pertama ───────────────────────────
        log(f"\n▶ TAHAP 6: Scroll pertama ke bawah")
        page.evaluate("window.scrollBy(0, window.innerHeight * 3);")
        time.sleep(2)
        screenshot(page, "06_after_scroll1")
        dom_snapshot(page, "06_after_scroll1")

        # ── TAHAP 7: Cari tombol "load more" secara exhaustive
        log(f"\n▶ TAHAP 7: Exhaustive search tombol 'load more komentar'")
        _exhaustive_button_search(page)

        # ── TAHAP 8: Scroll ke bawah + cari lagi ─────────────
        log(f"\n▶ TAHAP 8: Scroll ke artikel terakhir + re-check")
        page.evaluate("""() => {
            const articles = document.querySelectorAll('[role="article"]');
            if (articles.length > 0) {
                articles[articles.length - 1].scrollIntoView({behavior: 'auto', block: 'center'});
            }
        }""")
        time.sleep(2)
        screenshot(page, "08_scroll_to_last_article")
        dom_snapshot(page, "08_scroll_to_last_article")
        _exhaustive_button_search(page)  # Cari lagi setelah scroll

        # ── TAHAP 9: Coba klik tombol yang ditemukan ─────────
        log(f"\n▶ TAHAP 9: Coba klik semua tombol kandidat 'load more'")
        _try_click_load_more(page)
        time.sleep(2)
        screenshot(page, "09_after_click_load_more")
        dom_snapshot(page, "09_after_click_load_more")

        # ── TAHAP 10: Final state ─────────────────────────────
        log(f"\n▶ TAHAP 10: Final state")
        final_count = page.locator("[role='article']").count()
        log(f"   📊 Total artikel di DOM: {final_count}")
        screenshot(page, "10_final_state")
        dom_snapshot(page, "10_final_state")

        # ── SUMMARY ───────────────────────────────────────────
        _print_summary(page)

    except Exception as e:
        log(f"\n❌ EXCEPTION: {e}")
        import traceback
        tb = traceback.format_exc()
        log(tb)
        screenshot(page, "99_error")
        dom_snapshot(page, "99_error")

    finally:
        # Simpan semua network requests
        net_file = os.path.join(DEBUG_DIR, f"{TS}_network_requests.json")
        with open(net_file, "w", encoding="utf-8") as f:
            json.dump(network_requests, f, ensure_ascii=False, indent=2)
        log(f"\n🌐 Network requests tersimpan: {net_file} ({len(network_requests)} requests)")
        log(f"\n📁 Semua debug output di folder: {DEBUG_DIR}/")
        log(f"📝 Log file: {LOG_FILE}")
        
        input("\n⏸️  Tekan ENTER untuk tutup browser...")
        context.close()
        playwright.stop()


def _check_and_dismiss_popups(page):
    """Cek semua jenis popup/overlay yang mungkin muncul di Facebook"""
    
    # ── Cek via JavaScript ──
    try:
        overlays = page.evaluate("""() => {
            const results = [];
            
            // Dialog roles
            document.querySelectorAll('[role="dialog"], [role="alertdialog"]').forEach(el => {
                results.push({
                    type: 'dialog',
                    ariaLabel: el.getAttribute('aria-label') || '',
                    visible: el.offsetParent !== null,
                    text: el.innerText?.trim().slice(0, 200) || '',
                    hasCloseButton: !!el.querySelector('[aria-label="Tutup"], [aria-label="Close"], [aria-label="Dismiss"]'),
                });
            });
            
            // Fixed/sticky elements yang mungkin overlay
            document.querySelectorAll('div').forEach(el => {
                const style = window.getComputedStyle(el);
                if ((style.position === 'fixed' || style.position === 'sticky') 
                    && style.display !== 'none' 
                    && el.offsetHeight > 100
                    && el.offsetWidth > 100) {
                    const text = el.innerText?.trim().slice(0, 100) || '';
                    if (text) {
                        results.push({
                            type: 'fixed/sticky',
                            text,
                            zIndex: style.zIndex,
                            top: el.getBoundingClientRect().top,
                        });
                    }
                }
            });
            
            return results;
        }""")
        
        if overlays:
            log(f"   🔲 Ditemukan {len(overlays)} overlay/dialog:")
            for ov in overlays:
                log(f"      type={ov['type']} visible={ov.get('visible','?')} | {ov.get('text','')[:80]}")
        else:
            log("   ✅ Tidak ada overlay/dialog terdeteksi")
            
    except Exception as e:
        log(f"   ⚠️  Cek overlay error: {e}")
    
    # ── Coba dismiss ──
    dismiss_selectors = [
        ("aria-label", "Tutup"),
        ("aria-label", "Close"),
        ("aria-label", "Dismiss"),
        ("aria-label", "Lewati"),
        ("aria-label", "Skip"),
        ("text", "Tutup"),
        ("text", "Hanya cookie yang diperlukan"),
        ("text", "Only allow essential cookies"),
        ("text", "Terima semua"),
        ("text", "Accept All"),
        ("text", "Tidak sekarang"),
        ("text", "Not now"),
        ("text", "Nanti"),
        ("text", "Later"),
    ]
    
    for sel_type, sel_val in dismiss_selectors:
        try:
            if sel_type == "aria-label":
                el = page.locator(f"[aria-label='{sel_val}']")
            else:
                el = page.locator(f"[role='button']:has-text('{sel_val}')")
            
            if el.count() > 0 and el.first.is_visible(timeout=500):
                log(f"   🔘 Klik dismiss: {sel_type}='{sel_val}'")
                el.first.click(timeout=2000)
                time.sleep(0.5)
        except Exception:
            pass
    
    # Tekan Escape untuk dismiss popup
    try:
        page.keyboard.press("Escape")
        time.sleep(0.3)
    except:
        pass


def _exhaustive_button_search(page):
    """Cari semua tombol kandidat 'load more comments' secara exhaustive"""
    
    log("   🔍 Mencari semua tombol kandidat...")
    
    # ── Method 1: Semua [role=button] ──
    try:
        btns = page.locator("[role='button']")
        count = btns.count()
        log(f"   Total [role=button]: {count}")
        
        candidates = []
        for i in range(min(count, 200)):
            try:
                btn = btns.nth(i)
                txt = (btn.inner_text() or "").strip()
                aria = btn.get_attribute("aria-label") or ""
                visible = btn.is_visible(timeout=200)
                
                combined = (txt + " " + aria).lower()
                
                keywords = [
                    'komentar', 'comment', 'lihat', 'view', 'muat', 'load',
                    'balasan', 'reply', 'replies', 'banyak', 'more', 'lainnya',
                    'selanjutnya', 'sebelumnya', 'previous', 'next', 'lagi'
                ]
                
                if any(k in combined for k in keywords):
                    candidates.append({
                        'index': i,
                        'text': txt[:80],
                        'aria': aria[:80],
                        'visible': visible,
                    })
            except:
                pass
        
        if candidates:
            log(f"   🎯 Kandidat tombol ditemukan: {len(candidates)}")
            for c in candidates:
                status = "✅ VISIBLE" if c['visible'] else "❌ hidden"
                log(f"      [{c['index']}] {status} | text=\"{c['text']}\" | aria=\"{c['aria']}\"")
        else:
            log("   ⚠️  TIDAK ADA kandidat tombol 'load more' ditemukan!")
            
    except Exception as e:
        log(f"   ⚠️  Button search error: {e}")
    
    # ── Method 2: Cari teks langsung di DOM ──
    try:
        result = page.evaluate("""() => {
            const found = [];
            const patterns = [
                /lihat\s+lebih\s+banyak\s+komentar/i,
                /view\s+more\s+comments/i,
                /lihat\s+komentar\s+sebelumnya/i,
                /view\s+previous\s+comments/i,
                /muat\s+lebih\s+banyak/i,
                /load\s+more/i,
                /lihat\s+\d+\s+balasan/i,
                /view\s+\d+\s+repl/i,
                /\d+\s+balasan/i,
                /\d+\s+repl/i,
            ];
            
            // Cari di semua text nodes
            const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
            let node;
            while (node = walker.nextNode()) {
                const txt = node.textContent?.trim();
                if (!txt || txt.length > 120) continue;
                
                for (const pat of patterns) {
                    if (pat.test(txt)) {
                        const parent = node.parentElement;
                        const grandparent = parent?.parentElement;
                        
                        // Cari ancestor yang clickable
                        let clickable = parent;
                        for (let i = 0; i < 5; i++) {
                            if (!clickable) break;
                            const role = clickable.getAttribute('role');
                            if (role === 'button' || clickable.tagName === 'BUTTON') break;
                            clickable = clickable.parentElement;
                        }
                        
                        found.push({
                            text: txt,
                            pattern: pat.toString(),
                            tagName: parent?.tagName,
                            role: parent?.getAttribute('role') || grandparent?.getAttribute('role') || '',
                            clickableRole: clickable?.getAttribute('role') || '',
                            clickableTag: clickable?.tagName || '',
                            visible: parent?.offsetParent !== null,
                        });
                        break;
                    }
                }
            }
            return found;
        }""")
        
        if result:
            log(f"   📝 Text pattern matches: {len(result)}")
            for r in result:
                log(f"      \"{r['text']}\" | tag={r['tagName']} role={r['role']} visible={r['visible']}")
        else:
            log("   📝 Tidak ada text pattern 'load more' ditemukan di DOM")
            
    except Exception as e:
        log(f"   ⚠️  Text pattern search error: {e}")


def _try_click_load_more(page):
    """Coba klik tombol load more yang ditemukan"""
    
    patterns_to_try = [
        "Lihat lebih banyak komentar",
        "View more comments",
        "Lihat komentar sebelumnya",
        "View previous comments",
        "Muat lebih banyak",
        "Load more",
    ]
    
    clicked_total = 0
    
    for text in patterns_to_try:
        selectors = [
            f"[role='button']:has-text('{text}')",
            f"div[role='button'] span:text-is('{text}')",
            f"span:text-is('{text}')",
            f"div:text-is('{text}')",
        ]
        
        for sel in selectors:
            try:
                els = page.locator(sel)
                count = els.count()
                if count > 0:
                    log(f"   🎯 Found '{text}' dengan selector '{sel}' ({count} elemen)")
                    for i in range(count):
                        try:
                            el = els.nth(i)
                            visible = el.is_visible(timeout=500)
                            log(f"      [{i}] visible={visible}")
                            if visible:
                                el.scroll_into_view_if_needed(timeout=2000)
                                el.click(timeout=3000)
                                clicked_total += 1
                                log(f"      ✅ KLIK BERHASIL!")
                                time.sleep(1.5)
                        except Exception as e:
                            log(f"      ❌ Klik gagal: {e}")
            except Exception as e:
                pass
    
    log(f"   Total berhasil diklik: {clicked_total}")


def _print_summary(page):
    """Print ringkasan akhir"""
    log("\n" + "=" * 60)
    log("📊 SUMMARY DEBUG")
    log("=" * 60)
    
    try:
        summary = page.evaluate("""() => {
            return {
                url: window.location.href,
                title: document.title,
                articleCount: document.querySelectorAll('[role="article"]').length,
                buttonCount: document.querySelectorAll('[role="button"]').length,
                dialogCount: document.querySelectorAll('[role="dialog"]').length,
                bodyLength: document.body.innerText?.length || 0,
                hasLoginForm: !!document.querySelector('input[type="password"]'),
                hasCheckpoint: window.location.href.includes('checkpoint'),
            };
        }""")
        
        log(f"URL          : {summary['url'][:80]}")
        log(f"Title        : {summary['title'][:60]}")
        log(f"Articles     : {summary['articleCount']}")
        log(f"Buttons      : {summary['buttonCount']}")
        log(f"Dialogs      : {summary['dialogCount']}")
        log(f"Body length  : {summary['bodyLength']}")
        log(f"Has login    : {summary['hasLoginForm']}")
        log(f"Checkpoint   : {summary['hasCheckpoint']}")
        
    except Exception as e:
        log(f"Summary error: {e}")
    
    log(f"\n📁 Output folder: {DEBUG_DIR}/")
    log(f"📸 Screenshots: {TS}_01_*.png ... {TS}_10_*.png")
    log(f"📋 DOM snapshots: {TS}_*_dom.json")
    log(f"📝 Log: {LOG_FILE}")


# ── ENTRY POINT ──────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  FB SCRAPER DEBUG TOOL")
    print("=" * 60)
    
    url = input("\n🔗 URL post Facebook: ").strip()
    if not url:
        url = "https://www.facebook.com/share/p/1Dwc7NsdW7/"
    
    if not os.path.exists(FB_CHROME_PROFILE) or not os.listdir(FB_CHROME_PROFILE):
        print(f"\n❌ Profile tidak ditemukan: {FB_CHROME_PROFILE}")
        exit(1)
    
    run_debug(url, max_comments=30)