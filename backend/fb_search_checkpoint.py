"""
fb_search_checkpoint.py
=======================
Job manager untuk Facebook Deep Search.
Letakkan di folder: C:\\Users\\USER\\fb-scrapper\\backend\\

Menyimpan state tiap job ke file JSON di subfolder `fb_deep_jobs/`
sehingga job tetap ada walau server restart.

CHANGES v3:
  1. Semua worker baca sort_by/min_likes/min_comments/min_views dari config.
  2. _apply_sort_local() dan _apply_min_filters_local() untuk sorting/filter di checkpoint level.
  3. Field "rank" di-assign setelah sorting final.
  4. Flush posts ke disk setiap step untuk partial result.
"""

import os
import json
import uuid
import time
import random
import threading
import traceback
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

# ── Folder penyimpanan state job ────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_JOBS_DIR  = os.path.join(_HERE, "fb_deep_jobs")
_POSTS_DIR = os.path.join(_JOBS_DIR, "posts")

os.makedirs(_JOBS_DIR,  exist_ok=True)
os.makedirs(_POSTS_DIR, exist_ok=True)


# ── Status konstanta ────────────────────────────────────────────────────────
class JobStatus:
    PENDING   = "pending"
    RUNNING   = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR     = "error"


# ── Path helpers ────────────────────────────────────────────────────────────
def _state_path(job_id: str) -> str:
    return os.path.join(_JOBS_DIR, f"{job_id}.json")

def _posts_path(job_id: str) -> str:
    return os.path.join(_POSTS_DIR, f"{job_id}_posts.json")


# ── File I/O (thread-safe pakai lock per job_id) ────────────────────────────
_locks: Dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()

def _get_lock(job_id: str) -> threading.Lock:
    with _locks_lock:
        if job_id not in _locks:
            _locks[job_id] = threading.Lock()
        return _locks[job_id]


def _read_state(job_id: str) -> Optional[dict]:
    path = _state_path(job_id)
    if not os.path.exists(path):
        return None
    with _get_lock(job_id):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None


def _write_state(job_id: str, state: dict):
    path = _state_path(job_id)
    with _get_lock(job_id):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)


def _write_posts(job_id: str, posts: list):
    """Thread-safe write posts ke file."""
    path = _posts_path(job_id)
    with _get_lock(job_id):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(posts, f, ensure_ascii=False, default=str)


def _read_posts(job_id: str) -> list:
    path = _posts_path(job_id)
    if not os.path.exists(path):
        return []
    with _get_lock(job_id):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []


def _update_state(job_id: str, **kwargs):
    """Partial update — baca → merge → tulis."""
    state = _read_state(job_id) or {}
    state.update(kwargs)
    state["updated_at"] = datetime.now().isoformat()
    _write_state(job_id, state)


# ── Sort/Filter helpers (v3) ──────────────────────────────────────────────
def _engagement_score(item: dict) -> float:
    return (
        item.get("likes_count", 0) +
        item.get("comments_count", 0) * 2 +
        item.get("shares_count", 0) * 3 +
        item.get("views_count", 0) * 0.1
    )


def _apply_sort_local(items: list, sort_by: str) -> list:
    """Apply sorting by the specified metric. Modifies list in-place."""
    if not items:
        return items

    if sort_by == "engagement":
        items.sort(key=lambda x: _engagement_score(x), reverse=True)
    elif sort_by == "likes":
        items.sort(key=lambda x: x.get("likes_count", 0), reverse=True)
    elif sort_by == "comments":
        items.sort(key=lambda x: x.get("comments_count", 0), reverse=True)
    elif sort_by == "views":
        items.sort(key=lambda x: x.get("views_count", 0), reverse=True)
    elif sort_by == "shares":
        items.sort(key=lambda x: x.get("shares_count", 0), reverse=True)
    elif sort_by == "recent":
        items.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    else:
        items.sort(key=lambda x: _engagement_score(x), reverse=True)

    # Assign rank
    for idx, p in enumerate(items, 1):
        p["rank"] = idx
    return items


