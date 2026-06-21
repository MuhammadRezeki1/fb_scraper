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
import math
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs

# ── Folder penyimpanan state job ────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
_JOBS_DIR  = os.path.join(_HERE, "fb_deep_jobs")
_POSTS_DIR = os.path.join(_JOBS_DIR, "posts")
DEFAULT_DETAIL_ENRICH_LIMIT = int(os.getenv("FB_DETAIL_ENRICH_LIMIT", "24"))
DEFAULT_FAST_MAX_RELATED = int(os.getenv("FB_DEEP_FAST_MAX_RELATED", "2"))
DEFAULT_FAST_RELATED_LIMIT = int(os.getenv("FB_DEEP_FAST_RELATED_LIMIT", "60"))
DEFAULT_FAST_ROOT_LIMIT = int(os.getenv("FB_DEEP_FAST_ROOT_LIMIT", "100"))
DEFAULT_FAST_DETAIL_ENRICH_LIMIT = int(os.getenv("FB_DEEP_FAST_DETAIL_ENRICH_LIMIT", "12"))
FAST_TYPES = {"posts", "videos"}

os.makedirs(_JOBS_DIR,  exist_ok=True)
os.makedirs(_POSTS_DIR, exist_ok=True)


def _as_bool(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _fast_types(types: list) -> list:
    filtered = [t for t in (types or []) if t in FAST_TYPES]
    return filtered or ["posts", "videos"]


def _mix_types(types: list, mix: dict) -> list:
    existing = list(dict.fromkeys(types or ["posts", "videos"]))
    if mix["mode"] == "posts_only":
        return [t for t in existing if t != "videos"] or ["posts"]
    if mix["mode"] == "videos_only":
        return ["videos"]
    ordered = []
    if "posts" in existing:
        ordered.append("posts")
    ordered.extend(t for t in existing if t not in {"posts", "videos"})
    if "videos" in existing:
        ordered.append("videos")
    return ordered or ["posts", "videos"]


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
def _metric_value(value) -> int:
    try:
        if value is None:
            return 0
        return int(value or 0)
    except Exception:
        return 0


def _engagement_score(item: dict) -> float:
    return (
        _metric_value(item.get("likes_count")) +
        _metric_value(item.get("comments_count")) * 2 +
        _metric_value(item.get("shares_count")) * 3 +
        _metric_value(item.get("views_count")) * 0.1
    )


VIRAL_LEVEL_ORDER = {
    "unknown": 0,
    "low": 1,
    "potential": 2,
    "viral": 3,
    "strong_viral": 4,
    "very_viral": 5,
}


def _is_video_result(item: dict) -> bool:
    typ = (item.get("type") or "").lower()
    url = (item.get("url") or "").lower()
    return typ in {"videos", "video", "reel", "reels", "watch"} or any(
        x in url for x in ("/watch", "/reel/", "/reels/", "/videos/", "/video/", "/share/v/")
    )


def _is_metric_empty(item: dict) -> bool:
    return not any(
        _metric_value(item.get(key)) > 0
        for key in ("likes_count", "comments_count", "shares_count", "views_count")
    )


def _content_priority(item: dict) -> int:
    if not _is_video_result(item):
        return 1
    if item.get("metrics_valid") is True:
        return 2
    return 3 if not _is_metric_empty(item) else 4


def _count_videos(items: list) -> int:
    return sum(1 for item in items if _is_video_result(item))


def _count_non_videos(items: list) -> int:
    return sum(1 for item in items if not _is_video_result(item))


def _resolve_content_mix(config: dict, total_limit: int) -> dict:
    mode = config.get("content_mix_mode") or "posts_first_80_20"
    ratios = {
        "posts_first_80_20": (0.8, 0.2),
        "posts_first_60_40": (0.6, 0.4),
        "balanced_50_50": (0.5, 0.5),
        "posts_only": (1.0, 0.0),
        "videos_only": (0.0, 1.0),
    }
    post_ratio, video_ratio = ratios.get(mode, ratios["posts_first_80_20"])
    posts_target = int(config.get("posts_target") or round(total_limit * post_ratio))
    videos_target = int(config.get("videos_target") or (total_limit - posts_target if video_ratio > 0 else 0))
    if mode == "posts_only":
        posts_target, videos_target = total_limit, 0
    elif mode == "videos_only":
        posts_target, videos_target = 0, total_limit
    posts_target = max(0, min(total_limit, posts_target))
    videos_target = max(0, min(total_limit - posts_target, videos_target))
    if posts_target + videos_target < total_limit:
        posts_target += total_limit - posts_target - videos_target
    return {
        "mode": mode,
        "posts_target": posts_target,
        "videos_target": videos_target,
        "prioritize_posts": _as_bool(config.get("prioritize_posts"), True),
        "viral_only": _as_bool(config.get("viral_only"), False),
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


def _assign_viral_fields_local(item: dict) -> dict:
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
    if _is_video_result(item) and views >= 10000:
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
    _assign_viral_fields_local(item)
    return (
        -_content_priority(item),
        VIRAL_LEVEL_ORDER.get(item.get("viral_level", "unknown"), 0),
        float(item.get("viral_score") or 0),
        _metric_value(item.get("comments_count")),
        _metric_value(item.get("likes_count")),
        _metric_value(item.get("shares_count")),
        _metric_value(item.get("views_count")),
        str(item.get("timestamp") or item.get("created_time") or ""),
    )


def _priority_sort_key(item: dict):
    _assign_viral_fields_local(item)
    is_video = _is_video_result(item)
    primary_metrics = (
        _metric_value(item.get("views_count")),
        _metric_value(item.get("comments_count")),
        _metric_value(item.get("likes_count")),
        _metric_value(item.get("shares_count")),
    ) if is_video else (
        _metric_value(item.get("comments_count")),
        _metric_value(item.get("likes_count")),
        _metric_value(item.get("shares_count")),
        _metric_value(item.get("views_count")),
    )
    return (
        _content_priority(item),
        -primary_metrics[0],
        -primary_metrics[1],
        -primary_metrics[2],
        -primary_metrics[3],
        -float(item.get("viral_score") or 0),
        -VIRAL_LEVEL_ORDER.get(item.get("viral_level", "unknown"), 0),
        str(item.get("timestamp") or item.get("created_time") or ""),
    )


def _apply_content_mix_local(items: list, config: dict) -> list:
    if not items:
        return items
    max_total = int(config.get("max_total", len(items)) or len(items))
    mix = _resolve_content_mix(config, max_total)
    for item in items:
        _assign_viral_fields_local(item)
        item["content_priority"] = _content_priority(item)

    candidates = list(items)
    if mix["viral_only"]:
        candidates = [
            item for item in candidates
            if item.get("metrics_valid") is not False
            and VIRAL_LEVEL_ORDER.get(item.get("viral_level", "unknown"), 0) >= VIRAL_LEVEL_ORDER["viral"]
        ]

    posts = sorted([item for item in candidates if not _is_video_result(item)], key=_priority_sort_key)
    videos = sorted([item for item in candidates if _is_video_result(item)], key=_priority_sort_key)

    if mix["mode"] == "posts_only":
        selected = posts[:max_total]
        for idx, item in enumerate(selected, 1):
            item["rank"] = idx
        return selected

    if mix["mode"] == "videos_only":
        selected = videos[:max_total]
        for idx, item in enumerate(selected, 1):
            item["rank"] = idx
        return selected

    selected = posts[:mix["posts_target"]] + videos[:mix["videos_target"]]
    remaining_slots = max_total - len(selected)
    if remaining_slots > 0:
        selected_keys = {_content_key(item.get("url") or item.get("cleanHref")) for item in selected}
        overflow = [
            item for item in sorted(candidates, key=_priority_sort_key)
            if _content_key(item.get("url") or item.get("cleanHref")) not in selected_keys
        ]
        selected.extend(overflow[:remaining_slots])
    selected = sorted(selected[:max_total], key=_priority_sort_key)
    for idx, item in enumerate(selected, 1):
        item["rank"] = idx
    return selected


def _apply_sort_local(items: list, sort_by: str) -> list:
    """Apply sorting by the specified metric. Modifies list in-place."""
    if not items:
        return items
    for item in items:
        _assign_viral_fields_local(item)

    if sort_by in ("engagement", "viral", "trending", "", None):
        items.sort(key=_priority_sort_key)
    elif sort_by == "likes":
        items.sort(key=lambda x: _metric_value(x.get("likes_count")), reverse=True)
    elif sort_by == "comments":
        items.sort(key=lambda x: _metric_value(x.get("comments_count")), reverse=True)
    elif sort_by == "views":
        items.sort(key=lambda x: _metric_value(x.get("views_count")), reverse=True)
    elif sort_by == "shares":
        items.sort(key=lambda x: _metric_value(x.get("shares_count")), reverse=True)
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
        if min_likes is not None and _metric_value(item.get("likes_count")) < min_likes:
            continue
        if min_comments is not None and _metric_value(item.get("comments_count")) < min_comments:
            continue
        if min_views is not None and _metric_value(item.get("views_count")) < min_views:
            continue
        filtered.append(item)
    return filtered


def _parse_post_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    raw = str(value).strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        pass

    low = raw.lower()
    m = re.search(r'(\d+)\s*(detik|sec|second|menit|mnt|min|minute|jam|hour|hr|hari|day|minggu|mgg|week|bulan|month|tahun|year)', low)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2)
    now = datetime.now()
    if unit in ("detik", "sec", "second"):
        return now - timedelta(seconds=n)
    if unit in ("menit", "mnt", "min", "minute"):
        return now - timedelta(minutes=n)
    if unit in ("jam", "hour", "hr"):
        return now - timedelta(hours=n)
    if unit in ("hari", "day"):
        return now - timedelta(days=n)
    if unit in ("minggu", "mgg", "week"):
        return now - timedelta(weeks=n)
    if unit in ("bulan", "month"):
        return now - timedelta(days=n * 30)
    if unit in ("tahun", "year"):
        return now - timedelta(days=n * 365)
    return None


def _apply_recent_filter_local(items: list, recent_days: Optional[int]) -> list:
    if not recent_days or recent_days <= 0:
        return items
    cutoff = datetime.now() - timedelta(days=recent_days)
    kept = []
    for item in items:
        ts = _parse_post_timestamp(item.get("timestamp"))
        if ts is None or ts >= cutoff:
            kept.append(item)
    return kept


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


def _is_monitor_recoverable_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in [
        "event loop is closed",
        "playwright already stopped",
        "browser belum diinisialisasi",
        "browser has been closed",
        "target page",
        "target closed",
        "fb not logged in",
        "fb session expired",
    ])


