"""
fb_deep_endpoints.py
====================
Flask Blueprint untuk Facebook Deep Search dengan checkpoint backend.

Cara pakai di facebook_api_server.py:
  from fb_deep_endpoints import deep_search_bp
  app.register_blueprint(deep_search_bp)

CHANGES v3:
  - Endpoint POST /keyword, /hashtag, /trending sekarang menerima parameter baru
    dari request body: "sort_by" (string: engagement/likes/comments/views/shares/recent),
    "min_likes", "min_comments", "min_views" (integer, optional).
  - Semua parameter ini di-pass ke config dict yang diteruskan ke sc.create_job().
  - Partial endpoint /posts/partial tetap konsisten dengan format response final.
"""

from flask import Blueprint, request, jsonify
from datetime import datetime
import traceback

import fb_search_checkpoint as sc

deep_search_bp = Blueprint("deep_search", __name__, url_prefix="/api/v1/monitor/deep")


# ── Helper response ──────────────────────────────────────────────

def _ok(data: dict, msg: str = "OK"):
    return jsonify({
        "success": True,
        "message": msg,
        "timestamp": datetime.now().isoformat(),
        "data": data
    })

def _fail(msg: str, status: int = 400):
    return jsonify({
        "success": False,
        "message": msg,
        "timestamp": datetime.now().isoformat(),
        "data": {}
    }), status


# ── Helper: extract sort/filter params from request ──────────────
def _extract_sort_filter(data: dict) -> dict:
    """
    Extract sort_by, min_likes, min_comments, min_views dari request body.
    Validasi: sort_by harus salah satu dari nilai yang diizinkan.
    """
    result = {}
    sort_by = data.get("sort_by", "engagement")
    valid_sorts = {"engagement", "likes", "comments", "views", "shares", "recent"}
    if sort_by in valid_sorts:
        result["sort_by"] = sort_by
    else:
        result["sort_by"] = "engagement"  # fallback

    for key in ("min_likes", "min_comments", "min_views"):
        val = data.get(key)
        if val is not None:
            try:
                result[key] = int(val)
            except (ValueError, TypeError):
                pass  # skip invalid value

    # v4: comment scraping params
    mcp = data.get("max_comments_per_post")
    if mcp is not None:
        try:
            result["max_comments_per_post"] = int(mcp)
        except (ValueError, TypeError):
            pass
    tcc = data.get("top_comments_count")
    if tcc is not None:
        try:
            result["top_comments_count"] = int(tcc)
        except (ValueError, TypeError):
            pass

    return result


# ── Endpoints ────────────────────────────────────────────────────

@deep_search_bp.post("/keyword")
def deep_search_keyword():
    """
    Mulai deep search keyword.
    Scrape keyword utama + expand ke related keywords.
    CHANGES v3: menerima sort_by, min_likes, min_comments, min_views.
    """
    data = request.get_json() or {}
    keyword = (data.get("keyword") or "").strip()
    if not keyword:
        return _fail("Keyword kosong")
    
    try:
        config = {
            "max_related":    int(data.get("max_related", 5)),
            "max_per_query":  int(data.get("max_per_query", 200)),
            "max_total":      int(data.get("max_total", 1000)),
            "types":          data.get("types", ["posts", "videos", "groups", "pages"]),
        }
        # Merge sort/filter params
        config.update(_extract_sort_filter(data))

        job_id = sc.create_job("keyword", keyword, config)
        return _ok(
            {"job_id": job_id, "mode": "keyword", "query": keyword},
            f"Deep search '{keyword}' dimulai (job: {job_id})"
        )
    except Exception as e:
        traceback.print_exc()
        return _fail(f"Gagal memulai job: {e}", 500)


@deep_search_bp.post("/hashtag")
def deep_search_hashtag():
    """
    Mulai deep search hashtag.
    Scrape hashtag utama + expand ke related hashtags.
    CHANGES v3: menerima sort_by, min_likes, min_comments, min_views.
    """
    data = request.get_json() or {}
    hashtag = (data.get("hashtag") or "").strip().lstrip("#").lower()
    if not hashtag:
        return _fail("Hashtag kosong")
    
    try:
        config = {
            "max_related_hashtags": int(data.get("max_related_hashtags", 10)),
            "max_per_query":        int(data.get("max_per_query", 300)),
            "max_total":            int(data.get("max_total", 1000)),
        }
        # Merge sort/filter params
        config.update(_extract_sort_filter(data))

        job_id = sc.create_job("hashtag", hashtag, config)
        return _ok(
            {"job_id": job_id, "mode": "hashtag", "query": hashtag},
            f"Deep search #{hashtag} dimulai (job: {job_id})"
        )
    except Exception as e:
        traceback.print_exc()
        return _fail(f"Gagal memulai job: {e}", 500)


