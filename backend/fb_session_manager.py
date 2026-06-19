"""
fb_session_manager.py
=====================
CLI untuk manage session Facebook via Cookie-Editor JSON.

Cara pakai:
  1. Login Facebook di browser biasa (Chrome/Firefox)
  2. Install ekstensi Cookie-Editor
  3. Export cookies → Copy (JSON format)
  4. Jalankan: python fb_session_manager.py
  5. Pilih menu 1 → Paste JSON cookies → Enter 2x
  6. Session tersimpan di session/fb_session.json

Menu:
  1. Import cookies (paste JSON dari Cookie-Editor)
  2. Import cookies dari file JSON
  3. Cek status session
  4. Hapus session
  5. Export session info (untuk debugging)
  6. Test session (buka browser & verifikasi)
  7. Login via browser (tanpa Cookie-Editor)
  8. Exit
"""
import os
import sys
import json
import time
import threading
from datetime import datetime
from typing import List, Dict, Optional

from colorama import Fore, Style, init

init(autoreset=True)

# Import cookie injector Facebook
try:
    from fb_cookie_injector import (
        save_session,
        load_raw_cookies,
        has_valid_session,
        get_session_info,
        delete_session,
        SESSION_FILE,
        SESSION_DIR,
        REQUIRED_COOKIES,
        PREFERRED_COOKIES,
        FACEBOOK_DOMAINS,
    )
except ImportError:
    print(Fore.RED + "❌ fb_cookie_injector.py tidak ditemukan!")
    sys.exit(1)


# ── HELPERS ───────────────────────────────────────────────────────────────

def print_banner():
    print(Fore.CYAN + "\n" + "=" * 70)
    print(Fore.CYAN + "  FACEBOOK SESSION MANAGER")
    print(Fore.CYAN + "  Manage cookies login Facebook via Cookie-Editor JSON")
    print(Fore.CYAN + "=" * 70)


def print_instructions():
    print(Fore.YELLOW + """
📋 CARA LOGIN VIA COOKIE-EDITOR:

1. Buka browser Chrome/Firefox
2. Pergi ke https://www.facebook.com dan login manual
3. Setelah login berhasil, install ekstensi:
   • Chrome : https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm
   • Firefox: https://addons.mozilla.org/en-US/firefox/addon/cookie-editor/

4. Klik icon Cookie-Editor → klik "Export" → pilih "Export as JSON"
5. Semua cookies ter-copy ke clipboard
6. Kembali ke sini → pilih menu [1] → paste JSON → Enter 2x

💡 Tips:
   - Pastikan sudah login Facebook sebelum export
   - Cookie akan expired setelah beberapa hari/minggu
   - Jika scraper error "session expired", ulangi proses ini
   - Cookies yang diperlukan: c_user (wajib), xs (wajib)
   - Cookies yang disarankan: datr, fr, sb, wd
""")


def print_session_status(detailed: bool = False):
    """Print status session saat ini."""
    info = get_session_info()

    print(Fore.CYAN + "\n" + "─" * 55)
    print(Fore.CYAN + "📊 STATUS SESSION FACEBOOK")
    print(Fore.CYAN + "─" * 55)

    if not info.get("valid"):
        print(Fore.RED + "  ❌ Session TIDAK VALID / belum ada")
        if info.get("error"):
            print(Fore.RED + f"  Error: {info['error']}")
        return

    print(Fore.GREEN + "  ✅ Session VALID")
    print(Fore.WHITE + f"  📁 File         : {info.get('session_file', '-')}")
    print(Fore.WHITE + f"  👤 User ID       : {info.get('user_id', '-')}")
    print(Fore.WHITE + f"  🍪 Total cookies : {info.get('total_cookies', 0)}")

    if info.get("has_preferred"):
        print(Fore.GREEN + f"  ⭐ Preferred cookies: LENGKAP")
    else:
        missing = info.get("preferred_missing", [])
        if missing:
            print(Fore.YELLOW + f"  ⚠️  Preferred missing: {', '.join(missing)}")

    if info.get("xs_expiry"):
        try:
            exp_dt = datetime.fromtimestamp(float(info["xs_expiry"])).strftime("%Y-%m-%d %H:%M")
            print(Fore.WHITE + f"  ⏰ xs Expiry     : {exp_dt}")
        except Exception:
            pass

    if detailed and info.get("cookie_names"):
        print(Fore.CYAN + "\n  📋 Cookie names:")
        for name in info["cookie_names"]:
            if name in REQUIRED_COOKIES:
                marker = Fore.GREEN + "  ✅"
            elif name in PREFERRED_COOKIES:
                marker = Fore.YELLOW + "  ⭐"
            else:
                marker = Fore.WHITE + "    "
            print(f"  {marker} {name}" + Fore.RESET)

    print(Fore.CYAN + "─" * 55)