def _is_auth_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "fb not logged in" in text or "fb session expired" in text


def _session_error_message() -> str:
    return (
        "Session Facebook tidak diterima browser Docker. "
        "Import ulang cookie/login Facebook di menu Auth, lalu jalankan ulang scraping."
    )


def _restart_monitor(monitor):
    try:
        monitor.close()
    except Exception:
        pass
    from fb_keyword_monitor import FacebookKeywordMonitor
    fresh = FacebookKeywordMonitor()
    try:
        monitor.__dict__.clear()
        monitor.__dict__.update(fresh.__dict__)
        return monitor
    except Exception:
        return fresh


def _monitor_call(job_id: str, monitor, fn_name: str, *args, **kwargs):
    for attempt in range(2):
        try:
            return monitor, getattr(monitor, fn_name)(*args, **kwargs)
        except Exception as exc:
            if attempt == 0 and _is_monitor_recoverable_error(exc):
                _log_progress(job_id, f"  Browser/session reset setelah error: {exc}")
                monitor = _restart_monitor(monitor)
                continue
            raise


def _finalize(job_id: str, posts: list, config: Optional[dict] = None):
    """
    CHANGES v3: Apply sort & min filters sebelum save final.
    sort_by default "trending" jika tidak ada di config.
    """
    if config is None:
        config = {}

    sort_by = config.get("sort_by", "trending")
    min_likes = config.get("min_likes")
    min_comments = config.get("min_comments")
    min_views = config.get("min_views")
    recent_days = config.get("recent_days", 30)

    for item in posts:
        _assign_viral_fields_local(item)

    # Apply min filters
    posts = _apply_min_filters_local(posts, min_likes, min_comments, min_views)
    before_recent = len(posts)
    posts = _apply_recent_filter_local(posts, int(recent_days) if recent_days is not None else None)
    if recent_days and before_recent != len(posts):
        _log_progress(job_id, f"Filter waktu {recent_days} hari: {before_recent} -> {len(posts)} posts")
    posts = _apply_content_mix_local(posts, config)
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
    # ✅ FIX: support format share baru FB
    if re.search(r'/share/(p|v|r)/[a-z0-9_-]+', u):
        return True
    if 'facebook.com/photo/?fbid=' in u or '/photo/?fbid=' in u:
        return True
    if '/watch' in u and re.search(r'[?&]v=\d+', u):
        return True
    if re.search(r'/groups/[^/]+/(posts|permalink)/\d+', u):
        return True
    if re.search(r'facebook\.com/groups/[^/?#]+/?(?:[?#].*)?$', u):
        return True
    if re.search(r'/(posts|permalink)/(?:\d+|pfbid[a-z0-9_-]+)', u):
        return True
    if re.search(r'/(posts|permalink|videos|video|reel|reels)/\d+', u):
        return True
    if re.search(r'/(photo|photos)/\d+', u):
        return True
    return False

