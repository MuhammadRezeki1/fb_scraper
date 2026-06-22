"""Dump a reel's action-rail aria-labels + numbers so we know the TRUE counts
and where the scoped extractor's numbers come from."""
from __future__ import annotations
import json, sys, time
from fb_keyword_monitor import FacebookKeywordMonitor

URL = sys.argv[1] if len(sys.argv) > 1 else "https://www.facebook.com/reel/1531824931955274"


def main() -> None:
    m = FacebookKeywordMonitor()
    m.initialize_browser()
    page = m._new_page()
    try:
        page.goto(URL, wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        m._close_popups(page)
        time.sleep(1)
        data = page.evaluate(r"""
        () => {
          const clean = t => (t || '').replace(/ |\xa0/g, ' ').replace(/\s+/g, ' ').trim();
          const arias = [];
          document.querySelectorAll('[aria-label]').forEach(el => {
            const a = clean(el.getAttribute('aria-label'));
            if (/suka|like|komentar|comment|reaksi|reaction|bagikan|share|tayangan|view|ditonton|kirim/i.test(a)) {
              const r = el.getBoundingClientRect();
              arias.push({aria: a.slice(0,80), x: Math.round(r.x), y: Math.round(r.y), role: el.getAttribute('role')||'', tag: el.tagName});
            }
          });
          // numbers that sit on the right rail (x > 60% width), top-to-bottom
          const rail = [];
          document.querySelectorAll('span,div').forEach(el => {
            const t = clean(el.innerText || el.textContent || '');
            if (!/^\d+(?:[.,]\d+)?\s*(?:rb|ribu|k|jt|juta|m)?$/i.test(t)) return;
            if (t.length > 8) return;
            const r = el.getBoundingClientRect();
            if (r.width === 0 || r.x < window.innerWidth * 0.5) return;
            rail.push({n: t, x: Math.round(r.x), y: Math.round(r.y)});
          });
          rail.sort((a,b)=>a.y-b.y);
          const seen=new Set(); const railU=[];
          for(const o of rail){const k=o.n+'|'+o.y; if(!seen.has(k)){seen.add(k);railU.push(o);}}
          return {
            url: location.href, title: document.title,
            articleCount: document.querySelectorAll('[role="article"]').length,
            arias: arias.slice(0, 60),
            rightRailNumbers: railU.slice(0, 40),
            bodyLines: clean(document.body.innerText||'').split(/\n+/).map(clean).filter(Boolean).slice(0,120),
          };
        }
        """)
        with open("debug_reel_rail.json","w",encoding="utf-8") as f:
            json.dump(data,f,ensure_ascii=False,indent=2)
        print("articleCount:", data["articleCount"])
        print("=== action aria-labels ===")
        for a in data["arias"]:
            print(f"  y={a['y']:5} x={a['x']:5} role={a['role']:8} | {a['aria']}")
        print("=== right-rail standalone numbers (y asc) ===")
        for o in data["rightRailNumbers"]:
            print(f"  y={o['y']:5} x={o['x']:5} | {o['n']}")
        print("\n-> debug_reel_rail.json")
    finally:
        try: page.close()
        except Exception: pass
        m.close()


if __name__ == "__main__":
    main()