# ── MENU 1: IMPORT DARI CLIPBOARD ─────────────────────────────────────────

def import_cookies_from_clipboard() -> bool:
    """Minta user paste JSON cookies dari Cookie-Editor."""
    print(Fore.CYAN + "\n" + "=" * 70)
    print(Fore.CYAN + "  IMPORT COOKIES DARI COOKIE-EDITOR (PASTE)")
    print(Fore.CYAN + "=" * 70)

    print_instructions()

    print(Fore.YELLOW + "📥 Paste JSON cookies di bawah ini.")
    print(Fore.YELLOW + "   Setelah paste, tekan ENTER 2x (baris kosong) untuk selesai:\n")

    lines = []
    try:
        while True:
            try:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            except EOFError:
                break
    except KeyboardInterrupt:
        print(Fore.YELLOW + "\n⚠️  Dibatalkan")
        return False

    raw_text = "\n".join(lines).strip()
    if not raw_text:
        print(Fore.RED + "❌ Tidak ada input")
        return False

    return _process_and_save_cookies(raw_text)


# ── MENU 2: IMPORT DARI FILE ──────────────────────────────────────────────

def import_cookies_from_file() -> bool:
    """Import cookies dari file JSON."""
    print(Fore.CYAN + "\n" + "=" * 70)
    print(Fore.CYAN + "  IMPORT COOKIES DARI FILE JSON")
    print(Fore.CYAN + "=" * 70)

    filepath = input(Fore.WHITE + "\n📂 Path file JSON cookies: ").strip().strip('"').strip("'")
    if not filepath:
        print(Fore.RED + "❌ Path tidak boleh kosong")
        return False

    if not os.path.exists(filepath):
        print(Fore.RED + f"❌ File tidak ditemukan: {filepath}")
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            raw_text = f.read()
        print(Fore.GREEN + f"✅ File dibaca: {filepath}")
        return _process_and_save_cookies(raw_text)
    except Exception as e:
        print(Fore.RED + f"❌ Gagal baca file: {e}")
        return False


# ── SHARED COOKIE PROCESSOR ───────────────────────────────────────────────

