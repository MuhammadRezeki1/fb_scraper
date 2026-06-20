"""
facebook_api_server.py  —  PATCHED + HASHTAG & TRENDING + REAL-TIME SUBPROCESS
================================================================================
Fixes:
  1. run_post_scraper_subprocess: URL di-pass lewat env var, bukan f-string inject
  2. run_profile_scraper_subprocess: username + source_url via env var
  3. extract_username_from_url: filter 'share' dari path khusus FB
  4. scrape_single_profile: strip query params sebelum extract username
  5. _run_script_subprocess: real-time streaming output (Popen + threading)
  6. Endpoint:
     - POST /api/v1/monitor/keyword
     - POST /api/v1/monitor/hashtag
     - POST /api/v1/monitor/trending
  7. ✅ FIX Pylance: cast() untuk save_profile_to_tracking
  8. ✅ FIX NaN/Infinity: SafeJSONEncoder + _safe_json_response
"""
import os
import sys
import json
import time
import random
import re
import traceback
import threading
import subprocess
import tempfile
import shutil
import uuid
import math
from datetime import datetime, timedelta
from typing import Optional, List, cast
from functools import wraps
from fb_deep_endpoints import deep_search_bp

from dotenv import load_dotenv
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))

from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from colorama import Fore, init

app = Flask(__name__)
CORS(app)
init(autoreset=True)
# Register blueprint deep search
app.register_blueprint(deep_search_bp)


# ── CUSTOM JSON ENCODER (FIX NaN/Infinity) ──────────────────────────────

