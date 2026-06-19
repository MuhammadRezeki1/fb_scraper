"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Shield, CheckCircle, XCircle, LogIn, LogOut,
  RefreshCw, AlertTriangle, Key, Clock, Info, Eye,
  Cookie, Upload, Clipboard,
} from "lucide-react";
import GlassCard from "@/components/ui/GlassCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import { api, AuthStatus, ImportCookiesResult } from "@/lib/api";

export default function AuthPage() {
  const [status, setStatus]       = useState<AuthStatus | null>(null);
  const [loading, setLoading]     = useState(true);
  const [actionLoading, setAL]    = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [successMsg, setSuccess]  = useState<string | null>(null);
  const [timeout, setTimeout_]    = useState(5);
  const [headless, setHeadless]   = useState(false);

  // Cookie inject state
  const [cookiePaste, setCookiePaste]         = useState("");
  const [cookieUsername, setCookieUsername]   = useState("");
  const [cookieLoading, setCookieLoading]     = useState(false);
  const [cookieError, setCookieError]         = useState<string | null>(null);
  const [cookieResult, setCookieResult]       = useState<ImportCookiesResult | null>(null);
  const [cookieParseOk, setCookieParseOk]     = useState<number | null>(null); // parsed count preview

  const fetchStatus = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.auth.status();
      if (res.data) setStatus(res.data);
    } catch {
      setError("Tidak dapat terhubung ke backend");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchStatus(); }, [fetchStatus]);

  useEffect(() => {
    if (!status?.is_running) return;
    const id = setInterval(fetchStatus, 5000);
    return () => clearInterval(id);
  }, [status?.is_running, fetchStatus]);

  // Live-parse cookie paste for preview count
  useEffect(() => {
    const text = cookiePaste.trim();
    if (!text) { setCookieParseOk(null); return; }
    try {
      const parsed = JSON.parse(text);
      const arr = Array.isArray(parsed) ? parsed : parsed?.cookies;
      setCookieParseOk(Array.isArray(arr) ? arr.length : null);
    } catch {
      setCookieParseOk(null);
    }
  }, [cookiePaste]);

  const handleLogin = async () => {
    setAL(true);
    setError(null);
    setSuccess(null);
    try {
      await api.auth.login(timeout, headless);
      setSuccess("Browser login dibuka. Selesaikan login di browser, lalu klik Refresh Status.");
      await fetchStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Gagal membuka browser login");
    } finally {
      setAL(false);
    }
  };

  const handleLogout = async (hardReset: boolean) => {
    if (!confirm(hardReset ? "Hard reset akan menghapus seluruh profil Chrome. Lanjutkan?" : "Hapus sesi Facebook?")) return;
    setAL(true);
    setError(null);
    try {
      await api.auth.logout(hardReset);
      setSuccess(hardReset ? "Hard reset berhasil." : "Logout berhasil. Sesi dihapus.");
      await fetchStatus();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Gagal logout");
    } finally {
      setAL(false);
    }
  };

  const handleInjectCookies = async () => {
    setCookieError(null);
    setCookieResult(null);

    const text = cookiePaste.trim();
    if (!text) { setCookieError("Paste JSON cookies terlebih dahulu"); return; }

    let cookies: unknown[];
    try {
      const parsed = JSON.parse(text);
      if (Array.isArray(parsed)) {
        cookies = parsed;
      } else if (parsed?.cookies && Array.isArray(parsed.cookies)) {
        cookies = parsed.cookies;
      } else {
        setCookieError("Format tidak dikenali. Harus array [...] atau objek {\"cookies\": [...]}");
        return;
      }
    } catch (e: unknown) {
      setCookieError(`JSON tidak valid: ${e instanceof Error ? e.message : String(e)}`);
      return;
    }

    if (cookies.length === 0) {
      setCookieError("Array cookies kosong");
      return;
    }

    setCookieLoading(true);
    try {
      const res = await api.auth.importCookies(cookies, cookieUsername || undefined);
      if (res.data) {
        setCookieResult(res.data);
        if (res.data.valid) {
          setSuccess(`Cookies berhasil diinjeksi! User ID: ${res.data.user_id}`);
          setCookiePaste("");
          await fetchStatus();
        }
      }
    } catch (e: unknown) {
      setCookieError(e instanceof Error ? e.message : "Gagal inject cookies");
    } finally {
      setCookieLoading(false);
    }
  };

  const handlePasteFromClipboard = async () => {
    try {
      const text = await navigator.clipboard.readText();
      setCookiePaste(text);
    } catch {
      setCookieError("Tidak dapat membaca clipboard. Paste manual di kolom di bawah.");
    }
  };

  const isLoggedIn = status?.is_logged_in ?? false;
  const isRunning  = status?.is_running ?? false;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold gradient-text mb-1">Autentikasi</h1>
          <p className="text-sm" style={{ color: "#8890aa" }}>
            Kelola sesi login Facebook untuk scraping
          </p>
        </div>
        <button
          onClick={fetchStatus}
          disabled={loading}
          className="btn-glass flex items-center gap-2 px-4 py-2 text-sm"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Refresh Status
        </button>
      </div>

      {/* Alerts */}
      {error && (
        <GlassCard glow="pink">
          <div className="flex gap-3 items-start">
            <AlertTriangle size={16} style={{ color: "#c0394f" }} className="shrink-0 mt-0.5" />
            <p className="text-sm" style={{ color: "#c0394f" }}>{error}</p>
          </div>
        </GlassCard>
      )}
      {successMsg && (
        <GlassCard glow="green">
          <div className="flex gap-3 items-start">
            <CheckCircle size={16} style={{ color: "#1d7a47" }} className="shrink-0 mt-0.5" />
            <p className="text-sm" style={{ color: "#1d7a47" }}>{successMsg}</p>
          </div>
        </GlassCard>
      )}

      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner size={40} text="Mengambil status autentikasi..." />
        </div>
      ) : (
        <>
          {/* Status card */}
          <GlassCard glow={isLoggedIn ? "green" : "pink"}>
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-4">
                <div
                  className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0"
                  style={{
                    background: isLoggedIn ? "rgba(29,122,71,0.12)" : "rgba(192,57,79,0.12)",
                    border:     isLoggedIn ? "1px solid rgba(29,122,71,0.25)" : "1px solid rgba(192,57,79,0.25)",
                  }}
                >
                  <Shield size={26} color={isLoggedIn ? "#1d7a47" : "#c0394f"} />
                </div>
                <div>
                  <p className="text-xs font-medium uppercase tracking-wider mb-1" style={{ color: "#8890aa" }}>Status Login</p>
                  <p className="text-xl font-bold" style={{ color: isLoggedIn ? "#1d7a47" : "#c0394f" }}>
                    {isLoggedIn ? "Terverifikasi" : "Belum Login"}
                  </p>
                  <p className="text-sm mt-0.5" style={{ color: "#8890aa" }}>
                    {isLoggedIn
                      ? `User ID: ${status?.user_id || "terdeteksi"}`
                      : "Sesi Facebook tidak aktif"}
                  </p>
                </div>
              </div>
              {isRunning && (
                <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg shrink-0" style={{ background: "rgba(158,108,10,0.08)", border: "1px solid rgba(158,108,10,0.15)" }}>
                  <div className="pulse-dot bg-yellow-400" />
                  <span className="text-xs font-medium" style={{ color: "#9e6c0a" }}>Browser berjalan</span>
                </div>
              )}
            </div>
          </GlassCard>

          {/* Status checklist */}
          {status && (
            <GlassCard>
              <h3 className="font-semibold mb-4 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <Info size={16} style={{ color: "#3b6dce" }} />
                Detail Status
              </h3>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                {[
                  { label: "Session File Valid",  val: status.session_file_valid },
                  { label: "Login Terdeteksi",    val: status.login_detected },
                  { label: "Profile Dir Ada",     val: status.profile_dir_exists },
                  { label: "Browser Running",     val: status.is_running },
                  { label: "Is Logged In",        val: status.is_logged_in },
                ].map(({ label, val }) => (
                  <div
                    key={label}
                    className="flex items-center gap-2 p-3 rounded-xl"
                    style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.06)" }}
                  >
                    {val
                      ? <CheckCircle size={15} style={{ color: "#1d7a47" }} className="shrink-0" />
                      : <XCircle    size={15} style={{ color: "#8890aa" }} className="shrink-0" />}
                    <span className="text-xs" style={{ color: "#4a5070" }}>{label}</span>
                  </div>
                ))}
              </div>
              {status.browser_opened_at && (
                <div className="mt-4 flex items-center gap-2 text-xs" style={{ color: "#8890aa" }}>
                  <Clock size={12} />
                  Browser dibuka: {status.browser_opened_at.slice(0, 19).replace("T", " ")}
                </div>
              )}
              {status.last_error && (
                <div className="mt-3 p-3 rounded-xl" style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.15)" }}>
                  <p className="text-xs" style={{ color: "#c0394f" }}>
                    <span className="font-semibold">Error terakhir:</span> {status.last_error}
                  </p>
                </div>
              )}
            </GlassCard>
          )}

          {/* ── COOKIE INJECT ─────────────────────────────────────────────── */}
          <GlassCard glow="cyan">
            <h3 className="font-semibold mb-1 flex items-center gap-2" style={{ color: "#1a1c23" }}>
              <Cookie size={16} style={{ color: "#2193b0" }} />
              Inject Cookie Facebook
            </h3>
            <p className="text-xs mb-4" style={{ color: "#8890aa" }}>
              Export cookies dari ekstensi <span style={{ color: "#2193b0" }} className="font-semibold">Cookie-Editor</span> di Chrome/Firefox,
              lalu paste JSON-nya di bawah. Format array <code style={{ color: "#2193b0" }}>[ {"{...}"} ]</code> atau{" "}
              <code style={{ color: "#2193b0" }}>{"{ \"cookies\": [...] }"}</code> keduanya diterima.
            </p>

            {/* Textarea + paste button */}
            <div className="relative mb-3">
              <textarea
                value={cookiePaste}
                onChange={e => { setCookiePaste(e.target.value); setCookieResult(null); setCookieError(null); }}
                placeholder={'[\n  {\n    "name": "c_user",\n    "value": "...",\n    "domain": ".facebook.com",\n    ...\n  },\n  ...\n]'}
                rows={8}
                className="glass-input w-full px-4 py-3 text-xs font-mono resize-y"
                style={{ minHeight: "160px" }}
                spellCheck={false}
              />
              {/* Live parse preview */}
              {cookiePaste.trim() && (
                <div
                  className="absolute top-2 right-2 px-2 py-0.5 rounded-full text-xs font-mono"
                  style={{
                    background: cookieParseOk !== null ? "rgba(29,122,71,0.12)" : "rgba(192,57,79,0.12)",
                    border:     cookieParseOk !== null ? "1px solid rgba(29,122,71,0.25)" : "1px solid rgba(192,57,79,0.25)",
                    color:      cookieParseOk !== null ? "#1d7a47" : "#c0394f",
                  }}
                >
                  {cookieParseOk !== null ? `✓ ${cookieParseOk} cookies` : "✗ JSON invalid"}
                </div>
              )}
            </div>

            {/* Optional username + paste button row */}
            <div className="flex gap-3 mb-4 flex-wrap">
              <input
                type="text"
                value={cookieUsername}
                onChange={e => setCookieUsername(e.target.value)}
                placeholder="Username Facebook (opsional)"
                className="glass-input flex-1 px-4 py-2.5 text-sm min-w-0"
                style={{ minWidth: "160px" }}
              />
              <button
                onClick={handlePasteFromClipboard}
                className="btn-glass flex items-center gap-2 px-4 py-2.5 text-sm shrink-0"
              >
                <Clipboard size={13} />
                Paste Clipboard
              </button>
            </div>

            {/* Error */}
            {cookieError && (
              <div className="mb-4 p-3 rounded-xl flex gap-2 items-start"
                style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.2)" }}>
                <XCircle size={14} style={{ color: "#c0394f" }} className="shrink-0 mt-0.5" />
                <p className="text-xs" style={{ color: "#c0394f" }}>{cookieError}</p>
              </div>
            )}

            {/* Result */}
            {cookieResult && (
              <div
                className="mb-4 p-4 rounded-xl"
                style={{
                  background: cookieResult.valid ? "rgba(29,122,71,0.06)" : "rgba(158,108,10,0.06)",
                  border:     cookieResult.valid ? "1px solid rgba(29,122,71,0.2)" : "1px solid rgba(158,108,10,0.2)",
                }}
              >
                <div className="flex items-center gap-2 mb-2">
                  {cookieResult.valid
                    ? <CheckCircle size={14} style={{ color: "#1d7a47" }} />
                    : <AlertTriangle size={14} style={{ color: "#9e6c0a" }} />}
                  <span className="text-sm font-semibold" style={{ color: cookieResult.valid ? "#1d7a47" : "#9e6c0a" }}>
                    {cookieResult.valid ? "Session Valid!" : "Cookies Disimpan (Belum Valid)"}
                  </span>
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 text-xs" style={{ color: "#4a5070" }}>
                  <span>Total: <strong style={{ color: "#1a1c23" }}>{cookieResult.total_cookies}</strong></span>
                  {cookieResult.user_id && (
                    <span>User ID: <strong style={{ color: "#2193b0" }} className="font-mono">{cookieResult.user_id}</strong></span>
                  )}
                  {cookieResult.has_preferred !== undefined && (
                    <span>Preferred: <strong style={{ color: cookieResult.has_preferred ? "#1d7a47" : "#9e6c0a" }}>
                      {cookieResult.has_preferred ? "Lengkap" : "Kurang"}
                    </strong></span>
                  )}
                </div>
                {cookieResult.preferred_missing && cookieResult.preferred_missing.length > 0 && (
                  <p className="mt-2 text-xs" style={{ color: "#9e6c0a" }}>
                    Cookie yang disarankan tidak ada: {cookieResult.preferred_missing.join(", ")}
                  </p>
                )}
                {cookieResult.cookie_names && cookieResult.cookie_names.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {cookieResult.cookie_names.map(n => (
                      <span key={n}
                        className="px-1.5 py-0.5 rounded text-xs font-mono"
                        style={{ background: "rgba(33,147,176,0.1)", color: "#2193b0" }}>
                        {n}
                      </span>
                    ))}
                  </div>
                )}
                {cookieResult.warning && (
                  <p className="mt-2 text-xs" style={{ color: "#9e6c0a" }}>{cookieResult.warning}</p>
                )}
              </div>
            )}

            {/* Inject button */}
            <button
              onClick={handleInjectCookies}
              disabled={cookieLoading || !cookiePaste.trim()}
              className="btn-primary flex items-center gap-2 px-6 py-2.5 text-sm"
            >
              {cookieLoading
                ? <LoadingSpinner size={14} />
                : <Upload size={14} />}
              {cookieLoading ? "Menginjeksi..." : "Inject Cookies"}
            </button>

            {/* Tip */}
            <div className="mt-4 p-3 rounded-xl" style={{ background: "rgba(33,147,176,0.04)", border: "1px solid rgba(33,147,176,0.1)" }}>
              <p className="text-xs font-semibold mb-1.5 flex items-center gap-1" style={{ color: "#2193b0" }}>
                <Key size={11} />
                Cara export cookies dari browser:
              </p>
              <ol className="list-decimal list-inside space-y-0.5 text-xs" style={{ color: "#4a5070" }}>
                <li>Install ekstensi <span style={{ color: "#2193b0" }}>Cookie-Editor</span> di Chrome/Firefox</li>
                <li>Buka <span style={{ color: "#1a1c23" }}>facebook.com</span> dan pastikan sudah login</li>
                <li>Klik ikon Cookie-Editor → klik tombol <span style={{ color: "#1a1c23" }}>Export</span> (ikon copy)</li>
                <li>Paste JSON yang ter-copy ke kolom di atas</li>
                <li>Klik <span style={{ color: "#1a1c23" }}>Inject Cookies</span></li>
              </ol>
            </div>
          </GlassCard>

          {/* Login action (browser) */}
          {!isLoggedIn && (
            <GlassCard glow="purple">
              <h3 className="font-semibold mb-4 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <LogIn size={16} style={{ color: "#6b5ec7" }} />
                Login via Browser (Alternatif)
              </h3>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-5">
                <div>
                  <label className="text-xs font-medium mb-2 block" style={{ color: "#8890aa" }}>
                    Timeout (menit)
                  </label>
                  <input
                    type="number"
                    value={timeout}
                    onChange={e => setTimeout_(Number(e.target.value))}
                    min={1}
                    max={30}
                    className="glass-input w-full px-4 py-2.5 text-sm"
                  />
                </div>
                <div className="flex items-center gap-3 p-3 rounded-xl" style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.06)" }}>
                  <input
                    type="checkbox"
                    id="headless"
                    checked={headless}
                    onChange={e => setHeadless(e.target.checked)}
                    className="w-4 h-4 accent-purple-500"
                  />
                  <label htmlFor="headless" className="text-sm cursor-pointer" style={{ color: "#4a5070" }}>
                    <div className="flex items-center gap-1">
                      <Eye size={13} />
                      Mode Headless
                    </div>
                    <p className="text-xs mt-0.5" style={{ color: "#8890aa" }}>
                      Browser tidak tampil (background)
                    </p>
                  </label>
                </div>
              </div>

              <button
                onClick={handleLogin}
                disabled={actionLoading || isRunning}
                className="btn-primary flex items-center gap-2 px-6 py-2.5 text-sm"
              >
                {actionLoading ? <LoadingSpinner size={16} /> : <LogIn size={14} />}
                {isRunning ? "Browser sedang berjalan..." : "Buka Browser Login"}
              </button>

              {isRunning && (
                <div className="mt-4 p-4 rounded-xl"
                  style={{ background: "rgba(158,108,10,0.06)", border: "1px solid rgba(158,108,10,0.15)" }}>
                  <p className="text-sm font-semibold mb-2" style={{ color: "#9e6c0a" }}>Langkah Login:</p>
                  <ol className="list-decimal list-inside space-y-1 text-xs" style={{ color: "#4a5070" }}>
                    <li>Browser Chrome akan terbuka (atau sudah terbuka)</li>
                    <li>Login manual ke Facebook</li>
                    <li>Selesaikan verifikasi 2FA jika diminta</li>
                    <li>Tunggu halaman beranda Facebook muncul</li>
                    <li>Klik "Refresh Status" untuk memverifikasi</li>
                  </ol>
                </div>
              )}
            </GlassCard>
          )}

          {/* Logout action */}
          {isLoggedIn && (
            <GlassCard>
              <h3 className="font-semibold mb-4 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <LogOut size={16} style={{ color: "#c0394f" }} />
                Kelola Sesi
              </h3>
              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => handleLogout(false)}
                  disabled={actionLoading || isRunning}
                  className="btn-glass flex items-center gap-2 px-5 py-2.5 text-sm"
                  style={{ border: "1px solid rgba(192,57,79,0.25)", color: "#c0394f" }}
                >
                  {actionLoading ? <LoadingSpinner size={14} /> : <LogOut size={14} />}
                  Logout (Hapus Session File)
                </button>
                <button
                  onClick={() => handleLogout(true)}
                  disabled={actionLoading || isRunning}
                  className="btn-glass flex items-center gap-2 px-5 py-2.5 text-sm"
                  style={{ border: "1px solid rgba(192,57,79,0.4)", color: "#c0394f" }}
                >
                  <AlertTriangle size={14} />
                  Hard Reset (Hapus Chrome Profile)
                </button>
              </div>
              <p className="text-xs mt-3" style={{ color: "#8890aa" }}>
                Hard reset menghapus semua data Chrome lokal dan memerlukan login ulang.
              </p>
            </GlassCard>
          )}
        </>
      )}
    </div>
  );
}