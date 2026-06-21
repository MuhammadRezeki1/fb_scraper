# ============================================================
# FACEBOOK PROFILE SCRAPER V2.1 — COOKIE INJECTOR + EXTRACTION FIX
# ============================================================
# Fitur:
#   ✅ Cookie injector terintegrasi (fb_cookie_injector.py)
#   ✅ Session tersimpan di session/fb_session.json
#   ✅ Growth tracking tersimpan di data_fb_profiles/
#   ✅ Engagement anchor-first strategy (paling akurat)
#   ✅ Bio dari og:description (paling reliable)
#   ✅ Category dari pattern "Halaman · X" / "Page · X"
#   ✅ Name: hapus prefix notifikasi "(15)" / "(1)"
#   ✅ Website dari intro section + fallback plain text
#   ✅ Verified badge multi-pattern detection
#   ✅ DEBUG_DUMP mode (simpan HTML + anchors untuk troubleshoot)
#   ✅ Support URL dan username langsung
# ============================================================

import os
import re
import json
import time
import random
from datetime import datetime
from typing import Dict, Optional
from urllib.parse import urlparse, parse_qs, quote

from dotenv import load_dotenv
from colorama import Fore, init
from playwright.sync_api import sync_playwright, Page, BrowserContext, TimeoutError as PlaywrightTimeout
from browser_runtime import browser_channel_kwargs

init(autoreset=True)
load_dotenv()

# ── CONFIG ────────────────────────────────────────────────────
HEADLESS   = os.getenv("FB_HEADLESS", "False").lower() == "true"
PROXY      = os.getenv("FB_PROXY", "")
DEBUG_DUMP = os.getenv("DEBUG_DUMP", "0") == "1"

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
DATA_DIR          = os.path.join(os.getcwd(), "data_fb_profiles")
DEBUG_DIR         = os.path.join(os.getcwd(), "fb_debug_output")
TRACKING_FILE     = os.path.join(DATA_DIR, "growth_tracking.json")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FB_CHROME_PROFILE, exist_ok=True)
if DEBUG_DUMP:
    os.makedirs(DEBUG_DIR, exist_ok=True)


# ── HELPERS ───────────────────────────────────────────────────

# Path khusus FB yang BUKAN username/halaman
FB_PROFILE_RESERVED = {
    "share", "share_channel", "watch", "reel", "reels", "video", "videos",
    "photo", "photos", "story", "stories", "groups", "marketplace", "gaming",
    "events", "pages", "permalink", "sharer", "login", "home", "beranda",
    "messages", "notifications", "settings", "bookmarks", "live",
}


def extract_fb_username_from_url(url: str) -> str:
    """Extract username/page name dari link Facebook (clean, tanpa query params)."""
    url = url.strip()

    if not url.startswith('http') and '/' not in url:
        return url.lstrip('@')

    try:
        parsed = urlparse(url)
        path   = parsed.path.strip('/')
        parts  = [p for p in path.split('/') if p]

        if parts:
            if parts[0] == 'pages' and len(parts) > 1:
                return parts[-1] if parts[-1].isdigit() else parts[1]
            if parts[0] == 'profile.php':
                qs = parse_qs(parsed.query)
                if 'id' in qs:
                    return qs['id'][0]
            if parts[0] == 'groups' and len(parts) > 1:
                return parts[1]
            return parts[0]
    except Exception:
        pass

    match = re.search(r'facebook\.com/([a-zA-Z0-9_.\-]+)', url)
    if match:
        return match.group(1)

    return ""


def sanitize_filename(name: str) -> str:
    name = name.lstrip('@')
    name = re.sub(r'[<>:"/\\|?*]', '_', name)
    return name[:100]


# ============================================================
# MAIN PROFILE SCRAPER
# ============================================================

