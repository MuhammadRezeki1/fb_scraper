"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { CheckCircle, XCircle, Loader2, X } from "lucide-react";
import { useScrape } from "@/contexts/ScrapeContext";
import { api, type DeepPost } from "@/lib/api";

function readPersistedDeepJobId(): string | null {
  try {
    const raw = sessionStorage.getItem("fb-scrape:deep-active-job-id");
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    return typeof parsed === "string" ? parsed : null;
  } catch {
    return null;
  }
}

function persistDeepPosts(posts: DeepPost[]) {
  try {
    sessionStorage.setItem("fb-scrape:deep-posts-v2", JSON.stringify(posts));
  } catch {
    // Ignore storage quota errors; the Deep page can still fetch from backend.
  }
}

export default function ScrapeFloatingBadge() {
  const pathname = usePathname();
  const { job, clear, finish, fail } = useScrape();
  const [elapsed, setElapsed]     = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const startedAtRef              = useRef(0);
  const jobId                     = job?.id;
  const jobStatus                 = job?.status;
  const jobStartedAt              = job?.startedAt;
  const jobType                   = job?.type;
  const deepPollInFlightRef       = useRef(false);

  useEffect(() => {
    if (!jobStartedAt || jobStatus !== "running") return;
    startedAtRef.current = jobStartedAt;
    const resetId = window.setTimeout(() => setElapsed(0), 0);
    const id = window.setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAtRef.current) / 1000));
    }, 1000);
    return () => {
      window.clearTimeout(resetId);
      window.clearInterval(id);
    };
  }, [jobId, jobStatus, jobStartedAt]);

  useEffect(() => {
    if (!jobId) return;
    const id = window.setTimeout(() => setDismissed(false), 0);
    return () => window.clearTimeout(id);
  }, [jobId]);

  useEffect(() => {
    if (jobStatus === "done" || jobStatus === "error") {
      const id = window.setTimeout(() => setDismissed(true), 10_000);
      return () => window.clearTimeout(id);
    }
  }, [jobStatus, jobId]);

  useEffect(() => {
    if (jobType !== "deep" || jobStatus !== "running") return;
    if (pathname === "/monitor/deep") return;

    let ignore = false;
    const pollDeepJob = async () => {
      const jobId = readPersistedDeepJobId();
      if (!jobId) return;
      if (deepPollInFlightRef.current) return;
      deepPollInFlightRef.current = true;

      try {
        const statusRes = await api.deep.jobStatus(jobId);
        const status = statusRes.data?.status;
        if (!status || status === "running" || status === "pending") return;

        if (status === "completed") {
          const postsRes = await api.deep.jobPosts(jobId);
          const posts = postsRes.data?.posts || [];
          if (ignore) return;
          persistDeepPosts(posts);
          finish({ deepPosts: posts, elapsed: undefined });
        } else if (status === "error") {
          if (!ignore) fail(statusRes.data?.error || "Deep search gagal di backend");
        } else if (status === "cancelled") {
          if (!ignore) finish({ deepPosts: [], elapsed: undefined });
        }
      } catch (err) {
        console.warn("Deep badge polling error:", err);
      } finally {
        deepPollInFlightRef.current = false;
      }
    };

    pollDeepJob();
    const id = window.setInterval(pollDeepJob, 15000);
    return () => {
      ignore = true;
      deepPollInFlightRef.current = false;
      window.clearInterval(id);
    };
  }, [jobType, jobStatus, pathname, finish, fail]);

  if (!job || dismissed) return null;

  const typeLabel  = job.type === "post" ? "Post" : job.type === "profile" ? "Profil" : job.type === "deep" ? "Deep Search" : job.type;
  const resultPath = job.type === "post" ? "/scrape/posts" : job.type === "profile" ? "/scrape/profiles" : job.type === "deep" ? "/monitor/deep" : "/";

  return (
    <div
      className="fixed bottom-6 right-6 z-50"
      style={{
        width:          "300px",
        background:     "rgba(255,255,255,0.95)",
        backdropFilter: "blur(24px)",
        border:         "1px solid rgba(0,0,0,0.08)",
        borderRadius:   "16px",
        boxShadow:      "0 8px 40px rgba(0,0,0,0.12)",
        overflow:       "hidden",
      }}
    >
      <div
        className="h-0.5"
        style={{
          background:
            job.status === "running" ? "linear-gradient(90deg,#6b5ec7,#3b6dce,#2193b0)" :
            job.status === "done"    ? "linear-gradient(90deg,#1d7a47,#16a34a)" :
                                       "linear-gradient(90deg,#c0394f,#dc2626)",
        }}
      />

      <div className="p-4">
        <div className="flex items-center justify-between mb-1.5">
          <div className="flex items-center gap-2">
            {job.status === "running" && <Loader2 size={13} className="animate-spin" style={{ color: "#6b5ec7" }} />}
            {job.status === "done"    && <CheckCircle size={13} style={{ color: "#1d7a47" }} />}
            {job.status === "error"   && <XCircle size={13} style={{ color: "#c0394f" }} />}
            <span className="text-xs font-semibold" style={{ color: "#1a1c23" }}>
              {job.status === "running" && `Sedang scraping ${typeLabel}...`}
              {job.status === "done"    && `Scrape ${typeLabel} selesai!`}
              {job.status === "error"   && `Scrape ${typeLabel} gagal`}
            </span>
          </div>
          {job.status !== "running" && (
            <button onClick={() => { setDismissed(true); clear(); }}
              className="p-0.5 rounded transition-colors" style={{ color: "#8890aa" }}>
              <X size={12} />
            </button>
          )}
        </div>

        <p className="text-xs truncate mb-3" style={{ color: "#8890aa" }}>
          {job.label}
        </p>

        {job.status === "running" && (
          <div className="flex items-center gap-3">
            <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: "rgba(0,0,0,0.06)" }}>
              <div className="h-full rounded-full progress-indeterminate"
                style={{ width: "45%", background: "linear-gradient(90deg,#6b5ec7,#3b6dce)" }} />
            </div>
            <span className="text-xs font-mono shrink-0" style={{ color: "#8890aa" }}>
              {elapsed}s
            </span>
          </div>
        )}

        {job.status === "done" && (
          <div className="flex items-center justify-between">
            <p className="text-xs" style={{ color: "#1d7a47" }}>
              {job.elapsed != null && `${job.elapsed}s`}
              {job.type === "deep" && job.deepPosts.length ? ` - ${job.deepPosts.length} hasil` : ""}
              {job.type === "post" && job.postResult ? ` - ${job.postResult.comments_count} komentar` : ""}
              {job.type === "profile" && job.profileResults.length ? ` - ${job.profileResults.length} profil` : ""}
            </p>
            <Link href={resultPath}
              className="text-xs underline underline-offset-2 transition-colors" style={{ color: "#6b5ec7" }}>
              Lihat Hasil →
            </Link>
          </div>
        )}

        {job.status === "error" && (
          <p className="text-xs" style={{ color: "#c0394f" }}>{job.error}</p>
        )}
      </div>
    </div>
  );
}
