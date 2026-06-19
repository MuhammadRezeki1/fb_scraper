"""
Deep debug v4: focus on finding where the actual post link is stored in FB's DOM
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
        page.evaluate("window.scrollBy(0, 1200)")
        time.sleep(3)

        # Focus on: where's the actual story/post ID?
        debug = page.evaluate("""() => {
            const result = {};
            const mainArea = document.querySelector('[role="main"]');
            if (!mainArea) return {error: 'no main'};
            
            // Find post containers
            const postContainers = mainArea.querySelectorAll('[aria-posinset]');
            result.postCount = postContainers.length;
            
            result.posts = Array.from(postContainers).slice(0, 8).map((container, idx) => {
                const item = {idx, posinset: container.getAttribute('aria-posinset')};
                
                // Get ALL attributes on ALL elements recursively that might contain story/post IDs
                const allEls = container.querySelectorAll('*');
                const fbidAttrs = [];
                const storyAttrs = [];
                const idAttrs = [];
                
                allEls.forEach(el => {
                    Array.from(el.attributes).forEach(attr => {
                        const val = attr.value;
                        if (val.includes('story_fbid') || val.includes('fbid=') || val.includes('fbid:')) {
                            fbidAttrs.push({attr: attr.name, val: val.slice(0, 200), tag: el.tagName});
                        }
                        if (val.includes('story') && val.match(/\\d{10,}/)) {
                            storyAttrs.push({attr: attr.name, val: val.slice(0, 150), tag: el.tagName});
                        }
                        if ((attr.name === 'id' || attr.name === 'data-testid') && val) {
                            idAttrs.push({attr: attr.name, val: val.slice(0, 100), tag: el.tagName});
                        }
                    });
                });
                
                item.fbidAttrs = fbidAttrs.slice(0, 5);
                item.storyAttrs = storyAttrs.slice(0, 5);
                item.idAttrs = idAttrs.slice(0, 10);
                
                // Find ALL href values with profile.php or numbers
                const allLinks = container.querySelectorAll('a[href]');
                const fullHrefs = Array.from(allLinks).map(a => a.getAttribute('href')||'');
                
                // Look for any href containing '?' with profile.php (has story context)
                const interesting = fullHrefs
                    .filter(h => h.includes('profile.php') || h.match(/\\/photos\\//) || h.match(/\\/watch/) || h.match(/\\/videos\\//))
                    .slice(0, 5);
                item.interestingHrefs = interesting.map(h => h.slice(0, 250));
                
                // Also check data-hover and other data attrs
                const dataAttrs = [];
                allEls.forEach(el => {
                    const href = el.getAttribute('data-hover') || el.getAttribute('data-store') || '';
                    if (href && (href.includes('fbid') || href.includes('story'))) {
                        dataAttrs.push({tag: el.tagName, val: href.slice(0, 200)});
                    }
                });
                item.dataAttrs = dataAttrs.slice(0, 5);
                
                // Get the first link that's NOT a story
                const nonStoryLink = Array.from(allLinks).find(a => {
                    const h = a.getAttribute('href')||'';
                    return h.includes('profile.php') && h.length > 30;
                });
                if (nonStoryLink) {
                    const h = nonStoryLink.getAttribute('href')||'';
                    // Parse the URL to find story_fbid or post id
                    const urlObj = new URL(h.includes('http') ? h : 'https://www.facebook.com'+h);
                    item.parsedLink = {
                        href: h.slice(0, 300),
                        pathname: urlObj.pathname,
                        searchParams: Object.fromEntries(urlObj.searchParams.entries())
                    };
                }
                
                return item;
            });
            
            return result;
        }""")
        
        print(f"\n=== DEEP URL ANALYSIS ===\n{json.dumps(debug, indent=2, ensure_ascii=False)[:10000]}")
        
        # Also dump page HTML for finding pattern
        html = page.content()
        # Find story_fbid patterns in HTML
        matches = []
        for m in __import__('re').finditer(r'story_fbid[=:][\"\']?(\d+)', html):
            ctx = html[max(0,m.start()-200):m.end()+200]
            matches.append(ctx[:300])
        print(f"\n=== story_fbid patterns in HTML (first 5) ===")
        for i, m in enumerate(matches[:5]):
            print(f"\n[{i}]: {m}")
        
        context.close()

if __name__ == "__main__":
    main()