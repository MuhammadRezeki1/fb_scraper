"""
fb_debug_search.py — Debug Tool Komprehensif untuk Facebook Search
==================================================================
Analisa struktur HTML untuk posts, videos, groups, pages
"""
import os
import re
import json
import time
from datetime import datetime
from colorama import Fore, init
from playwright.sync_api import sync_playwright

init(autoreset=True)

PROFILE_DIR = os.path.join(os.getcwd(), "fb_chrome_real_profile")
DEBUG_DIR = os.path.join(os.getcwd(), "fb_keyword_debug")
os.makedirs(DEBUG_DIR, exist_ok=True)


def analyze_html(html: str, search_type: str, keyword: str) -> dict:
    """Analisa HTML mentah untuk extract pola data."""
    analysis = {
        "search_type": search_type,
        "keyword": keyword,
        "html_length": len(html),
        "articles_count": 0,
        "patterns_found": {},
        "sample_links": [],
    }
    
    # 1. Count [role="article"]
    analysis["articles_count"] = len(re.findall(r'role=["\']article["\']', html))
    
    # 2. Cari berbagai pattern URL
    patterns = {
        "wwwURL": r'"wwwURL":"(https?:\\\/\\\/[^"]+)"',
        "permalink": r'"permalink":"(https?:\\\/\\\/[^"]+)"',
        "url_fb": r'"url":"(https?:\\\/\\\/www\.facebook\.com[^"]+)"',
        "actors_name": r'"actors":\[\{[^}]*?"name":"([^"]+)"',
        "message_text": r'"message":\{"text":"((?:[^"\\]|\\.)*)"',
        "group_link": r'\/groups\/[a-zA-Z0-9._-]+',
        "page_link": r'\/pages\/[a-zA-Z0-9._-]+',
        "profile_php": r'profile\.php\?id=\d+',
        "watch_link": r'\/watch\/?\?v=[^"&\s]+',
        "reel_link": r'\/reel\/\d+',
        "video_link": r'\/videos\/\d+',
        "share_link": r'\/share\/[pr]\/[A-Za-z0-9_-]+',
    }
    
    for name, pattern in patterns.items():
        matches = re.findall(pattern, html)
        analysis["patterns_found"][name] = len(matches)
        if matches and len(analysis["sample_links"]) < 10:
            for m in matches[:2]:
                sample = m if isinstance(m, str) else str(m)
                if len(sample) < 200:
                    analysis["sample_links"].append({
                        "pattern": name,
                        "value": sample[:150]
                    })
    
    # 3. Cari semua link di HTML
    all_links = re.findall(r'href=["\']([^"\']+)["\']', html)
    fb_links = [l for l in all_links if 'facebook.com' in l or l.startswith('/')]
    analysis["total_links"] = len(all_links)
    analysis["fb_links"] = len(fb_links)
    
    return analysis


