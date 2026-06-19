"""
facebook_cli.py
===============
Unified CLI untuk semua fitur Facebook Scraper:
  - Scrape komentar post (FacebookScraperV21)
  - Scrape profil (FacebookProfileScraperV21)
  - Growth tracking & analisis
  - Manage session cookies

Menu utama:
  [1] Scrape Post (komentar + sentiment)
  [2] Scrape Profil
  [3] Growth Tracking & Analisis
  [4] Session Manager (login / cookies)
  [5] Output Manager (lihat file hasil)
  [6] Konfigurasi
  [7] Exit
"""
import os
import sys
import json
import time
import random
import csv
from datetime import datetime, timedelta
from typing import List, Dict, Optional

from colorama import Fore, Style, init

init(autoreset=True)

# ── PATHS ──────────────────────────────────────────────────────────────────
OUTPUT_POST_DIR    = "output_facebook"
OUTPUT_PROFILE_DIR = "output_fb_profiles"
TRACKING_FILE      = os.path.join(OUTPUT_PROFILE_DIR, "growth_tracking.json")

os.makedirs(OUTPUT_POST_DIR,    exist_ok=True)
os.makedirs(OUTPUT_PROFILE_DIR, exist_ok=True)


# ── HELPERS ────────────────────────────────────────────────────────────────

def print_banner():
    print(Fore.CYAN + """
╔══════════════════════════════════════════════════════════════════════╗
║               FACEBOOK SCRAPER — UNIFIED CLI                        ║
║   Post Comments • Profile Scraper • Growth Tracking • Session Mgr   ║
╚══════════════════════════════════════════════════════════════════════╝""")


def print_separator(title: str = "", char: str = "─", width: int = 70):
    if title:
        side = (width - len(title) - 2) // 2
        print(Fore.CYAN + char * side + f" {title} " + char * side)
    else:
        print(Fore.CYAN + char * width)


def check_session_status() -> bool:
    try:
        from fb_cookie_injector import has_valid_session
        return has_valid_session()
    except Exception:
        return False


def session_status_line() -> str:
    if check_session_status():
        try:
            from fb_cookie_injector import get_session_info
            info    = get_session_info()
            user_id = info.get("user_id", "?")
            return Fore.GREEN + f"● Session: VALID (User ID: {user_id})"
        except Exception:
            return Fore.GREEN + "● Session: VALID"
    return Fore.RED + "● Session: TIDAK ADA (login dulu via menu [4]!)"


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
        json.dump(data, f, ensure_ascii=False, indent=2)


def save_json(data: dict, filepath: str) -> str:
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return filepath


def _save_profile_to_tracking(profile_result: dict):
    """Simpan hasil scrape profil ke growth_tracking.json."""
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

        today   = scraped_at[:10]
        history = tracking[username].get("history", [])
        updated = False
        for h in history:
            if h.get("scraped_at", "")[:10] == today:
                h.update(snapshot)
                updated = True
                break
        if not updated:
            tracking[username]["history"].append(snapshot)

        tracking[username]["last_tracked"] = scraped_at
        save_tracking_data(tracking)
        print(Fore.GREEN + f"   💾 Growth tracking updated: @{username}")
    except Exception as e:
        print(Fore.YELLOW + f"   ⚠️  Tracking warning: {e}")


def input_with_default(prompt: str, default: str = "") -> str:
    display = f" [{default}]" if default else ""
    result  = input(Fore.WHITE + f"{prompt}{display}: ").strip()
    return result if result else default


def confirm(prompt: str) -> bool:
    ans = input(Fore.YELLOW + f"{prompt} (y/n) [n]: ").strip().lower()
    return ans in ("y", "yes", "ya")


# ═══════════════════════════════════════════════════════════════════════════
# MENU 1: SCRAPE POST
# ═══════════════════════════════════════════════════════════════════════════

def menu_scrape_post():
    print_separator("SCRAPE POST FACEBOOK")
    print(Fore.YELLOW + """
📋 Mode yang tersedia:
  1. Single post (satu URL)
  2. Multiple posts (dari file fb_urls.txt)
  3. Kembali
""")

    choice = input(Fore.WHITE + "Pilih [1-3]: ").strip()

    if choice == "1":
        _scrape_single_post()
    elif choice == "2":
        _scrape_batch_posts()
    elif choice == "3":
        return
    else:
        print(Fore.RED + "❌ Pilihan tidak valid")


