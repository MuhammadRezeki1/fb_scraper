"""
Comprehensive DOM debug for:
1. Reels: caption, likes, comments
2. Posts: likes, comments
3. Groups: name + about/description (NOT posts)
"""
import os, json, time, sys
from playwright.sync_api import sync_playwright

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")

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

        # ============================================================
        # TEST 1: REEL - caption, likes, comments
        # ============================================================
        print("\n\n=== TEST 1: REEL ===")
        reel_url = "https://www.facebook.com/reel/1423069579580402"
        print(f"[NAV] {reel_url}")
        page.goto(reel_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        
        reel_debug = page.evaluate("""() => {
            const result = {};
            
            // Full page text (first 3000 chars)
            result.fullText = (document.body.innerText || '').replace(/\\n/g, ' | ').slice(0, 3000);
            
            // Find caption/description
            const captionSelectors = [
                '[data-testid="post_message"]',
                '[data-testid="fbfeed_story"]',
                'div[dir="auto"]',
                'span[dir="auto"]',
                '[role="article"]'
            ];
            result.captions = [];
            captionSelectors.forEach(sel => {
                try {
                    const els = document.querySelectorAll(sel);
                    els.forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (t.length >= 10 && t.length < 2000) {
                            result.captions.push({
                                selector: sel,
                                text: t.slice(0, 300),
                                tag: el.tagName,
                                class: (el.getAttribute('class') || '').slice(0, 40)
                            });
                        }
                    });
                } catch(e) {}
            });
            
            // Find like buttons
            const likeSelectors = [
                '[aria-label*="Suka" i]',
                '[aria-label*="Like" i]',
                '[aria-label*="react" i]',
                '[data-testid="like_button"]'
            ];
            result.likeButtons = [];
            likeSelectors.forEach(sel => {
                try {
                    const els = document.querySelectorAll(sel);
                    els.forEach(el => {
                        const aria = el.getAttribute('aria-label') || '';
                        const text = (el.innerText || '').trim();
                        if (text || aria) {
                            result.likeButtons.push({
                                selector: sel,
                                aria: aria.slice(0, 100),
                                text: text.slice(0, 50),
                                tag: el.tagName
                            });
                        }
                    });
                } catch(e) {}
            });
            
            // Find comment buttons
            const commentSelectors = [
                '[aria-label*="Komentar" i]',
                '[aria-label*="Comment" i]',
                '[data-testid="comment_button"]'
            ];
            result.commentButtons = [];
            commentSelectors.forEach(sel => {
                try {
                    const els = document.querySelectorAll(sel);
                    els.forEach(el => {
                        const aria = el.getAttribute('aria-label') || '';
                        const text = (el.innerText || '').trim();
                        if (text || aria) {
                            result.commentButtons.push({
                                selector: sel,
                                aria: aria.slice(0, 100),
                                text: text.slice(0, 50)
                            });
                        }
                    });
                } catch(e) {}
            });
            
            // Find share buttons
            const shareSelectors = [
                '[aria-label*="Bagikan" i]',
                '[aria-label*="Share" i]'
            ];
            result.shareButtons = [];
            shareSelectors.forEach(sel => {
                try {
                    const els = document.querySelectorAll(sel);
                    els.forEach(el => {
                        const aria = el.getAttribute('aria-label') || '';
                        const text = (el.innerText || '').trim();
                        if (text || aria) {
                            result.shareButtons.push({
                                aria: aria.slice(0, 100),
                                text: text.slice(0, 50)
                            });
                        }
                    });
                } catch(e) {}
            });
            
            // Find all links
            const links = document.querySelectorAll('a[href]');
            result.links = Array.from(links).slice(0, 10).map(a => ({
                href: (a.getAttribute('href') || '').slice(0, 150),
                text: (a.innerText || '').trim().slice(0, 50)
            }));
            
            // Find data-testid attributes
            const testids = {};
            document.querySelectorAll('[data-testid]').forEach(el => {
                const tid = el.getAttribute('data-testid');
                if (tid) testids[tid] = (testids[tid] || 0) + 1;
            });
            result.testids = testids;
            
            return result;
        }""")
        
        print(f"\n=== REEL DEBUG ===\n{json.dumps(reel_debug, indent=2, ensure_ascii=False)[:8000]}")
        
        # ============================================================
        # TEST 2: GROUP - name + about/description
        # ============================================================
        print("\n\n=== TEST 2: GROUP ===")
        group_url = "https://www.facebook.com/groups/908802691854788"
        print(f"[NAV] {group_url}")
        page.goto(group_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        
        group_debug = page.evaluate("""() => {
            const result = {};
            
            // Group name
            const nameSelectors = [
                'h1',
                'h2',
                '[data-testid="group_name"]',
                'a[href*="/groups/"]'
            ];
            result.groupName = '';
            for (const sel of nameSelectors) {
                try {
                    const el = document.querySelector(sel);
                    if (el) {
                        const t = (el.innerText || '').trim();
                        if (t.length >= 2 && t.length < 200) {
                            result.groupName = t;
                            result.groupNameSelector = sel;
                            break;
                        }
                    }
                } catch(e) {}
            }
            
            // About/description
            const aboutSelectors = [
                '[data-testid="group_about"]',
                '[data-testid="group_description"]',
                'div[dir="auto"]',
                'span[dir="auto"]'
            ];
            result.aboutTexts = [];
            for (const sel of aboutSelectors) {
                try {
                    const els = document.querySelectorAll(sel);
                    els.forEach(el => {
                        const t = (el.innerText || '').trim();
                        if (t.length >= 20 && t.length < 1000) {
                            result.aboutTexts.push({
                                selector: sel,
                                text: t.slice(0, 300),
                                tag: el.tagName
                            });
                        }
                    });
                } catch(e) {}
            }
            
            // Full page text
            result.fullText = (document.body.innerText || '').replace(/\\n/g, ' | ').slice(0, 2000);
            
            // All data-testid
            const testids = {};
            document.querySelectorAll('[data-testid]').forEach(el => {
                const tid = el.getAttribute('data-testid');
                if (tid) testids[tid] = (testids[tid] || 0) + 1;
            });
            result.testids = testids;
            
            return result;
        }""")
        
        print(f"\n=== GROUP DEBUG ===\n{json.dumps(group_debug, indent=2, ensure_ascii=False)[:6000]}")
        
        # ============================================================
        # TEST 3: POST - likes, comments
        # ============================================================
        print("\n\n=== TEST 3: POST ===")
        post_url = "https://www.facebook.com/photo/?fbid=27273950132225203"
        print(f"[NAV] {post_url}")
        page.goto(post_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(5)
        
        post_debug = page.evaluate("""() => {
            const result = {};
            result.fullText = (document.body.innerText || '').replace(/\\n/g, ' | ').slice(0, 2000);
            
            // Like buttons
            result.likeButtons = [];
            document.querySelectorAll('[aria-label]').forEach(el => {
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                if (aria.includes('suka') || aria.includes('like') || aria.includes('react')) {
                    result.likeButtons.push({
                        aria: el.getAttribute('aria-label') || '',
                        text: (el.innerText || '').trim().slice(0, 30),
                        tag: el.tagName
                    });
                }
            });
            
            // Comment buttons
            result.commentButtons = [];
            document.querySelectorAll('[aria-label]').forEach(el => {
                const aria = (el.getAttribute('aria-label') || '').toLowerCase();
                if (aria.includes('komentar') || aria.includes('comment')) {
                    result.commentButtons.push({
                        aria: el.getAttribute('aria-label') || '',
                        text: (el.innerText || '').trim().slice(0, 30),
                        tag: el.tagName
                    });
                }
            });
            
            // data-testid
            const testids = {};
            document.querySelectorAll('[data-testid]').forEach(el => {
                const tid = el.getAttribute('data-testid');
                if (tid) testids[tid] = (testids[tid] || 0) + 1;
            });
            result.testids = testids;
            
            return result;
        }""")
        
        try:
            print(f"\n=== POST DEBUG ===\n{json.dumps(post_debug, indent=2, ensure_ascii=False)[:6000]}")
        except UnicodeEncodeError:
            print("\n=== POST DEBUG === (encoding error, saving to file)")
            with open("debug_post_result.json", "w", encoding="utf-8") as f:
                json.dump(post_debug, f, ensure_ascii=False, indent=2)
        
        # Screenshot
        page.screenshot(path="debug_reel_group_post.png", full_page=True)
        print("\n[Screenshot saved] debug_reel_group_post.png")
        
        context.close()
        print("\n[DONE]")

if __name__ == "__main__":
    main()