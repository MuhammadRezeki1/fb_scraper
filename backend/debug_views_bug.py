"""Debug where wrong views/likes come from on a Facebook watch/reel detail page.

Captures:
  - what extract_detail_metrics() actually returns (the real scraper path)
  - every metric-text candidate that yields a views/likes/comments/shares number,
    with the parsed value + a y-coordinate so we can tell the MAIN video apart
    from sidebar "suggested videos" and from the comments section.
  - the reel-footer parse + _extract_detail_metadata() result.

Run:  python debug_views_bug.py "https://www.facebook.com/watch/?v=1622180902211798"
"""
from __future__ import annotations

import json
import sys
import time

from fb_keyword_monitor import (
    FacebookKeywordMonitor,
    extract_video_metrics_from_text,
    extract_reel_footer_metrics_from_text,
)

DEFAULT_URL = "https://www.facebook.com/watch/?v=1622180902211798"


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    monitor = FacebookKeywordMonitor()
    monitor.initialize_browser()
    page = monitor._new_page()
    try:
        # 1) Run the REAL scraper path so we see what it currently returns.
        detail = monitor.extract_detail_metrics(page, url)

        # 2) Re-collect candidates with geometry so we can locate each number.
        candidates = monitor.collect_metric_text_candidates(page)
        try:
            body_text = page.locator("body").inner_text(timeout=3000)
        except Exception:
            body_text = ""

        # Per-candidate breakdown: which candidate produced which metric value.
        per_field: dict[str, list] = {"views": [], "likes": [], "comments": [], "shares": []}
        for cand in candidates:
            found = extract_video_metrics_from_text(cand)
            for field in per_field:
                if found.get(field) is not None:
                    per_field[field].append({
                        "value": found[field],
                        "pattern": found.get("matched_patterns", {}).get(field, ""),
                        "candidate": cand[:200],
                    })
        # Sort each field by value desc so the suspicious large numbers float up.
        for field in per_field:
            per_field[field].sort(key=lambda x: x["value"], reverse=True)

        footer = extract_reel_footer_metrics_from_text(body_text)
        meta = monitor._extract_detail_metadata(page)

        # 3) Geometry of every number labelled with a metric word, so we can see
        #    whether the picked value belongs to the main player or the right rail.
        geo = page.evaluate(r"""
        () => {
          const clean = t => (t || '').replace(/ |\xa0/g, ' ').replace(/\s+/g, ' ').trim();
          const metricRe = /([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(tayangan|views?|ditonton|suka|like|reaksi|reaction|komentar|comment|dibagikan|share)/i;
          const out = [];
          document.querySelectorAll('span,div,a,[aria-label]').forEach(el => {
            const txt = clean(el.innerText || el.textContent || '');
            const aria = clean(el.getAttribute('aria-label') || '');
            const combo = `${aria} ${txt}`;
            if (combo.length > 120) return;
            if (!metricRe.test(combo)) return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 && r.height === 0) return;
            out.push({
              text: combo.slice(0, 90),
              x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width),
              href: el.getAttribute('href') || (el.closest('a') ? el.closest('a').getAttribute('href') : '') || '',
            });
          });
          // dedupe by text+y
          const seen = new Set(); const uniq = [];
          for (const o of out) { const k = o.text + '|' + o.y; if (!seen.has(k)) { seen.add(k); uniq.push(o); } }
          uniq.sort((a, b) => a.y - b.y);
          return { vw: window.innerWidth, vh: window.innerHeight, nodes: uniq.slice(0, 120) };
        }
        """)

        payload = {
            "url": url,
            "final_url": detail.get("detail_final_url"),
            "SCRAPER_RETURNED": {
                k: detail.get(k) for k in
                ("likes_count", "comments_count", "shares_count", "views_count",
                 "metrics_valid", "metric_source", "detail_status")
            },
            "matched_patterns": detail.get("matched_patterns"),
            "per_field_candidates": per_field,
            "reel_footer": footer,
            "detail_metadata": meta,
            "geometry": geo,
        }
        with open("debug_views_bug.json", "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

        print(json.dumps({
            "url": url,
            "SCRAPER_RETURNED": payload["SCRAPER_RETURNED"],
            "matched_patterns": payload["matched_patterns"],
            "views_candidates_top5": per_field["views"][:5],
            "likes_candidates_top5": per_field["likes"][:5],
            "comments_candidates_top5": per_field["comments"][:3],
            "reel_footer": footer,
            "meta": meta,
        }, ensure_ascii=False, indent=2))
        print("\nFull dump -> debug_views_bug.json")
    finally:
        try:
            page.close()
        except Exception:
            pass
        monitor.close()


if __name__ == "__main__":
    main()
