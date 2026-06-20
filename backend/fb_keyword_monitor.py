import os, re, json, time, random, math, threading, uuid, html
from datetime import datetime
from typing import List, Dict, Optional, Set, Any, Callable
from urllib.parse import quote, urlparse, parse_qs
from dotenv import load_dotenv
from colorama import Fore, init
from playwright.sync_api import sync_playwright, Page, BrowserContext, Response

init(autoreset=True); load_dotenv()
HEADLESS = os.getenv("FB_HEADLESS", "False").lower() == "true"
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

def _engagement_score(item):
    """Return a score comparable across normal posts and videos."""
    return (
        item.get("likes_count", 0)
        + item.get("comments_count", 0) * 2
        + item.get("shares_count", 0) * 3
        + item.get("views_count", 0) * 0.1
    )

def _apply_sort(items,sort_by):
    if not items: return items
    m={"engagement":lambda x:_engagement_score(x),"likes":lambda x:x.get("likes_count",0),"comments":lambda x:x.get("comments_count",0),
       "views":lambda x:x.get("views_count",0),"shares":lambda x:x.get("shares_count",0),"recent":lambda x:x.get("timestamp","")}
    items.sort(key=m.get(sort_by,m["engagement"]),reverse=True)
    for i,p in enumerate(items,1): p["rank"]=i
    return items

