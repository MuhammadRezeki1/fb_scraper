from __future__ import annotations

import json
import time

from fb_keyword_monitor import FacebookKeywordMonitor


URL = "https://www.facebook.com/search/posts/?q=bemui"


def main() -> None:
    monitor = FacebookKeywordMonitor()
    monitor.initialize_browser()
    page = monitor._new_page()
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        monitor._close_popups(page)
        for _ in range(2):
            page.evaluate("window.scrollBy(0, 900)")
            time.sleep(0.5)

        data = page.evaluate(
            r"""
            () => {
              const clean = t => (t || '').replace(/\u00a0|\xa0/g, ' ').replace(/\s+/g, ' ').trim();
              const cards = [
                ...document.querySelectorAll('[role="feed"] [aria-posinset]'),
                ...document.querySelectorAll('[role="feed"] [role="article"]'),
                ...document.querySelectorAll('[role="article"]'),
              ];
              const seen = new Set();
              const out = [];
              cards.forEach((card, idx) => {
                if (seen.has(card)) return;
                seen.add(card);
                const text = clean(card.innerText || '');
                const links = [...card.querySelectorAll('a[href]')].map(a => ({
                  text: clean(a.innerText || ''),
                  aria: clean(a.getAttribute('aria-label') || ''),
                  href: a.getAttribute('href') || '',
                })).filter(x => x.href).slice(0, 40);
                out.push({
                  idx,
                  role: card.getAttribute('role') || '',
                  aria: clean(card.getAttribute('aria-label') || ''),
                  text: text.slice(0, 1200),
                  linkCount: links.length,
                  links,
                });
              });
              return {
                url: location.href,
                title: document.title,
                feedCount: document.querySelectorAll('[role="feed"] [aria-posinset]').length,
                articleCount: document.querySelectorAll('[role="article"]').length,
                cards: out.slice(0, 12),
              };
            }
            """
        )
        with open("debug_search_posts_dom_once.json", "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        print(json.dumps({
            "saved": "debug_search_posts_dom_once.json",
            "url": data.get("url"),
            "feedCount": data.get("feedCount"),
            "articleCount": data.get("articleCount"),
            "cards": len(data.get("cards", [])),
            "firstLinks": data.get("cards", [{}])[0].get("links", [])[:8] if data.get("cards") else [],
        }, ensure_ascii=True, indent=2))
    finally:
        try:
            page.close()
        except Exception:
            pass
        monitor.close()


if __name__ == "__main__":
    main()
