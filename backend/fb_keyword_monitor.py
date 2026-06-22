import os, re, json, time, random, math, threading, uuid, html
from datetime import datetime
from typing import List, Dict, Optional, Set, Any, Callable
from urllib.parse import quote, urlparse, parse_qs
from dotenv import load_dotenv
from colorama import Fore, init
from playwright.sync_api import sync_playwright, Page, BrowserContext, Response
from browser_runtime import browser_channel_kwargs, fb_headless

init(autoreset=True); load_dotenv()
HEADLESS = fb_headless(True)
FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
FB_BLOCK_HEAVY_RESOURCES = os.getenv("FB_BLOCK_HEAVY_RESOURCES", "true").lower() == "true"
FB_PER_TYPE_MIN = int(os.getenv("FB_PER_TYPE_MIN", "60"))
FB_SEARCH_PRE_SCROLLS = int(os.getenv("FB_SEARCH_PRE_SCROLLS", "2"))
FB_FEED_MAX_ROUNDS = int(os.getenv("FB_FEED_MAX_ROUNDS", "18"))
FB_FEED_WAIT_ROUNDS = int(os.getenv("FB_FEED_WAIT_ROUNDS", "4"))
FB_GENERIC_MAX_ROUNDS = int(os.getenv("FB_GENERIC_MAX_ROUNDS", "16"))
FB_DETAIL_ENRICH_LIMIT = int(os.getenv("FB_DETAIL_ENRICH_LIMIT", "24"))
FB_DETAIL_WAIT_SECONDS = float(os.getenv("FB_DETAIL_WAIT_SECONDS", "1.2"))
FB_WARMUP_SECONDS = float(os.getenv("FB_WARMUP_SECONDS", "3"))
FB_HOME_LOAD_SECONDS = float(os.getenv("FB_HOME_LOAD_SECONDS", "1.5"))
FB_SEARCH_LOAD_SECONDS = float(os.getenv("FB_SEARCH_LOAD_SECONDS", "1.2"))
FB_SEARCH_SCROLL_DELAY = float(os.getenv("FB_SEARCH_SCROLL_DELAY", "0.35"))
FB_TYPE_SWITCH_DELAY = float(os.getenv("FB_TYPE_SWITCH_DELAY", "0.25"))
FB_PAGE_DEEP_OPEN_LIMIT = int(os.getenv("FB_PAGE_DEEP_OPEN_LIMIT", "0"))
os.makedirs("output_facebook", exist_ok=True); os.makedirs("fb_keyword_debug", exist_ok=True)

def _metric_value(value) -> int:
    try:
        if value is None:
            return 0
        return int(value or 0)
    except Exception:
        return 0

def _engagement_score(item):
    """Return a score comparable across normal posts and videos."""
    return (
        _metric_value(item.get("likes_count"))
        + _metric_value(item.get("comments_count")) * 2
        + _metric_value(item.get("shares_count")) * 3
        + _metric_value(item.get("views_count")) * 0.1
    )

VIRAL_LEVEL_ORDER = {
    "unknown": 0,
    "low": 1,
    "potential": 2,
    "viral": 3,
    "strong_viral": 4,
    "very_viral": 5,
}

def _viral_level(score: float) -> str:
    if score < 100:
        return "low"
    if score < 300:
        return "potential"
    if score < 1000:
        return "viral"
    if score < 3000:
        return "strong_viral"
    return "very_viral"

def assign_viral_fields(item: dict) -> dict:
    if not item:
        return item
    likes = _metric_value(item.get("likes_count"))
    comments = _metric_value(item.get("comments_count"))
    shares = _metric_value(item.get("shares_count"))
    views = _metric_value(item.get("views_count"))
    has_any_metric = any(v > 0 for v in (likes, comments, shares, views))
    if item.get("metrics_valid") is False or not has_any_metric:
        item["metrics_valid"] = False
        item["viral_score"] = 0
        item["viral_level"] = "unknown"
        item["viral_reason"] = "metrics belum valid"
        return item

    score = likes + comments * 4 + shares * 6 + views * 0.02
    reasons = []
    viral_hit = False
    if _is_video_item(item) and views >= 10000:
        viral_hit = True
        reasons.append("views >= 10000")
    if comments >= 30:
        viral_hit = True
        reasons.append("comments >= 30")
    if likes >= 100:
        viral_hit = True
        reasons.append("likes >= 100")
    if shares >= 10:
        viral_hit = True
        reasons.append("shares >= 10")
    if score >= 300:
        viral_hit = True
        reasons.append("viral_score >= 300")
    if not reasons:
        reasons.append("engagement rendah")

    level = _viral_level(score)
    if viral_hit and VIRAL_LEVEL_ORDER.get(level, 0) < VIRAL_LEVEL_ORDER["viral"]:
        level = "viral"
    item["viral_score"] = round(score, 2)
    item["viral_level"] = level
    item["viral_reason"] = ", ".join(reasons)
    return item

def _viral_sort_key(item: dict):
    assign_viral_fields(item)
    return (
        VIRAL_LEVEL_ORDER.get(item.get("viral_level", "unknown"), 0),
        float(item.get("viral_score") or 0),
        _metric_value(item.get("comments_count")),
        _metric_value(item.get("views_count")),
    )

def _apply_sort(items,sort_by):
    if not items: return items
    for item in items:
        assign_viral_fields(item)
    if sort_by in ("engagement", "viral", "trending", "", None):
        items.sort(key=_viral_sort_key, reverse=True)
        for i,p in enumerate(items,1): p["rank"]=i
        return items
    m={"engagement":lambda x:_engagement_score(x),"likes":lambda x:_metric_value(x.get("likes_count")),"comments":lambda x:_metric_value(x.get("comments_count")),
       "views":lambda x:_metric_value(x.get("views_count")),"shares":lambda x:_metric_value(x.get("shares_count")),"recent":lambda x:x.get("timestamp","")}
    items.sort(key=m.get(sort_by,m["engagement"]),reverse=True)
    for i,p in enumerate(items,1): p["rank"]=i
    return items

def _apply_min_filters(items,ml=None,mc=None,mv=None):
    if ml is None and mc is None and mv is None: return items
    return [i for i in items if not(ml is not None and _metric_value(i.get("likes_count"))<ml or mc is not None and _metric_value(i.get("comments_count"))<mc or mv is not None and _metric_value(i.get("views_count"))<mv)]

def _is_commentable_url(url):
    if not url: return False
    if '/stories/' in url or url.startswith('https://www.facebook.com/article_'): return False
    if '/groups/' in url and '/posts/' not in url: return False
    if any(x in url for x in ['/posts/','/photo/','/videos/','/watch','/reel/','/permalink/']): return True
    if re.search(r'/\d{10,}',url): return True
    return False

def _is_valid_result_url(url):
    if not url:
        return False
    u = url.lower()

    # Blok absolut
    for blocked in ['/legal/','/privacy/','/help/','/about/','/policies',
                    '/security/','/stories/','/hashtag/','/login','/signup']:
        if blocked in u:
            return False

    # ✅ FIX: support format share baru FB (share/p/, share/v/, share/r/)
    if re.search(r'/share/(p|v|r)/[a-z0-9_-]+', u):
        return True

    # Photo dengan fbid
    if 'facebook.com/photo/?fbid=' in u or 'facebook.com/photo?fbid=' in u or re.search(r'/photo/?\?fbid=\d+', u):
        return True
    # Watch video, including live permalink surface.
    if '/watch' in u and re.search(r'[?&]v=\d+', u):
        return True
    # Group post (bukan group homepage)
    if re.search(r'/groups/[^/]+/(posts|permalink)/\d+', u):
        return True
    # Group searches intentionally return group metadata, not group posts.
    if re.search(r'facebook\.com/groups/[^/?#]+/?(?:[?#].*)?$', u):
        return True
    # Post / permalink
    if re.search(r'/(posts|permalink)/(?:\d+|pfbid[a-z0-9_-]+)', u):
        return True
    # Video / reel dengan ID
    if re.search(r'/(videos?|reels?)/\d+', u):
        return True
    # Photo dengan ID numerik
    if re.search(r'/(photo|photos)/\d+', u):
        return True
    # story_fbid
    if re.search(r'story_fbid=\d+', u):
        return True
    # profile.php — hanya jika ada konten (story_fbid atau set=)
    if re.search(r'/profile\.php\?id=\d+', u):
        return 'story_fbid=' in u or 'set=' in u
    # Page slug dengan konten spesifik
    if re.search(r'/[a-z0-9._%-]{3,}/(posts|videos?|photos?|permalink)/\d+', u):
        return True

    return False

def _is_video_url(url: str) -> bool:
    u = (url or "").lower()
    return any(x in u for x in ("/watch", "/reel/", "/reels/", "/videos/", "/video/", "/share/v/"))

def _is_video_item(item: dict) -> bool:
    typ = (item.get("type") or "").lower()
    return typ in ("videos", "video", "reel", "reels", "watch") or _is_video_url(item.get("url", ""))

def _is_search_card_url(url: str) -> bool:
    u = (url or "").lower()
    return "facebook.com/search/" in u and "fb_scrape_card=" in u

def _text_token_overlap(left: str, right: str) -> float:
    def toks(value: str) -> set:
        value = re.sub(r"https?://\S+", " ", (value or "").lower())
        return {
            t for t in re.findall(r"[a-z0-9À-ÿ#]{3,}", value)
            if t not in {"yang", "dan", "atau", "dengan", "untuk", "dari", "pada", "this", "that", "with"}
        }
    a, b = toks(left), toks(right)
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))
def _keyword_in_item(item: dict, keyword: str) -> bool:
    """
    Enhanced keyword matching:
    - Exact substring match (case-insensitive)
    - Fuzzy matching ignoring spaces & dashes ('bemui' matches 'BEM UI', 'bem-ui')
    - Regex word boundary matching for partial keywords
    - Also check 'group_name', 'page_name', 'matched_via' fields
    """
    if not keyword:
        return True
    kw = keyword.lower().strip().lstrip('#')
    kw_nospace = kw.replace(" ", "").replace("-", "").replace("_", "")
    # Synthetic search cards must prove relevance from visible content.
    # Their URL/matched_via contains the search query by construction.
    fields_to_check = [
        (item.get("text","") or item.get("caption","") or "").lower(),
        (item.get("author","") or "").lower(),
        (item.get("group_name","") or "").lower(),
        (item.get("page_name","") or "").lower(),
    ]
    if item.get("source") != "search_post_card":
        fields_to_check.extend([
            (item.get("url","") or "").lower(),
            (item.get("matched_via","") or "").lower(),
        ])
    for field in fields_to_check:
        if not field:
            continue
        # Exact substring match
        if kw in field:
            return True
        # Case-insensitive substring
        if kw in field.lower():
            return True
        # Fuzzy: ignore spaces, dashes, underscores
        if kw_nospace and len(kw_nospace) >= 3:
            field_nospace = field.replace(" ", "").replace("-", "").replace("_", "")
            if kw_nospace in field_nospace:
                return True
        # Regex: match keyword as word boundary (allows partial)
        if len(kw) >= 3:
            import re as _re
            try:
                pattern = _re.compile(_re.escape(kw), _re.IGNORECASE)
                if pattern.search(field):
                    return True
            except Exception:
                pass
    return False

def _hashtag_in_item(item: dict, hashtag: str) -> bool:
    """Match a complete hashtag, avoiding `#demo` matching `#demokrasi`."""
    tag = (hashtag or "").strip().lstrip("#")
    if not tag:
        return True
    text = " ".join(str(item.get(k, "") or "") for k in ("text", "caption", "url"))
    return bool(re.search(rf'(?<![\w#])#{re.escape(tag)}(?!\w)', text, re.IGNORECASE))

def _decode_fb_string(value: str) -> str:
    if not value: return ""
    try:
        value = json.loads(f'"{value}"')
    except Exception:
        value = value.replace("\\/", "/").replace("\\u0025", "%")
    return html.unescape(str(value)).strip()

def _normalize_fb_url(url: str) -> str:
    url = _decode_fb_string(url)
    if not url: return ""
    if url.startswith("/"):
        url = "https://www.facebook.com" + url
    url = url.replace("https://m.facebook.com", "https://www.facebook.com")
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if "facebook.com" in host:
            path = parsed.path or ""
            qs = parse_qs(parsed.query or "")
            story_id = (qs.get("story_fbid") or [""])[0]
            owner_id = (qs.get("id") or [""])[0]
            if story_id:
                return f"https://www.facebook.com/profile.php?story_fbid={story_id}" + (f"&id={owner_id}" if owner_id else "")
            photo_id = (qs.get("fbid") or [""])[0]
            if photo_id and "/photo" in path:
                return f"https://www.facebook.com/photo/?fbid={photo_id}"
            video_id = (qs.get("v") or [""])[0]
            if video_id and "/watch" in path:
                return f"https://www.facebook.com/watch/?v={video_id}"
            m = re.search(r"(/[^/?#]+/videos/(\d+))", path)
            if m:
                return f"https://www.facebook.com{m.group(1)}/"
    except Exception:
        pass
    return url.split("#")[0]

def _fb_content_key(url: str) -> str:
    """Stable key for deduping equivalent FB surfaces, e.g. watch/live vs /videos/id."""
    u = _normalize_fb_url(url or "")
    if not u:
        return ""
    try:
        parsed = urlparse(u)
        path = parsed.path or ""
        qs = parse_qs(parsed.query or "")
        video_id = (qs.get("v") or [""])[0]
        if not video_id:
            m = re.search(r"/(?:videos?|watch|reels?|reel)/(\d+)", path)
            video_id = m.group(1) if m else ""
        if video_id:
            return f"video:{video_id}"
        photo_id = (qs.get("fbid") or [""])[0]
        if photo_id:
            return f"photo:{photo_id}"
        story_id = (qs.get("story_fbid") or [""])[0]
        if story_id:
            return f"story:{story_id}"
    except Exception:
        pass
    return u.split("#")[0].rstrip("/")

def _is_canonical_video_permalink(url: str) -> bool:
    return bool(re.search(r"facebook\.com/[^/?#]+/videos/\d+", url or "", re.I))

def _looks_like_media_url(url: str) -> bool:
    u = (url or "").lower()
    return bool(u) and ("scontent" in u or "fbcdn" in u) and bool(re.search(r'\.(jpg|jpeg|png|webp)(?:\?|$)', u))

def _parse_compact_number(value: str) -> int:
    if value is None:
        return 0
    raw = str(value).lower()
    raw = (raw.replace("\u00a0", " ")
              .replace("\xa0", " ")
              .replace("Â", " ")
              .replace("�", " "))
    m = re.search(r'([\d]+(?:[.,][\d]+)?)(?:\s*(ribu|juta|mio|mn|rb|jt|k|m)(?![a-z]))?', raw, re.I)
    if not m:
        return 0
    try:
        n = float(m.group(1).replace(".", "").replace(",", "."))
    except ValueError:
        return 0
    suffix = (m.group(2) or "").lower()
    if suffix in ("rb", "ribu", "k"):
        n *= 1_000
    elif suffix in ("jt", "juta", "m", "mio", "mn"):
        n *= 1_000_000
    return int(n)

def parse_fb_number(text: str) -> Optional[int]:
    """Parse Facebook compact numbers in Indonesian and English formats."""
    if text is None:
        return None
    raw = str(text).strip().lower()
    raw = (raw.replace("\u00a0", " ")
              .replace("\xa0", " ")
              .replace("Ã‚", " ")
              .replace("ï¿½", " "))
    raw = raw.replace("Â", " ").replace("Ã‚", " ").replace("â€¦", " ")
    m = re.search(r'(\d+(?:[.,]\d+)?|\d{1,3}(?:[.,]\d{3})+)\s*(ribu|juta|mio|mn|rb|jt|k|m)?(?![a-z])', raw, re.I)
    if not m:
        return None
    num = m.group(1)
    suffix = (m.group(2) or "").lower()
    try:
        if suffix:
            n = float(num.replace(",", "."))
        else:
            n = float(num.replace(".", "").replace(",", ""))
    except ValueError:
        return None
    if suffix in ("rb", "ribu", "k"):
        n *= 1_000
    elif suffix in ("jt", "juta", "m", "mio", "mn"):
        n *= 1_000_000
    return int(n)