def _apply_min_filters_local(items: list, min_likes: Optional[int] = None,
                              min_comments: Optional[int] = None,
                              min_views: Optional[int] = None) -> list:
    """Filter items by minimum thresholds (AND logic)."""
    if min_likes is None and min_comments is None and min_views is None:
        return items
    filtered = []
    for item in items:
        if min_likes is not None and item.get("likes_count", 0) < min_likes:
            continue
        if min_comments is not None and item.get("comments_count", 0) < min_comments:
            continue
        if min_views is not None and item.get("views_count", 0) < min_views:
            continue
        filtered.append(item)
    return filtered


# ── Public API ──────────────────────────────────────────────────────────────

def create_job(mode: str, query: str, config: dict) -> str:
    """
    Buat job baru dan langsung jalankan worker di background thread.
    Return job_id.
    """
    job_id = str(uuid.uuid4())[:12]
    now    = datetime.now().isoformat()

    state = {
        "job_id":        job_id,
        "mode":          mode,
        "query":         query,
        "config":        config,
        "status":        JobStatus.PENDING,
        "created_at":    now,
        "updated_at":    now,
        "total_fetched": 0,
        "progress_log":  [],
        "error":         None,
    }
    _write_state(job_id, state)

    t = threading.Thread(
        target=_run_worker,
        args=(job_id, mode, query, config),
        daemon=True,
        name=f"fb-deep-search-{job_id}",
    )
    t.start()

    return job_id


def get_job(job_id: str) -> Optional[dict]:
    return _read_state(job_id)


def get_job_posts(job_id: str) -> list:
    return _read_posts(job_id)


def cancel_job(job_id: str) -> bool:
    state = _read_state(job_id)
    if not state:
        return False
    if state.get("status") in (JobStatus.COMPLETED, JobStatus.ERROR, JobStatus.CANCELLED):
        return False
    _update_state(job_id, status=JobStatus.CANCELLED)
    return True


def delete_job(job_id: str) -> bool:
    cancel_job(job_id)
    deleted = False
    for path in (_state_path(job_id), _posts_path(job_id)):
        if os.path.exists(path):
            try:
                os.remove(path)
                deleted = True
            except Exception:
                pass
    return deleted


def list_all_jobs() -> list:
    jobs = []
    try:
        for fname in sorted(os.listdir(_JOBS_DIR), reverse=True):
            if not fname.endswith(".json"):
                continue
            job_id = fname[:-5]
            state  = _read_state(job_id)
            if not state:
                continue
            jobs.append({
                "job_id":        state.get("job_id"),
                "mode":          state.get("mode"),
                "query":         state.get("query"),
                "status":        state.get("status"),
                "total_fetched": state.get("total_fetched", 0),
                "created_at":    state.get("created_at"),
                "updated_at":    state.get("updated_at"),
                "error":         state.get("error"),
            })
    except Exception:
        pass
    return jobs


# ── Worker ──────────────────────────────────────────────────────────────────

def _is_cancelled(job_id: str) -> bool:
    state = _read_state(job_id)
    return (state or {}).get("status") == JobStatus.CANCELLED


def _log_progress(job_id: str, msg: str):
    state = _read_state(job_id) or {}
    log   = state.get("progress_log", [])
    log.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    if len(log) > 50:
        log = log[-50:]
    _update_state(job_id, progress_log=log)
    print(f"[FB-DeepSearch:{job_id}] {msg}")


def _finalize(job_id: str, posts: list, config: Optional[dict] = None):
    """
    CHANGES v3: Apply sort & min filters sebelum save final.
    sort_by default "engagement" jika tidak ada di config.
    """
    if config is None:
        config = {}

    sort_by = config.get("sort_by", "engagement")
    min_likes = config.get("min_likes")
    min_comments = config.get("min_comments")
    min_views = config.get("min_views")

    # Apply min filters
    posts = _apply_min_filters_local(posts, min_likes, min_comments, min_views)
    # Apply sorting & assign rank
    posts = _apply_sort_local(posts, sort_by)

    _write_posts(job_id, posts)
    status = JobStatus.CANCELLED if _is_cancelled(job_id) else JobStatus.COMPLETED
    _update_state(job_id, status=status, total_fetched=len(posts))
    _log_progress(job_id, f"Selesai ({status}): {len(posts)} posts total (sort={sort_by})")


