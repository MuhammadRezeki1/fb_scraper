"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Activity, FileText, Users, Database, CheckCircle, XCircle,
  ArrowRight, TrendingUp, Shield, RefreshCw, AlertCircle,
  MessageSquare, Smile, AlertTriangle, Clock, Globe,
  Zap, BarChart2, ChevronRight,
} from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from "recharts";
import GlassCard from "@/components/ui/GlassCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import { api, DashboardData, RecentPost, RecentProfile } from "@/lib/api";

const TXT_SEC = { color: "#4a5070" };
const TXT_MUT = { color: "#8890aa" };
const TXT_PRI = { color: "#1a1c23" };

function fmtNum(n: number | undefined) {
  if (!n) return "0";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function timeAgo(iso: string | undefined) {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  const m = Math.floor(diff / 60000);
  if (m < 1) return "baru saja";
  if (m < 60) return `${m} menit lalu`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h} jam lalu`;
  return `${Math.floor(h / 24)} hari lalu`;
}

function StatCard({ icon: Icon, label, value, sub, color, glow }: {
  icon: React.ElementType; label: string; value: string | number;
  sub?: string; color: string; glow?: "purple" | "blue" | "cyan" | "pink" | "green";
}) {
  return (
    <GlassCard glow={glow}>
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium mb-2 uppercase tracking-wider" style={TXT_MUT}>{label}</p>
          <p className="text-3xl font-bold" style={TXT_PRI}>{value}</p>
          {sub && <p className="text-xs mt-1 truncate" style={TXT_MUT}>{sub}</p>}
        </div>
        <Icon size={28} style={{ color: `${color}60`, marginTop: 4 }} />
      </div>
    </GlassCard>
  );
}

const SENTIMENT_COLORS: Record<string, string> = {
  "Positif": "#1d7a47", "Negatif": "#c0394f", "Netral": "#8890aa",
  "Hate Speech": "#c0394f", "Toxic": "#9e6c0a", "Humor": "#9e6c0a", "Sarkasme": "#6b5ec7",
};

export default function DashboardPage() {
  const [data, setData] = useState<DashboardData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [lastRefresh, setLastRefresh] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      setLoading(true);
      setError("");
      const res = await api.dashboard();
      if (res.data) setData(res.data);
      setLastRefresh(new Date().toISOString());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Gagal load dashboard");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const sentPie = data?.latest_sentiment
    ? [
        { name: "Positif", value: data.latest_sentiment.positive_count },
        { name: "Negatif", value: data.latest_sentiment.negative_count },
        { name: "Netral", value: data.latest_sentiment.neutral_count },
        { name: "Hate Speech", value: data.latest_sentiment.hate_speech_count },
        { name: "Toxic", value: data.latest_sentiment.toxic_count },
        { name: "Humor", value: data.latest_sentiment.humor_count ?? 0 },
      ].filter(d => d.value > 0)
    : [];

  const profileBar = (data?.top_profiles ?? []).slice(0, 10).map(p => ({
    name: p.username,
    Followers: p.followers,
    Likes: p.likes,
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-3xl font-bold gradient-text mb-1" style={{ fontFamily: "var(--font-sora)" }}>Dashboard</h1>
          <p className="text-sm" style={TXT_MUT}>Monitor scraper Facebook secara real-time</p>
        </div>
        <div className="flex items-center gap-3">
          {lastRefresh && (
            <span className="flex items-center gap-1 text-xs" style={TXT_MUT}>
              <Clock size={11} /> {timeAgo(lastRefresh)}
            </span>
          )}
          <button onClick={fetchData} disabled={loading}
            className="btn-glass flex items-center gap-2 px-4 py-2 text-sm">
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      {error && (
        <GlassCard glow="pink">
          <div className="flex items-center gap-3">
            <AlertCircle size={18} style={{ color: "#c0394f" }} />
            <p className="text-sm" style={{ color: "#c0394f" }}>{error}</p>
          </div>
        </GlassCard>
      )}

      {loading && !data && (
        <GlassCard>
          <LoadingSpinner text="Memuat dashboard..." />
        </GlassCard>
      )}

      {data && (
        <>
          {/* Stats */}
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
            <StatCard icon={FileText} label="Total Post Files" value={fmtNum(data.total_post_files)} color="#6b5ec7" glow="purple" />
            <StatCard icon={Users} label="Total Profile Files" value={fmtNum(data.total_profile_files)} color="#3b6dce" glow="blue" />
            <StatCard icon={Database} label="Tracked Profiles" value={fmtNum(data.tracked_profiles)} color="#2193b0" glow="cyan" />
            <StatCard icon={Activity} label="Session" value={data.session_valid ? "Aktif" : "Invalid"} color="#1d7a47" glow={data.session_valid ? "green" : "pink"} />
            <StatCard icon={Shield} label="Login" value={data.is_logged_in ? "Aktif" : "Belum Login"} color="#3b6dce" />
          </div>

          {/* Sentiment + Top Profiles */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <GlassCard>
              <h3 className="font-semibold mb-1" style={TXT_PRI}>Sentimen Terbaru</h3>
              <p className="text-xs mb-4" style={TXT_MUT}>Distribusi dari scrape post paling baru</p>
              {sentPie.length > 0 ? (
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <Pie data={sentPie} cx="50%" cy="50%" innerRadius={45} outerRadius={85} paddingAngle={2} dataKey="value">
                      {sentPie.map(e => <Cell key={e.name} fill={SENTIMENT_COLORS[e.name] ?? "#8890aa"} stroke="transparent" />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "white", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 10, fontSize: 12 }} formatter={(v) => [`${v} komentar`, ""]} />
                    <Legend wrapperStyle={{ fontSize: 11, color: TXT_MUT.color }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-center py-8">
                  <BarChart2 size={32} className="mx-auto mb-2" style={{ color: "#8890aa", opacity: 0.3 }} />
                  <p className="text-sm" style={TXT_MUT}>Belum ada data sentimen</p>
                </div>
              )}
            </GlassCard>

            <GlassCard>
              <h3 className="font-semibold mb-1" style={TXT_PRI}>Top Profiles</h3>
              <p className="text-xs mb-4" style={TXT_MUT}>Berdasarkan jumlah followers</p>
              {profileBar.length > 0 ? (
                <ResponsiveContainer width="100%" height={250}>
                  <BarChart data={profileBar} margin={{ top: 5, right: 10, left: -10, bottom: 5 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
                    <XAxis dataKey="name" tick={{ fontSize: 11, fill: "#8890aa" }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 10, fill: "#8890aa" }} tickLine={false} axisLine={false} tickFormatter={v => fmtNum(v)} />
                    <Tooltip contentStyle={{ background: "white", border: "1px solid rgba(0,0,0,0.1)", borderRadius: 10, fontSize: 11 }}
                      formatter={(v) => [fmtNum(Number(v ?? 0)), ""]} />
                    <Bar dataKey="Followers" fill="#6b5ec7" radius={[4, 4, 0, 0]} />
                    <Bar dataKey="Likes" fill="#3b6dce" radius={[4, 4, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              ) : (
                <div className="text-center py-8">
                  <Users size={32} className="mx-auto mb-2" style={{ color: "#8890aa", opacity: 0.3 }} />
                  <p className="text-sm" style={TXT_MUT}>Belum ada profil dipantau</p>
                </div>
              )}
            </GlassCard>
          </div>

          {/* Recent Posts */}
          <GlassCard padding="p-0">
            <div className="p-4 flex items-center justify-between" style={{ borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
              <h3 className="font-semibold flex items-center gap-2 text-sm" style={TXT_PRI}>
                <FileText size={15} style={{ color: "#6b5ec7" }} /> Post Terbaru
              </h3>
              <Link href="/scrape/posts" className="flex items-center gap-1 text-xs" style={{ color: "#6b5ec7" }}>
                Lihat semua <ChevronRight size={12} />
              </Link>
            </div>
            <div className="divide-y" style={{ borderColor: "rgba(0,0,0,0.04)" }}>
              {(data?.recent_posts ?? []).length === 0 ? (
                <p className="text-sm text-center py-6" style={TXT_MUT}>Belum ada post discrape</p>
              ) : (
                data.recent_posts.slice(0, 8).map((p, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: "rgba(107,94,199,0.08)" }}>
                      <FileText size={14} style={{ color: "#6b5ec7" }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate" style={TXT_PRI}>{p.caption || "(tanpa caption)"}</p>
                      {p.comments_count !== undefined && <span className="text-xs" style={TXT_MUT}>{p.comments_count} komentar</span>}
                      <span className="text-xs ml-2" style={TXT_MUT}>{timeAgo(p.scraped_at || p.modified)}</span>
                    </div>
                    <span className="text-xs shrink-0" style={TXT_MUT}>{p.size_kb}KB</span>
                  </div>
                ))
              )}
            </div>
          </GlassCard>

          {/* Recent Profiles */}
          <GlassCard padding="p-0">
            <div className="p-4 flex items-center justify-between" style={{ borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
              <h3 className="font-semibold flex items-center gap-2 text-sm" style={TXT_PRI}>
                <Users size={15} style={{ color: "#3b6dce" }} /> Profil Terbaru
              </h3>
              <Link href="/scrape/profiles" className="flex items-center gap-1 text-xs" style={{ color: "#6b5ec7" }}>
                Lihat semua <ChevronRight size={12} />
              </Link>
            </div>
            <div className="divide-y" style={{ borderColor: "rgba(0,0,0,0.04)" }}>
              {(data?.recent_profiles ?? []).length === 0 ? (
                <p className="text-sm text-center py-6" style={TXT_MUT}>Belum ada profil discrape</p>
              ) : (
                data.recent_profiles.slice(0, 8).map((p, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3">
                    <div className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0" style={{ background: "rgba(59,109,206,0.08)" }}>
                      <UserIcon size={14} style={{ color: "#3b6dce" }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium" style={TXT_PRI}>{p.name || p.username || "—"}</p>
                      <span className="text-xs" style={TXT_MUT}>@{p.username} · {fmtNum(p.followers)} followers</span>
                    </div>
                    <span className="text-xs shrink-0" style={TXT_MUT}>{timeAgo(p.scraped_at)}</span>
                  </div>
                ))
              )}
            </div>
          </GlassCard>

          {/* Quick Actions */}
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-widest mb-3" style={TXT_MUT}>Aksi Cepat</h2>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {[
                { href: "/scrape/posts", icon: FileText, label: "Scrape Post", color: "#6b5ec7" },
                { href: "/scrape/profiles", icon: Users, label: "Scrape Profil", color: "#3b6dce" },
                { href: "/monitor/keyword", icon: Activity, label: "Keyword Monitor", color: "#2193b0" },
                { href: "/analytics", icon: TrendingUp, label: "Growth Analytics", color: "#1d7a47" },
              ].map(({ href, icon: Icon, label, color }) => (
                <Link key={href} href={href}>
                  <GlassCard>
                    <div className="flex flex-col items-center gap-2 py-2">
                      <Icon size={22} style={{ color: `${color}80` }} />
                      <span className="text-xs font-medium" style={TXT_SEC}>{label}</span>
                    </div>
                  </GlassCard>
                </Link>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

// Inline to avoid import conflict with lucide's User
function UserIcon({ size, style }: { size: number; style: React.CSSProperties }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={style}>
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}