def _process_and_save_cookies(raw_text: str) -> bool:
    """Parse, validasi, dan simpan cookies dari raw JSON string."""
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        print(Fore.RED + f"❌ JSON tidak valid: {e}")
        print(Fore.YELLOW + "   Pastikan format JSON benar dari Cookie-Editor")
        return False

    # Support format array langsung atau {cookies: [...]}
    if isinstance(raw, list):
        cookies = raw
    elif isinstance(raw, dict) and "cookies" in raw:
        cookies = raw["cookies"]
    else:
        print(Fore.RED + "❌ Format tidak dikenali — harus array atau {cookies: [...]}")
        return False

    if not isinstance(cookies, list) or len(cookies) == 0:
        print(Fore.RED + "❌ Cookies kosong atau format salah")
        return False

    # FIX: gunakan .get() untuk optional keys di Playwright Cookie TypedDict
    names = {c.get("name", "") for c in cookies if isinstance(c, dict)}
    missing_required = REQUIRED_COOKIES - names

    if missing_required:
        print(Fore.RED + f"❌ Cookie wajib tidak ada: {', '.join(missing_required)}")
        print(Fore.YELLOW + "   Pastikan sudah login Facebook sebelum export cookies")
        print(Fore.YELLOW + f"   Cookie wajib: {', '.join(REQUIRED_COOKIES)}")
        return False

    # Filter hanya cookies Facebook
    fb_cookies = [
        c for c in cookies
        if isinstance(c, dict) and any(
            domain in str(c.get("domain", "")).lower()
            for domain in ["facebook.com", "fbcdn.net"]
        )
    ]

    if not fb_cookies:
        print(Fore.YELLOW + "⚠️  Tidak ada cookie domain facebook.com, pakai semua cookies...")
        fb_cookies = [c for c in cookies if isinstance(c, dict)]

    # Info sebelum simpan
    fb_names = {c.get("name", "") for c in fb_cookies}
    print(Fore.CYAN + f"\n📋 Preview:")
    print(Fore.WHITE + f"   Total cookies  : {len(fb_cookies)}")
    print(Fore.WHITE + f"   Required (✅)   : {', '.join(REQUIRED_COOKIES & fb_names)}")
    preferred_found = PREFERRED_COOKIES & fb_names
    if preferred_found:
        print(Fore.WHITE + f"   Preferred (⭐)  : {', '.join(preferred_found)}")
    preferred_missing = PREFERRED_COOKIES - fb_names
    if preferred_missing:
        print(Fore.YELLOW + f"   Missing (⚠️)    : {', '.join(preferred_missing)}")

    # FIX: gunakan .get() untuk optional keys
    user_id = next((c.get("value", "") for c in fb_cookies if c.get("name") == "c_user"), "")
    if user_id:
        print(Fore.WHITE + f"   User ID        : {user_id}")

    # Minta username (opsional)
    username = input(Fore.WHITE + "\n👤 Username/nama Facebook (opsional, tekan Enter skip): ").strip()

    # Simpan
    print(Fore.CYAN + f"\n💾 Menyimpan {len(fb_cookies)} cookies...")
    session_path = save_session(fb_cookies, username=username)

    print(Fore.GREEN + f"✅ Session tersimpan: {session_path}")

    # Tampilkan status
    print_session_status()
    return True


# ── MENU 3: CEK STATUS ────────────────────────────────────────────────────

def check_status():
    print_session_status(detailed=True)

    if has_valid_session():
        try:
            raw = load_raw_cookies()
            print(Fore.CYAN + "\n📋 Preview cookies (5 pertama):")
            for c in raw[:5]:
                # FIX: gunakan .get() untuk optional keys di Cookie TypedDict
                name  = c.get("name", "")
                value = str(c.get("value", ""))[:20]
                exp   = c.get("expirationDate", "")
                if exp:
                    try:
                        exp_dt = datetime.fromtimestamp(float(exp)).strftime("%Y-%m-%d")
                        exp_str = f" (exp: {exp_dt})"
                    except Exception:
                        exp_str = ""
                else:
                    exp_str = " (session)"
                print(Fore.WHITE + f"   {name:<25} = {value}...{exp_str}")
        except Exception as e:
            print(Fore.RED + f"❌ Error baca cookies: {e}")

    input(Fore.WHITE + "\nTekan Enter untuk kembali...")


# ── MENU 4: HAPUS SESSION ─────────────────────────────────────────────────

def delete_session_interactive():
    print(Fore.CYAN + "\n⚠️  HAPUS SESSION FACEBOOK")

    if not has_valid_session():
        print(Fore.YELLOW + "   Session belum ada / sudah tidak ada")
        return

    info = get_session_info()
    user_id = info.get("user_id", "?")
    print(Fore.YELLOW + f"   Session aktif: User ID {user_id}")

    confirm = input(Fore.RED + "\n   Yakin hapus session? (ketik 'yes' untuk konfirmasi): ").strip().lower()
    if confirm != "yes":
        print(Fore.YELLOW + "   Dibatalkan")
        return

    if delete_session():
        print(Fore.GREEN + "✅ Session berhasil dihapus")
    else:
        print(Fore.RED + "❌ Gagal hapus session")


# ── MENU 5: EXPORT INFO ───────────────────────────────────────────────────

