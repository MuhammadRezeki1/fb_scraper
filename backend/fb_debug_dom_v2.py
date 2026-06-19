"""
Better debug script to find where Facebook search results actually live in the DOM
"""
import os, json, time, sys
from playwright.sync_api import sync_playwright
from urllib.parse import quote

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
keyword = sys.argv[1] if len(sys.argv) > 1 else "bemui"

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            FB_CHROME_PROFILE, channel="chrome", headless=False, no_viewport=True
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            from fb_cookie_injector import inject_cookies_sync
            inject_cookies_sync(context)
            print("[OK] Cookies injected")
        except Exception as e:
            print(f"[WARN] {e}")

        url = f"https://www.facebook.com/search/posts/?q={quote(keyword)}"
        print(f"\n[NAV] {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(6)
        page.evaluate("window.scrollBy(0, 1500)")
        time.sleep(3)

        # 1. Find ALL main content areas on the page
        info = page.evaluate("""() => {
            const result = {};
            // Find all data-pagelet
            const pagelets = document.querySelectorAll('[data-pagelet]');
            result.pagelets = Array.from(pagelets).slice(0,20).map(p => ({
                name: p.getAttribute('data-pagelet'),
                role: p.getAttribute('role')||'',
                childCount: p.children.length,
                html1: p.outerHTML.substring(0, 200)
            }));
            
            // Find ALL elements with role = article, feed, main, region
            ['article','feed','main','region','complementary'].forEach(r => {
                const els = document.querySelectorAll('[role="'+r+'"]');
                result['role_'+r] = Array.from(els).slice(0,10).map(el => ({
                    childCount: el.children.length,
                    innerLen: (el.innerText||'').length,
                    html1: el.outerHTML.substring(0, 300)
                }));
            });
            
            // Find divs with meaningful text (potential post containers)
            const mainArea = document.querySelector('[role="main"]');
            if (mainArea) {
                const allDivs = mainArea.querySelectorAll('div');
                result.mainDivCount = allDivs.length;
                // Find divs with significant text content
                const textDivs = [];
                allDivs.forEach(d => {
                    const t = (d.innerText||'').trim();
                    if (t.length > 50 && t.length < 2000) {
                        textDivs.push({
                            tag: d.tagName,
                            text: t.slice(0, 200),
                            depth: (function getDepth(el, d=0){return el.parentElement?getDepth(el.parentElement,d+1):d})(d)
                        });
                    }
                });
                // Deduplicate
                const seen = new Set();
                result.textDivs = textDivs.filter(x => {
                    if (seen.has(x.text)) return false;
                    seen.add(x.text);
                    return true;
                }).slice(0, 30);
                
                // Find links in main area
                const links = mainArea.querySelectorAll('a[href*="/"]');
                result.mainLinks = Array.from(links).slice(0, 30).map(a => ({
                    href: (a.getAttribute('href')||'').split('?')[0],
                    text: (a.innerText||'').trim().slice(0, 80),
                    role: a.getAttribute('role')||''
                })).filter(x => !x.href.includes('/stories/')).slice(0, 20);
            }
            
            return result;
        }""")
        print(f"\n=== PAGE STRUCTURE ===\n{json.dumps(info, indent=2, ensure_ascii=False)[:15000]}")

        # 2. Take screenshot
        page.screenshot(path="debug_search_posts.png", full_page=True)
        print(f"\n[Screenshot saved] debug_search_posts.png")
        
        # 3. Dump page HTML for analysis
        html_len = len(page.content())
        print(f"\n[HTML size] {html_len} chars")
        
        context.close()
        print("\n[DONE]")

if __name__ == "__main__":
    main()