def extract_reel_footer_metrics_from_text(text: str) -> dict:
    """
    Facebook Reels detail pages often expose unlabeled engagement counts as:
    Publik / <likes> / <comments> / <shares> / Reels.
    Only parse that tight footer block so caption numbers are ignored.
    """
    result = {
        "likes_count": None,
        "comments_count": None,
        "shares_count": None,
        "views_count": None,
        "matched_patterns": {},
    }
    raw = (text or "").replace("\u00a0", " ").replace("\xa0", " ").replace("Â", " ").replace("Ã‚", " ")
    lines = [re.sub(r"\s+", " ", line).strip() for line in raw.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return result

    numeric_re = re.compile(r'^\d+(?:[.,]\d+)?\s*(?:ribu|juta|mio|mn|rb|jt|k|m)?$', re.I)
    reel_indexes = [idx for idx, line in enumerate(lines) if line.lower() in {"reels", "reel"}]
    for reel_idx in reversed(reel_indexes):
        start = max(0, reel_idx - 10)
        window = lines[start:reel_idx]
        public_positions = [i for i, line in enumerate(window) if line.lower() in {"publik", "public"}]
        if public_positions:
            window = window[public_positions[-1] + 1:]
        values = []
        value_lines = []
        for line in window:
            clean_line = re.sub(r"[^\d.,a-zA-Z ]+", " ", line).strip()
            if not numeric_re.match(clean_line):
                continue
            value = parse_fb_number(clean_line)
            if value is None:
                continue
            values.append(value)
            value_lines.append(clean_line)
        if not values:
            continue
        # Reels footer order follows the visible action row: reactions, comments, shares.
        for field, value, source_line in zip(("likes_count", "comments_count", "shares_count"), values[:3], value_lines[:3]):
            result[field] = value
            result["matched_patterns"][field] = f"reel_footer:{source_line}"
        return result
    return result

def extract_video_metrics_from_text(text: str) -> dict:
    """Extract video metrics only when a number has nearby metric words."""
    text = re.sub(r"\s+", " ", (text or "").replace("\u00a0", " ")).strip()
    result = {
        "views": None,
        "likes": None,
        "comments": None,
        "shares": None,
        "matched_patterns": {},
    }
    num = r'(\d+(?:[.,]\d+)?|\d{1,3}(?:[.,]\d{3})+)\s*(ribu|juta|mio|mn|rb|jt|k|m)?(?![a-z])'
    specs = {
        "views": [
            rf'{num}\s*(?:tayangan|views?|ditonton|viewed)\b',
            rf'(?:tayangan|views?|ditonton|viewed)\s*[:\-]\s*{num}',
        ],
        "likes": [
            rf'{num}\s*(?:suka|likes?|reaksi|reactions?)\b',
            rf'(?:suka|likes?|reaksi|reactions?)\s*[:\-]\s*{num}',
        ],
        "comments": [
            rf'{num}\s*(?:komentar|comments?)\b',
            rf'(?:komentar|comments?)\s*[:\-]\s*{num}',
        ],
        "shares": [
            rf'{num}\s*(?:kali\s+dibagikan|x\s+dibagikan|dibagikan|shares?)\b',
            rf'(?:dibagikan|shares?)\s*[:\-]\s*{num}',
        ],
    }
    for field, patterns in specs.items():
        for pat in patterns:
            for m in re.finditer(pat, text, re.I):
                before = text[max(0, m.start() - 32):m.start()]
                if re.search(r'(tayangan|views?|ditonton|viewed|komentar|comments?|suka|likes?|reaksi|reactions?|dibagikan|shares?)\s*[:\-]\s*$', before, re.I):
                    continue
                value = parse_fb_number(" ".join(part for part in m.groups()[:2] if part))
                if value is None:
                    continue
                if result[field] is None or value > result[field]:
                    result[field] = value
                    result["matched_patterns"][field] = m.group(0)[:160]
    return result

class FacebookKeywordMonitor:
    def __init__(self):
        print(Fore.CYAN+"\n[FB] v5.3...")
        self.context=None; self.page=None; self.playwright=None
        self._gql: List[Dict]=[]; self._gql_urls: Set[int]=set()
        self._page_id_map: Dict[str,str]={}
        self._current_gql_session: str=""
        self._has_cookie=False; self._uid=None; self._warmed_up=False
        try:
            from fb_cookie_injector import has_valid_session, get_session_info
            self._has_cookie=has_valid_session()
            if self._has_cookie: self._uid=get_session_info().get("user_id","N/A"); print(Fore.GREEN+"[OK] Cookie FB | ID:"+str(self._uid))
            else: print(Fore.RED+"[FAIL] Session FB tidak valid!")
        except: print(Fore.YELLOW+"[WARN] fb_cookie_injector tidak ditemukan")

    def __enter__(self): return self
    def __exit__(self,*_): self.close()
    @property
    def pg(self):
        if self.page is None: raise RuntimeError("Browser belum diinisialisasi.")
        return self.page
    @property
    def ctx(self):
        if self.context is None: raise RuntimeError("Browser belum diinisialisasi.")
        return self.context

    def _new_page(self):
        p=self.ctx.new_page()
        try:
            p.set_default_timeout(15000)
            p.set_default_navigation_timeout(22000)
        except Exception:
            pass
        p.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                          "window.chrome={runtime:{},csi:function(){return{}},loadTimes:function(){return{}}};"
                          "Object.defineProperty(navigator,'languages',{get:()=>['id-ID','id','en-US','en']});"
                          "Object.defineProperty(navigator,'platform',{get:()=>'Win32'});")
        return p

    def _install_resource_blocking(self, context: BrowserContext):
        if not FB_BLOCK_HEAVY_RESOURCES:
            return
        def block_heavy(route):
            try:
                req = route.request
                resource_type = req.resource_type
                url = req.url.lower()
                if resource_type in ("image", "media", "font"):
                    route.abort()
                    return
                if any(x in url for x in [
                    "/ajax/bz", "/logging/", "/analytics", "/tr/?", "doubleclick",
                    "google-analytics", "facebook.com/impression.php",
                ]):
                    route.abort()
                    return
                route.continue_()
            except Exception:
                try:
                    route.continue_()
                except Exception:
                    pass
        try:
            context.route("**/*", block_heavy)
        except Exception:
            pass

    def _setup_gql(self, page: Page):
        sid = str(uuid.uuid4())[:8]
        page_gql = []
        page_urls = set()
        def handler(resp):
            try:
                u=resp.url
                if any(x in u for x in ["/api/graphql","/api/v","/search","/relay"]):
                    if resp.status==200:
                        ct=resp.headers.get("content-type","") or ""
                        if any(x in ct for x in ["application/json","text/javascript"]):
                            uh=hash(u.split("?")[0]+str(time.time())[:6])
                            if uh not in page_urls:
                                try: page_gql.append({"url":u,"data":resp.json(),"timestamp":time.time()}); page_urls.add(uh)
                                except: pass
            except: pass
        page.on("response", handler)
        return sid, page_gql, page_urls

    def _build_context(self):
        self.playwright=sync_playwright().start()
        context=self.playwright.chromium.launch_persistent_context(
            os.path.join(os.getcwd(),"fb_chrome_real_profile"),**browser_channel_kwargs(),headless=HEADLESS,
            args=["--window-size=1920,1080","--disable-blink-features=AutomationControlled","--disable-notifications","--mute-audio"],
            no_viewport=True,user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
            locale="id-ID",timezone_id="Asia/Jakarta",bypass_csp=True)
        def _apply(p): p.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});")
        context.on("page",_apply)
        self._install_resource_blocking(context)
        return context

    def _is_logged_in(self):
        try:
            c=self.ctx.cookies("https://www.facebook.com")
            cu=next((x for x in c if x.get("name")=="c_user"),None)
            xs=next((x for x in c if x.get("name")=="xs"),None)
            if cu and cu.get("value") and xs and xs.get("value"):
                print(Fore.GREEN+f"     [OK] Logged in as: {cu.get('value')}"); return True
            return False
        except: return False

    def initialize_browser(self):
        if self.context: return
        print(Fore.CYAN+"\n[FB] Menjalankan browser background...")
        self.context=self._build_context()
        self.page=self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        try:
            from fb_cookie_injector import inject_cookies_sync
            if self._has_cookie:
                try:
                    self.ctx.clear_cookies()
                except Exception:
                    pass
                inject_cookies_sync(self.ctx); print(Fore.GREEN+"   [OK] Cookies diinject")
        except: pass
        self._current_gql_session, self._gql, self._gql_urls = self._setup_gql(self.pg)
        print(Fore.CYAN+"   [..] Membuka homepage...")
        self.pg.goto("https://www.facebook.com/",wait_until="domcontentloaded",timeout=30000)
        time.sleep(FB_HOME_LOAD_SECONDS)
        cu=self.pg.url
        if "login" in cu or "checkpoint" in cu: print(Fore.RED+"   [FAIL] Redirect login!");self.close();raise Exception("FB session expired")
        if not self._is_logged_in(): print(Fore.RED+"   [FAIL] Belum login!");self.close();raise Exception("FB not logged in")
        self._warmup_browser(FB_WARMUP_SECONDS);self._warmed_up=True
        print(Fore.GREEN+"[OK] Browser siap (LOGGED IN)")

    def close(self):
        try:
            if self.context: self.context.close()
            if self.playwright: self.playwright.stop()
        except: pass
        self.context = None
        self.page = None
        self.playwright = None
        self._warmed_up = False

    def _clean_keyword(self,raw): return re.sub(r'site:\s*facebook\s*:\s*','',raw,flags=re.IGNORECASE).strip()
    def _warmup_browser(self,s=10):
        if self._warmed_up: return
        print(Fore.YELLOW+f"\n   [WARMUP] {s}s...")
        if s <= 0:
            return
        rounds = 1 if s <= 4 else 2
        delay = min(1.0, max(0.2, s / max(3, rounds * 3)))
        for _ in range(rounds):
            self.pg.evaluate(f"window.scrollBy(0,{random.randint(300,800)})")
            time.sleep(delay)
        self.pg.evaluate("window.scrollTo(0,0)")
        time.sleep(min(0.8, delay))
    def _close_popups(self,page=None):
        p=page or self.pg
        try: p.evaluate("()=>{document.querySelectorAll('[aria-label=\"Tutup\"],[aria-label=\"Close\"]').forEach(b=>{if(b.offsetParent!==null)b.click()})}");time.sleep(0.5)
        except: pass

    def _source_metric_label(self, source: str) -> str:
        source = (source or "").lower()
        if source == "html_embedded":
            return "html_fallback"
        if source in ("dom", "generic", "generic_article", "search_post_card", "page_feed"):
            return "search_only"
        if source == "graphql":
            return "graphql_search"
        return source or "unknown"

    def _prepare_item_metrics(self, item: dict) -> dict:
        if not item:
            return item
        source_label = self._source_metric_label(item.get("source", ""))
        item.setdefault("metrics_error", None)
        if _is_video_item(item):
            if item.get("metrics_valid") is True:
                item.setdefault("metric_source", item.get("metric_source") or source_label)
                item.setdefault("detail_status", item.get("detail_status") or "ok")
                return item
            item["metrics_valid"] = False
            item["metric_source"] = source_label
            item["detail_status"] = item.get("detail_status") or "pending_detail"
            item["metrics_unverified"] = True
            for key in ("likes_count", "comments_count", "views_count", "shares_count"):
                item[key] = None
        else:
            item.setdefault("metrics_valid", True)
            item.setdefault("metric_source", source_label)
            item.setdefault("detail_status", "not_required")
        item["engagement_score"] = _engagement_score(item)
        assign_viral_fields(item)
        return item

    # ======================================================================
    #  GRAPHQL EXTRACTION
    # ======================================================================
    def _extract_gql(self, gql_data: List[Dict], keyword="", strict=True):
        results=[]; seen_urls=set()
        for rd in gql_data:
            try:
                for item in self._recursive_extract(rd.get("data",{}),keyword,strict):
                    key = _fb_content_key(item.get("url", "")) or item.get("url", "")
                    if item.get("url","") and key not in seen_urls:
                        seen_urls.add(key); results.append(item)
            except: continue
        return results

    def _recursive_extract(self,data,keyword,depth=0,strict=True):
        if depth>20 or not isinstance(data,(dict,list)): return []
        results=[]
        if isinstance(data,dict):
            for key in ["story","creation_story","node","post","mediaset","search_results","edges","node_results","results",
                       "search_results_connection","units","unit","relay_rendering_strategy","data"]:
                if key in data:
                    v=data[key]
                    if isinstance(v,dict):
                        e=self._extract_node(v,keyword,strict)
                        if e: results.append(e)
                    elif isinstance(v,list):
                        for item in v:
                            if isinstance(item,dict):
                                e=self._extract_node(item,keyword,strict)
                                if e: results.append(e)
            for v in data.values():
                if isinstance(v,(dict,list)): results.extend(self._recursive_extract(v,keyword,depth+1,strict))
        elif isinstance(data,list):
            for item in data:
                if isinstance(item,(dict,list)): results.extend(self._recursive_extract(item,keyword,depth+1,strict))
        return results

    def _extract_node(self,node,keyword,strict=True):
        try:
            url=""
            for k in ["url","permalink","short_code","wwwURL","story_url"]:
                if k in node and node[k]: url=node[k]; break
            if not url:
                sc=node.get("shortcode") or (node.get("feedback") or {}).get("shortcode") or ""
                if sc: url=f"https://www.facebook.com/{sc}"
                else: return None
            url=_normalize_fb_url(url)
            if not _is_valid_result_url(url): return None
            msgd=node.get("message") or {}
            text=msgd.get("text","") if isinstance(msgd,dict) else (str(msgd) if msgd else "")
            actors=node.get("actors") or []
            author=(actors[0].get("name","") if actors and isinstance(actors,list) and len(actors)>0 and isinstance(actors[0],dict) else "")
            if keyword:
                kw=keyword.lower().lstrip('#')
                fi_t=kw in text.lower() if text else False
                fi_a=kw in author.lower()
                fi_u=kw in url.lower()
                if strict and not(fi_t or fi_a or fi_u): return None
            fb = node.get("feedback") or {}

            # Likes — coba reactors atau reaction_count
            likes = 0
            if isinstance(fb, dict):
                reactors = fb.get("reactors") or fb.get("reaction_count") or {}
                if isinstance(reactors, dict):
                    likes = int(reactors.get("count", 0) or 0)
                elif isinstance(reactors, int):
                    likes = reactors

            # Comments
            comments = 0
            if isinstance(fb, dict):
                for ckey in ["comment_rendering_instance", "top_level_comments", "comments"]:
                    cval = fb.get(ckey) or {}
                    if isinstance(cval, dict):
                        comments = int(cval.get("count", 0) or 0)
                        if comments > 0:
                            break

            # Shares — cek berbagai key GQL yang digunakan FB
            shares = 0
            if isinstance(fb, dict):
                # Coba semua key shares yang diketahui
                for share_key in ["share_count", "reshare_count", "shares", "reshares"]:
                    share_obj = fb.get(share_key)
                    if share_obj is None:
                        continue
                    if isinstance(share_obj, dict):
                        v = int(share_obj.get("count", 0) or 0)
                        if v > 0:
                            shares = v
                            break
                    elif isinstance(share_obj, int) and share_obj > 0:
                        shares = share_obj
                        break
            if shares == 0:
                # Fallback ke node level langsung
                for k in ["share_count", "reshare_count", "shares_count"]:
                    v = node.get(k)
                    if v:
                        shares = int(v or 0)
                        if shares > 0:
                            break

            # Views (video)
            views = 0
            for vkey in ["video_view_count", "play_count", "view_count"]:
                v = node.get(vkey) or (fb.get(vkey) if isinstance(fb, dict) else None)
                if v:
                    views = int(v or 0)
                    break

            ct = node.get("created_time") or node.get("publish_time") or node.get("creation_time") or 0
            ts = datetime.fromtimestamp(int(ct)).isoformat() if ct else ""
            pt="posts"
            if "/reel/" in url or "/reels/" in url: pt="videos"
            elif "/videos/" in url or "/watch" in url or "/video/" in url: pt="videos"
            elif "/groups/" in url: pt="groups"
            elif "/pages/" in url or "/profile.php" in url: pt="pages"
            media_urls=self._find_media_urls(node)
            page_name = actors[0].get("name","") if actors and isinstance(actors,list) and len(actors)>0 and isinstance(actors[0],dict) else ""
            item = {"url":url,"author":author,"text":text[:1000],"caption":text[:1000],"timestamp":ts,"type":pt,
                    "likes_count":likes,"comments_count":comments,"views_count":views,"shares_count":shares,
                    "images":media_urls,"media_urls":media_urls,"media_count":len(media_urls),
                    "page_name":page_name,
                    "engagement_score":likes+comments*2+views,"source":"graphql"}
            return self._prepare_item_metrics(item)
        except: return None

    def _find_media_urls(self, data, depth=0):
        if depth > 12 or not isinstance(data, (dict, list)): return []
        found=[]
        if isinstance(data, dict):
            for k, v in data.items():
                if isinstance(v, str):
                    val=_normalize_fb_url(v)
                    if _looks_like_media_url(val) and val not in found:
                        found.append(val)
                elif isinstance(v, (dict, list)):
                    for item in self._find_media_urls(v, depth+1):
                        if item not in found: found.append(item)
        else:
            for v in data:
                if isinstance(v, (dict, list, str)):
                    if isinstance(v, str):
                        val=_normalize_fb_url(v)
                        if _looks_like_media_url(val) and val not in found:
                            found.append(val)
                    else:
                        for item in self._find_media_urls(v, depth+1):
                            if item not in found: found.append(item)
        return found[:8]

    def _extract_embedded_html(self, page, max_items=100, keyword="", search_type="posts"):
        """
        Fallback extraction dari HTML mentah halaman FB.
        """
        html_text = page.content()
        results = []; seen = set()

        url_patterns = [
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*(?:facebook\.com)?/watch/?\?v=\d+[^"]*)"',
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*(?:facebook\.com)?/photo/?\?fbid=\d+[^"]*)"',
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*(?:facebook\.com)?/(?:posts|permalink)/(?:\d+|pfbid[a-zA-Z0-9_-]+)[^"]*)"',
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*(?:facebook\.com)?/(?:videos?|reels?)/\d+[^"]*)"',
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*(?:facebook\.com)?/groups/[^/]+/(?:posts|permalink)/\d+[^"]*)"',
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*story_fbid=\d+[^"]*)"',
            # ✅ FIX: format share baru FB
            r'"(?:wwwURL|url)"\s*:\s*"([^"]*(?:facebook\.com)?/share/(?:p|v|r)/[a-zA-Z0-9_-]+[^"]*)"',
            r'href="([^"]*(?:/watch/?\?v=|/photo/?\?fbid=|/(?:posts|permalink|videos?|reels?)/\d+|/groups/[^/]+/posts/\d+|story_fbid=|/share/(?:p|v|r)/)[^"]*)"',
        ]

        candidates = []
        for pat in url_patterns:
            for m in re.finditer(pat, html_text, flags=re.I):
                candidates.append((m.start(), m.group(1)))
        candidates.sort(key=lambda x: x[0])

        for pos, raw_url in candidates:
            if len(results) >= max_items:
                break

            url = _normalize_fb_url(raw_url)
            content_key = _fb_content_key(url) or url
            if not url or content_key in seen:
                continue

            if not _is_valid_result_url(url):
                continue

            seen.add(content_key)

            window = html_text[max(0, pos - 8000):pos + 10000]

            page_name = ""
            name_matches = re.findall(r'"name"\s*:\s*"([^"]{2,100})"', window)
            for nm in name_matches:
                nm_clean = _decode_fb_string(nm)
                low = nm_clean.lower()
                if (nm_clean and len(nm_clean) > 2
                        and not nm_clean.startswith("http")
                        and not any(x in low for x in [
                            "facebook", "watch", "reels", "video", "photo",
                            "lihat selengkapnya", "see more", "komentar",
                            "suka", "bagikan",
                        ])):
                    page_name = nm_clean
                    break

            media = []
            for im in re.findall(
                r'https?:\\/\\/(?:[^"\\]|\\.)*?(?:scontent|fbcdn)(?:[^"\\]|\\.)*?\.(?:jpg|jpeg|png|webp)(?:\?[^"\\]*)?',
                window, flags=re.I
            ):
                src = _normalize_fb_url(im)
                if _looks_like_media_url(src) and src not in media:
                    media.append(src)
            if not media:
                for im in re.findall(r'src="([^"]+(?:scontent|fbcdn)[^"]+)"', window, flags=re.I):
                    src = _normalize_fb_url(im)
                    if _looks_like_media_url(src) and src not in media:
                        media.append(src)

            texts = []
            for t in re.findall(r'"text"\s*:\s*"([^"]{8,2000})"', window):
                clean = _decode_fb_string(t)
                low = clean.lower()
                if clean and clean not in texts and len(clean) > 8 and not any(x in low for x in [
                    "lihat selengkapnya", "lihat semua", "lihat balasan",
                    "see more", "facebook watch", "watch video",
                ]):
                    texts.append(clean)

            # ✅ FIX: juga cek "message", "title", "description", "story" fields untuk video/reel
            for field in ["message", "title", "description", "story", "body_text"]:
                for t in re.findall(rf'"{field}"\s*:\s*\{{"text"\s*:\s*"([^"]+)"', window):
                    clean = _decode_fb_string(t)
                    if clean and len(clean) > 8 and clean not in texts:
                        texts.insert(0, clean)  # prioritaskan
                for t in re.findall(rf'"{field}"\s*:\s*"([^"{{][^"]{8,2000})"', window):
                    clean = _decode_fb_string(t)
                    if clean and len(clean) > 8 and clean not in texts:
                        texts.append(clean)

            if keyword:
                kw_lower = keyword.lower().lstrip("#").strip()
                caption = next((t for t in texts if kw_lower in t.lower()), texts[0] if texts else "")
            else:
                caption = max(texts, key=len) if texts else ""

            author = page_name
            if not author:
                names = [_decode_fb_string(n) for n in re.findall(r'"name"\s*:\s*"([^"]{2,120})"', window)]
                for n in names:
                    if (n and not n.lower().startswith("http")
                            and not any(x in n.lower() for x in ["facebook", "watch", "reel"])
                            and len(n) > 2):
                        author = n
                        break

            visible = re.sub(r'<[^>]+>', ' ', window)
            visible = html.unescape(visible)

            u_lower = url.lower()
            if "/reel/" in u_lower or "/reels/" in u_lower:
                pt = "videos"
            elif "/videos/" in u_lower or "/watch" in u_lower or "/video/" in u_lower:
                pt = "videos"
            elif "/groups/" in u_lower:
                pt = "groups"
            elif search_type == "pages":
                pt = "pages"
            else:
                pt = "posts"

            if pt == "videos":
                # Embedded HTML often contains metrics for nearby/other videos.
                # Keep video metrics empty unless DOM/detail extraction can prove them.
                likes = comments = views = shares = 0
                metrics_unverified = True
            else:
                likes    = self._extract_metric_from_text(visible, ["suka", "likes", "reaksi", "reaction"])
                comments = self._extract_metric_from_text(visible, ["komentar", "comments", "comment"])
                views    = self._extract_metric_from_text(visible, ["tayangan", "views", "ditonton", "viewed"])
                shares   = self._extract_metric_from_text(visible, ["dibagikan", "shares", "share", "bagikan"])
                metrics_unverified = False

            item = {
                "url":              url,
                "author":           author or "Unknown",
                "page_name":        page_name,
                "text":             caption[:1000],
                "caption":          caption[:1000],
                "timestamp":        "",
                "type":             pt,
                "likes_count":      likes,
                "comments_count":   comments,
                "views_count":      views,
                "shares_count":     shares,
                "images":           media[:6],
                "media_urls":       media[:6],
                "media_count":      len(media[:6]),
                "engagement_score": likes + comments * 2 + shares * 3 + views * 0.1,
                "source":           "html_embedded",
                "metrics_unverified": metrics_unverified,
            }
            self._prepare_item_metrics(item)

            if keyword and not _keyword_in_item(item, keyword):
                continue

            results.append(item)

        if results:
            print(Fore.GREEN + f"   [HTML-FALLBACK] {len(results)} items (shares+page_name fixed)")

        return results[:max_items]

    def _extract_metric_from_text(self, text, labels):
        """
        Extract angka engagement dari teks bebas.
        """
        text = (text or "").lower()
        text = (text.replace("\u00a0", " ")
                    .replace("\xa0", " ")
                    .replace("Â", " ")
                    .replace("�", " "))
        label_pat = "|".join(re.escape(x.lower()) for x in labels)

        def _parse(num_str, suffix):
            return _parse_compact_number(f"{num_str or ''} {suffix or ''}")

        SFX = r"(rb|ribu|k|jt|juta|m|mio|mn)?"

        # Pola khusus untuk shares: "N kali dibagikan" / "dibagikan N kali"
        if any(x in labels for x in ["dibagikan", "shares", "share", "bagikan"]):
            special_patterns = [
                r'([\d.,]+)\s*' + SFX + r'\s*kali\s+dibagikan',
                r'dibagikan\s+([\d.,]+)\s*' + SFX + r'\s*kali',
                r'([\d.,]+)\s*' + SFX + r'\s*x\s+dibagikan',
            ]
            for pat in special_patterns:
                m = re.search(pat, text, re.I)
                if m:
                    val = _parse(m.group(1), m.group(2) or "")
                    if val > 0: return val

        m = re.search(rf'([\d.,]+)\s*{SFX}\s*(?:{label_pat})', text, re.I)
        if m:
            val = _parse(m.group(1), m.group(2) or "")
            if val > 0: return val

        m = re.search(rf'(?:{label_pat})\s*[:\-]?\s*([\d.,]+)\s*{SFX}', text, re.I)
        if m:
            val = _parse(m.group(1), m.group(2) or "")
            if val > 0: return val

        m = re.search(rf'([\d.,]+)\s*{SFX}\s*[·•]\s*(?:{label_pat})', text, re.I)
        if m:
            val = _parse(m.group(1), m.group(2) or "")
            if val > 0: return val

        m = re.search(rf'(?:{label_pat})\s*[·•]\s*([\d.,]+)\s*{SFX}', text, re.I)
        if m:
            val = _parse(m.group(1), m.group(2) or "")
            if val > 0: return val

        return 0

    # ======================================================================
    #  FEED EXTRACTION
    # ======================================================================
    def _extract_feed(self, page, max_items=100, keyword=""):
        results=[]; seen_urls=set(); stable=0
        mx=max(4, min(FB_FEED_MAX_ROUNDS, math.ceil(max_items / 6) + 4))
        ms=4
        has_feed=False
        for _ in range(max(1, FB_FEED_WAIT_ROUNDS)):
            try:
                c=page.evaluate("""() => {
                    // ✅ FIX: cek berbagai selector feed FB (struktur berubah berkala)
                    const posinset = document.querySelectorAll('[role="feed"] [aria-posinset]').length;
                    const articles = document.querySelectorAll('[role="feed"] [role="article"]').length;
                    const feedDivs = document.querySelectorAll('[role="feed"]>div').length;
                    return Math.max(posinset, articles, feedDivs);
                }""")
                if c>0: print(Fore.GREEN+f"   [FEED] {c} items found"); has_feed=True; break
            except: pass
            time.sleep(0.5)
        if not has_feed:
            # ✅ FIX: Cek apakah ada artikel meski tidak ada feed element
            try:
                art_count = page.evaluate("document.querySelectorAll('[role=\"article\"]').length")
                if art_count > 0:
                    print(Fore.YELLOW+f"   [FEED] No [role=feed] tapi ada {art_count} articles, pakai article-based extraction...")
                    has_feed = True
            except: pass
        if not has_feed:
            print(Fore.YELLOW+"   [FEED] No feed element found, trying generic extraction...")
            return self._extract_generic(page, max_items, "posts", keyword)

        _JS_FEED = r"""
        (maxItems) => {
            const r=[], s=new Set();
            const parseNum=(text)=>{
                const m=(text||'').toLowerCase().replace(/\u00a0/g,' ').match(/([\d.,]+)\s*(rb|ribu|k|jt|juta|m|mio)?/i);
                if(!m)return 0;
                let n=parseFloat(m[1].replace(/\./g,'').replace(',','.'));
                const sf=(m[2]||'').toLowerCase();
                if(sf==='k'||sf==='rb'||sf==='ribu')n*=1000;
                else if(sf==='m'||sf==='jt'||sf==='juta'||sf==='mio')n*=1000000;
                return Math.floor(n)||0;
            };
            const clean=(text)=>(text||'')
                .replace(/\u00a0|\xa0|Ã‚|ï¿½/g,' ')
                .replace(/Facebook(?:\s+Facebook)+/gi,' ')
                .replace(/Indikator status online Aktif/gi,' ')
                .replace(/\bIkuti\b/gi,' ')
                .replace(/\bLihat selengkapnya\b/gi,' ')
                .replace(/\s+/g,' ')
                .trim();
            const cleanCaption=(text)=>{
                let t=clean(text);
                t=t.replace(/\b[otdSnpersihualgc0-9.]\s(?:[otdSnpersihualgc0-9.]\s){18,}[A-Za-z0-9.]\b/g,' ');
                t=t.replace(/\b(?:\d{1,2}:\d{2}\s*\/\s*\d{1,2}:\d{2}(?::\d{2})?)\b/g,' ');
                t=t.replace(/\s+/g,' ').trim();
                return t;
            };
            const hashText=(text)=>{
                let h=2166136261;
                for(const ch of (text||'')){
                    h^=ch.charCodeAt(0);
                    h=Math.imul(h,16777619);
                }
                return (h>>>0).toString(36);
            };
            const isSpecificFbUrl=(url)=>{
                const u=(url||'').toLowerCase();
                return /\/share\/(p|v|r)\//.test(u)
                    || (/\/watch/.test(u)&&/[?&]v=\d+/.test(u))
                    || /\/groups\/[^/]+\/(posts|permalink)\/\d+/.test(u)
                    || /\/(posts|permalink)\/(?:\d+|pfbid)/.test(u)
                    || /\/(videos?|reels?)\/\d+/.test(u)
                    || /\/photo\/?\?fbid=\d+/.test(u)
                    || /\/(photo|photos)\/\d+/.test(u)
                    || /story_fbid=\d+/.test(u);
            };
            const pageQuery=()=>{
                try{return new URLSearchParams(location.search||'').get('q')||'';}catch(e){return '';}
            };
            const pickAuthorUrl=(links)=>{
                for(const a of links){
                    const h=a.getAttribute('href')||'';
                    if(!h||h.includes('/stories/')||h.includes('/login')||h.includes('/help'))continue;
                    if(/facebook\.com\/[a-zA-Z0-9._-]{3,}/.test(h)||/profile\.php\?id=\d+/.test(h))return normalize(h);
                }
                return '';
            };
            const cleanAuthor=(text)=>{
                const t=clean(text).slice(0,100);
                if(!t||t.length<2||/https?:\/\//i.test(t)||/^m\.me$/i.test(t))return '';
                if(/^[A-Za-z0-9]{6,}\.com$/i.test(t)&&!/(kompas|tempo|detik|cnn|tribun|kumparan|liputan|antara|media|presisi|sumbar|balad)/i.test(t))return '';
                if(/^[A-Za-z0-9]{10,}$/i.test(t))return '';
                return t;
            };
            const pickAuthorName=(links)=>{
                for(const a of links){
                    const h=a.getAttribute('href')||'';
                    if(!h||h.includes('/stories/')||h.includes('l.facebook.com')||h.includes('m.me')||h.includes('/help')||h.includes('/login'))continue;
                    if(!(/facebook\.com\/[a-zA-Z0-9._-]{3,}/.test(h)||/profile\.php\?id=\d+/.test(h)))continue;
                    const name=cleanAuthor(a.innerText||a.getAttribute('aria-label')||'');
                    if(name)return name;
                }
                return '';
            };
            const extractLooseMetrics=(text)=>{
                const matches=[];
                const re=/(^|[\s·•])([\d.,]+)\s*(rb|ribu|k|jt|juta|m|mio)?(?=\s|$)/ig;
                let m;
                while((m=re.exec(text||''))){
                    const raw=(m[2]||'')+(m[3]?' '+m[3]:'');
                    const value=parseNum(raw);
                    if(!value)continue;
                    if(value>=1900&&value<=2100)continue;
                    matches.push({raw,value});
                }
                return matches;
            };
            const extractImages=(node)=>{
                const imgs=[];
                node.querySelectorAll('img[src*="scontent"],img[src*="fbcdn"]').forEach(im=>{
                    const src=im.getAttribute('src')||'';
                    const w=im.naturalWidth||im.width||0;
                    const h=im.naturalHeight||im.height||0;
                    if(src&&!imgs.includes(src)&&(w===0||w>=120)&&(h===0||h>=80))imgs.push(src);
                });
                return imgs.slice(0,6);
            };
            const normalize=(href)=>{
                if(!href)return '';
                let raw=href;
                if(raw.startsWith('http')){
                    try{
                        const u=new URL(raw);
                        raw=u.pathname+u.search;
                    }catch(e){}
                }
                if(!raw.startsWith('/'))raw='/'+raw;
                if(raw.includes('/stories/'))return '';
                // ✅ FIX: support format share baru FB
                if(/\/share\/(p|v|r)\/([A-Za-z0-9_-]+)/.test(raw)){
                    return 'https://www.facebook.com'+raw.split('#')[0];
                }
                if(raw.includes('/watch/')&&raw.includes('v=')){
                    const m=raw.match(/[?&]v=(\d+)/);
                    if(m)return 'https://www.facebook.com/watch/?v='+m[1];
                }
                if((raw.includes('/photo/')||raw.includes('/photo?'))&&raw.includes('fbid=')){
                    const m=raw.match(/[?&]fbid=(\d+)/);
                    if(m)return 'https://www.facebook.com/photo/?fbid='+m[1];
                }
                if(/profile\.php\?id=\d+/.test(raw)){
                    const m=raw.match(/id=(\d+)/);
                    if(m)return 'https://www.facebook.com/profile.php?id='+m[1];
                }
                if(raw.includes('story_fbid=')){
                    const m=raw.match(/story_fbid=(\d+)/);
                    if(m)return 'https://www.facebook.com/profile.php?story_fbid='+m[1];
                }
                raw=raw.split('#')[0].split('?')[0];
                return 'https://www.facebook.com'+raw;
            };
            const pickContentUrl=(links)=>{
                let best=null,bestScore=-1;
                for(const a of links){
                    const h=a.getAttribute('href')||'';
                    if(!h||h.includes('/stories/'))continue;
                    let score=-1;
                    if(/\/groups\/[^/]+\/(posts|permalink)\/\d+/.test(h))score=60;
                    else if(/\/(posts|permalink)\/(?:\d+|pfbid[A-Za-z0-9_-]+)/.test(h))score=55;
                    else if((h.includes('/photo/')||h.includes('/photo?'))&&h.includes('fbid='))score=50;
                    else if(/\/(photo|photos)\/\d+/.test(h))score=45;
                    // ✅ FIX: tambah format share baru FB
                    else if(/\/share\/(p|v|r)\/[A-Za-z0-9_-]+/.test(h))score=48;
                    else if(/profile\.php\?id=\d+/.test(h))score=-1;
                    else if(/facebook\.com\/[a-zA-Z0-9._-]{3,}\/?(?:[?#].*)?$/.test(h))score=-1;
                    else if(/\/(reel|reels|videos|video)\/\d+/.test(h)||h.includes('/watch/?v='))score=20;
                    else if(h.includes('facebook.com')&&!/\/(login|help|privacy|legal)/.test(h))score=-1;
                    if(score>bestScore){
                        const u=normalize(h);
                        if(u){best=u;bestScore=score;}
                    }
                }
                return best||'';
            };
            const recoverContentUrl=(node)=>{
                const html=(node?.outerHTML||'').replace(/&amp;/g,'&').replace(/\\\//g,'/').replace(/\u0025/g,'%');
                const patterns=[
                    /https?:\/\/www\.facebook\.com\/groups\/[^"'<>\s]+\/(?:posts|permalink)\/\d+/i,
                    /https?:\/\/www\.facebook\.com\/[^"'<>\s]+\/(?:posts|permalink)\/(?:\d+|pfbid[A-Za-z0-9_-]+)/i,
                    /https?:\/\/www\.facebook\.com\/photo\/?\?fbid=\d+/i,
                    /https?:\/\/www\.facebook\.com\/share\/(?:p|v|r)\/[A-Za-z0-9_-]+/i,
                    /\/groups\/[^"'<>\s]+\/(?:posts|permalink)\/\d+/i,
                    /\/[^"'<>\s]+\/(?:posts|permalink)\/(?:\d+|pfbid[A-Za-z0-9_-]+)/i,
                    /\/photo\/?\?fbid=\d+/i,
                    /\/share\/(?:p|v|r)\/[A-Za-z0-9_-]+/i,
                    /\/watch\/?\?v=\d+/i,
                    /\/(?:reel|reels|videos|video)\/\d+/i,
                ];
                for(const pat of patterns){
                    const m=html.match(pat);
                    if(m){
                        const u=normalize(m[0]);
                        if(u&&isSpecificFbUrl(u))return u;
                    }
                }
                const story=html.match(/story_fbid["'=:%&;\\]+(\d{8,})/i);
                if(story){
                    const owner=html.match(/(?:actorID|actor_id|ownerID|owner_id|profile_id|__user|id)["'=:%&;\\]+(\d{6,})/i);
                    return 'https://www.facebook.com/profile.php?story_fbid='+story[1]+(owner?'&id='+owner[1]:'');
                }
                return '';
            };            // ✅ FIX: selector lebih luas — cover semua variasi struktur FB feed + article fallback
            const feedContainers=[
                ...document.querySelectorAll('[role="feed"] [aria-posinset]'),
                ...document.querySelectorAll('[role="feed"] [role="article"]'),
                ...document.querySelectorAll('[role="feed"]>div>div>div>div'),
                ...Array.from(document.querySelectorAll('[role="article"]')).filter(a=>{
                    const al=(a.getAttribute('aria-label')||'').toLowerCase();
                    return !al.includes('komentar')&&!al.includes('comment')&&!al.includes('balasan');
                })
            ];
            const seen_c=new Set();
            feedContainers.filter(c=>{if(seen_c.has(c))return false;seen_c.add(c);return true;}).forEach(c=>{
                try{
                    const ls=c.querySelectorAll('a[href*="/"]');
                    let url=pickContentUrl(ls),author='',txt='';
                    if(!url)url=recoverContentUrl(c);
                    const sourceUrl=url||pickAuthorUrl(ls);
                    author=pickAuthorName(ls);
                    const ac=c.querySelector('a[role="link"] span[dir="auto"],strong[dir="auto"] > span[dir="auto"],h2 span[dir="auto"],h3 span[dir="auto"],h4 span[dir="auto"]');
                    if(!author&&ac)author=cleanAuthor(ac.innerText||'');
                    if(!author){
                        const ac2=c.querySelector('strong[dir="auto"],h2,h3,h4');
                        if(ac2)author=cleanAuthor(ac2.innerText||'');
                    }
                    c.querySelectorAll('span[dir="auto"],div[dir="auto"]').forEach(el=>{
                        const t=(el.innerText||'').trim();
                        if(t.length>txt.length&&t.length<3000&&t!==author&&t!=='Lihat selengkapnya')txt=t;
                    });
                    let likes=0,comms=0,views=0,shares=0;
                    const fullText=(c.innerText||'').replace(/\u00a0/g,' ');
                    txt=cleanCaption(txt);
                    if(!txt||txt.length<12)txt=cleanCaption(fullText);
                    const vm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:tayangan|views|ditonton)/i);
                    if(vm)views=parseNum(vm[0]);
                    c.querySelectorAll('div[role="button"],span[role="button"],a[role="button"]').forEach(el=>{
                        const aria=(el.getAttribute('aria-label')||'').toLowerCase();
                        let tx=(el.innerText||'').trim();
                        if(aria.includes('suka')||aria.includes('like')||aria.includes('react')||aria.includes('reaksi')){
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            likes=Math.max(likes,parseNum(tx||aria));
                        }
                        if(aria.includes('komentar')||aria.includes('comment')){
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            comms=Math.max(comms,parseNum(tx||aria));
                        }
                        if(aria.includes('bagikan')||aria.includes('share')||aria.includes('kirim')){
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            const num=parseNum(tx||aria);
                            if(num>0)shares=Math.max(shares,num);
                        }
                    });
                    // Fallback shares: cari pola teks dalam artikel
                    if(!shares){
                        const sm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:kali\s+dibagikan|x\s+dibagikan|dibagikan|shares?)\b/i);
                        if(sm)shares=parseNum(sm[0]);
                    }
                    if(!likes&&!comms&&!shares){
                        const loose=extractLooseMetrics(fullText).slice(-3);
                        if(loose.length>=2){
                            likes=loose[0]?.value||0;
                            comms=loose[1]?.value||0;
                            shares=loose[2]?.value||0;
                        }
                    }
                    const images=extractImages(c);
                    let source='dom';
                    if(!url||!isSpecificFbUrl(url)){
                        if(!txt || txt.length<20 || (!likes&&!comms&&!shares&&!views))return;
                        const q=pageQuery();
                        const h=hashText(`${author}|${txt}|${likes}|${comms}|${shares}|${views}`);
                        url=`https://www.facebook.com/search/posts/?q=${encodeURIComponent(q)}&fb_scrape_card=${h}`;
                        source='search_post_card';
                    }
                    if(!url||s.has(url))return;
                    s.add(url);
                    r.push({url,author:author||'Unknown',text:txt.slice(0,1000),caption:txt.slice(0,1000),
                        timestamp:'',type:'posts',likes_count:likes||0,comments_count:comms||0,
                        views_count:views||0,shares_count:shares||0,images,media_urls:images,media_count:images.length,
                        engagement_score:likes+comms*2+shares*3+views,source,source_url:sourceUrl||'',matched_via:pageQuery()?`search:${pageQuery()}`:'',link_valid:source!=='search_post_card',open_url_validated:source!=='search_post_card',search_card_uid:hashText(`${author}|${txt}|${likes}|${comms}|${shares}|${views}`)});
                }catch(e){}
            });
            return r;
        }
        """

        for rnd in range(mx):
            if len(results)>=max_items: break
            try:
                batch=page.evaluate(_JS_FEED, max_items-len(results))
            except Exception as e:
                print(Fore.YELLOW+f"   [FEED] stop early, returning {len(results)} partial items: {e}")
                break
            n=0
            for item in batch:
                u=item.get('url','')
                key = _fb_content_key(u) or u
                if not u or key in seen_urls: continue
                if item.get("source") != "search_post_card" and not _is_valid_result_url(u): continue
                if keyword and not _keyword_in_item(item, keyword):
                    continue
                seen_urls.add(key); results.append(item); n+=1
            if rnd%5==0 or n>0: print(Fore.CYAN+f"   [FEED] R{rnd+1}: {len(results)}(+{n})")
            if n==0: stable+=1
            else: stable=0
            if stable>=ms: break
            try:
                page.evaluate(f"window.scrollBy(0,{random.choice([1200,1500,2000])})")
            except Exception as e:
                print(Fore.YELLOW+f"   [FEED] scroll interrupted, keeping {len(results)} items: {e}")
                break
            time.sleep(random.uniform(0.8,1.5))
        return results[:max_items]

    # ======================================================================
    #  GENERIC SCROLL EXTRACTION
    # ======================================================================
    def _extract_generic(self, page, max_items=100, search_type="videos", keyword=""):
        results=[]; seen_urls=set(); stable=0; ms=6 if search_type == "videos" else 4

        print(Fore.CYAN+f"   [GENERIC] Using universal scroll extraction for {search_type}...")

        if search_type == "groups":
            return self._extract_group_posts(page, max_items, keyword)

        if search_type == "pages":
            return self._extract_page_posts(page, max_items, keyword)

        mx = max(4, min(FB_GENERIC_MAX_ROUNDS + (4 if search_type == "videos" else 0), math.ceil(max_items / 6) + (8 if search_type == "videos" else 4)))
        _JS_GENERIC = r"""
        (args) => {
            const st=args.searchType||'posts'; const kw=(args.keyword||'').toLowerCase();
            const r=[]; const s=new Set();
            const clean=(text)=>(text||'').replace(/\u00a0|\xa0|Â|�/g,' ').replace(/\s+/g,' ').trim();
            const compact=(text)=>clean(text).toLowerCase().replace(/[\s_-]+/g,'');
            const kwCompact=compact(kw);
            const kwMatch=(text)=>{
                if(!kw)return true;
                const low=clean(text).toLowerCase();
                return low.includes(kw)||Boolean(kwCompact&&kwCompact.length>=3&&compact(low).includes(kwCompact));
            };
            const parseNum=(text)=>{
                const m=(text||'').toLowerCase().replace(/\u00a0/g,' ').match(/([\d.,]+)\s*(rb|ribu|k|jt|juta|m|mio)?/i);
                if(!m)return 0;
                let n=parseFloat(m[1].replace(/\./g,'').replace(',','.'));
                const sf=(m[2]||'').toLowerCase();
                if(sf==='k'||sf==='rb'||sf==='ribu')n*=1000;
                else if(sf==='m'||sf==='jt'||sf==='juta'||sf==='mio')n*=1000000;
                return Math.floor(n)||0;
            };
            const extractImages=(node)=>{
                const imgs=[];
                if(!node)return imgs;
                node.querySelectorAll('img[src*="scontent"],img[src*="fbcdn"]').forEach(im=>{
                    const src=im.getAttribute('src')||'';
                    const w=im.naturalWidth||im.width||0;
                    const h=im.naturalHeight||im.height||0;
                    if(src&&!imgs.includes(src)&&(w===0||w>=120)&&(h===0||h>=80))imgs.push(src);
                });
                return imgs.slice(0,6);
            };
            const normalizeUrl=(href)=>{
                if(!href)return '';
                let raw=href;
                if(raw.startsWith('http')){
                    try{ raw=new URL(raw).pathname+new URL(raw).search; }catch(e){}
                }
                if(!raw.startsWith('/'))raw='/'+raw;
                if(raw.includes('/stories/'))return '';
                // ✅ FIX: support /watch/ dengan berbagai query param format
                if(raw.includes('/watch')&&raw.includes('v=')){
                    const m=raw.match(/[?&]v=(\d+)/);
                    if(m)return 'https://www.facebook.com/watch/?v='+m[1];
                }
                // ✅ FIX: format share baru FB
                if(/\/share\/(p|v|r)\/[A-Za-z0-9_-]+/.test(raw)){
                    return 'https://www.facebook.com'+raw.split('#')[0].split('?')[0];
                }
                if((raw.includes('/photo/')||raw.includes('/photo?'))&&raw.includes('fbid=')){
                    const m=raw.match(/[?&]fbid=(\d+)/);
                    if(m)return 'https://www.facebook.com/photo/?fbid='+m[1];
                }
                if(/profile\.php\?id=\d+/.test(raw)){
                    const m=raw.match(/id=(\d+)/);
                    if(m)return 'https://www.facebook.com/profile.php?id='+m[1];
                }
                if(raw.includes('story_fbid=')){
                    const m=raw.match(/story_fbid=(\d+)/);
                    if(m)return 'https://www.facebook.com/profile.php?story_fbid='+m[1];
                }
                raw=raw.split('#')[0].split('?')[0];
                return 'https://www.facebook.com'+raw;
            };
            const contentLinks=(node)=>{
                if(!node)return 0;
                let n=0;
                node.querySelectorAll('a[href]').forEach(x=>{
                    const h=x.getAttribute('href')||'';
                    // ✅ FIX: cek /watch dengan v= param di posisi manapun
                    const isWatch=h.includes('/watch')&&/[?&]v=\d/.test(h);
                    if(!h.includes('/stories/')&&(/\/(posts|permalink)\/(?:\d+|pfbid[A-Za-z0-9_-]+)/.test(h)||/\/(photo|photos|videos|video|reel|reels)\/\d+/.test(h)||isWatch||((h.includes('/photo/')||h.includes('/photo?'))&&h.includes('fbid='))))n++;
                });
                return n;
            };
            const pickCard=(a)=>{
                const article=a.closest('[role="article"]');
                if(article)return article;
                let best=a.parentElement;
                let node=a.parentElement;
                for(let i=0;node&&i<8;i++,node=node.parentElement){
                    const txt=(node.innerText||'').trim();
                    const links=contentLinks(node);
                    if(txt.length>=8&&txt.length<=1800&&links<=3){
                        best=node;
                        if(txt.length>=25)break;
                    }
                    if(txt.length>2500||links>6)break;
                }
                return best||a.parentElement;
            };
            const badText=(t)=>{
                const x=clean(t).toLowerCase();
                if(!x)return true;
                if(x===kw||x==='videos'||x==='reels'||x==='watch'||x==='lihat selengkapnya')return true;
                if(/^(like|comment|share|suka|komentar|bagikan|\d+:\d+)$/.test(x))return true;
                return false;
            };
            const metricNums=(text)=>{
                return [...clean(text).matchAll(/([\d]+(?:[.,][\d]+)?)(?:\s*(rb|ribu|k|jt|juta|m|mio|mn)(?![a-z]))?/gi)]
                    .map(m=>parseNum(`${m[1]} ${m[2]||''}`))
                    .filter(n=>n>0&&n<1000000000);
            };
            const extractArticleVideos=()=>{
                if(st!=='videos')return;
                const cards=[...document.querySelectorAll('[role="article"], [aria-posinset]')];
                cards.forEach(card=>{
                    try{
                        const links=[...card.querySelectorAll('a[href]')];
                        const videoLinks=links.filter(a=>{
                            const h=a.getAttribute('href')||'';
                            if(!h||h.includes('/search/')||h.includes('/stories/'))return false;
                            return (h.includes('/watch')&&/[?&]v=\d/.test(h))||/\/(?:videos?|reels?)\/\d+/.test(h)||/\/reel\/\d+/.test(h);
                        });
                        if(!videoLinks.length)return;
                        const best=videoLinks.find(a=>!badText(a.innerText||a.getAttribute('aria-label')||''))||videoLinks[0];
                        const url=normalizeUrl(best.getAttribute('href')||best.href||'');
                        if(!url||s.has(url))return;
                        const stripDuration=(text)=>clean(text).replace(/^(\d+:)?\d+:\d+(?:\s*\/\s*(\d+:)?\d+:\d+)?\s*/,'').trim();
                        const fullText=clean(card.innerText||best.innerText||best.getAttribute('aria-label')||'');
                        if(kw&&!kwMatch(fullText)&&!kwMatch(best.innerText||'')&&!((best.getAttribute('href')||'').toLowerCase().includes(`q=${encodeURIComponent(kw)}`)))return;
                        const lines=fullText.split(/\n+/).map(clean).filter(Boolean);
                        const titleLine=stripDuration(lines.find(line=>line.length>8&&!badText(line)&&!/^(\d+:)?\d+:\d+/.test(line))||best.innerText||'');
                        const textParts=lines.filter(line=>
                            line.length>8&&
                            !badText(line)&&
                            !/^(\d+:)?\d+:\d+/.test(line)&&
                            !/^(ikuti|follow|diverifikasi|verified)$/i.test(line)
                        );
                        const caption=stripDuration(textParts.join(' ').slice(0,1200)||titleLine);
                        let author='';
                        const authorLink=links.find(a=>{
                            const h=a.getAttribute('href')||'';
                            const t=clean(a.innerText||'');
                            return t.length>2&&t.length<90&&!/\/watch|\/reel|\/video|\/search/.test(h)&&!/^\d/.test(t)&&!badText(t);
                        });
                        if(authorLink)author=clean(authorLink.innerText||'').slice(0,100);
                        let likes=0,comms=0,views=0,shares=0;
                        const lm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:suka|likes?|reaksi|reactions?)/i);
                        const cm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)/i);
                        const vm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i);
                        const sm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:kali\s+dibagikan|x\s+dibagikan|dibagikan|shares?)/i);
                        if(lm)likes=parseNum(lm[1]||lm[0]);
                        if(cm)comms=parseNum(cm[1]||cm[0]);
                        if(vm)views=parseNum(vm[1]||vm[0]);
                        if(sm)shares=parseNum(sm[1]||sm[0]);
                        const images=extractImages(card);
                        s.add(url);
                        r.push({url,author:author||'Unknown',text:caption,caption,
                            timestamp:'',type:'videos',likes_count:likes||0,comments_count:comms||0,
                            views_count:views||0,shares_count:shares||0,images,media_urls:images,media_count:images.length,
                            engagement_score:likes+comms*2+shares*3+views*0.1,source:'generic_article',matched_via:kw ? `search:${kw}` : ''});
                    }catch(e){}
                });
            };
            extractArticleVideos();
            const allLinks=document.querySelectorAll('a[href*="/"]');
            allLinks.forEach(a=>{
                try{
                    const h=a.getAttribute('href')||''; const ch=h.split('#')[0].split('?')[0];
                    let url='',detected='';
                    if(st==='videos'){
                        // ✅ FIX: cek v= param di semua posisi (bukan hanya /watch/?v=)
                        const hasWatchV = h.includes('/watch')&&/[?&]v=\d/.test(h);
                        if(/\/(videos\/|video\/|reel\/|reels\/)/.test(ch)||hasWatchV){
                            url=normalizeUrl(h);detected='videos';
                        }
                    }
                    if(st==='pages'){
                        if(/^\/[a-zA-Z0-9._%-]+\/(posts|videos|photos)\/\d+/.test(ch)){
                            url=normalizeUrl(h);detected='pages';
                        }
                    }
                    if(st==='posts'){
                        if(/(posts|permalink)\/(?:\d+|pfbid[A-Za-z0-9_-]+)/.test(ch)||/photo\/\d+/.test(ch)||((h.includes('/photo/')||h.includes('/photo?'))&&h.includes('fbid='))){
                            url=normalizeUrl(h);detected='posts';
                        }
                    }
                    if(!url||s.has(url))return;
                    if(url.includes('/help/')||url.includes('/privacy/')||url.includes('/legal/'))return;
                    const container=pickCard(a);
                    let author='',txt='',likes=0,comms=0,views=0,images=[];
                    if(container){
                        // ✅ FIX: perkuat author extraction untuk video FB
                        const ac=container.querySelector('strong[dir="auto"],h2,h3,h4,a[role="link"] span[dir="auto"],a[href*="facebook.com"] strong');
                        if(ac)author=(ac.innerText||'').trim().slice(0,100);
                        if(!author){
                            // Coba dari link teks yang bukan URL, bukan timestamp
                            const links=container.querySelectorAll('a[href]');
                            for(const lk of links){
                                const lt=(lk.innerText||'').trim();
                                if(lt&&lt.length>2&&lt.length<80&&!/^\d+[:.]?\d*$/.test(lt)&&!lt.includes('http')){
                                    author=lt; break;
                                }
                            }
                        }
                        const candidates=[];
                        container.querySelectorAll('span[dir="auto"],div[dir="auto"]').forEach(el=>{
                            const t=clean(el.innerText||'');
                            if(t.length<3||t.length>2200||t===author||badText(t))return;
                            candidates.push(t);
                        });
                        candidates.sort((a,b)=>{
                            const ak=kwMatch(a)?1:0;
                            const bk=kwMatch(b)?1:0;
                            if(ak!==bk)return bk-ak;
                            return b.length-a.length;
                        });
                        txt=(candidates[0]||clean(a.innerText||a.getAttribute('aria-label')||a.getAttribute('title')||'')).slice(0,1000);
                        // ✅ FIX: replace \xa0 (non-breaking space) sebelum parse
                        const fullText=(container.innerText||'').replace(/\u00a0/g,' ').replace(/\xa0/g,' ');
                        // ✅ FIX: views — cek semua varian bahasa Indonesia/Inggris
                        const vmPatterns=[
                            /([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:tayangan|views|ditonton|viewed)/i,
                            /(?:tayangan|views|ditonton)\s*[:\-·]?\s*([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)/i,
                        ];
                        for(const vp of vmPatterns){const vm=fullText.match(vp);if(vm){views=parseNum(vm[1]||vm[0]);if(views>0)break;}}

                        // ✅ FIX: tambah selector broader untuk like/comment di video FB
                        // Di video search, engagement ada di aria-label dari link artikel, bukan [role=button]
                        const allEls=container.querySelectorAll('[aria-label],[role="button"],a[href]');
                        allEls.forEach(el=>{
                            const aria=(el.getAttribute('aria-label')||'').replace(/\xa0/g,' ').replace(/\u00a0/g,' ');
                            let tx=(el.innerText||'').replace(/\xa0/g,' ').replace(/\u00a0/g,' ').trim();
                            // Likes: "N Suka" / "N Like" / "Suka: N"
                            if(/suka|like|reaksi|react/i.test(aria)&&/\d/.test(aria)){
                                const nm=aria.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)/i);
                                if(nm)likes=Math.max(likes,parseNum(nm[1]));
                            }
                            // Comments
                            if(/komentar|comment/i.test(aria)&&/\d/.test(aria)){
                                const nm=aria.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)/i);
                                if(nm)comms=Math.max(comms,parseNum(nm[1]));
                            }
                        });
                        // ✅ FIX: fallback parse dari fullText untuk likes/comments/views video
                        if(!likes){
                            const lm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:suka|like|likes)\b/i)
                                    ||fullText.match(/(?:suka|like|likes)\s*[·:\-]?\s*([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)/i);
                            if(lm)likes=parseNum(lm[1]||lm[0]);
                        }
                        if(!comms){
                            const cm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:komentar|comment)\b/i)
                                    ||fullText.match(/(?:komentar|comment)\s*[·:\-]?\s*([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)/i);
                            if(cm)comms=parseNum(cm[1]||cm[0]);
                        }
                        if(!views){
                            const vm2=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:tayangan|views|ditonton)\b/i);
                            if(vm2)views=parseNum(vm2[1]||vm2[0]);
                        }
                        // Shares
                        let shares=0;
                        container.querySelectorAll('[aria-label*="bagikan"],[aria-label*="share"],[aria-label*="Share"],[aria-label*="Bagikan"]').forEach(el=>{
                            let tx=(el.innerText||'').replace(/\xa0/g,' ').trim();
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').replace(/\xa0/g,' ').trim();
                            const num=parseNum(tx+' '+(el.getAttribute('aria-label')||''));
                            if(num>0)shares=Math.max(shares,num);
                        });
                        if(!shares){
                            const sm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:kali\s+dibagikan|x\s+dibagikan|dibagikan|shares?)/i);
                            if(sm)shares=parseNum(sm[0]);
                        }
                        images=extractImages(container);
                    }
                    s.add(url);
                    r.push({url,author:author||'Unknown',text:txt.slice(0,1000),caption:txt.slice(0,1000),
                        timestamp:'',type:detected||st,likes_count:likes||0,comments_count:comms||0,
                        views_count:views||0,shares_count:shares||0,images,media_urls:images,media_count:images.length,
                        engagement_score:likes+comms*2+views,source:'generic',matched_via:kw ? `search:${kw}` : ''});
                }catch(e){}
            });
            return r;
        }
        """

        for rnd in range(mx):
            if len(results)>=max_items: break
            try:
                batch=page.evaluate(_JS_GENERIC, {"searchType": search_type, "keyword": keyword or ''})
            except Exception as e:
                print(Fore.YELLOW+f"   [GENERIC] stop early, returning {len(results)} partial items: {e}")
                break
            n=0
            for item in batch:
                u=item.get('url','')
                key = _fb_content_key(u) or u
                if not u or key in seen_urls or not _is_valid_result_url(u): continue
                if keyword and search_type != "videos" and not _keyword_in_item(item, keyword):
                    continue
                seen_urls.add(key); results.append(item); n+=1
            if rnd%5==0 or n>0: print(Fore.CYAN+f"   [GENERIC] R{rnd+1}: {len(results)}(+{n}) type={search_type}")
            if rnd == 0 and n == 0 and search_type == "videos":
                try:
                    diag = page.evaluate("""() => ({
                        links: document.querySelectorAll('a[href]').length,
                        reels: [...document.querySelectorAll('a[href]')].filter(a => /\\/reels?\\//.test(a.getAttribute('href') || '')).length,
                        videos: [...document.querySelectorAll('a[href]')].filter(a => /\\/videos?\\//.test(a.getAttribute('href') || '')).length,
                        watch: [...document.querySelectorAll('a[href]')].filter(a => /\\/watch/.test(a.getAttribute('href') || '')).length,
                        articles: document.querySelectorAll('[role="article"], [aria-posinset]').length
                    })""")
                    print(Fore.YELLOW+f"   [GENERIC-DOM] links={diag.get('links')} reels={diag.get('reels')} videos={diag.get('videos')} watch={diag.get('watch')} articles={diag.get('articles')}")
                except Exception:
                    pass
            if n==0: stable+=1
            else: stable=0
            if stable>=ms: break
            try:
                page.evaluate(f"window.scrollBy(0,{random.choice([1000,1500,2000])})")
            except Exception as e:
                print(Fore.YELLOW+f"   [GENERIC] scroll interrupted, keeping {len(results)} items: {e}")
                break
            time.sleep(random.uniform(0.8,1.5))
        return results[:max_items]

    def _needs_detail_enrich(self, item: dict) -> bool:
        url = item.get("url", "")
        if _is_search_card_url(url):
            item["link_valid"] = False
            item["open_url_validated"] = False
            item.setdefault("link_sync_error", "search_card_has_no_permalink")
            return False
        if not _is_commentable_url(url):
            return False
        text_missing = not (item.get("caption") or item.get("text") or "").strip()
        core_missing = (
            _metric_value(item.get("likes_count")) == 0
            or _metric_value(item.get("comments_count")) == 0
            or _metric_value(item.get("shares_count")) == 0
        )
        is_video = _is_video_item(item)
        source = (item.get("source") or "").lower()
        search_only_source = source in {"dom", "generic", "generic_article", "html_embedded"}
        return search_only_source or text_missing or (is_video and not item.get("metrics_valid")) or (is_video and core_missing) or (
            _metric_value(item.get("likes_count")) == 0
            and _metric_value(item.get("comments_count")) == 0
            and _metric_value(item.get("shares_count")) == 0
        )
    def safe_goto(self, page: Page, url: str, timeout=45000, retries=3) -> dict:
        last_error = None
        for attempt in range(1, retries + 1):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                return {"ok": True, "status": "loaded", "final_url": page.url, "error": None}
            except Exception as e:
                last_error = str(e)
                final_url = getattr(page, "url", "") or ""
                if "net::ERR_ABORTED" in last_error and "facebook.com" in final_url and final_url != "about:blank":
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=5000)
                    except Exception:
                        pass
                    return {"ok": True, "status": "loaded_after_abort", "final_url": final_url, "error": last_error}
                print(Fore.YELLOW+f"     [DETAIL] goto retry {attempt}/{retries}: {last_error[:180]}")
                try:
                    page.goto("about:blank", wait_until="domcontentloaded", timeout=5000)
                except Exception:
                    pass
                time.sleep(min(1.5 * attempt, 4.0))
        return {"ok": False, "status": "navigation_failed", "final_url": getattr(page, "url", "") or "", "error": last_error}

    def _save_detail_debug_snapshot(self, url: str, page: Optional[Page], error: str):
        try:
            os.makedirs("fb_keyword_debug", exist_ok=True)
            final_url = ""
            body = ""
            if page is not None:
                try:
                    final_url = page.url
                except Exception:
                    final_url = ""
                try:
                    body = page.locator("body").inner_text(timeout=3000)
                except Exception:
                    body = ""
            payload = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "url": url,
                "final_url": final_url,
                "body_text": (body or "")[:5000],
                "error": str(error or "")[:2000],
            }
            name = f"detail_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.json"
            with open(os.path.join("fb_keyword_debug", name), "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as snap_err:
            print(Fore.YELLOW+f"     [DETAIL] debug snapshot failed: {snap_err}")

    def collect_metric_text_candidates(self, page: Page) -> List[str]:
        try:
            return page.evaluate(r"""
            () => {
                const metricRe = /(tayangan|views?|ditonton|viewed|komentar|comments?|suka|likes?|reaksi|reactions?|dibagikan|shares?)/i;
                const clean = (text) => (text || '')
                    .replace(/\u00a0|\xa0|Ã‚|ï¿½/g, ' ')
                    .replace(/\s+/g, ' ')
                    .trim();
                const seen = new Set();
                const out = [];
                const add = (text) => {
                    const value = clean(text);
                    if (!value || seen.has(value)) return;
                    seen.add(value);
                    out.push(value);
                };

                add(document.body?.innerText || '');
                const bodyLines = (document.body?.innerText || '').split(/\n+/).map(clean).filter(Boolean);
                bodyLines.forEach((line, idx) => {
                    if (!metricRe.test(line)) return;
                    add(line);
                    if (idx > 0) add(`${bodyLines[idx - 1]} ${line}`);
                    if (idx + 1 < bodyLines.length) add(`${line} ${bodyLines[idx + 1]}`);
                    if (idx > 0 && idx + 1 < bodyLines.length) add(`${bodyLines[idx - 1]} ${line} ${bodyLines[idx + 1]}`);
                });

                document.querySelectorAll('[aria-label]').forEach(el => {
                    const aria = clean(el.getAttribute('aria-label') || '');
                    if (metricRe.test(aria)) add(aria);
                });

                document.querySelectorAll('[role="button"]').forEach(el => {
                    const text = clean(`${el.getAttribute('aria-label') || ''} ${el.innerText || ''}`);
                    if (metricRe.test(text)) add(text);
                });

                document.querySelectorAll('span,div').forEach(el => {
                    const text = clean(el.innerText || el.textContent || '');
                    if (!text || text.length > 260) return;
                    if (metricRe.test(text)) add(text);
                });

                return out.slice(0, 500);
            }
            """)
        except Exception as e:
            print(Fore.YELLOW+f"     [DETAIL] candidate collect error: {e}")
            try:
                return [page.locator("body").inner_text(timeout=3000)]
            except Exception:
                return []

    def _extract_primary_detail_counts(self, page: Page) -> Optional[dict]:
        """Scope-locked metric read for the ACTIVE video/reel only.

        Two real FB layouts (verified live via debug_views_bug.py / debug_reel_rail.py):
          * /watch & video permalinks -> ONE horizontal engagement row:
            "Suka Komentari Bagikan <likes> · <comments> komentar · <views> tayangan".
          * /reel -> a vertical action rail where the count sits on the FIRST
            Suka/Komentari/Bagikan buttons. Reels rendered below belong to OTHER clips
            in the feed, so only the topmost (active) rail may be read.

        Returning the metrics as one coherent set kills the old bug where a page-wide
        max scan grabbed a neighbouring 'suggested video' count (e.g. 333 rb views /
        5,3 rb likes from another clip instead of the real 34 rb / 881)."""
        try:
            return page.evaluate(r"""
            () => {
                const clean = (t) => (t || '').replace(/ |\xa0|Â|Ã‚|�/g, ' ').replace(/\s+/g, ' ').trim();
                const parseNum = (text) => {
                    const m = clean(text).toLowerCase().match(/([\d]+(?:[.,][\d]+)?)\s*(ribu|juta|mio|mn|rb|jt|k|m)?(?![a-z])/i);
                    if (!m) return null;
                    let n = parseFloat(m[1].replace(/\./g, '').replace(',', '.'));
                    if (Number.isNaN(n)) return null;
                    const sf = (m[2] || '').toLowerCase();
                    if (sf === 'k' || sf === 'rb' || sf === 'ribu') n *= 1000;
                    else if (sf === 'm' || sf === 'jt' || sf === 'juta' || sf === 'mio' || sf === 'mn') n *= 1000000;
                    return Math.floor(n);
                };

                // ── A) Horizontal engagement row (watch / video permalinks). The active
                //       video sits first in [role=main]/[role=article], so the FIRST row
                //       match belongs to it, never to the suggested-video feed below. ──
                const scopes = [document.querySelector('[role="main"]'), ...document.querySelectorAll('[role="article"]')].filter(Boolean);
                const scopedText = (scopes.map(el => clean(el.innerText || '')).filter(Boolean).join('\n')) || clean(document.body.innerText || '');
                const rowFull = scopedText.match(/(?:\bSuka\b|\bLike\b)\s+(?:Komentari|Comment)\s+(?:Bagikan|Share)\s+([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i);
                if (rowFull) {
                    return {likes: parseNum(rowFull[1]), comments: parseNum(rowFull[2]), shares: null, views: parseNum(rowFull[3]), source: 'detail_engagement_row', matched: clean(rowFull[0]).slice(0, 160)};
                }
                const rowNoLikes = scopedText.match(/(?:\bSuka\b|\bLike\b)\s+(?:Komentari|Comment)\s+(?:Bagikan|Share)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i);
                if (rowNoLikes) {
                    return {likes: null, comments: parseNum(rowNoLikes[1]), shares: null, views: parseNum(rowNoLikes[2]), source: 'detail_engagement_row_nolikes', matched: clean(rowNoLikes[0]).slice(0, 160)};
                }

                // ── B) Vertical reel action rail: read the count co-located with the
                //       FIRST (topmost = active) Suka/Komentari/Bagikan button. ──
                const isNum = /^\d+(?:[.,]\d+)?\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?$/i;
                const numbers = [];
                document.querySelectorAll('span,div').forEach(el => {
                    if (el.children.length) return;            // leaf text nodes only
                    const t = clean(el.innerText || el.textContent || '');
                    if (!isNum.test(t) || t.length > 8) return;
                    const r = el.getBoundingClientRect();
                    if (r.width === 0 && r.height === 0) return;
                    numbers.push({v: parseNum(t), cx: r.x + r.width / 2, cy: r.y + r.height / 2});
                });
                const btns = [...document.querySelectorAll('[role="button"][aria-label]')].map(el => {
                    const r = el.getBoundingClientRect();
                    return {a: clean(el.getAttribute('aria-label')).toLowerCase(), cx: r.x + r.width / 2, cy: r.y + r.height / 2, vis: r.width > 0 || r.height > 0};
                }).filter(b => b.vis);
                const firstBtn = (names) => btns.filter(b => names.some(n => b.a === n)).sort((x, y) => x.cy - y.cy)[0];
                const countNear = (btn) => {
                    if (!btn) return null;
                    let best = null, bestD = 26;               // own count is co-located (~0-15px); neighbour ~30px+
                    for (const n of numbers) {
                        if (n.v === null || Math.abs(n.cx - btn.cx) > 36) continue;
                        const d = Math.hypot(n.cx - btn.cx, n.cy - btn.cy);
                        if (d < bestD) { bestD = d; best = n.v; }
                    }
                    return best;
                };
                const likes = countNear(firstBtn(['suka', 'beri reaksi', 'like']));
                const comments = countNear(firstBtn(['komentari', 'comment']));
                const shares = countNear(firstBtn(['bagikan', 'share']));
                if (likes !== null || comments !== null || shares !== null) {
                    return {likes, comments, shares, views: null, source: 'reel_action_rail', matched: 'rail L=' + likes + ' C=' + comments + ' S=' + shares};
                }
                return null;
            }
            """)
        except Exception as e:
            print(Fore.YELLOW+f"     [DETAIL] primary-count extract error: {e}")
            return None

    def extract_detail_metrics(self, page: Page, url: str) -> dict:
        nav = self.safe_goto(page, url, timeout=45000, retries=3)
        out = {
            "likes_count": None,
            "comments_count": None,
            "shares_count": None,
            "views_count": None,
            "metrics_valid": False,
            "metric_source": "detail_page_text",
            "metrics_error": None,
            "detail_status": nav.get("status") or "unknown",
            "detail_final_url": nav.get("final_url") or "",
            "matched_patterns": {},
        }
        if not nav.get("ok"):
            out["metrics_error"] = nav.get("error") or "navigation_failed"
            self._save_detail_debug_snapshot(url, page, out["metrics_error"])
            return out
        try:
            time.sleep(random.uniform(3.0, 5.0))
            self._close_popups(page)
            try:
                page.evaluate("window.scrollBy(0, 650)")
                time.sleep(0.8)
                page.evaluate("window.scrollBy(0, -220)")
                time.sleep(0.4)
            except Exception:
                pass
            try:
                body_text_for_footer = page.locator("body").inner_text(timeout=3000)
            except Exception:
                body_text_for_footer = ""
            candidates = self.collect_metric_text_candidates(page)
            metrics = {
                "views": None,
                "likes": None,
                "comments": None,
                "shares": None,
                "matched_patterns": {},
            }
            # Authoritative pass: lock onto the ACTIVE video/reel's own counts so the
            # page-wide candidate scan below can never override them with a sibling
            # suggested-video number. Fields it resolves are "locked".
            locked = set()
            primary = self._extract_primary_detail_counts(page)
            if primary:
                for src, field in (("likes", "likes"), ("comments", "comments"), ("shares", "shares"), ("views", "views")):
                    value = primary.get(src)
                    if value is not None:
                        metrics[field] = int(value)
                        metrics["matched_patterns"][field] = f"{primary.get('source', 'primary')}:{primary.get('matched', '')}"[:160]
                        locked.add(field)
            # Fallback: page-wide text candidates only FILL fields still unresolved.
            for candidate in candidates:
                found = extract_video_metrics_from_text(candidate)
                for field in ("views", "likes", "comments", "shares"):
                    if field in locked:
                        continue
                    value = found.get(field)
                    if value is None:
                        continue
                    if metrics[field] is None or value > metrics[field]:
                        metrics[field] = value
                        metrics["matched_patterns"][field] = found.get("matched_patterns", {}).get(field, "")[:160]
            mapping = {
                "likes": "likes_count",
                "comments": "comments_count",
                "shares": "shares_count",
                "views": "views_count",
            }
            for src, dst in mapping.items():
                if metrics.get(src) is not None:
                    out[dst] = metrics[src]
            out["matched_patterns"] = metrics.get("matched_patterns", {})
            footer_metrics = extract_reel_footer_metrics_from_text(body_text_for_footer)
            footer_used = False
            for key in ("likes_count", "comments_count", "shares_count", "views_count"):
                val = footer_metrics.get(key)
                if val is not None and out.get(key) is None:
                    out[key] = int(val)
                    footer_used = True
                    pattern = footer_metrics.get("matched_patterns", {}).get(key)
                    if pattern:
                        out["matched_patterns"][key] = pattern
            if footer_used and not metrics.get("matched_patterns"):
                out["metric_source"] = "detail_page_reel_footer"
            out["metrics_valid"] = any(out.get(k) is not None for k in ("likes_count", "comments_count", "shares_count", "views_count"))
            if out["metrics_valid"]:
                out["detail_status"] = "ok"
            else:
                out["metrics_error"] = "no_detail_metric_pattern_matched"
                self._save_detail_debug_snapshot(url, page, out["metrics_error"])
            return out
        except Exception as e:
            out["metrics_error"] = str(e)[:1000]
            out["detail_status"] = "extract_failed"
            self._save_detail_debug_snapshot(url, page, out["metrics_error"])
            return out

    def _extract_detail_metadata(self, page: Page) -> dict:
        try:
            return page.evaluate(r"""
            () => {
                const out = {likes_count: 0, comments_count: 0, shares_count: 0, views_count: 0, caption: '', author: '', caption_reliable: false};
                const clean = (text) => (text || '').replace(/\u00a0|\xa0|Â|�/g, ' ').replace(/\s+/g, ' ').trim();
                const parseNum = (text) => {
                    const m = clean(text).toLowerCase().match(/([\d]+(?:[.,][\d]+)?)(?:\s*(ribu|juta|mio|mn|rb|jt|k|m)(?![a-z]))?/i);
                    if (!m) return 0;
                    let n = parseFloat(m[1].replace(/\./g, '').replace(',', '.'));
                    if (Number.isNaN(n)) return 0;
                    const sf = (m[2] || '').toLowerCase();
                    if (sf === 'k' || sf === 'rb' || sf === 'ribu') n *= 1000;
                    else if (sf === 'm' || sf === 'jt' || sf === 'juta' || sf === 'mio' || sf === 'mn') n *= 1000000;
                    return Math.floor(n) || 0;
                };
                const parseNums = (text) => {
                    const matches = [...clean(text).toLowerCase().matchAll(/([\d]+(?:[.,][\d]+)?)(?:\s*(ribu|juta|mio|mn|rb|jt|k|m)(?![a-z]))?/gi)];
                    return matches
                        .map(m => parseNum(`${m[1]} ${m[2] || ''}`))
                        .filter(n => n > 0);
                };
                const maxMetric = (current, text) => Math.max(current || 0, parseNum(text));
                const hasMetricNumber = (text) => /[\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?/i.test(clean(text));
                const bodyText = clean(document.body.innerText || '');
                const metricNumber = /^(\d+(?:[.,]\d+)?\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?|\d+)$/i;
                const scopedText = () => {
                    const scopes = [
                        ...document.querySelectorAll('[role="article"]'),
                        document.querySelector('[role="main"]'),
                    ].filter(Boolean);
                    const text = scopes.map(el => clean(el.innerText || '')).filter(Boolean).join('\n');
                    return text || bodyText;
                };
                const scanMetric = (patterns) => {
                    const text = scopedText();
                    for (const pat of patterns) {
                        const m = text.match(pat);
                        if (m) {
                            const n = parseNum(m[1] || m[0]);
                            if (n > 0) return n;
                        }
                    }
                    return 0;
                };

                document.querySelectorAll('[aria-label]').forEach(el => {
                    const aria = clean(el.getAttribute('aria-label') || '');
                    const text = clean(el.innerText || '');
                    const combined = `${aria} ${text}`;
                    if (/suka|like|reaction|reaksi/i.test(combined) && hasMetricNumber(combined)) out.likes_count = maxMetric(out.likes_count, combined);
                    if (/komentar|comment/i.test(combined) && hasMetricNumber(combined) && !/komentar oleh|comment by|beri komentar|write a comment|tulis komentar/i.test(combined)) out.comments_count = maxMetric(out.comments_count, combined);
                    if (/bagikan|share|kirim/i.test(combined) && hasMetricNumber(combined)) out.shares_count = maxMetric(out.shares_count, combined);
                    if (/tayangan|views|ditonton|viewed/i.test(combined) && hasMetricNumber(combined)) out.views_count = maxMetric(out.views_count, combined);
                });

                const inferVideoEngagementRow = () => {
                    const text = scopedText();
                    const primaryRow = text.match(/(?:\bSuka\b|\bLike\b)\s+(?:Komentari|Comment)\s+(?:Bagikan|Share)\s+([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i);
                    if (primaryRow) {
                        out.likes_count = parseNum(primaryRow[1]) || out.likes_count;
                        out.comments_count = parseNum(primaryRow[2]) || out.comments_count;
                        out.views_count = parseNum(primaryRow[3]) || out.views_count;
                        return;
                    }
                    const primaryRowNoLikes = text.match(/(?:\bSuka\b|\bLike\b)\s+(?:Komentari|Comment)\s+(?:Bagikan|Share)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)\s*(?:[^\w\d]+)\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i);
                    if (primaryRowNoLikes) {
                        out.comments_count = parseNum(primaryRowNoLikes[1]) || out.comments_count;
                        out.views_count = parseNum(primaryRowNoLikes[2]) || out.views_count;
                        return;
                    }
                };

                out.likes_count = Math.max(out.likes_count, scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:suka|likes?|reaksi|reactions?)/i,
                    /(?:suka|likes?|reaksi|reactions?)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]));
                out.comments_count = Math.max(out.comments_count, scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)/i,
                    /(?:komentar|comments?)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]));
                out.shares_count = Math.max(out.shares_count, scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:kali\s+dibagikan|x\s+dibagikan|dibagikan|shares?)/i,
                    /(?:dibagikan|shares?)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]));
                out.views_count = Math.max(out.views_count, scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i,
                    /(?:tayangan|views?|ditonton|viewed)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]));
                inferVideoEngagementRow();

                const chrome = /(notifikasi|belum dibaca|lihat semua|orang yang anda kenal|saran teman|selamat datang|welcome to facebook|masuk ke facebook|log in to facebook|filter|hasil pencarian|tanggal diposting|marketplace|halaman|grup|acara)/i;
                const pureMetric = /^([\d.,]+\s*(rb|ribu|k|jt|juta|m|mio|mn)?\s*(komentar|comments?|tayangan|views?|ditonton|suka|likes?|reaksi|reactions?|kali dibagikan|dibagikan|shares?))$/i;
                const metricish = /^([\d.,]+\s*(rb|ribu|k|jt|juta|m|mio|mn)?|[\d:]+|sukai?|komentari?|bagikan|kirim|share|like|comment|send)$/i;
                const okCaption = (t) => t && t.length >= 8 && t.length < 2200 && !chrome.test(t) && !metricish.test(t) && !pureMetric.test(t);

                // ── PRIMARY caption: the substantive line right before the ACTIVE clip's
                //    engagement controls ("Suka / Komentari / Bagikan"). Verified live via
                //    debug_caption_bug.py: og tags are empty on /watch, so the old
                //    "longest line on the page" grabbed comments or a sibling clip's caption.
                //    The active video's own caption always sits just above its action row. ──
                const captionFromRow = () => {
                    const mainEl = document.querySelector('[role="main"]') || document.body;
                    const lines = (mainEl.innerText || '').split(/\n+/).map(clean).filter(Boolean);
                    let rowIdx = -1;
                    for (let i = 0; i < lines.length; i++) {
                        if (/(?:^|\s)(?:suka|like)\b.*\b(?:komentari|comment)\b.*\b(?:bagikan|share)\b/i.test(lines[i])) { rowIdx = i; break; }
                        if (/^(?:suka|like)$/i.test(lines[i]) && i + 2 < lines.length && /^(?:komentari|comment)$/i.test(lines[i + 1]) && /^(?:bagikan|share)$/i.test(lines[i + 2])) { rowIdx = i; break; }
                    }
                    if (rowIdx <= 0) return '';
                    const skip = (t) => !t
                        || /^\d{1,2}:\d{2}(?::\d{2})?(?:\s*\/\s*\d{1,2}:\d{2}(?::\d{2})?)?$/.test(t)
                        || /^(?:lihat selengkapnya|selengkapnya|see more|lihat terjemahan|see translation|aktif|active)$/i.test(t)
                        || /^(?:suka|komentari|bagikan|like|comment|share|kirim|send)$/i.test(t)
                        || (/(?:·|ikuti|follow|diverifikasi)/i.test(t) && t.length < 45)
                        || metricish.test(t) || pureMetric.test(t);
                    for (let j = rowIdx - 1; j >= 0 && j >= rowIdx - 7; j--) {
                        if (skip(lines[j])) continue;
                        // Require real caption text (>= 2 words) so a bare author/page name
                        // sitting just above the row (e.g. "Kompas.com") is not taken as caption.
                        if (okCaption(lines[j]) && /\S\s+\S/.test(lines[j])) return lines[j];
                    }
                    return '';
                };
                const rowCaption = captionFromRow();
                if (rowCaption) { out.caption = rowCaption; out.caption_reliable = true; }

                const og = clean(document.querySelector('meta[property="og:description"],meta[name="description"]')?.getAttribute('content') || '');
                if (!out.caption && okCaption(og)) { out.caption = og; out.caption_reliable = true; }

                if (!out.caption) {
                    const selectors = ['[data-ad-preview="message"]', '[data-ad-comet-preview="message"]', '[data-testid="post_message"]'];
                    for (const sel of selectors) {
                        const text = clean(document.querySelector(sel)?.textContent || '');
                        if (okCaption(text)) { out.caption = text; out.caption_reliable = true; break; }
                    }
                }

                if (!out.caption) {
                    // Low-confidence fallback (caption_reliable stays false): only used by the
                    // caller for non-video posts, where the page is a single post not a feed.
                    let best = '';
                    document.querySelectorAll('[role="article"], [role="main"], [role="complementary"]').forEach(scope => {
                        const lines = (scope.innerText || '').split(/\n+/).map(clean).filter(Boolean);
                        for (const line of lines) {
                            if (!okCaption(line)) continue;
                            if (/durasi video|diverifikasi|yang lalu|\btayangan\b/i.test(line)) continue;
                            if (/^\d{1,2}:\d{2}(?::\d{2})?(?:\s*\/\s*\d{1,2}:\d{2}(?::\d{2})?)?$/.test(line)) continue;
                            if (line.length > best.length) best = line;
                        }
                    });
                    out.caption = best;
                }

                const authorEl = document.querySelector('h1 a[role="link"], h2 a[role="link"], h3 a[role="link"], strong[dir="auto"], a[role="link"] strong');
                out.author = clean(authorEl?.innerText || '');
                return out;
            }
            """)
        except Exception as e:
            print(Fore.YELLOW+f"     [DETAIL] metadata extract error: {e}")
            return {}

    def enrich_missing_details(self, posts, limit=None, progress_callback=None):
        if not posts:
            return posts
        try:
            limit = int(limit if limit is not None else FB_DETAIL_ENRICH_LIMIT)
        except Exception:
            limit = FB_DETAIL_ENRICH_LIMIT
        if limit <= 0:
            return posts

        def _detail_priority(item: dict):
            url = (item.get("url") or "").lower()
            is_video = _is_video_item(item)
            incomplete = _metric_value(item.get("shares_count")) == 0 or _metric_value(item.get("views_count")) == 0 or not item.get("metrics_valid")
            return (1 if is_video else 0, 1 if incomplete else 0, _engagement_score(item))

        targets = [p for p in posts if self._needs_detail_enrich(p)]
        if not targets:
            return posts
        self.initialize_browser()
        targets.sort(key=_detail_priority, reverse=True)
        targets = targets[:limit]
        tab = self._new_page()
        try:
            for idx, post in enumerate(targets, 1):
                url = post.get("url", "")
                if progress_callback:
                    progress_callback(f"Detail metadata {idx}/{len(targets)}")
                try:
                    print(Fore.CYAN+f"     [DETAIL] {idx}/{len(targets)} {url[:70]}...")
                    is_video = _is_video_item(post)
                    detail_metrics = None
                    if is_video:
                        detail_metrics = self.extract_detail_metrics(tab, url)
                        post["detail_status"] = detail_metrics.get("detail_status") or "unknown"
                        post["metrics_error"] = detail_metrics.get("metrics_error")
                        post["detail_final_url"] = detail_metrics.get("detail_final_url")
                        if detail_metrics.get("metrics_valid"):
                            for src_key, dst_key in [
                                ("likes_count", "likes_count"),
                                ("comments_count", "comments_count"),
                                ("shares_count", "shares_count"),
                                ("views_count", "views_count"),
                            ]:
                                val = detail_metrics.get(src_key)
                                if val is not None:
                                    post[dst_key] = int(val)
                            post["metrics_valid"] = True
                            post["metrics_unverified"] = False
                            post["metric_source"] = detail_metrics.get("metric_source") or "detail_page_text"
                            post["metric_patterns"] = detail_metrics.get("matched_patterns", {})
                        else:
                            post["metrics_valid"] = False
                            post["metric_source"] = detail_metrics.get("metric_source") or post.get("metric_source") or "detail_page_text"
                    else:
                        nav = self.safe_goto(tab, url, timeout=45000, retries=3)
                        post["detail_status"] = nav.get("status") or "unknown"
                        if not nav.get("ok"):
                            raise RuntimeError(nav.get("error") or "navigation_failed")
                        time.sleep(random.uniform(FB_DETAIL_WAIT_SECONDS, FB_DETAIL_WAIT_SECONDS + 0.6))
                        self._close_popups(tab)
                        try:
                            tab.evaluate("window.scrollBy(0, 500)")
                            time.sleep(0.4)
                        except Exception:
                            pass
                    meta = self._extract_detail_metadata(tab)
                    final_url = post.get("detail_final_url") or getattr(tab, "url", "") or ""
                    if final_url:
                        post["detail_final_url"] = final_url
                    input_key = _fb_content_key(url)
                    final_key = _fb_content_key(final_url)
                    if input_key and final_key and input_key != final_key and "/share/" not in (url or "").lower():
                        post["link_valid"] = False
                        post["open_url_validated"] = False
                        post["link_sync_error"] = f"detail_final_url_mismatch:{input_key}->{final_key}"
                    else:
                        post["link_valid"] = True
                        post["open_url_validated"] = True
                    if not is_video:
                        for src_key, dst_key in [
                            ("likes_count", "likes_count"),
                            ("comments_count", "comments_count"),
                            ("shares_count", "shares_count"),
                            ("views_count", "views_count"),
                        ]:
                            val = int(meta.get(src_key, 0) or 0)
                            if dst_key == "views_count" and val > 0:
                                has_detail_engagement = any(int(meta.get(k, 0) or 0) > 0 for k in ("likes_count", "comments_count", "shares_count"))
                                has_existing_engagement = any(_metric_value(post.get(k)) > 0 for k in ("likes_count", "comments_count", "shares_count"))
                                if has_detail_engagement or has_existing_engagement:
                                    post[dst_key] = val
                            elif val > _metric_value(post.get(dst_key)):
                                post[dst_key] = val
                        if any(int(meta.get(k, 0) or 0) > 0 for k in ("likes_count", "comments_count", "shares_count", "views_count")):
                            post["metrics_valid"] = True
                            post["metrics_unverified"] = False
                            post["metric_source"] = "detail_page"
                    caption = (meta.get("caption") or "").strip()
                    caption_reliable = bool(meta.get("caption_reliable"))
                    current = (post.get("caption") or post.get("text") or "").strip()
                    if caption:
                        overlap = _text_token_overlap(current, caption) if current else 0.0
                        search_only_source = (post.get("source") or "").lower() in {"dom", "generic", "generic_article", "html_embedded"}
                        if current and search_only_source and overlap < 0.28:
                            post["search_caption_mismatch"] = True
                            post["search_caption_before_detail"] = current[:500]
                            post["caption_match_score"] = round(overlap, 3)
                        # /watch is a feed: only adopt the detail caption when it was anchored
                        # to the ACTIVE clip (caption_reliable). For a video whose detail caption
                        # is the low-confidence longest-line fallback, keep the search-card caption
                        # (bound to this URL at scrape time) instead of a sibling/comment text.
                        trust_detail = caption_reliable or not is_video
                        if trust_detail and ((not current) or search_only_source or len(caption) > len(current)):
                            post["caption"] = caption[:1000]
                            post["text"] = caption[:1000]
                            post["caption_source"] = "detail_page"
                    author = (meta.get("author") or "").strip()
                    current_author = str(post.get("author") or "")
                    if author and (current_author in ("", "Unknown") or re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", current_author)):
                        post["author"] = author[:100]
                    post["engagement_score"] = _engagement_score(post)
                    assign_viral_fields(post)
                    post["detail_enriched"] = True
                except Exception as e:
                    print(Fore.YELLOW+f"     [DETAIL] skip: {e}")
                    post["detail_enrich_failed"] = True
                    post["detail_status"] = "detail_failed"
                    post["metrics_error"] = str(e)[:1000]
                    if _is_video_item(post):
                        post["metrics_valid"] = False
                        for key in ("likes_count", "comments_count", "views_count", "shares_count"):
                            if post.get(key) == 0:
                                post[key] = None
                        self._save_detail_debug_snapshot(url, tab, str(e))
        finally:
            try:
                tab.close()
            except Exception:
                pass
        return posts

    # ======================================================================
    #  GROUPS: extract group info (name + about) from search results
    # ======================================================================
    def _extract_group_posts(self, page, max_items=100, keyword=""):
        """
        FB /search/groups/?q=keyword = daftar grup yang namanya cocok keyword.
        Strategi: extract GROUP INFO (name + about/description) dari search results.
        """
        results=[]; seen_urls=set()

        print(Fore.CYAN+f"   [GROUPS] Mengumpulkan info grup untuk '{keyword}'...")

        _JS_GROUP_INFO = r"""
        () => {
            const r=[];
            const cards = document.querySelectorAll('[role="article"], [aria-posinset]');
            cards.forEach(card => {
                try {
                    const item = {name: '', about: '', members: '', url: ''};

                    const nameEl = card.querySelector('h1, h2, h3, a[href*="/groups/"]');
                    if (nameEl) {
                        const t = (nameEl.innerText || '').trim();
                        if (t.length >= 2 && t.length < 100) item.name = t;
                    }

                    const linkEl = card.querySelector('a[href*="/groups/"]');
                    if (linkEl) {
                        const h = linkEl.getAttribute('href') || '';
                        if (/\/groups\/[a-zA-Z0-9._-]+\/?$/.test(h.split('?')[0])) {
                            const path = h.startsWith('http') ? new URL(h).pathname : h.split('?')[0];
                            item.url = 'https://www.facebook.com' + path.replace(/\/$/, '') + '/';
                        }
                    }

                    const allText = (card.innerText || '').replace(/\n/g, ' | ');
                    const lines = allText.split('|').map(l => l.trim()).filter(l => l.length > 5);

                    for (const line of lines) {
                        if (/^Grup\s+(Publik|Privat|Tertutup)/i.test(line)) {
                            item.about = line;
                            break;
                        }
                        if (/\d+[.,]?\d*\s*(rb|ribu|k|jt|juta)?\s*anggota/i.test(line.toLowerCase())) {
                            item.members = line;
                        }
                    }

                    if (!item.about && item.name) {
                        const nameIdx = lines.findIndex(l => l === item.name);
                        if (nameIdx >= 0 && nameIdx + 1 < lines.length) {
                            item.about = lines[nameIdx + 1].slice(0, 200);
                        }
                    }

                    if (item.name && item.url) r.push(item);
                } catch(e) {}
            });
            return r.slice(0, 10);
        }
        """

        all_groups = []
        for _ in range(5):
            batch = page.evaluate(_JS_GROUP_INFO)
            for g in batch:
                if g['url'] not in [x['url'] for x in all_groups]:
                    all_groups.append(g)
            if len(all_groups) >= 10: break
            page.evaluate("window.scrollBy(0,1500)")
            time.sleep(1)

        print(Fore.CYAN+f"   [GROUPS] Ditemukan {len(all_groups)} grup")

        # FIX: inisialisasi detail_page = None dulu, baru buat Page jika all_groups tidak kosong
        # Ini mencegah Pylance error "goto/evaluate is not a known attribute of None"
        detail_page = None
        try:
            if all_groups:
                detail_page = self._new_page()
            for g in all_groups:
                if not detail_page:
                    continue
                try:
                    detail_url = g['url'].split('?', 1)[0].rstrip('/') + '/about'
                    detail_page.goto(detail_url, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(1.5)
                    detail = detail_page.evaluate(r"""  
                    () => {
                        const meta=(document.querySelector('meta[property="og:description"]')||document.querySelector('meta[name="description"]'))?.content||'';
                        let about='';
                        for(const h of document.querySelectorAll('h1,h2,h3,span[dir="auto"]')){
                            if(!/^(tentang grup ini|about this group)$/i.test((h.innerText||'').trim()))continue;
                            let p=h.parentElement;
                            for(let i=0;p&&i<5;i++,p=p.parentElement){
                                const lines=(p.innerText||'').split(/\n+/).map(x=>x.trim()).filter(Boolean);
                                const candidates=lines.filter(x=>x.length>20&&!/^(tentang grup ini|about this group|privat|publik|private|public)$/i.test(x));
                                if(candidates.length){about=candidates.sort((a,b)=>b.length-a.length)[0];break;}
                            }
                            if(about)break;
                        }
                        return {about:about||meta, title:(document.querySelector('meta[property="og:title"]')?.content||'')};
                    }
                    """)  # type: ignore[union-attr]
                    if detail.get('about'):
                        g['about'] = detail['about'][:1000]
                    if not g.get('name') and detail.get('title'):
                        g['name'] = detail['title'][:100]
                except Exception as e:
                    print(Fore.YELLOW+f"   [GROUPS] About gagal untuk {g.get('name','')[:30]}: {e}")
        finally:
            if detail_page:
                try: detail_page.close()
                except: pass

        for g in all_groups:
            if len(results) >= max_items: break
            item = {
                'url': g.get('url', ''),
                'author': g.get('name', ''),
                'text': g.get('about', ''),
                'caption': g.get('about', ''),
                'timestamp': '',
                'type': 'groups',
                'likes_count': 0,
                'comments_count': 0,
                'views_count': 0,
                'shares_count': 0,
                'images': [],
                'media_urls': [],
                'media_count': 0,
                'engagement_score': 0,
                'source': 'group_info',
                'group_name': g.get('name', ''),
                'group_about': g.get('about', ''),
                'group_members': g.get('members', ''),
                'group_category': '',
            }
            if keyword and not _keyword_in_item(item, keyword):
                continue
            results.append(item)
            print(Fore.GREEN+f"   [GROUPS] +1 grup: {g.get('name', '')[:50]}")

        if not results:
            print(Fore.YELLOW+f"   [GROUPS] Tidak ada grup yang cocok — skip")

        return results[:max_items]

    # ======================================================================
    #  PAGES: extract page posts
    # ======================================================================
    def _extract_page_posts(self, page, max_items=100, keyword=""):
        results=[]; seen_urls=set()

        print(Fore.CYAN+f"   [PAGES] Mengumpulkan daftar halaman untuk '{keyword}'...")
        if FB_PAGE_DEEP_OPEN_LIMIT <= 0:
            print(Fore.YELLOW+"   [PAGES] Deep-open halaman dinonaktifkan (FB_PAGE_DEEP_OPEN_LIMIT=0) untuk mode cepat")
            return []
        page_urls = []
        _JS_PAGES = r"""
        () => {
            const urls=new Set();
            document.querySelectorAll('a[href*="/"]').forEach(a=>{
                const h=(a.getAttribute('href')||'').split('?')[0].split('#')[0];
                if(h.includes('/groups/')||h.includes('/search/')||h.includes('/help/')||h.includes('/legal/')||h.includes('/privacy/')||h.includes('/policies/')||h.includes('/settings/'))return;
                if(/\/profile\.php$/.test(h)){urls.add(h.startsWith('http')?h:'https://www.facebook.com'+h);return;}
                const m=h.match(/^\/([a-zA-Z0-9._-]{3,})\/?$/);
                if(m){
                    const name=m[1].toLowerCase();
                    if(['home','watch','reels','gaming','marketplace','groups','pages','events','videos','photos','posts','permalink','stories','bookmark','notifications','settings','friends','messages','feed','timeline','about','community'].includes(name))return;
                    urls.add(h.startsWith('http')?h:'https://www.facebook.com'+h);
                }
            });
            return Array.from(urls).slice(0,10);
        }
        """
        for _ in range(5):
            batch = page.evaluate(_JS_PAGES)
            for u in batch:
                if u not in page_urls: page_urls.append(u)
            if len(page_urls)>=5: break
            page.evaluate("window.scrollBy(0,1500)")
            time.sleep(1)

        if FB_PAGE_DEEP_OPEN_LIMIT > 0:
            page_urls = page_urls[:FB_PAGE_DEEP_OPEN_LIMIT]
        print(Fore.CYAN+f"   [PAGES] Ditemukan {len(page_urls)} halaman, buka tiap halaman...")

        _JS_PAGE_FEED = r"""
        (keyword) => {
            const kw=(keyword||'').toLowerCase();
            const kwnospace=(kw||'').replace(/[\s-]/g,'');
            const r=[]; const s=new Set();
            const parseNum=(text)=>{
                const m=(text||'').toLowerCase().replace(/\u00a0/g,' ').match(/([\d.,]+)\s*(rb|ribu|k|jt|juta|m|mio)?/i);
                if(!m)return 0;
                let n=parseFloat(m[1].replace(/\./g,'').replace(',','.'));
                const sf=(m[2]||'').toLowerCase();
                if(sf==='k'||sf==='rb'||sf==='ribu')n*=1000;
                else if(sf==='m'||sf==='jt'||sf==='juta'||sf==='mio')n*=1000000;
                return Math.floor(n)||0;
            };
            const extractImages=(node)=>{
                const imgs=[];
                node.querySelectorAll('img[src*="scontent"],img[src*="fbcdn"]').forEach(im=>{
                    const src=im.getAttribute('src')||'';
                    const w=im.naturalWidth||im.width||0;
                    const h=im.naturalHeight||im.height||0;
                    if(src&&!imgs.includes(src)&&(w===0||w>=120)&&(h===0||h>=80))imgs.push(src);
                });
                return imgs.slice(0,6);
            };
            const kwMatch=(text)=>{
                if(!kw)return true;
                const low=(text||'').toLowerCase();
                if(low.includes(kw))return true;
                if(kwnospace&&kwnospace.length>=4){
                    const nospace=low.replace(/[\s-]/g,'');
                    if(nospace.includes(kwnospace))return true;
                }
                return false;
            };
            document.querySelectorAll('[role="feed"] [aria-posinset],[role="article"]').forEach(c=>{
                try{
                    const ls=c.querySelectorAll('a[href*="/"]');
                    let url='',author='',txt='';
                    for(const a of ls){
                        const h=(a.getAttribute('href')||'').split('?')[0].split('#')[0];
                        if(/\/[^/]+\/(posts|photos|videos)\/\d+/.test(h)||/\/permalink\/\d+/.test(h)||/\/photo\/?\?fbid=\d+/.test(h)){
                            url=h.startsWith('http')?h:'https://www.facebook.com'+h;
                            break;
                        }
                    }
                    if(!url||s.has(url))return;
                    const ac=c.querySelector('strong[dir="auto"],h2,h3,h4,a[role="link"]');
                    if(ac)author=(ac.innerText||'').trim().slice(0,100);
                    c.querySelectorAll('span[dir="auto"],div[dir="auto"]').forEach(el=>{
                        const t=(el.innerText||'').trim();
                        if(t.length>txt.length&&t.length<3000&&t!==author)txt=t;
                    });
                    if(kw&&!kwMatch(txt)&&!kwMatch(author))return;
                    let likes=0,comms=0,views=0,shares=0;
                    const fullText=(c.innerText||'').replace(/\u00a0/g,' ');
                    const vm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:tayangan|views|ditonton)/i);
                    if(vm)views=parseNum(vm[0]);
                    c.querySelectorAll('[aria-label]').forEach(el=>{
                        const aria=(el.getAttribute('aria-label')||'').toLowerCase();
                        const tx=(el.innerText||'').trim();
                        if(aria.includes('suka')||aria.includes('like')){
                            likes=Math.max(likes,parseNum(tx+' '+aria));
                        }
                        if(aria.includes('komentar')||aria.includes('comment')){
                            comms=Math.max(comms,parseNum(tx+' '+aria));
                        }
                        if(aria.includes('bagikan')||aria.includes('share')){
                            const num=parseNum(tx+' '+aria);
                            if(num>0)shares=Math.max(shares,num);
                        }
                    });
                    if(!shares){
                        const sm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:kali\s+dibagikan|dibagikan|shares?)/i);
                        if(sm)shares=parseNum(sm[0]);
                    }
                    const images=extractImages(c);
                    s.add(url);
                    r.push({url,author:author||'Unknown',text:txt.slice(0,1000),caption:txt.slice(0,1000),
                        timestamp:'',type:'pages',likes_count:likes||0,comments_count:comms||0,
                        views_count:views||0,shares_count:shares||0,images,media_urls:images,media_count:images.length,
                        engagement_score:likes+comms*2+views,source:'page_feed'});
                }catch(e){}
            });
            return r;
        }
        """

        tab = None
        for p_url in page_urls:
            if len(results) >= max_items: break
            try:
                tab = self._new_page()
                print(Fore.CYAN+f"   [PAGES] Buka: {p_url}")
                tab.goto(p_url, wait_until="domcontentloaded", timeout=20000)
                time.sleep(3)
                self._close_popups(tab)
                for _ in range(4):
                    tab.evaluate("window.scrollBy(0,1500)")
                    time.sleep(1)
                batch = tab.evaluate(_JS_PAGE_FEED, keyword or '')
                n = 0
                for item in batch:
                    u = item.get('url','')
                    key = _fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u):
                        if keyword and not _keyword_in_item(item, keyword):
                            continue
                        seen_urls.add(key); results.append(item); n+=1
                print(Fore.CYAN+f"   [PAGES] +{n} posts dari {p_url} (total: {len(results)})")
            except Exception as e:
                print(Fore.YELLOW+f"   [PAGES] Skip {p_url}: {e}")
            finally:
                if tab:
                    try: tab.close()
                    except: pass
                    tab = None

        if not results:
            print(Fore.YELLOW+f"   [PAGES] Tidak ada post halaman yang mengandung '{keyword}' — skip")

        return results[:max_items]

    # ======================================================================
    #  UNIFIED SCRAPE
    # ======================================================================
    def _scrape_search_url(self,url,keyword="",max_results=100,search_type="posts",page=None,strict_keyword=True):
        p=page or self.pg
        all_results=[]; seen_urls=set()
        print(Fore.YELLOW+f"\n[NAV] {url[:80]}")
        try:
            # ✅ FIX: Setup GQL interceptor SEBELUM goto agar tidak miss responses
            gql_sid, gql_data, gql_urls = self._setup_gql(p)
            last_nav_error = None
            for attempt in range(2):
                try:
                    p.goto(url,wait_until="domcontentloaded",timeout=30000)
                    last_nav_error = None
                    break
                except Exception as nav_err:
                    last_nav_error = nav_err
                    print(Fore.YELLOW+f"   [NAV] retry {attempt+1}/2 after navigation error: {nav_err}")
                    try:
                        p.goto("about:blank",wait_until="domcontentloaded",timeout=5000)
                    except Exception:
                        pass
                    time.sleep(1.0)
            if last_nav_error:
                raise last_nav_error
            # ✅ FIX: Tambah wait lebih lama agar GQL sempat di-intercept
            time.sleep(FB_SEARCH_LOAD_SECONDS)
            self._close_popups(p)
            # ✅ FIX: Scroll beberapa kali untuk trigger lazy load GQL
            for _ in range(max(0, FB_SEARCH_PRE_SCROLLS)):
                try:
                    p.evaluate("window.scrollBy(0, 800)")
                except Exception as e:
                    print(Fore.YELLOW+f"   [NAV] pre-scroll interrupted: {e}")
                    break
                time.sleep(FB_SEARCH_SCROLL_DELAY)
            time.sleep(min(0.3, FB_SEARCH_SCROLL_DELAY))
            if search_type == "posts":
                for item in self._extract_feed(p,max_results,keyword):
                    self._prepare_item_metrics(item)
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and (item.get("source") == "search_post_card" or _is_valid_result_url(u)):
                        seen_urls.add(key); all_results.append(item)
            else:
                for item in self._extract_generic(p,max_results,search_type,keyword):
                    self._prepare_item_metrics(item)
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u): seen_urls.add(key); all_results.append(item)
            # ✅ FIX: Coba GQL bahkan jika DOM extraction sudah berhasil (tambah lebih banyak)
            if len(all_results) < max_results:
                print(Fore.YELLOW+f"   [GQL-FALLBACK] Trying GraphQL ({len(gql_data)} responses)...")
                for item in self._extract_gql(gql_data,keyword,strict_keyword):
                    self._prepare_item_metrics(item)
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u): seen_urls.add(key); all_results.append(item)
                if gql_data: print(Fore.GREEN+f"   [GQL] +{len(all_results)} total after GQL")
            if not all_results:
                print(Fore.YELLOW+"   [HTML-FALLBACK] Parsing embedded page JSON/HTML...")
                for item in self._extract_embedded_html(p, max_results, "", search_type):
                    self._prepare_item_metrics(item)
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u):
                        seen_urls.add(key); all_results.append(item)
        except Exception as e: print(Fore.RED+f"   [FAIL] {e}")
        return all_results[:max_results]

    # ======================================================================
    #  MULTI-TAB SCRAPE
    # ======================================================================
    def _parallel_scrape_types(self,keyword,types,max_results):
        all_results=[]; seen_urls=set()
        active_types=list(dict.fromkeys(types or ['posts']))
        # ✅ FIX: per_type lebih besar agar total bisa mencapai max_results
        # Bagi merata tapi minimal 200 per tipe agar ada cukup hasil
        per_type=min(max_results, max(FB_PER_TYPE_MIN, math.ceil(max_results/len(active_types))))
        for i,st in enumerate(active_types):
            if i>0: time.sleep(FB_TYPE_SWITCH_DELAY)
            print(Fore.CYAN+f"\n   [TAB] '{keyword}' type={st}...")
            tab=self._new_page()
            try:
                urls = [f"https://www.facebook.com/search/{st}/?q={quote(keyword)}"]
                for surface_idx, url in enumerate(urls, 1):
                    if len(all_results) >= max_results:
                        break
                    for item in self._scrape_search_url(url,keyword,per_type,st,page=tab):
                        u=item.get('url','')
                        key=_fb_content_key(u) or u
                        if u and key not in seen_urls and (item.get("source") == "search_post_card" or _is_valid_result_url(u)):
                            seen_urls.add(key);item["deep_source_type"]="reels" if "/search/reels/" in url else st;all_results.append(item)
                print(Fore.GREEN+f"   [OK] {st}: {len(all_results)} items total")
            except Exception as e: print(Fore.RED+f"   [FAIL] {st}: {e}")
            finally:
                try: tab.close()
                except: pass
        return all_results[:max_results]

    # ======================================================================
    #  COMMENT SCRAPING v5.3
    # ======================================================================
    def _scrape_post_comments(self,post_url,max_comments=10,top_comments_count=10,page=None):
        result={"top_comments":[],"other_comments":[],"comments_scraped_count":0,"comments_scrape_failed":False}
        if max_comments<=0: return result
        if not _is_commentable_url(post_url):
            print(Fore.YELLOW+f"     [SKIP] {post_url[:60]} (not commentable)"); result["comments_scrape_failed"]=True; return result
        p=page or self.pg; deadline=time.time()+max(20, min(60, max_comments * 2))
        all_c=[]; seen_t=set()
        try:
            print(Fore.CYAN+f"     [COMMENTS] {post_url[:60]}...")
            p.goto(post_url,wait_until="domcontentloaded",timeout=15000)
            loaded=False
            for _ in range(6):
                if time.time()>deadline: break
                try:
                    if p.evaluate("document.querySelectorAll('[role=\"article\"]').length>0"): loaded=True; break
                except: pass
                time.sleep(1)
            if not loaded: time.sleep(3)
            self._close_popups(p)
            p.evaluate("window.scrollTo(0,document.body.scrollHeight)")
            time.sleep(1.5)
            more=0
            _JS_COMMENTS = r"""
            (maxItems) => {
                const r=[]; const st=new Set();
                const parseNum=(text)=>{
                    if(!text)return 0;
                    const raw=(text+'').toLowerCase().replace(/\u00a0/g,' ').trim();
                    // Coba format "N,N rb" atau "N.N k" atau "N jt"
                    const m=raw.match(/([\d]+(?:[.,][\d]+)?)\s*(rb|ribu|k|jt|juta|m|mio|mn)?/i);
                    if(!m)return 0;
                    let n=parseFloat(m[1].replace(',','.'));
                    if(isNaN(n))return 0;
                    const sf=(m[2]||'').toLowerCase();
                    if(sf==='k'||sf==='rb'||sf==='ribu')n=Math.floor(n*1000);
                    else if(sf==='m'||sf==='jt'||sf==='juta'||sf==='mio'||sf==='mn')n=Math.floor(n*1000000);
                    else n=Math.floor(n);
                    return n||0;
                };

                // Strategi 1: artikel komentar dengan aria-label lengkap (versi desktop/bahasa)
                let cs=[
                    ...document.querySelectorAll('[aria-label^="Komentar oleh "]'),
                    ...document.querySelectorAll('[aria-label^="Comment by "]'),
                ];
                // Strategi 2: fallback ke div UFI (versi lama)
                if(!cs.length){
                    cs=[...document.querySelectorAll('div[data-testid="UFI2Comment/body"],div[data-testid="UFI2Comment"]')];
                }
                // Strategi 3: role="article" di dalam section komentar
                if(!cs.length){
                    const allArts=[...document.querySelectorAll('[role="article"]')];
                    // Lewati artikel pertama (itu postingannya sendiri)
                    cs=allArts.slice(1).filter(a=>{
                        const al=(a.getAttribute('aria-label')||'').toLowerCase();
                        return al.includes('komentar')||al.includes('comment')||al.includes('balasan')||al.includes('reply');
                    });
                    if(!cs.length&&allArts.length>1)cs=allArts.slice(1);
                }

                cs.forEach(c=>{try{
                    const aria=(c.getAttribute('aria-label')||'').trim();
                    const am=aria.match(/^(?:Komentar oleh|Comment by)\s+(.+?)(?:\s+(\d+\s*(?:detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year)s?(?:\s+(?:yang lalu|ago))?))?$/i);
                    let au=am?am[1].trim():'';
                    let timestamp=am&&am[2]?am[2].trim():'';

                    // Fallback nama dari link/strong
                    if(!au){
                        const linkEl=c.querySelector('a[role="link"] span[dir="auto"]')||
                                     c.querySelector('strong[dir="auto"]')||
                                     c.querySelector('a[role="link"]');
                        if(linkEl)au=(linkEl.innerText||'').trim().slice(0,100);
                    }
                    if(!au)au='Unknown';

                    // Ekstrak timestamp jika belum ada
                    if(!timestamp){
                        const tsEl=c.querySelector('a[href*="comment_id"],abbr[data-utime],a[aria-label*="jam"],a[aria-label*="menit"],a[aria-label*="detik"],a[aria-label*="hari"],a[aria-label*="minggu"]');
                        if(tsEl){
                            const tsLabel=tsEl.getAttribute('aria-label')||tsEl.innerText||'';
                            const tsMatch=tsLabel.match(/\d+\s*(?:detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year)/i);
                            if(tsMatch)timestamp=tsMatch[0].trim();
                        }
                    }

                    // Ambil teks komentar — kecualikan: nama author, timestamp, tombol aksi
                    const lines=(c.innerText||'').split(/\n+/).map(x=>x.trim()).filter(Boolean);
                    const SKIP=/^(suka|like|balas|reply|lihat\s+balasan|view\s+replies?|lihat\s+lebih|see\s+more|pembuat|author|top\s+contributor|·|•|\d+[ws]|\d+\s*(detik|menit|jam|hari|minggu|bulan|tahun))$/i;
                    const bodies=lines.filter(x=>x&&x!==au&&!SKIP.test(x)&&!/^\d+\s*(detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year)/i.test(x));
                    // Pilih teks terpanjang sebagai isi komentar
                    const t=bodies.sort((a,b)=>b.length-a.length)[0]||'';
                    if(!t||st.has(t)||t.length<2)return;

                    // ── Ekstrak likes komentar — multi-strategi ──
                    let likes=0;

                    // S1: aria-label "Suka: N orang" / "Like: N people"
                    const reactionEl=c.querySelector(
                        '[aria-label*="Suka:"][aria-label*="orang"],' +
                        '[aria-label*="Like:"][aria-label*="people"],' +
                        '[aria-label*="reactions"],' +
                        '[aria-label*="reaksi"]'
                    );
                    if(reactionEl){
                        const rLabel=reactionEl.getAttribute('aria-label')||'';
                        const rMatch=rLabel.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m)?)/i);
                        if(rMatch)likes=parseNum(rMatch[1]);
                    }

                    // S2: tombol suka komentar (span dengan angka di sebelah heart icon)
                    if(!likes){
                        c.querySelectorAll('[aria-label*="suka"],[aria-label*="Suka"],[aria-label*="like"],[aria-label*="Like"]').forEach(el=>{
                            if(likes>0)return;
                            // Ambil span angka di dekatnya
                            const parent=el.parentElement||el;
                            const spans=[...parent.querySelectorAll('span,div')];
                            for(const sp of spans){
                                const t2=(sp.innerText||'').trim();
                                if(/^[\d.,]+\s*(rb|ribu|k|jt|juta|m)?$/i.test(t2)&&t2.length<10){
                                    const n=parseNum(t2);
                                    if(n>0){likes=n;break;}
                                }
                            }
                        });
                    }

                    // S3: cari angka setelah tombol "Suka" di teks artikel
                    if(!likes){
                        const actionIdx=lines.findIndex(x=>/^(suka|like)$/i.test(x));
                        if(actionIdx>=0){
                            for(let i=actionIdx+1;i<Math.min(actionIdx+4,lines.length);i++){
                                if(/^[\d.,]+\s*(rb|ribu|k|jt|juta|m)?$/i.test(lines[i])){
                                    likes=parseNum(lines[i]);break;
                                }
                            }
                        }
                    }

                    st.add(t);
                    r.push({
                        comment_author:au,
                        comment_text:t.slice(0,2000),
                        comment_likes:likes,
                        comment_timestamp:timestamp,
                        is_reply:false
                    });
                }catch(e){}});
                return r;
            }
            """
            while len(all_c)<max_comments and time.time()<deadline and more<15:
                try:
                    batch=p.evaluate(_JS_COMMENTS, max_comments-len(all_c))
                    for c in batch:
                        ct=c.get("comment_text","")
                        if ct and len(ct)>2 and ct not in seen_t: seen_t.add(ct); all_c.append(c)
                except: pass
                if len(all_c)>=max_comments: break
                _JS_EXPAND = r"""
                () => {
                    for(const b of document.querySelectorAll('[role="button"],[aria-label*="Komentar"],[aria-label*="Comment"]')){
                        const t=(b.innerText||'').toLowerCase();
                        if((t.includes('lihat')||t.includes('more')||t.includes('balasan')||t.includes('view')||t.includes('load'))&&b.offsetParent!==null){b.click();return true}
                    }
                    for(const b of document.querySelectorAll('span[dir="auto"]')){
                        const t=(b.innerText||'').toLowerCase();
                        if((t.includes('lihat komentar')||t.includes('lihat balasan')||t.includes('more comments'))&&b.offsetParent!==null){b.click();return true}
                    }
                    return false;
                }
                """
                try:
                    cl=p.evaluate(_JS_EXPAND)
                    if cl: more+=1; time.sleep(random.uniform(1.5,2.5))
                    else: break
                except: break
        except Exception as e:
            print(Fore.YELLOW+f"     [COMMENTS] Error: {e}"); result["comments_scrape_failed"]=True; return result
        all_c.sort(key=lambda c:c.get("comment_likes",0),reverse=True)
        top_count=max(1, min(int(top_comments_count or 10), len(all_c) or 1))
        result["top_comments"]=all_c[:top_count]; result["other_comments"]=all_c[top_count:]
        result["comments_scraped_count"]=len(all_c)
        if len(all_c)==0: result["comments_scrape_failed"]=True
        print(Fore.GREEN+f"     [COMMENTS] Done: {len(all_c)} comments, top {top_count} by likes")
        return result

    # ======================================================================
    #  PUBLIC APIs
    # ======================================================================
    def enrich_comments(self, posts, max_comments_per_post=0, top_comments_count=10,
                        progress_callback=None):
        """Attach comments once to each final, unique, commentable result."""
        if max_comments_per_post <= 0 or not posts:
            return posts
        self.initialize_browser()
        commentable=[p for p in posts if _is_commentable_url(p.get('url',''))]
        for idx,post in enumerate(commentable):
            if progress_callback:
                progress_callback(f"Comments {idx+1}/{len(commentable)}")
            tab=self._new_page()
            try:
                cd=self._scrape_post_comments(
                    post.get("url", ""), max_comments_per_post,
                    top_comments_count, page=tab,
                )
                post["top_comments"]=cd.get("top_comments",[])[:top_comments_count]
                post["other_comments"]=cd.get("other_comments",[])
                post["comments_scraped_count"]=cd.get("comments_scraped_count",0)
                if cd.get("comments_scrape_failed"):
                    post["comments_scrape_failed"]=True
            except Exception:
                post["comments_scrape_failed"]=True
            finally:
                try: tab.close()
                except: pass
        return posts

    def scrape_keyword(self,raw_keyword,max_results=1000,types=None,sort_by="trending",
                       min_likes=None,min_comments=None,min_views=None,
                       max_comments_per_post=0,top_comments_count=10,progress_callback=None,
                       detail_enrich_limit=None):
        if types is None: types=['posts']
        keyword=self._clean_keyword(raw_keyword)
        print(Fore.CYAN+f"\n[KEYWORD] {keyword} | Max:{max_results}")
        self.initialize_browser()
        all_results=self._parallel_scrape_types(keyword,types,max_results)
        self.enrich_missing_details(
            all_results,
            limit=detail_enrich_limit,
            progress_callback=progress_callback,
        )
        if max_comments_per_post>0 and all_results:
            commentable=[p for p in all_results if _is_commentable_url(p.get('url',''))]
            posts_for_c=sorted(commentable,key=lambda p:_engagement_score(p),reverse=True)
            if posts_for_c:
                print(Fore.YELLOW+f"\n[COMMENTS] {len(posts_for_c)} posts (filtered {len(all_results)-len(commentable)} non-commentable)...")
                for idx,post in enumerate(posts_for_c):
                    if progress_callback: progress_callback(f"Comments {idx+1}/{len(posts_for_c)}")
                    tab=self._new_page()
                    try:
                        cd=self._scrape_post_comments(post.get("url",""),max_comments_per_post,top_comments_count,page=tab)
                        post["top_comments"]=cd.get("top_comments",[])[:top_comments_count]
                        post["other_comments"]=cd.get("other_comments",[]); post["comments_scraped_count"]=cd.get("comments_scraped_count",0)
                        if cd.get("comments_scrape_failed"): post["comments_scrape_failed"]=True
                    except: post["comments_scrape_failed"]=True
                    finally:
                        try: tab.close()
                        except: pass
        all_results=_apply_min_filters(all_results,min_likes,min_comments,min_views)
        all_results=_apply_sort(all_results,sort_by)
        return {"keyword":keyword,"scraped_at":datetime.now().isoformat(),"types":types,
                "total_results":len(all_results),"results":all_results,"sort_by":sort_by,"success":True}

    def scrape_hashtag(self,hashtag,max_results=1000,sort_by="trending",types=None,
                       min_likes=None,min_comments=None,min_views=None,
                       max_comments_per_post=0,top_comments_count=10,progress_callback=None,
                       detail_enrich_limit=None):
        if types is None: types=['posts','videos']
        tag=hashtag.lstrip('#').strip()
        print(Fore.CYAN+f"\n[HASHTAG] #{tag}")
        self.initialize_browser()
        step_a=[]
        active_types=set(types or ['posts','videos'])
        if "posts" in active_types:
            try:
                for item in self._scrape_search_url(f"https://www.facebook.com/hashtag/{quote(tag)}",tag,max_results,"posts",strict_keyword=True):
                    item["matched_via"]="hashtag_page"; step_a.append(item)
            except: pass
        all_results=list(step_a)
        if "posts" in active_types and len(all_results)<5:
            try:
                for item in self._scrape_search_url(f"https://www.facebook.com/search/posts/?q={quote(tag)}",tag,max_results-len(all_results),"posts",strict_keyword=True):
                    item["matched_via"]="keyword_fallback"
                    if (item.get("source") == "search_post_card" or _is_valid_result_url(item.get("url",""))) and item.get("url","") not in [x.get("url","") for x in all_results]: all_results.append(item)
            except: pass
        if "videos" in active_types and len(all_results)<max_results:
            try:
                existing={_fb_content_key(x.get("url","")) or x.get("url","") for x in all_results}
                remaining=max_results-len(all_results)
                for item in self._scrape_search_url(f"https://www.facebook.com/search/videos/?q={quote(tag)}",tag,remaining,"videos",strict_keyword=True):
                    item["matched_via"]="hashtag_video_fallback"
                    u=item.get("url","")
                    key=_fb_content_key(u) or u
                    if u and key not in existing and _is_valid_result_url(u):
                        existing.add(key); all_results.append(item)
            except: pass
        self.enrich_missing_details(
            all_results,
            limit=detail_enrich_limit,
            progress_callback=progress_callback,
        )
        if max_comments_per_post>0 and all_results:
            commentable=[p for p in all_results if _is_commentable_url(p.get('url',''))]
            for idx,post in enumerate(commentable):
                tab=self._new_page()
                try:
                    cd=self._scrape_post_comments(post.get("url",""),max_comments_per_post,top_comments_count,page=tab)
                    post["top_comments"]=cd.get("top_comments",[])[:top_comments_count]; post["other_comments"]=cd.get("other_comments",[])
                    post["comments_scraped_count"]=cd.get("comments_scraped_count",0)
                    if cd.get("comments_scrape_failed"): post["comments_scrape_failed"]=True
                except: post["comments_scrape_failed"]=True
                finally:
                    try: tab.close()
                    except: pass
        all_results=_apply_min_filters(all_results,min_likes,min_comments,min_views)
        all_results=_apply_sort(all_results,sort_by)
        return {"hashtag":tag,"scraped_at":datetime.now().isoformat(),"total_results":len(all_results),
                "results":all_results[:max_results],"sort_by":sort_by,
                "matched_via_stats":{"hashtag_page":sum(1 for x in all_results if x.get("matched_via")=="hashtag_page"),
                                    "keyword_fallback":sum(1 for x in all_results if x.get("matched_via")=="keyword_fallback")},
                "success":True}

    def scrape_trending(self,max_results=1000,sort_by="trending",keyword="",
                       types=None,min_likes=None,min_comments=None,min_views=None,
                       max_comments_per_post=0,top_comments_count=10,progress_callback=None,
                       detail_enrich_limit=None):
        if types is None: types=['posts','videos','groups','pages']
        print(Fore.CYAN+f"\n[TRENDING] {keyword or '(semua)'}")
        self.initialize_browser()
        sks=[keyword] if keyword else ["viral hari ini","trending indonesia","berita terkini"]
        all_results=[]; seen_urls=set()
        for skw in sks:
            if len(all_results)>=max_results: break
            # ✅ FIX: beri cukup kuota per keyword, bukan dibatasi 200
            remaining = max_results - len(all_results)
            for item in self._parallel_scrape_types(skw, types, max(200, remaining)):
                u=item.get('url','')
                key=_fb_content_key(u) or u
                if u and key not in seen_urls and _is_valid_result_url(u): seen_urls.add(key);item["engagement_score"]=_engagement_score(item);all_results.append(item)
        for item in all_results:
            item["engagement_score"]=_engagement_score(item)
        self.enrich_missing_details(
            all_results,
            limit=detail_enrich_limit,
            progress_callback=progress_callback,
        )
        if max_comments_per_post>0 and all_results:
            commentable=[p for p in all_results if _is_commentable_url(p.get('url',''))]
            for idx,post in enumerate(commentable):
                tab=self._new_page()
                try:
                    cd=self._scrape_post_comments(post.get("url",""),max_comments_per_post,top_comments_count,page=tab)
                    post["top_comments"]=cd.get("top_comments",[])[:top_comments_count]; post["other_comments"]=cd.get("other_comments",[])
                    post["comments_scraped_count"]=cd.get("comments_scraped_count",0)
                    if cd.get("comments_scrape_failed"): post["comments_scrape_failed"]=True
                except: post["comments_scrape_failed"]=True
                finally:
                    try: tab.close()
                    except: pass
        all_results=_apply_min_filters(all_results,min_likes,min_comments,min_views)
        all_results=_apply_sort(all_results,sort_by)
        r={"mode":"trending","keyword":keyword,"types":types,"sort_by":sort_by,
           "scraped_at":datetime.now().isoformat(),"total_results":len(all_results),
           "results":all_results[:max_results],"success":True}
        if not keyword: r["note"]="Trending umum - gunakan keyword untuk lebih spesifik."
        return r