class SafeJSONEncoder(json.JSONEncoder):
    """Custom JSON encoder yang replace NaN/Infinity dengan 0."""
    def encode(self, o):
        # Sanitasi top-level
        o = self._sanitize(o)
        return super().encode(o)
    
    def _sanitize(self, obj):
        """Recursively replace NaN/Infinity with 0."""
        if isinstance(obj, dict):
            return {k: self._sanitize(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._sanitize(v) for v in obj]
        elif isinstance(obj, float):
            if math.isnan(obj) or math.isinf(obj):
                return 0
            return obj
        elif isinstance(obj, int):
            return obj
        return obj


def _safe_json_response(data: dict, status: int) -> Response:
    try:
        # ✅ FIX: Gunakan custom encoder untuk sanitasi NaN
        body = json.dumps(data, ensure_ascii=False, default=str, cls=SafeJSONEncoder)
    except Exception:
        body = '{"success":false,"message":"Internal serialization error","error":{}}'
    resp = Response(body, status=status, mimetype="application/json")
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return resp


@app.errorhandler(404)
def not_found(e):
    return _safe_json_response({"success": False, "message": f"Endpoint tidak ditemukan: {request.path}", "error": {}}, 404)


@app.errorhandler(405)
def method_not_allowed(e):
    return _safe_json_response({"success": False, "message": f"Method {request.method} tidak diizinkan", "error": {}}, 405)


@app.errorhandler(Exception)
def handle_all_exceptions(e):
    try:
        status = int(getattr(e, "code", 500))
    except Exception:
        status = 500
    return _safe_json_response({
        "success": False,
        "message": f"Server error: {str(e)}",
        "error":   {"type": type(e).__name__, "detail": str(e)},
    }, status)


# ── CONFIG ─────────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))

API_PORT   = int(os.getenv("FB_API_PORT", 5002))
API_HOST   = os.getenv("FB_API_HOST", "0.0.0.0")
DEBUG_MODE = os.getenv("DEBUG", "False").lower() == "true"

OUTPUT_POST_DIR    = os.path.join(_HERE, "output_facebook")
OUTPUT_PROFILE_DIR = os.path.join(_HERE, "output_fb_profiles")
TRACKING_FILE      = os.path.join(OUTPUT_PROFILE_DIR, "growth_tracking.json")
FB_CHROME_PROFILE  = os.path.join(_HERE, "fb_chrome_real_profile")

os.makedirs(OUTPUT_POST_DIR,    exist_ok=True)
os.makedirs(OUTPUT_PROFILE_DIR, exist_ok=True)
os.makedirs(FB_CHROME_PROFILE,  exist_ok=True)


# ── HELPERS ────────────────────────────────────────────────────────────────

def success_response(data: dict, message: str = "Success") -> dict:
    return {
        "success":   True,
        "message":   message,
        "timestamp": datetime.now().isoformat(),
        "data":      data,
    }


def ok(data: dict, message: str = "Success") -> Response:
    return _safe_json_response(success_response(data, message), 200)


def error_response(message: str, status_code: int = 400, details: Optional[dict] = None) -> Response:
    return _safe_json_response({
        "success":   False,
        "message":   str(message)[:2000],
        "timestamp": datetime.now().isoformat(),
        "error":     details or {},
    }, status_code)


def require_json_fields(*fields):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not request.is_json:
                return error_response("Content-Type must be application/json", 415)
            data = request.get_json(silent=True)
            if data is None:
                return error_response("Request body harus berupa JSON valid", 400)
            missing = [field for field in fields if field not in data or data[field] in (None, "")]
            if missing:
                return error_response(f"Missing required fields: {', '.join(missing)}", 400)
            return f(*args, **kwargs)
        return wrapper
    return decorator


def clean_fb_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def extract_username_from_url(url: str) -> Optional[str]:
    """
    Extract username/page dari URL Facebook.
    FIX: filter path khusus FB seperti 'share', 'reel', 'watch', dll.
    """
    url_clean = url.split("?")[0].rstrip("/")

    FB_RESERVED = {
        "login", "photo", "photos", "video", "videos", "events", "groups",
        "marketplace", "watch", "gaming", "pages", "share", "reel", "reels",
        "stories", "story", "live", "permalink", "sharer", "dialog",
        "hashtag", "explore", "bookmarks", "saved", "notifications",
        "messages", "settings", "help", "about",
    }

    patterns = [
        r'facebook\.com/pages/[^/?#]+/(\d+)',
        r'facebook\.com/profile\.php\?id=(\d+)',
        r'facebook\.com/groups/([a-zA-Z0-9._\-]+)',
        r'facebook\.com/([a-zA-Z0-9._\-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, url_clean, re.IGNORECASE)
        if match:
            username = match.group(1).strip()
            if username.lower() not in FB_RESERVED:
                return username
    return None


def save_json_output(data: dict, filename: str, output_dir: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    fp = os.path.join(output_dir, filename)
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str, cls=SafeJSONEncoder)
    return filename


def load_tracking_data() -> dict:
    if not os.path.exists(TRACKING_FILE):
        return {}
    try:
        with open(TRACKING_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_tracking_data(data: dict):
    os.makedirs(OUTPUT_PROFILE_DIR, exist_ok=True)
    with open(TRACKING_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, cls=SafeJSONEncoder)


# ═══════════════════════════════════════════════════════════════════════════
# AUTH / LOGIN STATE
# ═══════════════════════════════════════════════════════════════════════════

_login_state = {
    "is_running":        False,
    "browser_opened_at": None,
    "login_detected":    False,
    "user_id":           None,
    "last_error":        None,
}
_state_lock = threading.Lock()


def update_login_state(**kwargs):
    with _state_lock:
        _login_state.update(kwargs)


def get_login_state():
    with _state_lock:
        return dict(_login_state)


# ═══════════════════════════════════════════════════════════════════════════
# ASYNC JOB REGISTRY
# ═══════════════════════════════════════════════════════════════════════════

_jobs = {}
_jobs_lock = threading.Lock()
_JOB_RETENTION_SECONDS = 3600


def _prune_jobs():
    now = time.time()
    with _jobs_lock:
        stale = [
            jid for jid, j in _jobs.items()
            if j.get("_finished_ts") and (now - j["_finished_ts"]) > _JOB_RETENTION_SECONDS
        ]
        for jid in stale:
            _jobs.pop(jid, None)


def _create_job(job_type: str, label: str = "") -> str:
    job_id = uuid.uuid4().hex[:16]
    with _jobs_lock:
        _jobs[job_id] = {
            "job_id":       job_id,
            "type":         job_type,
            "label":        label,
            "status":       "running",
            "result":       None,
            "error":        None,
            "started_at":   datetime.now().isoformat(),
            "finished_at":  None,
            "_finished_ts": None,
        }
    return job_id


def _finish_job(job_id: str, result=None, error=None):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job["status"]       = "error" if error else "done"
            job["result"]       = result
            job["error"]        = error
            job["finished_at"]  = datetime.now().isoformat()
            job["_finished_ts"] = time.time()
    _prune_jobs()


def _get_job(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return None
        return {k: v for k, v in job.items() if not k.startswith("_")}


def _start_job(job_type: str, label: str, fn) -> Response:
    """Buat job, jalankan fn() di thread terpisah, balas job_id langsung."""
    job_id = _create_job(job_type, label)

    def _runner():
        try:
            result = fn()
            _finish_job(job_id, result=result)
        except Exception as e:
            traceback.print_exc()
            _finish_job(job_id, error=str(e)[:1000])

    threading.Thread(target=_runner, daemon=True).start()
    return ok(
        {"job_id": job_id, "status": "running", "type": job_type},
        "Scrape dimulai — polling status via GET /api/v1/scrape/job/<job_id>",
    )


@app.route("/api/v1/scrape/job/<job_id>", methods=["GET"])
def get_scrape_job(job_id):
    job = _get_job(job_id)
    if not job:
        return error_response("Job tidak ditemukan atau sudah kedaluwarsa", 404)
    return _safe_json_response(success_response(job, f"Job {job['status']}"), 200)


def run_login_browser_async(timeout_minutes: int = 5, headless: bool = False):
    def _thread_target():
        import asyncio

        async def _login_worker():
            from playwright.async_api import async_playwright

            print(Fore.CYAN + "\n🌐 [Login Worker] Membuka browser Chrome untuk Facebook...")
            update_login_state(
                is_running=True,
                browser_opened_at=datetime.now().isoformat(),
                login_detected=False,
                last_error=None,
                user_id=None,
            )

            try:
                async with async_playwright() as p:
                    context = await p.chromium.launch_persistent_context(
                        FB_CHROME_PROFILE,
                        channel="chrome",
                        headless=headless,
                        args=[
                            "--start-maximized",
                            "--disable-notifications",
                            "--disable-blink-features=AutomationControlled",
                            "--lang=id-ID",
                        ],
                        viewport=None,
                        locale="id-ID",
                        timezone_id="Asia/Jakarta",
                        bypass_csp=True,
                    )

                    page = context.pages[0] if context.pages else await context.new_page()

                    try:
                        from fb_cookie_injector import has_valid_session, inject_cookies_async
                        if has_valid_session():
                            n = await inject_cookies_async(context)
                            print(Fore.GREEN + f"   🍪 {n} cookies Facebook diinject dari session")
                    except Exception as ce:
                        print(Fore.YELLOW + f"   ⚠️  Cookie inject skip: {ce}")

                    await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(4)

                    cookies     = await context.cookies("https://www.facebook.com")
                    cookie_dict = {c.get("name", ""): c.get("value", "") for c in cookies}

                    if "c_user" in cookie_dict and "xs" in cookie_dict:
                        print(Fore.GREEN + "\n✅ [Login Worker] Sudah login sebelumnya!")
                        await _save_cookies_from_context(context, cookies)
                        update_login_state(login_detected=True, user_id=cookie_dict.get("c_user"))
                        await asyncio.sleep(3)
                        await context.close()
                        return

                    print(Fore.YELLOW + "\n⚠️  [Login Worker] Menunggu login manual Facebook...")

                    max_wait  = timeout_minutes * 12
                    logged_in = False

                    for i in range(max_wait):
                        await asyncio.sleep(5)
                        cookies     = await context.cookies("https://www.facebook.com")
                        cookie_dict = {c.get("name", ""): c.get("value", "") for c in cookies}
                        current_url = page.url

                        print(f"   [{i+1}/{max_wait}] {current_url[:60]}", end="\r")

                        if "c_user" in cookie_dict and "xs" in cookie_dict:
                            logged_in = True
                            user_id   = cookie_dict.get("c_user", "")
                            print(Fore.GREEN + f"\n\n✅ [Login Worker] Login berhasil! User ID: {user_id}")
                            update_login_state(user_id=user_id)
                            break

                    if not logged_in:
                        print(Fore.RED + "\n\n❌ [Login Worker] Timeout")
                        update_login_state(last_error="Timeout: user tidak login dalam waktu yang ditentukan")
                        await context.close()
                        return

                    print(Fore.YELLOW + "\n⏳ [Login Worker] Menyimpan session (8 detik)...")
                    await asyncio.sleep(8)

                    cookies = await context.cookies("https://www.facebook.com")
                    await _save_cookies_from_context(context, cookies)
                    update_login_state(login_detected=True)
                    print(Fore.GREEN + "✅ [Login Worker] Session tersimpan!")
                    await context.close()

            except Exception as e:
                print(Fore.RED + f"\n❌ [Login Worker] Error: {e}")
                update_login_state(last_error=str(e))
                traceback.print_exc()
            finally:
                update_login_state(is_running=False)

        async def _save_cookies_from_context(context, cookies):
            try:
                from fb_cookie_injector import save_session
                fb_cookies = [
                    {
                        "name":           c["name"],
                        "value":          c["value"],
                        "domain":         c.get("domain", ".facebook.com"),
                        "path":           c.get("path", "/"),
                        "httpOnly":       c.get("httpOnly", False),
                        "secure":         c.get("secure", True),
                        "sameSite":       c.get("sameSite", "Lax"),
                        "expirationDate": c.get("expires", -1),
                    }
                    for c in cookies
                    if "facebook.com" in c.get("domain", "")
                ]
                save_session(fb_cookies, note="auto_saved_from_api_login")
                print(Fore.GREEN + f"   💾 {len(fb_cookies)} cookies tersimpan ke session/fb_session.json")
            except Exception as se:
                print(Fore.YELLOW + f"   ⚠️  Gagal simpan session: {se}")

        asyncio.run(_login_worker())

    thread = threading.Thread(target=_thread_target, daemon=True)
    thread.start()
    return thread


# ═══════════════════════════════════════════════════════════════════════════
# SUBPROCESS HELPERS — FIXED with REAL-TIME STREAMING
# ═══════════════════════════════════════════════════════════════════════════

_POST_SCRAPER_SCRIPT = """\
import sys, os, json
sys.path.insert(0, os.environ["FB_SCRAPER_PATH"])

url             = os.environ["FB_SCRAPE_URL"]
max_comments    = int(os.environ.get("FB_MAX_COMMENTS", "200"))
include_replies = os.environ.get("FB_INCLUDE_REPLIES", "1") == "1"
scrape_reactors = os.environ.get("FB_SCRAPE_REACTORS", "0") == "1"
max_reactors    = int(os.environ.get("FB_MAX_REACTORS", "200"))

from fb_scraper_v21 import FacebookScraperV21
with FacebookScraperV21() as scraper:
    result = scraper.scrape_post(
        url,
        max_comments,
        include_replies=include_replies,
        scrape_reactors=scrape_reactors,
        max_reactors=max_reactors,
    )
    print(json.dumps(result, ensure_ascii=False, default=str))
"""

_PROFILE_SCRAPER_SCRIPT = """\
import sys, os, json
sys.path.insert(0, os.environ["FB_SCRAPER_PATH"])

username   = os.environ["FB_SCRAPE_USERNAME"]
source_url = os.environ.get("FB_SCRAPE_SOURCE_URL") or None

from fb_profile_scraper_v21 import FacebookProfileScraperV21
with FacebookProfileScraperV21() as scraper:
    result = scraper.scrape_profile(username)
    if source_url:
        if result.get("data"):
            result["data"]["source_url"] = source_url
        result["source_url"] = source_url
    print(json.dumps(result, ensure_ascii=False, default=str))
"""


def _run_script_subprocess(script: str, env: dict, timeout: int = 300) -> dict:
    """
    Helper: tulis script ke tempfile, jalankan, parse JSON output.
    ✅ FIX: Stream stdout/stderr ke console secara real-time (Popen + threading).
    """
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", delete=False, encoding="utf-8"
    ) as f:
        f.write(script)
        script_path = f.name

    try:
        process = subprocess.Popen(
            [sys.executable, "-u", script_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=_HERE,
            encoding="utf-8",
            errors="replace",
            env=env,
            bufsize=1,
        )

        stdout_lines: List[str] = []
        stderr_lines: List[str] = []

        def read_stdout():
            if process.stdout is None:
                return
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    stdout_lines.append(line)
                    clean = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
                    if not clean.startswith("{"):
                        print(line)
            except Exception:
                pass

        def read_stderr():
            if process.stderr is None:
                return
            try:
                for line in process.stderr:
                    line = line.rstrip()
                    stderr_lines.append(line)
                    if any(k in line for k in ("Error", "error", "Traceback", "Exception", "exit", "Warning")):
                        print(Fore.YELLOW + f"   ⚠️  {line}")
            except Exception:
                pass

        t_out = threading.Thread(target=read_stdout, daemon=True)
        t_err = threading.Thread(target=read_stderr, daemon=True)
        t_out.start()
        t_err.start()

        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            t_out.join(timeout=2)
            t_err.join(timeout=2)
            raise Exception(f"Subprocess timeout after {timeout}s")

        t_out.join(timeout=5)
        t_err.join(timeout=5)

        stdout = "\n".join(stdout_lines)
        stderr = "\n".join(stderr_lines)

        if process.returncode != 0:
            stderr_preview = stderr[-3000:] if stderr else "(no stderr)"
            raise Exception(f"Scraper subprocess exited {process.returncode}:\n{stderr_preview}")

        for line in reversed(stdout_lines):
            line = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        stdout_preview = stdout[-1000:] if stdout else "(empty)"
        raise Exception(
            f"No valid JSON output from scraper subprocess.\n"
            f"stdout (last 1000 chars):\n{stdout_preview}"
        )

    finally:
        try:
            os.unlink(script_path)
        except Exception:
            pass


def run_post_scraper_subprocess(url: str, max_comments: int, include_replies: bool = True,
                                scrape_reactors: bool = False, max_reactors: int = 200) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"]   = "utf-8"
    env["PYTHONUTF8"]         = "1"
    env["FB_SCRAPER_PATH"]    = _HERE
    env["FB_SCRAPE_URL"]      = url
    env["FB_MAX_COMMENTS"]    = str(max_comments)
    env["FB_INCLUDE_REPLIES"] = "1" if include_replies else "0"
    env["FB_SCRAPE_REACTORS"] = "1" if scrape_reactors else "0"
    env["FB_MAX_REACTORS"]    = str(max_reactors)

    timeout = 3600 if max_comments >= 5000 else 900
    return _run_script_subprocess(_POST_SCRAPER_SCRIPT, env=env, timeout=timeout)


def run_profile_scraper_subprocess(username: str, source_url: Optional[str] = None) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"]      = "utf-8"
    env["PYTHONUTF8"]            = "1"
    env["FB_SCRAPER_PATH"]       = _HERE
    env["FB_SCRAPE_USERNAME"]    = username
    if source_url:
        env["FB_SCRAPE_SOURCE_URL"] = source_url
    elif "FB_SCRAPE_SOURCE_URL" in env:
        del env["FB_SCRAPE_SOURCE_URL"]

    return _run_script_subprocess(_PROFILE_SCRAPER_SCRIPT, env=env, timeout=300)


# ═══════════════════════════════════════════════════════════════════════════
# ✅ FIX PYLANCE: save_profile_to_tracking dengan cast() eksplisit
# ═══════════════════════════════════════════════════════════════════════════
def save_profile_to_tracking(profile_result: dict) -> None:
    try:
        data     = profile_result.get("data", {}) or {}
        username = data.get("username") or profile_result.get("username", "")
        if not username:
            return

        tracking   = load_tracking_data()
        scraped_at = data.get("scraped_at", datetime.now().isoformat())

        if username not in tracking:
            tracking[username] = {
                "username":      username,
                "first_tracked": scraped_at,
                "history":       [],
                "platform":      "facebook",
            }

        snapshot = {
            "scraped_at": scraped_at,
            "followers":  data.get("followers", 0),
            "following":  data.get("following", 0),
            "likes":      data.get("likes", 0),
            "posts":      data.get("posts", 0),
            "is_page":    data.get("is_page", False),
        }

        today     = scraped_at[:10]
        user_data = tracking[username]

        # ✅ FIX PYLANCE: cast() untuk meyakinkan Pylance bahwa ini List[dict]
        history_raw = user_data.get("history")
        if not isinstance(history_raw, list):
            history_raw = []
        history: List[dict] = cast(List[dict], history_raw)

        # ✅ Sekarang Pylance 100% yakin history adalah List[dict]
        updated = False
        for h in history:
            if h.get("scraped_at", "")[:10] == today:
                h.update(snapshot)
                updated = True
                break
        if not updated:
            history.append(snapshot)

        # ✅ Simpan kembali ke user_data
        user_data["history"] = history
        user_data["last_tracked"] = scraped_at

        save_tracking_data(tracking)
        print(Fore.GREEN + f"   💾 Tracking updated: @{username}")
    except Exception as e:
        print(Fore.YELLOW + f"   ⚠️  Tracking save warning: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — AUTH
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/auth/login", methods=["POST"])
def trigger_login():
    data            = request.get_json() or {}
    timeout_minutes = data.get("timeout_minutes", 5)
    headless        = data.get("headless", False)

    state = get_login_state()
    if state["is_running"]:
        return error_response(
            "Browser login sedang berjalan. Cek status dengan GET /api/v1/auth/status",
            409,
            {"browser_opened_at": state["browser_opened_at"]},
        )

    run_login_browser_async(timeout_minutes=timeout_minutes, headless=headless)
    time.sleep(2)

    return jsonify(success_response({
        "browser_started":    True,
        "headless":           headless,
        "timeout_minutes":    timeout_minutes,
        "profile_path":       FB_CHROME_PROFILE,
        "session_file":       "session/fb_session.json",
        "alternative":        "Gunakan fb_session_manager.py untuk import cookies dari Cookie-Editor",
        "instructions": [
            "Browser Chrome akan terbuka",
            "Login manual ke Facebook",
            "Selesaikan verifikasi jika diminta",
            "Tunggu halaman beranda muncul",
            "Cek status dengan GET /api/v1/auth/status",
        ],
    }, f"Browser login dibuka. Timeout: {timeout_minutes} menit"))


@app.route("/api/v1/auth/status", methods=["GET"])
def check_login_status():
    state = get_login_state()

    try:
        from fb_cookie_injector import has_valid_session, get_session_info
        session_valid = has_valid_session()
        session_info  = get_session_info()
    except Exception:
        session_valid = False
        session_info  = {}

    profile_valid = os.path.exists(FB_CHROME_PROFILE) and bool(os.listdir(FB_CHROME_PROFILE))

    response_data = {
        "is_running":         state["is_running"],
        "login_detected":     state["login_detected"],
        "user_id":            state["user_id"],
        "browser_opened_at":  state["browser_opened_at"],
        "last_error":         state["last_error"],
        "session_file_valid": session_valid,
        "session_info":       session_info,
        "profile_dir_exists": profile_valid,
        "profile_path":       FB_CHROME_PROFILE,
        "is_logged_in":       session_valid or (state["login_detected"] and profile_valid),
    }

    if session_valid:
        msg = "Session valid — siap scraping"
    elif state["login_detected"]:
        msg = "Login via browser terdeteksi"
    elif state["last_error"]:
        msg = f"Error: {state['last_error']}"
    else:
        msg = "Belum login"

    return jsonify(success_response(response_data, msg))


@app.route("/api/v1/auth/session-info", methods=["GET"])
def get_session_detail():
    try:
        from fb_cookie_injector import get_session_info
        info = get_session_info()
        return jsonify(success_response(info, "Session info retrieved"))
    except Exception as e:
        return error_response(f"Error: {str(e)}", 500)


@app.route("/api/v1/auth/import-cookies", methods=["POST"])
def import_cookies():
    data = request.get_json() or {}
    raw_cookies = data.get("cookies")
    username    = data.get("username", "")

    if not raw_cookies:
        return error_response("Field 'cookies' wajib diisi (array Cookie-Editor JSON)", 400)
    if not isinstance(raw_cookies, list):
        return error_response("Field 'cookies' harus berupa array JSON", 400)
    if len(raw_cookies) == 0:
        return error_response("Array cookies tidak boleh kosong", 400)

    try:
        from fb_cookie_injector import save_session, get_session_info, has_valid_session
        save_session(raw_cookies, username=username, note="imported_from_dashboard")
        info  = get_session_info()
        valid = has_valid_session()

        if valid:
            user_id = info.get("user_id", "")
            update_login_state(login_detected=True, user_id=user_id)
            return jsonify(success_response({
                "saved":             True,
                "valid":             True,
                "total_cookies":     info.get("total_cookies", len(raw_cookies)),
                "user_id":           user_id,
                "cookie_names":      info.get("cookie_names", []),
                "has_preferred":     info.get("has_preferred", False),
                "preferred_missing": info.get("preferred_missing", []),
            }, f"Cookies berhasil diimport! User ID: {user_id}"))
        else:
            return jsonify(success_response({
                "saved":         True,
                "valid":         False,
                "total_cookies": len(raw_cookies),
                "warning":       "Cookies disimpan tapi session belum valid (c_user atau xs tidak ditemukan).",
                "info":          info,
            }, "Cookies disimpan tapi belum valid"))

    except Exception as e:
        return error_response(f"Gagal import cookies: {str(e)}", 500)


@app.route("/api/v1/auth/logout", methods=["POST"])
def logout():
    data       = request.get_json() or {}
    hard_reset = data.get("hard_reset", False)

    state = get_login_state()
    if state["is_running"]:
        return error_response("Browser sedang berjalan. Tidak bisa logout saat ini.", 409)

    try:
        from fb_cookie_injector import delete_session, SESSION_FILE
        deleted_session = delete_session()

        if hard_reset:
            if os.path.exists(FB_CHROME_PROFILE):
                shutil.rmtree(FB_CHROME_PROFILE)
                os.makedirs(FB_CHROME_PROFILE, exist_ok=True)
            update_login_state(login_detected=False, user_id=None, last_error=None, browser_opened_at=None)
            return jsonify(success_response({
                "session_deleted": deleted_session,
                "profile_reset":   True,
                "profile_path":    FB_CHROME_PROFILE,
            }, "Hard reset berhasil. Login baru diperlukan."))
        else:
            update_login_state(login_detected=False, user_id=None)
            return jsonify(success_response({
                "session_deleted": deleted_session,
                "session_file":    SESSION_FILE,
            }, "Logout berhasil. Session dihapus."))

    except Exception as e:
        return error_response(f"Logout failed: {str(e)}", 500)


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — SCRAPE POST (KOMENTAR)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/scrape/post", methods=["POST"])
@require_json_fields("url")
def scrape_single_post():
    data            = request.get_json(silent=True) or {}
    url             = clean_fb_url(data.get("url", ""))
    max_comments    = int(data.get("max_comments", 200))
    include_replies = bool(data.get("include_replies", True))
    scrape_reactors = bool(data.get("scrape_reactors", False))
    max_reactors    = max(0, min(int(data.get("max_reactors", 200) or 200), 5000))
    if data.get("all_comments") or max_comments <= 0:
        max_comments = 1_000_000

    def work():
        print(Fore.CYAN + f"\n📝 Scraping Facebook post: {url[:70]}")
        print(Fore.CYAN + f"   Max comments: {max_comments} | replies: {include_replies} | reactors: {scrape_reactors} ({max_reactors})")
        print(Fore.YELLOW + "   ⏳ Estimasi ~60-300 detik...")

        t_start   = time.time()
        result    = run_post_scraper_subprocess(url, max_comments, include_replies, scrape_reactors, max_reactors)
        t_elapsed = time.time() - t_start

        result["_meta"] = {
            "elapsed_seconds":     round(t_elapsed, 2),
            "requested_max":       max_comments,
            "scrape_reactors":     scrape_reactors,
            "max_reactors":        max_reactors,
            "url_cleaned":         url,
            "comments_per_second": round(
                result.get("comments_count", 0) / t_elapsed, 2
            ) if t_elapsed > 0 else 0,
        }

        filename = f"api_post_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(result, filename, OUTPUT_POST_DIR)
        result["_meta"]["saved_file"] = filename
        return result

    return _start_job("post", url, work)


@app.route("/api/v1/scrape/posts/batch", methods=["POST"])
@require_json_fields("urls")
def scrape_batch_posts():
    data          = request.get_json()
    urls          = [clean_fb_url(u) for u in data["urls"]]
    max_comments  = data.get("max_comments", 200)
    delay_between = data.get("delay_between", 30)

    if not isinstance(urls, list) or len(urls) == 0:
        return error_response("'urls' harus berupa array non-kosong", 400)

    def work():
        results = []
        t_total = time.time()

        for i, url in enumerate(urls):
            print(Fore.CYAN + f"\n[{i+1}/{len(urls)}] {url[:70]}")
            try:
                r = run_post_scraper_subprocess(url, max_comments)
                results.append({"url": url, "success": True, "data": r})
            except Exception as e:
                results.append({"url": url, "success": False, "error": str(e)})

            if i < len(urls) - 1:
                delay = delay_between + random.randint(5, 15)
                print(Fore.YELLOW + f"   ⏳ Jeda {delay}s...")
                time.sleep(delay)

        summary = {
            "total":           len(urls),
            "success":         sum(1 for r in results if r["success"]),
            "failed":          sum(1 for r in results if not r["success"]),
            "elapsed_seconds": round(time.time() - t_total, 2),
            "results":         results,
        }

        filename = f"api_batch_posts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(summary, filename, OUTPUT_POST_DIR)
        summary["saved_file"] = filename
        return summary

    return _start_job("post", f"{len(urls)} posts (batch)", work)


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — SCRAPE PROFILE
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/scrape/profile", methods=["POST"])
@require_json_fields("username")
def scrape_single_profile():
    data          = request.get_json()
    raw_input     = data["username"].strip().lstrip("@")
    save_tracking = data.get("save_tracking", True)

    if raw_input.startswith("http") or "facebook.com" in raw_input:
        clean_url  = raw_input.split("?")[0].split("#")[0].rstrip("/")
        extracted  = extract_username_from_url(clean_url)
        if extracted:
            print(Fore.CYAN + f"   ✅ URL → username: {extracted}")
            return _do_scrape_profile(extracted, save_tracking, source_url=raw_input)
        print(Fore.YELLOW + f"   🔀 URL ambigu, biar scraper resolve: {raw_input[:70]}")
        return _do_scrape_profile(raw_input, save_tracking, source_url=raw_input)

    return _do_scrape_profile(raw_input, save_tracking)


@app.route("/api/v1/scrape/profiles/batch", methods=["POST"])
@require_json_fields("usernames")
def scrape_batch_profiles():
    data          = request.get_json()
    usernames     = data["usernames"]
    delay_between = data.get("delay_between", 30)
    save_tracking = data.get("save_tracking", True)

    if not isinstance(usernames, list) or len(usernames) == 0:
        return error_response("'usernames' harus berupa array non-kosong", 400)

    def work():
        results = []
        t_total = time.time()

        for i, username in enumerate(usernames):
            uname = username.strip().lstrip("@")
            print(Fore.CYAN + f"\n[{i+1}/{len(usernames)}] @{uname}")
            try:
                r = run_profile_scraper_subprocess(uname)
                if save_tracking and r.get("success"):
                    save_profile_to_tracking(r)
                results.append({"username": uname, "success": True, "data": r})
            except Exception as e:
                results.append({"username": uname, "success": False, "error": str(e)})

            if i < len(usernames) - 1:
                delay = delay_between + random.randint(5, 10)
                print(Fore.YELLOW + f"   ⏳ Jeda {delay}s...")
                time.sleep(delay)

        summary = {
            "total":           len(usernames),
            "success":         sum(1 for r in results if r["success"]),
            "failed":          sum(1 for r in results if not r["success"]),
            "elapsed_seconds": round(time.time() - t_total, 2),
            "results":         results,
        }

        filename = f"api_batch_profiles_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(summary, filename, OUTPUT_PROFILE_DIR)
        summary["saved_file"] = filename
        return summary

    return _start_job("profile", f"{len(usernames)} profiles (batch)", work)


def _do_scrape_profile(username: str, save_tracking: bool, source_url: Optional[str] = None):
    def work():
        print(Fore.CYAN + f"\n🌐 [Job] Scraping Facebook profile: @{username}")
        print(Fore.YELLOW + "   ⏳ Estimasi ~30-60 detik...")
        t_start   = time.time()
        result    = run_profile_scraper_subprocess(username, source_url)
        t_elapsed = time.time() - t_start

        result["_meta"] = {
            "elapsed_seconds": round(t_elapsed, 2),
            "mode":            "subprocess_fresh",
            "scraped_at":      datetime.now().isoformat(),
        }
        if source_url:
            result["_meta"]["source_url"] = source_url

        resolved_uname = (result.get("data") or {}).get("username") or username
        safe_uname     = re.sub(r"[^A-Za-z0-9_.-]", "_", str(resolved_uname))[:40] or "profile"
        filename = f"api_profile_{safe_uname}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(result, filename, OUTPUT_PROFILE_DIR)
        result["_meta"]["saved_file"] = filename

        if save_tracking and result.get("success"):
            save_profile_to_tracking(result)
            result["_tracking_saved"] = True

        return result

    return _start_job("profile", username, work)


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — LAST RESULT
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/scrape/last-result", methods=["GET"])
def get_last_scrape_result():
    result_type = request.args.get("type", "profile")
    try:
        if result_type == "post":
            files = sorted(
                [f for f in os.listdir(OUTPUT_POST_DIR) if f.startswith("api_") and f.endswith(".json")],
                reverse=True,
            )
        else:
            files = sorted(
                [f for f in os.listdir(OUTPUT_PROFILE_DIR) if f.startswith("api_profile_") and f.endswith(".json")],
                reverse=True,
            )
        if not files:
            return error_response("Belum ada hasil scraping tersimpan", 404)
        path = os.path.join(OUTPUT_POST_DIR if result_type == "post" else OUTPUT_PROFILE_DIR, files[0])
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return jsonify(success_response(data, f"Last {result_type} result: {files[0]}"))
    except Exception as e:
        return error_response(f"Gagal baca hasil terakhir: {str(e)}", 500)


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — ANALYTICS / GROWTH
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/profiles", methods=["GET"])
def list_tracked_profiles():
    tracking = load_tracking_data()
    users    = []
    for username, data in tracking.items():
        history = data.get("history", [])
        latest  = history[-1] if history else {}
        users.append({
            "username":          username,
            "data_points":       len(history),
            "first_tracked":     data.get("first_tracked", ""),
            "last_tracked":      data.get("last_tracked", ""),
            "is_page":           latest.get("is_page", False),
            "current_followers": latest.get("followers", 0),
            "current_likes":     latest.get("likes", 0),
            "current_posts":     latest.get("posts", 0),
        })
    users.sort(key=lambda x: x["last_tracked"], reverse=True)
    return jsonify(success_response({"count": len(users), "users": users}))


@app.route("/api/v1/profiles/<username>", methods=["GET"])
def get_profile(username):
    username = username.strip().lstrip("@")
    tracking = load_tracking_data()

    if username not in tracking:
        return error_response(f"Tidak ada data untuk @{username}", 404)

    data    = tracking[username]
    history = data.get("history", [])
    latest  = history[-1] if history else {}

    return jsonify(success_response({
        "username":        username,
        "data_points":     len(history),
        "first_tracked":   data.get("first_tracked", ""),
        "last_tracked":    data.get("last_tracked", ""),
        "latest_snapshot": latest,
    }))


@app.route("/api/v1/profiles/<username>/history", methods=["GET"])
def get_profile_history(username):
    username = username.strip().lstrip("@")
    limit    = request.args.get("limit", 50, type=int)
    tracking = load_tracking_data()

    if username not in tracking:
        return error_response(f"Tidak ada data untuk @{username}", 404)

    history        = tracking[username].get("history", [])
    history_sorted = sorted(history, key=lambda x: x.get("scraped_at", ""), reverse=True)
    history_limited = history_sorted[:limit]

    return jsonify(success_response({
        "username":     username,
        "total_points": len(history),
        "returned":     len(history_limited),
        "snapshots":    history_limited,
    }))


@app.route("/api/v1/profiles/<username>/growth", methods=["GET"])
def get_growth_analysis(username):
    username = username.strip().lstrip("@")
    days     = request.args.get("days", 30, type=int)
    tracking = load_tracking_data()

    if username not in tracking:
        return error_response(f"Tidak ada data untuk @{username}", 404)

    history = tracking[username].get("history", [])
    if len(history) < 2:
        return error_response(
            f"Hanya ada {len(history)} data point untuk @{username}. Perlu minimal 2.",
            400,
        )

    cutoff   = datetime.now() - timedelta(days=days)
    filtered = [
        h for h in history
        if datetime.fromisoformat(h["scraped_at"]) >= cutoff
    ]
    if len(filtered) < 2:
        filtered = history

    filtered.sort(key=lambda x: x["scraped_at"])
    first    = filtered[0]
    last     = filtered[-1]
    first_dt = datetime.fromisoformat(first["scraped_at"])
    last_dt  = datetime.fromisoformat(last["scraped_at"])
    days_span = (last_dt - first_dt).days or 1

    def calc(field):
        start  = first.get(field, 0)
        end    = last.get(field, 0)
        growth = end - start
        pct    = round((growth / start * 100), 2) if start > 0 else 0.0
        daily  = round(growth / days_span, 2)
        return {"start": start, "end": end, "growth": growth, "growth_pct": pct, "avg_per_day": daily}

    analysis = {
        "username":    username,
        "analyzed_at": datetime.now().isoformat(),
        "platform":    "facebook",
        "period": {
            "start_date":  first_dt.isoformat(),
            "end_date":    last_dt.isoformat(),
            "days":        days_span,
            "data_points": len(filtered),
        },
        "followers": calc("followers"),
        "following": calc("following"),
        "likes":     calc("likes"),
        "posts":     calc("posts"),
        "history":   filtered,
    }

    return jsonify(success_response(analysis, f"Growth analysis @{username} ({days_span} days)"))


@app.route("/api/v1/profiles/<username>/track", methods=["POST"])
def manual_track_profile(username):
    username   = username.strip().lstrip("@")
    data       = request.get_json() or {}
    followers  = data.get("followers", 0)
    following  = data.get("following", 0)
    likes      = data.get("likes", 0)
    posts      = data.get("posts", 0)
    is_page    = data.get("is_page", False)
    scraped_at = data.get("scraped_at", datetime.now().isoformat())

    if not followers and not likes:
        return error_response("Minimal 'followers' atau 'likes' harus diisi", 400)

    tracking = load_tracking_data()
    if username not in tracking:
        tracking[username] = {
            "username":      username,
            "first_tracked": scraped_at,
            "history":       [],
            "platform":      "facebook",
        }

    snapshot = {
        "scraped_at": scraped_at,
        "followers":  followers,
        "following":  following,
        "likes":      likes,
        "posts":      posts,
        "is_page":    is_page,
    }

    tracking[username]["history"].append(snapshot)
    tracking[username]["last_tracked"] = scraped_at
    save_tracking_data(tracking)

    return jsonify(success_response({
        "username":          username,
        "snapshot_added":    snapshot,
        "total_data_points": len(tracking[username]["history"]),
    }, f"Manual snapshot added for @{username}"))


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — HEALTH & DASHBOARD
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/v1/health", methods=["GET"])
def health_check():
    login_state = get_login_state()

    try:
        from fb_cookie_injector import has_valid_session, get_session_info
        session_valid = has_valid_session()
        session_info  = get_session_info()
    except Exception:
        session_valid = False
        session_info  = {}

    tracking = load_tracking_data()

    total_posts_scraped = 0
    try:
        files = os.listdir(OUTPUT_POST_DIR)
        total_posts_scraped = sum(1 for f in files if f.endswith(".json"))
    except Exception:
        pass

    status = {
        "api":                   "running",
        "platform":              "facebook",
        "session_valid":         session_valid,
        "session_info":          session_info,
        "chrome_profile_path":   FB_CHROME_PROFILE,
        "chrome_profile_exists": os.path.exists(FB_CHROME_PROFILE) and bool(os.listdir(FB_CHROME_PROFILE)),
        "output_post_dir":       os.path.abspath(OUTPUT_POST_DIR),
        "output_profile_dir":    os.path.abspath(OUTPUT_PROFILE_DIR),
        "post_scraper_mode":     "subprocess (fresh per request)",
        "profile_scraper_mode":  "subprocess (fresh per request)",
        "tracked_profiles":      len(tracking),
        "post_files_saved":      total_posts_scraped,
        "login_state": {
            "is_running":     login_state["is_running"],
            "login_detected": login_state["login_detected"],
            "user_id":        login_state["user_id"],
        },
        "timestamp": datetime.now().isoformat(),
    }
    return jsonify(success_response(status, "Facebook API is healthy"))


@app.route("/api/v1/dashboard", methods=["GET"])
def dashboard_data():
    tracking    = load_tracking_data()
    login_state = get_login_state()

    try:
        from fb_cookie_injector import has_valid_session
        session_valid = has_valid_session()
    except Exception:
        session_valid = False

    is_logged_in = session_valid or login_state.get("login_detected", False)

    def _count_json(directory, exclude=None):
        try:
            return sum(
                1 for f in os.listdir(directory)
                if f.endswith(".json") and f != (exclude or "")
            )
        except Exception:
            return 0

    total_post_files    = _count_json(OUTPUT_POST_DIR)
    total_profile_files = _count_json(OUTPUT_PROFILE_DIR, exclude="growth_tracking.json")

    recent_posts = []
    try:
        files = sorted(
            [f for f in os.listdir(OUTPUT_POST_DIR) if f.endswith(".json")],
            key=lambda f: os.path.getmtime(os.path.join(OUTPUT_POST_DIR, f)),
            reverse=True,
        )[:5]
        for fname in files:
            fpath = os.path.join(OUTPUT_POST_DIR, fname)
            entry = {
                "filename": fname,
                "size_kb":  round(os.path.getsize(fpath) / 1024, 1),
                "modified": datetime.fromtimestamp(os.path.getmtime(fpath)).isoformat(),
            }
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                entry.update({
                    "scraped_at":        data.get("scraped_at", ""),
                    "post_type":         data.get("post_type", "post"),
                    "comments_count":    data.get("comments_count", 0),
                    "total_likes":       data.get("total_likes", 0),
                    "total_shares":      data.get("total_shares", 0),
                    "url":               data.get("url", ""),
                    "caption":           (data.get("caption") or "")[:100],
                    "sentiment_summary": {
                        k: v for k, v in (data.get("sentiment_summary") or {}).items()
                        if k in ("total_comments", "positive_percentage", "negative_percentage",
                                 "neutral_percentage", "hate_percentage", "toxic_percentage")
                    },
                })
            except Exception:
                pass
            recent_posts.append(entry)
    except Exception:
        pass

    recent_profiles = []
    try:
        files = sorted(
            [f for f in os.listdir(OUTPUT_PROFILE_DIR)
             if f.endswith(".json") and f != "growth_tracking.json"],
            key=lambda f: os.path.getmtime(os.path.join(OUTPUT_PROFILE_DIR, f)),
            reverse=True,
        )[:5]
        for fname in files:
            fpath = os.path.join(OUTPUT_PROFILE_DIR, fname)
            entry = {"filename": fname}
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                pdata = data.get("data") or {}
                entry.update({
                    "username":    pdata.get("username", ""),
                    "name":        pdata.get("name", ""),
                    "followers":   pdata.get("followers", 0),
                    "likes":       pdata.get("likes", 0),
                    "is_page":     pdata.get("is_page", False),
                    "is_verified": pdata.get("is_verified", False),
                    "scraped_at":  pdata.get("scraped_at", ""),
                })
            except Exception:
                pass
            recent_profiles.append(entry)
    except Exception:
        pass

    latest_sentiment = None
    try:
        files = sorted(
            [f for f in os.listdir(OUTPUT_POST_DIR) if f.endswith(".json")],
            key=lambda f: os.path.getmtime(os.path.join(OUTPUT_POST_DIR, f)),
            reverse=True,
        )
        if files:
            with open(os.path.join(OUTPUT_POST_DIR, files[0]), "r", encoding="utf-8") as f:
                lp = json.load(f)
            latest_sentiment = lp.get("sentiment_summary")
    except Exception:
        pass

    top_profiles = []
    for uname, udata in tracking.items():
        history = udata.get("history", [])
        if history:
            latest = history[-1]
            top_profiles.append({
                "username":  uname,
                "followers": latest.get("followers", 0),
                "likes":     latest.get("likes", 0),
            })
    top_profiles.sort(key=lambda x: x["followers"], reverse=True)
    top_profiles = top_profiles[:5]

    return jsonify(success_response({
        "total_post_files":    total_post_files,
        "total_profile_files": total_profile_files,
        "tracked_profiles":    len(tracking),
        "session_valid":       session_valid,
        "is_logged_in":        is_logged_in,
        "user_id":             login_state.get("user_id"),
        "browser_running":     login_state.get("is_running", False),
        "recent_posts":        recent_posts,
        "recent_profiles":     recent_profiles,
        "latest_sentiment":    latest_sentiment,
        "top_profiles":        top_profiles,
        "timestamp":           datetime.now().isoformat(),
    }, "Dashboard data retrieved"))


# ═══════════════════════════════════════════════════════════════════════════
# ENDPOINTS — KEYWORD / HASHTAG / TRENDING MONITORING
# ═══════════════════════════════════════════════════════════════════════════

_KEYWORD_MONITOR_SCRIPT = """\
import sys, os, json
sys.path.insert(0, os.environ["FB_SCRAPER_PATH"])
keyword     = os.environ["FB_KEYWORD"]
max_results = int(os.environ.get("FB_MAX_RESULTS", "1000"))
types       = os.environ.get("FB_TYPES", "posts").split(",")
sort_by     = os.environ.get("FB_SORT_BY", "engagement")
min_likes   = os.environ.get("FB_MIN_LIKES", "")
min_comments= os.environ.get("FB_MIN_COMMENTS", "")
min_views   = os.environ.get("FB_MIN_VIEWS", "")
max_comments_per_post = int(os.environ.get("FB_MAX_COMMENTS_PER_POST", "0"))
top_comments_count = int(os.environ.get("FB_TOP_COMMENTS_COUNT", "10"))

from fb_keyword_monitor import FacebookKeywordMonitor
with FacebookKeywordMonitor() as monitor:
    result = monitor.scrape_keyword(
        keyword, max_results, types, sort_by=sort_by,
        min_likes=int(min_likes) if min_likes else None,
        min_comments=int(min_comments) if min_comments else None,
        min_views=int(min_views) if min_views else None,
        max_comments_per_post=max_comments_per_post,
        top_comments_count=top_comments_count,
    )
print(json.dumps(result, ensure_ascii=False, default=str))
"""

_HASHTAG_SCRAPER_SCRIPT = """\
import sys, os, json
sys.path.insert(0, os.environ["FB_SCRAPER_PATH"])
hashtag     = os.environ["FB_HASHTAG"]
max_results = int(os.environ.get("FB_MAX_RESULTS", "1000"))
sort_by     = os.environ.get("FB_SORT_BY", "engagement")
min_likes   = os.environ.get("FB_MIN_LIKES", "")
min_comments= os.environ.get("FB_MIN_COMMENTS", "")
min_views   = os.environ.get("FB_MIN_VIEWS", "")
max_comments_per_post = int(os.environ.get("FB_MAX_COMMENTS_PER_POST", "0"))
top_comments_count = int(os.environ.get("FB_TOP_COMMENTS_COUNT", "10"))

from fb_keyword_monitor import FacebookKeywordMonitor
with FacebookKeywordMonitor() as monitor:
    result = monitor.scrape_hashtag(
        hashtag, max_results, sort_by=sort_by,
        min_likes=int(min_likes) if min_likes else None,
        min_comments=int(min_comments) if min_comments else None,
        min_views=int(min_views) if min_views else None,
        max_comments_per_post=max_comments_per_post,
        top_comments_count=top_comments_count,
    )
print(json.dumps(result, ensure_ascii=False, default=str))
"""

# ✅ UPDATED: _TRENDING_SCRAPER_SCRIPT with keyword + types support
_TRENDING_SCRAPER_SCRIPT = """\
import sys, os, json
sys.path.insert(0, os.environ["FB_SCRAPER_PATH"])
max_results = int(os.environ.get("FB_MAX_RESULTS", "1000"))
sort_by     = os.environ.get("FB_SORT_BY", "engagement")
keyword     = os.environ.get("FB_TRENDING_KEYWORD", "")
types_str   = os.environ.get("FB_TRENDING_TYPES", "posts,videos,groups,pages")
types       = [t.strip() for t in types_str.split(",") if t.strip()]
min_likes   = os.environ.get("FB_MIN_LIKES", "")
min_comments= os.environ.get("FB_MIN_COMMENTS", "")
min_views   = os.environ.get("FB_MIN_VIEWS", "")
max_comments_per_post = int(os.environ.get("FB_MAX_COMMENTS_PER_POST", "0"))
top_comments_count = int(os.environ.get("FB_TOP_COMMENTS_COUNT", "10"))

from fb_keyword_monitor import FacebookKeywordMonitor
with FacebookKeywordMonitor() as monitor:
    result = monitor.scrape_trending(
        max_results, sort_by, keyword, types,
        min_likes=int(min_likes) if min_likes else None,
        min_comments=int(min_comments) if min_comments else None,
        min_views=int(min_views) if min_views else None,
        max_comments_per_post=max_comments_per_post,
        top_comments_count=top_comments_count,
    )
print(json.dumps(result, ensure_ascii=False, default=str))
"""


def run_keyword_monitor_subprocess(
    keyword: str,
    max_results: int,
    types: list,
    sort_by: str = "engagement",
    min_likes: Optional[int] = None,
    min_comments: Optional[int] = None,
    min_views: Optional[int] = None,
    max_comments_per_post: int = 0,
    top_comments_count: int = 10,
) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["FB_SCRAPER_PATH"] = _HERE
    env["FB_KEYWORD"] = keyword
    env["FB_MAX_RESULTS"] = str(max_results)
    env["FB_TYPES"] = ",".join(types)
    env["FB_SORT_BY"] = sort_by
    env["FB_MIN_LIKES"] = "" if min_likes is None else str(min_likes)
    env["FB_MIN_COMMENTS"] = "" if min_comments is None else str(min_comments)
    env["FB_MIN_VIEWS"] = "" if min_views is None else str(min_views)
    env["FB_MAX_COMMENTS_PER_POST"] = str(max_comments_per_post)
    env["FB_TOP_COMMENTS_COUNT"] = str(top_comments_count)
    return _run_script_subprocess(_KEYWORD_MONITOR_SCRIPT, env=env, timeout=3600)


def run_hashtag_scraper_subprocess(
    hashtag: str,
    max_results: int,
    sort_by: str = "engagement",
    min_likes: Optional[int] = None,
    min_comments: Optional[int] = None,
    min_views: Optional[int] = None,
    max_comments_per_post: int = 0,
    top_comments_count: int = 10,
) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["FB_SCRAPER_PATH"] = _HERE
    env["FB_HASHTAG"] = hashtag
    env["FB_MAX_RESULTS"] = str(max_results)
    env["FB_SORT_BY"] = sort_by
    env["FB_MIN_LIKES"] = "" if min_likes is None else str(min_likes)
    env["FB_MIN_COMMENTS"] = "" if min_comments is None else str(min_comments)
    env["FB_MIN_VIEWS"] = "" if min_views is None else str(min_views)
    env["FB_MAX_COMMENTS_PER_POST"] = str(max_comments_per_post)
    env["FB_TOP_COMMENTS_COUNT"] = str(top_comments_count)
    return _run_script_subprocess(_HASHTAG_SCRAPER_SCRIPT, env=env, timeout=3600)


# ✅ UPDATED: run_trending_scraper_subprocess with keyword + types
def run_trending_scraper_subprocess(
    max_results: int,
    sort_by: str,
    keyword: str = "",
    types: Optional[List[str]] = None,
    min_likes: Optional[int] = None,
    min_comments: Optional[int] = None,
    min_views: Optional[int] = None,
    max_comments_per_post: int = 0,
    top_comments_count: int = 10,
) -> dict:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["FB_SCRAPER_PATH"] = _HERE
    env["FB_MAX_RESULTS"] = str(max_results)
    env["FB_SORT_BY"] = sort_by
    env["FB_TRENDING_KEYWORD"] = keyword
    env["FB_TRENDING_TYPES"] = ",".join(types or ["posts", "videos", "groups", "pages"])
    env["FB_MIN_LIKES"] = "" if min_likes is None else str(min_likes)
    env["FB_MIN_COMMENTS"] = "" if min_comments is None else str(min_comments)
    env["FB_MIN_VIEWS"] = "" if min_views is None else str(min_views)
    env["FB_MAX_COMMENTS_PER_POST"] = str(max_comments_per_post)
    env["FB_TOP_COMMENTS_COUNT"] = str(top_comments_count)
    return _run_script_subprocess(_TRENDING_SCRAPER_SCRIPT, env=env, timeout=3600)


@app.route("/api/v1/monitor/keyword", methods=["POST"])
@require_json_fields("keyword")
def monitor_keyword():
    data = request.get_json()
    keyword = data.get("keyword", "").strip()
    max_results = int(data.get("max_results", 1000))
    types = data.get("types", ["posts"])
    sort_by = data.get("sort_by", "engagement")
    min_likes = data.get("min_likes")
    min_comments = data.get("min_comments")
    min_views = data.get("min_views")
    max_comments_per_post = int(data.get("max_comments_per_post", 0) or 0)
    top_comments_count = int(data.get("top_comments_count", 10) or 10)
    if not isinstance(types, list):
        types = ["posts"]

    def work():
        print(Fore.CYAN + f"\n🔍 [Job] Monitoring keyword: {keyword}")
        print(Fore.CYAN + f"   Max results: {max_results} | types: {types} | sort: {sort_by}")
        print(Fore.YELLOW + "   ⏳ Estimasi bisa sampai beberapa menit...")
        t_start = time.time()
        result = run_keyword_monitor_subprocess(
            keyword, max_results, types, sort_by,
            int(min_likes) if min_likes not in (None, "") else None,
            int(min_comments) if min_comments not in (None, "") else None,
            int(min_views) if min_views not in (None, "") else None,
            max_comments_per_post,
            top_comments_count,
        )
        t_elapsed = time.time() - t_start

        result["_meta"] = {
            "elapsed_seconds": round(t_elapsed, 2),
            "keyword": keyword,
            "max_results": max_results,
            "types": types,
            "sort_by": sort_by,
            "min_likes": min_likes,
            "min_comments": min_comments,
            "min_views": min_views,
            "max_comments_per_post": max_comments_per_post,
        }

        filename = f"api_keyword_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(result, filename, OUTPUT_POST_DIR)
        result["_meta"]["saved_file"] = filename
        return result

    return _start_job("keyword", keyword, work)


@app.route("/api/v1/monitor/hashtag", methods=["POST"])
@require_json_fields("hashtag")
def monitor_hashtag():
    data = request.get_json()
    hashtag = data.get("hashtag", "").strip().lstrip('#')
    max_results = int(data.get("max_results", 1000))
    sort_by = data.get("sort_by", "engagement")
    min_likes = data.get("min_likes")
    min_comments = data.get("min_comments")
    min_views = data.get("min_views")
    max_comments_per_post = int(data.get("max_comments_per_post", 0) or 0)
    top_comments_count = int(data.get("top_comments_count", 10) or 10)

    def work():
        print(Fore.CYAN + f"\n🏷️  [Job] Scraping hashtag: #{hashtag}")
        print(Fore.CYAN + f"   Max results: {max_results} | sort: {sort_by}")
        print(Fore.YELLOW + "   ⏳ Estimasi bisa sampai beberapa menit...")
        t_start = time.time()
        result = run_hashtag_scraper_subprocess(
            hashtag, max_results, sort_by,
            int(min_likes) if min_likes not in (None, "") else None,
            int(min_comments) if min_comments not in (None, "") else None,
            int(min_views) if min_views not in (None, "") else None,
            max_comments_per_post,
            top_comments_count,
        )
        t_elapsed = time.time() - t_start

        result["_meta"] = {
            "elapsed_seconds": round(t_elapsed, 2),
            "hashtag": hashtag,
            "max_results": max_results,
            "sort_by": sort_by,
            "min_likes": min_likes,
            "min_comments": min_comments,
            "min_views": min_views,
            "max_comments_per_post": max_comments_per_post,
        }

        filename = f"api_hashtag_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(result, filename, OUTPUT_POST_DIR)
        result["_meta"]["saved_file"] = filename
        return result

    return _start_job("hashtag", f"#{hashtag}", work)


# ✅ UPDATED: endpoint monitor_trending with keyword + types support
@app.route("/api/v1/monitor/trending", methods=["POST"])
def monitor_trending():
    data = request.get_json() or {}
    max_results = int(data.get("max_results", 1000))
    sort_by = data.get("sort_by", "engagement")
    keyword = data.get("keyword", "").strip()  # ✅ BARU: keyword parameter
    types = data.get("types", ["posts", "videos", "groups", "pages"])  # ✅ BARU: types parameter
    min_likes = data.get("min_likes")
    min_comments = data.get("min_comments")
    min_views = data.get("min_views")
    max_comments_per_post = int(data.get("max_comments_per_post", 0) or 0)
    top_comments_count = int(data.get("top_comments_count", 10) or 10)
    
    if not isinstance(types, list):
        types = ["posts", "videos", "groups", "pages"]

    def work():
        print(Fore.CYAN + f"\n🔥 [Job] Scraping trending posts")
        print(Fore.CYAN + f"   Keyword: {keyword or '(semua trending)'}")
        print(Fore.CYAN + f"   Types: {types} | Sort: {sort_by}")
        print(Fore.YELLOW + "   ⏳ Estimasi bisa sampai beberapa menit...")
        t_start = time.time()
        result = run_trending_scraper_subprocess(
            max_results, sort_by, keyword, types,
            int(min_likes) if min_likes not in (None, "") else None,
            int(min_comments) if min_comments not in (None, "") else None,
            int(min_views) if min_views not in (None, "") else None,
            max_comments_per_post,
            top_comments_count,
        )
        t_elapsed = time.time() - t_start

        result["_meta"] = {
            "elapsed_seconds": round(t_elapsed, 2),
            "max_results": max_results,
            "sort_by": sort_by,
            "keyword": keyword,
            "types": types,
            "min_likes": min_likes,
            "min_comments": min_comments,
            "min_views": min_views,
            "max_comments_per_post": max_comments_per_post,
        }

        filename = f"api_trending_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json_output(result, filename, OUTPUT_POST_DIR)
        result["_meta"]["saved_file"] = filename
        return result

    return _start_job("trending", keyword or "trending", work)


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(Fore.CYAN + "=" * 65)
    print(Fore.CYAN + "  FACEBOOK SCRAPER API SERVER")
    print(Fore.CYAN + "  Post Comments + Profile + Growth Tracking")
    print(Fore.CYAN + "  + Hashtag & Trending Monitoring")
    print(Fore.CYAN + "  + Real-time Subprocess Output")
    print(Fore.CYAN + f"  Listening on http://{API_HOST}:{API_PORT}")
    print(Fore.CYAN + "=" * 65)

    try:
        from fb_cookie_injector import has_valid_session
        if has_valid_session():
            print(Fore.GREEN + "\n✅ Session Facebook valid — siap scraping!")
        else:
            print(Fore.YELLOW + "\n⚠️  Session belum ada.")
            print(Fore.YELLOW + "   Gunakan: python fb_session_manager.py")
    except Exception:
        print(Fore.YELLOW + "\n⚠️  fb_cookie_injector tidak ditemukan")

    print(Fore.YELLOW + "\n⚡ Server ready!\n")

    try:
        app.run(
            host=API_HOST,
            port=API_PORT,
            debug=DEBUG_MODE,
            threaded=False,
            use_reloader=False,
        )
    finally:
        print(Fore.YELLOW + "\n🧹 Server shutting down...")