def _is_search_post_card(item: dict, url: str) -> bool:
    if (item.get("source") or "") != "search_post_card":
        return False
    u = (url or "").lower()
    if "facebook.com/search/posts/" not in u or "fb_scrape_card=" not in u:
        return False
    text = " ".join(str(item.get(k, "") or "") for k in ("text", "caption", "author"))
    return len(text.strip()) >= 20

def _accept_result_item(item: dict, url: str) -> bool:
    if not url:
        return False
    return _is_valid_result_url(url) or _is_search_post_card(item, url)

def _content_key(url: str) -> str:
    if not url:
        return ""
    try:
        parsed = urlparse(url.replace("https://m.facebook.com", "https://www.facebook.com"))
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
    return (url or "").split("#")[0].rstrip("/")

def _is_canonical_video_permalink(url: str) -> bool:
    return bool(re.search(r"facebook\.com/[^/?#]+/videos/\d+", url or "", re.I))

def _merge_duplicate_post(existing: dict, incoming: dict):
    incoming_url = incoming.get("url") or incoming.get("cleanHref") or ""
    existing_url = existing.get("url") or ""
    incoming_is_canonical = _is_canonical_video_permalink(incoming_url)
    existing_is_canonical = _is_canonical_video_permalink(existing_url)
    existing_views = int(existing.get("views_count", 0) or 0)

    if incoming_is_canonical and not existing_is_canonical:
        existing["url"] = incoming_url
        existing["views_count"] = existing_views

    for key in ("caption", "text", "author", "timestamp", "page_name", "group_name"):
        old = str(existing.get(key) or "").strip()
        new = str(incoming.get(key) or "").strip()
        if new and (not old or len(new) > len(old)):
            existing[key] = incoming.get(key)

    for key in ("likes_count", "comments_count", "shares_count"):
        if int(incoming.get(key, 0) or 0) > int(existing.get(key, 0) or 0):
            existing[key] = incoming.get(key, 0)

    if int(incoming.get("views_count", 0) or 0) > int(existing.get("views_count", 0) or 0):
        existing["views_count"] = incoming.get("views_count", 0)

    if incoming.get("metrics_valid") is True and existing.get("metrics_valid") is not True:
        for key in ("metrics_valid", "metric_source", "metrics_error", "detail_status", "detail_final_url", "metric_patterns"):
            if key in incoming:
                existing[key] = incoming.get(key)
    else:
        for key in ("metrics_valid", "metric_source", "metrics_error", "detail_status"):
            if key not in existing and key in incoming:
                existing[key] = incoming.get(key)

    existing["engagement_score"] = _engagement_score(existing)
    _assign_viral_fields_local(existing)

