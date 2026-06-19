"use client";
import { useState, useMemo, useEffect } from "react";
import { api, KeywordResult, KeywordHit, CommentItem, MonitorSort, MonitorOptions } from "@/lib/api";
import {
  Search, Loader2, ExternalLink, FileText, Users, Video,
  Grid3x3, Hash, TrendingUp, ChevronDown, ChevronUp, MessageSquare,
  Heart, Eye, Image as ImageIcon,
} from "lucide-react";
import GlassCard from "@/components/ui/GlassCard";
import DownloadButton from "@/components/ui/DownloadButton";
import { useScrape } from "@/contexts/ScrapeContext";
import { usePersistState } from "@/hooks/usePersistState";

type MonitorMode = "keyword" | "hashtag" | "trending";
type HitWithComments = KeywordHit & { top_comments?: CommentItem[]; other_comments?: CommentItem[]; comments_scraped_count?: number; comments_scrape_failed?: boolean };

/** Group items by type and return ordered keys */
function groupByType(items: KeywordHit[]): { posts: KeywordHit[]; videos: KeywordHit[]; pages: KeywordHit[]; groups: KeywordHit[]; other: KeywordHit[] } {
  const groups = { posts: [] as KeywordHit[], videos: [] as KeywordHit[], pages: [] as KeywordHit[], groups: [] as KeywordHit[], other: [] as KeywordHit[] };
  for (const item of items) {
    const t = item.type?.toLowerCase() || "";
    if (t === "posts" || t === "post") groups.posts.push(item);
    else if (t === "videos" || t === "video" || t === "reel" || t === "reels") groups.videos.push(item);
    else if (t === "pages" || t === "page") groups.pages.push(item);
    else if (t === "groups" || t === "group") groups.groups.push(item);
    else groups.other.push(item);
  }
  return groups;
}

const GROUP_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  posts:   { label: "Postingan", color: "#3b6dce", icon: <FileText size={16} /> },
  videos:  { label: "Video/Reels", color: "#c0394f", icon: <Video size={16} /> },
  pages:   { label: "Halaman", color: "#1d7a47", icon: <Users size={16} /> },
  groups:  { label: "Grup", color: "#9e6c0a", icon: <Grid3x3 size={16} /> },
  other:   { label: "Lainnya", color: "#8890aa", icon: <Search size={16} /> },
};

function metric(hit: KeywordHit, sortBy: MonitorSort) {
  if (sortBy === "likes") return hit.likes_count ?? hit.like_count ?? 0;
  if (sortBy === "comments") return hit.comments_count ?? 0;
  if (sortBy === "views") return hit.views_count ?? 0;
  if (sortBy === "shares") return hit.shares_count ?? 0;
  if (sortBy === "recent") return hit.timestamp ? Date.parse(hit.timestamp) || 0 : 0;
  return hit.engagement_score ?? ((hit.likes_count ?? hit.like_count ?? 0) + (hit.comments_count ?? 0) * 2 + (hit.views_count ?? 0));
}

function sortHits(items: KeywordHit[], sortBy: MonitorSort) {
  return [...items].sort((a, b) => metric(b, sortBy) - metric(a, sortBy));
}

function hitImages(hit: KeywordHit) {
  return (hit.media_urls?.length ? hit.media_urls : hit.images ?? []).filter(Boolean);
}

/** CommentSection: shows top_comments + toggle for other_comments */
function CommentSection({ post }: { post: HitWithComments }) {
  const [expanded, setExpanded] = useState(false);
  if (post.comments_scrape_failed) return <div className="mt-3 p-2 rounded-lg text-xs" style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.12)", color: "#c0394f" }}>Komentar gagal di-scrape</div>;
  if (!post.top_comments?.length) return null;
  const total = post.comments_scraped_count || 0;
  const otherCount = total - post.top_comments.length;
  return (
    <div className="mt-3 space-y-2">
      <div className="flex items-center gap-2 text-xs font-semibold" style={{ color: "#4a5070" }}><MessageSquare size={14} />Top Komentar ({post.top_comments.length}{otherCount > 0 ? ` dari ${total}` : ""})</div>
      {post.top_comments.map((c, ci) => (
        <div key={ci} className="p-2 rounded-lg text-xs" style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.05)" }}>
          <div className="flex items-center gap-2 mb-0.5"><span className="font-medium" style={{ color: "#1a1c23" }}>{c.comment_author}</span><span style={{ color: "#8890aa" }}>{c.comment_timestamp}</span></div>
          <p style={{ color: "#4a5070" }}>{c.comment_text.slice(0, 300)}</p>
          <span style={{ color: "#8890aa" }}>\u2764 {c.comment_likes}</span>
        </div>
      ))}
      {otherCount > 0 && (
        <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-1 text-xs px-2 py-1 rounded-lg transition-all hover:bg-black/5" style={{ color: "#6b5ec7" }}>
          {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}{expanded ? "Sembunyikan" : `Lihat semua komentar (${otherCount})`}
        </button>
      )}
      {expanded && post.other_comments?.map((c, ci) => (
        <div key={`o-${ci}`} className="p-2 rounded-lg text-xs" style={{ background: "rgba(0,0,0,0.02)", border: "1px solid rgba(0,0,0,0.05)", marginLeft: "1rem" }}>
          <div className="flex items-center gap-2 mb-0.5"><span className="font-medium" style={{ color: "#1a1c23" }}>{c.comment_author}</span><span style={{ color: "#8890aa" }}>{c.comment_timestamp}</span></div>
          <p style={{ color: "#4a5070" }}>{c.comment_text.slice(0, 300)}</p>
          <span style={{ color: "#8890aa" }}>\u2764 {c.comment_likes}</span>
        </div>
      ))}
    </div>
  );
}