def _run_worker(job_id: str, mode: str, query: str, config: dict):
    """Worker utama — lazy import scraper agar tidak blokir startup."""
    _update_state(job_id, status=JobStatus.RUNNING)
    _log_progress(job_id, f"Worker started — mode={mode} query='{query}'")

    try:
        from fb_keyword_monitor import FacebookKeywordMonitor

        with FacebookKeywordMonitor() as monitor:
            if mode == "keyword":
                _worker_keyword(job_id, query, config, monitor)
            elif mode == "hashtag":
                _worker_hashtag(job_id, query, config, monitor)
            elif mode == "trending":
                _worker_trending(job_id, query, config, monitor)
            else:
                raise ValueError(f"Mode tidak dikenal: {mode}")

    except Exception as e:
        traceback.print_exc()
        if not _is_cancelled(job_id):
            _update_state(job_id, status=JobStatus.ERROR, error=str(e))
            _log_progress(job_id, f"ERROR: {e}")


# ── Helper: add posts ─────────────────────────────────────────────────────
def _is_valid_result_url(url: str) -> bool:
    if not url:
        return False
    u = url.lower()
    if any(x in u for x in ['/legal/','/privacy/','/help/','/about/','/policies','/security/','/stories/']):
        return False
    if 'facebook.com/photo/?fbid=' in u or '/photo/?fbid=' in u:
        return True
    if '/watch/?v=' in u or '/watch?v=' in u:
        return True
    if re.search(r'/groups/[^/]+/(posts|permalink)/\d+', u):
        return True
    if re.search(r'facebook\.com/groups/[^/?#]+/?(?:[?#].*)?$', u):
        return True
    if re.search(r'/(posts|permalink|videos|video|reel|reels)/\d+', u):
        return True
    if re.search(r'/(photo|photos)/\d+', u):
        return True
    return False


def _merge_posts(new_posts: list, seen: set, posts: list,
                 source_label: str, source_key: str = "deep_source") -> int:
    """Merge new posts into the master list, dedup by url. Returns added count."""
    added = 0
    for p in new_posts:
        key = p.get("url") or p.get("cleanHref")
        if not key or key in seen or not _is_valid_result_url(key):
            continue
        seen.add(key)
        p[source_key] = source_label
        posts.append(p)
        added += 1
    return added


# ── _worker_keyword ───────────────────────────────────────────────────────
def _worker_keyword(job_id: str, keyword: str, config: dict, monitor):
    """Deep search keyword — sequential per keyword, flush tiap step."""
    max_related   = config.get("max_related", 5)
    types         = config.get("types", ["posts", "videos", "groups", "pages"])
    max_per_query = config.get("max_per_query", 200)
    max_total     = config.get("max_total", 1000)
    sort_by       = config.get("sort_by", "engagement")

    # v4: comment scraping params
    max_comments_per_post = config.get("max_comments_per_post", 0)
    top_comments_count = config.get("top_comments_count", 5)

    # Pass sort/filter/comment params ke monitor.scrape_keyword()
    kwargs = {
        "sort_by": sort_by,
        "min_likes": config.get("min_likes"),
        "min_comments": config.get("min_comments"),
        "min_views": config.get("min_views"),
        # Deep jobs enrich comments once after URL deduplication.
        "max_comments_per_post": 0,
        "top_comments_count": top_comments_count,
    }

    seen:  set  = set()
    posts: list = []

    # ── Step 1: Scrape keyword utama ──
    if _is_cancelled(job_id):
        return
    _log_progress(job_id, f"Step 1: scraping '{keyword}' (types={types})...")
    if max_comments_per_post > 0:
        _log_progress(job_id, f"  (comment scraping enabled: {max_comments_per_post}/post, top {top_comments_count})")

    try:
        result = monitor.scrape_keyword(keyword, max_results=max_per_query,
                                         types=types, **kwargs)
        added = _merge_posts(result.get("results", []), seen, posts, keyword)
        _log_progress(job_id, f"  '{keyword}': +{added} posts (total: {len(posts)})")
    except Exception as e:
        _log_progress(job_id, f"  \u26a0\ufe0f '{keyword}' gagal: {e}")

    _update_state(job_id, total_fetched=len(posts))
    _write_posts(job_id, posts)
    _log_progress(job_id, f"  Flush after step 1: {len(posts)} posts saved to disk")

    # ── Step 2: Expand ke related keywords ──
    related_keywords = _generate_related_keywords(keyword, max_related)
    _log_progress(job_id, f"Step 2: expand ke {len(related_keywords)} related keywords (sequential)...")

    for i, rk in enumerate(related_keywords, 1):
        if _is_cancelled(job_id):
            break
        if len(posts) >= max_total:
            break

        time.sleep(random.uniform(0.3, 1.0))
        _log_progress(job_id, f"  [{i}/{len(related_keywords)}] '{rk}'...")
        try:
            r2 = monitor.scrape_keyword(rk, max_results=100, types=["posts"], **kwargs)
            added2 = _merge_posts(r2.get("results", []), seen, posts, rk)
            _log_progress(job_id, f"    +{added2} posts (total: {len(posts)})")
        except Exception as e:
            _log_progress(job_id, f"    \u26a0\ufe0f '{rk}' gagal: {e}")

        _update_state(job_id, total_fetched=len(posts))
        _write_posts(job_id, posts)
        _log_progress(job_id, f"  Flush: {len(posts)} posts saved to disk")

    if max_comments_per_post > 0 and posts:
        _log_progress(job_id, f"Scraping comments for {len(posts)} unique results...")
        monitor.enrich_comments(
            posts, max_comments_per_post, top_comments_count,
            lambda msg: _log_progress(job_id, msg),
        )
        _write_posts(job_id, posts)
    _finalize(job_id, posts, config)


