# ============================================================
# FACEBOOK SCRAPER V2.1 — PATCHED
# ============================================================
# Fix v2.1-patch:
#   ✅ Reel/video: JS click bypass overlay untuk buka panel komentar
#   ✅ Fallback selector komentar untuk reel ([role='complementary'])
#   ✅ result["success"] selalu di-set (True/False)
#   ✅ Semua fitur original tetap ada
#   ✅ Debug aria-label reply + fallback nested detection (v2.1-patch2)
# ============================================================

import os
import re
import json
import time
import random
import hashlib
from datetime import datetime
from typing import List, Dict, Optional
from collections import Counter

from dotenv import load_dotenv
from colorama import Fore, init
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout

from browser_runtime import browser_channel_kwargs, fb_headless
from sentiment_analyzer_v2 import SentimentAnalyzerV2

init(autoreset=True)
load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────
HEADLESS               = fb_headless(True)
PROXY                  = os.getenv("FB_PROXY", "")
MAX_COMMENTS           = int(os.getenv("FB_MAX_COMMENTS", 200))
DELAY_BETWEEN_REQUESTS = int(os.getenv("FB_DELAY_BETWEEN_REQUESTS", 10))
SENTIMENT_MODE         = os.getenv("SENTIMENT_MODE", "hybrid")
SCRAPE_REACTORS        = os.getenv("FB_SCRAPE_REACTORS", "0") == "1"
MAX_REACTORS           = int(os.getenv("FB_MAX_REACTORS", 200))
ALL_COMMENTS_FALLBACK_TARGET = int(os.getenv("FB_ALL_COMMENTS_FALLBACK_TARGET", 3000))

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
OUTPUT_DIR        = "output_facebook"
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(FB_CHROME_PROFILE, exist_ok=True)


# ============================================================
# MAIN SCRAPER
# ============================================================

