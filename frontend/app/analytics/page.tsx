"use client";

import { useEffect, useState, useCallback } from "react";
import {
  TrendingUp, TrendingDown, Minus, Users, Heart,
  FileText, RefreshCw, ChevronDown, ChevronUp,
  AlertTriangle, Calendar, BarChart3,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import GlassCard from "@/components/ui/GlassCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import { api, TrackedUser, GrowthData, HistorySnapshot } from "@/lib/api";

function fmtNum(n: number) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

function GrowthBadge({ pct }: { pct: number }) {
  if (pct > 0) return (
    <span className="flex items-center gap-1 text-xs font-semibold" style={{ color: "#1d7a47" }}>
      <TrendingUp size={12} />+{pct.toFixed(2)}%
    </span>
  );
  if (pct < 0) return (
    <span className="flex items-center gap-1 text-xs font-semibold" style={{ color: "#c0394f" }}>
      <TrendingDown size={12} />{pct.toFixed(2)}%
    </span>
  );
  return (
    <span className="flex items-center gap-1 text-xs font-semibold" style={{ color: "#8890aa" }}>
      <Minus size={12} />0%
    </span>
  );
}

function GrowthMetricCard({
  icon: Icon, label, metric, color,
}: {
  icon: React.ElementType;
  label: string;
  metric: GrowthData["followers"];
  color: string;
}) {
  return (
    <div
      className="rounded-xl p-4"
      style={{ background: `${color}0d`, border: `1px solid ${color}33` }}
    >
      <div className="flex items-center gap-2 mb-3">
        <Icon size={14} color={color} />
        <span className="text-xs font-semibold uppercase tracking-wider" style={{ color }}>
          {label}
        </span>
      </div>
      <p className="text-2xl font-bold mb-1" style={{ color: "#1a1c23" }}>{fmtNum(metric.end)}</p>
      <div className="flex items-center justify-between text-xs" style={{ color: "#8890aa" }}>
        <span>{fmtNum(metric.start)} → {fmtNum(metric.end)}</span>
        <GrowthBadge pct={metric.growth_pct} />
      </div>
      <p className="text-xs mt-1" style={{ color: "#8890aa" }}>
        +{fmtNum(metric.avg_per_day)}/hari
      </p>
    </div>
  );
}

export default function AnalyticsPage() {
  const [users, setUsers]       = useState<TrackedUser[]>([]);
  const [loading, setLoading]   = useState(true);
  const [selected, setSelected] = useState<string | null>(null);
  const [days, setDays]         = useState(30);
  const [growth, setGrowth]     = useState<GrowthData | null>(null);
  const [growthLoading, setGL]  = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const fetchUsers = async () => {
    setLoading(true);
    try {
      const res = await api.profiles.list();
      setUsers(res.data?.users ?? []);
    } catch {
      setError("Gagal mengambil daftar profil");
    } finally {
      setLoading(false);
    }
  };

  const fetchGrowth = useCallback(async (username: string) => {
    setGL(true);
    setGrowth(null);
    try {
      const res = await api.profiles.growth(username, days);
      if (res.data) setGrowth(res.data);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Gagal ambil data growth");
    } finally {
      setGL(false);
    }
  }, [days]);

  useEffect(() => { fetchUsers(); }, []);

  useEffect(() => {
    if (selected) fetchGrowth(selected);
  }, [selected, fetchGrowth]);

  const chartData = growth?.history.map((h: HistorySnapshot) => ({
    date:      h.scraped_at.slice(0, 10),
    Followers: h.followers,
    Likes:     h.likes,
    Posts:     h.posts,
  })) ?? [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold gradient-text mb-1">Analitik Growth</h1>
          <p className="text-sm" style={{ color: "#8890aa" }}>
            Pantau pertumbuhan profil Facebook dari waktu ke waktu
          </p>
        </div>
        <button
          onClick={fetchUsers}
          disabled={loading}
          className="btn-glass flex items-center gap-2 px-4 py-2 text-sm"
        >
          <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {error && (
        <GlassCard glow="pink">
          <div className="flex gap-3">
            <AlertTriangle size={16} style={{ color: "#c0394f" }} className="shrink-0" />
            <p className="text-sm" style={{ color: "#c0394f" }}>{error}</p>
          </div>
        </GlassCard>
      )}

      {loading ? (
        <div className="flex justify-center py-20">
          <LoadingSpinner size={40} text="Memuat data profil..." />
        </div>
      ) : users.length === 0 ? (
        <GlassCard>
          <div className="text-center py-10">
            <BarChart3 size={40} className="mx-auto mb-3" style={{ color: "#6b5ec7", opacity: 0.5 }} />
            <p className="font-semibold mb-1" style={{ color: "#1a1c23" }}>Belum ada profil dipantau</p>
            <p className="text-sm" style={{ color: "#8890aa" }}>
              Scrape profil dengan opsi "Simpan tracking" untuk mulai memantau growth.
            </p>
          </div>
        </GlassCard>
      ) : (
        <>
          {/* Profiles list */}
          <GlassCard padding="p-0">
            <div className="p-5">
              <h2 className="font-semibold flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <Users size={16} style={{ color: "#3b6dce" }} />
                Profil Dipantau ({users.length})
              </h2>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full glass-table">
                <thead>
                  <tr>
                    <th>Username</th>
                    <th>Followers</th>
                    <th>Likes</th>
                    <th>Posts</th>
                    <th>Data Points</th>
                    <th>Terakhir</th>
                    <th>Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {users.map(u => (
                    <tr
                      key={u.username}
                      className={selected === u.username ? "bg-purple-500/10" : ""}
                    >
                      <td>
                        <div className="flex items-center gap-2">
                          <div
                            className="w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold text-white shrink-0"
                            style={{ background: "linear-gradient(135deg, #6b5ec7, #3b6dce)" }}
                          >
                            {u.username.charAt(0).toUpperCase()}
                          </div>
                          <span className="font-medium text-sm" style={{ color: "#1a1c23" }}>@{u.username}</span>
                          {u.is_page && (
                            <span className="badge" style={{ background: "rgba(59,109,206,0.12)", color: "#3b6dce", border: "1px solid rgba(59,109,206,0.2)" }}>
                              Page
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="font-semibold" style={{ color: "#6b5ec7" }}>{fmtNum(u.current_followers)}</td>
                      <td style={{ color: "#c0394f" }}>{fmtNum(u.current_likes)}</td>
                      <td style={{ color: "#4a5070" }}>{u.current_posts}</td>
                      <td>
                        <span className="badge badge-neutral">{u.data_points} snapshots</span>
                      </td>
                      <td className="text-xs" style={{ color: "#8890aa" }}>
                        {u.last_tracked?.slice(0, 10) ?? "—"}
                      </td>
                      <td>
                        <button
                          onClick={() => setSelected(selected === u.username ? null : u.username)}
                          className="btn-glass flex items-center gap-1 px-3 py-1.5 text-xs"
                        >
                          {selected === u.username ? (
                            <><ChevronUp size={12} /> Tutup</>
                          ) : (
                            <><ChevronDown size={12} /> Detail</>
                          )}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </GlassCard>

          {/* Growth detail panel */}
          {selected && (
            <div className="space-y-4">
              <div className="flex items-center justify-between flex-wrap gap-3">
                <h2 className="font-semibold flex items-center gap-2" style={{ color: "#1a1c23" }}>
                  <TrendingUp size={16} style={{ color: "#2193b0" }} />
                  Growth @{selected}
                </h2>
                <div className="flex items-center gap-2">
                  <Calendar size={14} style={{ color: "#8890aa" }} />
                  <select
                    value={days}
                    onChange={e => setDays(Number(e.target.value))}
                    className="glass-input px-3 py-1.5 text-xs"
                  >
                    {[7, 14, 30, 60, 90].map(d => (
                      <option key={d} value={d}>
                        {d} hari
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {growthLoading ? (
                <GlassCard>
                  <div className="flex justify-center py-8">
                    <LoadingSpinner size={32} text="Menganalisis data growth..." />
                  </div>
                </GlassCard>
              ) : growth ? (
                <>
                  {/* Period info */}
                  <GlassCard>
                    <div className="flex items-center gap-4 flex-wrap text-xs" style={{ color: "#8890aa" }}>
                      <span className="flex items-center gap-1">
                        <Calendar size={12} />
                        {growth.period.start_date.slice(0, 10)} → {growth.period.end_date.slice(0, 10)}
                      </span>
                      <span>{growth.period.days} hari</span>
                      <span>{growth.period.data_points} data points</span>
                    </div>
                  </GlassCard>

                  {/* Metrics */}
                  <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
                    <GrowthMetricCard icon={Users}    label="Followers" metric={growth.followers} color="#6b5ec7" />
                    <GrowthMetricCard icon={Users}    label="Following" metric={growth.following} color="#3b6dce" />
                    <GrowthMetricCard icon={Heart}    label="Likes"     metric={growth.likes}     color="#c0394f" />
                    <GrowthMetricCard icon={FileText} label="Posts"     metric={growth.posts}     color="#1d7a47" />
                  </div>

                  {/* Line chart */}
                  {chartData.length >= 2 && (
                    <GlassCard>
                      <h3 className="font-semibold mb-4 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                        <TrendingUp size={16} style={{ color: "#6b5ec7" }} />
                        Grafik Pertumbuhan
                      </h3>
                      <ResponsiveContainer width="100%" height={300}>
                        <LineChart data={chartData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.06)" />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 11, fill: "#8890aa" }}
                            tickLine={false}
                            axisLine={{ stroke: "rgba(0,0,0,0.08)" }}
                          />
                          <YAxis
                            tick={{ fontSize: 11, fill: "#8890aa" }}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={v => fmtNum(v)}
                          />
                          <Tooltip
                            contentStyle={{
                              background: "white",
                              border: "1px solid rgba(0,0,0,0.1)",
                              borderRadius: "10px",
                              fontSize: 12,
                              color: "#1a1c23",
                            }}
                            formatter={(v) => [fmtNum(Number(v ?? 0)), ""]}
                          />
                          <Legend wrapperStyle={{ fontSize: 12, color: "#8890aa" }} />
                          <Line type="monotone" dataKey="Followers" stroke="#6b5ec7" strokeWidth={2} dot={{ r: 3, fill: "#6b5ec7" }} />
                          <Line type="monotone" dataKey="Likes"     stroke="#c0394f" strokeWidth={2} dot={{ r: 3, fill: "#c0394f" }} />
                          <Line type="monotone" dataKey="Posts"     stroke="#1d7a47" strokeWidth={2} dot={{ r: 3, fill: "#1d7a47" }} />
                        </LineChart>
                      </ResponsiveContainer>
                    </GlassCard>
                  )}

                  {/* History table */}
                  <GlassCard padding="p-0">
                    <div className="p-5">
                      <h3 className="font-semibold flex items-center gap-2" style={{ color: "#1a1c23" }}>
                        <Calendar size={16} style={{ color: "#3b6dce" }} />
                        Riwayat Snapshot
                      </h3>
                    </div>
                    <div className="overflow-x-auto">
                      <table className="w-full glass-table">
                        <thead>
                          <tr>
                            <th>Tanggal</th>
                            <th>Followers</th>
                            <th>Following</th>
                            <th>Likes</th>
                            <th>Posts</th>
                          </tr>
                        </thead>
                        <tbody>
                          {growth.history.slice().reverse().map((h, i) => (
                            <tr key={i}>
                              <td className="text-xs" style={{ color: "#8890aa" }}>
                                {h.scraped_at.slice(0, 16).replace("T", " ")}
                              </td>
                              <td className="font-semibold" style={{ color: "#6b5ec7" }}>{fmtNum(h.followers)}</td>
                              <td style={{ color: "#3b6dce" }}>{fmtNum(h.following)}</td>
                              <td style={{ color: "#c0394f" }}>{fmtNum(h.likes)}</td>
                              <td style={{ color: "#4a5070" }}>{h.posts}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </GlassCard>
                </>
              ) : null}
            </div>
          )}
        </>
      )}
    </div>
  );
}