# ── _worker_hashtag ───────────────────────────────────────────────────────
def _worker_hashtag(job_id: str, tag: str, config: dict, monitor):
    """Deep search hashtag — sequential seperti keyword worker."""
    max_related   = config.get("max_related_hashtags", 10)
    max_per_query = config.get("max_per_query", 300)
    max_total     = config.get("max_total", 1000)
    sort_by       = config.get("sort_by", "engagement")

    # v4: comment scraping params
    max_comments_per_post = config.get("max_comments_per_post", 0)
    top_comments_count = config.get("top_comments_count", 5)

    kwargs = {
        "sort_by": sort_by,
        "min_likes": config.get("min_likes"),
        "min_comments": config.get("min_comments"),
        "min_views": config.get("min_views"),
        "max_comments_per_post": 0,
        "top_comments_count": top_comments_count,
    }

    seen:  set  = set()
    posts: list = []

    if _is_cancelled(job_id):
        return

    # ── Step 1: panggil monitor.scrape_hashtag() yang sudah pake real URL + fallback
    _log_progress(job_id, f"Step 1: scraping '#{tag}' (hashtag URL + fallback)...")
    if max_comments_per_post > 0:
        _log_progress(job_id, f"  (comment scraping enabled: {max_comments_per_post}/post)")

    try:
        result = monitor.scrape_hashtag(tag, max_results=max_per_query, **kwargs)
        # result['results'] sudah ter-sort dan ter-filter oleh monitor
        added = _merge_posts(result.get("results", []), seen, posts, tag, "deep_source_tag")
        _log_progress(job_id, f"  '#{tag}': +{added} posts (total: {len(posts)})")
    except Exception as e:
        _log_progress(job_id, f"  \u26a0\ufe0f '#{tag}' gagal: {e}")

    _update_state(job_id, total_fetched=len(posts))
    _write_posts(job_id, posts)
    _log_progress(job_id, f"  Flush after step 1: {len(posts)} posts saved to disk")

    # ── Step 2: related keywords ──
    related = _generate_related_hashtags(tag, max_related, posts)
    _log_progress(job_id, f"Step 2: expand ke {len(related)} related keywords (sequential)...")

    for i, rk in enumerate(related, 1):
        if _is_cancelled(job_id):
            break
        if len(posts) >= max_total:
            break

        time.sleep(random.uniform(0.3, 1.0))
        _log_progress(job_id, f"  [{i}/{len(related)}] '{rk}'...")
        try:
            r2 = monitor.scrape_keyword(rk, max_results=150, types=["posts", "videos"], **kwargs)
            from fb_keyword_monitor import _hashtag_in_item
            relevant = [p for p in r2.get("results", []) if _hashtag_in_item(p, tag)]
            added2 = _merge_posts(relevant, seen, posts, rk, "deep_source_tag")
            _log_progress(job_id, f"    +{added2} posts (total: {len(posts)})")
        except Exception as e:
            _log_progress(job_id, f"    \u26a0\ufe0f '{rk}' gagal: {e}")

        _update_state(job_id, total_fetched=len(posts))
        _write_posts(job_id, posts)
        _log_progress(job_id, f"  Flush: {len(posts)} posts saved to disk")

    if max_comments_per_post > 0 and posts:
        _log_progress(job_id, f"Scraping comments for {len(posts)} unique results...")
        monitor.enrich_comments(
            posts, max_comments_per_post, top_comments_count,
            lambda msg: _log_progress(job_id, msg),
        )
        _write_posts(job_id, posts)
    _finalize(job_id, posts, config)