def export_session_info():
    """Export info session ke JSON untuk debugging."""
    info = get_session_info()
    if not info.get("valid"):
        print(Fore.RED + "❌ Tidak ada session valid untuk di-export")
        return

    os.makedirs(SESSION_DIR, exist_ok=True)
    output_file = os.path.join(SESSION_DIR, "fb_session_info.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(info, f, ensure_ascii=False, indent=2)

    print(Fore.GREEN + f"✅ Session info di-export ke: {output_file}")
    input(Fore.WHITE + "\nTekan Enter untuk kembali...")


# ── MENU 6: TEST SESSION ──────────────────────────────────────────────────

def test_session_browser():
    """Test session dengan membuka browser Playwright dan navigasi ke Facebook."""
    if not has_valid_session():
        print(Fore.RED + "❌ Session belum ada. Import dulu via menu [1] atau [2]")
        return

    print(Fore.CYAN + "\n🧪 TEST SESSION — Membuka browser Facebook...")
    print(Fore.YELLOW + "   Browser akan terbuka sebentar untuk verifikasi")

    result = {"success": False, "user_id": "", "error": ""}

    def _test():
        try:
            from playwright.sync_api import sync_playwright, Page
            from fb_cookie_injector import inject_cookies_sync

            profile_dir = os.path.join(os.getcwd(), "fb_chrome_real_profile")
            os.makedirs(profile_dir, exist_ok=True)

            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    profile_dir,
                    channel="chrome",
                    headless=False,
                    args=[
                        "--window-size=1280,800",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-notifications",
                    ],
                    viewport=None,
                    locale="id-ID",
                    timezone_id="Asia/Jakarta",
                )

                # Inject cookies
                n = inject_cookies_sync(context)
                print(Fore.GREEN + f"   🍪 {n} cookies diinject")

                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=30000)
                time.sleep(5)

                # Cek login
                cookies = context.cookies("https://www.facebook.com")
                # FIX: gunakan .get() untuk optional keys di Cookie TypedDict
                cookie_dict = {c.get("name", ""): c.get("value", "") for c in cookies}

                if "c_user" in cookie_dict and "xs" in cookie_dict:
                    result["success"] = True
                    result["user_id"] = cookie_dict.get("c_user", "")
                    print(Fore.GREEN + f"   ✅ Session valid — Facebook terbuka! User ID: {result['user_id']}")
                else:
                    result["error"] = "c_user / xs tidak ditemukan di browser cookies"
                    print(Fore.RED + f"   ❌ {result['error']}")

                time.sleep(4)
                context.close()

        except Exception as e:
            result["error"] = str(e)
            print(Fore.RED + f"   ❌ Error: {e}")

    thread = threading.Thread(target=_test, daemon=True)
    thread.start()
    thread.join(timeout=60)

    if result["success"]:
        print(Fore.GREEN + f"\n✅ TEST BERHASIL — Session Facebook valid! User ID: {result['user_id']}")
    else:
        print(Fore.RED + f"\n❌ TEST GAGAL: {result.get('error', 'Unknown error')}")
        print(Fore.YELLOW + "   Coba import ulang cookies (menu [1] atau [2])")


# ── MENU 7: LOGIN VIA BROWSER ─────────────────────────────────────────────

