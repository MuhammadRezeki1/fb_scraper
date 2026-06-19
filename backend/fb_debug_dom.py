"""
Debug script to inspect Facebook's actual DOM structure for search results.
Run: python fb_debug_dom.py
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

        # Inject cookies
        try:
            from fb_cookie_injector import inject_cookies_sync
            inject_cookies_sync(context)
            print("[OK] Cookies injected")
        except Exception as e:
            print(f"[WARN] Inject failed: {e}")

        # Test 1: Search posts page
        url = f"https://www.facebook.com/search/posts/?q={quote(keyword)}"
        print(f"\n=== TEST 1: Search Posts ===\n[NAV] {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        page.evaluate("window.scrollBy(0, 1200)")
        time.sleep(3)

        # Dump all roles and data-testids
        info = page.evaluate("""() => {
            const roles = {}, testids = {}, tags = {};
            document.querySelectorAll('*').forEach(el => {
                const r = el.getAttribute('role');
                if (r) roles[r] = (roles[r]||0) + 1;
                const d = el.getAttribute('data-testid');
                if (d) testids[d] = (testids[d]||0) + 1;
                const t = el.tagName;
                tags[t] = (tags[t]||0) + 1;
            });
            return {roles, testids, tags};
        }""")
        print(f"\nRoles: {json.dumps(info['roles'], indent=2)}")
        
        # Focus on comment/like/share structure
        like_els = page.evaluate("""() => {
            const els = document.querySelectorAll('[aria-label*=\"like\"], [aria-label*=\"Like\"], [aria-label*=\"suka\"], [aria-label*=\"Suka\"]');
            return Array.from(els).slice(0,5).map(el => ({
                tag: el.tagName,
                text: (el.innerText||'').trim().slice(0,100),
                aria: el.getAttribute('aria-label')||'',
                role: el.getAttribute('role')||'',
                parent_role: el.parentElement?.getAttribute('role')||'',
                parent_testid: el.parentElement?.getAttribute('data-testid')||''
            }));
        }""")
        print(f"\nLike elements (first 5): {json.dumps(like_els, indent=2)}")

        # Dump article structure more carefully
        article_html = page.evaluate("""() => {
            const arts = document.querySelectorAll('[role=\"article\"]');
            if (arts.length === 0) return 'NO ARTICLES';
            // Try to find what contains the posts
            const containers = document.querySelectorAll('div[data-pagelet]');
            const pagelets = Array.from(containers).slice(0,10).map(c => ({
                pagelet: c.getAttribute('data-pagelet'),
                children: c.children.length,
                html: c.outerHTML.substring(0,200)
            }));
            return JSON.stringify({count: arts.length, firstArticle: arts[0].outerHTML.substring(0,4000), pagelets});
        }""")
        print(f"\nArticle debug:\n{article_html[:5000]}")

        feed_items = page.evaluate("""() => {
            const classify = (href) => {
                const h = href || '';
                if (h.includes('/stories/')) return 'story';
                if (h.includes('story_fbid=')) return 'story_fbid';
                if (/\\/(posts|permalink)\\/\\d+/.test(h)) return 'post';
                if (/\\/(photo|photos)\\//.test(h)) return 'photo';
                if (/\\/(reel|reels|videos|video)\\//.test(h) || h.includes('/watch/?v=')) return 'video';
                return 'other';
            };
            return Array.from(document.querySelectorAll('[role="feed"] [aria-posinset], [role="feed"] > div > div > div > div'))
                .slice(0, 8)
                .map((item, idx) => {
                    const links = Array.from(item.querySelectorAll('a[href]'))
                        .map(a => ({
                            href: a.getAttribute('href') || '',
                            text: (a.innerText || '').trim().slice(0, 80),
                            aria: a.getAttribute('aria-label') || '',
                            kind: classify(a.getAttribute('href') || ''),
                        }))
                        .filter(x => x.href.includes('facebook.com') || x.href.startsWith('/'))
                        .slice(0, 30);
                    return {
                        idx,
                        pos: item.getAttribute('aria-posinset') || '',
                        text: (item.innerText || '').trim().replace(/\\n/g, ' | ').slice(0, 500),
                        linkKinds: links.reduce((acc, x) => {
                            acc[x.kind] = (acc[x.kind] || 0) + 1;
                            return acc;
                        }, {}),
                        links,
                    };
                });
        }""")
        print(f"\nFeed item link debug:\n{json.dumps(feed_items, ensure_ascii=False, indent=2)[:12000]}")

        # Test 2: Hashtag page
        print(f"\n\n=== TEST 2: Hashtag Page ===")
        hashtag_url = f"https://www.facebook.com/hashtag/{quote(keyword)}"
        page.goto(hashtag_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        page.evaluate("window.scrollBy(0, 800)")
        time.sleep(3)

        ht_articles = page.evaluate("""() => {
            const arts = document.querySelectorAll('[role=\"article\"]');
            const containers = document.querySelectorAll('[role=\"feed\"], [role=\"main\"]');
            return {
                articles: arts.length,
                feeds: Array.from(containers).slice(0,3).map(c => ({
                    role: c.getAttribute('role'),
                    children: c.children.length,
                    html: c.outerHTML.substring(0,300)
                })),
                firstArticleHTML: arts.length > 0 ? arts[0].outerHTML.substring(0,4000) : 'NONE'
            };
        }""")
        print(f"\nHashtag debug:\n{json.dumps(ht_articles, indent=2)[:5000]}")

        context.close()
        print("\n[DONE]")

if __name__ == "__main__":
    main()
