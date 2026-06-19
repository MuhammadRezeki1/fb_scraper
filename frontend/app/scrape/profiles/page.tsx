"use client";

import { useState } from "react";
import {
  User, Plus, Trash2, Send, CheckCircle, AlertTriangle,
  Users, FileText, Globe, BadgeCheck, Clock, Download,
  Building, Loader2, Sparkles, AtSign, Mail, Phone, MapPin,
  Image as ImageIcon, ExternalLink,
} from "lucide-react";
import GlassCard from "@/components/ui/GlassCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import DownloadButton from "@/components/ui/DownloadButton";
import { api, ProfileData } from "@/lib/api";
import { useScrape } from "@/contexts/ScrapeContext";

const TXT_SECONDARY = { color: "#4a5070" };
const TXT_MUTED = { color: "#8890aa" };

function fmtNum(n: number | undefined | null) {
  if (!n) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function firstLetter(name?: string) {
  return name?.trim()?.charAt(0)?.toUpperCase() || "?";
}

function profilePic(data: ProfileData) {
  return data.profile_picture_url || data.profile_pic_url || "";
}

function isVerified(data: ProfileData) {
  return Boolean(data.is_verified ?? data.verified);
}

function unpackProfile(payload: unknown): ProfileData | null {
  if (!payload || typeof payload !== "object") return null;
  const record = payload as { data?: unknown; username?: unknown; name?: unknown };
  if (record.data && typeof record.data === "object") return record.data as ProfileData;
  if (record.username || record.name) return payload as ProfileData;
  return null;
}

function introLines(data: ProfileData) {
  const raw = data.intro || data.bio || "";
  return raw
    .split("|")
    .map((item) => item.trim())
    .filter((item) => item.length > 0)
    .slice(0, 6);
}

function buildInsights(data: ProfileData) {
  const insights: string[] = [];
  if ((data.followers ?? 0) >= 1_000_000) insights.push("Audience besar, cocok diprioritaskan untuk tracking growth rutin.");
  if (data.category) insights.push(`Kategori terdeteksi: ${data.category}.`);
  if (data.website || data.email || data.phone) insights.push("Kontak publik ditemukan dari intro profil.");
  if (data.cover_photo_url && profilePic(data)) insights.push("Foto profil dan sampul berhasil ditangkap.");
  if (!insights.length) insights.push("Data dasar profil berhasil diambil. Jalankan ulang saat halaman Facebook sudah login penuh untuk detail yang lebih lengkap.");
  return insights.slice(0, 3);
}

function DetailLink({ icon: Icon, label, href }: { icon: typeof Globe; label: string; href?: string }) {
  const content = (
    <span className="min-w-0 truncate text-sm" style={TXT_SECONDARY}>
      {label}
    </span>
  );

  return (
    <div className="flex items-center gap-2 min-w-0">
      <Icon size={15} className="shrink-0" style={{ color: "#6b5ec7" }} />
      {href ? (
        <a href={href} target="_blank" rel="noopener noreferrer" className="min-w-0 truncate hover:underline" style={{ color: "#3b6dce" }}>
          {label}
        </a>
      ) : content}
    </div>
  );
}

function ProfileCard({ data }: { data: ProfileData }) {
  const avatar = profilePic(data);
  const cover = data.cover_photo_url || "";
  const intro = introLines(data);
  const verified = isVerified(data);
  const details = [
    data.category ? { icon: Building, label: data.category } : null,
    data.website ? { icon: Globe, label: data.website, href: data.website } : null,
    data.email ? { icon: Mail, label: data.email, href: `mailto:${data.email}` } : null,
    data.phone ? { icon: Phone, label: data.phone } : null,
    data.address ? { icon: MapPin, label: data.address } : null,
    data.profile_url ? { icon: ExternalLink, label: "Buka profil Facebook", href: data.profile_url } : null,
  ].filter(Boolean) as Array<{ icon: typeof Globe; label: string; href?: string }>;

  return (
    <GlassCard padding="p-0" className="overflow-hidden">
      <div
        className="relative min-h-44 sm:min-h-56"
        style={{ background: "linear-gradient(135deg, rgba(59,109,206,0.18), rgba(29,122,71,0.12), rgba(158,108,10,0.10))" }}
      >
        {cover ? (
          <img
            src={cover}
            alt={`Sampul ${data.name || data.username}`}
            referrerPolicy="no-referrer"
            className="absolute inset-0 h-full w-full object-cover"
            onError={(e) => { e.currentTarget.style.display = "none"; }}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center">
            <ImageIcon size={34} style={{ color: "rgba(74,80,112,0.35)" }} />
          </div>
        )}
        <div className="absolute inset-0" style={{ background: "linear-gradient(180deg, rgba(0,0,0,0.08), rgba(0,0,0,0.24))" }} />
      </div>

      <div className="px-5 pb-5 sm:px-6 sm:pb-6">
        <div className="-mt-12 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="flex min-w-0 items-end gap-4">
            <div
              className="h-24 w-24 shrink-0 overflow-hidden rounded-2xl border-4 border-white shadow-lg"
              style={{ background: "linear-gradient(135deg,#6b5ec7,#3b6dce)" }}
            >
              {avatar ? (
                <img
                  src={avatar}
                  alt={`Foto profil ${data.name || data.username}`}
                  referrerPolicy="no-referrer"
                  className="h-full w-full object-cover"
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
              ) : (
                <div className="flex h-full w-full items-center justify-center text-3xl font-bold text-white">
                  {firstLetter(data.name || data.username)}
                </div>
              )}
            </div>

            <div className="min-w-0 pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-2xl font-bold" style={{ color: "#1a1c23" }}>{data.name || data.username || "Profil"}</h3>
                {verified && <BadgeCheck size={20} style={{ color: "#3b6dce" }} />}
                {data.is_page && (
                  <span className="badge" style={{ background: "rgba(59,109,206,0.12)", color: "#3b6dce", border: "1px solid rgba(59,109,206,0.2)" }}>
                    Page
                  </span>
                )}
              </div>
              <p className="mt-1 flex items-center gap-1 text-sm" style={TXT_MUTED}>
                <AtSign size={13} />{data.username || "unknown"}
              </p>
            </div>
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {data.scraped_at && <span className="text-xs" style={TXT_MUTED}>{data.scraped_at.slice(0, 10)}</span>}
            <DownloadButton data={data} filename={`fb-profile-${data.username || "profile"}`} label="Download" className="px-3 py-2 text-sm" />
          </div>
        </div>

        <div className="mt-6 grid grid-cols-1 gap-3 lg:grid-cols-3">
          {[
            { icon: Users, label: "Followers", val: data.followers, color: "#6b5ec7" },
            { icon: User, label: "Following", val: data.following, color: "#3b6dce" },
            { icon: FileText, label: "Postingan", val: data.posts, color: "#1d7a47" },
          ].map(({ icon: Icon, label, val, color }) => (
            <div key={label} className="rounded-xl p-4" style={{ background: `${color}08`, border: `1px solid ${color}20` }}>
              <div className="flex items-center justify-between gap-3">
                <p className="text-sm font-medium" style={TXT_MUTED}>{label}</p>
                <Icon size={18} color={color} />
              </div>
              <p className="mt-2 text-2xl font-bold" style={{ color: "#1a1c23" }}>{fmtNum(val)}</p>
            </div>
          ))}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.8fr]">
          <div className="rounded-xl p-4" style={{ background: "rgba(255,255,255,0.72)", border: "1px solid rgba(0,0,0,0.07)" }}>
            <div className="mb-3 flex items-center gap-2">
              <Sparkles size={16} style={{ color: "#9e6c0a" }} />
              <h4 className="font-semibold" style={{ color: "#1a1c23" }}>Intro Profil</h4>
            </div>
            {intro.length > 0 ? (
              <div className="space-y-2">
                {intro.map((line, idx) => (
                  <p key={`${line}-${idx}`} className="text-sm leading-relaxed" style={TXT_SECONDARY}>{line}</p>
                ))}
              </div>
            ) : (
              <p className="text-sm" style={TXT_MUTED}>Intro belum terbaca dari halaman ini.</p>
            )}
          </div>

          <div className="rounded-xl p-4" style={{ background: "rgba(0,0,0,0.025)", border: "1px solid rgba(0,0,0,0.06)" }}>
            <div className="mb-3 flex items-center gap-2">
              <Sparkles size={16} style={{ color: "#6b5ec7" }} />
              <h4 className="font-semibold" style={{ color: "#1a1c23" }}>Insight Otomatis</h4>
            </div>
            <div className="space-y-2">
              {buildInsights(data).map((item, idx) => (
                <p key={idx} className="text-sm leading-relaxed" style={TXT_SECONDARY}>{item}</p>
              ))}
            </div>
          </div>
        </div>

        {details.length > 0 && (
          <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {details.map((item) => (
              <DetailLink key={item.label} icon={item.icon} label={item.label} href={item.href} />
            ))}
          </div>
        )}
      </div>
    </GlassCard>
  );
}