export default function KeywordMonitoringPage() {
  const { job, isRunning, start, finish, fail } = useScrape();
  const [mode, setMode] = usePersistState<MonitorMode>("kw-mode", "keyword");
  const [keyword, setKeyword] = usePersistState("kw-keyword", "");
  const [types, setTypes] = usePersistState<string[]>("kw-types", ["posts"]);
  const [hashtag, setHashtag] = usePersistState("kw-hashtag", "");
  const [maxResults, setMaxResults] = useState(1000);
  const [maxCommentsPerPost, setMaxCommentsPerPost] = useState(0);
  const [sortBy, setSortBy] = useState<MonitorSort>("engagement");
  const [minLikes, setMinLikes] = useState(0);
  const [minComments, setMinComments] = useState(0);
  const [minViews, setMinViews] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeTab, setActiveTab] = useState<string>("all");
  const [cachedResult, setCachedResult] = usePersistState<KeywordResult | null>("keyword-result", null);

  const ctxResult = job?.type === "keyword" && job.status === "done" ? job.keywordResult : null;
  const scrapeErr = job?.type === "keyword" && job.status === "error" ? job.error : null;
  const isMyJob = job?.type === "keyword";
  const isMyRun = isRunning && isMyJob;
  const otherRun = isRunning && !isMyJob;

  // Sync context result to cache only when done (not when running)
  useEffect(() => { if (ctxResult) setCachedResult(ctxResult); }, [ctxResult, setCachedResult]);

  const displayResult = ctxResult ?? cachedResult;
  const allResults = useMemo(() => sortHits(displayResult?.results ?? [], sortBy), [displayResult?.results, sortBy]);
  const groups = useMemo(() => groupByType(allResults), [allResults]);

  const typeOptions = [
    { value: "posts", label: "Postingan", icon: FileText },
    { value: "videos", label: "Video/Reels", icon: Video },
    { value: "pages", label: "Halaman", icon: Users },
    { value: "groups", label: "Grup", icon: Grid3x3 },
  ];

  const toggleType = (val: string) => {
    setTypes(prev => prev.includes(val) ? prev.filter(t => t !== val) : [...prev, val]);
  };

  const handleScrape = async () => {
    if (loading || isRunning) return;
    setLoading(true); setError(""); setCachedResult(null);
    setActiveTab("all");
    try {
      let res;
      const options: MonitorOptions = {
        sort_by: sortBy,
        min_likes: minLikes > 0 ? minLikes : null,
        min_comments: minComments > 0 ? minComments : null,
        min_views: minViews > 0 ? minViews : null,
        max_comments_per_post: maxCommentsPerPost,
        top_comments_count: 5,
      };
      if (mode === "keyword") {
        if (!keyword.trim()) throw new Error("Keyword wajib diisi");
        start("keyword", keyword);
        res = await api.monitor.keyword(keyword, maxResults, types, options);
      } else if (mode === "hashtag") {
        if (!hashtag.trim()) throw new Error("Hashtag wajib diisi");
        start("keyword", `#${hashtag}`);
        res = await api.monitor.hashtag(hashtag, maxResults, options);
      } else {
        start("keyword", keyword || "trending");
        res = await api.monitor.trending(maxResults, sortBy, keyword, types, options);
      }
      const data = res.data ?? null;
      setCachedResult(data);
      finish({ keywordResult: data, elapsed: undefined });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Terjadi kesalahan";
      setError(message);
      fail(message || "Gagal monitoring");
    } finally { setLoading(false); }
  };

  // Warning hanya muncul ketika scraping benar-benar berjalan, bukan saat ubah input
  const showCommentWarning = isMyRun && maxCommentsPerPost > 0 && maxResults > 50;
  const tabKeys = ["all", ...Object.keys(groups).filter(k => groups[k as keyof typeof groups].length > 0)];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold gradient-text flex items-center gap-2"><Search size={24} style={{ color: "#6b5ec7" }} />Keyword Monitoring</h1>
        <p className="text-sm mt-1" style={{ color: "#8890aa" }}>Social listening: Cari postingan berdasarkan keyword, hashtag, atau trending topics.</p>
      </div>

      {otherRun && (
        <GlassCard glow="purple">
          <div className="flex items-center gap-3"><Loader2 size={15} className="animate-spin shrink-0" style={{ color: "#6b5ec7" }} /><p className="text-sm" style={{ color: "#6b5ec7" }}>Scraping lain sedang berjalan ({job?.label}).</p></div>
        </GlassCard>
      )}

      {/* Mode Tabs */}
      <div className="glass rounded-2xl p-2 flex gap-2">
        {(["keyword", "hashtag", "trending"] as MonitorMode[]).map(m => {
          const active = mode === m;
          const Icon = m === "keyword" ? Search : m === "hashtag" ? Hash : TrendingUp;
          return (
            <button key={m} onClick={() => setMode(m)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium transition-all ${active ? "bg-purple-100 text-purple-700 shadow-sm" : "hover:bg-black/5"}`}
              style={{ color: active ? "#6b5ec7" : "#4a5070" }}>
              <Icon size={16} />{m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          );
        })}
      </div>

      {/* Form */}
      <div className="glass rounded-2xl p-6 space-y-4">
        {mode === "keyword" && (
          <>
            <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Keyword</label><input type="text" value={keyword} onChange={e => setKeyword(e.target.value)} placeholder='Contoh: "Pertamina"' className="glass-input w-full px-4 py-3 text-sm" disabled={isMyRun} /></div>
            <div><label className="text-sm font-medium mb-2 block" style={{ color: "#4a5070" }}>Tipe Konten</label><div className="flex flex-wrap gap-2">{typeOptions.map(opt => { const a = types.includes(opt.value); const I = opt.icon; return (<button key={opt.value} onClick={() => toggleType(opt.value)} disabled={isMyRun} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all ${a ? "bg-purple-100 text-purple-700 shadow-sm" : "bg-black/5 hover:bg-black/10"}`} style={{ color: a ? "#6b5ec7" : "#4a5070" }}><I size={16} />{opt.label}</button>); })}</div></div>
          </>
        )}
        {mode === "hashtag" && (
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Hashtag</label><input type="text" value={hashtag} onChange={e => setHashtag(e.target.value)} placeholder='Contoh: "jokowi" (tanpa #)' className="glass-input w-full px-4 py-3 text-sm" disabled={isMyRun} /></div>
        )}
        {mode === "trending" && (
          <>
            <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Keyword (Opsional)</label><input type="text" value={keyword} onChange={e => setKeyword(e.target.value)} placeholder='Kosongkan untuk semua trending' className="glass-input w-full px-4 py-3 text-sm" disabled={isMyRun} /></div>
            <div><label className="text-sm font-medium mb-2 block" style={{ color: "#4a5070" }}>Tipe Konten</label><div className="flex flex-wrap gap-2">{typeOptions.map(opt => { const a = types.includes(opt.value); const I = opt.icon; return (<button key={opt.value} onClick={() => toggleType(opt.value)} disabled={isMyRun} className={`flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all ${a ? "bg-pink-100 text-pink-700 shadow-sm" : "bg-black/5 hover:bg-black/10"}`} style={{ color: a ? "#c0394f" : "#4a5070" }}><I size={16} />{opt.label}</button>); })}</div></div>
          </>
        )}
        <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-6 gap-4">
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Maks Hasil</label><input type="number" value={maxResults} onChange={e => setMaxResults(Math.min(1000, Math.max(10, parseInt(e.target.value) || 10)))} disabled={isMyRun} className="glass-input w-full px-4 py-2 text-sm" /></div>
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Urutkan</label><select value={sortBy} onChange={e => setSortBy(e.target.value as MonitorSort)} disabled={isMyRun} className="glass-input w-full px-4 py-2 text-sm"><option value="engagement">Engagement</option><option value="likes">Like terbanyak</option><option value="comments">Komentar terbanyak</option><option value="views">Views terbanyak</option><option value="recent">Terbaru</option></select></div>
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Min Like</label><input type="number" value={minLikes} onChange={e => setMinLikes(Math.max(0, parseInt(e.target.value) || 0))} disabled={isMyRun} className="glass-input w-full px-4 py-2 text-sm" /></div>
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Min Komentar</label><input type="number" value={minComments} onChange={e => setMinComments(Math.max(0, parseInt(e.target.value) || 0))} disabled={isMyRun} className="glass-input w-full px-4 py-2 text-sm" /></div>
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Min Views</label><input type="number" value={minViews} onChange={e => setMinViews(Math.max(0, parseInt(e.target.value) || 0))} disabled={isMyRun} className="glass-input w-full px-4 py-2 text-sm" /></div>
          <div><label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Komentar per Post</label><input type="number" value={maxCommentsPerPost} onChange={e => setMaxCommentsPerPost(Math.min(50, Math.max(0, parseInt(e.target.value) || 0)))} disabled={isMyRun} className="glass-input w-full px-4 py-2 text-sm" /><p className="text-xs mt-1" style={{ color: "#8890aa" }}>0 = skip</p></div>
        </div>
        {showCommentWarning && <div className="p-3 rounded-xl text-xs flex items-center gap-2" style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.15)", color: "#c0394f" }}><Loader2 size={12} className="animate-spin shrink-0" />Scraping komentar untuk banyak post akan menambah waktu signifikan</div>}
        <button onClick={handleScrape} disabled={isRunning || loading} className="btn-primary w-full flex items-center justify-center gap-2 py-3">{isMyRun ? <Loader2 size={20} className="animate-spin" /> : <Search size={20} />}{isMyRun ? "Sedang Monitoring..." : `Mulai ${mode === "keyword" ? "Keyword" : mode === "hashtag" ? "Hashtag" : "Trending"} Monitoring`}</button>
        {isMyRun && <div className="mt-3 p-3 rounded-xl flex items-center gap-2 text-xs" style={{ background: "rgba(107,94,199,0.06)", border: "1px solid rgba(107,94,199,0.15)", color: "#6b5ec7" }}><Loader2 size={12} className="animate-spin shrink-0" />Monitoring berjalan...</div>}
      </div>

      {((error || scrapeErr) || (job?.status === "error" && isMyJob)) && <div className="p-4 rounded-xl" style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.15)", color: "#c0394f" }}>{scrapeErr || error}</div>}

      {displayResult && allResults.length > 0 && (
        <>
          {/* Filter Tabs Per Type */}
          <div className="glass rounded-2xl p-2 flex gap-1 flex-wrap">
            {tabKeys.map(k => {
              const count = k === "all" ? allResults.length : groups[k as keyof typeof groups]?.length || 0;
              const meta = k === "all" ? { label: "Semua", color: "#6b5ec7", icon: <Search size={16} /> } : GROUP_META[k] || { label: k, color: "#8890aa", icon: <Search size={16} /> };
              const active = activeTab === k;
              return (
                <button key={k} onClick={() => setActiveTab(k)}
                  className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all ${active ? "shadow-sm" : "hover:bg-black/5"}`}
                  style={{ background: active ? `${meta.color}15` : "transparent", color: active ? meta.color : "#4a5070", border: active ? `1px solid ${meta.color}30` : "1px solid transparent" }}>
                  {meta.icon}<span>{meta.label}</span><span className="opacity-60">({count})</span>
                </button>
              );
            })}
          </div>

          {/* Download button */}
          <div className="flex justify-end"><DownloadButton data={allResults} filename={`fb-monitor-${displayResult.keyword || displayResult.hashtag || "trending"}-${new Date().toISOString().slice(0, 10)}`} label="Download Semua Hasil" /></div>

          {/* Content */}
          {tabKeys.filter(k => k === activeTab || activeTab === "all").map(k => {
            if (activeTab !== "all" && k !== activeTab) return null;
            const items = k === "all" ? allResults : groups[k as keyof typeof groups] || [];
            if (items.length === 0) return null;
            const meta = k === "all" ? { label: "Semua", color: "#6b5ec7" } : GROUP_META[k] || { label: k, color: "#8890aa" };
            return (
              <div key={k}>
                <h2 className="text-lg font-bold mb-3 flex items-center gap-2" style={{ color: meta.color }}>{meta.label}<span className="text-sm font-normal opacity-60">({items.length})</span></h2>
                {items.map((hit, idx) => {
                  const images = hitImages(hit);
                  const thumb = images[0];
                  const caption = hit.caption || hit.text || "";
                  return (
                  <GlassCard key={`${hit.url}-${idx}`}>
                    <div className="grid grid-cols-1 md:grid-cols-[220px_1fr_auto] gap-4">
                      <a href={hit.url} target="_blank" rel="noopener noreferrer"
                        className="relative block overflow-hidden rounded-xl min-h-40 md:min-h-32"
                        style={{ background: "rgba(0,0,0,0.04)", border: "1px solid rgba(0,0,0,0.06)" }}>
                        {thumb ? (
                          <img src={thumb} alt={caption || hit.author || "thumbnail"} referrerPolicy="no-referrer" loading="lazy"
                            className="absolute inset-0 h-full w-full object-cover"
                            onError={(e) => { e.currentTarget.style.display = "none"; }} />
                        ) : (
                          <div className="absolute inset-0 flex items-center justify-center">
                            <ImageIcon size={28} style={{ color: "rgba(136,144,170,0.55)" }} />
                          </div>
                        )}
                        {(hit.type === "videos" || hit.type === "video" || hit.type === "reel") && (
                          <span className="absolute left-2 top-2 rounded-full px-2 py-1 text-xs font-semibold" style={{ background: "rgba(0,0,0,0.65)", color: "white" }}>Video</span>
                        )}
                      </a>

                      <div className="min-w-0">
                        <div className="flex items-center gap-2 mb-1 flex-wrap">
                          <span className={`text-xs font-bold px-2 py-0.5 rounded-full uppercase ${hit.type === "posts" || hit.type === "post" ? "bg-blue-100 text-blue-700" : hit.type === "videos" || hit.type === "video" || hit.type === "reel" ? "bg-pink-100 text-pink-700" : hit.type === "pages" || hit.type === "page" ? "bg-green-100 text-green-700" : hit.type === "groups" || hit.type === "group" ? "bg-orange-100 text-orange-700" : "bg-gray-100 text-gray-700"}`}>{hit.type}</span>
                          <span className="text-xs" style={{ color: "#8890aa" }}>{hit.author || "Unknown"}</span>
                          {typeof hit.rank === "number" && <span className="text-xs" style={{ color: "#8890aa" }}>Rank #{hit.rank}</span>}
                        </div>
                        {caption && <p className="text-sm leading-relaxed line-clamp-4" style={{ color: "#4a5070" }}>{caption}</p>}
                        <div className="flex items-center gap-4 mt-3 flex-wrap">
                          {hit.timestamp && <p className="text-xs" style={{ color: "#8890aa" }}>{hit.timestamp}</p>}
                          <div className="flex items-center gap-3 text-xs" style={{ color: "#8890aa" }}>
                            <span className="flex items-center gap-1"><Heart size={13} />{(hit.likes_count ?? hit.like_count ?? 0).toLocaleString('id-ID')}</span>
                            <span className="flex items-center gap-1"><MessageSquare size={13} />{(hit.comments_count ?? 0).toLocaleString('id-ID')}</span>
                            <span className="flex items-center gap-1"><Eye size={13} />{(hit.views_count ?? 0).toLocaleString('id-ID')}</span>
                          </div>
                        </div>
                        {hit.source && <p className="text-xs mt-2" style={{ color: "#8890aa" }}>Source: {hit.source}</p>}
                        <CommentSection post={hit as HitWithComments} />
                      </div>

                      <div className="flex md:flex-col gap-2 shrink-0">
                        <a href={hit.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-2 px-3 py-2 rounded-lg text-sm transition-all hover:bg-purple-100" style={{ background: "rgba(0,0,0,0.04)", color: "#3b6dce" }}><ExternalLink size={16} />Buka</a>
                        <DownloadButton data={hit} filename={`fb-monitor-${hit.author || "post"}-${idx}`} label="" className="px-2 py-1" />
                      </div>
                    </div>
                  </GlassCard>
                );})}
              </div>
            );
          })}
        </>
      )}

      {displayResult && allResults.length === 0 && !isMyRun && (
        <GlassCard>
          <div className="flex items-start gap-3">
            <Search size={18} className="shrink-0 mt-0.5" style={{ color: "#9e6c0a" }} />
            <div>
              <h3 className="font-semibold mb-1" style={{ color: "#1a1c23" }}>Belum ada hasil yang lolos filter</h3>
              <p className="text-sm" style={{ color: "#4a5070" }}>
                Coba kecilkan minimum like/komentar/views, tambah tipe konten, atau gunakan keyword yang lebih umum. Backend sekarang juga mencoba fallback HTML untuk format link Facebook terbaru.
              </p>
            </div>
          </div>
        </GlassCard>
      )}
    </div>
  );
}