def main():
    print(Fore.CYAN + "=" * 70)
    print(Fore.CYAN + "  FACEBOOK SEARCH DEBUG TOOL")
    print(Fore.CYAN + "=" * 70)
    
    keyword = input("\n🔍 Keyword untuk test (default: jokowi): ").strip()
    if not keyword:
        keyword = "jokowi"
    
    search_types = ["posts", "videos", "groups", "pages"]
    
    with sync_playwright() as pw:
        print(Fore.YELLOW + "\n🌐 Membuka browser...")
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
        
        all_analyses = {}
        
        for search_type in search_types:
            print(Fore.CYAN + "\n" + "=" * 70)
            print(Fore.CYAN + f"TESTING: {search_type.upper()} SEARCH")
            print(Fore.CYAN + "=" * 70)
            
            url = f"https://www.facebook.com/search/{search_type}/?q={keyword}"
            print(Fore.YELLOW + f"🌐 URL: {url}")
            
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                
                # Close popups
                page.evaluate(r"""() => {
                    document.querySelectorAll('[aria-label="Tutup"], [aria-label="Close"]').forEach(btn => {
                        if (btn.offsetParent !== null) btn.click();
                    });
                }""")
                
                print(Fore.YELLOW + "⏳ Tunggu 10 detik untuk load...")
                time.sleep(10)
                
                # Scroll untuk trigger lazy load
                print(Fore.YELLOW + "📜 Scroll untuk trigger lazy load...")
                for i in range(3):
                    page.evaluate(f"window.scrollBy(0, {1000 + i * 500})")
                    time.sleep(2)
                page.evaluate("window.scrollTo(0, 0)")
                time.sleep(2)
                
                # Ambil HTML
                html = page.content()
                
                # Analisa
                analysis = analyze_html(html, search_type, keyword)
                all_analyses[search_type] = analysis
                
                # Simpan HTML mentah
                html_file = os.path.join(DEBUG_DIR, f"search_{search_type}_{keyword}_{datetime.now().strftime('%H%M%S')}.html")
                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(html)
                print(Fore.GREEN + f"💾 HTML saved: {html_file}")
                
                # Print hasil
                print(Fore.GREEN + f"\n📊 HASIL ANALISA {search_type.upper()}:")
                print(Fore.GREEN + f"   HTML size: {analysis['html_length']:,} bytes")
                print(Fore.GREEN + f"   [role='article']: {analysis['articles_count']}")
                print(Fore.GREEN + f"   Total links: {analysis['total_links']}")
                print(Fore.GREEN + f"   FB links: {analysis['fb_links']}")
                
                print(Fore.CYAN + "\n   🔍 Patterns ditemukan:")
                for pattern, count in analysis['patterns_found'].items():
                    color = Fore.GREEN if count > 0 else Fore.RED
                    print(color + f"      {pattern:25s}: {count}")
                
                if analysis['sample_links']:
                    print(Fore.CYAN + "\n   📝 Sample links:")
                    for sample in analysis['sample_links'][:5]:
                        print(Fore.YELLOW + f"      [{sample['pattern']}] {sample['value'][:100]}")
                
                # Cek DOM articles
                articles_info = page.evaluate(r"""() => {
                    const articles = document.querySelectorAll('[role="article"]');
                    const info = [];
                    for (let i = 0; i < Math.min(5, articles.length); i++) {
                        const art = articles[i];
                        const links = art.querySelectorAll('a[href]');
                        const sampleLinks = [];
                        for (let j = 0; j < Math.min(5, links.length); j++) {
                            sampleLinks.push(links[j].getAttribute('href') || '');
                        }
                        info.push({
                            text: (art.innerText || '').slice(0, 100).replace(/\n/g, ' | '),
                            links: sampleLinks,
                        });
                    }
                    return info;
                }""")
                
                if articles_info:
                    print(Fore.GREEN + f"\n   📄 Sample articles ({len(articles_info)} shown):")
                    for idx, art in enumerate(articles_info):
                        print(Fore.CYAN + f"      Article #{idx+1}:")
                        print(Fore.CYAN + f"         Text: {art['text'][:80]}...")
                        print(Fore.CYAN + f"         Links: {art['links'][:3]}")
                else:
                    print(Fore.RED + "\n   ❌ NO [role='article'] FOUND!")
                    
                    # Cek apa yang ada di halaman
                    body_text = page.evaluate("() => document.body.innerText.slice(0, 1000)")
                    print(Fore.YELLOW + f"\n   Body text preview:")
                    print(Fore.YELLOW + f"   {body_text[:500]}")
                
                time.sleep(2)
                
            except Exception as e:
                print(Fore.RED + f"❌ Error testing {search_type}: {e}")
                all_analyses[search_type] = {"error": str(e)}
        
        # Summary
        print(Fore.CYAN + "\n" + "=" * 70)
        print(Fore.CYAN + "SUMMARY")
        print(Fore.CYAN + "=" * 70)
        
        for st, analysis in all_analyses.items():
            if "error" in analysis:
                print(Fore.RED + f"   {st:10s}: ERROR - {analysis['error']}")
            else:
                articles = analysis.get('articles_count', 0)
                www_urls = analysis.get('patterns_found', {}).get('wwwURL', 0)
                permalinks = analysis.get('patterns_found', {}).get('permalink', 0)
                fb_links = analysis.get('fb_links', 0)
                
                status = "✅" if (articles > 0 or www_urls > 0 or permalinks > 0) else "❌"
                print(Fore.GREEN + f"   {st:10s}: {status} articles={articles}, wwwURL={www_urls}, permalink={permalinks}, fb_links={fb_links}")
        
        # Save summary
        summary_file = os.path.join(DEBUG_DIR, f"debug_summary_{keyword}_{datetime.now().strftime('%H%M%S')}.json")
        with open(summary_file, "w", encoding="utf-8") as f:
            json.dump(all_analyses, f, ensure_ascii=False, indent=2, default=str)
        print(Fore.GREEN + f"\n💾 Summary saved: {summary_file}")
        
        input(Fore.CYAN + "\n✋ Tekan ENTER untuk tutup browser...")
        ctx.close()


if __name__ == "__main__":
    main()