# ============================================================
# FACEBOOK PROFILE DEBUGGER
#
# Script ini akan:
#   1. Buka profile FB
#   2. Scroll & wait
#   3. DUMP semua yang bisa di-dump ke folder fb_debug_output/:
#      - page_full.html       → HTML raw
#      - page_text.txt        → inner_text full
#      - screenshot.png       → screenshot full page
#      - meta_tags.json       → semua <meta>
#      - h1_h2_h3.json        → semua heading
#      - links_with_count.json → link yang ada angka (kandidat followers/following)
#      - aria_labels.json     → semua aria-label dengan angka
#      - intro_section.txt    → khusus section Intro
#
# Tujuan: kita lihat persis Facebook serve apa, baru tweak regex/selector.
# ============================================================

import os
import json
import time
import re
from datetime import datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from colorama import Fore, init
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout

init(autoreset=True)
load_dotenv()

HEADLESS = False  # WAJIB False biar lihat browser-nya
PROXY = os.getenv("FB_PROXY", "")

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
DEBUG_DIR = os.path.join(os.getcwd(), "fb_debug_output")
os.makedirs(DEBUG_DIR, exist_ok=True)


def extract_username_from_url(url: str) -> str:
    url = url.strip()
    if not url.startswith('http') and '/' not in url:
        return url.lstrip('@')
    try:
        parsed = urlparse(url)
        path = parsed.path.strip('/')
        parts = [p for p in path.split('/') if p]
        if parts:
            if parts[0] in ('pages',) and len(parts) > 1:
                return parts[1]
            return parts[0]
    except Exception:
        pass
    return ""