def _apply_min_filters(items,ml=None,mc=None,mv=None):
    if ml is None and mc is None and mv is None: return items
    return [i for i in items if not(ml is not None and i.get("likes_count",0)<ml or mc is not None and i.get("comments_count",0)<mc or mv is not None and i.get("views_count",0)<mv)]

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
    if 'facebook.com/photo/?fbid=' in u or re.search(r'/photo/\?fbid=\d+', u):
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
    # Collect all text fields
    fields_to_check = [
        (item.get("text","") or item.get("caption","") or "").lower(),
        (item.get("author","") or "").lower(),
        (item.get("url","") or "").lower(),
        (item.get("group_name","") or "").lower(),
        (item.get("page_name","") or "").lower(),
        (item.get("matched_via","") or "").lower(),
    ]
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
            os.path.join(os.getcwd(),"fb_chrome_real_profile"),channel="chrome",headless=HEADLESS,
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
        print(Fore.CYAN+"\n[FB] Membuka browser...")
        self.context=self._build_context()
        self.page=self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        try:
            from fb_cookie_injector import inject_cookies_sync
            if self._has_cookie: inject_cookies_sync(self.ctx); print(Fore.GREEN+"   [OK] Cookies diinject")
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
            return {"url":url,"author":author,"text":text[:1000],"caption":text[:1000],"timestamp":ts,"type":pt,
                    "likes_count":likes,"comments_count":comments,"views_count":views,"shares_count":shares,
                    "images":media_urls,"media_urls":media_urls,"media_count":len(media_urls),
                    "page_name":page_name,
                    "engagement_score":likes+comments*2+views,"source":"graphql"}
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

            likes    = self._extract_metric_from_text(visible, ["suka", "likes", "reaksi", "reaction"])
            comments = self._extract_metric_from_text(visible, ["komentar", "comments", "comment"])
            views    = self._extract_metric_from_text(visible, ["tayangan", "views", "ditonton", "viewed"])
            shares   = self._extract_metric_from_text(visible, ["dibagikan", "shares", "share", "bagikan"])

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
                "engagement_score": likes + comments * 2 + views,
                "source":           "html_embedded",
            }

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
                if(raw.includes('/photo/')&&raw.includes('fbid=')){
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
                    else if(/\/(posts|permalink)\/\d+/.test(h))score=55;
                    else if((h.includes('/photo/')||h.includes('/photo?'))&&h.includes('fbid='))score=50;
                    else if(/\/(photo|photos)\/\d+/.test(h))score=45;
                    // ✅ FIX: tambah format share baru FB
                    else if(/\/share\/(p|v|r)\/[A-Za-z0-9_-]+/.test(h))score=48;
                    else if(/profile\.php\?id=\d+/.test(h))score=35;
                    else if(/facebook\.com\/[a-zA-Z0-9._-]{3,}\/?$/.test(h))score=30;
                    else if(/\/(reel|reels|videos|video)\/\d+/.test(h)||h.includes('/watch/?v='))score=20;
                    else if(h.includes('facebook.com')&&!/\/(login|help|privacy|legal)/.test(h))score=10;
                    if(score>bestScore){
                        const u=normalize(h);
                        if(u){best=u;bestScore=score;}
                    }
                }
                return best||'';
            };
            // ✅ FIX: selector lebih luas — cover semua variasi struktur FB feed + article fallback
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
                    if(!url||s.has(url))return;
                    const ac=c.querySelector('a[role="link"] span[dir="auto"],strong[dir="auto"] > span[dir="auto"],h2 span[dir="auto"],h3 span[dir="auto"],h4 span[dir="auto"]');
                    if(ac)author=(ac.innerText||'').trim().slice(0,100);
                    if(!author){
                        const ac2=c.querySelector('strong[dir="auto"],h2,h3,h4');
                        if(ac2)author=(ac2.innerText||'').trim().slice(0,100);
                    }
                    c.querySelectorAll('span[dir="auto"],div[dir="auto"]').forEach(el=>{
                        const t=(el.innerText||'').trim();
                        if(t.length>txt.length&&t.length<3000&&t!==author&&t!=='Lihat selengkapnya')txt=t;
                    });
                    let likes=0,comms=0,views=0,shares=0;
                    const fullText=(c.innerText||'').replace(/\u00a0/g,' ');
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
                    const images=extractImages(c);
                    s.add(url);
                    r.push({url,author:author||'Unknown',text:txt.slice(0,1000),caption:txt.slice(0,1000),
                        timestamp:'',type:'posts',likes_count:likes||0,comments_count:comms||0,
                        views_count:views||0,shares_count:shares||0,images,media_urls:images,media_count:images.length,
                        engagement_score:likes+comms*2+views,source:'dom'});
                }catch(e){}
            });
            return r;
        }
        """

        for rnd in range(mx):
            if len(results)>=max_items: break
            batch=page.evaluate(_JS_FEED, max_items-len(results))
            n=0
            for item in batch:
                u=item.get('url','')
                key = _fb_content_key(u) or u
                if not u or key in seen_urls or not _is_valid_result_url(u): continue
                if keyword and not _keyword_in_item(item, keyword):
                    continue
                seen_urls.add(key); results.append(item); n+=1
            if rnd%5==0 or n>0: print(Fore.CYAN+f"   [FEED] R{rnd+1}: {len(results)}(+{n})")
            if n==0: stable+=1
            else: stable=0
            if stable>=ms: break
            page.evaluate(f"window.scrollBy(0,{random.choice([1200,1500,2000])})")
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
                if(raw.includes('/photo/')&&raw.includes('fbid=')){
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
                    if(!h.includes('/stories/')&&(/\/(posts|permalink|photo|videos|video|reel|reels)\/\d+/.test(h)||isWatch||(h.includes('/photo/')&&h.includes('fbid='))))n++;
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
                        if(!likes&&!comms&&!views){
                            const nums=metricNums(fullText).filter(n=>n>9);
                            if(nums.length>=3){
                                const tail=nums.slice(-3);
                                likes=tail[0]; comms=tail[1]; views=tail[2];
                            }else if(nums.length>=2){
                                likes=nums[0]; comms=nums[1];
                            }
                        }
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
                        if(/(posts|permalink|photo)\/\d+/.test(ch)||(h.includes('/photo/')&&h.includes('fbid='))){
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
            batch=page.evaluate(_JS_GENERIC, {"searchType": search_type, "keyword": keyword or ''})
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
            page.evaluate(f"window.scrollBy(0,{random.choice([1000,1500,2000])})")
            time.sleep(random.uniform(0.8,1.5))
        return results[:max_items]

    def _needs_detail_enrich(self, item: dict) -> bool:
        url = item.get("url", "")
        if not _is_commentable_url(url):
            return False
        text_missing = not (item.get("caption") or item.get("text") or "").strip()
        core_missing = (
            item.get("likes_count", 0) == 0
            or item.get("comments_count", 0) == 0
            or item.get("shares_count", 0) == 0
        )
        is_video = (item.get("type", "").lower() in ("videos", "video", "reel", "reels")
                    or any(x in url.lower() for x in ("/watch", "/reel/", "/reels/", "/videos/", "/share/v/")))
        return text_missing or (is_video and core_missing) or (
            item.get("likes_count", 0) == 0
            and item.get("comments_count", 0) == 0
            and item.get("shares_count", 0) == 0
        )

    def _extract_detail_metadata(self, page: Page) -> dict:
        try:
            return page.evaluate(r"""
            () => {
                const out = {likes_count: 0, comments_count: 0, shares_count: 0, views_count: 0, caption: '', author: ''};
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
                    if (/suka|like|reaction|reaksi/i.test(combined)) out.likes_count = maxMetric(out.likes_count, combined);
                    if (/komentar|comment/i.test(combined)) out.comments_count = maxMetric(out.comments_count, combined);
                    if (/bagikan|share|kirim/i.test(combined)) out.shares_count = maxMetric(out.shares_count, combined);
                    if (/tayangan|views|ditonton|viewed/i.test(combined)) out.views_count = maxMetric(out.views_count, combined);
                });

                const inferVideoViewsFromEngagementRow = () => {
                    const lines = scopedText().split(/\n+/).map(clean).filter(Boolean);
                    const actionIdx = lines.findIndex(line => /^(suka|like)$/i.test(line));
                    if (actionIdx <= 0) return 0;
                    const nums = [];
                    for (let i = Math.max(0, actionIdx - 10); i < actionIdx; i++) {
                        const line = lines[i];
                        if (metricNumber.test(line) && !/^\d{1,2}:\d{2}(?::\d{2})?$/.test(line)) {
                            nums.push(line);
                        }
                    }
                    if (nums.length >= 3) return parseNum(nums[nums.length - 1]);
                    if (nums.length >= 2 && /(rb|ribu|k|jt|juta|mio|mn)\b/i.test(nums[nums.length - 1])) {
                        return parseNum(nums[nums.length - 1]);
                    }
                    return 0;
                };
                const inferVideoEngagementRow = () => {
                    const text = scopedText();
                    const actionMatch = text.match(/([\s\S]{0,500}?)(?:\bSuka\b|\bLike\b)\s+(?:Komentari|Comment)\s+(?:Bagikan|Share)\b/i);
                    if (!actionMatch) return;
                    const nums = parseNums(actionMatch[1]).filter(n => n < 1000000000);
                    if (nums.length < 2) return;
                    const isVideo = /\/(?:videos?|watch|reels?|reel)\b/i.test(location.pathname + location.search);
                    if (isVideo && nums.length >= 3) {
                        const [likes, comments, views] = nums.slice(-3);
                        out.likes_count = Math.max(out.likes_count, likes);
                        out.comments_count = Math.max(out.comments_count, comments);
                        out.views_count = Math.max(out.views_count, views);
                    } else if (nums.length >= 3) {
                        const [likes, comments, shares] = nums.slice(-3);
                        out.likes_count = Math.max(out.likes_count, likes);
                        out.comments_count = Math.max(out.comments_count, comments);
                        out.shares_count = Math.max(out.shares_count, shares);
                    } else {
                        const [likes, comments] = nums.slice(-2);
                        out.likes_count = Math.max(out.likes_count, likes);
                        out.comments_count = Math.max(out.comments_count, comments);
                    }
                };

                out.likes_count = out.likes_count || scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:suka|likes?|reaksi|reactions?)/i,
                    /(?:suka|likes?|reaksi|reactions?)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]);
                out.comments_count = out.comments_count || scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:komentar|comments?)/i,
                    /(?:komentar|comments?)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]);
                out.shares_count = out.shares_count || scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:kali\s+dibagikan|x\s+dibagikan|dibagikan|shares?)/i,
                    /(?:dibagikan|shares?)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]);
                out.views_count = out.views_count || scanMetric([
                    /([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)\s*(?:tayangan|views?|ditonton|viewed)/i,
                    /(?:tayangan|views?|ditonton|viewed)\s*[:\-]?\s*([\d][\d.,]*\s*(?:rb|ribu|k|jt|juta|m|mio|mn)?)/i,
                ]);
                inferVideoEngagementRow();
                out.views_count = Math.max(inferVideoViewsFromEngagementRow(), out.views_count);

                const chrome = /(notifikasi|belum dibaca|lihat semua|orang yang anda kenal|saran teman|selamat datang|welcome to facebook|masuk ke facebook|log in to facebook|filter|hasil pencarian|tanggal diposting|marketplace|halaman|grup|acara)/i;
                const metricish = /^([\d.,]+\s*(rb|ribu|k|jt|juta|m|mio|mn)?|[\d:]+|suka|komentar|bagikan|share|like|comment)$/i;
                const okCaption = (t) => t && t.length >= 8 && t.length < 2200 && !chrome.test(t) && !metricish.test(t);

                const og = clean(document.querySelector('meta[property="og:description"],meta[name="description"]')?.getAttribute('content') || '');
                if (okCaption(og)) out.caption = og;

                if (!out.caption) {
                    const selectors = ['[data-ad-preview="message"]', '[data-ad-comet-preview="message"]', '[data-testid="post_message"]'];
                    for (const sel of selectors) {
                        const text = clean(document.querySelector(sel)?.textContent || '');
                        if (okCaption(text)) { out.caption = text; break; }
                    }
                }

                if (!out.caption) {
                    let best = '';
                    document.querySelectorAll('[role="article"], [role="main"], [role="complementary"]').forEach(scope => {
                        const lines = (scope.innerText || '').split(/\n+/).map(clean).filter(Boolean);
                        for (const line of lines) {
                            if (!okCaption(line)) continue;
                            if (/durasi video|diverifikasi|yang lalu|\btayangan\b/i.test(line)) continue;
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
            is_video = item.get("type", "").lower() in ("videos", "video", "reel", "reels") or any(
                x in url for x in ("/watch", "/reel/", "/reels/", "/videos/", "/share/v/")
            )
            incomplete = int(item.get("shares_count", 0) or 0) == 0 or int(item.get("views_count", 0) or 0) == 0
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
                    tab.goto(url, wait_until="domcontentloaded", timeout=18000)
                    time.sleep(random.uniform(FB_DETAIL_WAIT_SECONDS, FB_DETAIL_WAIT_SECONDS + 0.6))
                    self._close_popups(tab)
                    try:
                        tab.evaluate("window.scrollBy(0, 500)")
                        time.sleep(0.4)
                    except Exception:
                        pass
                    meta = self._extract_detail_metadata(tab)
                    for src_key, dst_key in [
                        ("likes_count", "likes_count"),
                        ("comments_count", "comments_count"),
                        ("shares_count", "shares_count"),
                        ("views_count", "views_count"),
                    ]:
                        val = int(meta.get(src_key, 0) or 0)
                        if dst_key == "views_count" and val > 0:
                            # Detail/permalink view count is more trustworthy than search-card text.
                            post[dst_key] = val
                        elif val > int(post.get(dst_key, 0) or 0):
                            post[dst_key] = val
                    caption = (meta.get("caption") or "").strip()
                    current = (post.get("caption") or post.get("text") or "").strip()
                    if caption and (not current or len(caption) > len(current)):
                        post["caption"] = caption[:1000]
                        post["text"] = caption[:1000]
                    author = (meta.get("author") or "").strip()
                    current_author = str(post.get("author") or "")
                    if author and (current_author in ("", "Unknown") or re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", current_author)):
                        post["author"] = author[:100]
                    post["engagement_score"] = _engagement_score(post)
                    post["detail_enriched"] = True
                except Exception as e:
                    print(Fore.YELLOW+f"     [DETAIL] skip: {e}")
                    post["detail_enrich_failed"] = True
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
            p.goto(url,wait_until="domcontentloaded",timeout=30000)
            # ✅ FIX: Tambah wait lebih lama agar GQL sempat di-intercept
            time.sleep(FB_SEARCH_LOAD_SECONDS)
            self._close_popups(p)
            # ✅ FIX: Scroll beberapa kali untuk trigger lazy load GQL
            for _ in range(max(0, FB_SEARCH_PRE_SCROLLS)):
                p.evaluate("window.scrollBy(0, 800)")
                time.sleep(FB_SEARCH_SCROLL_DELAY)
            time.sleep(min(0.3, FB_SEARCH_SCROLL_DELAY))
            if search_type == "posts":
                for item in self._extract_feed(p,max_results,keyword):
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u): seen_urls.add(key); all_results.append(item)
            else:
                for item in self._extract_generic(p,max_results,search_type,keyword):
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u): seen_urls.add(key); all_results.append(item)
            # ✅ FIX: Coba GQL bahkan jika DOM extraction sudah berhasil (tambah lebih banyak)
            if len(all_results) < max_results:
                print(Fore.YELLOW+f"   [GQL-FALLBACK] Trying GraphQL ({len(gql_data)} responses)...")
                for item in self._extract_gql(gql_data,keyword,strict_keyword):
                    u=item.get('url','')
                    key=_fb_content_key(u) or u
                    if u and key not in seen_urls and _is_valid_result_url(u): seen_urls.add(key); all_results.append(item)
                if gql_data: print(Fore.GREEN+f"   [GQL] +{len(all_results)} total after GQL")
            if not all_results:
                print(Fore.YELLOW+"   [HTML-FALLBACK] Parsing embedded page JSON/HTML...")
                for item in self._extract_embedded_html(p, max_results, "", search_type):
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
                        if u and key not in seen_urls and _is_valid_result_url(u):
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

    def scrape_keyword(self,raw_keyword,max_results=1000,types=None,sort_by="engagement",
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

    def scrape_hashtag(self,hashtag,max_results=1000,sort_by="engagement",
                       min_likes=None,min_comments=None,min_views=None,
                       max_comments_per_post=0,top_comments_count=10,progress_callback=None,
                       detail_enrich_limit=None):
        tag=hashtag.lstrip('#').strip()
        print(Fore.CYAN+f"\n[HASHTAG] #{tag}")
        self.initialize_browser()
        step_a=[]
        try:
            for item in self._scrape_search_url(f"https://www.facebook.com/hashtag/{quote(tag)}",tag,max_results,"posts",strict_keyword=True):
                item["matched_via"]="hashtag_page"; step_a.append(item)
        except: pass
        all_results=list(step_a)
        if len(all_results)<5:
            try:
                for item in self._scrape_search_url(f"https://www.facebook.com/search/posts/?q={quote(tag)}",tag,max_results-len(all_results),"posts",strict_keyword=True):
                    item["matched_via"]="keyword_fallback"
                    if _is_valid_result_url(item.get("url","")) and item.get("url","") not in [x.get("url","") for x in all_results]: all_results.append(item)
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

    def scrape_trending(self,max_results=1000,sort_by="engagement",keyword="",
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
