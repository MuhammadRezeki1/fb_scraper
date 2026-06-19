"""
fb_cookie_injector.py
=====================
Jembatan antara login-via-cookie (Cookie-Editor JSON) dengan engine
Facebook scraper yang memakai Playwright persistent context.

Cara kerja:
  - Cookies disimpan di session/fb_session.json (oleh fb_session_manager / CLI).
  - Saat engine membuat context, panggil inject_cookies_sync(context) untuk
    memasukkan cookies sebelum navigasi pertama.

Integrasi ke engine Facebook HANYA butuh 1 baris setelah launch_persistent_context:

    from fb_cookie_injector import inject_cookies_sync
    ...
    context = self.playwright.chromium.launch_persistent_context(...)
    inject_cookies_sync(context)        # ← tambahkan baris ini

Cookies wajib Facebook:
  - c_user      : user ID (sesi login utama)
  - xs          : session token
  - datr        : browser identifier
"""
import os
import json
from typing import List, Dict, Optional

# ── Lokasi file session ────────────────────────────────────────────────────
_HERE        = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR  = os.path.join(_HERE, "session")
SESSION_FILE = os.path.join(SESSION_DIR, "fb_session.json")

# Cookie minimal yang wajib ada agar dianggap valid session
REQUIRED_COOKIES  = {"c_user", "xs"}
# Cookie tambahan yang sebaiknya ada
PREFERRED_COOKIES = {"datr", "fr", "sb", "wd"}

_SAMESITE_MAP = {
    "no_restriction": "None",
    "unspecified":    "Lax",
    "lax":            "Lax",
    "strict":         "Strict",
    "none":           "None",
}

FACEBOOK_DOMAINS = [".facebook.com", "www.facebook.com", "facebook.com"]


# ── LOAD ──────────────────────────────────────────────────────────────────

def load_raw_cookies() -> List[Dict]:
    """Muat cookies mentah (Cookie-Editor format) dari session file."""
    if not os.path.exists(SESSION_FILE):
        raise FileNotFoundError(
            f"Session Facebook belum ada di {SESSION_FILE}. "
            "Login dulu lewat: python fb_session_manager.py"
        )
    with open(SESSION_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)

    cookies = data.get("cookies", [])
    if not cookies:
        raise ValueError("Session file Facebook tidak berisi cookies.")
    return cookies


def has_valid_session() -> bool:
    """Cek cepat apakah session file ada & punya cookie wajib Facebook."""
    try:
        cookies = load_raw_cookies()
    except Exception:
        return False
    names = {c.get("name") for c in cookies}
    return bool(REQUIRED_COOKIES.issubset(names))


def get_session_info() -> Dict:
    """
    Ambil info session: user_id (dari c_user), expired?, preferred cookies ada?
    Returns dict dengan info atau error jika session tidak ada.
    """
    try:
        cookies = load_raw_cookies()
    except Exception as e:
        return {"valid": False, "error": str(e)}

    names         = {c.get("name") for c in cookies}
    has_required  = REQUIRED_COOKIES.issubset(names)
    has_preferred = PREFERRED_COOKIES.issubset(names)

    # Ambil user ID dari c_user
    user_id = next(
        (c.get("value", "") for c in cookies if c.get("name") == "c_user"),
        ""
    )

    # Cek expiry dari xs cookie (paling penting)
    xs_expiry = None
    for c in cookies:
        if c.get("name") == "xs":
            exp = c.get("expirationDate")
            if exp:
                xs_expiry = exp
            break

    return {
        "valid":             has_required,
        "has_required":      has_required,
        "has_preferred":     has_preferred,
        "total_cookies":     len(cookies),
        "cookie_names": sorted(n for n in names if n is not None),
        "user_id":           user_id,
        "xs_expiry":         xs_expiry,
        "preferred_missing": sorted(list(PREFERRED_COOKIES - names)),
        "session_file":      SESSION_FILE,
    }


# ── KONVERSI FORMAT ───────────────────────────────────────────────────────