class FacebookDebugger:
    def __init__(self):
        self.context = None
        self.page = None
        self.playwright = None

    def _build_context(self):
        self.playwright = sync_playwright().start()

        args = [
            "--window-size=1920,1080",
            "--window-position=0,0",
            "--disable-blink-features=AutomationControlled",
            "--disable-notifications",
            "--mute-audio",
            "--disable-features=AutomationControlled",
            "--exclude-switches=enable-automation",
        ]

        if PROXY:
            args.append(f"--proxy-server={PROXY}")

        stealth_script = """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            window.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en-US', 'en']});
        """

        context = self.playwright.chromium.launch_persistent_context(
            FB_CHROME_PROFILE,
            channel="chrome",
            headless=HEADLESS,
            args=args,
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            locale="id-ID",
            timezone_id="Asia/Jakarta",
        )

        context.on("page", lambda page: page.add_init_script(stealth_script))
        return context

    def initialize_browser(self):
        if self.context:
            return

        print(Fore.CYAN + "\n[*] Membuka browser Facebook...")
        self.context = self._build_context()
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()

        # JANGAN block resource apapun saat debug — biar full lihat
        print(Fore.CYAN + "   Buka homepage Facebook...")
        self.page.goto("https://www.facebook.com/")
        time.sleep(3)

        if "login" in self.page.url:
            print(Fore.RED + "[X] Redirect ke login page. Session expired.")
            self.close()
            exit(1)

        print(Fore.GREEN + "[OK] Browser Facebook siap")

    def close(self):
        try:
            if self.context:
                self.context.close()
            if self.playwright:
                self.playwright.stop()
        except:
            pass

    def debug_profile(self, url_or_username: str):
        username = extract_username_from_url(url_or_username) or "unknown"

        if url_or_username.startswith('http'):
            url = url_or_username
        else:
            url = f"https://www.facebook.com/{username}"

        if not self.context:
            self.initialize_browser()

        # Folder output untuk profile ini
        out_dir = os.path.join(DEBUG_DIR, f"{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
        os.makedirs(out_dir, exist_ok=True)
        print(Fore.CYAN + f"\n[*] Output ke: {out_dir}")

        try:
            print(Fore.CYAN + f"\n[*] Navigate ke: {url}")
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            try:
                self.page.wait_for_load_state("networkidle", timeout=15000)
            except PlaywrightTimeout:
                print(Fore.YELLOW + "   [!] networkidle timeout, lanjut")

            print(Fore.CYAN + "[*] Scroll untuk trigger lazy load...")
            for i in range(4):
                self.page.evaluate(f'window.scrollBy(0, {300 + i * 200})')
                time.sleep(2)
            self.page.evaluate('window.scrollTo(0, 0)')
            time.sleep(2)

            print(Fore.CYAN + "\n[*] DUMP semua data...")

            # ─── 1. SCREENSHOT FULL PAGE ─────────────────────
            try:
                screenshot_path = os.path.join(out_dir, "screenshot.png")
                self.page.screenshot(path=screenshot_path, full_page=True)
                print(Fore.GREEN + f"   [OK] screenshot.png")
            except Exception as e:
                print(Fore.RED + f"   [X] screenshot: {e}")

            # ─── 2. HTML FULL ────────────────────────────────
            try:
                html = self.page.content()
                with open(os.path.join(out_dir, "page_full.html"), "w", encoding="utf-8") as f:
                    f.write(html)
                print(Fore.GREEN + f"   [OK] page_full.html ({len(html):,} chars)")
            except Exception as e:
                print(Fore.RED + f"   [X] html: {e}")

            # ─── 3. INNER TEXT FULL ──────────────────────────
            try:
                text = self.page.inner_text('body')
                with open(os.path.join(out_dir, "page_text.txt"), "w", encoding="utf-8") as f:
                    f.write(text)
                print(Fore.GREEN + f"   [OK] page_text.txt ({len(text):,} chars)")
            except Exception as e:
                print(Fore.RED + f"   [X] text: {e}")

            # ─── 4. META TAGS ────────────────────────────────
            try:
                meta_data = self.page.evaluate("""() => {
                    const metas = document.querySelectorAll('meta');
                    const result = [];
                    for (const m of metas) {
                        const obj = {};
                        for (const attr of m.attributes) {
                            obj[attr.name] = attr.value;
                        }
                        result.push(obj);
                    }
                    return result;
                }""")
                with open(os.path.join(out_dir, "meta_tags.json"), "w", encoding="utf-8") as f:
                    json.dump(meta_data, f, indent=2, ensure_ascii=False)
                print(Fore.GREEN + f"   [OK] meta_tags.json ({len(meta_data)} tags)")
            except Exception as e:
                print(Fore.RED + f"   [X] meta_tags: {e}")

            # ─── 5. HEADINGS (H1, H2, H3) ────────────────────
            try:
                headings = self.page.evaluate("""() => {
                    const result = {h1: [], h2: [], h3: []};
                    for (const tag of ['h1', 'h2', 'h3']) {
                        const els = document.querySelectorAll(tag);
                        for (const el of els) {
                            const txt = (el.innerText || el.textContent || '').trim();
                            if (txt) result[tag].push(txt.substring(0, 200));
                        }
                    }
                    return result;
                }""")
                with open(os.path.join(out_dir, "headings.json"), "w", encoding="utf-8") as f:
                    json.dump(headings, f, indent=2, ensure_ascii=False)
                print(Fore.GREEN + f"   [OK] headings.json (h1={len(headings['h1'])}, h2={len(headings['h2'])}, h3={len(headings['h3'])})")
                # Print h1 untuk insight cepat
                if headings['h1']:
                    print(Fore.YELLOW + f"      H1 list:")
                    for h in headings['h1'][:5]:
                        print(Fore.YELLOW + f"        - '{h[:80]}'")
            except Exception as e:
                print(Fore.RED + f"   [X] headings: {e}")

            # ─── 6. LINKS DENGAN ANGKA (kandidat followers/following) ─
            try:
                links_with_num = self.page.evaluate("""() => {
                    const links = document.querySelectorAll('a');
                    const result = [];
                    for (const link of links) {
                        const txt = (link.innerText || link.textContent || '').trim();
                        const href = link.getAttribute('href') || '';
                        // Filter: harus ada angka & teks pendek
                        if (txt && txt.length < 100 && /[\\d]/.test(txt)) {
                            result.push({
                                text: txt,
                                href: href.substring(0, 200),
                                aria_label: link.getAttribute('aria-label') || ''
                            });
                        }
                    }
                    return result;
                }""")
                with open(os.path.join(out_dir, "links_with_count.json"), "w", encoding="utf-8") as f:
                    json.dump(links_with_num, f, indent=2, ensure_ascii=False)
                print(Fore.GREEN + f"   [OK] links_with_count.json ({len(links_with_num)} links)")
                # Print yang relevan ke followers/following
                print(Fore.YELLOW + f"      Links yang mengandung 'follow', 'suka', 'mengikuti':")
                count_shown = 0
                for link in links_with_num:
                    txt_lower = link['text'].lower()
                    href_lower = link['href'].lower()
                    if any(kw in txt_lower or kw in href_lower for kw in
                           ['follow', 'suka', 'mengikuti', 'pengikut', 'like', 'friend', 'teman']):
                        if count_shown < 15:
                            print(Fore.YELLOW + f"        - text='{link['text'][:50]}' | href='{link['href'][:60]}'")
                            count_shown += 1
            except Exception as e:
                print(Fore.RED + f"   [X] links_with_count: {e}")

            # ─── 7. ARIA-LABELS DENGAN ANGKA ─────────────────
            try:
                aria_data = self.page.evaluate("""() => {
                    const els = document.querySelectorAll('[aria-label]');
                    const result = [];
                    for (const el of els) {
                        const aria = el.getAttribute('aria-label') || '';
                        if (aria && /\\d/.test(aria) && aria.length < 300) {
                            result.push({
                                aria: aria,
                                tag: el.tagName.toLowerCase(),
                                role: el.getAttribute('role') || '',
                                text: (el.innerText || '').trim().substring(0, 100)
                            });
                        }
                    }
                    return result;
                }""")
                with open(os.path.join(out_dir, "aria_labels.json"), "w", encoding="utf-8") as f:
                    json.dump(aria_data, f, indent=2, ensure_ascii=False)
                print(Fore.GREEN + f"   [OK] aria_labels.json ({len(aria_data)} items)")
                # Print yang relevan
                print(Fore.YELLOW + f"      Aria-label yang mengandung kata kunci profile:")
                count_shown = 0
                for item in aria_data:
                    aria_lower = item['aria'].lower()
                    if any(kw in aria_lower for kw in
                           ['follow', 'suka', 'mengikuti', 'pengikut', 'like',
                            'menyukai', 'postingan', 'post', 'verifikasi', 'verified']):
                        if count_shown < 15:
                            print(Fore.YELLOW + f"        - <{item['tag']}> aria='{item['aria'][:100]}'")
                            count_shown += 1
            except Exception as e:
                print(Fore.RED + f"   [X] aria_labels: {e}")

            # ─── 8. INTRO SECTION (DETAIL) ───────────────────
            try:
                intro_data = self.page.evaluate("""() => {
                    const result = {
                        sections: [],
                        all_long_divs: []
                    };

                    // Cari semua section yang heading-nya "Intro" / "Perkenalan" / "About"
                    const headers = document.querySelectorAll('h1, h2, h3, span, div');
                    for (const h of headers) {
                        const txt = (h.innerText || '').trim();
                        if (['Intro', 'Perkenalan', 'About', 'Tentang'].some(k =>
                            txt === k || txt.startsWith(k + '\\n'))) {
                            // Ambil parent yang kemungkinan berisi konten intro
                            let parent = h;
                            for (let i = 0; i < 5; i++) {
                                parent = parent.parentElement;
                                if (!parent) break;
                            }
                            if (parent) {
                                result.sections.push({
                                    header: txt.substring(0, 50),
                                    content: parent.innerText.substring(0, 2000)
                                });
                            }
                        }
                    }

                    // Bonus: semua div[dir="auto"] dengan text panjang
                    const divs = document.querySelectorAll('div[dir="auto"], span[dir="auto"]');
                    const seen = new Set();
                    for (const d of divs) {
                        const txt = (d.innerText || '').trim();
                        if (txt && txt.length > 20 && txt.length < 500 && !seen.has(txt)) {
                            seen.add(txt);
                            result.all_long_divs.push(txt);
                        }
                    }
                    result.all_long_divs = result.all_long_divs.slice(0, 30);

                    return result;
                }""")
                with open(os.path.join(out_dir, "intro_section.json"), "w", encoding="utf-8") as f:
                    json.dump(intro_data, f, indent=2, ensure_ascii=False)
                print(Fore.GREEN + f"   [OK] intro_section.json ({len(intro_data['sections'])} sections)")
            except Exception as e:
                print(Fore.RED + f"   [X] intro: {e}")

            # ─── 9. VERIFIED CHECK ───────────────────────────
            try:
                verified_data = self.page.evaluate("""() => {
                    const result = {found: [], texts: []};
                    // Cek semua element dengan kata "verified" atau "diverifikasi"
                    const all = document.querySelectorAll('[aria-label], [title], [alt]');
                    for (const el of all) {
                        for (const attr of ['aria-label', 'title', 'alt']) {
                            const val = el.getAttribute(attr) || '';
                            if (val.toLowerCase().includes('verif') || val.toLowerCase().includes('diverif')) {
                                result.found.push({attr: attr, value: val, tag: el.tagName});
                            }
                        }
                    }
                    return result;
                }""")
                with open(os.path.join(out_dir, "verified_check.json"), "w", encoding="utf-8") as f:
                    json.dump(verified_data, f, indent=2, ensure_ascii=False)
                print(Fore.GREEN + f"   [OK] verified_check.json ({len(verified_data['found'])} matches)")
                if verified_data['found']:
                    print(Fore.YELLOW + f"      Verified indicators:")
                    for v in verified_data['found'][:5]:
                        print(Fore.YELLOW + f"        - [{v['attr']}]='{v['value'][:80]}'")
            except Exception as e:
                print(Fore.RED + f"   [X] verified: {e}")

            # ─── 10. SUMMARY ─────────────────────────────────
            summary = {
                "url": url,
                "username": username,
                "final_url": self.page.url,
                "title": self.page.title(),
                "scraped_at": datetime.now().isoformat(),
                "output_dir": out_dir,
            }
            with open(os.path.join(out_dir, "_SUMMARY.json"), "w", encoding="utf-8") as f:
                json.dump(summary, f, indent=2, ensure_ascii=False)

            print(Fore.GREEN + f"\n[OK] Debug selesai. Semua file di:")
            print(Fore.CYAN + f"     {out_dir}")
            print(Fore.YELLOW + f"\n[!] Buka folder di atas, upload ke Claude untuk analisa lanjutan.")
            print(Fore.YELLOW + f"    Yang paling penting:")
            print(Fore.YELLOW + f"      - meta_tags.json")
            print(Fore.YELLOW + f"      - headings.json")
            print(Fore.YELLOW + f"      - links_with_count.json")
            print(Fore.YELLOW + f"      - aria_labels.json")
            print(Fore.YELLOW + f"      - screenshot.png")

            input(Fore.CYAN + "\nPress Enter to close browser...")

        except Exception as e:
            print(Fore.RED + f"\n[X] Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    debugger = FacebookDebugger()
    try:
        user_input = input(
            "Masukkan URL/username Facebook untuk debug\n"
            "(contoh: https://facebook.com/PrabowoSubianto): "
        ).strip()

        if user_input:
            debugger.debug_profile(user_input)
        else:
            print(Fore.RED + "[X] Input kosong")
    finally:
        debugger.close()