# ── _worker_trending ──────────────────────────────────────────────────────
def _worker_trending(job_id: str, query: str, config: dict, monitor):
    """Deep search trending — sequential per keyword."""
    types     = config.get("types", ["posts", "videos", "groups", "pages"])
    max_total = config.get("max_total", 1000)
    sort_by   = config.get("sort_by", "engagement")

    # v4: comment scraping params
    max_comments_per_post = config.get("max_comments_per_post", 0)
    top_comments_count = config.get("top_comments_count", 5)

    kwargs = {
        "sort_by": sort_by,
        "min_likes": config.get("min_likes"),
        "min_comments": config.get("min_comments"),
        "min_views": config.get("min_views"),
        "max_comments_per_post": 0,
        "top_comments_count": top_comments_count,
    }

    seen:  set  = set()
    posts: list = []

    if query:
        search_keywords = [query]
    else:
        search_keywords = [
            "viral hari ini",
            "trending indonesia",
            "berita terkini",
            "breaking news",
        ]

    _log_progress(job_id, f"Scraping {len(search_keywords)} keywords (sequential)...")

    for i, kw in enumerate(search_keywords, 1):
        if _is_cancelled(job_id):
            break
        if len(posts) >= max_total:
            break

        _log_progress(job_id, f"[{i}/{len(search_keywords)}] Trending: '{kw}'...")
        try:
            # monitor.scrape_trending() sudah handle engagement filter internal
            result = monitor.scrape_trending(
                max_results=200,
                keyword=kw,
                types=types,
                **kwargs
            )
            added = 0
            for p in result.get("results", []):
                key = p.get("url") or p.get("cleanHref")
                if not key or key in seen or not _is_valid_result_url(key):
                    continue
                seen.add(key)
                p["deep_source"] = kw
                posts.append(p)
                added += 1
            _log_progress(job_id, f"  +{added} posts (total: {len(posts)})")
        except Exception as e:
            _log_progress(job_id, f"  \u26a0\ufe0f '{kw}' gagal: {e}")

        _update_state(job_id, total_fetched=len(posts))
        _write_posts(job_id, posts)
        _log_progress(job_id, f"  Flush: {len(posts)} posts saved to disk")

    if max_comments_per_post > 0 and posts:
        _log_progress(job_id, f"Scraping comments for {len(posts)} unique results...")
        monitor.enrich_comments(
            posts, max_comments_per_post, top_comments_count,
            lambda msg: _log_progress(job_id, msg),
        )
        _write_posts(job_id, posts)
    _finalize(job_id, posts, config)


# ── Keyword/ hashtag generators ──────────────────────────────────────────
def _generate_related_keywords(keyword: str, max_count: int) -> list:
    variations = []
    kw_lower = keyword.lower().strip()
    prefixes = ["", "berita ", "info ", "update "]
    suffixes = ["", " terbaru", " hari ini", " viral", " trending"]
    for pre in prefixes:
        for suf in suffixes:
            variation = f"{pre}{kw_lower}{suf}".strip()
            if variation != kw_lower and variation not in variations:
                variations.append(variation)
    if " " in kw_lower:
        variations.append(f'"{kw_lower}"')
    return variations[:max_count]


def _generate_related_hashtags(tag: str, max_count: int, posts: Optional[list] = None) -> list:
    """Discover co-occurring tags instead of inventing unrelated suffixes."""
    counts = {}
    tag_clean = tag.lower().strip().lstrip("#")
    for post in posts or []:
        text = " ".join(str(post.get(k, "") or "") for k in ("text", "caption"))
        tags = {x.lower() for x in re.findall(r"#([\w]+)", text, re.UNICODE)}
        if tag_clean not in tags:
            continue
        for candidate in tags:
            if candidate != tag_clean and len(candidate) >= 3:
                counts[candidate] = counts.get(candidate, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [candidate for candidate, _ in ranked[:max_count]]