class FacebookScraperV21:

    def __init__(self, sentiment_mode: str = SENTIMENT_MODE):
        print(Fore.CYAN + f"\n🧠 Initializing Sentiment Analyzer (mode: {sentiment_mode})...")
        self.sentiment = SentimentAnalyzerV2(mode=sentiment_mode, verbose=True)

        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self._last_scrape_time: float = 0.0
        self._min_gap_seconds: int = 20

        self._has_cookie_session = False
        try:
            from fb_cookie_injector import has_valid_session
            self._has_cookie_session = has_valid_session()
            if self._has_cookie_session:
                print(Fore.GREEN + "✅ Cookie session Facebook ditemukan")
        except ImportError:
            pass

        if not self._has_cookie_session:
            if not os.path.exists(FB_CHROME_PROFILE) or not os.listdir(FB_CHROME_PROFILE):
                print(Fore.RED + f"\n❌ Tidak ada session maupun Chrome profile!")
                print(Fore.YELLOW + "\n📋 Pilihan login:")
                print(Fore.CYAN + "   OPSI 1 (Rekomendasi): python fb_cookie_injector.py")
                print(Fore.CYAN + "   OPSI 2: python fb_login_helper.py")
                exit(1)
            print(Fore.GREEN + f"✅ Facebook Chrome profile ditemukan: {FB_CHROME_PROFILE}")

    def __enter__(self): return self
    def __exit__(self, *_): self.close()

    # ── INTERNAL ACCESSORS (narrow Optional → tipe konkret) ────────
    @property
    def pg(self) -> Page:
        if self.page is None:
            raise RuntimeError("Browser belum diinisialisasi. Panggil initialize_browser() dulu.")
        return self.page

    @property
    def ctx(self) -> BrowserContext:
        if self.context is None:
            raise RuntimeError("Browser belum diinisialisasi. Panggil initialize_browser() dulu.")
        return self.context

    # ── BROWSER SETUP ──────────────────────────────────────────────

    def _build_context(self):
        self.playwright = sync_playwright().start()

        args = [
            "--window-size=1920,1080",
            "--window-position=0,0",
            "--disable-blink-features=AutomationControlled",
            "--disable-notifications",
            "--mute-audio",
            "--disable-infobars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-features=AutomationControlled",
            "--exclude-switches=enable-automation",
        ]

        if PROXY:
            args.append(f"--proxy-server={PROXY}")

        stealth_script = """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {
                get: () => [
                    {name: 'PDF Viewer', filename: 'internal-pdf-viewer'},
                    {name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer'},
                    {name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer'},
                ]
            });
            window.chrome = {
                runtime: {},
                csi: function() { return {}; },
                loadTimes: function() {
                    return {
                        requestTime: Date.now()/1000 - 1,
                        startLoadTime: Date.now()/1000 - 1,
                        commitLoadTime: Date.now()/1000 - 0.9,
                        finishDocumentLoadTime: Date.now()/1000 - 0.5,
                        finishLoadTime: Date.now()/1000 - 0.3,
                        firstPaintTime: Date.now()/1000 - 0.4,
                    };
                },
            };
            Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en-US', 'en']});
            Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
            Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}
            try { delete navigator.__proto__.webdriver; } catch(e) {}
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications'
                    ? Promise.resolve({state: Notification.permission})
                    : originalQuery(parameters)
            );
        """

        context = self.playwright.chromium.launch_persistent_context(
            FB_CHROME_PROFILE,
            **browser_channel_kwargs(),
            headless=HEADLESS,
            args=args,
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            bypass_csp=True,
            java_script_enabled=True,
        )
        def _apply_stealth(p: Page) -> None:
            p.add_init_script(stealth_script)

        context.on("page", _apply_stealth)
        return context

    def _inject_cookies_if_available(self):
        try:
            from fb_cookie_injector import inject_cookies_sync, has_valid_session
            if has_valid_session():
                n = inject_cookies_sync(self.context)
                print(Fore.GREEN + f"   🍪 {n} cookies Facebook diinject dari session/fb_session.json")
                return True
        except ImportError:
            pass
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Cookie inject gagal: {e}")
        return False

    def _is_logged_in(self) -> bool:
        try:
            cookies = self.ctx.cookies("https://www.facebook.com")
            c_user = next((c for c in cookies if c.get("name") == "c_user"), None)
            xs = next((c for c in cookies if c.get("name") == "xs"), None)
            if c_user and c_user.get("value") and xs and xs.get("value"):
                return True
            return False
        except Exception:
            return False

    def initialize_browser(self):
        if self.context:
            return

        print(Fore.CYAN + "\n🌐 Menjalankan browser Facebook background (stealth)...")
        self.context = self._build_context()
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()

        def block_heavy_resources(route):
            try:
                resource_type = route.request.resource_type
                url = route.request.url.lower()
                if resource_type in ["image", "media", "font"]:
                    if "favicon" in url or "icon" in url:
                        route.continue_()
                    else:
                        route.abort()
                else:
                    route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        self.pg.route("**/*", block_heavy_resources)
        self._inject_cookies_if_available()

        print(Fore.CYAN + "   ☕ Warming up — buka homepage Facebook...")
        self.pg.goto("https://www.facebook.com/")
        time.sleep(4)
        self._close_cookie_banners()

        if "login" in self.pg.url:
            print(Fore.RED + "❌ Redirect ke login page. Session expired.")
            print(Fore.YELLOW + "\n   ➡️  Jalankan: python fb_cookie_injector.py")
            self.close()
            exit(1)

        if not self._is_logged_in():
            print(Fore.RED + "\n❌ Browser TERBUKA tapi BELUM LOGIN!")
            print(Fore.YELLOW + "\n   ➡️  Jalankan: python fb_cookie_injector.py")
            self.close()
            exit(1)

        print(Fore.GREEN + "✅ Browser Facebook siap (LOGGED IN ✓)")

    # ── POPUP HANDLING ─────────────────────────────────────────────

    def _close_cookie_banners(self):
        selectors = [
            "[data-testid='cookie-policy-manage-dialog-accept-button']",
            "button:has-text('Terima semua')",
            "button:has-text('Accept all')",
            "button:has-text('Hanya cookie yang diperlukan')",
            "button:has-text('Only allow essential cookies')",
        ]
        for sel in selectors:
            try:
                el = self.pg.locator(sel)
                if el.count() > 0 and el.first.is_visible(timeout=1000):
                    el.first.click(timeout=2000)
                    time.sleep(0.8)
            except Exception:
                pass

    def _close_non_post_popups(self):
        try:
            dialogs = self.pg.locator("[role='dialog']")
            count = dialogs.count()
            for i in range(count):
                try:
                    dlg = dialogs.nth(i)
                    if not dlg.is_visible(timeout=300):
                        continue
                    text = (dlg.inner_text() or "")[:200].lower()
                    post_indicators = [
                        "postingan", "komentar", "suka", "bagikan", "balasan",
                        "post", "comment", "like", "share", "reply",
                    ]
                    if any(ind in text for ind in post_indicators):
                        continue
                    close_btn = dlg.locator(
                        "[aria-label='Tutup'], [aria-label='Close'], [aria-label='Dismiss']"
                    )
                    if close_btn.count() > 0 and close_btn.first.is_visible(timeout=300):
                        close_btn.first.click(timeout=1000)
                        time.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            pass

    def close(self):
        try:
            if self.context:
                self.ctx.close()
                self.context = None
            if self.playwright:
                self.playwright.stop()
                self.playwright = None
        except Exception:
            pass

    def _enforce_rate_limit(self):
        if self._last_scrape_time <= 0:
            return
        elapsed = time.time() - self._last_scrape_time
        if elapsed < self._min_gap_seconds:
            wait = self._min_gap_seconds - elapsed
            print(Fore.YELLOW + f"\n⏱️  Rate-limit guard: tunggu {wait:.0f}s...")
            time.sleep(wait)

    # ── CHECKPOINT / WARM-UP (anti rate-limit) ────────────────────

    def _is_on_post(self) -> bool:
        """True jika benar-benar di halaman post (ada artikel/panel komentar), bukan homepage."""
        try:
            return bool(self.pg.evaluate(r"""() => {
                const url = location.href;
                if (/^https:\/\/(www|web|m)\.facebook\.com\/?(\?|#|$)/.test(url)) return false;
                if (/\/(login|checkpoint)/.test(url)) return false;
                if (document.querySelectorAll('[role="article"]').length > 0) return true;
                if (document.querySelector('[role="complementary"]')) return true;
                const btns = document.querySelectorAll('[aria-label]');
                for (const b of btns) {
                    const a = (b.getAttribute('aria-label') || '').toLowerCase();
                    if (a === 'beri komentar' || a === 'komentari' || a === 'comment') return true;
                }
                return false;
            }"""))
        except Exception:
            return True

    def _detect_rate_limit(self) -> bool:
        """Deteksi pesan rate-limit / pembatasan sementara dari Facebook."""
        try:
            return bool(self.pg.evaluate(r"""() => {
                const t = (document.body.innerText || '').toLowerCase();
                return /(terlalu cepat|coba lagi nanti|sementara diblokir|untuk sementara|temporarily blocked|try again later|you're temporarily|kami membatasi|dibatasi sementara|melebihi batas)/.test(t);
            }"""))
        except Exception:
            return False

    def _warmup(self, seconds: float = 10.0):
        """Warm-up ala manusia: buka homepage, scroll pelan, jeda — menurunkan rate-limit."""
        print(Fore.YELLOW + f"   🔥 Warm-up {seconds:.0f}s (hindari rate-limit)...")
        try:
            self.pg.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
            steps = max(2, int(seconds / 2.5))
            for _ in range(steps):
                self.pg.evaluate(f"window.scrollBy(0, {random.randint(300, 800)})")
                time.sleep(random.uniform(0.9, 2.0))
            self.pg.evaluate("window.scrollTo(0, 0)")
            time.sleep(random.uniform(1.0, 2.0))
        except Exception:
            time.sleep(seconds)

    # ── URL PARSER & NAVIGASI ──────────────────────────────────────

    def _navigate_and_extract_id(self, url: str) -> tuple:
        print(Fore.YELLOW + f"\n🌍 Navigasi ke: {url[:80]}")

        try:
            self.pg.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PlaywrightTimeout:
            print(Fore.YELLOW + "   ⚠️  Timeout goto, lanjut...")

        print(Fore.CYAN + "   ⏳ Menunggu redirect selesai...")
        stable_count = 0
        prev_url = ""
        for _ in range(20):
            time.sleep(0.5)
            cur_url = self.pg.url
            if cur_url == prev_url:
                stable_count += 1
                if stable_count >= 4:
                    break
            else:
                stable_count = 0
                prev_url = cur_url

        final_url = self.pg.url
        print(Fore.CYAN + f"   ✅ URL final: {final_url[:80]}")

        if "login" in final_url or "checkpoint" in final_url:
            raise Exception("Redirect ke login/checkpoint! Session expired, import ulang cookies.")

        try:
            self.pg.wait_for_load_state("networkidle", timeout=8000)
        except PlaywrightTimeout:
            pass

        self._close_cookie_banners()
        self._close_non_post_popups()

        current_url = self.pg.url
        homepage_patterns = [
            r"^https://www\.facebook\.com/?$",
            r"^https://www\.facebook\.com/\?",
            r"^https://www\.facebook\.com/#",
        ]
        url_changed_to_home = any(re.match(p, current_url) for p in homepage_patterns)

        if url_changed_to_home and final_url != current_url:
            print(Fore.YELLOW + "   ⚠️  URL berubah ke homepage — re-navigate...")
            try:
                self.pg.goto(final_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
                try:
                    self.pg.wait_for_load_state("networkidle", timeout=8000)
                except PlaywrightTimeout:
                    pass
            except PlaywrightTimeout:
                pass

        final_url = self.pg.url
        print(Fore.GREEN + f"   ✅ URL aktif: {final_url[:80]}")

        post_id = self._extract_post_id(final_url)
        if not post_id:
            post_id = self._extract_post_id_from_dom()
        if not post_id:
            post_id = self._extract_post_id_from_patterns(final_url)

        return final_url, post_id

    def _extract_post_id(self, url: str) -> Optional[str]:
        m = re.search(r"/posts/(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/videos/(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/reel/(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/reels/(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/photos/[^/]+/(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"fbid=(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"/groups/\d+/posts/(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"story_fbid=(\d+)", url)
        if m: return m.group(1)
        m = re.search(r"(pfbid[A-Za-z0-9_-]+)", url)
        if m: return m.group(1)
        m = re.search(r"/permalink/(\d+)", url)
        if m: return m.group(1)
        return None

    def _extract_post_id_from_dom(self) -> Optional[str]:
        try:
            result = self.pg.evaluate("""() => {
                const articles = document.querySelectorAll('[role="article"]');
                for (const article of articles) {
                    const ft = article.getAttribute('data-ft');
                    if (ft) {
                        try {
                            const parsed = JSON.parse(ft);
                            if (parsed.mf_story_key) return parsed.mf_story_key;
                        } catch(e) {}
                    }
                }
                const meta = document.querySelector('meta[property="al:ios:url"]');
                if (meta) {
                    const m = meta.content.match(/\\/post\\/([^\\/]+)/);
                    if (m) return m[1];
                }
                const html = document.body.innerHTML;
                const m = html.match(/(pfbid[A-Za-z0-9_-]{20,})/);
                if (m) return m[1];
                return null;
            }""")
            return result
        except Exception:
            return None

    def _detect_post_type(self, url: str) -> str:
        u = (url or "").lower()
        if "/reel/" in u or "/reels/" in u:
            return "reel"
        if "/videos/" in u or "/watch" in u or "/share/v/" in u:
            return "video"
        if "/photo" in u or "/photos/" in u:
            return "photo"
        return "post"

    def _extract_post_id_from_patterns(self, url: str) -> Optional[str]:
        patterns = [
            r"/share/p/([A-Za-z0-9_-]+)",
            r"/share/v/([A-Za-z0-9_-]+)",
            r"/share/r/([A-Za-z0-9_-]+)",
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    # ── METADATA EXTRACTION ───────────────────────────────────────

    def _get_post_metadata(self) -> Dict:
        meta = {"total_likes": 0, "total_comments": 0, "total_shares": 0, "caption": ""}
        try:
            result = self.pg.evaluate(r"""() => {
                const out = {likes_raw: '', comments_raw: '', shares_raw: '', caption: ''};

                // ── Strategi A: Reels Viewer / action bar modern ──
                // innerText tombol aksi LANGSUNG berisi jumlahnya (mis. "12,9 rb", "301", "31")
                const byAria = (re) => {
                    let val = '';
                    document.querySelectorAll('[aria-label]').forEach(el => {
                        if (val) return;
                        const a = el.getAttribute('aria-label') || '';
                        if (a.length < 55 && re.test(a)) {
                            const t = (el.innerText || '').trim();
                            if (t && t.length < 15 && /\d/.test(t)) val = t;
                        }
                    });
                    return val;
                };
                out.likes_raw    = byAria(/^(beri reaksi|suka|like)$/i);
                out.comments_raw = byAria(/^(beri komentar|komentari|comment)$/i);
                out.shares_raw   = byAria(/^(kirim ini|bagikan|share|kirim)/i);

                // ── Strategi B (fallback post biasa): reaksi dari aria "Suka: N orang" ──
                if (!out.likes_raw) {
                    document.querySelectorAll('[aria-label]').forEach(el => {
                        if (out.likes_raw) return;
                        const a = el.getAttribute('aria-label') || '';
                        const m = a.match(/(?:suka|like|semua reaksi|all reactions|reaksi)\D{0,4}([\d][\d.,]*\s*(?:rb|jt|k|m)?)/i);
                        if (m) out.likes_raw = m[1];
                    });
                }

                // ── Fallback komentar/share dari teks halaman ──
                const bodyText = document.body.innerText || '';
                if (!out.comments_raw) {
                    const m = bodyText.match(/([\d][\d.,]*\s*(?:rb|jt)?)\s*komentar/i);
                    if (m) out.comments_raw = m[1];
                }
                if (!out.shares_raw) {
                    // Coba berbagai pola shares di halaman post
                    const sharePatterns = [
                        /([\d][\d.,]*\s*(?:rb|jt)?)\s*(?:kali\s+dibagikan|x\s+dibagikan)/i,
                        /([\d][\d.,]*\s*(?:rb|jt)?)\s*dibagikan/i,
                        /dibagikan\s+([\d][\d.,]*\s*(?:rb|jt)?)\s*kali/i,
                        /([\d][\d.,]*\s*(?:rb|jt)?)\s*shares?/i,
                    ];
                    for (const pat of sharePatterns) {
                        const m = bodyText.match(pat);
                        if (m) { out.shares_raw = m[1]; break; }
                    }
                }
                // Coba juga dari aria-label tombol share di dalam article
                if (!out.shares_raw) {
                    document.querySelectorAll('[aria-label]').forEach(el => {
                        if (out.shares_raw) return;
                        const a = (el.getAttribute('aria-label') || '').toLowerCase();
                        if (a.includes('bagikan') || a.includes('share')) {
                            // Kadang ada angka di teks elemennya
                            const t = (el.innerText || '').trim();
                            if (t && /^\d/.test(t) && t.length < 12) {
                                out.shares_raw = t;
                            }
                        }
                    });
                }

                // ── Caption ──
                // Blokir teks "chrome" Facebook (homepage/notifikasi) agar tidak bocor jadi caption
                const CHROME = /(selamat datang di facebook|belum dibaca|ketuk di sini|welcome to facebook|orang yang anda kenal|saran teman|jadikan profil|tandai semua|tandai sebagai|notifikasi|masuk ke facebook|buat akun baru|log in to facebook|people you may know|mungkin anda kenal|lihat semua|jelajahi)/i;
                const okCap = (t) => t && t.length > 4 && t.length < 2000 && !CHROME.test(t) && !/^facebook$/i.test(t.trim());

                // 1) og:description / meta description (paling reliable untuk caption publik)
                const ogEl = document.querySelector('meta[property="og:description"]')
                          || document.querySelector('meta[name="description"]');
                const og = ogEl ? (ogEl.getAttribute('content') || '').trim() : '';
                if (okCap(og)) out.caption = og;

                // 2) selector message khusus
                if (!out.caption) {
                    const capSel = ['[data-ad-preview="message"]', '[data-ad-comet-preview="message"]', '.userContent', '[data-testid="post_message"]'];
                    for (const sel of capSel) {
                        const el = document.querySelector(sel);
                        const t = el ? (el.textContent || '').trim() : '';
                        if (okCap(t)) { out.caption = t; break; }
                    }
                }

                // 3) Reel/video: teks dir=auto di LUAR [role="article"], filter chrome
                if (!out.caption) {
                    const articles = document.querySelectorAll('[role="article"]');
                    const isInArticle = (el) => {
                        for (const art of articles) if (art.contains(el)) return true;
                        return false;
                    };
                    let best = '';
                    document.querySelectorAll('span[dir="auto"], div[dir="auto"]').forEach(el => {
                        if (isInArticle(el)) return;
                        const t = (el.textContent || '').trim();
                        if (!okCap(t)) return;
                        if (/^[\d.,\s]+(rb|jt)?$/i.test(t)) return;
                        if (t.length > best.length) best = t;
                    });
                    out.caption = best;
                }
                return out;
            }""")

            meta["total_likes"]    = self._parse_number(result.get("likes_raw", ""))
            meta["total_comments"] = self._parse_number(result.get("comments_raw", ""))
            meta["total_shares"]   = self._parse_number(result.get("shares_raw", ""))
            meta["caption"]        = result.get("caption", "")

        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Metadata extract error: {e}")

        return meta

    def _parse_number(self, text: str) -> int:
        if not text:
            return 0
        text = text.strip().replace(" ", "").replace("\u00a0", "")
        m = re.search(r'([\d.,]+)\s*[Kk]', text)
        if m:
            try: return int(float(m.group(1).replace(",", ".")) * 1000)
            except: pass
        m = re.search(r'([\d.,]+)\s*[Mm]', text)
        if m:
            try: return int(float(m.group(1).replace(",", ".")) * 1000000)
            except: pass
        m = re.search(r'([\d.,]+)\s*rb', text, re.I)
        if m:
            try: return int(float(m.group(1).replace(",", ".")) * 1000)
            except: pass
        clean = re.sub(r'[^\d]', '', text)
        try: return int(clean) if clean else 0
        except: return 0

    def _extract_post_extras(self) -> Dict:
        """
        Ekstra dari postingan: tag 'bersama/with' (orang yang di-tag),
        mention di caption, tipe & jumlah media, lokasi.
        """
        extras = {"with_tags": [], "with_others": 0, "mentions": [],
                  "media_type": "", "media_count": 0, "location": "", "media_urls": []}
        try:
            result = self.pg.evaluate(r"""() => {
                const out = {with_tags: [], with_others: 0, mentions: [],
                             media_type: '', media_count: 0, location: '', media_urls: []};

                // Postingan utama = [role=article] pertama yang BUKAN komentar/balasan
                let main = null;
                document.querySelectorAll('[role="article"]').forEach(a => {
                    if (main) return;
                    const al = a.getAttribute('aria-label') || '';
                    if (!/komentar|balasan|comment|repl/i.test(al)) main = a;
                });
                const scope = main || document.body;
                const txt   = scope.innerText || '';

                // "bersama X dan N orang lainnya" / "is with X and N others"
                let wm = txt.match(/bersama\s+(.+?)(?:\s+dan\s+(\d+)\s+orang lainnya|[\.\n]|$)/i)
                      || txt.match(/\bis with\s+(.+?)(?:\s+and\s+(\d+)\s+others|[\.\n]|$)/i);
                if (wm) {
                    out.with_tags = wm[1].split(/,|\sdan\s|\sand\s/)
                        .map(s => s.trim()).filter(s => s && s.length < 50);
                    if (wm[2]) out.with_others = parseInt(wm[2]) || 0;
                }

                // mentions = link profil di dalam postingan utama (selain penulis)
                if (main) {
                    const author = (main.querySelector('h2,h3,strong')?.innerText || '').trim();
                    main.querySelectorAll('a[href*="facebook.com/"], a[href*="/profile.php"]').forEach(el => {
                        const t = (el.textContent || '').trim();
                        if (t && t.length < 50 && t !== author && !/^\d/.test(t) &&
                            !out.mentions.includes(t) && !/yang lalu|ago|·/i.test(t)) {
                            out.mentions.push(t);
                        }
                    });
                    out.mentions = out.mentions.slice(0, 20);

                    const imgs = main.querySelectorAll('img[src*="scontent"]');
                    imgs.forEach(im => {
                        const s = im.getAttribute('src') || '';
                        // abaikan gambar kecil (avatar/emoji): cari yang berukuran wajar
                        const w = im.naturalWidth || im.width || 0;
                        if (s && !out.media_urls.includes(s) && (w === 0 || w >= 120)) out.media_urls.push(s);
                    });
                    out.media_urls = out.media_urls.slice(0, 10);
                    out.media_count = out.media_urls.length;
                    if (out.media_count > 1) out.media_type = 'album';
                    else if (out.media_count === 1) out.media_type = 'photo';

                    const place = main.querySelector('a[href*="/places/"], a[href*="maps"]');
                    if (place) out.location = (place.textContent || '').trim().slice(0, 80);
                }

                // media video: cek di scope (reel viewer tidak punya main article)
                const vid = scope.querySelector('video');
                if (vid) {
                    out.media_type = 'video';
                    const poster = vid.getAttribute('poster') || '';
                    if (poster && !out.media_urls.includes(poster)) out.media_urls.unshift(poster);
                }
                return out;
            }""")
            extras.update({k: result.get(k, extras[k]) for k in extras})
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Extras extract error: {e}")
        return extras

    # ── REEL/VIDEO: BUKA PANEL KOMENTAR ──────────────────────────

    def _scrape_post_reactors(self, max_reactors: int = MAX_REACTORS) -> List[Dict]:
        """
        Best-effort scrape akun yang muncul di dialog reaction.
        Facebook hanya menampilkan nama yang berhasil dimuat di DOM.
        """
        if max_reactors <= 0:
            return []

        print(Fore.CYAN + f"\n   [REACTIONS] Membuka daftar reaction (limit: {max_reactors})...")
        try:
            clicked = self.pg.evaluate(r"""() => {
                const bad = /(komentar|comment|bagikan|share|kirim|send|balas|reply)/i;
                const good = /(semua reaksi|all reactions|suka:|like:|reaksi|reaction|people reacted|orang)/i;
                const candidates = [];
                document.querySelectorAll('[aria-label], a[href], [role="button"]').forEach(el => {
                    const aria = el.getAttribute('aria-label') || '';
                    const text = (el.innerText || el.textContent || '').trim();
                    const combined = `${aria} ${text}`.trim();
                    if (!combined || bad.test(combined) || !good.test(combined) || !/\d|rb|ribu|k|jt|juta/i.test(combined)) return;
                    const target = el.closest('a[href], [role="button"]') || el;
                    const rect = target.getBoundingClientRect();
                    if (rect.width < 4 || rect.height < 4) return;
                    candidates.push({ target, score: aria.length < 120 ? 2 : 1 });
                });
                candidates.sort((a, b) => b.score - a.score);
                const chosen = candidates[0]?.target;
                if (!chosen) return false;
                chosen.scrollIntoView({ block: 'center', behavior: 'auto' });
                chosen.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, view: window }));
                return true;
            }""")
            if not clicked:
                print(Fore.YELLOW + "   [REACTIONS] Tombol reaction tidak ditemukan")
                self._debug_reaction_dialog_snapshot("reaction_button_not_found")
                return []

            time.sleep(2.5)
            reactors: List[Dict] = []
            seen = set()
            stable = 0

            max_rounds = max(40, min(140, max_reactors // 8 + 30))
            for _ in range(max_rounds):
                batch = self.pg.evaluate(r"""(limit) => {
                    const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                    const badName = /(tambahkan teman|add friend|ikuti|follow|mengikuti|message|pesan|lihat profil|view profile|teman bersama|mutual|reaction|reaksi|suka|like)$/i;
                    const badUrl = /(\/help\/|\/privacy\/|\/legal\/|\/groups\/|\/events\/|\/watch\/|\/reel\/|\/videos\/|\/photo|\/posts\/|\/permalink\/|\/ufi\/reaction)/i;
                    const isProfileHref = (href) =>
                        href && href.includes('facebook.com') && !badUrl.test(href) &&
                        (/facebook\.com\/[a-zA-Z0-9._-]{3,}/.test(href) || /profile\.php\?id=\d+/.test(href));
                    const pickName = (lines) => lines.find(line =>
                        line.length >= 2 && line.length <= 90 &&
                        !badName.test(line) && !/^\d/.test(line) && !line.includes('facebook.com')
                    );
                    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).pop() || document.body;
                    const rows = [];
                    const pushed = new Set();
                    const addRow = (name, href) => {
                        const url = (href || '').split('?')[0].split('#')[0];
                        const key = (url || name).toLowerCase();
                        if (!name || pushed.has(key)) return;
                        pushed.add(key);
                        rows.push({ name, profile_url: url, reaction_type: '' });
                    };

                    // Pass 1: nama ada di dalam anchor profil
                    [...dialog.querySelectorAll('a[href]')].forEach(a => {
                        const href = a.href || a.getAttribute('href') || '';
                        if (!isProfileHref(href)) return;
                        const name = pickName(clean(a.innerText || a.textContent || '').split(/\n+/).map(clean).filter(Boolean));
                        if (name) addRow(name, href);
                    });

                    // Pass 2 (fallback): baris list — anchor avatar tanpa teks, nama di span sebelah
                    if (rows.length === 0) {
                        const listRows = [
                            ...dialog.querySelectorAll('[role="listitem"]'),
                            ...dialog.querySelectorAll('div[role="none"] > div, ul > li'),
                        ];
                        listRows.forEach(row => {
                            const a = [...row.querySelectorAll('a[href]')].find(x => isProfileHref(x.href || x.getAttribute('href') || ''));
                            const href = a ? (a.href || a.getAttribute('href') || '') : '';
                            const spans = [...row.querySelectorAll('span[dir="auto"], strong, span')]
                                .map(s => clean(s.innerText || s.textContent || '')).filter(Boolean);
                            const name = pickName(spans);
                            if (name) addRow(name, href);
                        });
                    }

                    return rows.slice(0, limit);
                }""", max_reactors)

                added = 0
                for item in batch:
                    key = (item.get("profile_url") or item.get("name") or "").lower()
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    reactors.append(item)
                    added += 1
                    if len(reactors) >= max_reactors:
                        break
                if len(reactors) >= max_reactors:
                    break

                scrolled = self.pg.evaluate(r"""() => {
                    const dialog = Array.from(document.querySelectorAll('[role="dialog"]')).pop();
                    if (!dialog) return false;
                    let moved = false;
                    let best = null, roomBest = 0;
                    [dialog, ...dialog.querySelectorAll('*')].forEach(el => {
                        const s = getComputedStyle(el);
                        if ((s.overflowY === 'auto' || s.overflowY === 'scroll' || el === dialog) && el.scrollHeight > el.clientHeight + 50) {
                            const room = el.scrollHeight - el.scrollTop - el.clientHeight;
                            if (room > roomBest) { roomBest = room; best = el; }
                        }
                    });
                    if (best && roomBest > 2) {
                        best.scrollTop = Math.min(best.scrollHeight, best.scrollTop + Math.max(500, best.clientHeight * 0.95));
                        moved = true;
                    }
                    dialog.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 900 }));
                    window.dispatchEvent(new WheelEvent('wheel', { bubbles: true, cancelable: true, deltaY: 900 }));
                    return moved || roomBest > 2;
                }""")
                stable = stable + 1 if added == 0 else 0
                if stable >= 8 or (not scrolled and stable >= 3):
                    break
                time.sleep(0.8 if added == 0 else 0.45)

            if not reactors:
                self._debug_reaction_dialog_snapshot("reaction_dialog_empty")
            try:
                self.pg.keyboard.press("Escape")
            except Exception:
                pass
            print(Fore.GREEN + f"   [REACTIONS] {len(reactors)} akun")
            return reactors[:max_reactors]
        except Exception as e:
            print(Fore.YELLOW + f"   [REACTIONS] gagal: {e}")
            return []

    def _open_reel_comments(self) -> bool:
        """
        FIX: Reel/video Facebook butuh klik tombol 'Komentari' dulu.
        Tombol diblok overlay, jadi pakai JS click (dispatchEvent).
        """
        try:
            current_url = self.pg.url
            is_reel_or_video = any(x in current_url for x in [
                "/reel/", "/reels/", "/videos/", "/watch/", "/share/v/"
            ])
            if not is_reel_or_video:
                return False

            print(Fore.CYAN + "   🎬 Reel/video terdeteksi — buka panel komentar via JS click...")

            clicked_label = self.pg.evaluate("""() => {
                // Cari tombol Komentari / Comment via aria-label
                const patterns = [/^Komentari$/i, /^Comment$/i, /^Komentar$/i];
                const buttons = document.querySelectorAll('[role="button"][aria-label]');
                for (const btn of buttons) {
                    const label = (btn.getAttribute('aria-label') || '').trim();
                    if (patterns.some(p => p.test(label))) {
                        btn.dispatchEvent(new MouseEvent('click', {
                            bubbles: true, cancelable: true, view: window
                        }));
                        return label;
                    }
                }
                // Fallback: cari semua [role="button"] via innerText
                const allBtns = document.querySelectorAll('[role="button"]');
                for (const btn of allBtns) {
                    const txt = (btn.innerText || btn.textContent || '').trim();
                    if (/^(Komentari|Komentar|Comment)$/i.test(txt)) {
                        btn.dispatchEvent(new MouseEvent('click', {
                            bubbles: true, cancelable: true, view: window
                        }));
                        return txt;
                    }
                }
                return null;
            }""")

            if clicked_label:
                print(Fore.GREEN + f"   ✅ JS click: '{clicked_label}'")
                time.sleep(4)

                # Tunggu panel komentar muncul
                comment_selectors = [
                    "[role='complementary']",
                    "div[aria-label*='omentar']",
                    "div[aria-label*='omment']",
                    "[role='article']",
                    "div[data-pagelet*='omment']",
                    "ul",
                ]
                for sel in comment_selectors:
                    try:
                        self.pg.wait_for_selector(sel, timeout=4000)
                        count = self.pg.locator(sel).count()
                        if count > 0:
                            print(Fore.GREEN + f"   ✅ Panel komentar: {sel} ({count} el)")
                            return True
                    except Exception:
                        continue

                # Scroll sedikit untuk trigger lazy-load komentar
                self.pg.evaluate("window.scrollBy(0, 300)")
                time.sleep(2)
                return True
            else:
                print(Fore.YELLOW + "   ⚠️  Tombol komentar tidak ditemukan (mungkin sudah terbuka)")
                return False

        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  _open_reel_comments error: {e}")
            return False

    # ── SCROLL & EXPAND ───────────────────────────────────────────

    def _click_more_comments_aggressive(self):
        patterns = [
            "Lihat lebih banyak komentar",
            "Lihat komentar lain",            # ← tambahan untuk cover varian
            "View more comments",
            "Lihat komentar sebelumnya",
            "View previous comments",
            "Muat lebih banyak",
            "Load more",
            "Lihat balasan lainnya",
            "View more replies",
        ]

        for _ in range(5):
            clicked_any = False
            for text in patterns:
                try:
                    selectors = [
                        f"div[role='button']:has-text('{text}')",
                        f"span[role='button']:has-text('{text}')",
                        f"span:text-is('{text}')",
                    ]
                    for sel in selectors:
                        btns = self.pg.locator(sel)
                        count = btns.count()
                        for i in range(count):
                            try:
                                btn = btns.nth(i)
                                if btn.is_visible(timeout=1000):
                                    btn.scroll_into_view_if_needed(timeout=2000)
                                    btn.click(timeout=3000)
                                    clicked_any = True
                                    time.sleep(1.0)
                            except Exception:
                                pass
                except Exception:
                    pass
            if not clicked_any:
                break
            time.sleep(1.5)

    def _expand_replies_aggressive(self):
        try:
            clicked = self.pg.evaluate("""() => {
                let count = 0;
                const patterns = [
                    /lihat semua \\d+ balasan/i,
                    /lihat \\d+ balasan/i,
                    /view \\d+ repl/i,
                    /lihat semua balasan/i,
                    /view all replies/i,
                    /\\d+ balasan/i,
                    /\\d+ repl/i,
                ];
                const allBtns = document.querySelectorAll('[role="button"]');
                for (const btn of allBtns) {
                    const txt = (btn.innerText || btn.textContent || '').trim();
                    if (!txt) continue;
                    const match = patterns.some(p => p.test(txt));
                    if (match && count < 30) {
                        try {
                            btn.scrollIntoView({behavior: 'auto', block: 'center'});
                            btn.dispatchEvent(new MouseEvent('click', {
                                bubbles: true, cancelable: true, view: window
                            }));
                            count++;
                        } catch(e) {}
                    }
                }
                return count;
            }""")
            if clicked > 0:
                print(Fore.CYAN + f"   🔓 JS-klik {clicked} tombol balasan")
                time.sleep(1.5)
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  expand_replies JS error: {e}")

    def _scroll_down_aggressive(self):
        """Scroll agresif — prioritas panel scrollable (reel) jika ada."""
        try:
            scrolled = self.pg.evaluate("""() => {
                // Cari panel scrollable terbesar (bukan window/body) — ini panel komentar reel
                let best = null, bestH = 0;
                document.querySelectorAll('*').forEach(el => {
                    const s = window.getComputedStyle(el);
                    if ((s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                        el.scrollHeight > el.clientHeight + 50 &&
                        el.clientHeight > 80) {
                        if (el.scrollHeight > bestH) { bestH = el.scrollHeight; best = el; }
                    }
                });
                if (best) {
                    best.scrollTop = best.scrollHeight;
                    return true;
                }
                return false;
            }""")
            time.sleep(0.8)

            if not scrolled:
                self.pg.evaluate("""() => {
                    const articles = document.querySelectorAll('[role="article"]');
                    if (articles.length > 0) {
                        articles[articles.length - 1].scrollIntoView({behavior: 'auto', block: 'end'});
                    }
                }""")
                self.pg.evaluate("window.scrollBy(0, window.innerHeight * 2);")
                time.sleep(0.5)
                self.pg.keyboard.press("End")
                time.sleep(0.5)
        except Exception:
            try:
                self.pg.evaluate("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(1.0)
            except Exception:
                pass

    # ── AKUMULASI & DEDUP ─────────────────────────────────────────

    @staticmethod
    def _dedup_comments(raw_comments: List[Dict]) -> List[Dict]:
        seen   = set()
        unique = []
        for c in raw_comments:
            raw_key = c.get("username", "") + "::" + c.get("text", "")
            key     = hashlib.md5(raw_key.encode("utf-8", errors="replace")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)
        return unique

    @staticmethod
    def _merge_comments(accumulated: List[Dict], new_batch: List[Dict]) -> List[Dict]:
        """Gabungkan hasil ekstraksi batch baru ke accumulator, dedup by (username + text)."""
        seen = set()
        for c in accumulated:
            raw_key = c.get("username", "") + "::" + c.get("text", "")
            seen.add(hashlib.md5(raw_key.encode("utf-8", errors="replace")).hexdigest())

        for c in new_batch:
            raw_key = c.get("username", "") + "::" + c.get("text", "")
            key = hashlib.md5(raw_key.encode("utf-8", errors="replace")).hexdigest()
            if key in seen:
                continue
            seen.add(key)
            accumulated.append(c)

        return accumulated

    def _scroll_to_load_comments(self, target_count: int, include_replies: bool = True,
                                 target_total_items: bool = False) -> List[Dict]:
        """
        Scroll + ekstraksi per-round, akumulasi hasil (anti-virtualization).
        Mengembalikan list komentar gabungan (sudah dedup).
        """
        print(Fore.CYAN + f"\n📜 Scroll untuk load komentar (target: {target_count})...")

        accumulated: List[Dict] = []
        last_progress = 0
        stable_rounds  = 0
        is_all         = target_count >= 5000
        max_stable     = 8 if is_all else 5
        scroll_round   = 0
        max_rounds     = 400 if is_all else 150
        warmups_done   = 0
        max_warmups    = 6 if is_all else 3   # checkpoint warm-up sebelum menyerah

        # Ekstrak batch awal (sebelum scroll apapun)
        try:
            batch = self._extract_all_comments(target_count, include_replies=include_replies)
            accumulated = self._merge_comments(accumulated, batch)
        except Exception:
            pass

        while scroll_round < max_rounds:
            scroll_round += 1

            self._click_more_comments_aggressive()
            self._expand_replies_aggressive()
            self._scroll_down_aggressive()

            # Ekstrak batch yang sedang terlihat & gabungkan
            try:
                batch = self._extract_all_comments(target_count, include_replies=include_replies)
                accumulated = self._merge_comments(accumulated, batch)
            except Exception:
                pass

            top_level_now = sum(1 for c in accumulated if not c.get("is_reply"))
            progress_now = len(accumulated) if target_total_items else top_level_now

            if progress_now > last_progress:
                print(Fore.CYAN + f"   📄 Round {scroll_round}: {top_level_now} komentar utama "
                                   f"({len(accumulated)} total termasuk balasan)")
                last_progress = progress_now
                stable_rounds = 0
                if progress_now >= target_count:
                    print(Fore.GREEN + f"   🎯 Target {target_count} komentar tercapai")
                    break
            else:
                stable_rounds += 1
                # Rate-limit terdeteksi → warm-up lebih panjang
                rate_limited = self._detect_rate_limit()
                if (stable_rounds >= max_stable or rate_limited) and progress_now < target_count:
                    if warmups_done < max_warmups:
                        warmups_done += 1
                        stable_rounds = 0
                        wait = random.uniform(12, 20) if rate_limited else random.uniform(7, 13)
                        print(Fore.YELLOW + f"   🔥 Checkpoint warm-up #{warmups_done}/{max_warmups} "
                                            f"({'rate-limit terdeteksi' if rate_limited else 'stuck'}) — jeda {wait:.0f}s lalu lanjut...")
                        time.sleep(wait)
                        try:
                            self.pg.evaluate("window.scrollTo(0, document.body.scrollHeight*0.3)")
                            time.sleep(1.5)
                            self.pg.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                            time.sleep(1.5)
                        except Exception:
                            pass
                        continue
                    print(Fore.YELLOW + f"   ⚠️  Tidak ada komentar baru setelah {warmups_done} warm-up — berhenti "
                                        f"(dapat {top_level_now} komentar utama).")
                    break
                elif stable_rounds >= max_stable:
                    # sudah mencapai/melebihi target tapi tidak ada yang baru
                    break

            delay = 1.5 + random.uniform(0, 1.0)
            if stable_rounds > 0:
                delay += 1.0
            time.sleep(delay)

        return accumulated

    def _count_comments_in_dom(self) -> int:
        """Hitung komentar dengan multi-selector (support reel + post biasa)."""
        # [role='article'] untuk post biasa
        count = self.pg.locator("[role='article']").count()
        if count > 0:
            return count
        # Fallback untuk reel: coba selector lain
        for sel in [
            "[role='complementary'] [role='listitem']",
            "[role='complementary'] div[dir='auto']",
            "div[aria-label*='omentar'] [role='listitem']",
            "ul li",
        ]:
            c = self.pg.locator(sel).count()
            if c > 0:
                return c
        return 0

    # ── COMMENT EXTRACTION ────────────────────────────────────────

    def _get_comment_container(self):
        """
        Return locator yang berisi komentar.
        Support post biasa ([role='article']) dan reel ([role='complementary']).
        """
        # Post biasa
        articles = self.pg.locator("[role='article']")
        if articles.count() > 0:
            return articles, "article"

        # Reel: panel komentar di complementary
        for sel in [
            "[role='complementary'] [role='listitem']",
            "[role='complementary'] div[dir='auto']",
            "div[aria-label*='omentar'] div[dir='auto']",
            "ul li",
        ]:
            loc = self.pg.locator(sel)
            if loc.count() > 0:
                print(Fore.CYAN + f"   🔄 Reel comment selector: {sel}")
                return loc, "reel"

        return self.pg.locator("[role='article']"), "article"

    def _extract_all_comments(self, max_comments: int, include_replies: bool = True) -> List[Dict]:
        """
        Ekstraksi komentar + balasan via 1x JS evaluate (cepat & terstruktur).
        Membedakan komentar utama ('Komentar oleh') vs balasan ('Balasan ...'),
        beserta penulis, teks, jumlah like, timestamp, dan target balasan.
        max_comments = jumlah KOMENTAR UTAMA (balasan dari komentar yang masuk ikut diambil).
        """
        print(Fore.CYAN + "\n🔍 Extract komentar + balasan (JS)...")
        try:
            raw = self.pg.evaluate(r"""(maxItems) => {
                const out = [];
                const arts = document.querySelectorAll('[role="article"]');
                for (const a of arts) {
                    const aria = a.getAttribute('aria-label') || '';
                    let author = '', isReply = false, replyTo = '';

                    let m = aria.match(/^Komentar oleh (.+?)\s+(?:\d|sekitar|baru saja|kemarin|sehari|seminggu|sebulan|setahun|hampir|lebih)/i)
                         || aria.match(/^Comment by (.+?)\s+\d/i);
                    if (m) {
                        author = m[1].trim();
                    } else {
                        let r = aria.match(/^Balasan oleh (.+?)\s+pada komentar (.+)$/i)
                             || aria.match(/^Balasan dari (.+?)\s+(?:pada|untuk|kepada) (.+?)(?:\s+\d.*)?$/i)
                             || aria.match(/^Balasan (.+?)\s+ke balasan (.+?)(?:\s+\d+)?$/i)
                             || aria.match(/^Balasan oleh (.+?)\s+(?:\d|sekitar|baru saja|kemarin|sehari|seminggu|sebulan|setahun|hampir|lebih)/i)
                             || aria.match(/^Reply by (.+?)\s+to (.+)$/i)
                             || aria.match(/^Reply by (.+?)\s+\d/i);
                        if (r) {
                            isReply = true;
                            author = r[1].trim();
                            replyTo = (r[2] || '').trim();
                        } else if (/^Balasan/i.test(aria) || /^Reply/i.test(aria)) {
                            // Fallback: pattern "Balasan oleh X ..." tanpa target jelas
                            let r2 = aria.match(/^Balasan(?:\s+oleh)?\s+(.+?)\s+\d/i)
                                  || aria.match(/^Balasan(?:\s+oleh)?\s+(.+)$/i);
                            if (r2) { isReply = true; author = r2[1].trim(); replyTo = ''; }
                            else { continue; }
                        } else if (!aria) {
                            // FIX: aria-label kosong — deteksi reply via DOM nesting
                            // (article ini bersarang di dalam article lain → kemungkinan reply)
                            const parentArticle = a.parentElement?.closest('[role="article"]');
                            if (parentArticle && parentArticle !== a) {
                                isReply = true;
                                // ambil author dari span pertama di dalam article ini
                                const nameSpan = a.querySelector('span[dir="auto"]');
                                author = nameSpan ? (nameSpan.innerText || '').trim() : '';
                                if (!author) continue;
                                // simpan reference index parent untuk dipetakan nanti
                                replyTo = '__nested__';
                            } else {
                                continue;
                            }
                        } else {
                            continue;
                        }
                    }
                    if (!author) continue;

                    // teks komentar = div[dir=auto] terpanjang yang bukan nama penulis
                    let text = '';
                    const divs = a.querySelectorAll('div[dir="auto"]');
                    for (const d of divs) {
                        const t = (d.innerText || '').trim();
                        if (t && t !== author && t.length > text.length) text = t;
                    }

                    // jumlah like komentar dari aria "N reaksi"
                    let likes = '0';
                    const els = a.querySelectorAll('[aria-label]');
                    for (const e of els) {
                        const al = e.getAttribute('aria-label') || '';
                        const lm = al.match(/^([\d.,]+)\s*(?:reaksi|reaction|orang)/i);
                        if (lm) { likes = lm[1]; break; }
                    }

                    // timestamp
                    let ts = '';
                    const links = a.querySelectorAll('a');
                    for (const e of links) {
                        const t = (e.innerText || '').trim();
                        if (/yang lalu|ago/i.test(t) || /^\d+\s*(j|jam|mnt|menit|h|hr|hari|mgg|minggu|bln|bulan|thn|tahun|d|w|y)\b/i.test(t)) { ts = t; break; }
                    }

                    out.push({author, text, is_reply: isReply, reply_to: replyTo, likes_raw: String(likes), timestamp: ts, _aria: aria.slice(0, 80)});
                    if (out.length >= maxItems + 500) break;
                }
                return out;
            }""", max_comments)
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  JS extract gagal ({e}), fallback locator...")
            return self._extract_all_comments_locator(max_comments)

        if not raw:
            raw = self._extract_reel_comments_from_visible_panel(max_comments)

        print(Fore.CYAN + f"   📊 Kandidat dari DOM: {len(raw)}")
        # DEBUG: tampilkan sample aria-label untuk verifikasi pattern reply
        replies_sample = [r for r in raw if r.get("is_reply")]
        print(Fore.MAGENTA + f"   🔍 Reply terdeteksi: {len(replies_sample)}")
        for r in replies_sample[:5]:
            print(Fore.MAGENTA + f"      aria='{r.get('_aria','')}' author={r.get('author')} replyTo={r.get('reply_to')}")
        if not replies_sample:
            non_empty_aria = [r for r in raw if r.get("_aria")][:5]
            print(Fore.YELLOW + "   ⚠️  Sample aria-label dari komentar (untuk cek pattern):")
            for r in non_empty_aria:
                print(Fore.YELLOW + f"      '{r.get('_aria','')}'")

        comments    = []
        seen_hashes = set()
        top_level   = 0
        last_top_level_author = ""

        for r in raw:
            is_reply = bool(r.get("is_reply"))
            if is_reply and not include_replies:
                continue

            # FIX: petakan reply_to='__nested__' ke top-level comment terakhir
            if is_reply and r.get("reply_to") == "__nested__":
                r["reply_to"] = last_top_level_author
            if not is_reply:
                last_top_level_author = r.get("author", "")

            text = self._clean_comment_text(r.get("text", ""), r.get("author", ""))
            if not text or len(text) < 2:
                continue

            # Batas berlaku untuk komentar utama; balasan dari parent yang masuk tetap diambil
            if not is_reply and top_level >= max_comments:
                break

            raw_key = (r.get("author", "") + "::" + text)
            key     = hashlib.md5(raw_key.encode("utf-8", errors="replace")).hexdigest()
            if key in seen_hashes:
                continue
            seen_hashes.add(key)

            # Bersihkan reply_to dari ekor index/waktu (mis. "Sandi Adhari 18 jam")
            reply_to = r.get("reply_to", "")
            reply_to = re.sub(r'\s+\d+\s*(?:jam|menit|detik|hari|minggu|bulan|tahun|j|mnt)\b.*$', '', reply_to, flags=re.I)
            reply_to = re.sub(r'\s+\d+\s*$', '', reply_to).strip()

            comments.append({
                "username":    r.get("author", ""),
                "text":        text[:1000],
                "timestamp":   r.get("timestamp", ""),
                "like_count":  self._parse_number(r.get("likes_raw", "0")),
                "reply_count": 0,
                "is_reply":    is_reply,
                "reply_to":    reply_to,
            })
            if not is_reply:
                top_level += 1

        n_reply = sum(1 for c in comments if c["is_reply"])
        print(Fore.GREEN + f"   ✅ {len(comments)} item ({len(comments)-n_reply} komentar + {n_reply} balasan)")
        return comments

    def _extract_reel_comments_from_visible_panel(self, max_comments: int) -> List[Dict]:
        """
        Fallback Reels terbaru: komentar kadang muncul sebagai blok panel biasa,
        bukan role=article dengan aria "Komentar oleh ...".
        """
        try:
            raw = self.pg.evaluate(r"""(maxItems) => {
                const clean = (text) => (text || '')
                    .replace(/\u00a0|\xa0/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim();
                const badLine = /^(suka|like|balas|reply|bagikan|share|komentari|comment|reels?|publik|public|audio asli|original audio|lihat selengkapnya|see more)$/i;
                const timeRe = /(?:baru saja|kemarin|\d+\s*(?:d|h|j|jam|mnt|menit|detik|hari|minggu|bulan|tahun|w|y)\b|just now|yesterday|\d+\s*(?:sec|second|min|minute|hour|day|week|month|year)s?\b)/i;
                const actionRe = /\b(?:suka|like|balas|reply|reaksi|reaction)\b/i;
                const chromeRe = /(tulis komentar|write a comment|paling relevan|most relevant|semua komentar|all comments|masuk|lupa akun|facebook|notifikasi|lihat semua|view all|pelajari selengkapnya)/i;
                const panels = [
                    ...document.querySelectorAll('[role="complementary"]'),
                    ...document.querySelectorAll('div[aria-label*="Komentar"],div[aria-label*="komentar"],div[aria-label*="Comments"],div[aria-label*="comments"]')
                ].filter(Boolean);
                const scope = panels.find(p => clean(p.innerText).length > 20) || document.body;
                const out = [];
                const seen = new Set();

                const getAuthor = (el) => {
                    const linkCandidates = [
                        ...el.querySelectorAll('a[role="link"], a[href*="facebook.com"], a[href*="profile.php"]')
                    ];
                    for (const a of linkCandidates) {
                        const t = clean(a.innerText || a.textContent || a.getAttribute('aria-label') || '');
                        if (!t || t.length < 2 || t.length > 80) continue;
                        if (badLine.test(t) || timeRe.test(t) || chromeRe.test(t)) continue;
                        return t;
                    }
                    const spans = [...el.querySelectorAll('span[dir="auto"], strong, h3, h4')];
                    for (const s of spans) {
                        const t = clean(s.innerText || s.textContent || '');
                        if (!t || t.length < 2 || t.length > 80) continue;
                        if (badLine.test(t) || timeRe.test(t) || chromeRe.test(t)) continue;
                        return t;
                    }
                    return '';
                };

                const getText = (el, author) => {
                    const textNodes = [
                        ...el.querySelectorAll('div[dir="auto"], span[dir="auto"]')
                    ].map(n => clean(n.innerText || n.textContent || ''))
                     .filter(Boolean)
                     .filter(t => t !== author)
                     .filter(t => !badLine.test(t))
                     .filter(t => !timeRe.test(t))
                     .filter(t => !chromeRe.test(t))
                     .filter(t => !/^\d+([\.,]\d+)?\s*(rb|jt|k|m)?$/i.test(t));
                    textNodes.sort((a, b) => b.length - a.length);
                    return textNodes[0] || '';
                };

                const getLikes = (el) => {
                    const combined = clean(`${el.getAttribute('aria-label') || ''} ${el.innerText || ''}`);
                    const m = combined.match(/(\d+(?:[.,]\d+)?)\s*(?:reaksi|reaction|suka|likes?)/i);
                    return m ? m[1] : '0';
                };

                const getTimestamp = (el) => {
                    const parts = [
                        ...el.querySelectorAll('a, span, div')
                    ].map(n => clean(n.innerText || n.textContent || ''));
                    return parts.find(t => timeRe.test(t) && t.length < 40) || '';
                };

                const candidates = [];
                [
                    '[role="article"]',
                    '[role="listitem"]',
                    'li',
                    'div[aria-label^="Komentar oleh"]',
                    'div[aria-label^="Comment by"]',
                    'div[aria-label^="Balasan"]',
                    'div[aria-label^="Reply"]'
                ].forEach(sel => scope.querySelectorAll(sel).forEach(el => candidates.push(el)));

                scope.querySelectorAll('div').forEach(el => {
                    const txt = clean(el.innerText || '');
                    if (txt.length < 15 || txt.length > 900) return;
                    if (!actionRe.test(txt) && !timeRe.test(txt)) return;
                    candidates.push(el);
                });

                for (const el of candidates) {
                    if (out.length >= maxItems + 100) break;
                    const full = clean(el.innerText || el.textContent || '');
                    if (!full || full.length < 10 || full.length > 1200) continue;
                    if (chromeRe.test(full) && !actionRe.test(full)) continue;
                    const author = getAuthor(el);
                    if (!author) continue;
                    const text = getText(el, author);
                    if (!text || text.length < 2 || text === author) continue;
                    const key = `${author}::${text}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    const aria = el.getAttribute('aria-label') || '';
                    const isReply = /^Balasan|^Reply/i.test(aria);
                    out.push({
                        author,
                        text,
                        is_reply: !!isReply,
                        reply_to: '',
                        likes_raw: getLikes(el),
                        timestamp: getTimestamp(el),
                        _aria: aria.slice(0, 80) || 'visible_panel'
                    });
                }
                return out;
            }""", max_comments)
            if raw:
                print(Fore.CYAN + f"   🔁 Fallback panel Reels menemukan {len(raw)} kandidat")
            else:
                self._debug_comment_panel_snapshot("no_visible_panel_comments")
            return raw or []
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  fallback panel komentar gagal: {e}")
            self._debug_comment_panel_snapshot(str(e))
            return []

    def _debug_comment_panel_snapshot(self, reason: str):
        try:
            os.makedirs("fb_post_debug", exist_ok=True)
            payload = self.pg.evaluate(r"""(reason) => {
                const clean = (text) => (text || '').replace(/\s+/g, ' ').trim();
                const panels = [
                    ...document.querySelectorAll('[role="complementary"]'),
                    ...document.querySelectorAll('div[aria-label*="Komentar"],div[aria-label*="komentar"],div[aria-label*="Comments"],div[aria-label*="comments"]')
                ];
                return {
                    reason,
                    url: location.href,
                    body: (document.body.innerText || '').slice(0, 5000),
                    panels: panels.slice(0, 5).map(p => ({
                        aria: p.getAttribute('aria-label') || '',
                        text: clean(p.innerText || '').slice(0, 2000),
                        articles: p.querySelectorAll('[role="article"]').length,
                        listitems: p.querySelectorAll('[role="listitem"],li').length,
                        dirAuto: p.querySelectorAll('[dir="auto"]').length
                    }))
                };
            }""", reason[:300])
            name = f"comments_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(100000, 999999)}.json"
            with open(os.path.join("fb_post_debug", name), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(Fore.YELLOW + f"   🧪 Snapshot komentar disimpan: fb_post_debug/{name}")
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  debug snapshot komentar gagal: {e}")

    def _debug_reaction_dialog_snapshot(self, reason: str):
        """Dump struktur dialog reaction supaya bisa diperbaiki kalau 0 akun."""
        try:
            os.makedirs("fb_post_debug", exist_ok=True)
            payload = self.pg.evaluate(r"""(reason) => {
                const clean = (t) => (t || '').replace(/\s+/g, ' ').trim();
                const dialogs = [...document.querySelectorAll('[role="dialog"]')];
                const last = dialogs[dialogs.length - 1] || null;
                const sampleAnchors = last ? [...last.querySelectorAll('a[href]')].slice(0, 25).map(a => ({
                    href: (a.href || a.getAttribute('href') || '').slice(0, 120),
                    text: clean(a.innerText || a.textContent || '').slice(0, 80),
                    aria: (a.getAttribute('aria-label') || '').slice(0, 80),
                })) : [];
                return {
                    reason,
                    url: location.href,
                    dialog_count: dialogs.length,
                    last_dialog_aria: last ? (last.getAttribute('aria-label') || '') : '(no dialog)',
                    last_dialog_text: last ? clean(last.innerText || '').slice(0, 2000) : '',
                    last_dialog_listitems: last ? last.querySelectorAll('[role="listitem"],li').length : 0,
                    last_dialog_anchors: last ? last.querySelectorAll('a[href]').length : 0,
                    sample_anchors: sampleAnchors,
                };
            }""", reason[:300])
            name = f"reactions_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{random.randint(100000, 999999)}.json"
            with open(os.path.join("fb_post_debug", name), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
            print(Fore.YELLOW + f"   🧪 Snapshot reaction disimpan: fb_post_debug/{name}")
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  debug snapshot reaction gagal: {e}")

    def _extract_all_comments_locator(self, max_comments: int) -> List[Dict]:
        """Fallback lama berbasis Playwright locator (lebih lambat)."""
        container, mode = self._get_comment_container()
        total = container.count()
        print(Fore.CYAN + f"   📊 Total element ({mode}): {total}")

        comments    = []
        seen_hashes = set()

        for i in range(min(total, max_comments + 20)):
            try:
                item   = container.nth(i)
                parsed = self._parse_single_comment(item)
                if not parsed or not parsed.get("text"):
                    continue
                raw_key = parsed.get("username", "") + "::" + parsed.get("text", "")
                key     = hashlib.md5(raw_key.encode("utf-8", errors="replace")).hexdigest()
                if key in seen_hashes:
                    continue
                seen_hashes.add(key)
                if len(parsed["text"]) < 3:
                    continue
                parsed["is_reply"] = False
                parsed["reply_to"] = ""
                comments.append(parsed)
                if len(comments) >= max_comments:
                    break
            except Exception:
                continue

        return comments

    def _parse_single_comment(self, article) -> Optional[Dict]:
        try:
            username = self._extract_username(article)
            if not username:
                return None

            text = self._extract_comment_text(article, username)
            if not text or len(text) < 2:
                return None

            text = self._clean_comment_text(text, username)
            if not text or len(text) < 3:
                return None

            timestamp   = self._extract_timestamp(article)
            like_count  = self._extract_like_count(article)
            reply_count = self._extract_reply_count(article)

            return {
                "username":    username,
                "text":        text[:1000],
                "timestamp":   timestamp,
                "like_count":  like_count,
                "reply_count": reply_count,
            }
        except Exception:
            return None

    def _extract_username(self, article) -> str:
        try:
            aria = article.get_attribute("aria-label") or ""
            m = re.search(
                r'(?:Komentar oleh|komentar oleh|Comment by)\s+(.+?)\s+'
                r'(?:sehari|seminggu|sebulan|baru saja|yesterday|just now|\d+\s*'
                r'(?:jam|menit|detik|hari|minggu|bulan|tahun|hour|minute|second|day|week|month|year))',
                aria, re.I
            )
            if m:
                return m.group(1).strip()
        except Exception:
            pass

        try:
            spans = article.locator("span")
            for i in range(min(spans.count(), 10)):
                txt = (spans.nth(i).inner_text() or "").strip()
                if txt and 1 < len(txt) < 60 and not txt.isdigit() and not re.match(r'^\d', txt):
                    try:
                        parent = spans.nth(i).locator("xpath=..")
                        href   = parent.get_attribute("href") or ""
                        if "facebook.com/" in href or "profile.php" in href:
                            return txt
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            links = article.locator("a[href*='facebook.com/'], a[href*='profile.php']")
            for i in range(min(links.count(), 5)):
                txt = (links.nth(i).inner_text() or "").strip()
                if txt and 1 < len(txt) < 60 and not txt.isdigit():
                    return txt
        except Exception:
            pass

        return ""

    def _extract_comment_text(self, article, username: str) -> str:
        try:
            divs = article.locator("div[dir='auto']")
            best = ""
            for i in range(divs.count()):
                txt = (divs.nth(i).inner_text() or "").strip()
                if txt and txt != username and len(txt) > len(best):
                    best = txt
            if best:
                return best
        except Exception:
            pass

        try:
            spans = article.locator("span[dir='auto']")
            best  = ""
            for i in range(spans.count()):
                txt = (spans.nth(i).inner_text() or "").strip()
                if txt and txt != username and len(txt) > len(best):
                    best = txt
            if best:
                return best
        except Exception:
            pass

        try:
            full = (article.inner_text() or "").strip()
            if username and full.startswith(username):
                return full[len(username):].strip()
            return full
        except Exception:
            return ""

    def _clean_comment_text(self, text: str, username: str) -> str:
        if not text:
            return ""

        noise_patterns = [
            r'\n?Suka\s*\d*\n?', r'\n?Balas\s*\n?', r'\n?Like\s*\d*\n?', r'\n?Reply\s*\n?',
            r'\n?Diedit\s*\n?', r'\n?Edited\s*\n?', r'\n?Lihat\s+terjemahan\s*\n?',
            r'\n?See\s+translation\s*\n?', r'\n?Terjemahkan\s*\n?', r'\n?Translate\s*\n?',
            r'\n?Lebih\s+banyak\s*\n?', r'\n?More\s*\n?',
            r'\n?\d+\s*(?:jam|hari|menit|detik|minggu|bulan)\s*\n?',
            r'\n?\d+\s*(?:hour|day|minute|second|week|month)\s*\n?',
        ]

        clean = text
        for pat in noise_patterns:
            clean = re.sub(pat, ' ', clean, flags=re.IGNORECASE)

        if username and clean.lower().startswith(username.lower()):
            clean = clean[len(username):].strip()

        clean = re.sub(r'\s{2,}', ' ', clean).strip()
        return clean

    def _extract_timestamp(self, article) -> str:
        try:
            links = article.locator("a[role='link']")
            for i in range(links.count()):
                txt = (links.nth(i).inner_text() or "").strip()
                if re.search(r'\d+\s*(?:jam|hari|menit|detik|minggu|bulan|tahun)', txt, re.I):
                    return txt
                if txt.lower() in ("kemarin", "yesterday", "just now", "baru saja"):
                    return txt
        except Exception:
            pass
        return ""

    def _extract_like_count(self, article) -> int:
        try:
            els = article.locator("[aria-label]")
            for i in range(els.count()):
                aria = els.nth(i).get_attribute("aria-label") or ""
                if "reaksi" in aria.lower() or "reaction" in aria.lower():
                    m = re.match(r'^([\d.,]+)', aria)
                    if m:
                        raw = m.group(1).replace(".", "").replace(",", "")
                        return int(raw)
        except Exception:
            pass
        return 0

    def _extract_reply_count(self, article) -> int:
        try:
            spans = article.locator("span")
            for i in range(spans.count()):
                txt = (spans.nth(i).inner_text() or "").strip()
                m = re.search(r'(\d+)\s*(?:balas|reply|replies)', txt, re.I)
                if m:
                    return int(m.group(1))
        except Exception:
            pass
        return 0

    # ── SENTIMENT ─────────────────────────────────────────────────

    def _analyze_sentiment(self, text: str) -> Dict:
        if not text or not text.strip():
            return self._empty_sentiment()

        analysis = self.sentiment.analyze_sentiment(text)
        category = self.sentiment.categorize_comment(text)

        return {
            "sentiment":       analysis["sentiment"],
            "category":        category,
            "language":        analysis["language"],
            "is_hate_speech":  analysis["is_hate_speech"],
            "is_toxic":        analysis["is_toxic"],
            "is_sarcasm":      analysis.get("is_sarcasm", False),
            "is_wellwish":     analysis.get("is_wellwish", False),
            "hate_score":      analysis["hate_score"],
            "hate_words":      analysis["hate_words"],
            "toxic_words":     analysis["toxic_words"],
            "positive_words":  analysis["positive_words"],
            "negative_words":  analysis.get("negative_words", []),
            "humor_words":     analysis["humor_words"],
            "emojis":          analysis["emojis"],
            "ml_confidence":   analysis.get("ml_confidence", 0.0),
            "decision_source": analysis.get("decision_source", "rule"),
        }

    def _empty_sentiment(self) -> Dict:
        return {
            "sentiment": "NEUTRAL", "category": "NEUTRAL", "language": "id",
            "is_hate_speech": False, "is_toxic": False,
            "is_sarcasm": False, "is_wellwish": False,
            "hate_score": 0.0, "hate_words": [], "toxic_words": [],
            "positive_words": [], "negative_words": [], "humor_words": [],
            "emojis": [], "ml_confidence": 0.0, "decision_source": "empty",
        }

    # ============================================================
    # MAIN SCRAPE FLOW
    # ============================================================

    def scrape_post(self, post_url: str, max_comments: int = MAX_COMMENTS,
                    include_replies: bool = True, scrape_reactors: bool = SCRAPE_REACTORS,
                    max_reactors: int = MAX_REACTORS) -> Dict:
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + f"📝 {post_url[:70]}")
        print(Fore.CYAN + "=" * 70)

        result = {
            "url":               post_url,
            "scraped_at":        datetime.now().isoformat(),
            "platform":          "facebook",
            "sentiment_mode":    self.sentiment.mode,
            "post_id":           "",
            "post_type":         "post",
            "caption":           "",
            "with_tags":         [],
            "with_others":       0,
            "mentions":          [],
            "media_type":        "",
            "media_count":       0,
            "media_urls":        [],
            "location":          "",
            "total_likes":       0,
            "reactors":          [],
            "reactors_count":    0,
            "reactors_scrape_failed": False,
            "total_comments":    0,
            "total_shares":      0,
            "total_saves":       None,   # FB tidak mengekspos jumlah save ke publik
            "include_replies":   include_replies,
            "method":            "dom",
            "comments":          [],
            "comments_count":    0,
            "top_level_count":   0,
            "replies_count":     0,
            "sentiment_summary": {},
            "caption_sentiment": {},
            "success":           False,  # FIX: selalu ada field success
        }

        try:
            self.initialize_browser()
            self._enforce_rate_limit()

            final_url, post_id = self._navigate_and_extract_id(post_url)
            result["url"]       = final_url

            # CHECKPOINT/WARM-UP: pastikan benar2 mendarat di post (bukan homepage akibat rate-limit)
            nav_attempt = 0
            while nav_attempt < 3 and (not self._is_on_post() or self._detect_rate_limit()):
                nav_attempt += 1
                print(Fore.YELLOW + f"   ⚠️  Belum di halaman post (percobaan {nav_attempt}/3) — kemungkinan rate-limit.")
                self._warmup(8 + nav_attempt * 5)
                final_url, post_id = self._navigate_and_extract_id(post_url)
                result["url"] = final_url

            result["post_type"] = self._detect_post_type(final_url)
            print(Fore.CYAN + f"   🎬 Tipe konten: {result['post_type']}")

            if post_id:
                result["post_id"] = post_id
                print(Fore.GREEN + f"✅ Post ID: {post_id}")
            else:
                print(Fore.YELLOW + "   ⚠️  Post ID tidak ditemukan, lanjut tanpa ID")

            # FIX: Buka panel komentar untuk reel/video sebelum wait_for_selector
            self._open_reel_comments()

            print(Fore.CYAN + "   ⏳ Menunggu komentar load...")
            try:
                # Coba selector post biasa dulu, lalu reel
                found = False
                for sel in ["[role='article']", "[role='complementary']", "ul li"]:
                    try:
                        self.pg.wait_for_selector(sel, timeout=8000)
                        count = self.pg.locator(sel).count()
                        if count > 0:
                            print(Fore.GREEN + f"   ✅ Konten ditemukan: {sel} ({count} el)")
                            found = True
                            break
                    except PlaywrightTimeout:
                        continue
                if not found:
                    print(Fore.YELLOW + "   ⚠️  Timeout tunggu komentar, coba scroll...")
            except Exception:
                pass

            meta = self._get_post_metadata()
            result["caption"]        = meta.get("caption", "")
            result["total_likes"]    = meta.get("total_likes", 0)
            result["total_comments"] = meta.get("total_comments", 0)
            result["total_shares"]   = meta.get("total_shares", 0)

            extras = self._extract_post_extras()
            result["with_tags"]   = extras.get("with_tags", [])
            result["with_others"] = extras.get("with_others", 0)
            result["mentions"]    = extras.get("mentions", [])
            result["media_type"]  = extras.get("media_type", "")
            result["media_count"] = extras.get("media_count", 0)
            result["media_urls"]  = extras.get("media_urls", [])
            result["location"]    = extras.get("location", "")

            print(Fore.CYAN + "\n📊 Metadata post:")
            print(Fore.CYAN + f"   ❤️  Reactions : {result['total_likes']:,}")
            print(Fore.CYAN + f"   💬 Comments   : {result['total_comments']:,}")
            print(Fore.CYAN + f"   📤 Shares     : {result['total_shares']:,}")
            if result["with_tags"]:
                extra_s = f" +{result['with_others']} lainnya" if result['with_others'] else ""
                print(Fore.CYAN + f"   👥 Bersama    : {', '.join(result['with_tags'])}{extra_s}")
            if result["media_type"]:
                print(Fore.CYAN + f"   🖼️  Media      : {result['media_type']} ({result['media_count']})")

            if scrape_reactors:
                reactors = self._scrape_post_reactors(max_reactors)
                result["reactors"] = reactors
                result["reactors_count"] = len(reactors)
                if not reactors and result.get("total_likes", 0) > 0:
                    result["reactors_scrape_failed"] = True
                self._open_reel_comments()

            if result["caption"]:
                print(Fore.CYAN + f"\n📝 Caption: {result['caption'][:150]}")
                print(Fore.CYAN + "\n🧠 Analyzing caption sentiment...")
                cap_sent = self._analyze_sentiment(result["caption"])
                result["caption_sentiment"] = cap_sent
                self._display_caption_box(result["caption"], cap_sent["category"], cap_sent)

            # Scroll + akumulasi komentar per-round (anti‑virtualization)
            if max_comments <= 0:
                print(Fore.YELLOW + "   [COMMENTS] Skip komentar (max_comments=0)")
                raw_comments = []
            else:
                target_total_items = max_comments >= 5000
                comment_target = max_comments
                if target_total_items and result.get("total_comments", 0) > 0:
                    comment_target = min(max_comments, max(1, int(result["total_comments"])))
                    print(Fore.CYAN + f"   [COMMENTS] Target disesuaikan dari {max_comments:,} ke {comment_target:,} berdasarkan total komentar post")
                elif target_total_items:
                    comment_target = min(max_comments, ALL_COMMENTS_FALLBACK_TARGET)
                    print(Fore.YELLOW + f"   [COMMENTS] Total komentar tidak terbaca, pakai fallback target {comment_target:,}")
                raw_comments = self._scroll_to_load_comments(
                    comment_target,
                    include_replies=include_replies,
                    target_total_items=target_total_items,
                )

                # FIX REEL: viewer reel sering menyajikan panel komentar kosong
                # (video gagal play / autoplay pindah reel). Coba ulang lewat
                # halaman watch theater yang lebih stabil. Hanya jalan kalau FB
                # melaporkan ada komentar tapi kita dapat 0 — jadi tidak mengganggu
                # post foto/biasa yang sudah berhasil.
                if (not raw_comments
                        and result["post_type"] in ("reel", "video")
                        and result.get("post_id")
                        and int(result.get("total_comments") or 0) > 0):
                    watch_url = f"https://www.facebook.com/watch/?v={result['post_id']}"
                    print(Fore.YELLOW + f"   🔁 Komentar reel kosong — coba ulang via watch theater: {watch_url}")
                    try:
                        self._navigate_and_extract_id(watch_url)
                        self._open_reel_comments()
                        time.sleep(2)
                        raw_comments = self._scroll_to_load_comments(
                            comment_target,
                            include_replies=include_replies,
                            target_total_items=target_total_items,
                        )
                    except Exception as e:
                        print(Fore.YELLOW + f"   ⚠️  Retry watch theater gagal: {e}")

                raw_comments = self._dedup_comments(raw_comments)
            print(Fore.GREEN + f"\n✅ Setelah dedup: {len(raw_comments)} komentar unik")

            if raw_comments:
                print(Fore.CYAN + f"\n🧠 Analisis sentimen {len(raw_comments)} komentar...")

            t_start = time.time()
            final_comments = []
            for i, rc in enumerate(raw_comments, 1):
                text = rc.get("text", "")
                if not text:
                    continue

                analysis = self._analyze_sentiment(text)

                entry = {
                    "number":          i,
                    "username":        rc.get("username", ""),
                    "text":            text,
                    "timestamp":       rc.get("timestamp", ""),
                    "like_count":      rc.get("like_count", 0),
                    "reply_count":     rc.get("reply_count", 0),
                    "is_reply":        rc.get("is_reply", False),
                    "reply_to":        rc.get("reply_to", ""),
                    "category":        analysis["category"],
                    "sentiment":       analysis["sentiment"],
                    "language":        analysis["language"],
                    "is_hate_speech":  analysis["is_hate_speech"],
                    "is_toxic":        analysis["is_toxic"],
                    "is_sarcasm":      analysis["is_sarcasm"],
                    "is_wellwish":     analysis["is_wellwish"],
                    "hate_score":      analysis["hate_score"],
                    "hate_words":      analysis["hate_words"],
                    "toxic_words":     analysis["toxic_words"],
                    "positive_words":  analysis["positive_words"],
                    "negative_words":  analysis["negative_words"],
                    "humor_words":     analysis["humor_words"],
                    "emojis":          analysis["emojis"],
                    "ml_confidence":   analysis["ml_confidence"],
                    "decision_source": analysis["decision_source"],
                }
                final_comments.append(entry)

                if analysis["is_hate_speech"]:          label = Fore.RED    + "🚨 HATE "
                elif analysis["is_toxic"]:               label = Fore.YELLOW + "⚠️  TOXIC"
                elif analysis["category"] == "POSITIVE": label = Fore.GREEN  + "😊 POS  "
                elif analysis["category"] == "NEGATIVE": label = Fore.MAGENTA + "😞 NEG  "
                elif analysis["category"] == "HUMOR":    label = Fore.CYAN   + "😂 HUMOR"
                else:                                    label = Fore.WHITE  + "💬 NEU  "

                indicators = ""
                if analysis["is_sarcasm"]:  indicators += "🎭"
                if analysis["is_wellwish"]: indicators += "🙏"

                preview   = text[:55].replace("\n", " ")
                likes     = rc.get("like_count", 0)
                likes_str = f" [{likes:,}❤]" if likes > 0 else ""
                print(f"{label} #{i:3d} {indicators} @{entry['username'][:18]}: {preview}{likes_str}")

            if final_comments:
                t_s = time.time() - t_start
                print(Fore.CYAN + f"\n   ⏱️  Sentiment: {t_s:.1f}s ({t_s/len(final_comments)*1000:.0f}ms/komentar)")

            replies_n = sum(1 for c in final_comments if c.get("is_reply"))
            result["comments"]          = final_comments
            result["comments_count"]    = len(final_comments)
            result["top_level_count"]   = len(final_comments) - replies_n
            result["replies_count"]     = replies_n
            result["sentiment_summary"] = self._summarize(final_comments, result)
            result["success"]           = True  # FIX: set success = True
            print(Fore.GREEN + f"\n✅ Total: {result['top_level_count']} komentar + {replies_n} balasan")

        except Exception as e:
            print(Fore.RED + f"\n❌ GAGAL: {e}")
            import traceback
            traceback.print_exc()
            result["error"]   = str(e)
            result["success"] = False  # FIX: set success = False on error

        self._last_scrape_time = time.time()
        return result

    # ── DISPLAY & SUMMARY ─────────────────────────────────────────

    def _display_caption_box(self, caption: str, category: str, analysis: Dict):
        if analysis["is_hate_speech"]:
            color, icon, label = Fore.RED,     "🚨", "HATE SPEECH"
        elif analysis["is_toxic"]:
            color, icon, label = Fore.YELLOW,  "⚠️", "TOXIC"
        elif category == "POSITIVE":
            color, icon, label = Fore.GREEN,   "😊", "POSITIVE"
        elif category == "NEGATIVE":
            color, icon, label = Fore.MAGENTA, "😞", "NEGATIVE"
        elif category == "HUMOR":
            color, icon, label = Fore.CYAN,    "😂", "HUMOR"
        else:
            color, icon, label = Fore.WHITE,   "💬", "NEUTRAL"

        indicators = []
        if analysis.get("is_sarcasm"):  indicators.append("🎭 Sarcasm")
        if analysis.get("is_wellwish"): indicators.append("🙏 Wellwish")

        box_width = 68
        print("\n" + color + "┌" + "─" * box_width + "┐")
        print(color + "│" + " " * box_width + "│")
        print(color + "│" + "  📝 POST CAPTION / DESCRIPTION".center(box_width) + "│")
        print(color + "│" + " " * box_width + "│")
        print(color + "├" + "─" * box_width + "┤")

        sentiment_line = f"  {icon} {label}  |  {analysis['sentiment']}"
        if indicators:
            sentiment_line += f"  |  {', '.join(indicators)}"
        print(color + "│  " + sentiment_line.ljust(box_width - 2) + "│")

        if analysis.get("ml_confidence", 0) > 0:
            print(color + "│  " + f"  🎯 ML Confidence: {analysis['ml_confidence']:.1%}".ljust(box_width - 2) + "│")

        print(color + "├" + "─" * box_width + "┤")
        print(color + "│" + " " * box_width + "│")

        max_line_len = box_width - 6
        words = caption.split()
        lines, current = [], ""
        for word in words:
            if len(current) + len(word) + 1 <= max_line_len:
                current += (" " if current else "") + word
            else:
                if current: lines.append(current)
                current = word
        if current: lines.append(current)

        if len(lines) > 5:
            lines = lines[:5]
            lines[-1] = lines[-1][:max_line_len - 3] + "..."

        for line in lines:
            print(color + "│  " + line.ljust(box_width - 2) + "│")

        print(color + "│" + " " * box_width + "│")
        print(color + "└" + "─" * box_width + "┘")
        print(Fore.RESET)

    def _summarize(self, comments: List[Dict], post_data: Optional[Dict] = None) -> Dict:
        if not comments:
            return {"total_comments": 0}

        total  = len(comments)
        counts = {k: 0 for k in ("HATE_SPEECH", "TOXIC", "POSITIVE", "NEGATIVE", "NEUTRAL", "HUMOR")}
        hate_ex, toxic_ex = [], []
        sarcasm_count = wellwish_count = 0
        ds_counter    = Counter()
        ml_confs      = []

        for c in comments:
            cat = c.get("category", "NEUTRAL")
            if cat in counts: counts[cat] += 1
            if c.get("is_hate_speech"):
                hate_ex.append({"username": c["username"], "text": c["text"],
                                "hate_words": c["hate_words"], "like_count": c.get("like_count", 0)})
            if c.get("is_toxic"):
                toxic_ex.append({"username": c["username"], "text": c["text"],
                                 "toxic_words": c["toxic_words"]})
            if c.get("is_sarcasm"):  sarcasm_count  += 1
            if c.get("is_wellwish"): wellwish_count += 1
            ds_counter[c.get("decision_source", "unknown")] += 1
            mlc = c.get("ml_confidence", 0)
            if mlc > 0: ml_confs.append(mlc)

        sorted_by_likes = sorted(comments, key=lambda x: x.get("like_count", 0), reverse=True)
        top_liked = []
        for rank, c in enumerate(sorted_by_likes[:10], start=1):
            top_liked.append({
                "rank": rank, "username": c["username"], "text": c["text"][:200],
                "like_count": c.get("like_count", 0), "category": c.get("category", ""),
                "sentiment": c.get("sentiment", ""), "number": c.get("number", 0),
            })

        active_map = {}
        for c in comments:
            username = c.get("username") or "Unknown"
            item = active_map.setdefault(username, {
                "username": username,
                "count": 0,
                "comments_count": 0,
                "replies_count": 0,
                "reply_targets": Counter(),
                "total_likes": 0,
                "examples": [],
            })
            is_reply = bool(c.get("is_reply"))
            item["count"] += 1
            item["replies_count" if is_reply else "comments_count"] += 1
            item["total_likes"] += int(c.get("like_count", 0) or 0)
            if is_reply and c.get("reply_to"):
                item["reply_targets"][c.get("reply_to")] += 1
            if len(item["examples"]) < 3:
                item["examples"].append({
                    "number": c.get("number", 0),
                    "text": (c.get("text") or "")[:260],
                    "is_reply": is_reply,
                    "reply_to": c.get("reply_to", ""),
                    "like_count": c.get("like_count", 0),
                    "category": c.get("category", ""),
                    "sentiment": c.get("sentiment", ""),
                    "timestamp": c.get("timestamp", ""),
                })

        most_active = []
        for item in sorted(active_map.values(), key=lambda x: (x["count"], x["replies_count"], x["total_likes"]), reverse=True):
            if item["count"] <= 1:
                continue
            targets = item.pop("reply_targets")
            item["reply_targets"] = [
                {"username": target, "count": count}
                for target, count in targets.most_common(3)
                if target
            ]
            most_active.append(item)
            if len(most_active) >= 10:
                break

        def pct(n): return round(n / total * 100, 1) if total > 0 else 0
        avg_conf = round(sum(ml_confs) / len(ml_confs), 3) if ml_confs else 0.0

        s = {
            "total_comments":       total,
            "hate_speech_count":    counts["HATE_SPEECH"], "hate_percentage":     pct(counts["HATE_SPEECH"]),
            "toxic_count":          counts["TOXIC"],        "toxic_percentage":    pct(counts["TOXIC"]),
            "positive_count":       counts["POSITIVE"],     "positive_percentage": pct(counts["POSITIVE"]),
            "negative_count":       counts["NEGATIVE"],     "negative_percentage": pct(counts["NEGATIVE"]),
            "neutral_count":        counts["NEUTRAL"],      "neutral_percentage":  pct(counts["NEUTRAL"]),
            "humor_count":          counts["HUMOR"],        "humor_percentage":    pct(counts["HUMOR"]),
            "sarcasm_count":        sarcasm_count,          "sarcasm_percentage":  pct(sarcasm_count),
            "wellwish_count":       wellwish_count,         "wellwish_percentage": pct(wellwish_count),
            "avg_ml_confidence":    avg_conf,
            "decision_source_breakdown": dict(ds_counter),
            "hate_examples":        hate_ex[:10],
            "toxic_examples":       toxic_ex[:10],
            "top_liked_comments":   top_liked,
            "most_active_users":    most_active,
        }

        print(Fore.CYAN + "\n" + "=" * 55)
        print(Fore.CYAN + "📊 RINGKASAN SENTIMEN")
        print(Fore.CYAN + "=" * 55)
        print(f"  💬 Total komentar     : {total}")
        print(Fore.RED     + f"  🚨 Hate Speech        : {counts['HATE_SPEECH']:>4} ({pct(counts['HATE_SPEECH']):>5}%)")
        print(Fore.YELLOW  + f"  ⚠️  Toxic             : {counts['TOXIC']:>4} ({pct(counts['TOXIC']):>5}%)")
        print(Fore.GREEN   + f"  😊 Positif            : {counts['POSITIVE']:>4} ({pct(counts['POSITIVE']):>5}%)")
        print(Fore.MAGENTA + f"  😞 Negatif            : {counts['NEGATIVE']:>4} ({pct(counts['NEGATIVE']):>5}%)")
        print(Fore.WHITE   + f"  😐 Netral             : {counts['NEUTRAL']:>4} ({pct(counts['NEUTRAL']):>5}%)")
        print(Fore.CYAN    + f"  😂 Humor              : {counts['HUMOR']:>4} ({pct(counts['HUMOR']):>5}%)")
        if avg_conf > 0:
            print(Fore.CYAN + f"\n  🎯 Avg ML confidence  : {avg_conf:.1%}")

        if post_data:
            print(Fore.CYAN + "\n" + "=" * 55)
            print(Fore.CYAN + "📈 RINGKASAN ENGAGEMENT")
            print(Fore.CYAN + "=" * 55)
            print(Fore.CYAN + f"  ❤️  Reactions         : {post_data.get('total_likes', 0):>12,}")
            print(Fore.CYAN + f"  💬 Comments total     : {post_data.get('total_comments', 0):>12,}")
            print(Fore.CYAN + f"  📤 Shares             : {post_data.get('total_shares', 0):>12,}")

        return s

    def save(self, data: Dict, filename: str) -> str:
        fp = os.path.join(OUTPUT_DIR, filename)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(Fore.GREEN + f"\n💾 Tersimpan: {fp}")
        return fp

    # ── CLI ──────────────────────────────────────────────────────

    def run(self):
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + "  FACEBOOK SCRAPER V2.1 — PATCHED")
        print(Fore.CYAN + "  ✅ Cookie session dari session/fb_session.json")
        print(Fore.CYAN + "  ✅ Reel/video comment support (JS click bypass)")
        print(Fore.CYAN + "  ✅ Dedup pakai MD5 hash full text")
        print(Fore.CYAN + "  ✅ Sentiment analysis lengkap")
        print(Fore.CYAN + "=" * 70)

        while True:
            print(Fore.CYAN + "\n📋 MENU")
            print("  1. Scrape Single Post")
            print("  2. Scrape Multiple Posts (dari fb_urls.txt)")
            print("  3. Exit")

            choice = input(Fore.WHITE + "\nPilih [1-3]: ").strip()

            if choice == "1":
                url = input("\n🔗 URL post Facebook: ").strip()
                if not url:
                    continue
                raw   = input(f"Max komentar [{MAX_COMMENTS}]: ").strip()
                max_c = int(raw) if raw.isdigit() else MAX_COMMENTS

                t_start = time.time()
                result  = self.scrape_post(url, max_c)
                elapsed = time.time() - t_start

                print(Fore.CYAN + f"\n⏱️  Waktu total: {elapsed:.1f} detik")
                if result.get("comments_count", 0) > 0:
                    print(Fore.CYAN + f"📈 Rate: {result['comments_count'] / elapsed:.1f} komentar/detik")

                ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                self.save(result, f"fb_{ts}.json")

            elif choice == "2":
                url_file = input("\n📄 File URL (default: fb_urls.txt): ").strip() or "fb_urls.txt"
                if not os.path.exists(url_file):
                    print(Fore.RED + f"❌ {url_file} tidak ditemukan")
                    continue

                with open(url_file, "r", encoding="utf-8") as f:
                    urls = [l.strip() for l in f if l.strip() and not l.startswith("#")]

                raw  = input(f"Max post (tersedia {len(urls)}, Enter=semua): ").strip()
                urls = urls[:int(raw)] if raw.isdigit() else urls
                raw  = input(f"Max komentar per post [{MAX_COMMENTS}]: ").strip()
                max_c = int(raw) if raw.isdigit() else MAX_COMMENTS

                t_total = time.time()
                for idx, url in enumerate(urls, 1):
                    print(Fore.CYAN + f"\n[{idx}/{len(urls)}]")
                    result = self.scrape_post(url, max_c)
                    ts     = datetime.now().strftime('%Y%m%d_%H%M%S')
                    self.save(result, f"fb_{ts}_{idx}.json")
                    if idx < len(urls):
                        d = DELAY_BETWEEN_REQUESTS + random.randint(5, 12)
                        print(Fore.YELLOW + f"⏳ Jeda {d}s antar post...")
                        time.sleep(d)

                print(Fore.GREEN + f"\n✅ Selesai! {len(urls)} post dalam {time.time() - t_total:.1f}s")

            elif choice == "3":
                print(Fore.CYAN + "\n👋 Bye!")
                break
            else:
                print(Fore.RED + "❌ Pilihan tidak valid")


if __name__ == "__main__":
    with FacebookScraperV21(sentiment_mode=SENTIMENT_MODE) as scraper:
        scraper.run()
