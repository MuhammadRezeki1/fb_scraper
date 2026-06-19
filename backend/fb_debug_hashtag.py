"""
fb_debug_hashtag.py — Debug struktur DOM untuk Facebook Hashtag Search
=========================================================================
Jalankan tool ini untuk melihat struktur HTML saat search hashtag
"""
import os
import time
import json
from colorama import Fore, init
from playwright.sync_api import sync_playwright

init(autoreset=True)

PROFILE_DIR = os.path.join(os.getcwd(), "fb_chrome_real_profile")


def main():
    print(Fore.CYAN + "=" * 70)
    print(Fore.CYAN + "  FACEBOOK HASHTAG DEBUG TOOL")
    print(Fore.CYAN + "=" * 70)
    
    hashtag = input("\n🏷️  Hashtag (tanpa #): ").strip()
    if not hashtag:
        print(Fore.RED + "❌ Hashtag kosong")
        return
    
    # URL yang akan di-test
    hashtag_url = f"https://www.facebook.com/search/posts/?q=%23{hashtag}"
    keyword_url = f"https://www.facebook.com/search/posts/?q={hashtag}"
    
    print(Fore.CYAN + f"\n🔍 Testing 2 URL:")
    print(Fore.CYAN + f"   1. Hashtag: {hashtag_url}")
    print(Fore.CYAN + f"   2. Keyword: {keyword_url}")
    
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=False,
            args=["--start-maximized", "--disable-notifications", "--no-sandbox"],
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            bypass_csp=True,
        )
        
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        
        # Test 1: Hashtag search
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + f"TEST 1: HASHTAG SEARCH (#%{hashtag})")
        print(Fore.CYAN + "=" * 70)
        
        page.goto(hashtag_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        
        # Close popups
        for sel in ["[aria-label='Tutup']", "[aria-label='Close']"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=2000)
                    time.sleep(0.5)
            except:
                pass
        
        print(Fore.YELLOW + "\n⏳ Tunggu 5 detik untuk load...")
        time.sleep(5)
        
        # ✅ FIX: Gunakan raw string r"""...""" agar regex JS tidak bentrok dengan Python
        dom_info = page.evaluate(r"""() => {
            const info = {
                url: window.location.href,
                articles: 0,
                buttons: 0,
                posts: [],
                scrollablePanels: [],
            };
            
            info.articles = document.querySelectorAll('[role="article"]').length;
            info.buttons = document.querySelectorAll('[role="button"]').length;
            
            document.querySelectorAll('*').forEach(el => {
                const s = window.getComputedStyle(el);
                if (
                    (s.overflowY === 'auto' || s.overflowY === 'scroll') &&
                    el.scrollHeight > el.clientHeight + 50 &&
                    el.clientHeight > 100
                ) {
                    info.scrollablePanels.push({
                        tag: el.tagName,
                        role: el.getAttribute('role') || '',
                        className: el.className.toString().slice(0, 100),
                        scrollHeight: el.scrollHeight,
                        clientHeight: el.clientHeight,
                        hasArticles: el.querySelectorAll('[role="article"]').length > 0,
                    });
                }
            });
            
            const articles = document.querySelectorAll('[role="article"]');
            for (let i = 0; i < Math.min(5, articles.length); i++) {
                const art = articles[i];
                const links = art.querySelectorAll('a[href]');
                const ariaLabels = [];
                
                art.querySelectorAll('[aria-label]').forEach(el => {
                    const label = el.getAttribute('aria-label');
                    if (label && label.length < 100) ariaLabels.push(label);
                });
                
                info.posts.push({
                    index: i,
                    textPreview: (art.innerText || '').slice(0, 150).replace(/\n/g, ' | '),
                    linkCount: links.length,
                    ariaLabels: ariaLabels.slice(0, 5),
                    childCount: art.children.length,
                });
            }
            
            return info;
        }""")
        
        print(Fore.GREEN + f"\n📊 DOM Info:")
        print(Fore.GREEN + f"   URL: {dom_info['url'][:80]}")
        print(Fore.GREEN + f"   Articles: {dom_info['articles']}")
        print(Fore.GREEN + f"   Buttons: {dom_info['buttons']}")
        print(Fore.GREEN + f"   Scrollable panels: {len(dom_info['scrollablePanels'])}")
        
        if dom_info['posts']:
            print(Fore.GREEN + f"\n📝 Found {len(dom_info['posts'])} articles:")
            for post in dom_info['posts']:
                print(Fore.GREEN + f"   [{post['index']}] links={post['linkCount']} children={post['childCount']}")
                print(Fore.GREEN + f"       Text: {post['textPreview'][:100]}...")
                if post['ariaLabels']:
                    print(Fore.GREEN + f"       Aria: {post['ariaLabels'][:3]}")
        else:
            print(Fore.RED + "\n❌ NO ARTICLES FOUND!")
            print(Fore.YELLOW + "\n💡 Checking body content...")
            
            body_text = page.evaluate("() => document.body.innerText")
            print(Fore.YELLOW + f"   Body text length: {len(body_text)}")
            print(Fore.YELLOW + f"   First 500 chars: {body_text[:500]}")
        
        # Save full HTML
        html_file = f"debug_hashtag_{hashtag}.html"
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(page.content())
        print(Fore.GREEN + f"\n💾 Full HTML saved to: {html_file}")
        
        # Test 2: Keyword search (comparison)
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + f"TEST 2: KEYWORD SEARCH ({hashtag})")
        print(Fore.CYAN + "=" * 70)
        
        page.goto(keyword_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        
        for sel in ["[aria-label='Tutup']", "[aria-label='Close']"]:
            try:
                if page.locator(sel).count() > 0:
                    page.locator(sel).first.click(timeout=2000)
                    time.sleep(0.5)
            except:
                pass
        
        time.sleep(3)
        
        dom_info2 = page.evaluate(r"""() => {
            return {
                url: window.location.href,
                articles: document.querySelectorAll('[role="article"]').length,
                buttons: document.querySelectorAll('[role="button"]').length,
            };
        }""")
        
        print(Fore.GREEN + f"\n📊 DOM Info:")
        print(Fore.GREEN + f"   URL: {dom_info2['url'][:80]}")
        print(Fore.GREEN + f"   Articles: {dom_info2['articles']}")
        print(Fore.GREEN + f"   Buttons: {dom_info2['buttons']}")
        
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + "COMPARISON:")
        print(Fore.CYAN + "=" * 70)
        print(Fore.GREEN + f"   Hashtag search: {dom_info['articles']} articles")
        print(Fore.GREEN + f"   Keyword search: {dom_info2['articles']} articles")
        
        if dom_info['articles'] == 0 and dom_info2['articles'] > 0:
            print(Fore.RED + "\n⚠️  HASHTAG SEARCH TIDAK MENEMUKAN ARTICLES!")
            print(Fore.YELLOW + "\n💡 Kemungkinan penyebab:")
            print(Fore.YELLOW + "   1. Facebook tidak menampilkan hasil untuk search dengan #")
            print(Fore.YELLOW + "   2. Perlu scroll lebih banyak untuk load konten")
            print(Fore.YELLOW + "   3. Struktur DOM berbeda untuk hashtag search")
            print(Fore.YELLOW + "\n💡 Solusi yang disarankan:")
            print(Fore.YELLOW + "   - Gunakan keyword search tanpa # (lebih reliable)")
            print(Fore.YELLOW + "   - Atau implementasi scroll otomatis yang lebih agresif")
        
        input(Fore.CYAN + "\n✋ Tekan ENTER untuk tutup browser...")
        ctx.close()


if __name__ == "__main__":
    main()