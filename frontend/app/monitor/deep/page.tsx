"use client";
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { useRouter } from "next/navigation";
import { api, ContentMixMode, DeepJobState, DeepPost } from "@/lib/api";
import {
  Search, Loader2, ExternalLink, FileText, Users, Video,
  Grid3x3, Hash, TrendingUp, Play, Square, RefreshCw,
  CheckCircle, XCircle, Clock, AlertCircle, ChevronDown, ChevronUp,
  Heart, MessageCircle, Eye, Share2, Newspaper, AlertTriangle,
} from "lucide-react";
import GlassCard from "@/components/ui/GlassCard";
import DownloadButton from "@/components/ui/DownloadButton";
import { useScrape } from "@/contexts/ScrapeContext";
import { usePersistState } from "@/hooks/usePersistState";
import { downloadJSON, downloadCSV } from "@/lib/download";

type DeepMode = "keyword" | "hashtag" | "trending";
type DeepSort = "trending" | "viral" | "engagement" | "likes" | "comments" | "shares" | "views" | "recent";
type ResultFilter = "all" | "viral_plus" | "potential_plus" | "metrics_valid" | "hide_invalid";

// ─── Helpers ────────────────────────────────────────────────────────────────

function groupByType(items: DeepPost[]) {
  const groups = {
    posts:  [] as DeepPost[],
    videos: [] as DeepPost[],
    pages:  [] as DeepPost[],
    groups: [] as DeepPost[],
    other:  [] as DeepPost[],
  };
  for (const item of items) {
    const t = item.type?.toLowerCase() || "";
    if (t === "posts" || t === "post")                               groups.posts.push(item);
    else if (t === "videos" || t === "video" || t === "reel" || t === "reels") groups.videos.push(item);
    else if (t === "pages" || t === "page")                          groups.pages.push(item);
    else if (t === "groups" || t === "group")                        groups.groups.push(item);
    else                                                             groups.other.push(item);
  }
  return groups;
}

const GROUP_META: Record<string, { label: string; color: string; icon: React.ReactNode }> = {
  posts:  { label: "Postingan",   color: "#3b6dce", icon: <FileText  size={14} /> },
  videos: { label: "Video/Reels", color: "#c0394f", icon: <Video     size={14} /> },
  pages:  { label: "Halaman",     color: "#1d7a47", icon: <Users     size={14} /> },
  groups: { label: "Grup",        color: "#9e6c0a", icon: <Grid3x3   size={14} /> },
  other:  { label: "Lainnya",     color: "#8890aa", icon: <Search    size={14} /> },
};

/** Ambil domain dari URL untuk dijadikan nama media */
function mediaDomain(url?: string): string {
  if (!url) return "";
  try {
    const { hostname, pathname } = new URL(url);
    // Cek apakah ini halaman profile/page FB tertentu
    const pathClean = pathname.replace(/\/$/, "");
    const slug = pathClean.split("/").find(s => s && !["www", "facebook", "watch", "groups", "pages", "photo", "photos", "videos", "reel", "reels", "posts", "permalink"].includes(s.toLowerCase()));
    if (slug && slug.length > 2 && !slug.startsWith("?") && !/^\d{10,}$/.test(slug)) return slug.replace(/[._-]/g, " ");
    return hostname.replace("www.", "");
  } catch {
    return "";
  }
}

/** Apakah post ini benar-benar post (bukan sekadar URL halaman/hashtag)? */
function isRealPost(post: DeepPost): boolean {
  if (post.type === "groups" && post.group_name) return true;
  const u = post.url?.toLowerCase() || "";
  // Exclude: hashtag pages, pure profile pages, pure group homepages
  if (u.includes("/hashtag/")) return false;
  if (/facebook\.com\/[a-z0-9._-]+\/?$/.test(u) && !/\/(posts|permalink|photo|video|reel)/.test(u)) {
    // Profile/page homepage — masih boleh tampil tapi tandai "terbatas"
    return false;
  }
  return true;
}

function hasEngagement(post: DeepPost): boolean {
  return (post.likes_count || 0) > 0 || (post.comments_count || 0) > 0 || (post.views_count || 0) > 0 || (post.shares_count || 0) > 0;
}

function hasContent(post: DeepPost): boolean {
  return !!((post.group_about || post.caption || post.text || "").trim());
}

function compactUrl(url?: string) {
  if (!url) return "URL tidak tersedia";
  try {
    const u = new URL(url);
    return `${u.hostname}${u.pathname}${u.search}`.replace(/\/$/, "").slice(0, 80);
  } catch {
    return url.slice(0, 80);
  }
}

// Apakah URL adalah permalink post asli yang bisa di-scrape detail.
// Post dari kartu pencarian tanpa permalink memakai placeholder
// (/search/posts/?...&fb_scrape_card=...) yang tidak bisa di-scrape detail.
function isRealPostLink(url?: string): boolean {
  if (!url) return false;
  const u = url.toLowerCase();
  if (u.includes("fb_scrape_card=") || u.includes("/search/posts/") || u.includes("/search/top/")) return false;
  return (
    /\/share\/(p|v|r)\//.test(u) ||
    (/\/watch/.test(u) && /[?&]v=\d+/.test(u)) ||
    /\/groups\/[^/]+\/(posts|permalink)\/\d+/.test(u) ||
    /\/(posts|permalink)\/(?:\d+|pfbid)/.test(u) ||
    /\/(videos?|reels?|reel)\/\d+/.test(u) ||
    /\/photo\/?\?fbid=\d+/.test(u) ||
    /[?&]fbid=\d+/.test(u) ||
    /\/(photo|photos)\/\d+/.test(u) ||
    /story_fbid=\d+/.test(u)
  );
}

// Filter defensif: jangan tampilkan item dari cache lama yang link-nya invalid.
// Backend sekarang sudah drop placeholder kartu pencarian + item link_valid=false,
// tapi cache "deep-posts-v2" di browser bisa berisi data lama sebelum fix ini.
function isInvalidCachedPost(post: DeepPost): boolean {
  if (post.link_valid === false) return true;
  const u = (post.url || "").toLowerCase();
  return u.includes("fb_scrape_card=") || u.includes("/search/posts/") || u.includes("/search/top/");
}

function primaryText(post: DeepPost) {
  return (post.group_about || post.caption || post.text || "").trim();
}

