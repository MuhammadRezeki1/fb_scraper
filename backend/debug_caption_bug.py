"""Debug where the WRONG caption comes from on a watch/reel detail page.

Captures every caption source the scraper could use, plus the active video's
engagement-row position, so we can tell whether a caption belongs to the active
clip or to a sibling 'suggested video' in the feed below.

Run: python debug_caption_bug.py "https://www.facebook.com/watch/?v=996715136272161"
"""
from __future__ import annotations
import json, sys, time
from fb_keyword_monitor import FacebookKeywordMonitor

DEFAULT = "https://www.facebook.com/watch/?v=996715136272161"


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    m = FacebookKeywordMonitor(); m.initialize_browser(); page = m._new_page()
    try:
        nav = m.safe_goto(page, url, timeout=45000, retries=3)
        time.sleep(4); m._close_popups(page)
        try:
            page.evaluate("window.scrollBy(0, 650)"); time.sleep(0.8)
            page.evaluate("window.scrollBy(0, -220)"); time.sleep(0.4)
        except Exception:
            pass
        data = page.evaluate(r"""
        () => {
          const clean = t => (t || '').replace(/ |\xa0|Â|�/g, ' ').replace(/\s+/g, ' ').trim();
          const og = clean(document.querySelector('meta[property="og:description"]')?.getAttribute('content') || '');
          const metaDesc = clean(document.querySelector('meta[name="description"]')?.getAttribute('content') || '');
          const ogTitle = clean(document.querySelector('meta[property="og:title"]')?.getAttribute('content') || '');
          // caption-like longest line per scope (mirrors current fallback)
          const chrome = /(notifikasi|belum dibaca|lihat semua|selamat datang|masuk ke facebook|log in|filter|hasil pencarian|marketplace|halaman|grup|acara)/i;
          const metricish = /^([\d.,]+\s*(rb|ribu|k|jt|juta|m|mio|mn)?|[\d:]+|suka|komentar|bagikan|share|like|comment)$/i;
          const okCap = t => t && t.length >= 8 && t.length < 2200 && !chrome.test(t) && !metricish.test(t);
          const scopes = [];
          document.querySelectorAll('[role="main"],[role="article"],[role="complementary"]').forEach((sc, i) => {
            const role = sc.getAttribute('role');
            const r = sc.getBoundingClientRect();
            const lines = (sc.innerText || '').split(/\n+/).map(clean).filter(Boolean);
            let best = '';
            for (const ln of lines) {
              if (!okCap(ln)) continue;
              if (/durasi video|diverifikasi|yang lalu|\btayangan\b/i.test(ln)) continue;
              if (ln.length > best.length) best = ln;
            }
            scopes.push({i, role, y: Math.round(r.y), h: Math.round(r.height), bestLine: best.slice(0,140), firstLines: lines.slice(0,6)});
          });
          // global longest (what current code returns)
          let globalBest = '';
          scopes.forEach(s => { if (s.bestLine.length > globalBest.length) globalBest = s.bestLine; });
          // active video engagement row position (anchor)
          const rowM = (document.querySelector('[role="main"]')?.innerText || document.body.innerText || '')
            .match(/(?:\bSuka\b|\bLike\b)\s+(?:Komentari|Comment)\s+(?:Bagikan|Share)[^\n]{0,80}?(?:tayangan|views?|ditonton)/i);
          return {url: location.href, title: document.title, ogTitle, og, metaDesc,
                  globalLongestCaption: globalBest, engagementRow: rowM ? clean(rowM[0]).slice(0,120) : null,
                  scopeCount: scopes.length, scopes: scopes.slice(0, 10)};
        }
        """)
        meta = m._extract_detail_metadata(page)
        out = {"nav_final": nav.get("final_url"), "scraper_caption": (meta.get("caption") or "")[:200],
               "scraper_author": meta.get("author"), "dom": data}
        with open("debug_caption_bug.json", "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print("saved debug_caption_bug.json")
        print("URL              :", url)
        print("og:title         :", data.get("ogTitle"))
        print("og:description   :", (data.get("og") or "")[:160])
        print("meta description :", (data.get("metaDesc") or "")[:160])
        print("engagement row   :", data.get("engagementRow"))
        print("GLOBAL longest cap:", (data.get("globalLongestCaption") or "")[:160])
        print("SCRAPER caption  :", out["scraper_caption"][:160])
        print("scopes:")
        for s in data.get("scopes", []):
            print(f"  [{s['i']}] role={s['role']:13} y={s['y']:5} h={s['h']:5} | best={s['bestLine'][:90]}")
    finally:
        try: page.close()
        except Exception: pass
        m.close()


if __name__ == "__main__":
    main()
