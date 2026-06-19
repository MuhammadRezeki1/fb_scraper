# ============================================================
# FB LOGIN HELPER — Playwright Persistent Context (Chrome ASLI)
# Jalankan SEKALI untuk login Facebook dan simpan session
# ============================================================

import os
import time
from colorama import Fore, init
from playwright.sync_api import sync_playwright

init(autoreset=True)

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
os.makedirs(FB_CHROME_PROFILE, exist_ok=True)


def main():
    print(Fore.CYAN + "=" * 60)
    print(Fore.CYAN + "  FACEBOOK LOGIN HELPER — Chrome ASLI + Playwright")
    print(Fore.CYAN + "=" * 60)
    print(Fore.YELLOW + f"\n📁 Profile dir: {FB_CHROME_PROFILE}")

    with sync_playwright() as pw:
        args = [
            "--window-size=1920,1080",
            "--window-position=0,0",
            "--disable-blink-features=AutomationControlled",
            "--disable-notifications",
            "--disable-infobars",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
        ]

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
            delete navigator.__proto__.webdriver;
            Object.defineProperty(navigator, 'languages', {get: () => ['id-ID', 'id', 'en-US', 'en']});
            Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
            Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
        """

        context = pw.chromium.launch_persistent_context(
            FB_CHROME_PROFILE,
            channel="chrome",  # ✅ Chrome ASLI
            headless=False,
            args=args,
            no_viewport=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            bypass_csp=True,
        )

        page = context.pages[0] if context.pages else context.new_page()
        page.add_init_script(stealth_script)

        print(Fore.YELLOW + "\n🌐 Membuka Facebook...")
        page.goto("https://www.facebook.com/")
        time.sleep(3)

        # Cek apakah sudah login
        current = page.url
        if "facebook.com" in current and "login" not in current:
            try:
                page.wait_for_selector(
                    "[aria-label='Facebook'], div[role='feed'], [data-pagelet='FeedUnit_0']",
                    timeout=5000
                )
                print(Fore.GREEN + "\n✅ Sudah login sebelumnya!")
                print(Fore.GREEN + "   Session tersimpan di fb_chrome_real_profile/")
                print(Fore.CYAN + "   Langsung jalankan: python fb_graphql_scraper.py")
                time.sleep(3)
                context.close()
                return
            except:
                pass

        print(Fore.YELLOW + "\n⚠️  Silakan LOGIN MANUAL di browser yang terbuka.")
        print(Fore.YELLOW + "    1. Masukkan email/no HP & password")
        print(Fore.YELLOW + "    2. Selesaikan 2FA / captcha jika diminta")
        print(Fore.YELLOW + "    3. Tunggu sampai halaman beranda Facebook muncul")
        print(Fore.YELLOW + "    4. Jangan tutup browser ini!\n")
        print(Fore.CYAN + "⏳ Menunggu login (max 5 menit)...")

        for i in range(60):
            time.sleep(5)
            url = page.url
            print(f"   [{i+1:02d}/60] {url[:80]}", end="\r")

            logged_in = (
                "facebook.com" in url
                and "login" not in url
                and "checkpoint" not in url
                and "recover" not in url
                and "two_step" not in url
            )

            if logged_in:
                try:
                    page.wait_for_selector(
                        "div[role='feed'], [data-pagelet='FeedUnit_0'], [aria-label='Facebook']",
                        timeout=5000
                    )
                    print(Fore.GREEN + f"\n\n✅ Login berhasil terdeteksi!")
                    break
                except:
                    pass
        else:
            print(Fore.RED + "\n\n❌ Timeout. Coba jalankan ulang script ini.")
            context.close()
            return

        print(Fore.YELLOW + "\n⏳ Menyimpan session (tunggu 8 detik)...")
        time.sleep(8)

        context.close()

    print(Fore.GREEN + f"\n✅ Session tersimpan di: {FB_CHROME_PROFILE}")
    print(Fore.CYAN + "👉 Sekarang jalankan: python fb_graphql_scraper.py")


if __name__ == "__main__":
    main()