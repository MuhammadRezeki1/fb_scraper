"""
Deep debug: actual post containers, links, text, likes, comments in Facebook search results
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

        # Deep analysis of each post container
        debug = page.evaluate("""() => {
            const result = {};
            const mainArea = document.querySelector('[role="main"]');
            if (!mainArea) return {error: 'no main'};
            
            // Find actual post containers - look for x1a2a7pz class (FB's post container)
            const postContainers = mainArea.querySelectorAll('[aria-posinset]');
            result.postCount = postContainers.length;
            
            result.posts = Array.from(postContainers).slice(0, 10).map((container, idx) => {
                const item = {idx, posinset: container.getAttribute('aria-posinset')};
                
                // ALL links in container
                const links = container.querySelectorAll('a[href]');
                item.links = Array.from(links).map(a => ({
                    href: (a.getAttribute('href')||'').split('?')[0],
                    fullHref: (a.getAttribute('href')||'').slice(0, 200),
                    text: (a.innerText||'').trim().slice(0, 80),
                    role: a.getAttribute('role')||'',
                    class: (a.getAttribute('class')||'').slice(0, 40)
                }));
                
                // Find story_fbid links specifically
                item.storyFbidLinks = Array.from(links)
                    .filter(a => (a.getAttribute('href')||'').includes('story_fbid'))
                    .map(a => ({href: a.getAttribute('href')||'', text: (a.innerText||'').trim().slice(0,80)}));
                
                // Find author name
                const strongs = container.querySelectorAll('strong[dir="auto"], a[role="link"]');
                item.authorEls = Array.from(strongs).slice(0,3).map(s => ({
                    text: (s.innerText||'').trim().slice(0, 100),
                    tag: s.tagName,
                    href: s.getAttribute('href')||''
                }));
                
                // Find ALL text spans/divs with content
                const textEls = container.querySelectorAll('span[dir="auto"], div[dir="auto"]');
                item.texts = [];
                textEls.forEach(el => {
                    const t = (el.innerText||'').trim();
                    if (t.length >= 10 && t.length < 3000) {
                        item.texts.push({
                            text: t.slice(0, 200),
                            tag: el.tagName,
                            parentClass: (el.parentElement?.getAttribute('class')||'').slice(0,30)
                        });
                    }
                });
                
                // Like buttons
                const likeEls = container.querySelectorAll('[aria-label*="Suka" i], [aria-label*="Like" i], [aria-label*="suka" i]');
                item.likeButtons = Array.from(likeEls).slice(0,3).map(el => ({
                    aria: el.getAttribute('aria-label')||'',
                    text: (el.innerText||'').trim().slice(0,30),
                    role: el.getAttribute('role')||'',
                    tag: el.tagName,
                    parentRole: el.parentElement?.getAttribute('role')||''
                }));
                
                // Comment buttons
                const commentEls = container.querySelectorAll('[aria-label*="Komentar" i], [aria-label*="Comment" i]');
                item.commentButtons = Array.from(commentEls).slice(0,3).map(el => ({
                    aria: el.getAttribute('aria-label')||'',
                    text: (el.innerText||'').trim().slice(0,30),
                    role: el.getAttribute('role')||'',
                    tag: el.tagName
                }));
                
                // Share buttons
                const shareEls = container.querySelectorAll('[aria-label*="Bagikan" i], [aria-label*="Share" i]');
                item.shareButtons = Array.from(shareEls).slice(0,2).map(el => ({
                    aria: el.getAttribute('aria-label')||'',
                    text: (el.innerText||'').trim().slice(0,30)
                }));
                
                // Full text dump
                item.fullText = (container.innerText||'').replace(/\\n/g, ' | ').slice(0, 1000);
                
                // Container HTML structure (first 3000 chars)
                item.containerHTML = container.outerHTML.substring(0, 3000);
                
                return item;
            });
            
            return result;
        }""")
        
        print(f"\n=== DEEP POST ANALYSIS ===\n{json.dumps(debug, indent=2, ensure_ascii=False)[:20000]}")
        
        # Also check video-specific DOM
        print("\n\n=== VIDEO SECTION ===")
        page.goto(f"https://www.facebook.com/search/videos/?q={quote(keyword)}", 
                   wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        page.evaluate("window.scrollBy(0, 1000)")
        time.sleep(3)
        
        videoDebug = page.evaluate("""() => {
            const result = {};
            const mainArea = document.querySelector('[role="main"]');
            if (!mainArea) return {error: 'no main'};
            
            // Find all links that look like video content
            const allLinks = mainArea.querySelectorAll('a[href*="/watch"], a[href*="/reel"], a[href*="/reels"], a[href*="/videos/"]');
            result.videoLinks = Array.from(allLinks).slice(0, 10).map(a => ({
                href: (a.getAttribute('href')||'').split('?')[0],
                fullHref: (a.getAttribute('href')||'').slice(0, 200),
                text: (a.innerText||'').trim().slice(0, 100)
            }));
            
            // Find cards with thumbnails
            const cards = mainArea.querySelectorAll('[role="article"], [data-pagelet]');
            result.cards = Array.from(cards).slice(0, 5).map(c => ({
                role: c.getAttribute('role')||'',
                pagelet: c.getAttribute('data-pagelet')||'',
                text: (c.innerText||'').trim().replace(/\\n/g, ' | ').slice(0, 500),
                links: Array.from(c.querySelectorAll('a[href*="/"]')).slice(0,5).map(a => ({
                    href: (a.getAttribute('href')||'').split('?')[0],
                    text: (a.innerText||'').trim().slice(0, 50)
                }))
            }));
            
            // Look for text containers
            const textBlocks = mainArea.querySelectorAll('span[dir="auto"], div[dir="auto"]');
            const seen = new Set();
            result.textBlocks = Array.from(textBlocks)
                .filter(el => {
                    const t = (el.innerText||'').trim();
                    if (t.length < 15 || t.length > 5000) return false;
                    if (seen.has(t)) return false;
                    seen.add(t);
                    return true;
                })
                .slice(0, 15)
                .map(el => ({
                    text: (el.innerText||'').trim().slice(0, 200),
                    tag: el.tagName,
                    parentClass: (el.parentElement?.getAttribute('class')||'').slice(0,30)
                }));
            
            return result;
        }""")
        
        print(f"\n=== VIDEO ANALYSIS ===\n{json.dumps(videoDebug, indent=2, ensure_ascii=False)[:12000]}")
        
        # Screenshot
        page.screenshot(path="debug_v2_search_posts.png", full_page=True)
        print("\n[Screenshot saved]")
        
        context.close()
        print("\n[DONE]")

if __name__ == "__main__":
    main()