def _split_multi_query(raw: str, strip_hash: bool = False) -> list:
    """Split comma/newline/semicolon separated query text while preserving single-query behavior."""
    parts = []
    seen = set()
    for part in re.split(r"[,;\n\r]+", raw or ""):
        q = part.strip()
        if strip_hash:
            q = q.lstrip("#").strip()
        key = q.lower()
        if q and key not in seen:
            seen.add(key)
            parts.append(q)
    return parts or ([raw.strip().lstrip("#") if strip_hash else raw.strip()] if raw and raw.strip() else [])


def _merge_posts(new_posts: list, seen: set, posts: list,
                 source_label: str, source_key: str = "deep_source",
                 root_label: Optional[str] = None) -> int:
    """Merge new posts into the master list, dedup by url. Returns added count."""
    added = 0
    root = root_label or source_label
    for p in new_posts:
        raw_url = p.get("url") or p.get("cleanHref")
        key = _content_key(raw_url)
        if not _accept_result_item(p, raw_url):
            continue
        existing = next((x for x in posts if _content_key(x.get("url") or x.get("cleanHref")) == key), None)
        if existing:
            _merge_duplicate_post(existing, p)
            continue
        if key in seen:
            continue
        seen.add(key)
        p[source_key] = source_label
        p["deep_root_query"] = root
        p["deep_query"] = root
        if source_key == "deep_source_tag":
            p["deep_root_tag"] = root
        _assign_viral_fields_local(p)
        posts.append(p)
        added += 1
    return added


def _second_pass_video_metrics(job_id: str, monitor, posts: list, config: dict):
    if not posts:
        return
    invalid_videos = [
        p for p in posts
        if _is_video_result(p) and p.get("metrics_valid") is not True
    ]
    if not invalid_videos:
        return
    try:
        detail_limit = int(config.get("detail_enrich_limit", DEFAULT_DETAIL_ENRICH_LIMIT))
    except Exception:
        detail_limit = DEFAULT_DETAIL_ENRICH_LIMIT
    if _as_bool(config.get("fast_mode"), True):
        detail_limit = min(detail_limit, DEFAULT_FAST_DETAIL_ENRICH_LIMIT)
    try:
        max_total = int(config.get("max_total", len(posts)) or len(posts))
    except Exception:
        max_total = len(posts)
    mix = _resolve_content_mix(config, max_total)
    detail_limit = min(detail_limit, mix["videos_target"])
    detail_limit = max(0, min(detail_limit, len(invalid_videos)))
    if detail_limit <= 0:
        return
    _log_progress(job_id, f"Second-pass detail video metrics: {detail_limit}/{len(invalid_videos)} invalid videos")
    monitor.enrich_missing_details(
        invalid_videos,
        limit=detail_limit,
        progress_callback=lambda msg: _log_progress(job_id, f"Second-pass {msg}"),
    )
    for item in posts:
        _assign_viral_fields_local(item)
    _write_posts(job_id, posts)


