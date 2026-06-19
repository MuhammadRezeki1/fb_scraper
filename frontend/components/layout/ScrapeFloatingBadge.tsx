"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { CheckCircle, XCircle, Loader2, X } from "lucide-react";
import { useScrape } from "@/contexts/ScrapeContext";

export default function ScrapeFloatingBadge() {
  const { job, clear } = useScrape();
  const [elapsed, setElapsed]     = useState(0);
  const [dismissed, setDismissed] = useState(false);
  const startedAtRef              = useRef(0);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    startedAtRef.current = job.startedAt;
    setElapsed(0);
    const id = setInterval(() => {
      setElapsed(Math.round((Date.now() - startedAtRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.id, job?.status]);

  useEffect(() => { if (job) setDismissed(false); }, [job?.id]);

  useEffect(() => {
    if (job?.status === "done" || job?.status === "error") {
      const id = setTimeout(() => setDismissed(true), 10_000);
      return () => clearTimeout(id);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [job?.status, job?.id]);

  if (!job || dismissed) return null;

  const typeLabel  = job.type === "post" ? "Post" : job.type === "profile" ? "Profil" : job.type;
  const resultPath = job.type === "post" ? "/scrape/posts" : job.type === "profile" ? "/scrape/profiles" : "/";

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
              {job.type === "post"    && job.postResult           ? ` · ${job.postResult.comments_count} komentar` : ""}
              {job.type === "profile" && job.profileResults.length ? ` · ${job.profileResults.length} profil`     : ""}
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