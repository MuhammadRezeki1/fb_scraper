"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import {
  FileText, Users, RefreshCw, Eye, MessageSquare,
  AlertTriangle, Download, Calendar, Filter,
  ChevronDown, ChevronUp, BarChart2, Globe,
  ThumbsUp, Share2,
} from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import GlassCard from "@/components/ui/GlassCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import StatusBadge from "@/components/ui/StatusBadge";
import { api, DashboardData, RecentPost, RecentProfile, Comment } from "@/lib/api";
import { useScrape } from "@/contexts/ScrapeContext";
import { downloadJSON, downloadCSV } from "@/lib/download";

// ─── Helpers ──────────────────────────────────────────────────────────────────
function fmtNum(n: number | undefined) {
  if (!n) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

const PIE_COLORS: Record<string, string> = {
  Positif: "#4ade80", Negatif: "#f87171", Netral: "#94a3b8",
  "Hate Speech": "#ef4444", Toxic: "#fb923c", Humor: "#facc15", Sarkasme: "#c084fc",
};

type TabType = "posts" | "profiles";

// ─── Sentiment mini-bar ────────────────────────────────────────────────────────
function SentimentBar({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div>
      <div className="flex justify-between text-xs mb-1">
        <span style={{ color: "#8890aa" }}>{label}</span>
        <span style={{ color }}>{pct.toFixed(1)}%</span>
      </div>
      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} />
      </div>
    </div>
  );
}

