import os, re, json, time, random, math, threading, uuid, html
from datetime import datetime
from typing import List, Dict, Optional, Set, Any, Callable
from urllib.parse import quote
from dotenv import load_dotenv
from colorama import Fore, init
from playwright.sync_api import sync_playwright, Page, BrowserContext, Response

init(autoreset=True); load_dotenv()
HEADLESS = os.getenv("FB_HEADLESS", "False").lower() == "true"
FB_CHROME_PROFILE = os.path.join(os.getcwd(), "fb_chrome_real_profile")
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
    """
    Terima hanya URL post/video/photo nyata di Facebook.
    BARU: buang hashtag pages, profile/group homepage tanpa konten spesifik.
    """
    if not url:
        return False
    u = url.lower()

    # Blok absolut
    for blocked in ['/legal/','/privacy/','/help/','/about/','/policies',
                    '/security/','/stories/','/hashtag/','/login','/signup']:
        if blocked in u:
            return False

    # Photo dengan fbid
    if 'facebook.com/photo/?fbid=' in u or re.search(r'/photo/\?fbid=\d+', u):
        return True
    # Watch video
    if re.search(r'/watch/?\?v=\d+', u):
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
    return url.split("#")[0]

def _looks_like_media_url(url: str) -> bool:
    u = (url or "").lower()
    return bool(u) and ("scontent" in u or "fbcdn" in u) and bool(re.search(r'\.(jpg|jpeg|png|webp)(?:\?|$)', u))

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
        p.add_init_script("Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                          "window.chrome={runtime:{},csi:function(){return{}},loadTimes:function(){return{}}};"
                          "Object.defineProperty(navigator,'languages',{get:()=>['id-ID','id','en-US','en']});"
                          "Object.defineProperty(navigator,'platform',{get:()=>'Win32'});")
        return p

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
        time.sleep(4)
        cu=self.pg.url
        if "login" in cu or "checkpoint" in cu: print(Fore.RED+"   [FAIL] Redirect login!");self.close();raise Exception("FB session expired")
        if not self._is_logged_in(): print(Fore.RED+"   [FAIL] Belum login!");self.close();raise Exception("FB not logged in")
        self._warmup_browser(10);self._warmed_up=True
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
        for _ in range(2): self.pg.evaluate(f"window.scrollBy(0,{random.randint(300,800)})");time.sleep(random.uniform(1.5,3))
        self.pg.evaluate("window.scrollTo(0,0)");time.sleep(1.5)
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
                    if item.get("url","") and item["url"] not in seen_urls:
                        seen_urls.add(item["url"]); results.append(item)
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

            # Shares — cek share_count, reshare_count, lalu node langsung
            shares = 0
            if isinstance(fb, dict):
                share_obj = fb.get("share_count") or fb.get("reshare_count") or {}
                if isinstance(share_obj, dict):
                    shares = int(share_obj.get("count", 0) or 0)
                elif isinstance(share_obj, int):
                    shares = share_obj
            if shares == 0:
                shares = int(node.get("share_count", 0) or node.get("reshare_count", 0) or 0)

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
            r'href="([^"]*(?:/watch/?\?v=|/photo/?\?fbid=|/(?:posts|permalink|videos?|reels?)/\d+|/groups/[^/]+/posts/\d+|story_fbid=)[^"]*)"',
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
            if not url or url in seen:
                continue

            if not _is_valid_result_url(url):
                continue

            seen.add(url)

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
        text = (text or "").lower().replace("\u00a0", " ")
        label_pat = "|".join(re.escape(x.lower()) for x in labels)

        def _parse(num_str, suffix):
            try:
                n = float(num_str.replace(".", "").replace(",", "."))
            except ValueError:
                return 0
            sf = (suffix or "").lower().strip()
            if sf in ("rb", "ribu", "k"):
                n *= 1_000
            elif sf in ("jt", "juta", "m", "mio", "mn"):
                n *= 1_000_000
            return int(n)

        SFX = r"(rb|ribu|k|jt|juta|m|mio|mn)?"

        m = re.search(rf'([\d.,]+)\s*{SFX}\s*(?:{label_pat})', text, re.I)
        if m:
            r = _parse(m.group(1), m.group(2) or "")
            if r > 0: return r

        m = re.search(rf'(?:{label_pat})\s*[:\-]?\s*([\d.,]+)\s*{SFX}', text, re.I)
        if m:
            r = _parse(m.group(1), m.group(2) or "")
            if r > 0: return r

        m = re.search(rf'([\d.,]+)\s*{SFX}\s*[·•]\s*(?:{label_pat})', text, re.I)
        if m:
            r = _parse(m.group(1), m.group(2) or "")
            if r > 0: return r

        m = re.search(rf'(?:{label_pat})\s*[·•]\s*([\d.,]+)\s*{SFX}', text, re.I)
        if m:
            r = _parse(m.group(1), m.group(2) or "")
            if r > 0: return r

        return 0

    # ======================================================================
    #  FEED EXTRACTION
    # ======================================================================
    def _extract_feed(self, page, max_items=100, keyword=""):
        results=[]; seen_urls=set(); stable=0; mx=80; ms=6
        has_feed=False
        for _ in range(8):
            try:
                c=page.evaluate("document.querySelectorAll('[role=\"feed\"] [aria-posinset]').length")
                if c>0: print(Fore.GREEN+f"   [FEED] {c} posts"); has_feed=True; break
            except: pass
            time.sleep(1)
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
            document.querySelectorAll('[role="feed"] [aria-posinset],[role="feed"]>div>div>div>div').forEach(c=>{
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
                    c.querySelectorAll('div[role="button"],span[role="button"]').forEach(el=>{
                        const aria=(el.getAttribute('aria-label')||'').toLowerCase();
                        let tx=(el.innerText||'').trim();
                        if(aria.includes('suka')||aria.includes('like')||aria.includes('react')){
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            likes=Math.max(likes,parseNum(tx||aria));
                        }
                        if(aria.includes('komentar')||aria.includes('comment')){
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            comms=Math.max(comms,parseNum(tx||aria));
                        }
                        if(aria.includes('bagikan')||aria.includes('share')){
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            shares=Math.max(shares,parseNum(tx||aria));
                        }
                    });
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
                if not u or u in seen_urls or not _is_valid_result_url(u): continue
                if keyword and not _keyword_in_item(item, keyword):
                    continue
                seen_urls.add(u); results.append(item); n+=1
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
        results=[]; seen_urls=set(); stable=0; ms=4

        print(Fore.CYAN+f"   [GENERIC] Using universal scroll extraction for {search_type}...")

        if search_type == "groups":
            return self._extract_group_posts(page, max_items, keyword)

        if search_type == "pages":
            return self._extract_page_posts(page, max_items, keyword)

        mx = 60
        _JS_GENERIC = r"""
        (args) => {
            const st=args.searchType||'posts'; const kw=(args.keyword||'').toLowerCase();
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
            const contentLinks=(node)=>{
                if(!node)return 0;
                let n=0;
                node.querySelectorAll('a[href]').forEach(x=>{
                    const h=x.getAttribute('href')||'';
                    if(!h.includes('/stories/')&&(/\/(posts|permalink|photo|videos|video|reel|reels)\/\d+/.test(h)||h.includes('/watch/?v=')||(h.includes('/photo/')&&h.includes('fbid='))))n++;
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
                const x=(t||'').trim().toLowerCase();
                if(!x)return true;
                if(x===kw||x==='videos'||x==='reels'||x==='watch'||x==='lihat selengkapnya')return true;
                if(/^(like|comment|share|suka|komentar|bagikan|\d+:\d+)$/.test(x))return true;
                return false;
            };
            const allLinks=document.querySelectorAll('a[href*="/"]');
            allLinks.forEach(a=>{
                try{
                    const h=a.getAttribute('href')||''; const ch=h.split('#')[0].split('?')[0];
                    let url='',detected='';
                    if(st==='videos'){
                        if(/\/(videos\/|video\/|reel\/|reels\/)/.test(ch)||h.includes('/watch/?v=')){
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
                        const ac=container.querySelector('strong[dir="auto"],h2,h3,h4,a[role="link"]');
                        if(ac)author=(ac.innerText||'').trim().slice(0,100);
                        const candidates=[];
                        container.querySelectorAll('span[dir="auto"],div[dir="auto"]').forEach(el=>{
                            const t=(el.innerText||'').trim();
                            if(t.length<3||t.length>2200||t===author||badText(t))return;
                            candidates.push(t);
                        });
                        candidates.sort((a,b)=>{
                            const ak=kw&&a.toLowerCase().includes(kw)?1:0;
                            const bk=kw&&b.toLowerCase().includes(kw)?1:0;
                            if(ak!==bk)return bk-ak;
                            return b.length-a.length;
                        });
                        txt=(candidates[0]||'').slice(0,1000);
                        const fullText=(container.innerText||'').replace(/\u00a0/g,' ');
                        const vm=fullText.match(/([\d.,]+\s*(?:rb|ribu|k|jt|juta|m|mio)?)\s*(?:tayangan|views|ditonton)/i);
                        if(vm)views=parseNum(vm[0]);
                        container.querySelectorAll('[aria-label*="suka"],[aria-label*="like"],[aria-label*="react"]').forEach(el=>{
                            let tx=(el.innerText||'').trim();
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            likes=Math.max(likes,parseNum(tx+' '+(el.getAttribute('aria-label')||'')));
                        });
                        container.querySelectorAll('[aria-label*="komentar"],[aria-label*="comment"]').forEach(el=>{
                            let tx=(el.innerText||'').trim();
                            const childSpan=el.querySelector('span[dir="auto"]');
                            if(childSpan)tx=(childSpan.innerText||'').trim();
                            comms=Math.max(comms,parseNum(tx+' '+(el.getAttribute('aria-label')||'')));
                        });
                        images=extractImages(container);
                    }
                    s.add(url);
                    r.push({url,author:author||'Unknown',text:txt.slice(0,1000),caption:txt.slice(0,1000),
                        timestamp:'',type:detected||st,likes_count:likes||0,comments_count:comms||0,
                        views_count:views||0,shares_count:0,images,media_urls:images,media_count:images.length,
                        engagement_score:likes+comms*2+views,source:'generic'});
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
                if not u or u in seen_urls or not _is_valid_result_url(u): continue
                if keyword and not _keyword_in_item(item, keyword):
                    continue
                seen_urls.add(u); results.append(item); n+=1
            if rnd%5==0 or n>0: print(Fore.CYAN+f"   [GENERIC] R{rnd+1}: {len(results)}(+{n}) type={search_type}")
            if n==0: stable+=1
            else: stable=0
            if stable>=ms: break
            page.evaluate(f"window.scrollBy(0,{random.choice([1000,1500,2000])})")
            time.sleep(random.uniform(0.8,1.5))
        return results[:max_items]

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
                    let likes=0,comms=0,views=0;
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
                    });
                    const images=extractImages(c);
                    s.add(url);
                    r.push({url,author:author||'Unknown',text:txt.slice(0,1000),caption:txt.slice(0,1000),
                        timestamp:'',type:'pages',likes_count:likes||0,comments_count:comms||0,
                        views_count:views||0,shares_count:0,images,media_urls:images,media_count:images.length,
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
                    if u and u not in seen_urls and _is_valid_result_url(u):
                        if keyword and not _keyword_in_item(item, keyword):
                            continue
                        seen_urls.add(u); results.append(item); n+=1
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
            gql_sid, gql_data, gql_urls = self._setup_gql(p)
            p.goto(url,wait_until="domcontentloaded",timeout=30000); time.sleep(4); self._close_popups(p)
            if search_type == "posts":
                for item in self._extract_feed(p,max_results,keyword):
                    u=item.get('url','')
                    if u and u not in seen_urls and _is_valid_result_url(u): seen_urls.add(u); all_results.append(item)
            else:
                for item in self._extract_generic(p,max_results,search_type,keyword):
                    u=item.get('url','')
                    if u and u not in seen_urls and _is_valid_result_url(u): seen_urls.add(u); all_results.append(item)
            if not all_results:
                print(Fore.YELLOW+f"   [GQL-FALLBACK] Trying GraphQL ({len(gql_data)} responses)...")
                for item in self._extract_gql(gql_data,keyword,strict_keyword):
                    u=item.get('url','')
                    if u and u not in seen_urls and _is_valid_result_url(u): seen_urls.add(u); all_results.append(item)
                if all_results: print(Fore.GREEN+f"   [OK] GQL: {len(all_results)} items")
            if not all_results:
                print(Fore.YELLOW+"   [HTML-FALLBACK] Parsing embedded page JSON/HTML...")
                for item in self._extract_embedded_html(p, max_results, "", search_type):
                    u=item.get('url','')
                    if u and u not in seen_urls and _is_valid_result_url(u):
                        seen_urls.add(u); all_results.append(item)
        except Exception as e: print(Fore.RED+f"   [FAIL] {e}")
        return all_results[:max_results]

    # ======================================================================
    #  MULTI-TAB SCRAPE
    # ======================================================================
    def _parallel_scrape_types(self,keyword,types,max_results):
        all_results=[]; seen_urls=set()
        active_types=list(dict.fromkeys(types or ['posts']))
        per_type=max(1, math.ceil(max_results/len(active_types)))
        for i,st in enumerate(active_types):
            if i>0: time.sleep(random.uniform(0.5,1.5))
            print(Fore.CYAN+f"\n   [TAB] '{keyword}' type={st}...")
            tab=self._new_page()
            try:
                url=f"https://www.facebook.com/search/{st}/?q={quote(keyword)}"
                for item in self._scrape_search_url(url,keyword,min(200,per_type),st,page=tab):
                    u=item.get('url','')
                    if u and u not in seen_urls and _is_valid_result_url(u): seen_urls.add(u);item["deep_source_type"]=st;all_results.append(item)
                print(Fore.GREEN+f"   [OK] {st}: {len(all_results)} items")
            except Exception as e: print(Fore.RED+f"   [FAIL] {st}: {e}")
            finally:
                try: tab.close()
                except: pass
        return all_results[:max_results]

    # ======================================================================
    #  COMMENT SCRAPING v5.3
    # ======================================================================
    def _scrape_post_comments(self,post_url,max_comments=5,top_comments_count=5,page=None):
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
                    const m=(text||'').toLowerCase().replace(/\u00a0/g,' ').match(/([\d.,]+)\s*(rb|ribu|k|jt|juta|m|mio)?/i);
                    if(!m)return 0;
                    let n=parseFloat(m[1].replace(/\./g,'').replace(',','.'));
                    const sf=(m[2]||'').toLowerCase();
                    if(sf==='k'||sf==='rb'||sf==='ribu')n*=1000;
                    else if(sf==='m'||sf==='jt'||sf==='juta'||sf==='mio')n*=1000000;
                    return Math.floor(n)||0;
                };
                let cs=[...document.querySelectorAll('[aria-label^="Komentar oleh "],[aria-label^="Comment by "]')];
                if(!cs.length)cs=[...document.querySelectorAll('div[data-testid="UFI2Comment/body"],div[data-testid="UFI2Comment"]')];
                cs.forEach(c=>{try{
                    const aria=(c.getAttribute('aria-label')||'').trim();
                    const am=aria.match(/^(?:Komentar oleh|Comment by)\s+(.+?)\s+(\d+\s*(?:detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year)s?(?:\s+(?:yang lalu|ago))?)/i);
                    let au=am?am[1].trim():'Unknown';
                    const timestamp=am?am[2].trim():'';
                    if(au==='Unknown'){
                        const linkEl=c.querySelector('a[role="link"] span[dir="auto"],strong[dir="auto"],a[role="link"]');
                        if(linkEl)au=(linkEl.innerText||'').trim().slice(0,100)||'Unknown';
                    }
                    const lines=(c.innerText||'').split(/\n+/).map(x=>x.trim()).filter(Boolean);
                    const actionAt=lines.findIndex(x=>/^(suka|like|balas|reply)$/i.test(x));
                    const timeAt=lines.findIndex(x=>/^\d+\s*(detik|menit|jam|hari|minggu|bulan|tahun|second|minute|hour|day|week|month|year)/i.test(x));
                    const end=[actionAt,timeAt].filter(x=>x>=0).reduce((a,b)=>Math.min(a,b),lines.length);
                    const bodies=lines.slice(0,end).filter(x=>x!==au&&!/^(pembuat|author|top contributor)$/i.test(x));
                    const t=bodies.sort((a,b)=>b.length-a.length)[0]||'';
                    if(!t||st.has(t)||t.length<3)return;
                    let likes=0;
                    const reaction=c.querySelector('[aria-label^="Suka: "][aria-label*="orang"],[aria-label^="Like: "]');
                    if(reaction)likes=parseNum(reaction.getAttribute('aria-label')||'');
                    if(!likes&&actionAt>=0){
                        for(const line of lines.slice(actionAt+1)){
                            if(/^[\d.,]+\s*(rb|ribu|k|jt|juta|m|mio)?$/i.test(line)){likes=parseNum(line);break;}
                            if(/^lihat|^view/i.test(line))break;
                        }
                    }
                    st.add(t);
                    r.push({comment_author:au,comment_text:t.slice(0,2000),comment_likes:likes,comment_timestamp:timestamp,is_reply:false});
                }catch(e){}});return r;
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
        top_count=max(1, min(int(top_comments_count or 5), len(all_c) or 1))
        result["top_comments"]=all_c[:top_count]; result["other_comments"]=all_c[top_count:]
        result["comments_scraped_count"]=len(all_c)
        if len(all_c)==0: result["comments_scrape_failed"]=True
        print(Fore.GREEN+f"     [COMMENTS] Done: {len(all_c)} comments")
        return result

    # ======================================================================
    #  PUBLIC APIs
    # ======================================================================
    def enrich_comments(self, posts, max_comments_per_post=0, top_comments_count=5,
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
                       max_comments_per_post=0,top_comments_count=5,progress_callback=None):
        if types is None: types=['posts']
        keyword=self._clean_keyword(raw_keyword)
        print(Fore.CYAN+f"\n[KEYWORD] {keyword} | Max:{max_results}")
        self.initialize_browser()
        all_results=self._parallel_scrape_types(keyword,types,max_results)
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
                       max_comments_per_post=0,top_comments_count=5,progress_callback=None):
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
                       max_comments_per_post=0,top_comments_count=5,progress_callback=None):
        if types is None: types=['posts','videos','groups','pages']
        print(Fore.CYAN+f"\n[TRENDING] {keyword or '(semua)'}")
        self.initialize_browser()
        sks=[keyword] if keyword else ["viral hari ini","trending indonesia","berita terkini"]
        all_results=[]; seen_urls=set()
        for skw in sks:
            if len(all_results)>=max_results: break
            for item in self._parallel_scrape_types(skw,types,min(200,max_results-len(all_results))):
                u=item.get('url','')
                if u and u not in seen_urls and _is_valid_result_url(u): seen_urls.add(u);item["engagement_score"]=_engagement_score(item);all_results.append(item)
        for item in all_results:
            item["engagement_score"]=_engagement_score(item)
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