def _scrape_single_post():
    print(Fore.CYAN + "\n💡 Contoh URL:")
    print("   https://www.facebook.com/username/posts/1234567890")
    print("   https://www.facebook.com/photo?fbid=1234567890")
    print("   https://www.facebook.com/share/p/abcXYZ")

    url = input(Fore.WHITE + "\n🔗 URL Facebook Post: ").strip()
    if not url:
        print(Fore.RED + "❌ URL tidak boleh kosong")
        return

    max_comments = input_with_default("Max komentar", "200")
    try:
        max_comments = int(max_comments)
    except ValueError:
        max_comments = 200

    print(Fore.CYAN + f"\n⏳ Mulai scraping... (maks {max_comments} komentar)")
    print(Fore.YELLOW + "   Estimasi waktu: 60-180 detik\n")

    try:
        from fb_scraper import FacebookScraperV21

        t_start = time.time()
        with FacebookScraperV21() as scraper:
            result = scraper.scrape_post(url, max_comments)
        t_elapsed = time.time() - t_start

        print(Fore.CYAN + f"\n⏱️  Waktu: {t_elapsed:.1f} detik")
        if result.get("comments_count", 0) > 0:
            print(Fore.CYAN + f"📈 Rate: {result['comments_count']/t_elapsed:.1f} komentar/detik")

        filename = f"post_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(OUTPUT_POST_DIR, filename)
        save_json(result, filepath)
        print(Fore.GREEN + f"\n💾 Hasil tersimpan: {filepath}")

    except ImportError:
        print(Fore.RED + "❌ fb_scraper_v21.py tidak ditemukan di direktori ini")
    except Exception as e:
        print(Fore.RED + f"\n❌ Gagal: {e}")
        import traceback
        traceback.print_exc()