// ─── Post row (expandable) ────────────────────────────────────────────────────
function PostRow({ post, idx, onScrapePost, isRunning }: { post: RecentPost; idx: number; onScrapePost: (url: string) => void; isRunning: boolean }) {
  const [open, setOpen] = useState(false);
  const s = post.sentiment_summary;

  const pieData = s
    ? [
        { name: "Positif",    value: Math.round((s.positive_percentage ?? 0) * (s.total_comments ?? 0) / 100) },
        { name: "Negatif",    value: Math.round((s.negative_percentage ?? 0) * (s.total_comments ?? 0) / 100) },
        { name: "Netral",     value: Math.round((s.neutral_percentage  ?? 0) * (s.total_comments ?? 0) / 100) },
        { name: "Hate Speech",value: Math.round((s.hate_percentage     ?? 0) * (s.total_comments ?? 0) / 100) },
        { name: "Toxic",      value: Math.round((s.toxic_percentage    ?? 0) * (s.total_comments ?? 0) / 100) },
      ].filter(d => d.value > 0)
    : [];

  return (
    <>
      <tr className="cursor-pointer hover:bg-[rgba(107,94,199,0.02)]" onClick={() => setOpen(o => !o)}>
        <td className="text-xs" style={{ color: "#8890aa" }}>{idx + 1}</td>
        <td>
          <div className="flex items-start gap-2">
            <div
              className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 mt-0.5"
              style={{ background: "rgba(107,94,199,0.1)", border: "1px solid rgba(107,94,199,0.2)" }}
            >
              <FileText size={12} style={{ color: "#6b5ec7" }} />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <p className="text-sm font-medium truncate max-w-xs" style={{ color: "#1a1c23" }}>
                  {post.caption || post.url || post.filename}
                </p>
                {post.post_type && post.post_type !== "post" && (
                  <span className="badge shrink-0" style={{ background: "rgba(107,94,199,0.1)", color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.2)", fontSize: 10 }}>
                    {post.post_type.toUpperCase()}
                  </span>
                )}
              </div>
              <p className="text-xs truncate max-w-xs" style={{ color: "#8890aa" }}>
                {post.filename}
              </p>
            </div>
          </div>
        </td>
        <td className="text-sm" style={{ color: "#4a5070" }}>
          {post.comments_count !== undefined ? (
            <span className="flex items-center gap-1">
              <MessageSquare size={12} style={{ color: "#6b5ec7" }} />
              {post.comments_count}
            </span>
          ) : "—"}
        </td>
        <td className="text-xs" style={{ color: "#4a5070" }}>
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1" title="Likes/Reactions">
              <ThumbsUp size={11} style={{ color: "#c0394f" }} />{fmtNum(post.total_likes)}
            </span>
            <span className="flex items-center gap-1" title="Shares">
              <Share2 size={11} style={{ color: "#3b6dce" }} />{fmtNum(post.total_shares)}
            </span>
          </div>
        </td>
        <td>
          {s ? (
            <div className="flex items-center gap-1.5">
              <span className="text-xs" style={{ color: "#1d7a47" }}>{(s.positive_percentage ?? 0).toFixed(0)}%+</span>
              <span className="text-xs" style={{ color: "#8890aa" }}>/</span>
              <span className="text-xs" style={{ color: "#c0394f" }}>{(s.negative_percentage ?? 0).toFixed(0)}%-</span>
            </div>
          ) : "—"}
        </td>
        <td className="text-xs" style={{ color: "#8890aa" }}>
          <span className="flex items-center gap-1">
            <Calendar size={11} />
            {(post.scraped_at || post.modified || "").slice(0, 10)}
          </span>
        </td>
        <td className="text-xs" style={{ color: "#8890aa" }}>{post.size_kb}KB</td>
        <td>
          {open ? <ChevronUp size={14} style={{ color: "#8890aa" }} /> : <ChevronDown size={14} style={{ color: "#8890aa" }} />}
        </td>
      </tr>

      {open && (
        <tr>
          <td colSpan={8} className="px-4 pb-4 pt-1">
            <div
              className="rounded-xl p-4"
              style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.06)" }}
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {/* Caption / URL */}
                <div className="space-y-3">
                  {post.url && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: "#8890aa" }}>URL</p>
                      <div className="flex items-center gap-2 flex-wrap">
                        <a
                          href={post.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-xs break-all flex items-center gap-1"
                          style={{ color: "#3b6dce" }}
                        >
                          <Globe size={11} />
                          {post.url.slice(0, 80)}…
                        </a>
                        <button
                          onClick={() => onScrapePost(post.url!)}
                          disabled={isRunning}
                          title={isRunning ? "Tunggu scraping selesai dulu" : "Scrape postingan ini"}
                          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-all hover:bg-green-50 shrink-0"
                          style={{ background: "rgba(29,122,71,0.07)", color: "#1d7a47", border: "1px solid rgba(29,122,71,0.2)", opacity: isRunning ? 0.5 : 1, cursor: isRunning ? "not-allowed" : "pointer" }}
                        >
                          <FileText size={12} /> Scrape Post
                        </button>
                      </div>
                    </div>
                  )}
                  {post.caption && (
                    <div>
                      <p className="text-xs font-semibold uppercase tracking-wider mb-1" style={{ color: "#8890aa" }}>Caption</p>
                      <p className="text-sm leading-relaxed" style={{ color: "#4a5070" }}>{post.caption}</p>
                    </div>
                  )}
                  {s && (
                    <div className="space-y-2 pt-1">
                      <SentimentBar label="Positif"    pct={s.positive_percentage ?? 0} color="#1d7a47" />
                      <SentimentBar label="Negatif"    pct={s.negative_percentage ?? 0} color="#c0394f" />
                      <SentimentBar label="Netral"     pct={s.neutral_percentage  ?? 0} color="#8890aa" />
                      <SentimentBar label="Hate Speech"pct={s.hate_percentage     ?? 0} color="#c0394f" />
                      <SentimentBar label="Toxic"      pct={s.toxic_percentage    ?? 0} color="#9e6c0a" />
                    </div>
                  )}
                </div>

                {/* Pie */}
                {pieData.length > 0 && (
                  <div>
                    <p className="text-xs font-semibold uppercase tracking-wider mb-2" style={{ color: "#8890aa" }}>Distribusi</p>
                    <ResponsiveContainer width="100%" height={180}>
                      <PieChart>
                        <Pie data={pieData} cx="50%" cy="50%" innerRadius={40} outerRadius={70} paddingAngle={2} dataKey="value">
                          {pieData.map(e => <Cell key={e.name} fill={PIE_COLORS[e.name] ?? "#8890aa"} stroke="transparent" />)}
                        </Pie>
                        <Tooltip
                          contentStyle={{ background: "white", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 8, fontSize: 11, color: "#1a1c23" }}
                          formatter={(v) => [`${v}`, ""]}
                        />
                        <Legend wrapperStyle={{ fontSize: 10, color: "#8890aa" }} />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Profile row ──────────────────────────────────────────────────────────────
function ProfileRow({ profile, idx }: { profile: RecentProfile; idx: number }) {
  return (
    <tr>
      <td className="text-xs" style={{ color: "#8890aa" }}>{idx + 1}</td>
      <td>
        <div className="flex items-center gap-2">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0 text-xs font-bold text-white"
            style={{ background: "linear-gradient(135deg, #3b6dce, #2193b0)" }}
          >
            {profile.username?.charAt(0).toUpperCase() ?? "?"}
          </div>
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <p className="text-sm font-medium" style={{ color: "#1a1c23" }}>{profile.name || `@${profile.username}`}</p>
              {profile.is_page && (
                <span className="badge" style={{ background: "rgba(59,109,206,0.12)", color: "#3b6dce", border: "1px solid rgba(59,109,206,0.2)", fontSize: 10 }}>
                  Page
                </span>
              )}
            </div>
            <p className="text-xs" style={{ color: "#8890aa" }}>@{profile.username}</p>
          </div>
        </div>
      </td>
      <td className="font-semibold" style={{ color: "#6b5ec7" }}>{fmtNum(profile.followers)}</td>
      <td style={{ color: "#c0394f" }}>{fmtNum(profile.likes)}</td>
      <td className="text-xs" style={{ color: "#8890aa" }}>
        <span className="flex items-center gap-1">
          <Calendar size={11} />
          {(profile.scraped_at || "").slice(0, 10) || "—"}
        </span>
      </td>
      <td className="text-xs truncate max-w-48" style={{ color: "#8890aa" }}>
        {profile.filename}
      </td>
    </tr>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────
export default function ResultsPage() {
  const router = useRouter();
  const { isRunning, setAutoFillUrl } = useScrape();
  const [data, setData]         = useState<DashboardData | null>(null);
  const [loading, setLoading]   = useState(true);
  const [tab, setTab]           = useState<TabType>("posts");
  const [search, setSearch]     = useState("");
  const [error, setError]       = useState<string | null>(null);

  const handleScrapePost = useCallback((url: string) => {
    setAutoFillUrl(url);
    router.push("/scrape/posts");
  }, [setAutoFillUrl, router]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.dashboard();
      if (res.data) setData(res.data);
    } catch {
      setError("Gagal mengambil data hasil scrape dari backend");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const posts = (data?.recent_posts ?? []).filter(p => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (p.caption ?? "").toLowerCase().includes(q) ||
           (p.url ?? "").toLowerCase().includes(q) ||
           p.filename.toLowerCase().includes(q);
  });

  const profiles = (data?.recent_profiles ?? []).filter(p => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (p.username ?? "").toLowerCase().includes(q) ||
           (p.name ?? "").toLowerCase().includes(q) ||
           p.filename.toLowerCase().includes(q);
  });

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-3xl font-bold gradient-text mb-1">Hasil Scrape</h1>
          <p className="text-sm" style={{ color: "#8890aa" }}>
            Lihat dan telusuri semua hasil scraping yang tersimpan
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {tab === "posts" && posts.length > 0 && (
            <>
              <button
                onClick={() => downloadJSON(posts, `fb-results-posts-${new Date().toISOString().slice(0,10)}`)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-purple-50"
                style={{ background: "rgba(107,94,199,0.07)", color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.2)" }}
              >
                <FileText size={13} /> JSON
              </button>
              <button
                onClick={() => downloadCSV(posts, `fb-results-posts-${new Date().toISOString().slice(0,10)}`)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-green-50"
                style={{ background: "rgba(29,122,71,0.07)", color: "#1d7a47", border: "1px solid rgba(29,122,71,0.2)" }}
              >
                <Download size={13} /> CSV
              </button>
            </>
          )}
          {tab === "profiles" && profiles.length > 0 && (
            <>
              <button
                onClick={() => downloadJSON(profiles, `fb-results-profiles-${new Date().toISOString().slice(0,10)}`)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-purple-50"
                style={{ background: "rgba(107,94,199,0.07)", color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.2)" }}
              >
                <FileText size={13} /> JSON
              </button>
              <button
                onClick={() => downloadCSV(profiles, `fb-results-profiles-${new Date().toISOString().slice(0,10)}`)}
                className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-green-50"
                style={{ background: "rgba(29,122,71,0.07)", color: "#1d7a47", border: "1px solid rgba(29,122,71,0.2)" }}
              >
                <Download size={13} /> CSV
              </button>
            </>
          )}
          <button
            onClick={fetchData}
            disabled={loading}
            className="btn-glass flex items-center gap-2 px-4 py-2 text-sm"
          >
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <GlassCard glow="pink">
          <div className="flex gap-3">
            <AlertTriangle size={16} className="text-red-400 shrink-0" />
            <p className="text-sm text-red-300">{error}</p>
          </div>
        </GlassCard>
      )}

      {loading && !data ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner size={40} text="Memuat hasil scrape..." />
        </div>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "File Post",          val: data?.total_post_files ?? 0,    color: "#a855f7", icon: FileText },
              { label: "File Profil",         val: data?.total_profile_files ?? 0, color: "#3b82f6", icon: Users },
              { label: "Profil Dipantau",     val: data?.tracked_profiles ?? 0,   color: "#06b6d4", icon: BarChart2 },
              { label: "Komentar Terakhir",   val: data?.recent_posts?.[0]?.comments_count ?? 0, color: "#22c55e", icon: MessageSquare },
            ].map(({ label, val, color, icon: Icon }) => (
              <GlassCard key={label}>
                <div className="flex items-center gap-3">
                  <div
                    className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
                    style={{ background: `${color}1a`, border: `1px solid ${color}33` }}
                  >
                    <Icon size={16} color={color} />
                  </div>
                  <div>
                    <p className="text-xl font-bold" style={{ color: "#1a1c23" }}>{fmtNum(val)}</p>
                    <p className="text-xs" style={{ color: "#8890aa" }}>{label}</p>
                  </div>
                </div>
              </GlassCard>
            ))}
          </div>

          {/* Tabs + Search */}
          <GlassCard padding="p-0">
            <div
              className="flex items-center justify-between gap-4 p-4 flex-wrap"
              style={{ borderBottom: "1px solid rgba(0,0,0,0.06)" }}
            >
              {/* Tabs */}
              <div className="flex gap-1 p-1 rounded-xl" style={{ background: "rgba(0,0,0,0.03)" }}>
                {(["posts", "profiles"] as TabType[]).map(t => (
                  <button
                    key={t}
                    onClick={() => { setTab(t); setSearch(""); }}
                    className="flex items-center gap-2 px-4 py-1.5 rounded-lg text-sm font-medium transition-all"
                    style={tab === t ? {
                      background: "linear-gradient(135deg, rgba(124,58,237,0.5), rgba(59,130,246,0.4))",
                      color: "white",
                      border: "1px solid rgba(168,85,247,0.4)",
                    } : {
                      color: "#8890aa",
                    }}
                  >
                    {t === "posts" ? <FileText size={13} /> : <Users size={13} />}
                    {t === "posts" ? "Post" : "Profil"}
                    <span
                      className="px-1.5 py-0.5 rounded-full text-xs"
                      style={{ background: "rgba(107,94,199,0.08)", color: "#6b5ec7" }}
                    >
                      {t === "posts" ? data?.total_post_files ?? 0 : data?.total_profile_files ?? 0}
                    </span>
                  </button>
                ))}
              </div>

              {/* Search */}
              <div className="flex items-center gap-2">
                <Filter size={13} style={{ color: "#8890aa" }} />
                <input
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  placeholder={tab === "posts" ? "Cari URL, caption..." : "Cari username, nama..."}
                  className="glass-input px-3 py-1.5 text-xs w-52"
                />
              </div>
            </div>

            {/* Table */}
            <div className="overflow-x-auto">
              {tab === "posts" ? (
                <table className="w-full glass-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Post</th>
                      <th>Komentar</th>
                      <th>Engagement</th>
                      <th>Sentimen</th>
                      <th>Tanggal</th>
                      <th>Ukuran</th>
                      <th></th>
                    </tr>
                  </thead>
                  <tbody>
                    {posts.length === 0 ? (
                      <tr>
                        <td colSpan={8} className="text-center py-10">
                          <p className="text-sm" style={{ color: "#8890aa" }}>
                            {search ? `Tidak ada hasil untuk "${search}"` : "Belum ada post discrape"}
                          </p>
                        </td>
                      </tr>
                    ) : (
                      posts.map((p, i) => <PostRow key={p.filename} post={p} idx={i} onScrapePost={handleScrapePost} isRunning={isRunning} />)
                    )}
                  </tbody>
                </table>
              ) : (
                <table className="w-full glass-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Profil</th>
                      <th>Followers</th>
                      <th>Likes</th>
                      <th>Tanggal</th>
                      <th>File</th>
                    </tr>
                  </thead>
                  <tbody>
                    {profiles.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="text-center py-10">
                          <p className="text-sm" style={{ color: "#8890aa" }}>
                            {search ? `Tidak ada hasil untuk "${search}"` : "Belum ada profil discrape"}
                          </p>
                        </td>
                      </tr>
                    ) : (
                      profiles.map((p, i) => <ProfileRow key={p.filename} profile={p} idx={i} />)
                    )}
                  </tbody>
                </table>
              )}
            </div>

            {/* Footer note */}
            {(tab === "posts" ? data?.total_post_files : data?.total_profile_files) !== undefined &&
             (tab === "posts" ? (data?.total_post_files ?? 0) : (data?.total_profile_files ?? 0)) > 5 && (
              <div
                className="p-3 text-center text-xs"
                style={{ borderTop: "1px solid rgba(0,0,0,0.06)", color: "#8890aa" }}
              >
                <Download size={11} className="inline mr-1" />
                Menampilkan 5 terbaru dari {tab === "posts" ? data?.total_post_files : data?.total_profile_files} file.
                File lengkap tersimpan di folder{" "}
                <code className="font-mono text-purple-400">
                  {tab === "posts" ? "output_facebook/" : "output_fb_profiles/"}
                </code>
              </div>
            )}
          </GlassCard>
        </>
      )}
    </div>
  );
}