def to_playwright_cookies(cookies: List[Dict]) -> List[Dict]:
    """Cookie-Editor format → format add_cookies() Playwright."""
    out = []
    for c in cookies:
        name  = c.get("name")
        value = c.get("value")
        if not name or value is None:
            continue

        # Normalisasi domain untuk Facebook
        domain = c.get("domain", ".facebook.com")
        if domain and not domain.startswith(".") and "facebook.com" in domain:
            domain = "." + domain.lstrip(".")

        pw = {
            "name":     name,
            "value":    value,
            "domain":   domain,
            "path":     c.get("path", "/"),
            "httpOnly": bool(c.get("httpOnly", False)),
            "secure":   bool(c.get("secure", True)),
            "sameSite": _SAMESITE_MAP.get(
                str(c.get("sameSite", "unspecified")).lower(), "Lax"
            ),
        }
        exp = c.get("expirationDate")
        pw["expires"] = float(exp) if exp is not None else -1
        out.append(pw)
    return out


# ── INJECT (SYNC — untuk scraper Facebook) ───────────────────────────────

def inject_cookies_sync(context) -> int:
    """
    Inject cookies ke sync Playwright BrowserContext untuk Facebook.
    Mengembalikan jumlah cookie yang diinject.
    Panggil SETELAH launch_persistent_context, SEBELUM page.goto pertama.
    """
    cookies    = load_raw_cookies()
    pw_cookies = to_playwright_cookies(cookies)
    context.add_cookies(pw_cookies)
    return len(pw_cookies)


# ── INJECT (ASYNC — untuk engine async) ──────────────────────────────────

async def inject_cookies_async(context) -> int:
    """Versi async dari inject_cookies_sync untuk Facebook."""
    cookies    = load_raw_cookies()
    pw_cookies = to_playwright_cookies(cookies)
    await context.add_cookies(pw_cookies)
    return len(pw_cookies)


# ── SAVE SESSION ──────────────────────────────────────────────────────────

def save_session(cookies: List[Dict], username: str = "", note: str = "") -> str:
    """
    Simpan cookies ke session file.
    cookies: List of cookie dicts (Cookie-Editor format)
    Returns: path file yang disimpan
    """
    os.makedirs(SESSION_DIR, exist_ok=True)

    data = {
        "platform":  "facebook",
        "username":  username,
        "note":      note,
        "saved_at":  __import__("datetime").datetime.now().isoformat(),
        "cookies":   cookies,
    }

    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return SESSION_FILE


def delete_session() -> bool:
    """Hapus session file Facebook."""
    if os.path.exists(SESSION_FILE):
        os.remove(SESSION_FILE)
        return True
    return False


# ── SESSION MANAGER CLI ───────────────────────────────────────────────────

def print_banner():
    from colorama import Fore, init
    init(autoreset=True)
    print(Fore.CYAN + """
╔══════════════════════════════════════════════════════════════╗
║             FACEBOOK SESSION MANAGER                        ║
║  Import cookies dari Cookie-Editor → fb_session.json        ║
╚══════════════════════════════════════════════════════════════╝""")