# ── _worker_keyword ───────────────────────────────────────────────────────
def _worker_keyword(job_id: str, keyword: str, config: dict, monitor):
    """Deep search keyword — sequential per keyword, flush tiap step."""
    fast_mode     = _as_bool(config.get("fast_mode"), True)
    max_related   = config.get("max_related", 5)
    types         = config.get("types", ["posts", "videos", "groups", "pages"])
    max_per_query = config.get("max_per_query", 200)
    max_total     = config.get("max_total", 1000)
    sort_by       = config.get("sort_by", "trending")
    auth_failed   = False
    mix           = _resolve_content_mix(config, max_total)

    if fast_mode:
        types = _fast_types(types)
        max_related = min(max_related, DEFAULT_FAST_MAX_RELATED)
        max_per_query = min(max_per_query, DEFAULT_FAST_ROOT_LIMIT)
    types = _mix_types(types, mix)

    # Keep each keyword root bounded by max_per_query so multi-query jobs stay predictable.
    effective_per_query = min(max_total, max(25, max_per_query))

    # v4: comment scraping params
    max_comments_per_post = config.get("max_comments_per_post", 0)
    top_comments_count = config.get("top_comments_count", 10)

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
    detail_limit = int(config.get("detail_enrich_limit", DEFAULT_DETAIL_ENRICH_LIMIT))
    if fast_mode:
        detail_limit = min(detail_limit, DEFAULT_FAST_DETAIL_ENRICH_LIMIT)
    detail_limit = min(detail_limit, mix["videos_target"])
    root_kwargs = {**kwargs, "detail_enrich_limit": detail_limit}
    fast_kwargs = {**kwargs, "detail_enrich_limit": 0}
    related_limit = DEFAULT_FAST_RELATED_LIMIT if fast_mode else 80
    related_types = _mix_types(["posts", "videos"], mix)

    root_keywords = _split_multi_query(keyword)
    if mix["prioritize_posts"] and "posts" in types and "videos" in types and mix["mode"] not in {"videos_only"}:
        seen: set = set()
        posts: list = []
        query_plan = []
        for root_kw in root_keywords:
            query_plan.append((root_kw, root_kw, True))
            for rk in _generate_related_keywords(root_kw, max_related):
                query_plan.append((rk, root_kw, False))

        _log_progress(
            job_id,
            f"Posts-first mix: mode={mix['mode']} target posts={mix['posts_target']} videos={mix['videos_target']} queries={len(query_plan)}",
        )

        for qi, (q, root_kw, is_root) in enumerate(query_plan, 1):
            if _is_cancelled(job_id) or _count_non_videos(posts) >= mix["posts_target"]:
                break
            remaining_posts = max(1, mix["posts_target"] - _count_non_videos(posts))
            limit = min(effective_per_query if is_root else related_limit, remaining_posts)
            _log_progress(job_id, f"Posts phase {qi}/{len(query_plan)}: '{q}' (limit={limit})...")
            try:
                monitor, result = _monitor_call(
                    job_id,
                    monitor,
                    "scrape_keyword",
                    q,
                    max_results=limit,
                    types=["posts"],
                    **fast_kwargs,
                )
                added = _merge_posts(result.get("results", []), seen, posts, q, "deep_source", root_kw)
                _log_progress(job_id, f"  posts +{added} (total: {_count_non_videos(posts)})")
            except Exception as e:
                if _is_auth_error(e):
                    auth_failed = True
                _log_progress(job_id, f"  ⚠️ posts '{q}' gagal: {e}")
            _update_state(job_id, total_fetched=len(posts))
            _write_posts(job_id, posts)

        if mix["videos_target"] > 0:
            for qi, (q, root_kw, is_root) in enumerate(query_plan, 1):
                if _is_cancelled(job_id) or _count_videos(posts) >= mix["videos_target"]:
                    break
                remaining_videos = max(1, mix["videos_target"] - _count_videos(posts))
                limit = min(effective_per_query if is_root else related_limit, remaining_videos)
                video_detail_limit = min(detail_limit, remaining_videos)
                _log_progress(job_id, f"Videos phase {qi}/{len(query_plan)}: '{q}' (limit={limit}, detail={video_detail_limit})...")
                try:
                    monitor, result = _monitor_call(
                        job_id,
                        monitor,
                        "scrape_keyword",
                        q,
                        max_results=limit,
                        types=["videos"],
                        **{**kwargs, "detail_enrich_limit": video_detail_limit},
                    )
                    added = _merge_posts(result.get("results", []), seen, posts, q, "deep_source", root_kw)
                    _log_progress(job_id, f"  videos +{added} (total: {_count_videos(posts)})")
                except Exception as e:
                    if _is_auth_error(e):
                        auth_failed = True
                    _log_progress(job_id, f"  ⚠️ videos '{q}' gagal: {e}")
                _update_state(job_id, total_fetched=len(posts))
                _write_posts(job_id, posts)

        if not posts and auth_failed:
            raise RuntimeError(_session_error_message())
        _second_pass_video_metrics(job_id, monitor, posts, config)
        if max_comments_per_post > 0 and posts:
            _log_progress(job_id, f"Scraping comments for {len(posts)} unique results...")
            monitor.enrich_comments(
                posts, max_comments_per_post, top_comments_count,
                lambda msg: _log_progress(job_id, msg),
            )
            _write_posts(job_id, posts)
        _finalize(job_id, posts, config)
        return

    if len(root_keywords) > 1:
        seen: set = set()
        posts: list = []
        _log_progress(job_id, f"Multi keyword: {len(root_keywords)} query ({', '.join(root_keywords)})")
        if fast_mode:
            _log_progress(job_id, f"  Fast mode aktif: types={types}, max_related={max_related}, detail_limit={detail_limit}")
        if max_comments_per_post > 0:
            _log_progress(job_id, f"  (comment scraping enabled: {max_comments_per_post}/post, top {top_comments_count})")

        for qi, root_kw in enumerate(root_keywords, 1):
            if _is_cancelled(job_id) or len(posts) >= max_total:
                break
            remaining = max_total - len(posts)
            root_limit = max(1, min(effective_per_query, remaining))
            _log_progress(job_id, f"Query {qi}/{len(root_keywords)}: scraping '{root_kw}' (limit={root_limit}, types={types})...")
            try:
                monitor, result = _monitor_call(job_id, monitor, "scrape_keyword", root_kw, max_results=root_limit, types=types, **root_kwargs)
                added = _merge_posts(result.get("results", []), seen, posts, root_kw, "deep_source", root_kw)
                _log_progress(job_id, f"  '{root_kw}': +{added} posts (combined total: {len(posts)})")
            except Exception as e:
                if _is_auth_error(e):
                    auth_failed = True
                _log_progress(job_id, f"  \u26a0\ufe0f '{root_kw}' gagal: {e}")

            related_keywords = _generate_related_keywords(root_kw, max_related)
            _log_progress(job_id, f"  Expand '{root_kw}' ke {len(related_keywords)} related keywords...")
            for i, rk in enumerate(related_keywords, 1):
                if _is_cancelled(job_id) or len(posts) >= max_total:
                    break
                if not fast_mode:
                    time.sleep(random.uniform(0.3, 1.0))
                _log_progress(job_id, f"    [{i}/{len(related_keywords)}] '{rk}'...")
                try:
                    monitor, r2 = _monitor_call(job_id, monitor, "scrape_keyword", rk, max_results=min(related_limit, max_total - len(posts)), types=related_types, **fast_kwargs)
                    added2 = _merge_posts(r2.get("results", []), seen, posts, rk, "deep_source", root_kw)
                    _log_progress(job_id, f"      +{added2} posts (combined total: {len(posts)})")
                except Exception as e:
                    if _is_auth_error(e):
                        auth_failed = True
                    _log_progress(job_id, f"      \u26a0\ufe0f '{rk}' gagal: {e}")

            _update_state(job_id, total_fetched=len(posts))
            _write_posts(job_id, posts)
            _log_progress(job_id, f"  Flush after '{root_kw}': {len(posts)} posts saved to disk")

        if not posts and auth_failed:
            raise RuntimeError(_session_error_message())
        _second_pass_video_metrics(job_id, monitor, posts, config)
        if max_comments_per_post > 0 and posts:
            _log_progress(job_id, f"Scraping comments for {len(posts)} unique results...")
            monitor.enrich_comments(
                posts, max_comments_per_post, top_comments_count,
                lambda msg: _log_progress(job_id, msg),
            )
            _write_posts(job_id, posts)
        _finalize(job_id, posts, config)
        return

    seen:  set  = set()
    posts: list = []

    # ── Step 1: Scrape keyword utama ──
    if _is_cancelled(job_id):
        return
    _log_progress(job_id, f"Step 1: scraping '{keyword}' (types={types})...")
    if fast_mode:
        _log_progress(job_id, f"  Fast mode aktif: max_related={max_related}, detail_limit={detail_limit}")
    if max_comments_per_post > 0:
        _log_progress(job_id, f"  (comment scraping enabled: {max_comments_per_post}/post, top {top_comments_count})")

    try:
        monitor, result = _monitor_call(job_id, monitor, "scrape_keyword", keyword, max_results=effective_per_query,
                                         types=types, **root_kwargs)
        added = _merge_posts(result.get("results", []), seen, posts, keyword, "deep_source", keyword)
        _log_progress(job_id, f"  '{keyword}': +{added} posts (total: {len(posts)})")
    except Exception as e:
        if _is_auth_error(e):
            auth_failed = True
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

        if not fast_mode:
            time.sleep(random.uniform(0.3, 1.0))
        _log_progress(job_id, f"  [{i}/{len(related_keywords)}] '{rk}'...")
        try:
            monitor, r2 = _monitor_call(job_id, monitor, "scrape_keyword", rk, max_results=related_limit, types=related_types, **fast_kwargs)
            added2 = _merge_posts(r2.get("results", []), seen, posts, rk, "deep_source", keyword)
            _log_progress(job_id, f"    +{added2} posts (total: {len(posts)})")
        except Exception as e:
            if _is_auth_error(e):
                auth_failed = True
            _log_progress(job_id, f"    \u26a0\ufe0f '{rk}' gagal: {e}")

        _update_state(job_id, total_fetched=len(posts))
        _write_posts(job_id, posts)
        _log_progress(job_id, f"  Flush: {len(posts)} posts saved to disk")

    if not posts and auth_failed:
        raise RuntimeError(_session_error_message())
    _second_pass_video_metrics(job_id, monitor, posts, config)
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
    fast_mode     = _as_bool(config.get("fast_mode"), True)
    types         = config.get("types", ["posts", "videos"])
    max_related   = config.get("max_related_hashtags", 10)
    max_per_query = config.get("max_per_query", 300)
    max_total     = config.get("max_total", 1000)
    sort_by       = config.get("sort_by", "trending")
    auth_failed   = False
    mix           = _resolve_content_mix(config, max_total)

    if fast_mode:
        types = _fast_types(types)
        max_related = min(max_related, DEFAULT_FAST_MAX_RELATED)
        max_per_query = min(max_per_query, DEFAULT_FAST_ROOT_LIMIT)
    types = _mix_types(types, mix)

    # Keep each hashtag root bounded by max_per_query so multi-tag jobs stay predictable.
    effective_per_query = min(max_total, max(25, max_per_query))

    # v4: comment scraping params
    max_comments_per_post = config.get("max_comments_per_post", 0)
    top_comments_count = config.get("top_comments_count", 10)

    kwargs = {
        "sort_by": sort_by,
        "min_likes": config.get("min_likes"),
        "min_comments": config.get("min_comments"),
        "min_views": config.get("min_views"),
        "max_comments_per_post": 0,
        "top_comments_count": top_comments_count,
    }
    detail_limit = int(config.get("detail_enrich_limit", DEFAULT_DETAIL_ENRICH_LIMIT))
    if fast_mode:
        detail_limit = min(detail_limit, DEFAULT_FAST_DETAIL_ENRICH_LIMIT)
    detail_limit = min(detail_limit, mix["videos_target"])
    root_kwargs = {**kwargs, "detail_enrich_limit": detail_limit}
    fast_kwargs = {**kwargs, "detail_enrich_limit": 0}
    related_limit = DEFAULT_FAST_RELATED_LIMIT if fast_mode else 100
    related_types = _mix_types(["posts", "videos"], mix)

    root_tags = _split_multi_query(tag, strip_hash=True)
    if len(root_tags) > 1:
        seen: set = set()
        posts: list = []
        _log_progress(job_id, f"Multi hashtag: {len(root_tags)} tag ({', '.join('#' + t for t in root_tags)})")
        if fast_mode:
            _log_progress(job_id, f"  Fast mode aktif: max_related={max_related}, detail_limit={detail_limit}")
        if max_comments_per_post > 0:
            _log_progress(job_id, f"  (comment scraping enabled: {max_comments_per_post}/post)")

        for qi, root_tag in enumerate(root_tags, 1):
            if _is_cancelled(job_id) or len(posts) >= max_total:
                break
            remaining = max_total - len(posts)
            root_limit = max(1, min(effective_per_query, remaining))
            _log_progress(job_id, f"Query {qi}/{len(root_tags)}: scraping '#{root_tag}' (limit={root_limit})...")
            try:
                monitor, result = _monitor_call(job_id, monitor, "scrape_hashtag", root_tag, max_results=root_limit, types=types, **root_kwargs)
                added = _merge_posts(result.get("results", []), seen, posts, root_tag, "deep_source_tag", root_tag)
                _log_progress(job_id, f"  '#{root_tag}': +{added} posts (combined total: {len(posts)})")
            except Exception as e:
                if _is_auth_error(e):
                    auth_failed = True
                _log_progress(job_id, f"  \u26a0\ufe0f '#{root_tag}' gagal: {e}")

            related = _generate_related_hashtags(root_tag, max_related, posts)
            _log_progress(job_id, f"  Expand '#{root_tag}' ke {len(related)} related keywords...")
            for i, rk in enumerate(related, 1):
                if _is_cancelled(job_id) or len(posts) >= max_total:
                    break
                if not fast_mode:
                    time.sleep(random.uniform(0.3, 1.0))
                _log_progress(job_id, f"    [{i}/{len(related)}] '{rk}'...")
                try:
                    monitor, r2 = _monitor_call(job_id, monitor, "scrape_keyword", rk, max_results=min(related_limit, max_total - len(posts)), types=related_types, **fast_kwargs)
                    from fb_keyword_monitor import _hashtag_in_item
                    relevant = [p for p in r2.get("results", []) if _hashtag_in_item(p, root_tag)]
                    added2 = _merge_posts(relevant, seen, posts, rk, "deep_source_tag", root_tag)
                    _log_progress(job_id, f"      +{added2} posts (combined total: {len(posts)})")
                except Exception as e:
                    if _is_auth_error(e):
                        auth_failed = True
                    _log_progress(job_id, f"      \u26a0\ufe0f '{rk}' gagal: {e}")

            _update_state(job_id, total_fetched=len(posts))
            _write_posts(job_id, posts)
            _log_progress(job_id, f"  Flush after '#{root_tag}': {len(posts)} posts saved to disk")

        if not posts and auth_failed:
            raise RuntimeError(_session_error_message())
        _second_pass_video_metrics(job_id, monitor, posts, config)
        if max_comments_per_post > 0 and posts:
            _log_progress(job_id, f"Scraping comments for {len(posts)} unique results...")
            monitor.enrich_comments(
                posts, max_comments_per_post, top_comments_count,
                lambda msg: _log_progress(job_id, msg),
            )
            _write_posts(job_id, posts)
        _finalize(job_id, posts, config)
        return

    seen:  set  = set()
    posts: list = []

    if _is_cancelled(job_id):
        return

    # ── Step 1: panggil monitor.scrape_hashtag() yang sudah pake real URL + fallback
    _log_progress(job_id, f"Step 1: scraping '#{tag}' (hashtag URL + fallback)...")
    if fast_mode:
        _log_progress(job_id, f"  Fast mode aktif: max_related={max_related}, detail_limit={detail_limit}")
    if max_comments_per_post > 0:
        _log_progress(job_id, f"  (comment scraping enabled: {max_comments_per_post}/post)")

    try:
        monitor, result = _monitor_call(job_id, monitor, "scrape_hashtag", tag, max_results=effective_per_query, types=types, **root_kwargs)
        # result['results'] sudah ter-sort dan ter-filter oleh monitor
        added = _merge_posts(result.get("results", []), seen, posts, tag, "deep_source_tag", tag)
        _log_progress(job_id, f"  '#{tag}': +{added} posts (total: {len(posts)})")
    except Exception as e:
        if _is_auth_error(e):
            auth_failed = True
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

        if not fast_mode:
            time.sleep(random.uniform(0.3, 1.0))
        _log_progress(job_id, f"  [{i}/{len(related)}] '{rk}'...")
        try:
            monitor, r2 = _monitor_call(job_id, monitor, "scrape_keyword", rk, max_results=related_limit, types=related_types, **fast_kwargs)
            from fb_keyword_monitor import _hashtag_in_item
            relevant = [p for p in r2.get("results", []) if _hashtag_in_item(p, tag)]
            added2 = _merge_posts(relevant, seen, posts, rk, "deep_source_tag", tag)
            _log_progress(job_id, f"    +{added2} posts (total: {len(posts)})")
        except Exception as e:
            if _is_auth_error(e):
                auth_failed = True
            _log_progress(job_id, f"    \u26a0\ufe0f '{rk}' gagal: {e}")

        _update_state(job_id, total_fetched=len(posts))
        _write_posts(job_id, posts)
        _log_progress(job_id, f"  Flush: {len(posts)} posts saved to disk")

    if not posts and auth_failed:
        raise RuntimeError(_session_error_message())
    _second_pass_video_metrics(job_id, monitor, posts, config)
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
    fast_mode = _as_bool(config.get("fast_mode"), True)
    types     = config.get("types", ["posts", "videos", "groups", "pages"])
    max_total = config.get("max_total", 1000)
    sort_by   = config.get("sort_by", "trending")
    auth_failed = False
    mix = _resolve_content_mix(config, max_total)
    if fast_mode:
        types = _fast_types(types)
    types = _mix_types(types, mix)

    # v4: comment scraping params
    max_comments_per_post = config.get("max_comments_per_post", 0)
    top_comments_count = config.get("top_comments_count", 10)

    kwargs = {
        "sort_by": sort_by,
        "min_likes": config.get("min_likes"),
        "min_comments": config.get("min_comments"),
        "min_views": config.get("min_views"),
        "max_comments_per_post": 0,
        "top_comments_count": top_comments_count,
    }
    detail_limit = int(config.get("detail_enrich_limit", DEFAULT_DETAIL_ENRICH_LIMIT))
    if fast_mode:
        detail_limit = min(detail_limit, DEFAULT_FAST_DETAIL_ENRICH_LIMIT)
    detail_limit = min(detail_limit, mix["videos_target"])
    root_kwargs = {**kwargs, "detail_enrich_limit": detail_limit}

    seen:  set  = set()
    posts: list = []

    if query:
        search_keywords = _split_multi_query(query)
    else:
        search_keywords = [
            "viral hari ini",
            "trending indonesia",
            "berita terkini",
            "breaking news",
        ]

    _log_progress(job_id, f"Scraping {len(search_keywords)} keywords (sequential)...")
    if fast_mode:
        _log_progress(job_id, f"  Fast mode aktif: types={types}, detail_limit={detail_limit}")

    for i, kw in enumerate(search_keywords, 1):
        if _is_cancelled(job_id):
            break
        if len(posts) >= max_total:
            break

        remaining_keywords = max(1, len(search_keywords) - i + 1)
        per_keyword_limit = max(25, min(200, math.ceil((max_total - len(posts)) / remaining_keywords)))
        if fast_mode:
            per_keyword_limit = min(per_keyword_limit, DEFAULT_FAST_ROOT_LIMIT)
        _log_progress(job_id, f"[{i}/{len(search_keywords)}] Trending: '{kw}' (limit={per_keyword_limit})...")
        try:
            # monitor.scrape_trending() sudah handle engagement filter internal
            monitor, result = _monitor_call(
                job_id,
                monitor,
                "scrape_trending",
                max_results=per_keyword_limit,
                keyword=kw,
                types=types,
                **root_kwargs
            )
            added = 0
            for p in result.get("results", []):
                raw_url = p.get("url") or p.get("cleanHref")
                key = _content_key(raw_url)
                if key in seen or not _accept_result_item(p, raw_url):
                    continue
                seen.add(key)
                p["deep_source"] = kw
                p["deep_root_query"] = kw
                p["deep_query"] = kw
                posts.append(p)
                added += 1
            _log_progress(job_id, f"  +{added} posts (total: {len(posts)})")
        except Exception as e:
            if _is_auth_error(e):
                auth_failed = True
            _log_progress(job_id, f"  \u26a0\ufe0f '{kw}' gagal: {e}")

        _update_state(job_id, total_fetched=len(posts))
        _write_posts(job_id, posts)
        _log_progress(job_id, f"  Flush: {len(posts)} posts saved to disk")

    if not posts and auth_failed:
        raise RuntimeError(_session_error_message())
    _second_pass_video_metrics(job_id, monitor, posts, config)
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
