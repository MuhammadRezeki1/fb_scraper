"use client";

import { createContext, useContext, useState, useCallback, ReactNode } from "react";
import type { PostResult, ProfileData, KeywordResult } from "@/lib/api";

export type JobType   = "post" | "profile" | "keyword" | "deep";
export type JobStatus = "running" | "done" | "error";

export interface ScrapeJob {
  id:             string;
  type:           JobType;
  status:         JobStatus;
  label:          string;
  postResult:     PostResult | null;
  profileResults: ProfileData[];
  keywordResult:  KeywordResult | null;
  deepPosts:      unknown[];
  error:          string | null;
  startedAt:      number;
  finishedAt:     number | null;
  elapsed:        number | null;
}

interface ScrapeCtx {
  job:                ScrapeJob | null;
  isRunning:          boolean;
  pendingAutoFillUrl: string | null;         // ✅ URL auto-fill untuk scrape/posts
  start:     (type: JobType, label: string) => void;
  finish:    (data: {
    postResult?:     PostResult | null;
    profileResults?: ProfileData[];
    keywordResult?:  KeywordResult | null;
    deepPosts?:      unknown[];
    elapsed?:        number;
  }) => void;
  fail:      (error: string) => void;
  clear:     () => void;
  setAutoFillUrl: (url: string | null) => void;  // ✅ set URL auto-fill
}

const ScrapeContext = createContext<ScrapeCtx>({
  job: null, isRunning: false, pendingAutoFillUrl: null,
  start: () => {}, finish: () => {}, fail: () => {}, clear: () => {},
  setAutoFillUrl: () => {},
});

export function ScrapeProvider({ children }: { children: ReactNode }) {
  const [job, setJob] = useState<ScrapeJob | null>(null);
  const [pendingAutoFillUrl, setPendingAutoFillUrl] = useState<string | null>(null);

  const start = useCallback((type: JobType, label: string) => {
    setJob({
      id:             Math.random().toString(36).slice(2),
      type, status:   "running", label,
      postResult:     null,
      profileResults: [],
      keywordResult:  null,
      deepPosts:      [],
      error:          null,
      startedAt:      Date.now(),
      finishedAt:     null,
      elapsed:        null,
    });
  }, []);

  const finish = useCallback((
    data: {
      postResult?:     PostResult | null;
      profileResults?: ProfileData[];
      keywordResult?:  KeywordResult | null;
      deepPosts?:      unknown[];
      elapsed?:        number;
    }
  ) => {
    setJob(prev => prev ? {
      ...prev,
      status:         "done",
      postResult:     data.postResult     !== undefined ? data.postResult     : prev.postResult,
      profileResults: data.profileResults !== undefined ? data.profileResults : prev.profileResults,
      keywordResult:  data.keywordResult  !== undefined ? data.keywordResult  : prev.keywordResult,
      deepPosts:      data.deepPosts      !== undefined ? data.deepPosts      : prev.deepPosts,
      elapsed:        data.elapsed ?? null,
      finishedAt:     Date.now(),
    } : null);
  }, []);

  const fail = useCallback((error: string) => {
    setJob(prev => prev ? { ...prev, status: "error", error, finishedAt: Date.now() } : null);
  }, []);

  const clear = useCallback(() => setJob(null), []);

  const setAutoFillUrl = useCallback((url: string | null) => {
    setPendingAutoFillUrl(url);
  }, []);

  return (
    <ScrapeContext.Provider value={{
      job,
      isRunning: job?.status === "running",
      pendingAutoFillUrl,
      start, finish, fail, clear,
      setAutoFillUrl,
    }}>
      {children}
    </ScrapeContext.Provider>
  );
}

export const useScrape = () => useContext(ScrapeContext);