def main():
    """CLI sederhana untuk manage session Facebook."""
    from colorama import Fore, init
    init(autoreset=True)

    print_banner()

    while True:
        print(Fore.CYAN + "\n📋 MENU SESSION MANAGER")
        print("  1. Import cookies dari file JSON (Cookie-Editor)")
        print("  2. Import cookies dari clipboard / paste manual")
        print("  3. Cek status session")
        print("  4. Hapus session")
        print("  5. Tampilkan info detail session")
        print("  6. Exit")

        choice = input(Fore.WHITE + "\nPilih [1-6]: ").strip()

        if choice == "1":
            filepath = input("Path file JSON cookies: ").strip().strip('"')
            if not os.path.exists(filepath):
                print(Fore.RED + f"❌ File tidak ditemukan: {filepath}")
                continue
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                # Support format array langsung atau {cookies: [...]}
                if isinstance(raw, list):
                    cookies = raw
                elif isinstance(raw, dict) and "cookies" in raw:
                    cookies = raw["cookies"]
                else:
                    print(Fore.RED + "❌ Format JSON tidak dikenali")
                    continue

                username = input("Username Facebook (opsional): ").strip()
                save_session(cookies, username=username, note="imported_from_file")
                print(Fore.GREEN + f"✅ {len(cookies)} cookies tersimpan ke {SESSION_FILE}")

                # Validasi
                if has_valid_session():
                    info = get_session_info()
                    print(Fore.GREEN + f"✅ Session valid! User ID: {info.get('user_id', 'N/A')}")
                else:
                    print(Fore.YELLOW + "⚠️  Cookies disimpan tapi session belum valid (c_user atau xs tidak ada)")
            except Exception as e:
                print(Fore.RED + f"❌ Error: {e}")

        elif choice == "2":
            print(Fore.YELLOW + "\nPaste JSON cookies (Cookie-Editor format), tekan Enter 2x setelah selesai:")
            lines = []
            while True:
                line = input()
                if line == "" and lines and lines[-1] == "":
                    break
                lines.append(line)
            raw_text = "\n".join(lines).strip()
            if not raw_text:
                print(Fore.RED + "❌ Tidak ada input")
                continue
            try:
                raw = json.loads(raw_text)
                if isinstance(raw, list):
                    cookies = raw
                elif isinstance(raw, dict) and "cookies" in raw:
                    cookies = raw["cookies"]
                else:
                    print(Fore.RED + "❌ Format JSON tidak dikenali")
                    continue

                username = input("Username Facebook (opsional): ").strip()
                save_session(cookies, username=username, note="imported_from_paste")
                print(Fore.GREEN + f"✅ {len(cookies)} cookies tersimpan ke {SESSION_FILE}")

                if has_valid_session():
                    info = get_session_info()
                    print(Fore.GREEN + f"✅ Session valid! User ID: {info.get('user_id', 'N/A')}")
                else:
                    print(Fore.YELLOW + "⚠️  Cookies tersimpan tapi session belum valid")
            except json.JSONDecodeError as e:
                print(Fore.RED + f"❌ JSON parse error: {e}")

        elif choice == "3":
            if has_valid_session():
                info = get_session_info()
                print(Fore.GREEN + f"✅ Session VALID")
                print(Fore.CYAN + f"   User ID    : {info.get('user_id', 'N/A')}")
                print(Fore.CYAN + f"   Total cookies: {info.get('total_cookies', 0)}")
            else:
                print(Fore.RED + "❌ Session TIDAK VALID atau belum ada")

        elif choice == "4":
            confirm = input(Fore.YELLOW + "Hapus session? (y/n): ").strip().lower()
            if confirm == "y":
                if delete_session():
                    print(Fore.GREEN + "✅ Session dihapus")
                else:
                    print(Fore.YELLOW + "⚠️  Session file tidak ditemukan")

        elif choice == "5":
            info = get_session_info()
            if info.get("valid"):
                print(Fore.GREEN + "\n✅ SESSION INFO:")
                print(Fore.CYAN + f"   Valid          : {info['valid']}")
                print(Fore.CYAN + f"   User ID        : {info.get('user_id', 'N/A')}")
                print(Fore.CYAN + f"   Total cookies  : {info['total_cookies']}")
                print(Fore.CYAN + f"   Cookie names   : {', '.join(info['cookie_names'])}")
                print(Fore.CYAN + f"   Preferred ok   : {info['has_preferred']}")
                if info.get("preferred_missing"):
                    print(Fore.YELLOW + f"   Missing        : {', '.join(info['preferred_missing'])}")
                print(Fore.CYAN + f"   Session file   : {info['session_file']}")
            else:
                print(Fore.RED + f"❌ Session tidak valid: {info.get('error', 'Unknown error')}")

        elif choice == "6":
            print(Fore.CYAN + "\n👋 Bye!")
            break
        else:
            print(Fore.RED + "❌ Pilihan tidak valid")


if __name__ == "__main__":
    main()