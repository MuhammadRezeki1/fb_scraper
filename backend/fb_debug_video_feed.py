"""
Debug script: Analisa mengapa video caption/likes/comments tidak terscrape
dan mengapa feed extraction gagal (FEED R1: 0(+0))

Usage: python fb_debug_video_feed.py [keyword]
"""
import os, json, time, sys
from playwright.sync_api import sync_playwright
from urllib.parse import quote

FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
keyword = sys.argv[1] if len(sys.argv) > 1 else "polda metro jaya"

OUTPUT_DIR = "fb_dom_debug_output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

def save(name, data):
    path = os.path.join(OUTPUT_DIR, f"debug_{name}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [SAVED] {path}")

def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            FB_CHROME_PROFILE, channel="chrome", headless=False, no_viewport=True,
            args=["--disable-notifications", "--mute-audio"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            from fb_cookie_injector import inject_cookies_sync
            inject_cookies_sync(context)
            print("[OK] Cookies injected")
        except Exception as e:
            print(f"[WARN] {e}")

        # ================================================================
        # TEST 1: Feed Posts Search — mengapa FEED R1: 0(+0)?
        # ================================================================
        print(f"\n\n=== TEST 1: FEED POSTS SEARCH '{keyword}' ===")
        url = f"https://www.facebook.com/search/posts/?q={quote(keyword)}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(6)
        page.evaluate("window.scrollBy(0, 1500)")
        time.sleep(3)

        # FIX: gunakan \\d bukan \d di dalam Python string
        feed_debug = page.evaluate("""() => {
            const result = {};
            // Cek struktur feed
            result.hasFeed = !!document.querySelector('[role="feed"]');
            result.feedChildCount = document.querySelector('[role="feed"]')?.children.length || 0;
            result.ariaPosinset = document.querySelectorAll('[role="feed"] [aria-posinset]').length;
            result.feedDirectDiv = document.querySelectorAll('[role="feed"]>div>div>div>div').length;

            // Cek apakah ada article elements
            result.articleCount = document.querySelectorAll('[role="article"]').length;

            // Sample artikel pertama
            const firstArticle = document.querySelector('[role="article"]');
            if (firstArticle) {
                result.firstArticleInnerText = (firstArticle.innerText || '').slice(0, 500);
                result.firstArticleLinks = Array.from(firstArticle.querySelectorAll('a[href]'))
                    .slice(0, 10).map(a => ({
                        href: (a.getAttribute('href') || '').slice(0, 200),
                        text: (a.innerText || '').slice(0, 50)
                    }));
            }

            // Cek struktur halaman
            result.main = !!document.querySelector('[role="main"]');
            result.mainChildCount = document.querySelector('[role="main"]')?.children.length || 0;

            // Sampling semua link di halaman yang mengandung post/video/photo
            const validLinks = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.getAttribute('href') || '';
                if (h.includes('/posts/') || h.includes('/videos/') || h.includes('/photo/')
                    || h.includes('/reel/') || h.includes('fbid=') || h.includes('/watch')) {
                    validLinks.push(h.slice(0, 200));
                }
            });
            result.validPostLinks = [...new Set(validLinks)].slice(0, 15);
            result.validPostLinksCount = validLinks.length;

            // Cek apakah feed items pakai selector baru
            const feedSelectors = [
                '[role="feed"] [aria-posinset]',
                '[role="feed"] > div',
                '[data-pagelet="FeedUnit"]',
                '[data-testid="fbfeed_story"]',
                '[data-testid="story-subtitle"]',
                'div[class*="x1lliihq"][class*="x6ikm8r"]',
            ];
            result.selectorCounts = {};
            feedSelectors.forEach(sel => {
                try { result.selectorCounts[sel] = document.querySelectorAll(sel).length; }
                catch(e) { result.selectorCounts[sel] = 'error'; }
            });

            // Sample innerHTML dari feed container (2000 chars untuk analisis)
            const feedEl = document.querySelector('[role="feed"]');
            if (feedEl) {
                result.feedInnerTextSample = (feedEl.innerText || '').slice(0, 1500).replace(/\\n/g, ' | ');
                const children = Array.from(feedEl.children);
                result.feedChildren = children.slice(0, 5).map(c => ({
                    tag: c.tagName,
                    role: c.getAttribute('role') || '',
                    ariaPosinset: c.getAttribute('aria-posinset') || '',
                    childCount: c.children.length,
                    text: (c.innerText || '').slice(0, 100)
                }));
            }
            return result;
        }""")
        save("feed_posts_search", feed_debug)
        print(f"  hasFeed: {feed_debug.get('hasFeed')}")
        print(f"  ariaPosinset count: {feed_debug.get('ariaPosinset')}")
        print(f"  feedDirectDiv: {feed_debug.get('feedDirectDiv')}")
        print(f"  articleCount: {feed_debug.get('articleCount')}")
        print(f"  validPostLinksCount: {feed_debug.get('validPostLinksCount')}")
        print(f"  validLinks sample: {feed_debug.get('validPostLinks', [])[:5]}")
        print(f"  selectorCounts: {feed_debug.get('selectorCounts')}")

        # ================================================================
        # TEST 2: Video Search — mengapa caption/likes/comments 0?
        # ================================================================
        print(f"\n\n=== TEST 2: VIDEO SEARCH '{keyword}' ===")
        url2 = f"https://www.facebook.com/search/videos/?q={quote(keyword)}"
        page.goto(url2, wait_until="domcontentloaded", timeout=30000)
        time.sleep(6)
        page.evaluate("window.scrollBy(0, 1500)")
        time.sleep(3)

        # FIX: \\d bukan \d di dalam Python string
        video_debug = page.evaluate("""() => {
            const result = {};
            result.articleCount = document.querySelectorAll('[role="article"]').length;

            const articles = Array.from(document.querySelectorAll('[role="article"]'));
            result.articles = articles.slice(0, 4).map(art => {
                const links = Array.from(art.querySelectorAll('a[href]'))
                    .map(a => (a.getAttribute('href') || '').slice(0, 200))
                    .filter(h => h.includes('/video') || h.includes('/reel') || h.includes('/watch'));

                const buttons = Array.from(art.querySelectorAll('[role="button"],[aria-label]'));
                const engagementBtns = buttons
                    .filter(b => {
                        const a = (b.getAttribute('aria-label') || '').toLowerCase();
                        return a.includes('suka') || a.includes('like') || a.includes('komentar')
                            || a.includes('comment') || a.includes('bagikan') || a.includes('share')
                            || a.includes('tayangan') || a.includes('view') || /\\d+/.test(a);
                    })
                    .slice(0, 10).map(b => ({
                        aria: (b.getAttribute('aria-label') || '').slice(0, 100),
                        text: (b.innerText || '').trim().slice(0, 50),
                        tag: b.tagName
                    }));

                return {
                    ariaLabel: art.getAttribute('aria-label') || '',
                    text: (art.innerText || '').slice(0, 400).replace(/\\n/g, ' | '),
                    videoLinks: links.slice(0, 3),
                    engagementBtns
                };
            });

            const videoLinks = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const h = a.getAttribute('href') || '';
                if (h.includes('/videos/') || h.includes('/reel/') || h.includes('/watch') || h.includes('/video/')) {
                    videoLinks.push({href: h.slice(0, 200), text: (a.innerText || '').slice(0, 50)});
                }
            });
            result.videoLinksCount = videoLinks.length;
            result.videoLinksSample = videoLinks.slice(0, 8);

            result.hasJsonLd = !!document.querySelector('script[type="application/ld+json"]');
            result.metaOgTitle = document.querySelector('meta[property="og:title"]')?.content || '';
            result.metaOgDesc = document.querySelector('meta[property="og:description"]')?.content || '';
            return result;
        }""")
        save("video_search", video_debug)
        print(f"  articleCount: {video_debug.get('articleCount')}")
        print(f"  videoLinksCount: {video_debug.get('videoLinksCount')}")
        print(f"  videoLinksSample: {video_debug.get('videoLinksSample', [])[:3]}")
        for i, art in enumerate(video_debug.get('articles', [])):
            print(f"  --- Article {i+1} ---")
            print(f"    aria: {art['ariaLabel'][:80]}")
            print(f"    text: {art['text'][:200]}")
            print(f"    videoLinks: {art['videoLinks']}")
            print(f"    engagementBtns: {art['engagementBtns'][:3]}")

        # ================================================================
        # TEST 3: Buka salah satu video secara langsung
        # ================================================================
        video_links = video_debug.get('videoLinksSample', [])
        if video_links:
            test_video = video_links[0]['href']
            if not test_video.startswith('http'):
                test_video = 'https://www.facebook.com' + test_video
            print(f"\n\n=== TEST 3: INDIVIDUAL VIDEO PAGE ===")
            print(f"  URL: {test_video}")
            page.goto(test_video, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)

            # FIX: \\d bukan \d, \\n bukan \n di dalam Python string
            individual_debug = page.evaluate("""() => {
                const result = {};
                result.url = location.href;
                result.title = document.title;

                const numericAria = [];
                document.querySelectorAll('[aria-label]').forEach(el => {
                    const a = el.getAttribute('aria-label') || '';
                    if (/\\d/.test(a) && a.length < 150) {
                        numericAria.push({
                            aria: a.slice(0, 100),
                            text: (el.innerText || '').trim().slice(0, 30),
                            tag: el.tagName
                        });
                    }
                });
                result.numericAriaLabels = numericAria.slice(0, 20);

                const bodyText = document.body.innerText || '';
                const engagementPatterns = [
                    /([\\d][\\d.,]*\\s*(?:rb|jt|k|m)?)\\s*(?:suka|like|likes)/gi,
                    /([\\d][\\d.,]*\\s*(?:rb|jt|k|m)?)\\s*(?:komentar|comment)/gi,
                    /([\\d][\\d.,]*\\s*(?:rb|jt|k|m)?)\\s*(?:dibagikan|share|bagikan)/gi,
                    /([\\d][\\d.,]*\\s*(?:rb|jt|k|m)?)\\s*(?:tayangan|view|ditonton)/gi,
                    /(?:suka|like|likes)\\s*[:\\s]*([\\d][\\d.,]*\\s*(?:rb|jt|k|m)?)/gi,
                    /(?:komentar|comment)\\s*[:\\s]*([\\d][\\d.,]*\\s*(?:rb|jt|k|m)?)/gi,
                ];
                result.engagementMatches = {};
                engagementPatterns.forEach(pat => {
                    const matches = [];
                    let m;
                    pat.lastIndex = 0;
                    const text = bodyText.slice(0, 5000);
                    while ((m = pat.exec(text)) !== null && matches.length < 5) {
                        matches.push(m[0].slice(0, 50));
                    }
                    if (matches.length) result.engagementMatches[pat.source.slice(0, 30)] = matches;
                });

                const og = document.querySelector('meta[property="og:description"]');
                result.ogDescription = og ? (og.getAttribute('content') || '').slice(0, 500) : '';
                result.bodyTextSample = bodyText.slice(0, 2000).replace(/\\n/g, ' | ');
                return result;
            }""")
            save("individual_video", individual_debug)
            print(f"  title: {individual_debug.get('title', '')[:80]}")
            print(f"  ogDescription: {individual_debug.get('ogDescription', '')[:200]}")
            print(f"  numericAriaLabels sample: {individual_debug.get('numericAriaLabels', [])[:8]}")
            print(f"  engagementMatches: {individual_debug.get('engagementMatches', {})}")
            print(f"  bodyText (first 500): {individual_debug.get('bodyTextSample', '')[:500]}")

        print("\n\n=== DEBUG SELESAI ===")
        print(f"Hasil disimpan di folder: {OUTPUT_DIR}/")
        input("Tekan ENTER untuk tutup browser...")
        context.close()

if __name__ == "__main__":
    main()