def _scrape_batch_posts():
    url_file = input_with_default("File URL", "fb_urls.txt")

    if not os.path.exists(url_file):
        create_sample = confirm(f"File '{url_file}' tidak ada. Buat file contoh?")
        if create_sample:
            with open(url_file, "w", encoding="utf-8") as f:
                f.write("# Facebook Post Scraper — Satu URL per baris\n")
                f.write("# Baris yang dimulai dengan # akan diabaikan\n")
                f.write("# Contoh:\n")
                f.write("# https://www.facebook.com/username/posts/1234567890\n")
                f.write("# https://www.facebook.com/photo?fbid=9876543210\n")
            print(Fore.GREEN + f"✅ File contoh dibuat: {url_file}")
            print(Fore.YELLOW + "   Isi file dengan URL Facebook, lalu jalankan ulang")
        return

    with open(url_file, "r", encoding="utf-8") as f:
        urls = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    if not urls:
        print(Fore.RED + f"❌ File '{url_file}' kosong atau hanya berisi komentar")
        return

    print(Fore.CYAN + f"\n📋 {len(urls)} URL ditemukan")

    max_urls_input = input_with_default(f"Max URL (tersedia {len(urls)}, Enter=semua)", "")
    if max_urls_input.isdigit():
        urls = urls[:int(max_urls_input)]

    max_comments = input_with_default("Max komentar per post", "200")
    try:
        max_comments = int(max_comments)
    except ValueError:
        max_comments = 200

    delay = input_with_default("Jeda antar post (detik)", "30")
    try:
        delay = int(delay)
    except ValueError:
        delay = 30

    print(Fore.CYAN + f"\n📋 Konfigurasi batch:")
    print(f"   URL         : {len(urls)}")
    print(f"   Max komentar: {max_comments}")
    print(f"   Jeda        : {delay}s")

    if not confirm("\nMulai batch scraping?"):
        return

    try:
        from fb_scraper import FacebookScraperV21

        results   = []
        t_total   = time.time()
        success_n = 0

        with FacebookScraperV21() as scraper:
            for i, url in enumerate(urls, 1):
                print(Fore.CYAN + f"\n[{i}/{len(urls)}] {url[:70]}")
                try:
                    r = scraper.scrape_post(url, max_comments)
                    filename = f"post_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{i}.json"
                    filepath = os.path.join(OUTPUT_POST_DIR, filename)
                    save_json(r, filepath)
                    print(Fore.GREEN + f"   ✅ Tersimpan: {filename}")
                    results.append({"url": url, "success": True, "file": filename,
                                    "comments_count": r.get("comments_count", 0)})
                    success_n += 1
                except Exception as e:
                    print(Fore.RED + f"   ❌ Gagal: {e}")
                    results.append({"url": url, "success": False, "error": str(e)})

                if i < len(urls):
                    actual_delay = delay + random.randint(5, 15)
                    print(Fore.YELLOW + f"   ⏳ Jeda {actual_delay}s...")
                    time.sleep(actual_delay)

        t_elapsed = time.time() - t_total
        print(Fore.GREEN + f"\n✅ Batch selesai!")
        print(f"   Berhasil   : {success_n}/{len(urls)}")
        print(f"   Gagal      : {len(urls) - success_n}/{len(urls)}")
        print(f"   Total waktu: {t_elapsed:.1f} detik")

        summary_file = os.path.join(
            OUTPUT_POST_DIR,
            f"batch_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        save_json({
            "total":           len(urls),
            "success":         success_n,
            "failed":          len(urls) - success_n,
            "elapsed_seconds": round(t_elapsed, 2),
            "results":         results,
        }, summary_file)
        print(Fore.GREEN + f"   Summary: {summary_file}")

    except ImportError:
        print(Fore.RED + "❌ fb_scraper_v21.py tidak ditemukan")
    except Exception as e:
        print(Fore.RED + f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MENU 2: SCRAPE PROFIL
# ═══════════════════════════════════════════════════════════════════════════

def menu_scrape_profile():
    print_separator("SCRAPE PROFIL FACEBOOK")
    print(Fore.YELLOW + """
📋 Mode yang tersedia:
  1. Single profil (username atau URL)
  2. Multiple profil (dari file fb_usernames.txt)
  3. Kembali
""")

    choice = input(Fore.WHITE + "Pilih [1-3]: ").strip()

    if choice == "1":
        _scrape_single_profile()
    elif choice == "2":
        _scrape_batch_profiles()
    elif choice == "3":
        return
    else:
        print(Fore.RED + "❌ Pilihan tidak valid")


def _scrape_single_profile():
    print(Fore.CYAN + "\n💡 Format input yang diterima:")
    print("   • Username biasa  : prabowo")
    print("   • Dengan @        : @prabowo")
    print("   • URL lengkap     : https://www.facebook.com/prabowo")
    print("   • URL profil.php  : https://www.facebook.com/profile.php?id=123456")

    raw_input = input(Fore.WHITE + "\n👤 Username / URL: ").strip()
    if not raw_input:
        print(Fore.RED + "❌ Input tidak boleh kosong")
        return

    save_tracking = confirm("Simpan ke growth tracking?")

    print(Fore.CYAN + "\n⏳ Scraping profil...")
    print(Fore.YELLOW + "   Estimasi: 30-60 detik\n")

    try:
        from fb_profile_scraper import FacebookProfileScraperV21

        t_start = time.time()
        with FacebookProfileScraperV21() as scraper:
            result = scraper.scrape_profile(raw_input)
        t_elapsed = time.time() - t_start

        print(Fore.CYAN + f"\n⏱️  Waktu: {t_elapsed:.1f} detik")

        if result.get("success") and result.get("data"):
            data     = result["data"]
            username = data.get("username", "unknown")

            filename = f"profile_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            filepath = os.path.join(OUTPUT_PROFILE_DIR, filename)
            save_json(result["data"], filepath)
            print(Fore.GREEN + f"💾 Tersimpan: {filepath}")

            if save_tracking:
                _save_profile_to_tracking(result)
        else:
            print(Fore.RED + f"❌ Scraping gagal: {result.get('error', 'Unknown error')}")

    except ImportError:
        print(Fore.RED + "❌ fb_profile_scraper_v21.py tidak ditemukan")
    except Exception as e:
        print(Fore.RED + f"❌ Error: {e}")
        import traceback
        traceback.print_exc()


def _scrape_batch_profiles():
    usernames_file = input_with_default("File usernames", "fb_usernames.txt")

    if not os.path.exists(usernames_file):
        create_sample = confirm(f"File '{usernames_file}' tidak ada. Buat file contoh?")
        if create_sample:
            with open(usernames_file, "w", encoding="utf-8") as f:
                f.write("# Facebook Profile Scraper — Satu username/URL per baris\n")
                f.write("# Contoh:\n")
                f.write("# prabowo\n")
                f.write("# @jokowi\n")
                f.write("# https://www.facebook.com/GibranRakabuming\n")
            print(Fore.GREEN + f"✅ File contoh dibuat: {usernames_file}")
        return

    with open(usernames_file, "r", encoding="utf-8") as f:
        usernames = [l.strip() for l in f if l.strip() and not l.startswith("#")]

    if not usernames:
        print(Fore.RED + f"❌ File '{usernames_file}' kosong")
        return

    print(Fore.CYAN + f"\n📋 {len(usernames)} username/URL ditemukan")

    max_input = input_with_default(f"Max profiles (tersedia {len(usernames)}, Enter=semua)", "")
    if max_input.isdigit():
        usernames = usernames[:int(max_input)]

    delay = input_with_default("Jeda antar profil (detik)", "30")
    try:
        delay = int(delay)
    except ValueError:
        delay = 30

    save_tracking = confirm("Simpan ke growth tracking?")

    if not confirm(f"\nMulai batch scraping {len(usernames)} profil?"):
        return

    try:
        from fb_profile_scraper import FacebookProfileScraperV21

        results   = []
        t_total   = time.time()
        success_n = 0

        with FacebookProfileScraperV21() as scraper:
            for i, raw_input in enumerate(usernames, 1):
                print(Fore.CYAN + f"\n[{i}/{len(usernames)}] {raw_input}")
                try:
                    r = scraper.scrape_profile(raw_input)
                    if r.get("success") and r.get("data"):
                        data     = r["data"]
                        username = data.get("username", f"user_{i}")
                        filename = f"profile_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
                        filepath = os.path.join(OUTPUT_PROFILE_DIR, filename)
                        save_json(data, filepath)
                        if save_tracking:
                            _save_profile_to_tracking(r)
                        results.append({"input": raw_input, "username": username,
                                        "success": True, "file": filename})
                        success_n += 1
                    else:
                        results.append({"input": raw_input, "success": False,
                                        "error": r.get("error", "Unknown")})
                except Exception as e:
                    results.append({"input": raw_input, "success": False, "error": str(e)})
                    print(Fore.RED + f"   ❌ Error: {e}")

                if i < len(usernames):
                    actual_delay = delay + random.randint(5, 10)
                    print(Fore.YELLOW + f"   ⏳ Jeda {actual_delay}s...")
                    time.sleep(actual_delay)

        t_elapsed = time.time() - t_total
        print(Fore.GREEN + f"\n✅ Batch profil selesai!")
        print(f"   Berhasil: {success_n}/{len(usernames)}")
        print(f"   Waktu   : {t_elapsed:.1f} detik")

        summary_file = os.path.join(
            OUTPUT_PROFILE_DIR,
            f"batch_profile_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
        )
        save_json({"total": len(usernames), "success": success_n, "results": results}, summary_file)
        print(Fore.GREEN + f"   Summary: {summary_file}")

    except ImportError:
        print(Fore.RED + "❌ fb_profile_scraper_v21.py tidak ditemukan")
    except Exception as e:
        print(Fore.RED + f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MENU 3: GROWTH TRACKING & ANALISIS
# ═══════════════════════════════════════════════════════════════════════════

def menu_growth_tracking():
    print_separator("GROWTH TRACKING & ANALISIS")

    tracking = load_tracking_data()

    if not tracking:
        print(Fore.YELLOW + "\n⚠️  Belum ada data tracking.")
        print(Fore.YELLOW + "   Scrape profil dulu (Menu 2) untuk mulai tracking.")
        input(Fore.WHITE + "\nTekan Enter untuk kembali...")
        return

    print(Fore.YELLOW + f"\n📊 {len(tracking)} akun ter-track\n")
    print("""
  1. Lihat daftar akun ter-track
  2. Analisis pertumbuhan satu akun
  3. Bandingkan beberapa akun
  4. Export history ke CSV
  5. Tambah data manual (backfill)
  6. Hapus data akun
  7. Kembali
""")

    choice = input(Fore.WHITE + "Pilih [1-7]: ").strip()

    if choice == "1":
        _list_tracked_accounts(tracking)
    elif choice == "2":
        _analyze_single_growth(tracking)
    elif choice == "3":
        _compare_accounts(tracking)
    elif choice == "4":
        _export_to_csv(tracking)
    elif choice == "5":
        _add_manual_snapshot(tracking)
    elif choice == "6":
        _delete_tracking_account(tracking)
    elif choice == "7":
        return
    else:
        print(Fore.RED + "❌ Pilihan tidak valid")


def _list_tracked_accounts(tracking: dict):
    print_separator("DAFTAR AKUN TER-TRACK (FACEBOOK)")
    print()

    for username, data in sorted(tracking.items()):
        history  = data.get("history", [])
        count    = len(history)
        first    = data.get("first_tracked", "")[:10]
        last     = data.get("last_tracked", "")[:10]
        latest   = history[-1] if history else {}
        is_page  = "📄" if latest.get("is_page") else "👤"
        followers = latest.get("followers", 0)
        likes     = latest.get("likes", 0)

        print(Fore.CYAN + f"  {is_page} @{username:<28}" + Fore.WHITE +
              f" {count:>3} snapshots  |  " +
              Fore.YELLOW + f"{first} → {last}" +
              Fore.WHITE + f"  |  👥 {followers:>10,}  ❤️  {likes:>12,}")

    print()
    input(Fore.WHITE + "Tekan Enter untuk kembali...")


def _analyze_single_growth(tracking: dict):
    print(Fore.CYAN + "\n📈 ANALISIS PERTUMBUHAN SATU AKUN (FACEBOOK)")

    usernames = list(tracking.keys())
    print(Fore.YELLOW + "\nAkun tersedia:")
    for i, u in enumerate(usernames, 1):
        count   = len(tracking[u].get("history", []))
        is_page = "📄" if tracking[u].get("history", [{}])[-1].get("is_page") else "👤"
        print(f"  {i:>3}. {is_page} @{u} ({count} snapshots)")

    raw = input(Fore.WHITE + "\n👤 Username (atau nomor): ").strip().lstrip("@")

    if raw.isdigit():
        idx = int(raw) - 1
        if 0 <= idx < len(usernames):
            username = usernames[idx]
        else:
            print(Fore.RED + "❌ Nomor tidak valid")
            return
    else:
        username = raw

    if username not in tracking:
        print(Fore.RED + f"❌ @{username} tidak ada dalam tracking")
        return

    days_input = input_with_default("Analisis berapa hari terakhir", "30")
    try:
        days = int(days_input)
    except ValueError:
        days = 30

    history = tracking[username].get("history", [])
    if len(history) < 2:
        print(Fore.YELLOW + f"⚠️  Hanya {len(history)} data point — perlu minimal 2")
        return

    cutoff   = datetime.now() - timedelta(days=days)
    filtered = [h for h in history if datetime.fromisoformat(h["scraped_at"]) >= cutoff]
    if len(filtered) < 2:
        print(Fore.YELLOW + f"⚠️  Hanya {len(filtered)} data dalam {days} hari terakhir, pakai semua data")
        filtered = history

    filtered.sort(key=lambda x: x["scraped_at"])
    first = filtered[0]
    last  = filtered[-1]

    first_dt  = datetime.fromisoformat(first["scraped_at"])
    last_dt   = datetime.fromisoformat(last["scraped_at"])
    days_span = (last_dt - first_dt).days or 1

    box = 68
    print("\n" + Fore.GREEN + "┌" + "─" * box + "┐")
    print(Fore.GREEN + "│" + f"  📈 ANALISIS PERTUMBUHAN — @{username} [FACEBOOK]".center(box) + "│")
    print(Fore.GREEN + "├" + "─" * box + "┤")
    print(Fore.GREEN + "│  " + f"📅 {first_dt.strftime('%d %b %Y')} → {last_dt.strftime('%d %b %Y')} ({days_span} hari)".ljust(box-2) + "│")
    print(Fore.GREEN + "│  " + f"📊 {len(filtered)} data points".ljust(box-2) + "│")
    print(Fore.GREEN + "├" + "─" * box + "┤")

    def print_metric(label, field, icon=""):
        s       = first.get(field, 0)
        e       = last.get(field, 0)
        g       = e - s
        pct     = round(g / s * 100, 1) if s > 0 else 0
        per_day = round(g / days_span, 1)
        color   = Fore.GREEN if g >= 0 else Fore.RED
        sign    = "+" if g >= 0 else ""
        print(Fore.GREEN + "│" + " " * box + "│")
        print(Fore.GREEN + "│  " + f"{icon} {label}".ljust(box-2) + "│")
        print(Fore.GREEN + "│  " + f"   Awal   : {s:>15,}".ljust(box-2) + "│")
        print(Fore.GREEN + "│  " + f"   Akhir  : {e:>15,}".ljust(box-2) + "│")
        print(color + "│  " + f"   Growth : {sign}{g:>15,} ({sign}{pct}%)".ljust(box-2) + "│")
        print(color + "│  " + f"   /hari  : {sign}{per_day:>15,}".ljust(box-2) + "│")

    print_metric("FOLLOWERS", "followers", "👥")
    print_metric("FOLLOWING", "following", "👤")
    print_metric("LIKES",     "likes",     "❤️ ")
    print_metric("POSTS",     "posts",     "📝")

    print(Fore.GREEN + "│" + " " * box + "│")
    print(Fore.GREEN + "└" + "─" * box + "┘\n")

    if confirm("Simpan analisis ke file JSON?"):
        analysis = {
            "username":    username,
            "platform":    "facebook",
            "analyzed_at": datetime.now().isoformat(),
            "days_span":   days_span,
            "data_points": len(filtered),
            "first":       first,
            "last":        last,
            "history":     filtered,
        }
        fn  = f"fb_growth_{username}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        fp  = os.path.join(OUTPUT_PROFILE_DIR, fn)
        save_json(analysis, fp)
        print(Fore.GREEN + f"💾 {fp}")


def _compare_accounts(tracking: dict):
    print(Fore.CYAN + "\n📊 PERBANDINGAN BEBERAPA AKUN (FACEBOOK)")
    print(Fore.YELLOW + "Akun tersedia: " + ", ".join([f"@{u}" for u in tracking.keys()]))

    raw = input(Fore.WHITE + "\n👥 Usernames (pisahkan koma): ").strip()
    if not raw:
        return

    usernames = [u.strip().lstrip("@") for u in raw.split(",") if u.strip()]
    metric_map = {"1": "followers", "2": "following", "3": "likes", "4": "posts"}

    print(Fore.YELLOW + "\nMetric:")
    print("  1. Followers  2. Following  3. Likes  4. Posts")
    metric_choice = input_with_default("Pilih [1-4]", "1")
    metric = metric_map.get(metric_choice, "followers")

    print(Fore.CYAN + f"\n📊 Perbandingan {metric.upper()} untuk {len(usernames)} akun:\n")
    print_separator()

    rows = []
    for username in usernames:
        if username not in tracking:
            print(Fore.YELLOW + f"   ⚠️  @{username} tidak ada, skip")
            continue

        history = tracking[username].get("history", [])
        if not history:
            continue

        history_sorted = sorted(history, key=lambda x: x["scraped_at"])
        first_val = history_sorted[0].get(metric, 0)
        last_val  = history_sorted[-1].get(metric, 0)
        growth    = last_val - first_val
        pct       = round(growth / first_val * 100, 1) if first_val > 0 else 0
        is_page   = "📄" if history_sorted[-1].get("is_page") else "👤"

        rows.append({
            "username":  username,
            "is_page":   is_page,
            "first_val": first_val,
            "last_val":  last_val,
            "growth":    growth,
            "pct":       pct,
        })

    rows.sort(key=lambda x: x["last_val"], reverse=True)

    header = f"{'Rank':<5} {'Username':<27} {'Current':>12} {'Growth':>12} {'Growth %':>10}"
    print(Fore.CYAN + header)
    print(Fore.CYAN + "─" * 70)

    for rank, row in enumerate(rows, 1):
        color = Fore.GREEN if row["growth"] >= 0 else Fore.RED
        sign  = "+" if row["growth"] >= 0 else ""
        print(Fore.WHITE + f"{rank:<5} {row['is_page']} @{row['username']:<24} " +
              f"{row['last_val']:>12,}  " +
              color + f"{sign}{row['growth']:>11,}  {sign}{row['pct']:>8.1f}%")

    print_separator()


def _export_to_csv(tracking: dict):
    username_input = input(Fore.WHITE + "\n👤 Username (atau 'all' untuk semua): ").strip().lstrip("@")

    if username_input == "all":
        targets = list(tracking.keys())
    else:
        targets = [username_input] if username_input in tracking else []
        if not targets:
            print(Fore.RED + f"❌ @{username_input} tidak ditemukan")
            return

    for username in targets:
        history = tracking[username].get("history", [])
        if not history:
            continue

        output_file = os.path.join(OUTPUT_PROFILE_DIR, f"{username}_fb_growth_history.csv")
        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["Date", "Followers", "Following", "Likes", "Posts", "Is_Page"])
            for entry in sorted(history, key=lambda x: x["scraped_at"]):
                date = entry["scraped_at"][:19].replace("T", " ")
                writer.writerow([
                    date,
                    entry.get("followers", 0),
                    entry.get("following", 0),
                    entry.get("likes", 0),
                    entry.get("posts", 0),
                    entry.get("is_page", False),
                ])
        print(Fore.GREEN + f"✅ Export @{username}: {output_file}")

    input(Fore.WHITE + "\nTekan Enter untuk kembali...")


def _add_manual_snapshot(tracking: dict):
    print(Fore.CYAN + "\n📝 TAMBAH DATA MANUAL (BACKFILL)")

    username = input(Fore.WHITE + "👤 Username: ").strip().lstrip("@")
    if not username:
        return

    date_input  = input_with_default("Tanggal (YYYY-MM-DD)", datetime.now().strftime("%Y-%m-%d"))
    followers   = input_with_default("Followers", "0")
    following   = input_with_default("Following", "0")
    likes       = input_with_default("Likes", "0")
    posts       = input_with_default("Posts", "0")
    is_page_raw = input_with_default("Apakah ini Facebook Page? (y/n)", "n")
    is_page     = is_page_raw.lower() in ("y", "yes", "ya")

    try:
        scraped_at = f"{date_input}T00:00:00"
        datetime.fromisoformat(scraped_at)
    except ValueError:
        print(Fore.RED + "❌ Format tanggal tidak valid. Gunakan YYYY-MM-DD")
        return

    if username not in tracking:
        tracking[username] = {
            "username":      username,
            "first_tracked": scraped_at,
            "history":       [],
            "platform":      "facebook",
        }

    snapshot = {
        "scraped_at": scraped_at,
        "followers":  int(followers.replace(",", "") or 0),
        "following":  int(following.replace(",", "") or 0),
        "likes":      int(likes.replace(",", "") or 0),
        "posts":      int(posts.replace(",", "") or 0),
        "is_page":    is_page,
    }

    tracking[username]["history"].append(snapshot)
    tracking[username]["last_tracked"] = scraped_at
    save_tracking_data(tracking)
    print(Fore.GREEN + f"✅ Snapshot manual ditambahkan untuk @{username} pada {date_input}")


def _delete_tracking_account(tracking: dict):
    print(Fore.CYAN + "\n🗑️  HAPUS DATA TRACKING AKUN")
    print(Fore.YELLOW + "Akun yang tersedia:")
    for u in tracking.keys():
        count = len(tracking[u].get("history", []))
        print(f"   @{u} ({count} snapshots)")

    username = input(Fore.WHITE + "\n👤 Username yang akan dihapus: ").strip().lstrip("@")

    if username not in tracking:
        print(Fore.RED + f"❌ @{username} tidak ditemukan")
        return

    count = len(tracking[username].get("history", []))
    if confirm(f"Hapus semua {count} data tracking untuk @{username}?"):
        del tracking[username]
        save_tracking_data(tracking)
        print(Fore.GREEN + f"✅ Data @{username} dihapus")


# ═══════════════════════════════════════════════════════════════════════════
# MENU 4: SESSION MANAGER
# ═══════════════════════════════════════════════════════════════════════════

def menu_session():
    print_separator("SESSION MANAGER")

    try:
        import fb_session_manager as sm
        sm.print_banner()
        sm.main()
    except ImportError:
        print(Fore.RED + "❌ fb_session_manager.py tidak ditemukan")
        print(Fore.YELLOW + "\n📋 Manual workaround:")
        print("   1. Login Facebook di browser")
        print("   2. Install ekstensi Cookie-Editor")
        print("   3. Export cookies sebagai JSON")
        print("   4. Simpan ke session/fb_session.json")
    except SystemExit:
        pass
    except Exception as e:
        print(Fore.RED + f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MENU 5: OUTPUT MANAGER
# ═══════════════════════════════════════════════════════════════════════════

def menu_output_manager():
    print_separator("OUTPUT MANAGER")

    print(Fore.YELLOW + "\n📁 Direktori output:")
    print(f"   Post komentar : {os.path.abspath(OUTPUT_POST_DIR)}")
    print(f"   Profiles      : {os.path.abspath(OUTPUT_PROFILE_DIR)}")

    post_files    = [f for f in os.listdir(OUTPUT_POST_DIR)    if f.endswith(".json")] if os.path.exists(OUTPUT_POST_DIR)    else []
    profile_files = [f for f in os.listdir(OUTPUT_PROFILE_DIR) if f.endswith(".json")] if os.path.exists(OUTPUT_PROFILE_DIR) else []

    print(Fore.CYAN + f"\n📊 Statistik:")
    print(f"   Post files    : {len(post_files)}")
    print(f"   Profile files : {len(profile_files)}")

    print(Fore.YELLOW + """
  1. Lihat file post terbaru (10)
  2. Lihat file profil terbaru (10)
  3. Buka folder post di file explorer
  4. Buka folder profil di file explorer
  5. Hapus semua file output post
  6. Hapus semua file output profil
  7. Kembali
""")

    choice = input(Fore.WHITE + "Pilih [1-7]: ").strip()

    if choice == "1":
        _list_recent_files(OUTPUT_POST_DIR, "post", 10)
    elif choice == "2":
        _list_recent_files(OUTPUT_PROFILE_DIR, "profil", 10)
    elif choice == "3":
        _open_folder(OUTPUT_POST_DIR)
    elif choice == "4":
        _open_folder(OUTPUT_PROFILE_DIR)
    elif choice == "5":
        _clear_output_dir(OUTPUT_POST_DIR, "post")
    elif choice == "6":
        _clear_output_dir(OUTPUT_PROFILE_DIR, "profil")
    elif choice == "7":
        return
    else:
        print(Fore.RED + "❌ Pilihan tidak valid")


def _list_recent_files(directory: str, label: str, n: int):
    if not os.path.exists(directory):
        print(Fore.RED + f"❌ Folder {directory} tidak ditemukan")
        return

    files = [
        (f, os.path.getmtime(os.path.join(directory, f)))
        for f in os.listdir(directory)
        if f.endswith(".json")
    ]
    files.sort(key=lambda x: x[1], reverse=True)

    print(Fore.CYAN + f"\n📁 {n} file {label} terbaru:")
    for i, (fname, mtime) in enumerate(files[:n], 1):
        dt      = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
        size_kb = os.path.getsize(os.path.join(directory, fname)) / 1024
        print(f"  {i:>3}. {fname:<52} {dt}  {size_kb:>8.1f} KB")

    print()
    input(Fore.WHITE + "Tekan Enter untuk kembali...")


def _open_folder(path: str):
    abs_path = os.path.abspath(path)
    try:
        if sys.platform == "win32":
            os.startfile(abs_path)
        elif sys.platform == "darwin":
            os.system(f"open '{abs_path}'")
        else:
            os.system(f"xdg-open '{abs_path}'")
        print(Fore.GREEN + f"✅ Folder dibuka: {abs_path}")
    except Exception as e:
        print(Fore.YELLOW + f"   ⚠️  Tidak bisa buka folder otomatis: {e}")
        print(Fore.WHITE + f"   Path: {abs_path}")


def _clear_output_dir(directory: str, label: str):
    if not os.path.exists(directory):
        print(Fore.YELLOW + f"⚠️  Folder {directory} tidak ditemukan")
        return

    files = [f for f in os.listdir(directory) if f.endswith(".json")]
    if not files:
        print(Fore.YELLOW + f"⚠️  Tidak ada file JSON di folder {label}")
        return

    if confirm(f"Hapus {len(files)} file JSON dari folder {label}?"):
        deleted = 0
        for f in files:
            try:
                os.remove(os.path.join(directory, f))
                deleted += 1
            except Exception:
                pass
        print(Fore.GREEN + f"✅ {deleted} file dihapus dari {directory}")


# ═══════════════════════════════════════════════════════════════════════════
# MENU 6: KONFIGURASI
# ═══════════════════════════════════════════════════════════════════════════

def menu_config():
    print_separator("KONFIGURASI FACEBOOK SCRAPER")

    env_file = ".env"
    env_vars = {}

    if os.path.exists(env_file):
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    env_vars[key.strip()] = val.strip()

    defaults = {
        "FB_HEADLESS":               "False",
        "FB_MAX_COMMENTS":           "200",
        "FB_DELAY_BETWEEN_REQUESTS": "30",
        "FB_PROXY":                  "",
        "SENTIMENT_MODE":            "hybrid",
        "FB_API_PORT":               "5002",
        "DEBUG_DUMP":                "0",
    }

    fb_vars = {k: v for k, v in env_vars.items() if k.startswith("FB_") or k in ("SENTIMENT_MODE", "DEBUG_DUMP")}

    print(Fore.CYAN + "\n📋 Konfigurasi Facebook saat ini (.env):")
    for key, default in defaults.items():
        current = fb_vars.get(key, default)
        print(f"   {key:<40} = {Fore.YELLOW}{current}{Fore.WHITE} (default: {default})")

    print(Fore.YELLOW + "\n  1. Edit konfigurasi")
    print("  2. Reset ke default")
    print("  3. Lihat .env file lengkap")
    print("  4. Kembali")

    choice = input(Fore.WHITE + "\nPilih [1-4]: ").strip()

    if choice == "1":
        print(Fore.CYAN + "\n📝 Edit konfigurasi (Enter untuk skip/pertahankan nilai saat ini):")
        new_vals = {}
        for key, default in defaults.items():
            current = fb_vars.get(key, default)
            new_val = input(f"   {key} [{current}]: ").strip()
            if new_val:
                new_vals[key] = new_val

        if new_vals:
            env_vars.update(new_vals)
            with open(env_file, "w", encoding="utf-8") as f:
                for k, v in env_vars.items():
                    f.write(f"{k}={v}\n")
            print(Fore.GREEN + f"✅ {len(new_vals)} nilai tersimpan ke {env_file}")
            print(Fore.YELLOW + "   Restart CLI agar perubahan berlaku")
        else:
            print(Fore.YELLOW + "   Tidak ada perubahan")

    elif choice == "2":
        if confirm("Reset semua konfigurasi Facebook ke default?"):
            for key in defaults:
                env_vars.pop(key, None)
            with open(env_file, "w", encoding="utf-8") as f:
                for k, v in env_vars.items():
                    f.write(f"{k}={v}\n")
            print(Fore.GREEN + "✅ Konfigurasi direset ke default")

    elif choice == "3":
        if os.path.exists(env_file):
            with open(env_file, "r", encoding="utf-8") as f:
                print(Fore.CYAN + f"\n📄 {env_file}:")
                print(f.read())
        else:
            print(Fore.YELLOW + f"⚠️  File {env_file} belum ada")

    input(Fore.WHITE + "\nTekan Enter untuk kembali...")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print_banner()

    session_ok = check_session_status()
    tracking   = load_tracking_data()

    print(Fore.WHITE + f"\n  {session_status_line()}")
    print(Fore.WHITE + f"  📊 Tracking: {len(tracking)} akun")
    print(Fore.WHITE + f"  📁 Output post    : {OUTPUT_POST_DIR}/")
    print(Fore.WHITE + f"  📁 Output profil  : {OUTPUT_PROFILE_DIR}/")

    while True:
        print(Fore.CYAN + "\n" + "═" * 70)
        print(Fore.CYAN + "  MENU UTAMA — FACEBOOK SCRAPER")
        print(Fore.CYAN + "═" * 70)
        print(f"  {Fore.WHITE}[1]{Fore.RESET} 📝  Scrape Post (komentar + sentiment)")
        print(f"  {Fore.WHITE}[2]{Fore.RESET} 👤  Scrape Profil (Facebook Page/Profile)")
        print(f"  {Fore.WHITE}[3]{Fore.RESET} 📈  Growth Tracking & Analisis")
        print(f"  {Fore.WHITE}[4]{Fore.RESET} 🔑  Session Manager (login / cookies)")
        print(f"  {Fore.WHITE}[5]{Fore.RESET} 📁  Output Manager")
        print(f"  {Fore.WHITE}[6]{Fore.RESET} ⚙️   Konfigurasi")
        print(f"  {Fore.WHITE}[7]{Fore.RESET} 👋  Exit")
        print(Fore.CYAN + "─" * 70)
        print(f"  {session_status_line()}")

        choice = input(Fore.WHITE + "\nPilih [1-7]: ").strip()

        if choice == "1":
            if not session_ok:
                print(Fore.RED + "\n❌ Session tidak valid! Gunakan menu [4] untuk login dulu.")
                continue
            menu_scrape_post()

        elif choice == "2":
            if not session_ok:
                print(Fore.RED + "\n❌ Session tidak valid! Gunakan menu [4] untuk login dulu.")
                continue
            menu_scrape_profile()

        elif choice == "3":
            menu_growth_tracking()

        elif choice == "4":
            menu_session()
            session_ok = check_session_status()

        elif choice == "5":
            menu_output_manager()

        elif choice == "6":
            menu_config()

        elif choice == "7":
            print(Fore.CYAN + "\n👋 Bye! Terima kasih menggunakan Facebook Scraper CLI")
            break

        else:
            print(Fore.RED + "❌ Pilihan tidak valid [1-7]")


if __name__ == "__main__":
    main()