"use client";

import { Fragment, useState, useEffect } from "react";
import {
  FileText, Plus, Trash2, Send, ChevronDown, ChevronUp,
  MessageSquare, ThumbsUp, Share2, AlertTriangle, Smile,
  Zap, BarChart2, Clock, Download, Loader2, Bookmark,
  Users, MapPin, Image as ImageIcon, ExternalLink,
} from "lucide-react";
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import GlassCard from "@/components/ui/GlassCard";
import LoadingSpinner from "@/components/ui/LoadingSpinner";
import StatusBadge from "@/components/ui/StatusBadge";
import DownloadButton from "@/components/ui/DownloadButton";
import { api, PostResult, Comment } from "@/lib/api";
import { useScrape } from "@/contexts/ScrapeContext";
import { usePersistState } from "@/hooks/usePersistState";

const SENTIMENT_COLORS: Record<string, string> = {
  "Positif":     "#1d7a47",
  "Negatif":     "#c0394f",
  "Netral":      "#8890aa",
  "Hate Speech": "#c0394f",
  "Toxic":       "#9e6c0a",
  "Humor":       "#9e6c0a",
  "Sarkasme":    "#6b5ec7",
};

const TXT_SECONDARY = { color: "#4a5070" };
const TXT_MUTED    = { color: "#8890aa" };

function fmtNum(n: number) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + "M";
  if (n >= 1_000)     return (n / 1_000).toFixed(1) + "K";
  return String(n);
}

interface CommentWithReplies extends Comment {
  replies: Comment[];
}

function groupComments(comments: Comment[]): CommentWithReplies[] {
  const topLevel: CommentWithReplies[] = [];
  const replyMap: Record<string | number, Comment[]> = {};
  for (const c of comments) {
    if (c.is_reply) {
      const parentKey = c.reply_to ?? "__orphan__";
      if (!replyMap[parentKey]) replyMap[parentKey] = [];
      replyMap[parentKey].push(c);
    } else {
      topLevel.push({ ...c, replies: [] });
    }
  }
  for (const parent of topLevel) {
    const byUsername = replyMap[parent.username] ?? [];
    const byNumber   = replyMap[parent.number]   ?? [];
    parent.replies   = [...byUsername, ...byNumber];
  }
  const orphans = replyMap["__orphan__"] ?? [];
  for (const o of orphans) topLevel.push({ ...o, replies: [] });
  return topLevel;
}