class FacebookProfileScraperV21:

    def __init__(self):
        print(Fore.CYAN + "\n🎭 Initializing Facebook Profile Scraper V2.1...")

        # FIX: deklarasi eksplisit dengan tipe Optional agar Pylance tahu
        self.context:    Optional[BrowserContext] = None
        self.page:       Optional[Page]           = None
        self.playwright                            = None

        self._last_scrape_time: float = 0.0
        self._min_gap_seconds:  int   = 30

        # Cek cookie session
        self._has_cookie_session = False
        try:
            from fb_cookie_injector import has_valid_session
            self._has_cookie_session = has_valid_session()
            if self._has_cookie_session:
                print(Fore.GREEN + "✅ Cookie session Facebook ditemukan")
        except ImportError:
            pass

        # Fallback ke chrome profile
        if not self._has_cookie_session:
            if not os.path.exists(FB_CHROME_PROFILE) or not os.listdir(FB_CHROME_PROFILE):
                print(Fore.RED + f"\n❌ Tidak ada session maupun Chrome profile!")
                print(Fore.YELLOW + "\n📋 Pilihan login:")
                print(Fore.CYAN + "   OPSI 1: python fb_cookie_injector.py")
                print(Fore.CYAN + "   OPSI 2: python fb_login_helper.py")
                exit(1)
            print(Fore.GREEN + f"✅ Facebook Chrome profile: {FB_CHROME_PROFILE}")

    def __enter__(self) -> "FacebookProfileScraperV21":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ── HELPER: assert self.page tidak None ───────────────────────

    def _page(self) -> Page:
        """Return self.page yang sudah dijamin non-None. Raise jika belum initialize."""
        if self.page is None:
            raise RuntimeError("Browser belum diinisialisasi. Panggil initialize_browser() dulu.")
        return self.page

    # ── BROWSER SETUP ──────────────────────────────────────────────

    def _build_context(self) -> BrowserContext:
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
            window.chrome = { runtime: {}, csi: function() { return {}; }, loadTimes: function() { return {}; } };
            Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en-US', 'en']});
            Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
            Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            try { delete Object.getPrototypeOf(navigator).webdriver; } catch(e) {}
            try { delete navigator.__proto__.webdriver; } catch(e) {}
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

        # FIX: wrap lambda biar return None, bukan SyncContextManager
        def _on_new_page(page: Page) -> None:
            page.add_init_script(stealth_script)

        context.on("page", _on_new_page)
        return context

    def _inject_cookies_if_available(self) -> bool:
        """Inject cookie session jika tersedia."""
        try:
            from fb_cookie_injector import inject_cookies_sync, has_valid_session
            if has_valid_session():
                n = inject_cookies_sync(self.context)
                print(Fore.GREEN + f"   🍪 {n} cookies Facebook diinject dari session")
                return True
        except ImportError:
            pass
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Cookie inject gagal: {e}")
        return False

    def initialize_browser(self) -> None:
        if self.context:
            return

        print(Fore.CYAN + "\n🌐 Membuka browser Facebook (Google Chrome ASLI + stealth)...")
        self.context = self._build_context()
        self.page    = self.context.pages[0] if self.context.pages else self.context.new_page()

        # FIX: gunakan _page() helper supaya Pylance tahu page non-None di bawah sini
        page = self._page()

        # Block media dan font, pertahankan gambar untuk profile pic
        def block_heavy(route):
            try:
                resource_type = route.request.resource_type
                if resource_type in ["media", "font"]:
                    route.abort()
                else:
                    route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass

        page.route("**/*", block_heavy)

        # Inject cookies sebelum navigasi pertama
        self._inject_cookies_if_available()

        print(Fore.CYAN + "   ☕ Buka homepage Facebook...")
        page.goto("https://www.facebook.com/")
        time.sleep(4)

        self._close_cookie_banners()

        if "login" in page.url:
            print(Fore.RED + "❌ Redirect ke login page. Session expired.")
            print(Fore.YELLOW + "   ➡️  Jalankan: python fb_cookie_injector.py")
            self.close()
            exit(1)

        print(Fore.GREEN + "✅ Browser Facebook siap (LOGGED IN ✓)")

    def _close_cookie_banners(self) -> None:
        page = self._page()
        selectors = [
            "[data-testid='cookie-policy-manage-dialog-accept-button']",
            "button:has-text('Terima semua')",
            "button:has-text('Accept all')",
            "button:has-text('Hanya cookie yang diperlukan')",
            "button:has-text('Only allow essential cookies')",
        ]
        for sel in selectors:
            try:
                el = page.locator(sel)
                if el.count() > 0 and el.first.is_visible(timeout=1000):
                    el.first.click(timeout=2000)
                    time.sleep(0.8)
            except Exception:
                pass

    def _close_login_popup(self) -> None:
        """Dismiss login prompt / modal yang bukan dialog konten."""
        page = self._page()
        try:
            selectors = [
                "[aria-label='Tutup']",
                "[aria-label='Close']",
                "div[role='dialog'] [aria-label='Tutup']",
                "div[role='dialog'] [aria-label='Close']",
            ]
            for sel in selectors:
                try:
                    el = page.locator(sel)
                    if el.count() > 0 and el.first.is_visible(timeout=500):
                        el.first.click(timeout=1500)
                        time.sleep(0.5)
                except Exception:
                    pass
        except Exception:
            pass

    def _enforce_rate_limit(self) -> None:
        if self._last_scrape_time <= 0:
            return
        elapsed = time.time() - self._last_scrape_time
        if elapsed < self._min_gap_seconds:
            wait = self._min_gap_seconds - elapsed
            print(Fore.YELLOW + f"\n⏱️  Rate-limit guard: tunggu {wait:.0f}s...")
            time.sleep(wait)

    def close(self) -> None:
        try:
            if self.context:
                self.context.close()
                self.context = None
            if self.playwright:
                self.playwright.stop()
                self.playwright = None
        except Exception:
            pass

    # ── NUMBER PARSER ─────────────────────────────────────────────

    def _parse_number(self, text: str) -> int:
        """
        Convert text format ke integer.
        Support: English (1.2M, 500K), Indonesia (1,2 jt, 500 rb), plain (12345)
        """
        if not text:
            return 0

        text = str(text).strip().lower()
        text = text.replace('\u00a0', ' ')
        text = re.sub(r'\s+', ' ', text)

        m = re.search(
            r'([\d.,]+)\s*(jt|juta|rb|ribu|million|thousand|billion|[kmbKMB])\b',
            text
        )
        if m:
            num_str = m.group(1)
            suffix  = m.group(2).lower()

            if num_str.count('.') > 1:
                num_str = num_str.replace('.', '')
            elif num_str.count(',') > 1:
                num_str = num_str.replace(',', '')
            else:
                num_str = num_str.replace(',', '.')

            try:
                num = float(num_str)
            except ValueError:
                return 0

            multipliers = {
                'jt': 1_000_000, 'juta': 1_000_000, 'million': 1_000_000, 'm': 1_000_000,
                'rb': 1_000,     'ribu': 1_000,      'thousand': 1_000,    'k': 1_000,
                'b':  1_000_000_000, 'billion': 1_000_000_000,
            }
            return int(num * multipliers.get(suffix, 1))

        clean = re.sub(r'[^\d]', '', text)
        try:
            return int(clean) if clean else 0
        except ValueError:
            return 0

    # ── EXTRACTION METHODS ────────────────────────────────────────

    def _extract_name(self) -> str:
        """Extract nama profile. Hapus prefix notifikasi '(15)' dan suffix '| Facebook'."""
        page = self._page()

        def clean_name(raw: str) -> str:
            if not raw:
                return ""
            cleaned = re.sub(r'^\(\d+\)\s*', '', raw)
            cleaned = re.split(r'\s*\|\s*Facebook', cleaned)[0]
            return cleaned.strip()

        # Strategy 1: h1 di header
        try:
            h1_count = page.locator("h1").count()
            for i in range(min(h1_count, 3)):
                h1  = page.locator("h1").nth(i)
                txt = (h1.inner_text() or "").strip()
                if txt and txt.lower() not in ('notifikasi', 'notifications') and len(txt) < 200:
                    return clean_name(txt)
        except Exception:
            pass

        # Strategy 2: og:title
        try:
            meta = page.locator("meta[property='og:title']").first
            if meta.count() > 0:
                content = meta.get_attribute("content") or ""
                if content:
                    return clean_name(content)
        except Exception:
            pass

        # Strategy 3: title page
        try:
            title = page.title()
            if title:
                return clean_name(title)
        except Exception:
            pass

        return ""

    def _extract_engagement_numbers(self) -> Dict[str, int]:
        """
        Anchor-first strategy untuk akurasi maksimal.
        1. Anchor links dengan path follower/following
        2. Fallback ke header text (batasi 5000 char pertama)
        """
        page   = self._page()
        result     = {"followers": 0, "following": 0, "likes": 0, "posts": 0}
        raw_values = {"followers": "", "following": "", "likes": "", "posts": ""}

        # Strategy 1: Anchor links (paling akurat)
        try:
            anchor_data = page.evaluate("""() => {
                const out = {followers_raw: '', following_raw: ''};
                const main = document.querySelector('[role="main"]');
                if (!main) return out;

                const anchors = main.querySelectorAll('a[href]');
                for (const a of anchors) {
                    const href = (a.getAttribute('href') || '').toLowerCase();
                    const txt  = (a.innerText || a.textContent || '').trim();
                    if (!txt || txt.length > 60) continue;
                    if (!/^[\\d]/.test(txt)) continue;

                    if (/\\/following(\\/|\\?|$)/.test(href) && !out.following_raw) {
                        out.following_raw = txt;
                    } else if (/\\/followers(\\/|\\?|$)/.test(href) && !out.followers_raw) {
                        out.followers_raw = txt;
                    }
                }
                return out;
            }""")

            if anchor_data:
                raw_values["followers"] = anchor_data.get("followers_raw", "")
                raw_values["following"] = anchor_data.get("following_raw", "")
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Anchor extract error: {e}")

        # Strategy 2: Header text (untuk likes & posts)
        try:
            header_text = page.evaluate("""() => {
                const main = document.querySelector('[role="main"]') || document.body;

                return (main.innerText || '').slice(0, 5000);
            }""") or ""

            patterns_map = {
                'followers': [
                    r'([\d.,]+\s*(?:jt|rb|juta|ribu|[KkMmBb])?)\s*(?:pengikut|followers?)\b',
                ],
                'following': [
                    r'([\d.,]+\s*(?:jt|rb|juta|ribu|[KkMmBb])?)\s*(?:mengikuti|following)\b',
                ],
                'likes': [
                    r'([\d.,]+\s*(?:jt|rb|juta|ribu|[KkMmBb])?)\s*(?:menyukai ini|orang menyukai|people like)',
                    r'([\d.,]+\s*(?:jt|rb|juta|ribu|[KkMmBb])?)\s*(?:suka|likes?)\b',
                ],
                'posts': [
                    r'([\d.,]+)\s*(?:postingan|posts?|kiriman)\b',
                ],
            }

            for field, patterns in patterns_map.items():
                if raw_values[field]:
                    continue
                for pattern in patterns:
                    match = re.search(pattern, header_text, re.IGNORECASE)
                    if match:
                        raw_values[field] = match.group(1).strip()
                        break
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Header text extract error: {e}")

        # Parse semua raw value
        for field in result:
            if raw_values[field]:
                result[field] = self._parse_number(raw_values[field])

        # Debug output
        print(Fore.CYAN + "   📊 Engagement raw → parsed:")
        for k in ["followers", "following", "likes", "posts"]:
            raw = raw_values[k] or "(none)"
            print(Fore.CYAN + f"     {k:10s}: '{raw}' → {result[k]:,}")

        # Auto-sync likes ↔ followers untuk modern FB Page
        if result['likes'] > 0 and result['followers'] == 0:
            result['followers'] = result['likes']
        elif result['followers'] > 0 and result['likes'] == 0:
            result['likes'] = result['followers']

        return result

    def _extract_bio_and_intro(self) -> Dict[str, str]:
        """
        Bio = og:description (paling reliable).
        Intro = section "Intro" / "Perkenalan" di profile.
        """
        page   = self._page()
        result = {"bio": "", "intro": ""}

        # Bio dari og:description
        try:
            meta = page.locator("meta[property='og:description']").first
            if meta.count() > 0:
                content = (meta.get_attribute("content") or "").strip()
                if 10 < len(content) < 1000:
                    result["bio"] = content
        except Exception:
            pass

        if not result["bio"]:
            try:
                meta = page.locator("meta[name='description']").first
                if meta.count() > 0:
                    content = (meta.get_attribute("content") or "").strip()
                    if 10 < len(content) < 1000:
                        result["bio"] = content
            except Exception:
                pass

        # Intro section
        try:
            intro_text = page.evaluate("""() => {
                const headings  = document.querySelectorAll('h2, span');
                const blacklist = [
                    'Foto', 'Lihat Semua Foto', 'Privasi', 'Ketentuan',
                    'Iklan', 'Cookie', 'Lainnya', 'Pilihan Iklan',
                    'See All Photos', 'Photos', 'Privacy', 'Terms',
                    'Ads', 'More', 'Halaman', 'Page',
                ];

                let introHeading = null;
                for (const h of headings) {
                    const t = (h.innerText || h.textContent || '').trim();
                    if (t === 'Intro' || t === 'Perkenalan') {
                        introHeading = h;
                        break;
                    }
                }
                if (!introHeading) return '';

                let container = introHeading.parentElement;
                for (let i = 0; i < 5 && container; i++) {
                    if (container.innerText && container.innerText.length > 50) break;
                    container = container.parentElement;
                }
                if (!container) return '';

                const fullText = container.innerText || '';
                const lines = fullText.split('\\n').map(l => l.trim()).filter(Boolean);

                const filtered = lines.filter(l => {
                    if (l === 'Intro' || l === 'Perkenalan') return false;
                    if (blacklist.some(b => l === b || l.startsWith(b + ' · '))) return false;
                    if (l.length < 5 || l.length > 300) return false;
                    if (l.match(/^[\\s·•]+$/)) return false;
                    return true;
                });

                return filtered.slice(0, 5).join(' | ');
            }""")

            if intro_text:
                result["intro"] = intro_text.strip()[:500]
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Intro extract error: {e}")

        # Fallback bio dari intro
        if not result["bio"] and result["intro"]:
            for part in result["intro"].split('|'):
                part = part.strip()
                if len(part) > 20 and not re.match(r'^https?://|^[\w-]+\.[\w]{2,}/', part):
                    result["bio"] = part[:500]
                    break

        return result

    def _extract_extra_info(self) -> Dict:
        """Extract category, verified, website, email, phone, profile/cover images, is_page."""
        page   = self._page()
        result = {
            "category":            "",
            "verified":            False,
            "website":             "",
            "email":               "",
            "phone":               "",
            "address":             "",
            "profile_picture_url": "",
            "cover_photo_url":      "",
            "is_page":             False,
        }

        try:
            data = page.evaluate("""() => {
                const out = {
                    category: '', verified: false, website: '',
                    email: '', phone: '', address: '',
                    profile_picture_url: '', cover_photo_url: '', is_page: false
                };

                // Profile picture
                const ogImage = document.querySelector('meta[property="og:image"]');
                if (ogImage) out.profile_picture_url = ogImage.getAttribute('content') || '';

                const main = document.querySelector('[role="main"]') || document.body;

                const cleanImageUrl = (url) => {
                    if (!url) return '';
                    if (url.startsWith('data:') || url.startsWith('blob:')) return '';
                    return url;
                };

                const imageCandidates = [];
                main.querySelectorAll('img[src], image[href], image[xlink\\\\:href]').forEach((img) => {
                    const src = cleanImageUrl(
                        img.getAttribute('src') ||
                        img.getAttribute('href') ||
                        img.getAttribute('xlink:href') ||
                        ''
                    );
                    if (!src || !/(scontent|fbcdn|akamaihd)/i.test(src)) return;

                    const rect = img.getBoundingClientRect();
                    const width = img.naturalWidth || rect.width || 0;
                    const height = img.naturalHeight || rect.height || 0;
                    const alt = (img.getAttribute('alt') || '').toLowerCase();
                    const aria = (img.getAttribute('aria-label') || '').toLowerCase();

                    imageCandidates.push({
                        src,
                        width,
                        height,
                        top: rect.top,
                        left: rect.left,
                        alt,
                        aria,
                        score: (width * height) + Math.max(0, 900 - Math.abs(rect.top)) * 5
                    });
                });

                if (!out.profile_picture_url) {
                    const profileLike = imageCandidates.find((c) => {
                        const label = `${c.alt} ${c.aria}`;
                        const nearSquare = c.width > 60 && c.height > 60 &&
                            Math.abs(c.width - c.height) < Math.max(c.width, c.height) * 0.35;
                        return nearSquare && (label.includes('profile') || label.includes('profil') || label.includes('foto'));
                    });
                    if (profileLike) out.profile_picture_url = profileLike.src;
                }

                const coverCandidate = imageCandidates
                    .filter((c) => {
                        const isWide = c.width >= 300 && c.width >= c.height * 1.6;
                        const nearHeader = c.top < 650;
                        return isWide && nearHeader && c.src !== out.profile_picture_url;
                    })
                    .sort((a, b) => b.score - a.score)[0];
                if (coverCandidate) out.cover_photo_url = coverCandidate.src;

                // Verified badge — multi-pattern
                const verifiedSelectors = [
                    '[aria-label*="Diverifikasi"]', '[aria-label*="Verified"]',
                    '[aria-label*="diverifikasi"]', '[aria-label*="verified"]',
                    '[aria-label*="terverifikasi"]', '[aria-label*="Akun terverifikasi"]',
                    '[aria-label*="Halaman terverifikasi"]',
                ];
                for (const sel of verifiedSelectors) {
                    if (main.querySelector(sel)) { out.verified = true; break; }
                }

                if (!out.verified) {
                    const svgTitles = main.querySelectorAll('svg title');
                    for (const t of svgTitles) {
                        const txt = (t.textContent || '').toLowerCase();
                        if (txt.includes('verif') || txt.includes('terverif')) {
                            out.verified = true; break;
                        }
                    }
                }

                // Category: "Halaman · X" atau "Page · X"
                const mainText = main.innerText || '';
                const catMatch = mainText.match(/(?:Halaman|Page)\\s*·\\s*([^\\n·]{3,80})/);
                if (catMatch) {
                    out.category = catMatch[1].trim();
                    out.is_page  = true;
                }

                // Email
                const emailMatch = mainText.match(/[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}/);
                if (emailMatch) out.email = emailMatch[0];

                // Phone (format ID)
                const phoneMatch = mainText.match(/(?:\\+62|0)8[0-9]{1,3}[\\s-]?[0-9]{3,5}[\\s-]?[0-9]{3,5}/);
                if (phoneMatch) out.phone = phoneMatch[0].trim();

                // Website dari intro section
                let introHeading = null;
                const headings = main.querySelectorAll('h2, span');
                for (const h of headings) {
                    const t = (h.innerText || '').trim();
                    if (t === 'Intro' || t === 'Perkenalan') { introHeading = h; break; }
                }

                if (introHeading) {
                    let container = introHeading.parentElement;
                    for (let i = 0; i < 5 && container; i++) {
                        if (container.querySelectorAll('a').length > 0) break;
                        container = container.parentElement;
                    }
                    if (container) {
                        const links = container.querySelectorAll('a[href]');
                        for (const link of links) {
                            const href = link.getAttribute('href') || '';
                            const text = (link.innerText || '').trim();

                            if (!href || href.startsWith('#')) continue;
                            if (href.includes('facebook.com') || href.includes('fb.com')) continue;
                            if (href.includes('messenger.com')) continue;
                            if (href.match(/\\.(jpg|jpeg|png|gif|webp|svg)(\\?|$)/i)) continue;
                            if (href.includes('fbcdn')) continue;
                            if (href.startsWith('mailto:') || href.startsWith('tel:')) continue;
                            if (text && text.length > 100) continue;

                            let cleanUrl = href;
                            if (href.includes('/l.php?')) {
                                try {
                                    const u = new URL(href, 'https://www.facebook.com');
                                    const real = u.searchParams.get('u');
                                    if (real) cleanUrl = decodeURIComponent(real);
                                } catch(e) {}
                            }

                            if (cleanUrl.startsWith('http') && !out.website) {
                                out.website = cleanUrl.substring(0, 300);
                                break;
                            }
                        }

                        // Fallback: plain text URL di container
                        if (!out.website) {
                            const containerText = container.innerText || '';
                            const urlPatterns = [
                                /\\b(https?:\\/\\/[^\\s|]+)/i,
                                /\\b([a-z0-9-]+\\.(?:com|net|org|io|co|id|me|ly|gov|edu|app|link|tree|page)(?:\\/[^\\s|]*)?)/i,
                            ];
                            for (const pat of urlPatterns) {
                                const m = containerText.match(pat);
                                if (m) {
                                    let url = m[1];
                                    if (!url.startsWith('http')) url = 'https://' + url;
                                    out.website = url.substring(0, 300);
                                    break;
                                }
                            }
                        }
                    }
                }

                // Fallback is_page
                if (!out.is_page) {
                    const headerText = mainText.slice(0, 3000);
                    if (/menyukai ini|people like this|orang menyukai/i.test(headerText)) {
                        out.is_page = true;
                    }
                }

                return out;
            }""")

            if data:
                result.update(data)
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Extra info extract error: {e}")

        return result

    # ── DEBUG DUMP ────────────────────────────────────────────────

    def _dump_debug(self, username: str) -> None:
        """Simpan HTML + screenshot + anchors untuk debugging manual."""
        page = self._page()
        try:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            sub_dir   = os.path.join(DEBUG_DIR, f"{username}_{timestamp}")
            os.makedirs(sub_dir, exist_ok=True)

            html = page.content()
            with open(os.path.join(sub_dir, "page.html"), 'w', encoding='utf-8') as f:
                f.write(html)

            page.screenshot(
                path=os.path.join(sub_dir, "page.png"),
                full_page=False
            )

            anchors = page.evaluate("""() => {
                const links  = document.querySelectorAll('a[href]');
                const result = [];
                for (const a of links) {
                    const text = (a.innerText || '').trim();
                    if (!text || text.length > 100) continue;
                    result.push({text: text.substring(0, 100), href: a.getAttribute('href') || ''});
                }
                return result.slice(0, 100);
            }""")

            with open(os.path.join(sub_dir, "anchors.json"), 'w', encoding='utf-8') as f:
                json.dump(anchors, f, indent=2, ensure_ascii=False)

            print(Fore.YELLOW + f"   🔍 Debug dump: {sub_dir}")
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Debug dump gagal: {e}")

    # ── MAIN SCRAPE ───────────────────────────────────────────────

    def scrape_profile(self, url_or_username: str) -> Dict:
        """
        Scrape single profile.
        Mendukung: URL lengkap, username biasa, username dengan @
        """
        url_or_username = url_or_username.strip()
        username = extract_fb_username_from_url(url_or_username)

        if not username:
            return {
                "username":   url_or_username,
                "scraped_at": datetime.now().isoformat(),
                "platform":   "facebook",
                "success":    False,
                "error":      f"Username tidak valid dari input: {url_or_username}",
            }

        url = url_or_username if url_or_username.startswith("http") else f"https://www.facebook.com/{quote(username, safe='')}"

        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + f"👤 Scraping: @{username}")
        print(Fore.CYAN + "=" * 70)

        result: Dict = {
            "username":   username,
            "scraped_at": datetime.now().isoformat(),
            "platform":   "facebook",
            "data":       {},
            "success":    False,
            "error":      None,
        }

        try:
            self.initialize_browser()
            self._enforce_rate_limit()

            # Setelah initialize_browser(), self.page pasti non-None
            page = self._page()

            print(Fore.YELLOW + f"\n🌍 Navigasi ke: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except PlaywrightTimeout:
                pass

            current_url = page.url
            if "login" in current_url or "checkpoint" in current_url:
                raise Exception("Redirect ke login/checkpoint! Session expired.")

            # ── Resolusi redirect ──
            final_url = page.url
            content_markers = [
                "/posts/", "/permalink/", "/videos/", "/video/", "/reel/",
                "/reels/", "/watch", "/photo", "/share/p/", "/share/v/", "/share/r/",
            ]
            if any(seg in final_url for seg in content_markers):
                raise Exception(
                    "Link mengarah ke konten (post/video/reel), bukan profil/halaman. "
                    "Gunakan URL profil/halaman, contoh: facebook.com/namahalaman"
                )

            resolved = extract_fb_username_from_url(final_url)
            if resolved and resolved.lower() not in FB_PROFILE_RESERVED:
                if resolved != username:
                    print(Fore.CYAN + f"   🔀 Redirect → username sebenarnya: {resolved}")
                username = resolved
            elif username.lower() in FB_PROFILE_RESERVED or not username:
                raise Exception(f"Tidak bisa menemukan profil/halaman dari link: {url_or_username}")

            result["username"] = username

            self._close_login_popup()

            # Scroll untuk trigger lazy-load
            print(Fore.CYAN + "   📜 Scroll untuk load konten lengkap...")
            for i in range(3):
                page.evaluate(f"window.scrollBy(0, {400 + i * 200})")
                time.sleep(1.5)

            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(2)

            if DEBUG_DUMP:
                self._dump_debug(username)

            print(Fore.CYAN + "   📊 Extracting profile data...")

            name     = self._extract_name()
            bio_info = self._extract_bio_and_intro()
            numbers  = self._extract_engagement_numbers()
            extras   = self._extract_extra_info()

            profile_data = {
                "username":            username,
                "scraped_at":          datetime.now().isoformat(),
                "platform":            "facebook",
                "profile_url":         current_url,
                "name":                name,
                "bio":                 bio_info.get("bio", ""),
                "intro":               bio_info.get("intro", ""),
                "category":            extras.get("category", ""),
                "verified":            extras.get("verified", False),
                "is_page":             extras.get("is_page", False),
                "followers":           numbers.get("followers", 0),
                "following":           numbers.get("following", 0),
                "likes":               numbers.get("likes", 0),
                "posts":               numbers.get("posts", 0),
                "website":             extras.get("website", ""),
                "email":               extras.get("email", ""),
                "phone":               extras.get("phone", ""),
                "address":             extras.get("address", ""),
                "profile_picture_url": extras.get("profile_picture_url", ""),
                "cover_photo_url":      extras.get("cover_photo_url", ""),
            }

            self._display_profile_box(profile_data)

            result["success"] = True
            result["data"]    = profile_data

        except Exception as e:
            print(Fore.RED + f"\n❌ GAGAL: {e}")
            import traceback
            traceback.print_exc()
            result["error"] = str(e)

        self._last_scrape_time = time.time()
        return result

    def _display_profile_box(self, data: Dict) -> None:
        """Display profil dalam box yang rapi."""
        box = 68
        print("\n" + Fore.CYAN + "┌" + "─" * box + "┐")
        print(Fore.CYAN + "│" + " " * box + "│")
        print(Fore.CYAN + "│" + "  👤 PROFIL FACEBOOK".center(box) + "│")
        print(Fore.CYAN + "│" + " " * box + "│")
        print(Fore.CYAN + "├" + "─" * box + "┤")

        verified  = " ✓" if data.get("verified") else ""
        page_type = "PAGE" if data.get("is_page") else "PROFILE"
        print(Fore.CYAN + "│  " + f"@{data['username']}{verified} [{page_type}]".ljust(box - 2) + "│")
        if data.get("name"):
            print(Fore.CYAN + "│  " + f"{data['name']}".ljust(box - 2) + "│")
        if data.get("category"):
            print(Fore.CYAN + "│  " + f"📂 {data['category']}".ljust(box - 2) + "│")

        print(Fore.CYAN + "├" + "─" * box + "┤")
        print(Fore.CYAN + "│" + " " * box + "│")
        print(Fore.CYAN + "│  " + f"👥 Followers  : {data['followers']:>15,}".ljust(box - 2) + "│")
        print(Fore.CYAN + "│  " + f"👤 Following  : {data['following']:>15,}".ljust(box - 2) + "│")
        print(Fore.CYAN + "│  " + f"❤️  Likes      : {data['likes']:>15,}".ljust(box - 2) + "│")
        print(Fore.CYAN + "│  " + f"📝 Posts      : {data['posts']:>15,}".ljust(box - 2) + "│")

        if data["followers"] > 0 and data["posts"] > 0:
            eng = (data["likes"] / data["followers"]) * 100
            print(Fore.CYAN + "│  " + f"📊 Engagement : {eng:>14.2f}%".ljust(box - 2) + "│")

        print(Fore.CYAN + "│" + " " * box + "│")

        if data.get("bio"):
            print(Fore.CYAN + "├" + "─" * box + "┤")
            print(Fore.CYAN + "│  " + "📝 Bio:".ljust(box - 2) + "│")
            max_len = box - 6
            words = data["bio"].split()
            lines: list = []
            current = ""
            for word in words:
                if len(current) + len(word) + 1 <= max_len:
                    current += (" " if current else "") + word
                else:
                    if current:
                        lines.append(current)
                    current = word
            if current:
                lines.append(current)
            for line in lines[:5]:
                print(Fore.CYAN + "│  " + line.ljust(box - 2) + "│")

        if data.get("website"):
            print(Fore.CYAN + "│  " + f"🌐 {data['website'][:box-6]}".ljust(box - 2) + "│")
        if data.get("email"):
            print(Fore.CYAN + "│  " + f"✉️  {data['email']}".ljust(box - 2) + "│")
        if data.get("phone"):
            print(Fore.CYAN + "│  " + f"📞 {data['phone']}".ljust(box - 2) + "│")

        print(Fore.CYAN + "│" + " " * box + "│")
        print(Fore.CYAN + "└" + "─" * box + "┘")
        print(Fore.RESET)

    # ── GROWTH TRACKING ───────────────────────────────────────────

    def save_tracking_data(self, profile_result: Dict) -> None:
        """Simpan hasil scrape profil ke growth_tracking.json."""
        try:
            data       = profile_result.get("data", {}) or {}
            username   = data.get("username") or profile_result.get("username", "")
            if not username:
                return

            tracking   = self._load_tracking()
            scraped_at = data.get("scraped_at", datetime.now().isoformat())

            if username not in tracking:
                tracking[username] = {
                    "username":      username,
                    "first_tracked": scraped_at,
                    "history":       [],
                }

            snapshot = {
                "scraped_at": scraped_at,
                "followers":  data.get("followers", 0),
                "following":  data.get("following", 0),
                "likes":      data.get("likes", 0),
                "posts":      data.get("posts", 0),
            }

            today   = scraped_at[:10]
            history = tracking[username].get("history", [])
            updated = False
            for h in history:
                if h.get("scraped_at", "")[:10] == today:
                    h.update(snapshot)
                    updated = True
                    break
            if not updated:
                tracking[username]["history"].append(snapshot)

            tracking[username]["last_tracked"] = scraped_at
            self._save_tracking(tracking)
            print(Fore.GREEN + f"   💾 Growth tracking updated: @{username}")
        except Exception as e:
            print(Fore.YELLOW + f"   ⚠️  Tracking save warning: {e}")

    def _load_tracking(self) -> dict:
        if not os.path.exists(TRACKING_FILE):
            return {}
        try:
            with open(TRACKING_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_tracking(self, data: dict) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(TRACKING_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get_all_tracked_users(self) -> list:
        tracking = self._load_tracking()
        return sorted(tracking.keys())

    def save(self, data: Dict, filename: str) -> str:
        fp = os.path.join(DATA_DIR, filename)
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(Fore.GREEN + f"\n💾 Tersimpan: {fp}")
        return fp

    # ── CLI ──────────────────────────────────────────────────────

    def run(self) -> None:
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + "  FACEBOOK PROFILE SCRAPER V2.1 — COOKIE INJECTOR")
        print(Fore.CYAN + "  ✅ Cookie session dari session/fb_session.json")
        print(Fore.CYAN + "  ✅ Anchor-first engagement extraction")
        print(Fore.CYAN + "  ✅ Bio dari og:description (paling reliable)")
        print(Fore.CYAN + "  ✅ Category dari pattern 'Halaman · X'")
        print(Fore.CYAN + "  ✅ Growth tracking otomatis")
        print(Fore.CYAN + "  ✅ Debug dump mode (set DEBUG_DUMP=1)")
        print(Fore.CYAN + "=" * 70)

        while True:
            print(Fore.CYAN + "\n📋 MENU")
            print("  1. Scrape Single Profile")
            print("  2. Scrape Multiple Profiles (dari fb_usernames.txt)")
            print("  3. Lihat tracked profiles")
            print("  4. Exit")

            choice = input(Fore.WHITE + "\nPilih [1-4]: ").strip()

            if choice == "1":
                print(Fore.CYAN + "\n💡 Format input:")
                print("   • Username  : prabowo")
                print("   • URL       : https://www.facebook.com/prabowo")
                raw_input = input(Fore.WHITE + "\n👤 Username / URL: ").strip()
                if not raw_input:
                    continue

                t_start = time.time()
                result  = self.scrape_profile(raw_input)
                elapsed = time.time() - t_start
                print(Fore.CYAN + f"\n⏱️  Waktu: {elapsed:.1f} detik")

                if result["success"]:
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    self.save(result["data"], f"profile_{result['username']}_{ts}.json")
                    self.save_tracking_data(result)

            elif choice == "2":
                fname = input("\n📄 File usernames (default: fb_usernames.txt): ").strip() or "fb_usernames.txt"
                if not os.path.exists(fname):
                    print(Fore.RED + f"❌ {fname} tidak ditemukan")
                    continue

                with open(fname, "r", encoding="utf-8") as f:
                    usernames = [l.strip() for l in f if l.strip() and not l.startswith("#")]

                raw = input(f"Max profiles (tersedia {len(usernames)}, Enter=semua): ").strip()
                usernames = usernames[:int(raw)] if raw.isdigit() else usernames

                delay_input = input("Jeda antar profil (detik) [15]: ").strip()
                delay       = int(delay_input) if delay_input.isdigit() else 15

                t_total   = time.time()
                success_n = 0
                for idx, raw_input in enumerate(usernames, 1):
                    print(Fore.CYAN + f"\n[{idx}/{len(usernames)}]")
                    result = self.scrape_profile(raw_input)
                    if result["success"]:
                        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                        self.save(result["data"], f"profile_{result['username']}_{ts}.json")
                        self.save_tracking_data(result)
                        success_n += 1
                    if idx < len(usernames):
                        d = delay + random.randint(3, 8)
                        print(Fore.YELLOW + f"⏳ Jeda {d}s...")
                        time.sleep(d)

                print(Fore.GREEN + f"\n✅ Selesai! {success_n}/{len(usernames)} berhasil dalam {time.time()-t_total:.1f}s")

            elif choice == "3":
                users    = self.get_all_tracked_users()
                tracking = self._load_tracking()
                if not users:
                    print(Fore.YELLOW + "\n⚠️  Belum ada data tracking. Scrape profile dulu.")
                else:
                    print(Fore.CYAN + f"\n📊 {len(users)} akun ter-track:")
                    for u in users:
                        h = tracking[u].get("history", [])
                        latest = h[-1] if h else {}
                        print(f"  @{u:<30} {len(h):>3}x | followers: {latest.get('followers', 0):>10,}")

            elif choice == "4":
                print(Fore.CYAN + "\n👋 Bye!")
                break
            else:
                print(Fore.RED + "❌ Pilihan tidak valid")


if __name__ == "__main__":
    with FacebookProfileScraperV21() as scraper:
        scraper.run()