def open_login_browser():
    """Buka browser untuk login manual Facebook, lalu auto-save session."""
    print(Fore.CYAN + "\n🌐 BUKA BROWSER UNTUK LOGIN FACEBOOK")
    print(Fore.YELLOW + "   Browser Chrome akan terbuka")
    print(Fore.YELLOW + "   Login manual di browser, lalu session akan otomatis tersimpan")
    print(Fore.YELLOW + "   (Cookie-Editor lebih reliable — gunakan menu [1] jika ada masalah)")

    profile_dir = os.path.join(os.getcwd(), "fb_chrome_real_profile")
    os.makedirs(profile_dir, exist_ok=True)

    result = {"logged_in": False, "error": "", "user_id": ""}

    def _browser_worker():
        try:
            from playwright.sync_api import sync_playwright, Page

            stealth_script = """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
                try { delete navigator.__proto__.webdriver; } catch(e) {}
            """

            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    profile_dir,
                    channel="chrome",
                    headless=False,
                    args=[
                        "--window-size=1280,900",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-notifications",
                        "--start-maximized",
                    ],
                    viewport=None,
                    locale="id-ID",
                    timezone_id="Asia/Jakarta",
                    bypass_csp=True,
                )

                # FIX: wrap lambda agar return None, bukan SyncContextManager
                def _on_new_page(page: "Page") -> None:
                    page.add_init_script(stealth_script)

                context.on("page", _on_new_page)

                page = context.pages[0] if context.pages else context.new_page()
                page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)

                print(Fore.CYAN + "\n   Browser terbuka! Login manual di browser...")
                print(Fore.CYAN + "   Menunggu login (max 5 menit)...")

                max_wait  = 60
                logged_in = False

                for i in range(max_wait):
                    time.sleep(5)
                    cookies = context.cookies("https://www.facebook.com")
                    # FIX: gunakan .get() untuk optional keys di Cookie TypedDict
                    cookie_dict = {c.get("name", ""): c.get("value", "") for c in cookies}

                    if "c_user" in cookie_dict and "xs" in cookie_dict:
                        logged_in         = True
                        result["user_id"] = cookie_dict.get("c_user", "")
                        print(Fore.GREEN + f"\n   ✅ Login terdeteksi! User ID: {result['user_id']}")

                        # Simpan ke session file
                        fb_cookies = [
                            {
                                # FIX: gunakan .get() untuk optional keys
                                "name":           c.get("name", ""),
                                "value":          c.get("value", ""),
                                "domain":         c.get("domain", ".facebook.com"),
                                "path":           c.get("path", "/"),
                                "httpOnly":       c.get("httpOnly", False),
                                "secure":         c.get("secure", True),
                                "sameSite":       c.get("sameSite", "Lax"),
                                "expirationDate": c.get("expires", -1),
                            }
                            for c in cookies
                            if "facebook.com" in c.get("domain", "")
                        ]
                        save_session(fb_cookies, note="auto_saved_from_browser_login")
                        result["logged_in"] = True
                        print(Fore.GREEN + f"   💾 Session tersimpan: {SESSION_FILE}")
                        break

                    remaining = (max_wait - i - 1) * 5
                    if i % 6 == 0:
                        print(Fore.YELLOW + f"   ⏳ Menunggu login... {remaining}s tersisa", end="\r")

                if not logged_in:
                    print(Fore.RED + "\n   ❌ Timeout — login tidak terdeteksi dalam 5 menit")
                    result["error"] = "Timeout"

                time.sleep(5)
                context.close()

        except Exception as e:
            result["error"] = str(e)
            print(Fore.RED + f"\n   ❌ Error: {e}")

    thread = threading.Thread(target=_browser_worker, daemon=True)
    thread.start()
    thread.join(timeout=320)

    if result["logged_in"]:
        print(Fore.GREEN + f"\n✅ LOGIN BERHASIL — Session tersimpan! User ID: {result['user_id']}")
        print_session_status()
    else:
        print(Fore.RED + f"\n❌ Login gagal: {result.get('error', 'Unknown')}")
        print(Fore.YELLOW + "   Coba gunakan Cookie-Editor (menu [1]) sebagai alternatif")


# ── MAIN CLI ──────────────────────────────────────────────────────────────

def main():
    print_banner()

    if has_valid_session():
        info = get_session_info()
        print(Fore.GREEN + f"\n✅ Session aktif — User ID: {info.get('user_id', '?')}")
    else:
        print(Fore.YELLOW + "\n⚠️  Belum ada session — Import cookies dulu (menu [1] atau [2])")

    while True:
        print(Fore.CYAN + "\n" + "─" * 55)
        print(Fore.CYAN + "📋 MENU SESSION MANAGER FACEBOOK")
        print(Fore.CYAN + "─" * 55)
        print("  1. Import cookies (paste dari Cookie-Editor)")
        print("  2. Import cookies dari file JSON")
        print("  3. Cek status session detail")
        print("  4. Hapus session")
        print("  5. Export session info (debugging)")
        print("  6. Test session (buka browser & verifikasi)")
        print("  7. Login via browser (tanpa Cookie-Editor)")
        print("  8. Exit")
        print(Fore.CYAN + "─" * 55)

        choice = input(Fore.WHITE + "\nPilih [1-8]: ").strip()

        if choice == "1":
            import_cookies_from_clipboard()

        elif choice == "2":
            import_cookies_from_file()

        elif choice == "3":
            check_status()

        elif choice == "4":
            delete_session_interactive()

        elif choice == "5":
            export_session_info()

        elif choice == "6":
            test_session_browser()

        elif choice == "7":
            open_login_browser()

        elif choice == "8":
            print(Fore.CYAN + "\n👋 Bye!")
            break

        else:
            print(Fore.RED + "❌ Pilihan tidak valid [1-8]")


if __name__ == "__main__":
    main()