function sourceLabel(post: DeepPost): string {
  return (
    post.deep_root_query ||
    post.deep_root_tag ||
    post.deep_query ||
    post.deep_source_tag ||
    post.deep_source ||
    "Tanpa sumber"
  ).trim();
}

function errorMessage(error: unknown, fallback: string) {
  return error instanceof Error ? error.message : fallback;
}

function fmtNum(n?: number | null): string {
  if (!n || n === 0) return "0";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}jt`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}rb`;
  return n.toLocaleString("id-ID");
}

function metricNum(value?: number | null): number {
  return Number(value || 0);
}

function engagementValue(post: DeepPost): number {
  return (
    metricNum(post.likes_count) +
    metricNum(post.comments_count) * 2 +
    metricNum(post.shares_count) * 3 +
    metricNum(post.views_count) * 0.1
  );
}

function viralLevelValue(level?: string): number {
  if (level === "very_viral") return 5;
  if (level === "strong_viral") return 4;
  if (level === "viral") return 3;
  if (level === "potential") return 2;
  if (level === "low") return 1;
  return 0;
}

function viralLabel(level?: string): string {
  if (level === "very_viral") return "Very Viral";
  if (level === "strong_viral") return "Strong Viral";
  if (level === "viral") return "Viral";
  if (level === "potential") return "Potential";
  return "";
}

function viralBadgeStyle(level?: string) {
  if (level === "very_viral") return { background: "rgba(192,57,79,0.12)", color: "#b4233c" };
  if (level === "strong_viral") return { background: "rgba(219,112,31,0.12)", color: "#b95716" };
  if (level === "viral") return { background: "rgba(29,122,71,0.12)", color: "#1d7a47" };
  if (level === "potential") return { background: "rgba(107,94,199,0.12)", color: "#5b4fc4" };
  return { background: "rgba(136,144,170,0.12)", color: "#60687f" };
}

function passesResultFilter(post: DeepPost, filter: ResultFilter): boolean {
  if (filter === "all") return true;
  if (filter === "metrics_valid" || filter === "hide_invalid") return post.metrics_valid !== false;
  const rank = viralLevelValue(post.viral_level);
  if (filter === "viral_plus") return post.metrics_valid !== false && rank >= viralLevelValue("viral");
  if (filter === "potential_plus") return post.metrics_valid !== false && rank >= viralLevelValue("potential");
  return true;
}

function sortPostsForDisplay(items: DeepPost[], sortBy: DeepSort): DeepPost[] {
  const value = (post: DeepPost) => {
    if (sortBy === "trending" || sortBy === "viral") {
      // Video & post pakai ranking yang sama: comments + likes dulu, views belakangan,
      // supaya views besar pada video tidak otomatis mendominasi urutan feed.
      return (
        metricNum(post.comments_count) * 1_000_000 +
        metricNum(post.likes_count) * 10_000 +
        metricNum(post.shares_count) * 1_000 +
        metricNum(post.views_count) +
        metricNum(post.viral_score)
      );
    }
    if (sortBy === "likes") return metricNum(post.likes_count);
    if (sortBy === "comments") return metricNum(post.comments_count);
    if (sortBy === "shares") return metricNum(post.shares_count);
    if (sortBy === "views") return metricNum(post.views_count);
    if (sortBy === "recent") return post.timestamp ? Date.parse(post.timestamp) || 0 : 0;
    return engagementValue(post);
  };
  return [...items].sort((a, b) => {
    const diff = value(b) - value(a);
    if (diff !== 0) return diff;
    return (a.rank || Number.MAX_SAFE_INTEGER) - (b.rank || Number.MAX_SAFE_INTEGER);
  });
}