export default function ProfileScraperPage() {
  const { job, isRunning, start, finish, fail } = useScrape();
  const [usernames, setUsernames] = useState<string[]>([""]);
  const [saveTracking, setSave] = useState(true);
  const [delay, setDelay] = useState(30);
  const [formError, setFormError] = useState<string | null>(null);
  const [localResults, setLocalResults] = useState<ProfileData[]>([]);

  const ctxResults = job?.type === "profile" && job.status !== "running" ? job.profileResults : [];
  const elapsed = job?.type === "profile" && job.status === "done" ? job.elapsed : null;
  const scrapeErr = job?.type === "profile" && job.status === "error" ? job.error : null;
  const isMyRun = isRunning && job?.type === "profile";
  const otherRun = isRunning && job?.type !== "profile";
  const results = isMyRun ? [] : ctxResults.length > 0 ? ctxResults : localResults;
  const isBatch = usernames.filter(Boolean).length > 1;

  const addUsername = () => setUsernames((p) => [...p, ""]);
  const removeUsername = (i: number) => setUsernames((p) => p.filter((_, idx) => idx !== i));
  const setUsername = (i: number, v: string) => setUsernames((p) => p.map((u, idx) => idx === i ? v : u));

  const handleScrape = async () => {
    const valid = usernames.map((u) => u.trim()).filter(Boolean);
    if (!valid.length) { setFormError("Masukkan minimal satu username atau URL profil"); return; }
    if (isRunning) { setFormError("Scraping lain sedang berjalan, tunggu selesai dulu"); return; }
    setFormError(null);
    setLocalResults([]);
    const label = valid.length > 1 ? `${valid.length} profil (batch)` : valid[0];
    start("profile", label);
    const t0 = Date.now();
    try {
      let profiles: ProfileData[] = [];
      if (isBatch) {
        const res = await api.scrape.batchProfiles(valid, delay, saveTracking);
        profiles = (res.data?.results ?? [])
          .map((r) => unpackProfile(r.data))
          .filter((d): d is ProfileData => Boolean(d));
      } else {
        const res = await api.scrape.profile(valid[0], saveTracking);
        const profileData = unpackProfile(res.data);
        if (profileData) profiles = [profileData];
      }
      setLocalResults(profiles);
      finish({ profileResults: profiles, elapsed: Math.round((Date.now() - t0) / 1000) });
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : "Gagal scrape profil");
    }
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="mb-1 text-3xl font-bold gradient-text" style={{ fontFamily: "var(--font-sora)" }}>Scrape Profil</h1>
        <p className="text-sm" style={TXT_MUTED}>Ambil profil Facebook lengkap dengan foto, sampul, intro, followers, dan statistik publik.</p>
      </div>

      {otherRun && (
        <GlassCard glow="purple">
          <div className="flex items-center gap-3">
            <Loader2 size={15} className="shrink-0 animate-spin" style={{ color: "#6b5ec7" }} />
            <p className="text-sm" style={{ color: "#6b5ec7" }}>Scraping lain sedang berjalan di background. Tunggu selesai sebelum scrape profil.</p>
          </div>
        </GlassCard>
      )}

      <GlassCard>
        <h2 className="mb-4 flex items-center gap-2 font-semibold" style={{ color: "#1a1c23" }}>
          <User size={16} style={{ color: "#3b6dce" }} />Username / URL Facebook
        </h2>
        <div className="mb-4 space-y-2">
          {usernames.map((u, i) => (
            <div key={i} className="flex gap-2">
              <input
                type="text"
                value={u}
                onChange={(e) => setUsername(i, e.target.value)}
                placeholder="raffiAhmadLagi atau https://www.facebook.com/RaffiAhmadLagi"
                className="glass-input flex-1 px-4 py-2.5 text-sm"
                disabled={isMyRun}
              />
              {usernames.length > 1 && (
                <button onClick={() => removeUsername(i)} disabled={isMyRun} className="btn-glass px-3 py-2" style={{ color: "#c0394f" }}>
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          ))}
        </div>

        <button onClick={addUsername} disabled={isMyRun} className="btn-glass mb-5 flex items-center gap-2 px-4 py-2 text-sm">
          <Plus size={14} />Tambah Username
        </button>

        <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div className="flex items-center gap-3 rounded-xl p-3" style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.06)" }}>
            <input
              type="checkbox"
              id="tracking"
              checked={saveTracking}
              onChange={(e) => setSave(e.target.checked)}
              disabled={isMyRun}
              className="h-4 w-4 accent-violet-500"
            />
            <label htmlFor="tracking" className="cursor-pointer text-sm" style={TXT_SECONDARY}>Simpan untuk tracking growth</label>
          </div>
          {isBatch && (
            <div>
              <label className="mb-2 block text-xs font-medium" style={TXT_MUTED}>Jeda antar request (detik)</label>
              <input
                type="number"
                value={delay}
                onChange={(e) => setDelay(Number(e.target.value))}
                min={10}
                disabled={isMyRun}
                className="glass-input w-full px-4 py-2.5 text-sm"
              />
            </div>
          )}
        </div>

        <button onClick={handleScrape} disabled={isRunning || !usernames.some((u) => u.trim())} className="btn-primary flex items-center gap-2 px-6 py-2.5 text-sm">
          {isMyRun ? <LoadingSpinner size={16} /> : <Send size={14} />}
          {isMyRun ? "Sedang scraping..." : isBatch ? `Scrape ${usernames.filter(Boolean).length} Profil` : "Scrape Profil"}
        </button>

        {isMyRun && (
          <div className="mt-3 flex items-center gap-2 rounded-xl p-3 text-xs" style={{ background: "rgba(59,109,206,0.06)", border: "1px solid rgba(59,109,206,0.15)", color: "#3b6dce" }}>
            <Loader2 size={12} className="shrink-0 animate-spin" />
            Scraping berjalan di background. Output lama sudah dibersihkan dan hasil baru akan tampil saat selesai.
          </div>
        )}
      </GlassCard>

      {formError && (
        <GlassCard glow="pink">
          <div className="flex items-start gap-3">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: "#c0394f" }} />
            <p className="text-sm" style={{ color: "#c0394f" }}>{formError}</p>
          </div>
        </GlassCard>
      )}

      {scrapeErr && (
        <GlassCard glow="pink">
          <div className="flex items-start gap-3">
            <AlertTriangle size={16} className="mt-0.5 shrink-0" style={{ color: "#c0394f" }} />
            <p className="text-sm" style={{ color: "#c0394f" }}>{scrapeErr}</p>
          </div>
        </GlassCard>
      )}

      {results.length > 0 && (
        <GlassCard>
          <div className="flex flex-wrap items-center gap-4">
            <div className="flex items-center gap-2">
              <CheckCircle size={16} style={{ color: "#1d7a47" }} />
              <span className="text-sm font-semibold" style={{ color: "#1a1c23" }}>{results.length} profil berhasil diambil</span>
            </div>
            {elapsed !== null && <div className="flex items-center gap-2 text-xs" style={TXT_MUTED}><Clock size={12} />{elapsed}s</div>}
            {saveTracking && <div className="flex items-center gap-2 text-xs" style={TXT_MUTED}><Download size={12} />Tersimpan di tracking</div>}
            <div className="ml-auto flex items-center gap-2">
              <DownloadButton data={results} filename={`fb-profiles-${new Date().toISOString().slice(0, 10)}`} label="Download Profil" />
            </div>
          </div>
        </GlassCard>
      )}

      <div className="grid grid-cols-1 gap-5">
        {results.map((p, idx) => (
          <ProfileCard key={`${p.username || "profile"}-${idx}`} data={p} />
        ))}
      </div>

      {results.length === 0 && !isMyRun && !scrapeErr && (
        <GlassCard>
          <h3 className="mb-3 text-sm font-semibold" style={{ color: "#1a1c23" }}>Tips Penggunaan</h3>
          <ul className="space-y-2 text-sm" style={TXT_SECONDARY}>
            {[
              "Masukkan username atau URL profil lengkap.",
              "Aktifkan tracking growth agar snapshot tersimpan ke analitik.",
              "Gunakan batch untuk beberapa profil sekaligus.",
              "Foto profil dan sampul akan tampil jika Facebook memuat gambar publiknya.",
            ].map((t, i) => (
              <li key={i} className="flex items-start gap-2">
                <CheckCircle size={13} className="mt-0.5 shrink-0" style={{ color: "#6b5ec7" }} />{t}
              </li>
            ))}
          </ul>
        </GlassCard>
      )}
    </div>
  );
}