@deep_search_bp.post("/trending")
def deep_search_trending():
    """
    Mulai deep search trending.
    Jika query ada: scrape trending untuk keyword tersebut.
    Jika kosong: scrape trending umum.
    CHANGES v3: menerima sort_by, min_likes, min_comments, min_views.
    """
    data = request.get_json() or {}
    query = (data.get("keyword") or data.get("query") or "").strip()
    
    try:
        config = {
            "sort_by":     data.get("sort_by", "engagement"),
            "types":       data.get("types", ["posts", "videos", "groups", "pages"]),
            "max_total":   int(data.get("max_total", 1000)),
        }
        # Merge sort/filter params (sort_by sudah di set di atas, _extract_sort_filter akan override)
        config.update(_extract_sort_filter(data))

        job_id = sc.create_job("trending", query, config)
        return _ok(
            {"job_id": job_id, "mode": "trending", "query": query or "(semua trending)"},
            f"Deep search trending dimulai (job: {job_id})"
        )
    except Exception as e:
        traceback.print_exc()
        return _fail(f"Gagal memulai job: {e}", 500)


@deep_search_bp.get("/jobs")
def list_deep_jobs():
    """Daftar semua job (ringkasan tanpa posts)."""
    try:
        jobs = sc.list_all_jobs()
        return _ok({"jobs": jobs, "count": len(jobs)})
    except Exception as e:
        return _fail(str(e), 500)


@deep_search_bp.get("/jobs/<job_id>")
def get_deep_job(job_id: str):
    """Status + progres job."""
    state = sc.get_job(job_id)
    if not state:
        return _fail(f"Job '{job_id}' tidak ditemukan", 404)
    return _ok(
        state,
        f"Job {job_id}: {state.get('status')} ({state.get('total_fetched', 0)} posts)"
    )


@deep_search_bp.get("/jobs/<job_id>/posts")
def get_deep_job_posts(job_id: str):
    """Ambil HANYA posts dari job yang sudah completed (FINAL result)."""
    state = sc.get_job(job_id)
    if not state:
        return _fail(f"Job '{job_id}' tidak ditemukan", 404)
    if state.get("status") != sc.JobStatus.COMPLETED:
        return _fail(f"Job belum selesai (status: {state.get('status')})")
    posts = sc.get_job_posts(job_id)
    return _ok({"posts": posts or [], "total": len(posts or [])})


@deep_search_bp.get("/jobs/<job_id>/posts/partial")
def get_deep_job_posts_partial(job_id: str):
    """
    Ambil posts SAAT INI JUGA tanpa syarat status COMPLETED.
    Baca dari file posts yg di-flush berkala oleh worker.
    """
    state = sc.get_job(job_id)
    if not state:
        return _fail(f"Job '{job_id}' tidak ditemukan", 404)
    posts = sc.get_job_posts(job_id)
    return _ok({
        "posts": posts or [],
        "total": len(posts or []),
        "job_status": state.get("status"),
        "total_fetched": state.get("total_fetched", 0),
        "progress_log": state.get("progress_log", []),
    })


@deep_search_bp.post("/jobs/<job_id>/cancel")
def cancel_deep_job(job_id: str):
    """Cancel job yang sedang berjalan."""
    ok = sc.cancel_job(job_id)
    if ok:
        return _ok({"job_id": job_id, "cancelled": True}, "Job dibatalkan")
    return _fail(f"Job '{job_id}' tidak ditemukan atau sudah selesai")


@deep_search_bp.delete("/jobs/<job_id>")
def delete_deep_job(job_id: str):
    """Hapus job (cancel + hapus file state)."""
    ok = sc.delete_job(job_id)
    if ok:
        return _ok({"job_id": job_id, "deleted": True}, "Job dihapus")
    return _fail(f"Job '{job_id}' tidak ditemukan")