export default function PostScraperPage() {
  const { job, isRunning, start, finish, fail } = useScrape();
  const [urls, setUrls]               = useState<string[]>([""]);
  const [maxComments, setMax]         = useState(200);
  const [allComments, setAllComments] = useState(false);
  const [includeReplies, setReplies]  = useState(true);
  const [delay, setDelay]             = useState(30);
  const [expandedKeys, setExpKeys]    = useState<Set<string | number>>(new Set());
  const [filterCat, setFilter]        = useState<string>("ALL");
  const [formError, setFormError]     = useState<string | null>(null);
  const [page, setPage]               = useState(1);
  const PAGE_SIZE = 50;

  const [cachedResult, setCachedResult] = usePersistState<PostResult | null>("post-result", null);

  const ctxResult = job?.type === "post" && job.status !== "running" ? job.postResult : null;
  const scrapeErr = job?.type === "post" && job.status === "error"   ? job.error      : null;
  const isMyJob   = job?.type === "post";
  const isMyRun   = isRunning && isMyJob;
  const otherRun  = isRunning && !isMyJob;

  const result = ctxResult ?? cachedResult;

  useEffect(() => {
    if (ctxResult) setCachedResult(ctxResult);
  }, [ctxResult, setCachedResult]);

  const isBatch = urls.filter(Boolean).length > 1;
  const addUrl    = () => setUrls(p => [...p, ""]);
  const removeUrl = (i: number) => setUrls(p => p.filter((_, idx) => idx !== i));
  const setUrl    = (i: number, v: string) => setUrls(p => p.map((u, idx) => idx === i ? v : u));

  const toggleExpand = (key: string | number) => {
    setExpKeys(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };

  const isPostUrl = (url: string) => {
    if (!url.includes("facebook.com") && !url.includes("fb.com")) return false;
    return !(/facebook\.com\/[^/?#]+\/?(\?[^#]*)?$/.test(url) &&
      !/\/(posts|videos|photo|photos|reel|reels|share|permalink|watch|story|video)\//i.test(url) &&
      !/[?&](v|story_fbid|fbid)=/i.test(url));
  };

  const handleScrape = async () => {
    const valid = urls.map(u => u.trim()).filter(Boolean);
    if (!valid.length) { setFormError("Masukkan minimal satu URL post Facebook"); return; }
    if (isRunning) { setFormError("Scraping lain sedang berjalan, tunggu selesai dulu"); return; }
    const nonPost = valid.filter(u => !isPostUrl(u));
    if (nonPost.length) {
      setFormError(`URL bukan URL post spesifik: "${nonPost[0].slice(0, 60)}"\nGunakan URL post seperti: facebook.com/namahalaman/posts/123456`);
      return;
    }
    setFormError(null);
    const label = valid.length > 1 ? `${valid.length} post (batch)` : valid[0];
    start("post", label);
    const t0 = Date.now();
    try {
      if (isBatch) {
        const res = await api.scrape.batchPosts(valid, maxComments, delay);
        const first = (res.data?.results ?? []).find(r => r.success && r.data != null);
        const postResult = (first?.data as PostResult) ?? null;
        setCachedResult(postResult);
        finish({ postResult, elapsed: Math.round((Date.now() - t0) / 1000) });
      } else {
        const res = await api.scrape.post(valid[0], maxComments, includeReplies, allComments);
        const postResult = res.data ?? null;
        setCachedResult(postResult);
        finish({ postResult, elapsed: Math.round((Date.now() - t0) / 1000) });
      }
    } catch (e: unknown) {
      fail(e instanceof Error ? e.message : "Gagal scrape post");
    }
  };

  const categories = result ? ["ALL", ...new Set(result.comments.map((c: Comment) => c.category))] : ["ALL"];
  const handleFilterChange = (val: string) => { setFilter(val); setPage(1); };

  const flatFiltered: Comment[] = result
    ? filterCat === "ALL" ? result.comments : result.comments.filter((c: Comment) => c.category === filterCat)
    : [];
  const grouped = groupComments(flatFiltered);
  const totalPages = Math.max(1, Math.ceil(grouped.length / PAGE_SIZE));
  const safePage   = Math.min(page, totalPages);
  const pageStart  = (safePage - 1) * PAGE_SIZE;
  const pageEnd    = pageStart + PAGE_SIZE;
  const pagedGroups = grouped.slice(pageStart, pageEnd);

  const pieData = result?.sentiment_summary
    ? [
        { name: "Positif",     value: result.sentiment_summary.positive_count },
        { name: "Negatif",     value: result.sentiment_summary.negative_count },
        { name: "Netral",      value: result.sentiment_summary.neutral_count },
        { name: "Hate Speech", value: result.sentiment_summary.hate_speech_count },
        { name: "Toxic",       value: result.sentiment_summary.toxic_count },
        { name: "Humor",       value: result.sentiment_summary.humor_count },
        { name: "Sarkasme",    value: result.sentiment_summary.sarcasm_count },
      ].filter(d => d.value > 0)
    : [];

  const renderCommentRow = (c: Comment, isReply = false, rowIdx: number) => {
    const key = `${c.number}-${rowIdx}`;
    const expKey = c.number;
    const isExp = expandedKeys.has(expKey);
    return (
      <Fragment key={key}>
        <tr className="cursor-pointer" style={isReply ? { background: "rgba(59,109,206,0.03)" } : undefined}
          onClick={() => toggleExpand(expKey)}>
          <td className="text-xs" style={TXT_MUTED}>
            {isReply ? <span style={{ color: "rgba(59,109,206,0.4)" }}>↳</span> : c.number}
          </td>
          <td className="font-medium text-sm">
            <span style={isReply ? { color: "#3b6dce" } : { color: "#6b5ec7" }}>
              {isReply && <span style={TXT_MUTED}>↳ </span>}@{c.username}
            </span>
            {isReply && c.reply_to && <span className="block text-xs" style={TXT_MUTED}>ke @{c.reply_to}</span>}
          </td>
          <td className="max-w-xs">
            <p className={`text-sm truncate ${isReply ? "pl-3" : ""}`}
              style={isReply ? { borderLeft: "2px solid rgba(59,109,206,0.3)" } : undefined}>{c.text}</p>
          </td>
          <td><StatusBadge category={c.category} /></td>
          <td className="text-sm">{c.like_count}</td>
          <td className="text-sm" style={TXT_MUTED}>{((c.ml_confidence ?? 0) * 100).toFixed(0)}%</td>
        </tr>
        {isExp && (
          <tr key={`exp-${key}`}>
            <td colSpan={6} className="px-4 pb-3">
              <div className="rounded-xl p-4 text-sm space-y-2" style={{ background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.06)" }}>
                <p style={{ color: "#1a1c23" }}>{c.text}</p>
                <div className="flex flex-wrap gap-3 text-xs" style={TXT_MUTED}>
                  <span>Bahasa: {c.language}</span>
                  <span>Source: {c.decision_source}</span>
                  <span>Hate: {c.is_hate_speech ? "✓" : "—"}</span>
                  <span>Toxic: {c.is_toxic ? "✓" : "—"}</span>
                  <span>Sarkasme: {c.is_sarcasm ? "✓" : "—"}</span>
                  {c.emojis?.length > 0 && <span>Emojis: {c.emojis.join(" ")}</span>}
                </div>
              </div>
            </td>
          </tr>
        )}
      </Fragment>
    );
  };

  const renderGroup = (parent: CommentWithReplies, groupIdx: number) => {
    const hasReplies  = parent.replies.length > 0;
    const repliesKey  = `replies-${parent.number}`;
    const showReplies = expandedKeys.has(repliesKey);
    return (
      <Fragment key={`group-${parent.number}-${groupIdx}`}>
        {renderCommentRow(parent, false, groupIdx)}
        {hasReplies && (
          <tr key={`toggle-${parent.number}`} className="cursor-pointer"
            onClick={() => toggleExpand(repliesKey)} style={{ background: "rgba(59,109,206,0.02)" }}>
            <td colSpan={6}>
              <div className="flex items-center gap-2 px-4 py-1.5 text-xs" style={{ color: "rgba(59,109,206,0.7)" }}>
                {showReplies ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
                {showReplies ? `Sembunyikan ${parent.replies.length} balasan` : `Tampilkan ${parent.replies.length} balasan`}
              </div>
            </td>
          </tr>
        )}
        {hasReplies && showReplies && parent.replies.map((reply, ri) => renderCommentRow(reply, true, groupIdx * 10000 + ri))}
      </Fragment>
    );
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold gradient-text mb-1" style={{ fontFamily: "var(--font-sora)" }}>Scrape Post</h1>
        <p className="text-sm" style={TXT_MUTED}>Ambil komentar dan analisis sentimen dari post Facebook</p>
      </div>

      {otherRun && (
        <GlassCard glow="purple">
          <div className="flex items-center gap-3">
            <Loader2 size={15} className="animate-spin shrink-0" style={{ color: "#6b5ec7" }} />
            <p className="text-sm" style={{ color: "#6b5ec7" }}>Scraping profil sedang berjalan di background. Tunggu selesai sebelum scrape post.</p>
          </div>
        </GlassCard>
      )}

      <GlassCard>
        <h2 className="font-semibold mb-1 flex items-center gap-2" style={{ color: "#1a1c23" }}>
          <FileText size={16} style={{ color: "#6b5ec7" }} />URL Post Facebook
        </h2>
        <p className="text-xs mb-4" style={TXT_MUTED}>
          URL post, video, reel, atau share link — contoh:{" "}
          <span className="font-mono" style={{ color: "#6b5ec7" }}>facebook.com/share/v/18biJvNvty/</span>
        </p>

        <div className="space-y-2 mb-4">
          {urls.map((url, i) => (
            <div key={i} className="flex gap-2">
              <input type="text" value={url} onChange={e => setUrl(i, e.target.value)}
                placeholder="https://www.facebook.com/share/v/... atau /posts/..."
                className="glass-input flex-1 px-4 py-2.5 text-sm" disabled={isMyRun} />
              {urls.length > 1 && (
                <button onClick={() => removeUrl(i)} disabled={isMyRun}
                  className="btn-glass px-3 py-2" style={{ color: "#c0394f" }}><Trash2 size={14} /></button>
              )}
            </div>
          ))}
        </div>

        <button onClick={addUrl} disabled={isMyRun} className="btn-glass flex items-center gap-2 px-4 py-2 text-sm mb-5">
          <Plus size={14} />Tambah URL
        </button>

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
          <div>
            <label className="text-xs font-medium mb-2 block" style={TXT_MUTED}>
              Jumlah Komentar {allComments && <span style={{ color: "#6b5ec7" }}>(semua)</span>}
            </label>
            <input type="number" value={maxComments} onChange={e => setMax(Number(e.target.value))}
              min={10} max={100000} disabled={isMyRun || allComments} className="glass-input w-full px-4 py-2.5 text-sm disabled:opacity-40" />
          </div>
          {isBatch && (
            <div>
              <label className="text-xs font-medium mb-2 block" style={TXT_MUTED}>Jeda Antar Request (detik)</label>
              <input type="number" value={delay} onChange={e => setDelay(Number(e.target.value))}
                min={10} disabled={isMyRun} className="glass-input w-full px-4 py-2.5 text-sm" />
            </div>
          )}
        </div>

        <div className="flex flex-wrap gap-3 mb-5">
          <label className="flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer text-sm"
            style={{ background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)", color: TXT_SECONDARY.color }}>
            <input type="checkbox" checked={allComments} onChange={e => setAllComments(e.target.checked)}
              disabled={isMyRun} className="w-4 h-4 accent-violet-600" />
            Ambil semua komentar
          </label>
          <label className="flex items-center gap-2 px-3 py-2 rounded-xl cursor-pointer text-sm"
            style={{ background: "rgba(0,0,0,0.03)", border: "1px solid rgba(0,0,0,0.08)", color: TXT_SECONDARY.color }}>
            <input type="checkbox" checked={includeReplies} onChange={e => setReplies(e.target.checked)}
              disabled={isMyRun} className="w-4 h-4 accent-violet-600" />
            Sertakan balasan
          </label>
        </div>

        {allComments && <p className="text-xs mb-4 -mt-1" style={{ color: "#9e6c0a" }}>⚠️ Mode "semua komentar" bisa memakan beberapa menit untuk post dengan ribuan komentar.</p>}

        <button onClick={handleScrape} disabled={isRunning || !urls.some(u => u.trim())}
          className="btn-primary flex items-center gap-2 px-6 py-2.5 text-sm">
          {isMyRun ? <LoadingSpinner size={16} /> : <Send size={14} />}
          {isMyRun ? "Sedang scraping..." : isBatch ? `Scrape ${urls.filter(Boolean).length} Post` : "Scrape Post"}
        </button>

        {isMyRun && (
          <div className="mt-3 p-3 rounded-xl flex items-center gap-2 text-xs"
            style={{ background: "rgba(107,94,199,0.06)", border: "1px solid rgba(107,94,199,0.15)", color: "#6b5ec7" }}>
            <Loader2 size={12} className="animate-spin shrink-0" />
            Scraping berjalan di background. Anda bisa pindah halaman, hasil tetap tersimpan.
          </div>
        )}
      </GlassCard>

      {formError && (
        <GlassCard glow="pink">
          <div className="flex gap-3 items-start">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" style={{ color: "#c0394f" }} />
            <p className="text-sm" style={{ color: "#c0394f" }}>{formError}</p>
          </div>
        </GlassCard>
      )}

      {scrapeErr && (
        <GlassCard glow="pink">
          <div className="flex gap-3 items-start">
            <AlertTriangle size={16} className="shrink-0 mt-0.5" style={{ color: "#c0394f" }} />
            <p className="text-sm" style={{ color: "#c0394f" }}>{scrapeErr}</p>
          </div>
        </GlassCard>
      )}

      {result && (
        <>
          <GlassCard glow="purple">
            <div className="flex items-start justify-between gap-4 flex-wrap">
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 mb-1">
                  <p className="text-xs" style={TXT_MUTED}>{result.scraped_at}</p>
                  {result.post_type && result.post_type !== "post" && (
                    <span className="badge" style={{ background: "rgba(107,94,199,0.1)", color: "#6b5ec7", border: "1px solid rgba(107,94,199,0.2)" }}>
                      {result.post_type.toUpperCase()}
                    </span>
                  )}
                </div>
                <p className="font-medium text-sm leading-relaxed whitespace-pre-wrap wrap-break-word" style={{ color: "#1a1c23" }}>
                  {result.caption || "(tidak ada caption)"}
                </p>
                {(result.with_tags !== undefined && result.with_tags.length > 0 || result.location || result.media_type) && (
                  <div className="flex flex-wrap items-center gap-2 mt-2 text-xs" style={TXT_MUTED}>
                    {result.with_tags !== undefined && result.with_tags.length > 0 && (
                      <span className="flex items-center gap-1"><Users size={11} style={{ color: "#2193b0" }} />
                        bersama {(result.with_tags as string[]).join(", ")}{result.with_others ? ` +${result.with_others} lainnya` : ""}
                      </span>
                    )}
                    {result.location && <span className="flex items-center gap-1"><MapPin size={11} style={{ color: "#1d7a47" }} />{result.location}</span>}
                    {result.media_type && <span className="flex items-center gap-1"><ImageIcon size={11} style={{ color: "#6b5ec7" }} />
                      {result.media_type}{result.media_count ? ` (${result.media_count})` : ""}</span>}
                  </div>
                )}
                {result.mentions !== undefined && result.mentions.length > 0 && (
                  <div className="flex flex-wrap gap-1.5 mt-2">
                    {(result.mentions as string[]).slice(0, 10).map((m: string) => (
                      <span key={m} className="px-2 py-0.5 rounded-full text-xs"
                        style={{ background: "rgba(59,109,206,0.08)", color: "#3b6dce", border: "1px solid rgba(59,109,206,0.15)" }}>@{m}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="flex gap-4 shrink-0">
                {[
                  { icon: ThumbsUp,      val: fmtNum(result.total_likes),   label: "Likes" },
                  { icon: MessageSquare, val: fmtNum(result.total_comments), label: "Komentar" },
                  { icon: Share2,        val: fmtNum(result.total_shares),   label: "Shares" },
                  { icon: Bookmark,      val: "—",                           label: "Saves" },
                ].map(({ icon: Icon, val, label }) => (
                  <div key={label} className="text-center" title={label === "Saves" ? "Facebook tidak mengekspos jumlah save ke publik" : undefined}>
                    <Icon size={16} className="mx-auto mb-1" style={{ color: "#6b5ec7" }} />
                    <p className="font-bold text-lg" style={{ color: "#1a1c23" }}>{val}</p>
                    <p className="text-xs" style={TXT_MUTED}>{label}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="mt-4 flex items-center gap-3 flex-wrap">
              <DownloadButton data={result}
                filename={`fb-post-${result.post_id || result.url?.split("/").pop() || "unknown"}`}
                label="Download Full Data" />
              <DownloadButton data={result.comments}
                filename={`fb-post-${result.post_id || "unknown"}-comments`}
                label="Download Komentar" />
            </div>

            {result.media_urls && result.media_urls.length > 0 && (
              <div className={`mt-4 grid gap-2 ${result.media_urls.length > 1 ? "grid-cols-2 sm:grid-cols-3" : "grid-cols-1 max-w-md"}`}>
                {result.media_urls.slice(0, 6).map((src: string, i: number) => (
                  <a key={i} href={result.url} target="_blank" rel="noopener noreferrer"
                    className="block rounded-xl overflow-hidden" style={{ border: "1px solid rgba(0,0,0,0.08)" }}>
                    <img src={src} alt={`media ${i + 1}`} referrerPolicy="no-referrer" loading="lazy"
                      className="w-full h-44 object-cover"
                      onError={(e) => { const a = e.currentTarget.parentElement as HTMLElement | null; if (a) a.style.display = "none"; }} />
                  </a>
                ))}
              </div>
            )}

            <div className="mt-4 flex items-center gap-4 text-xs flex-wrap" style={TXT_MUTED}>
              <span className="flex items-center gap-1"><MessageSquare size={12} />
                {result.comments_count} diambil
                {result.replies_count !== undefined && result.replies_count > 0 && ` (${result.top_level_count} komentar + ${result.replies_count} balasan)`}
              </span>
              {result._meta && <span className="flex items-center gap-1"><Clock size={12} />{result._meta.elapsed_seconds}s</span>}
              {result.url && (
                <a href={result.url} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-1" style={{ color: "#3b6dce" }}>
                  <ExternalLink size={12} /> Buka post di Facebook
                </a>
              )}
              {result._meta?.saved_file && <span className="flex items-center gap-1"><Download size={12} />{result._meta.saved_file}</span>}
            </div>
          </GlassCard>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <GlassCard>
              <h3 className="font-semibold mb-4 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <BarChart2 size={16} style={{ color: "#3b6dce" }} />Distribusi Sentimen
              </h3>
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height={260}>
                  <PieChart>
                    <Pie data={pieData} cx="50%" cy="50%" innerRadius={55} outerRadius={95} paddingAngle={2} dataKey="value">
                      {pieData.map(entry => <Cell key={entry.name} fill={SENTIMENT_COLORS[entry.name] ?? "#8890aa"} stroke="transparent" />)}
                    </Pie>
                    <Tooltip contentStyle={{ background: "white", border: "1px solid rgba(0,0,0,0.1)", borderRadius: "10px", color: "#1a1c23", fontSize: 12 }}
                      formatter={(v) => [`${v ?? 0} komentar`, ""]} />
                    <Legend wrapperStyle={{ fontSize: 12, color: TXT_MUTED.color }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <p className="text-sm text-center py-8" style={TXT_MUTED}>Tidak ada data sentimen</p>
              )}
            </GlassCard>

            <GlassCard>
              <h3 className="font-semibold mb-4 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <Zap size={16} style={{ color: "#9e6c0a" }} />Ringkasan Sentimen
              </h3>
              {result.sentiment_summary && (
                <div className="space-y-3">
                  {[
                    { label: "Positif",     pct: result.sentiment_summary.positive_percentage,     color: "#1d7a47" },
                    { label: "Negatif",     pct: result.sentiment_summary.negative_percentage,     color: "#c0394f" },
                    { label: "Netral",      pct: result.sentiment_summary.neutral_percentage,      color: "#8890aa" },
                    { label: "Hate Speech", pct: result.sentiment_summary.hate_percentage,         color: "#c0394f" },
                    { label: "Toxic",       pct: result.sentiment_summary.toxic_percentage,        color: "#9e6c0a" },
                    { label: "Humor",       pct: result.sentiment_summary.humor_percentage ?? 0,   color: "#9e6c0a" },
                  ].map(({ label, pct, color }) => (
                    <div key={label}>
                      <div className="flex justify-between text-xs mb-1" style={TXT_SECONDARY}>
                        <span>{label}</span><span style={{ color }}>{pct.toFixed(1)}%</span>
                      </div>
                      <div className="progress-bar"><div className="progress-fill" style={{ width: `${Math.min(pct, 100)}%`, background: color }} /></div>
                    </div>
                  ))}
                  <p className="text-xs pt-2" style={TXT_MUTED}>
                    Avg ML confidence: {((result.sentiment_summary.avg_ml_confidence ?? 0) * 100).toFixed(1)}%
                  </p>
                </div>
              )}
            </GlassCard>
          </div>

          {result.sentiment_summary?.most_active_users?.length > 0 && (
            <GlassCard>
              <h3 className="font-semibold mb-3 flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <Smile size={16} style={{ color: "#2193b0" }} />Pengguna Paling Aktif
              </h3>
              <div className="flex flex-wrap gap-2">
                {result.sentiment_summary.most_active_users.slice(0, 10).map((u: { username: string; count: number }) => (
                  <span key={u.username} className="px-3 py-1 rounded-full text-xs font-medium"
                    style={{ background: "rgba(107,94,199,0.08)", border: "1px solid rgba(107,94,199,0.15)", color: "#6b5ec7" }}>
                    @{u.username} ({u.count})
                  </span>
                ))}
              </div>
            </GlassCard>
          )}

          <GlassCard padding="p-0">
            <div className="p-5 flex items-center justify-between flex-wrap gap-3">
              <h3 className="font-semibold flex items-center gap-2" style={{ color: "#1a1c23" }}>
                <MessageSquare size={16} style={{ color: "#6b5ec7" }} />
                Komentar ({flatFiltered.length})
                {flatFiltered.length !== grouped.length && (
                  <span className="text-xs font-normal" style={TXT_MUTED}>
                    · {grouped.filter(g => g.replies.length > 0).length} thread berbalasan
                  </span>
                )}
              </h3>
              <div className="flex items-center gap-2">
                <DownloadButton data={flatFiltered} filename={`fb-post-${result.post_id || "unknown"}-comments-filtered`}
                  label="Download CSV" className="px-2 py-1 text-xs" />
                <select value={filterCat} onChange={e => handleFilterChange(e.target.value)} className="glass-input px-3 py-1.5 text-xs">
                  {categories.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
              </div>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full glass-table">
                <thead><tr><th>#</th><th>Username</th><th>Komentar</th><th>Kategori</th><th>Likes</th><th>Confidence</th></tr></thead>
                <tbody>{pagedGroups.map((parent, gi) => renderGroup(parent, pageStart + gi))}</tbody>
              </table>
              <div className="flex items-center justify-between gap-3 px-4 py-4 flex-wrap">
                <p className="text-xs" style={TXT_MUTED}>
                  Menampilkan {pageStart + 1}-{Math.min(pageEnd, grouped.length)} dari {grouped.length} thread komentar (halaman {safePage} dari {totalPages})
                </p>
                <div className="flex items-center gap-2">
                  <button onClick={() => setPage(p => Math.max(1, p - 1))} disabled={safePage <= 1}
                    className="btn-glass px-3 py-1.5 text-xs disabled:opacity-40">← Sebelumnya</button>
                  <span className="text-xs px-2" style={TXT_SECONDARY}>{safePage} / {totalPages}</span>
                  <button onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={safePage >= totalPages}
                    className="btn-glass px-3 py-1.5 text-xs disabled:opacity-40">Selanjutnya →</button>
                </div>
              </div>
            </div>
          </GlassCard>
        </>
      )}
    </div>
  );
}