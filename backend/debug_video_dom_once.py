from __future__ import annotations

import json
import time

from fb_keyword_monitor import FacebookKeywordMonitor


URL = "https://www.facebook.com/watch/?v=1564433578638128"


def main() -> None:
    monitor = FacebookKeywordMonitor()
    monitor.initialize_browser()
    page = monitor._new_page()
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        monitor._close_popups(page)
        try:
            page.evaluate("window.scrollBy(0, 700)")
            time.sleep(1)
        except Exception:
            pass

        data = page.evaluate(
            r"""
            () => {
              const clean = t => (t || '').replace(/\u00a0|\xa0/g, ' ').replace(/\s+/g, ' ').trim();
              const nodes = [
                ...document.querySelectorAll('[role="article"], [role="main"], [role="complementary"], [aria-label], [role="button"], a[href]')
              ];
              const interesting = [];
              nodes.forEach((el, i) => {
                const txt = clean(el.innerText || el.textContent || '');
                const aria = clean(el.getAttribute('aria-label') || '');
                const href = el.getAttribute('href') || '';
                const combo = `${aria} ${txt} ${href}`;
                if (/suka|like|komentar|comment|bagikan|share|tayangan|view|1564433578638128|reactions?|reaksi|ikuti|kolektif|papua/i.test(combo)) {
                  const r = el.getBoundingClientRect();
                  interesting.push({
                    i,
                    tag: el.tagName,
                    role: el.getAttribute('role') || '',
                    aria,
                    href,
                    text: txt.slice(0, 600),
                    rect: { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height) },
                  });
                }
              });
              const lines = clean(document.body.innerText || '').split(/\n+/).map(clean).filter(Boolean);
              return {
                url: location.href,
                title: document.title,
                articleCount: document.querySelectorAll('[role="article"]').length,
                mainText: clean(document.querySelector('[role="main"]')?.innerText || '').slice(0, 3000),
                lines: lines.slice(0, 180),
                interesting: interesting.slice(0, 140),
              };
            }
            """
        )
        meta = monitor._extract_detail_metadata(page)
        payload = {"dom": data, "meta": meta}
        with open("debug_video_dom_once.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(json.dumps({
            "saved": "debug_video_dom_once.json",
            "url": data.get("url"),
            "articleCount": data.get("articleCount"),
            "meta": meta,
            "interestingCount": len(data.get("interesting", [])),
        }, ensure_ascii=True, indent=2))
    finally:
        try:
            page.close()
        except Exception:
            pass
        monitor.close()


if __name__ == "__main__":
    main()