// ─── CommentSection ──────────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-unused-vars
function CommentSection({ post }: { post: DeepPost }) {
  const [expanded, setExpanded] = useState(false);

  if (post.comments_scrape_failed) {
    return (
      <div className="mt-3 flex items-center gap-2 px-3 py-2 rounded-xl text-xs" style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.15)", color: "#c0394f" }}>
        <AlertTriangle size={13} />
        Komentar tidak berhasil di-scrape
      </div>
    );
  }

  if (!post.top_comments?.length) return null;

  const total = post.comments_scraped_count || 0;
  const otherCount = total - post.top_comments.length;

  return (
    <div className="mt-4 space-y-2">
      {/* Header */}
      <div className="flex items-center gap-1.5 text-xs font-semibold" style={{ color: "#4a5070" }}>
        <MessageCircle size={13} style={{ color: "#3b6dce" }} />
        Top Komentar (Like Terbanyak)
        <span style={{ color: "#8890aa", fontWeight: 400 }}>
          ({post.top_comments.length} komentar{otherCount > 0 ? ` · ${total} total scraped` : ""})
        </span>
      </div>

      {/* Comment list */}
      {post.top_comments.map((c, ci) => (
        <div
          key={ci}
          className="rounded-xl px-3 py-2.5 text-xs space-y-1"
          style={{ background: "rgba(59,109,206,0.04)", border: "1px solid rgba(59,109,206,0.1)" }}
        >
          {/* Author + timestamp */}
          <div className="flex items-center gap-2">
            {/* Avatar placeholder */}
          <div className="shrink-0 rounded-full flex items-center justify-center text-white font-bold"
              style={{ width: 24, height: 24, fontSize: 10, background: `hsl(${(c.comment_author?.charCodeAt(0) || 0) * 47 % 360}, 60%, 50%)` }}
            >
              {(c.comment_author || "?")[0].toUpperCase()}
            </div>
            <span className="font-semibold" style={{ color: "#1a1c23" }}>{c.comment_author || "Anonim"}</span>
            {c.comment_timestamp && (
              <span style={{ color: "#8890aa" }}>{c.comment_timestamp}</span>
            )}
          </div>

          {/* Comment text */}
          <p className="leading-5 pl-8" style={{ color: "#4a5070" }}>{c.comment_text.slice(0, 300)}</p>

          {/* Likes */}
          {c.comment_likes > 0 && (
            <div className="flex items-center gap-1 pl-8" style={{ color: "#8890aa" }}>
              {/* ✅ FIX: pakai karakter langsung, bukan \u2764 sebagai string */}
              <Heart size={11} style={{ color: "#e0245e" }} fill="#e0245e" />
              <span>{fmtNum(c.comment_likes)}</span>
            </div>
          )}
        </div>
      ))}

      {/* Show more / collapse */}
      {otherCount > 0 && (
        <>
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1.5 text-xs px-2 py-1.5 rounded-lg transition-all hover:bg-black/5 font-medium"
            style={{ color: "#6b5ec7" }}
          >
            {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            {expanded ? "Sembunyikan" : `Lihat ${otherCount} komentar lainnya`}
          </button>

          {expanded && post.other_comments?.map((c, ci) => (
            <div
              key={`o-${ci}`}
              className="rounded-xl px-3 py-2.5 text-xs space-y-1 ml-4"
              style={{ background: "rgba(0,0,0,0.025)", border: "1px solid rgba(0,0,0,0.07)" }}
            >
              <div className="flex items-center gap-2">
                <div
                  className="shrink-0 rounded-full flex items-center justify-center text-white font-bold"
                  style={{ width: 20, height: 20, fontSize: 9, background: `hsl(${(c.comment_author?.charCodeAt(0) || 0) * 47 % 360}, 55%, 55%)` }}
                >
                  {(c.comment_author || "?")[0].toUpperCase()}
                </div>
                <span className="font-semibold" style={{ color: "#1a1c23" }}>{c.comment_author || "Anonim"}</span>
                {c.comment_timestamp && <span style={{ color: "#8890aa" }}>{c.comment_timestamp}</span>}
              </div>
              <p className="leading-5 pl-7" style={{ color: "#4a5070" }}>{c.comment_text.slice(0, 300)}</p>
              {c.comment_likes > 0 && (
                <div className="flex items-center gap-1 pl-7" style={{ color: "#8890aa" }}>
                  <Heart size={10} style={{ color: "#e0245e" }} fill="#e0245e" />
                  <span>{fmtNum(c.comment_likes)}</span>
                </div>
              )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

// ─── PostCard ────────────────────────────────────────────────────────────────

function PostCard({ post, idx, onScrapePost }: { post: DeepPost; idx: number; onScrapePost: (url: string) => void }) {
  const text       = primaryText(post);
  const openUrl = isRealPostLink(post.detail_final_url) ? post.detail_final_url! : post.url;
  const canOpenFb = isRealPostLink(openUrl) && post.link_valid !== false;
  const domain     = mediaDomain(openUrl || post.url);
  const realPost   = isRealPost(post);
  const hasContent_ = hasContent(post);
  const hasEngage  = hasEngagement(post);
  const typeKey    = (post.type?.toLowerCase() || "other") as keyof typeof GROUP_META;
  const meta       = GROUP_META[typeKey] || GROUP_META.other;

  return (
    <GlassCard className="overflow-hidden mb-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start">
        {/* ── Left: Main content ── */}
        <div className="flex-1 min-w-0 space-y-3">

          {/* Row 1: Badges + rank */}
          <div className="flex items-center gap-2 flex-wrap">
            {post.rank && (
              <span className="text-xs font-bold px-2 py-0.5 rounded-full" style={{ background: "rgba(107,94,199,0.1)", color: "#6b5ec7" }}>
                #{post.rank}
              </span>
            )}

            {/* Type badge */}
            <span
              className="flex items-center gap-1 text-xs font-bold px-2 py-0.5 rounded-full uppercase"
              style={{ background: `${meta.color}18`, color: meta.color }}
            >
              {meta.icon}{post.type || "post"}
            </span>

            {/* Data terbatas badge */}
            {(!realPost || (!hasContent_ && !hasEngage)) && (
              <span className="flex items-center gap-1 text-xs px-2 py-0.5 rounded-full" style={{ background: "rgba(158,108,10,0.1)", color: "#9e6c0a" }}>
                <AlertTriangle size={11} /> Data terbatas
              </span>
            )}

            {post.metrics_valid === false ? (
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "rgba(136,144,170,0.12)", color: "#60687f" }}>
                Metrics belum valid
              </span>
            ) : viralLabel(post.viral_level) ? (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full" style={viralBadgeStyle(post.viral_level)}>
                {viralLabel(post.viral_level)}
              </span>
            ) : null}

            {/* Source tag */}
            {sourceLabel(post) !== "Tanpa sumber" && (
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "rgba(29,122,71,0.08)", color: "#1d7a47" }}>
                {sourceLabel(post)}
              </span>
            )}
            {post.deep_source_tag && post.deep_source_tag !== sourceLabel(post) && (
              <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: "rgba(107,94,199,0.08)", color: "#6b5ec7" }}>
                #{post.deep_source_tag}
              </span>
            )}
          </div>

          {/* Row 2: Media name + author */}
          <div className="flex items-center gap-2 flex-wrap">
            {/* ✅ Nama media dari domain URL */}
            {(post.group_name || domain) && (
              <div className="flex items-center gap-1 text-xs font-semibold" style={{ color: "#1a1c23" }}>
                <Newspaper size={12} style={{ color: "#6b5ec7" }} />
                {post.group_name || domain}
              </div>
            )}
            {post.author && post.author !== "Unknown" && post.author !== domain && post.author !== post.group_name && (
              <span className="text-xs" style={{ color: "#8890aa" }}>
                oleh <span style={{ color: "#4a5070" }}>{post.author}</span>
              </span>
            )}
            {post.type === "groups" && post.group_members && (
              <span className="text-xs" style={{ color: "#8890aa" }}>{post.group_members}</span>
            )}
            {post.timestamp && (
              <span className="text-xs" style={{ color: "#8890aa" }}>· {post.timestamp}</span>
            )}
          </div>

          {/* Row 3: Caption/text */}
          {hasContent_ ? (
            <p className="text-sm leading-6 whitespace-pre-wrap overflow-wrap-anywhere" style={{ color: "#1a1c23" }}>
              {text}
            </p>
          ) : (
            <p className="text-sm italic" style={{ color: "#aab0bf" }}>
              Konten tidak berhasil ter-extract dari halaman ini
            </p>
          )}

          {/* Row 4: Engagement metrics */}
          {(realPost || hasContent_ || hasEngage) ? (
            <div className="flex flex-wrap items-center gap-3">
              {post.likes_count != null && (
                <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#4a5070" }}>
                  {/* ✅ FIX: Heart icon dari lucide, bukan \u2764 string */}
                  <Heart size={14} style={{ color: "#e0245e" }} fill="#e0245e" />
                  {fmtNum(post.likes_count)}
                </span>
              )}
              {post.comments_count != null && (
                <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#4a5070" }}>
                  <MessageCircle size={14} style={{ color: "#3b6dce" }} />
                  {fmtNum(post.comments_count)}
                </span>
              )}
              {(post.views_count || 0) > 0 && (
                <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#4a5070" }}>
                  <Eye size={14} style={{ color: "#8890aa" }} />
                  {fmtNum(post.views_count)}
                </span>
              )}
              {/* ✅ FIX: Shares menggunakan Share2 icon */}
              {post.shares_count != null && (
                <span className="flex items-center gap-1.5 text-xs font-medium" style={{ color: "#4a5070" }}>
                  <Share2 size={14} style={{ color: "#1d7a47" }} />
                  {fmtNum(post.shares_count)}
                </span>
              )}
              {post.metrics_valid === false && (
                <span className="text-xs px-2 py-1 rounded-full" style={{ background: "rgba(192,57,79,0.08)", color: "#c0394f" }}>
                  metrics: {post.metric_source || "unverified"}
                </span>
              )}
            </div>
          ) : (
            <div className="flex items-center gap-1.5 text-xs" style={{ color: "#aab0bf" }}>
              <AlertTriangle size={12} />
              Engagement belum ter-extract
            </div>
          )}

          {/* Row 5: URL */}
          <div
            className="rounded-lg px-3 py-2 text-xs break-all font-mono"
            style={{ background: "rgba(0,0,0,0.025)", color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.12)" }}
          >
            {compactUrl(post.url)}
          </div>

        </div>

        {/* ── Right: Actions ── */}
        <div className="flex shrink-0 flex-row gap-1.5 lg:w-32 lg:flex-col">
          {canOpenFb ? (
            <a
              href={openUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="flex-1 lg:flex-none flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-purple-50"
              style={{ color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.2)", background: "rgba(107,94,199,0.05)" }}
            >
              <ExternalLink size={12} /> Buka FB
            </a>
          ) : (
            <button
              type="button"
              disabled
              title={post.link_sync_error || "Permalink asli belum tervalidasi dari hasil pencarian Facebook"}
              className="flex-1 lg:flex-none flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium disabled:cursor-not-allowed disabled:opacity-45"
              style={{ color: "#4a5070", border: "1px solid rgba(74,80,112,0.16)", background: "rgba(74,80,112,0.04)" }}
            >
              <ExternalLink size={12} /> Link belum valid
            </button>
          )}
          {(() => {
            const canScrape = canOpenFb;
            return (
              <button
                onClick={() => canScrape && onScrapePost(openUrl)}
                disabled={!canScrape}
                title={canScrape
                  ? "Scrape detail postingan ini"
                  : "Tidak bisa scrape detail — post ini ditangkap dari kartu pencarian dan Facebook tidak memberi permalink aslinya"}
                className="flex-1 lg:flex-none flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl text-xs font-medium transition-all hover:bg-green-50 disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent"
                style={{ color: "#1d7a47", border: "1px solid rgba(29,122,71,0.2)", background: "rgba(29,122,71,0.05)" }}
              >
                <FileText size={12} /> Scrape Post
              </button>
            );
          })()}
          <DownloadButton
            data={post}
            filename={`fb-post-${post.author || "unknown"}-${idx}`}
            label="Download"
            className="flex-1 lg:flex-none justify-center px-3 py-2 text-xs"
          />
        </div>
      </div>
    </GlassCard>
  );
}

// ─── Main Page ───────────────────────────────────────────────────────────────

export default function DeepSearchPage() {
  const router = useRouter();
  const { job, isRunning, start, finish, fail, clear, setAutoFillUrl } = useScrape();

  const [mode,    setMode]    = usePersistState<DeepMode>("deep-mode",  "keyword");
  const [query,   setQuery]   = usePersistState("deep-query",           "");
  const [types,   setTypes]   = usePersistState<string[]>("deep-types", ["posts", "videos"]);
  const [sortBy,  setSortBy]  = usePersistState<DeepSort>("deep-sort-v3", "trending");
  const contentMixMode: ContentMixMode = "posts_first_80_20";
  const [resultFilter, setResultFilter] = usePersistState<ResultFilter>("deep-result-filter", "all");
  const [maxTotal,            setMaxTotal]            = useState(1000);
  const [recentDays,          setRecentDays]          = useState(30);
  const [fastMode,            setFastMode]            = useState(true);

  const [jobId,     setJobId]     = usePersistState<string | null>("deep-active-job-id", null);
  const [jobState,  setJobState]  = useState<DeepJobState | null>(null);
  const [posts,     setPosts]     = useState<DeepPost[]>([]);
  const [loading,   setLoading]   = useState(false);
  const [error,     setError]     = useState("");
  const [activeTab, setActiveTab] = useState("all");
  const [activeSource, setActiveSource] = useState("all");
  const [showEmpty, setShowEmpty] = useState(false);

  const [cachedPosts, setCachedPosts] = usePersistState<DeepPost[]>("deep-posts-v2", []);

  const pollRef        = useRef<NodeJS.Timeout | null>(null);
  const pollInFlightRef = useRef(false);
  const lastPartialFetchRef = useRef(0);
  const cancelledRef   = useRef(false);
  const activeJobIdRef = useRef<string | null>(null);

  const isMyJob  = job?.type === "deep";
  const isMyRun  = isRunning && isMyJob;
  const otherRun = isRunning && !isMyJob;

  const jobPosts = useMemo(
    () => (job?.type === "deep" && job.status === "done" ? (job.deepPosts as DeepPost[]) : []),
    [job],
  );
  const allPosts    = useMemo(
    () => (jobPosts.length > 0 ? jobPosts : posts.length > 0 ? posts : cachedPosts).filter(p => !isInvalidCachedPost(p)),
    [jobPosts, posts, cachedPosts],
  );

  // Split: post "nyata" vs post data terbatas
  const realPosts  = useMemo(() => allPosts.filter(p => isRealPost(p) && (hasContent(p) || hasEngagement(p))), [allPosts]);
  const limitedPosts = useMemo(() => allPosts.filter(p => !isRealPost(p) || (!hasContent(p) && !hasEngagement(p))), [allPosts]);
  const baseDisplayPosts = showEmpty ? allPosts : (realPosts.length > 0 ? realPosts : allPosts);
  const sourceOptions = useMemo(() => {
    const counts = new Map<string, number>();
    for (const post of baseDisplayPosts) {
      const label = sourceLabel(post);
      counts.set(label, (counts.get(label) || 0) + 1);
    }
    return Array.from(counts.entries())
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  }, [baseDisplayPosts]);
  const effectiveSource = activeSource === "all" || sourceOptions.some(opt => opt.label === activeSource)
    ? activeSource
    : "all";
  const displayPosts = useMemo(() => {
    const sourceFiltered = effectiveSource === "all"
      ? baseDisplayPosts
      : baseDisplayPosts.filter(post => sourceLabel(post) === effectiveSource);
    const filtered = sourceFiltered.filter(post => passesResultFilter(post, resultFilter));
    return sortPostsForDisplay(filtered, sortBy);
  }, [effectiveSource, baseDisplayPosts, resultFilter, sortBy]);

  const groups = useMemo(() => groupByType(displayPosts), [displayPosts]);

  const typeOptions = [
    { value: "posts",   label: "Postingan",   icon: FileText },
    { value: "videos",  label: "Video/Reels", icon: Video    },
    { value: "pages",   label: "Halaman",     icon: Users    },
    { value: "groups",  label: "Grup",        icon: Grid3x3  },
  ];
  const sortOptions: Array<{ value: DeepSort; label: string }> = [
    { value: "trending", label: "Trending" },
    { value: "likes", label: "Like" },
    { value: "comments", label: "Komentar" },
    { value: "shares", label: "Share" },
    { value: "views", label: "Views" },
  ];
  const resultFilterOptions: Array<{ value: ResultFilter; label: string }> = [
    { value: "all", label: "Semua" },
    { value: "viral_plus", label: "Viral+" },
    { value: "potential_plus", label: "Potential+" },
    { value: "metrics_valid", label: "Metrics valid saja" },
    { value: "hide_invalid", label: "Sembunyikan invalid" },
  ];

  const toggleType = (val: string) => {
    setTypes(prev => prev.includes(val) ? prev.filter(t => t !== val) : [...prev, val]);
  };

  const stopPolling = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  useEffect(() => {
    if (jobId) return;
    if (!isMyRun) return;

    let ignore = false;
    const recoverLatestJob = async () => {
      try {
        const res = await api.deep.jobs();
        const jobs = (res.data?.jobs || [])
          .filter(j => j.mode === mode)
          .sort((a, b) => new Date(b.updated_at || b.created_at).getTime() - new Date(a.updated_at || a.created_at).getTime());

        if (ignore || jobs.length === 0) return;

        const wanted = (job?.type === "deep" ? job.label : query).trim().toLowerCase();
        const matchedCandidates = wanted
          ? jobs.filter(j => (j.query || "").toLowerCase().includes(wanted) || wanted.includes((j.query || "").toLowerCase()))
          : jobs;
        const candidates = matchedCandidates.length > 0 ? matchedCandidates : jobs;

        const latestRunning = candidates.find(j => j.status === "running" || j.status === "pending");
        if (!latestRunning) return;

        setJobId(latestRunning.job_id);
        setLoading(true);
      } catch (err) {
        console.warn("Deep job recovery failed:", errorMessage(err, "unknown"));
      }
    };

    recoverLatestJob();
    return () => { ignore = true; };
  }, [jobId, mode, query, job, isMyRun, setJobId]);

  useEffect(() => {
    if (!jobId || isMyRun || loading || jobState) return;
    setJobId(null);
    activeJobIdRef.current = null;
    const id = window.setTimeout(() => setLoading(false), 0);
    return () => window.clearTimeout(id);
  }, [jobId, isMyRun, loading, jobState, setJobId]);

  useEffect(() => {
    if (!jobId) return;
    if (!isMyRun) return;
    activeJobIdRef.current = jobId;
    cancelledRef.current   = false;

    const poll = async () => {
      if (cancelledRef.current || activeJobIdRef.current !== jobId) { stopPolling(); return; }
      if (pollInFlightRef.current) return;
      pollInFlightRef.current = true;
      try {
        const res = await api.deep.jobStatus(jobId);
        if (!res.data) return;
        setJobState(res.data);
        setLoading(res.data.status === "running" || res.data.status === "pending");

        if (res.data.status === "running" || res.data.status === "pending") {
          try {
            const now = Date.now();
            if (now - lastPartialFetchRef.current >= 15_000) {
              lastPartialFetchRef.current = now;
              const partialRes = await api.deep.jobPostsPartial(jobId);
              if (partialRes.data?.posts?.length) {
                setPosts(partialRes.data.posts);
                setCachedPosts(partialRes.data.posts);
              }
            }
          } catch (e: unknown) { console.warn("Partial fetch error:", errorMessage(e, "unknown")); }
        }

        if (res.data.status === "completed" || res.data.status === "cancelled") {
          stopPolling(); setLoading(false);
          if (res.data.status === "completed") {
            let fp: DeepPost[] = [];
            try {
              const postsRes = await api.deep.jobPosts(jobId);
              fp = postsRes.data?.posts || [];
            } catch (finalErr) {
              console.warn("Final fetch error, falling back to partial:", errorMessage(finalErr, "unknown"));
              const partialRes = await api.deep.jobPostsPartial(jobId);
              fp = partialRes.data?.posts || [];
            }
            setPosts(fp); setCachedPosts(fp);
            finish({ deepPosts: fp, elapsed: undefined });
          } else { finish({ deepPosts: [], elapsed: undefined }); }
        } else if (res.data.status === "error") {
          stopPolling();
          setError(res.data.error || "Job error");
          fail(res.data.error || "Job error");
          setLoading(false);
        }
      } catch (err: unknown) {
        if (cancelledRef.current || activeJobIdRef.current !== jobId) { stopPolling(); setLoading(false); return; }
        if (errorMessage(err, "").includes("cancelled")) {
          stopPolling(); setLoading(false);
          finish({ deepPosts: [], elapsed: undefined });
        } else if (errorMessage(err, "").includes("tidak ditemukan") || errorMessage(err, "").includes("404")) {
          stopPolling(); setLoading(false); setJobId(null);
          setError("Job deep search tidak ditemukan di backend. Jalankan ulang scraping.");
        } else {
          console.warn("Deep polling error:", errorMessage(err, "unknown"));
        }
      } finally {
        pollInFlightRef.current = false;
      }
    };

    poll();
    pollRef.current = setInterval(poll, 8000);
    return () => { stopPolling(); };
  }, [jobId, isMyRun, finish, fail, setCachedPosts, setJobId, stopPolling]);

  const handleStart = async () => {
    if (!query.trim() && mode !== "trending") { setError("Query wajib diisi"); return; }
    if (isRunning) { setError("Scraping lain sedang berjalan"); return; }
    setLoading(true); setError(""); setJobId(null); setJobState(null);
    setPosts([]); setCachedPosts([]); setActiveTab("all"); setActiveSource("all"); setShowEmpty(false);
    cancelledRef.current = false;
    const label = query || `${mode} search`;
    start("deep", label);
    try {
      let res;
      const selectedTypes = types.length ? types : ["posts", "videos"];
      let runTypes = fastMode
        ? (selectedTypes.filter(t => t === "posts" || t === "videos").length
            ? selectedTypes.filter(t => t === "posts" || t === "videos")
            : ["posts", "videos"])
        : selectedTypes;      if (runTypes.length === 0) runTypes = ["posts"];
      const commonConfig = {
        max_total: maxTotal,
        recent_days: recentDays,
        fast_mode: fastMode,
        sort_by: sortBy,
        detail_enrich_limit: Math.min(maxTotal, fastMode ? 60 : 150),
        content_mix_mode: contentMixMode,
        prioritize_posts: true,
        viral_only: false,
      };
      if (mode === "keyword") {
        res = await api.deep.keyword(query, {
          ...commonConfig,
          max_related: fastMode ? 2 : 5,
          max_per_query: fastMode ? 100 : 200,
          types: runTypes,
        });
      } else if (mode === "hashtag") {
        res = await api.deep.hashtag(query, {
          ...commonConfig,
          max_related_hashtags: fastMode ? 2 : 10,
          max_per_query: fastMode ? 100 : 300,
          types: runTypes,
        });
      } else {
        res = await api.deep.trending({
          ...commonConfig,
          keyword: query,
          types: runTypes,
        });
      }
      if (res.data?.job_id) setJobId(res.data.job_id);
      else throw new Error("Job ID tidak diterima");
    } catch (err: unknown) {
      const msg = errorMessage(err, "Gagal memulai deep search");
      setError(msg); setLoading(false); fail(msg);
    }
  };

  const handleCancel = async () => {
    if (!jobId || cancelledRef.current) return;
    cancelledRef.current = true; stopPolling();
    try {
      await api.deep.cancelJob(jobId);
      setJobState(prev => prev ? { ...prev, status: "cancelled" } : null);
      setJobId(null);
      activeJobIdRef.current = null;
      setLoading(false);
      finish({ deepPosts: [], elapsed: undefined });
    } catch {
      setJobId(null);
      activeJobIdRef.current = null;
      setLoading(false);
      finish({ deepPosts: [], elapsed: undefined });
    }
  };

  const handleReset = () => {
    const activeId = jobId;
    if (activeId && loading) {
      void api.deep.cancelJob(activeId).catch(err => {
        console.warn("Reset cancel failed:", errorMessage(err, "unknown"));
      });
    }
    stopPolling(); setJobId(null); setJobState(null); setPosts([]);
    setCachedPosts([]); setError(""); setLoading(false); setShowEmpty(false); setActiveSource("all");
    cancelledRef.current = false; activeJobIdRef.current = null; pollInFlightRef.current = false; lastPartialFetchRef.current = 0;
    clear();
  };

  const handleScrapePost = useCallback((url: string) => {
    setAutoFillUrl(url);
    router.push("/scrape/posts");
  }, [setAutoFillUrl, router]);

  const statusIcon = () => {
    if (!jobState) return null;
    switch (jobState.status) {
      case "pending":   return <Clock        size={15} style={{ color: "#8890aa" }} />;
      case "running":   return <Loader2      size={15} style={{ color: "#3b6dce" }} className="animate-spin" />;
      case "completed": return <CheckCircle  size={15} style={{ color: "#1d7a47" }} />;
      case "cancelled": return <XCircle      size={15} style={{ color: "#9e6c0a" }} />;
      case "error":     return <AlertCircle  size={15} style={{ color: "#c0394f" }} />;
      default:          return null;
    }
  };

  const tabKeys = ["all", ...Object.keys(groups).filter(k => groups[k as keyof typeof groups].length > 0)];
  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">

      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold gradient-text flex items-center gap-2">
          <Search size={24} style={{ color: "#6b5ec7" }} /> Deep Search
        </h1>
        <p className="text-sm mt-1" style={{ color: "#8890aa" }}>
          Pencarian mendalam: scrape + expand ke related keywords / hashtags.
        </p>
      </div>

      {/* Other scrape warning */}
      {otherRun && (
        <GlassCard glow="purple">
          <div className="flex items-center gap-3">
            <Loader2 size={15} style={{ color: "#6b5ec7" }} className="animate-spin shrink-0" />
            <p className="text-sm" style={{ color: "#6b5ec7" }}>Scraping lain sedang berjalan ({job?.label}).</p>
          </div>
        </GlassCard>
      )}

      {/* Mode Tabs */}
      <div className="glass rounded-2xl p-2 flex gap-2">
        {(["keyword", "hashtag", "trending"] as DeepMode[]).map(m => {
          const active = mode === m;
          const Icon   = m === "keyword" ? Search : m === "hashtag" ? Hash : TrendingUp;
          return (
            <button
              key={m} onClick={() => setMode(m)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl text-sm font-medium transition-all ${active ? "shadow-sm" : "hover:bg-black/5"}`}
              style={{ background: active ? "rgba(107,94,199,0.1)" : "transparent", color: active ? "#6b5ec7" : "#4a5070" }}
            >
              <Icon size={15} />{m.charAt(0).toUpperCase() + m.slice(1)}
            </button>
          );
        })}
      </div>

      {/* Form */}
      <div className="glass rounded-2xl p-6 space-y-4">
        {mode !== "trending" && (
          <div>
            <label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>
              {mode === "keyword" ? "Keyword / Dork" : "Hashtag (boleh banyak, pisahkan koma)"}
            </label>
            <input
              type="text" value={query} onChange={e => setQuery(e.target.value)}
              placeholder={mode === "keyword" ? 'Contoh: bemui, bemugm, demo' : 'Contoh: bemui, bemugm, demo'}
              className="glass-input w-full px-4 py-3 text-sm" disabled={isMyRun}
            />
            <p className="text-xs mt-1" style={{ color: "#8890aa" }}>
              Pisahkan dengan koma untuk scrape masing-masing query dan melihat hasil gabungan.
            </p>
          </div>
        )}

        {mode === "trending" && (
          <>
            <div>
              <label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Keyword Trending (Opsional, boleh banyak)</label>
              <input type="text" value={query} onChange={e => setQuery(e.target.value)} placeholder="Contoh: bemui, bemugm, demo atau kosongkan untuk trending umum" className="glass-input w-full px-4 py-3 text-sm" disabled={isMyRun} />
              <p className="text-xs mt-1" style={{ color: "#8890aa" }}>
                Pisahkan dengan koma untuk memproses beberapa trending keyword.
              </p>
            </div>
          </>
        )}

        {(
          <div>
            <label className="text-sm font-medium mb-2 block" style={{ color: "#4a5070" }}>Tipe Konten</label>
            <div className="flex flex-wrap gap-2">
              {typeOptions.map(opt => {
                const active = types.includes(opt.value);
                const I = opt.icon;
                return (
                  <button
                    key={opt.value} onClick={() => toggleType(opt.value)} disabled={isMyRun}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-sm font-medium transition-all"
                    style={{ background: active ? "rgba(107,94,199,0.1)" : "rgba(0,0,0,0.04)", color: active ? "#6b5ec7" : "#4a5070", border: active ? "1px solid rgba(107,94,199,0.25)" : "1px solid transparent" }}
                  >
                    <I size={14} />{opt.label}
                  </button>
                );
              })}
            </div>
          </div>
        )}

        <label
          className="flex items-start gap-3 rounded-xl px-4 py-3 text-sm"
          style={{ background: "rgba(107,94,199,0.06)", border: "1px solid rgba(107,94,199,0.14)", color: "#4a5070" }}
        >
          <input
            type="checkbox"
            checked={fastMode}
            onChange={e => setFastMode(e.target.checked)}
            disabled={isMyRun}
            className="mt-1"
          />
          <span>
            <span className="font-semibold" style={{ color: "#1a1c23" }}>Mode cepat</span>
            <span className="block text-xs mt-0.5" style={{ color: "#8890aa" }}>
              Fokus Post + Video/Reels, related keyword dibatasi, dan enrichment detail secukupnya agar CPU lebih ringan.
            </span>
          </span>
        </label>

        <div className="flex gap-4 flex-wrap">
          <div>
            <label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Max Total Posts</label>
            <input type="number" value={maxTotal} onChange={e => setMaxTotal(Math.min(5000, Math.max(100, parseInt(e.target.value) || 100)))} disabled={isMyRun} className="glass-input w-28 px-4 py-2 text-sm" />
          </div>
          <div>
            <label className="text-sm font-medium mb-1 block" style={{ color: "#4a5070" }}>Rentang Hari</label>
            <input type="number" value={recentDays} onChange={e => setRecentDays(Math.min(365, Math.max(0, parseInt(e.target.value) || 0)))} disabled={isMyRun} className="glass-input w-28 px-4 py-2 text-sm" />
            <p className="text-xs mt-1" style={{ color: "#8890aa" }}>30 = sebulan terakhir, 0 = semua</p>
          </div>
        </div>

        {/* Buttons */}
        <div className="flex gap-2">
          {!loading && !jobId && (
            <button onClick={handleStart} disabled={isRunning}
              className="btn-primary flex-1 flex items-center justify-center gap-2 py-3">
              <Play size={18} /> Mulai Deep Search
            </button>
          )}
          {loading && (
            <button onClick={handleCancel}
              className="flex-1 py-3 rounded-xl flex items-center justify-center gap-2 font-semibold transition-all text-white"
              style={{ background: "#c0394f" }}>
              <Square size={18} /> Cancel Job
            </button>
          )}
          {(jobId || jobState || allPosts.length > 0) && (
            <button onClick={handleReset}
              className="flex-1 py-3 rounded-xl flex items-center justify-center gap-2 font-semibold transition-all"
              style={{ background: "rgba(0,0,0,0.05)", color: "#4a5070" }}>
              <RefreshCw size={18} /> Reset Tampilan
            </button>
          )}
        </div>

        {isMyRun && (
          <div className="flex items-center gap-2 text-xs px-3 py-2.5 rounded-xl" style={{ background: "rgba(107,94,199,0.06)", border: "1px solid rgba(107,94,199,0.15)", color: "#6b5ec7" }}>
            <Loader2 size={12} className="animate-spin shrink-0" /> Deep search berjalan di background...
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="p-4 rounded-xl flex items-center gap-2" style={{ background: "rgba(192,57,79,0.06)", border: "1px solid rgba(192,57,79,0.15)", color: "#c0394f" }}>
          <AlertCircle size={15} /> {error}
        </div>
      )}

      {/* Job Status */}
      {jobState && (
        <div className="glass rounded-2xl p-6 space-y-4">
          <div className="flex items-center gap-3">
            {statusIcon()}
            <div>
              <h2 className="text-base font-bold" style={{ color: "#1a1c23" }}>
                {jobState.mode} — {jobState.query || "(trending)"}
              </h2>
              <p className="text-xs" style={{ color: "#8890aa" }}>
                Status: <span className="font-mono">{jobState.status}</span>
                {" "}· Fetched: {jobState.total_fetched}
                {" "}· Ditampilkan: {displayPosts.length}
                {limitedPosts.length > 0 && !showEmpty && ` (${limitedPosts.length} data terbatas disembunyikan)`}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Results */}
      {allPosts.length > 0 && (
        <>
          <div className="glass rounded-2xl p-2 flex items-center justify-between gap-3 flex-wrap">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="px-2 text-xs font-semibold" style={{ color: "#4a5070" }}>Urutkan</span>
              {sortOptions.map(s => (
                <button key={s.value} onClick={() => setSortBy(s.value)}
                  className="px-3 py-2 rounded-lg text-xs font-medium transition-all"
                  style={{ background: sortBy === s.value ? "rgba(192,57,79,0.1)" : "transparent", color: sortBy === s.value ? "#c0394f" : "#4a5070", border: sortBy === s.value ? "1px solid rgba(192,57,79,0.25)" : "1px solid transparent" }}
                >
                  {s.label}
                </button>
              ))}
            </div>
            <select
              value={resultFilter}
              onChange={e => setResultFilter(e.target.value as ResultFilter)}
              className="px-3 py-2 rounded-lg text-xs font-medium outline-none"
              style={{ background: "rgba(107,94,199,0.08)", color: "#4a5070", border: "1px solid rgba(107,94,199,0.16)" }}
            >
              {resultFilterOptions.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          {/* Show empty toggle */}
          {limitedPosts.length > 0 && (
            <div className="flex items-center justify-between px-1">
              <p className="text-xs" style={{ color: "#8890aa" }}>
                {limitedPosts.length} hasil dengan data terbatas (caption/engagement kosong)
              </p>
              <button
                onClick={() => setShowEmpty(v => !v)}
                className="text-xs px-3 py-1.5 rounded-lg font-medium transition-all hover:bg-black/5"
                style={{ color: "#6b5ec7" }}
              >
                {showEmpty ? "Sembunyikan" : "Tampilkan semua"}
              </button>
            </div>
          )}

          {/* Source filter */}
          {sourceOptions.length > 1 && (
            <div className="glass rounded-2xl p-2 flex gap-1 flex-wrap">
              <button
                onClick={() => { setActiveSource("all"); setActiveTab("all"); }}
                className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all"
                style={{
                  background: effectiveSource === "all" ? "rgba(107,94,199,0.12)" : "transparent",
                  color: effectiveSource === "all" ? "#6b5ec7" : "#4a5070",
                  border: effectiveSource === "all" ? "1px solid rgba(107,94,199,0.3)" : "1px solid transparent",
                }}
              >
                <Search size={13} />
                <span>Gabungan</span>
                <span className="opacity-60">({baseDisplayPosts.length})</span>
              </button>
              {sourceOptions.map(opt => {
                const active = effectiveSource === opt.label;
                return (
                  <button
                    key={opt.label}
                    onClick={() => { setActiveSource(opt.label); setActiveTab("all"); }}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all"
                    style={{
                      background: active ? "rgba(29,122,71,0.1)" : "transparent",
                      color: active ? "#1d7a47" : "#4a5070",
                      border: active ? "1px solid rgba(29,122,71,0.25)" : "1px solid transparent",
                    }}
                  >
                    <Hash size={13} />
                    <span>{opt.label}</span>
                    <span className="opacity-60">({opt.count})</span>
                  </button>
                );
              })}
            </div>
          )}

          {/* Tab filter */}
          <div className="glass rounded-2xl p-2 flex gap-1 flex-wrap">
            {tabKeys.map(k => {
              const count = k === "all" ? displayPosts.length : groups[k as keyof typeof groups]?.length || 0;
              const meta  = k === "all"
                ? { label: "Semua", color: "#6b5ec7", icon: <Search size={13} /> }
                : GROUP_META[k] || { label: k, color: "#8890aa", icon: <Search size={13} /> };
              const active = activeTab === k;
              return (
                <button
                  key={k} onClick={() => setActiveTab(k)}
                  className="flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs font-medium transition-all"
                  style={{
                    background: active ? `${meta.color}15` : "transparent",
                    color: active ? meta.color : "#4a5070",
                    border: active ? `1px solid ${meta.color}30` : "1px solid transparent",
                  }}
                >
                  {meta.icon}<span>{meta.label}</span>
                  <span className="opacity-60">({count})</span>
                </button>
              );
            })}
          </div>

          <div className="flex justify-end gap-2">
            <button
              onClick={() => downloadJSON(displayPosts, `fb-deep-${query || "search"}-${new Date().toISOString().slice(0, 10)}`)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all hover:bg-purple-50"
              style={{ background: "rgba(107,94,199,0.07)", color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.2)" }}
            >
              <FileText size={15} /> Download JSON
            </button>
            <button
              onClick={() => downloadCSV(displayPosts, `fb-deep-${query || "search"}-${new Date().toISOString().slice(0, 10)}`)}
              className="flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-medium transition-all hover:bg-green-50"
              style={{ background: "rgba(29,122,71,0.07)", color: "#1d7a47", border: "1px solid rgba(29,122,71,0.2)" }}
            >
              <FileText size={15} /> Download CSV
            </button>
          </div>

          {/* Post list */}
          {tabKeys.filter(k => activeTab === "all" || k === activeTab).map(k => {
            if (activeTab !== "all" && k !== activeTab) return null;
            const items = k === "all" ? displayPosts : groups[k as keyof typeof groups] || [];
            if (!items.length) return null;
            const meta  = k === "all" ? { label: "Semua", color: "#6b5ec7" } : GROUP_META[k] || { label: k, color: "#8890aa" };
            return (
              <div key={k}>
                <h2 className="text-base font-bold mb-3 flex items-center gap-2" style={{ color: meta.color }}>
                  {meta.label}
                  <span className="text-sm font-normal opacity-60">({items.length})</span>
                </h2>
                {items.map((post, idx) => (
                  <PostCard key={post.url || `${k}-${idx}`} post={post} idx={idx} onScrapePost={handleScrapePost} />
                ))}
              </div>
            );
          })}
        </>
      )}

      {/* Loading state */}
      {loading && jobState?.status === "running" && displayPosts.length === 0 && (
        <div className="text-center py-12" style={{ color: "#8890aa" }}>
          <Loader2 size={28} className="animate-spin mx-auto mb-3" style={{ color: "#6b5ec7" }} />
          <p className="text-sm font-medium">Mengumpulkan hasil pertama...</p>
          <p className="text-xs mt-1">Biasanya membutuhkan 30–60 detik</p>
        </div>
      )}
    </div>
  );
}
