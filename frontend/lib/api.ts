// lib/api.ts
// ============================================================================
//  Facebook Scraper API Client (Full TypeScript)
//  Support: Keyword, Hashtag, Trending, Post, Profile, Growth Tracking
//  + Deep Monitoring (multi-query, auto-discovery, related topics)
// ============================================================================

const BASE = (process.env.NEXT_PUBLIC_API_BASE_PATH ?? "/api/v1").replace(/\/$/, "");

// ----------------------------------------------------------------------------
//  Helper: Request dengan fetch + JSON handling + sanitasi NaN/Infinity
// ----------------------------------------------------------------------------
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });

  const contentType = res.headers.get("content-type") ?? "";
  if (!contentType.includes("application/json")) {
    throw new Error(
      res.ok
        ? `Backend mengembalikan respons bukan JSON (${res.status})`
        : `Backend tidak dapat dijangkau atau endpoint belum tersedia (${res.status}). Pastikan backend sudah direstart.`
    );
  }

  // ✅ FIX: Custom JSON parsing yang handle NaN/Infinity
  let json;
  try {
    const text = await res.text();
    // Replace NaN, Infinity, -Infinity dengan 0 sebelum parse
    const sanitized = text
      .replace(/:\s*NaN/g, ': 0')
      .replace(/:\s*Infinity/g, ': 0')
      .replace(/:\s*-Infinity/g, ': 0')
      .replace(/,\s*NaN/g, ', 0')
      .replace(/,\s*Infinity/g, ', 0');
    json = JSON.parse(sanitized);
  } catch (parseErr) {
    throw new Error(`Gagal parse JSON response: ${(parseErr as Error).message}`);
  }

  // Special case: cancelled job is not a real error for polling
  if (!json.success) {
    const msg = json.message || "";
    // If status >= 400, throw error. Otherwise return the json with success=false
    // so callers can check json.success themselves.
    if (res.status >= 400) {
      throw new Error(msg || "Request failed");
    }
  }
  return json;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// ----------------------------------------------------------------------------
//  Job polling (untuk scrape yang lama) - ✅ OPTIMIZED VERSION
// ----------------------------------------------------------------------------
interface JobState<T> {
  job_id: string;
  type: string;
  status: "running" | "done" | "error" | "completed";
  result: T | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
}

// Polling dengan exponential backoff + null safety
async function runScrapeJob<T>(
  path: string,
  body: unknown,
  {
    pollMs = 5000,
    timeoutMs = 900_000,
    maxPollMs = 15000,
  }: {
    pollMs?: number;
    timeoutMs?: number;
    maxPollMs?: number;
  } = {}
): Promise<T> {
  const startRes = await request<ApiResponse<{ job_id: string }>>(path, {
    method: "POST",
    body: JSON.stringify(body),
  });

  const jobId = startRes.data?.job_id;
  if (!jobId) throw new Error("Gagal memulai job scrape (job_id kosong)");

  const deadline = Date.now() + timeoutMs;
  let currentPollMs = pollMs;
  let consecutiveErrors = 0;

  while (Date.now() < deadline) {
    await sleep(currentPollMs);

    try {
      const res = await request<ApiResponse<JobState<T>>>(`/scrape/job/${jobId}`);
      const st = res.data;
      consecutiveErrors = 0;

      if (!st) {
        continue;
      }

      if (st.status === "done" || st.status === "completed") {
        if (st.result == null) throw new Error("Job selesai tapi hasil kosong");
        return st.result;
      }

      if (st.status === "error") {
        throw new Error(st.error || "Scrape gagal di server");
      }

      if (currentPollMs < maxPollMs) {
        currentPollMs = Math.min(currentPollMs * 1.2, maxPollMs);
      }
    } catch {
      consecutiveErrors++;
      if (consecutiveErrors >= 5) {
        throw new Error(`Gagal polling status job setelah ${consecutiveErrors} percobaan`);
      }

      await sleep(Math.min(1000 * Math.pow(2, consecutiveErrors), 10000));
      continue;
    }
  }

  throw new Error("Timeout menunggu hasil scrape (job masih berjalan di server)");
}

function wrap<T>(data: T): ApiResponse<T> {
  return { success: true, message: "ok", timestamp: new Date().toISOString(), data };
}

// ============================================================================
//  API Object
// ============================================================================
export const api = {
  health: () => request<ApiResponse<HealthData>>("/health"),
  dashboard: () => request<ApiResponse<DashboardData>>("/dashboard"),

  auth: {
    status: () => request<ApiResponse<AuthStatus>>("/auth/status"),
    login: (timeout_minutes = 5, headless = false) =>
      request<ApiResponse<unknown>>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ timeout_minutes, headless }),
      }),
    logout: (hard_reset = false) =>
      request<ApiResponse<unknown>>("/auth/logout", {
        method: "POST",
        body: JSON.stringify({ hard_reset }),
      }),
    sessionInfo: () => request<ApiResponse<unknown>>("/auth/session-info"),
    importCookies: (cookies: unknown[], username?: string) =>
      request<ApiResponse<ImportCookiesResult>>("/auth/import-cookies", {
        method: "POST",
        body: JSON.stringify({ cookies, username: username ?? "" }),
      }),
  },

  scrape: {
    post: async (
      url: string,
      max_comments = 200,
      include_replies = true,
      all_comments = false,
      scrape_reactors = false,
      max_reactors = 200
    ) =>
      wrap(
        await runScrapeJob<PostResult>(
          "/scrape/post",
          { url, max_comments, include_replies, all_comments, scrape_reactors, max_reactors },
          { timeoutMs: all_comments ? 3_600_000 : 900_000, pollMs: all_comments ? 5000 : 3000 }
        )
      ),
    batchPosts: async (urls: string[], max_comments = 200, delay_between = 30) =>
      wrap(
        await runScrapeJob<BatchResult>("/scrape/posts/batch", { urls, max_comments, delay_between }, {
          timeoutMs: 3_600_000,
          pollMs: 5000,
        })
      ),
    profile: async (username: string, save_tracking = true) =>
      wrap(await runScrapeJob<ProfileResult>("/scrape/profile", { username, save_tracking })),
    batchProfiles: async (usernames: string[], delay_between = 30, save_tracking = true) =>
      wrap(
        await runScrapeJob<BatchResult>("/scrape/profiles/batch", { usernames, delay_between, save_tracking }, {
          timeoutMs: 3_600_000,
          pollMs: 5000,
        })
      ),
    job: (jobId: string) => request<ApiResponse<JobState<unknown>>>(`/scrape/job/${jobId}`),
    lastResult: (type: "post" | "profile") =>
      request<ApiResponse<unknown>>(`/scrape/last-result?type=${type}`),
  },

  monitor: {
    keyword: async (
      keyword: string,
      max_results = 300,
      types: string[] = ["posts"],
      options: MonitorOptions = {}
    ) =>
      wrap(
        await runScrapeJob<KeywordResult>("/monitor/keyword", { keyword, max_results, types, ...options }, {
          timeoutMs: 3_600_000,
          pollMs: 5000,
        })
      ),

    hashtag: async (hashtag: string, max_results = 1000, options: MonitorOptions = {}) =>
      wrap(
        await runScrapeJob<KeywordResult>("/monitor/hashtag", { hashtag, max_results, ...options }, {
          timeoutMs: 3_600_000,
          pollMs: 5000,
        })
      ),

    trending: async (
      max_results = 1000,
      sort_by: MonitorSort = "trending",
      keyword: string = "",
      types: string[] = ["posts", "videos", "groups", "pages"],
      options: MonitorOptions = {}
    ) =>
      wrap(
        await runScrapeJob<KeywordResult>("/monitor/trending", {
          max_results,
          sort_by,
          keyword,
          types,
          ...options,
        }, {
          timeoutMs: 3_600_000,
          pollMs: 5000,
        })
      ),
  },

  // ==========================================================================
  //  ✅ DEEP MONITORING API
  // ==========================================================================
  deep: {
    keyword: async (
      keyword: string,
      config: {
        max_related?: number;
        max_per_query?: number;
        max_total?: number;
        types?: string[];
        max_comments_per_post?: number;
        top_comments_count?: number;
        sort_by?: MonitorSort;
        min_likes?: number;
        min_comments?: number;
        min_views?: number;
        recent_days?: number;
        fast_mode?: boolean;
        detail_enrich_limit?: number;
        content_mix_mode?: ContentMixMode;
        posts_target?: number;
        videos_target?: number;
        prioritize_posts?: boolean;
        viral_only?: boolean;
      } = {}
    ) =>
      request<ApiResponse<{ job_id: string; mode: string; query: string }>>(
        "/monitor/deep/keyword",
        {
          method: "POST",
          body: JSON.stringify({ keyword, ...config }),
        }
      ),

    hashtag: async (
      hashtag: string,
      config: {
        max_related_hashtags?: number;
        max_per_query?: number;
        max_total?: number;
        types?: string[];
        max_comments_per_post?: number;
        top_comments_count?: number;
        sort_by?: MonitorSort;
        min_likes?: number;
        min_comments?: number;
        min_views?: number;
        recent_days?: number;
        fast_mode?: boolean;
        detail_enrich_limit?: number;
        content_mix_mode?: ContentMixMode;
        posts_target?: number;
        videos_target?: number;
        prioritize_posts?: boolean;
        viral_only?: boolean;
      } = {}
    ) =>
      request<ApiResponse<{ job_id: string; mode: string; query: string }>>(
        "/monitor/deep/hashtag",
        {
          method: "POST",
          body: JSON.stringify({ hashtag, ...config }),
        }
      ),

    trending: async (
      config: {
        keyword?: string;
        sort_by?: MonitorSort;
        types?: string[];
        max_total?: number;
        max_comments_per_post?: number;
        top_comments_count?: number;
        min_likes?: number;
        min_comments?: number;
        min_views?: number;
        recent_days?: number;
        fast_mode?: boolean;
        detail_enrich_limit?: number;
        content_mix_mode?: ContentMixMode;
        posts_target?: number;
        videos_target?: number;
        prioritize_posts?: boolean;
        viral_only?: boolean;
      } = {}
    ) =>
      request<ApiResponse<{ job_id: string; mode: string; query: string }>>(
        "/monitor/deep/trending",
        {
          method: "POST",
          body: JSON.stringify(config),
        }
      ),

    jobs: () =>
      request<ApiResponse<{ jobs: DeepJobSummary[]; count: number }>>(
        "/monitor/deep/jobs"
      ),

    jobStatus: (jobId: string) =>
      request<ApiResponse<DeepJobState>>(`/monitor/deep/jobs/${jobId}`),

    jobPosts: (jobId: string) =>
      request<ApiResponse<{ posts: DeepPost[]; total: number }>>(
        `/monitor/deep/jobs/${jobId}/posts`
      ),

    // NEW v2: Partial results — return posts SAAT INI JUGA tanpa syarat COMPLETED
    jobPostsPartial: (jobId: string) =>
      request<ApiResponse<{
        posts: DeepPost[];
        total: number;
        job_status: string;
        total_fetched: number;
        progress_log: string[];
      }>>(
        `/monitor/deep/jobs/${jobId}/posts/partial`
      ),

    cancelJob: (jobId: string) =>
      request<ApiResponse<{ job_id: string; cancelled: boolean }>>(
        `/monitor/deep/jobs/${jobId}/cancel`,
        { method: "POST" }
      ),

    deleteJob: (jobId: string) =>
      request<ApiResponse<{ job_id: string; deleted: boolean }>>(
        `/monitor/deep/jobs/${jobId}`,
        { method: "DELETE" }
      ),
  },

  profiles: {
    list: () => request<ApiResponse<{ count: number; users: TrackedUser[] }>>("/profiles"),
    get: (username: string) => request<ApiResponse<unknown>>(`/profiles/${username}`),
    history: (username: string, limit = 50) =>
      request<ApiResponse<HistoryData>>(`/profiles/${username}/history?limit=${limit}`),
    growth: (username: string, days = 30) =>
      request<ApiResponse<GrowthData>>(`/profiles/${username}/growth?days=${days}`),
    track: (username: string, data: SnapshotInput) =>
      request<ApiResponse<unknown>>(`/profiles/${username}/track`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
  },
};

// ============================================================================
//  Type Definitions
// ============================================================================

export interface ApiResponse<T> {
  success: boolean;
  message: string;
  timestamp: string;
  data?: T;
  error?: unknown;
}

export interface HealthData {
  api: string;
  session_valid: boolean;
  tracked_profiles: number;
  post_files_saved: number;
  login_state: { is_running: boolean; login_detected: boolean; user_id: string | null };
}

export interface RecentPost {
  filename: string;
  size_kb: number;
  modified: string;
  scraped_at?: string;
  post_type?: string;
  comments_count?: number;
  total_likes?: number;
  total_shares?: number;
  url?: string;
  caption?: string;
  sentiment_summary?: {
    total_comments?: number;
    positive_percentage?: number;
    negative_percentage?: number;
    neutral_percentage?: number;
    hate_percentage?: number;
    toxic_percentage?: number;
  };
}

export interface RecentProfile {
  filename: string;
  username?: string;
  name?: string;
  followers?: number;
  likes?: number;
  is_page?: boolean;
  is_verified?: boolean;
  scraped_at?: string;
}

export interface DashboardData {
  total_post_files: number;
  total_profile_files: number;
  tracked_profiles: number;
  session_valid: boolean;
  is_logged_in: boolean;
  user_id: string | null;
  browser_running: boolean;
  recent_posts: RecentPost[];
  recent_profiles: RecentProfile[];
  latest_sentiment: SentimentSummary | null;
  top_profiles: Array<{ username: string; followers: number; likes: number }>;
  timestamp: string;
}

export interface ImportCookiesResult {
  saved: boolean;
  valid: boolean;
  total_cookies: number;
  user_id?: string;
  cookie_names?: string[];
  has_preferred?: boolean;
  preferred_missing?: string[];
  warning?: string;
}

export interface AuthStatus {
  is_running: boolean;
  login_detected: boolean;
  user_id: string | null;
  browser_opened_at: string | null;
  last_error: string | null;
  session_file_valid: boolean;
  profile_dir_exists: boolean;
  is_logged_in: boolean;
  session_info: Record<string, unknown>;
}

export interface Comment {
  number: number;
  username: string;
  text: string;
  timestamp: string;
  like_count: number;
  reply_count: number;
  is_reply?: boolean;
  reply_to?: string;
  category: string;
  sentiment: "positive" | "negative" | "neutral";
  language: string;
  is_hate_speech: boolean;
  is_toxic: boolean;
  is_sarcasm: boolean;
  is_wellwish: boolean;
  hate_score: number;
  ml_confidence: number;
  decision_source: string;
  emojis: string[];
}

export interface SentimentSummary {
  total_comments: number;
  hate_speech_count: number;
  hate_percentage: number;
  toxic_count: number;
  toxic_percentage: number;
  positive_count: number;
  positive_percentage: number;
  negative_count: number;
  negative_percentage: number;
  neutral_count: number;
  neutral_percentage: number;
  humor_count: number;
  humor_percentage: number;
  sarcasm_count: number;
  sarcasm_percentage: number;
  wellwish_count: number;
  wellwish_percentage: number;
  avg_ml_confidence: number;
  decision_source_breakdown: Record<string, number>;
  top_liked_comments: Comment[];
  most_active_users: MostActiveUser[];
}

export interface ActiveUserExample {
  number: number;
  text: string;
  is_reply?: boolean;
  reply_to?: string;
  like_count?: number;
  category?: string;
  sentiment?: string;
  timestamp?: string;
}

export interface MostActiveUser {
  username: string;
  count: number;
  comments_count?: number;
  replies_count?: number;
  total_likes?: number;
  reply_targets?: Array<{ username: string; count: number }>;
  examples?: ActiveUserExample[];
}

export interface Reactor {
  name: string;
  profile_url: string;
  reaction_type?: string;
}

export interface PostResult {
  url: string;
  scraped_at: string;
  post_id: string;
  post_type?: string;
  caption: string;
  with_tags?: string[];
  with_others?: number;
  mentions?: string[];
  media_type?: string;
  media_count?: number;
  media_urls?: string[];
  location?: string;
  total_likes: number;
  reactors?: Reactor[];
  reactors_count?: number;
  reactors_scrape_failed?: boolean;
  total_comments: number;
  total_shares: number;
  total_saves?: number | null;
  include_replies?: boolean;
  comments_count: number;
  top_level_count?: number;
  replies_count?: number;
  comments: Comment[];
  sentiment_summary: SentimentSummary;
  _meta?: { elapsed_seconds: number; saved_file: string };
}

export interface KeywordHit {
  type: string;
  author: string;
  text: string;
  caption: string;
  images?: string[];
  media_urls?: string[];
  media_count?: number;
  url: string;
  timestamp: string;
  category?: string;
  sentiment?: string;
  like_count?: number;
  likes_count?: number;
  comments_count?: number;
  views_count?: number;
  shares_count?: number;
  engagement_score?: number;
  source?: string;
  rank?: number;
}

export type MonitorSort = "trending" | "viral" | "engagement" | "likes" | "comments" | "views" | "shares" | "recent";
export type ContentMixMode = "posts_first_80_20" | "posts_first_60_40" | "balanced_50_50" | "posts_only" | "videos_only";

export interface MonitorOptions {
  sort_by?: MonitorSort;
  min_likes?: number | null;
  min_comments?: number | null;
  min_views?: number | null;
  max_comments_per_post?: number;
  top_comments_count?: number;
}

export interface KeywordResult {
  keyword?: string;
  hashtag?: string;
  scraped_at: string;
  types?: string[];
  total_results: number;
  results: KeywordHit[];
  type_counts?: Record<string, number>;
  sentiment_summary?: SentimentSummary;
  _meta?: { elapsed_seconds: number; saved_file: string };
}

export interface ProfileData {
  username: string;
  name: string;
  followers: number;
  following: number;
  likes: number;
  posts: number;
  bio: string;
  intro?: string;
  website?: string;
  email?: string;
  phone?: string;
  address?: string;
  category: string;
  is_page: boolean;
  is_verified?: boolean;
  verified?: boolean;
  profile_pic_url?: string;
  profile_picture_url?: string;
  cover_photo_url?: string;
  profile_url?: string;
  scraped_at: string;
}

export interface ProfileResult {
  success: boolean;
  data: ProfileData;
  _meta?: { elapsed_seconds: number; saved_file: string };
  _tracking_saved?: boolean;
}

export interface BatchResult {
  total: number;
  success: number;
  failed: number;
  elapsed_seconds: number;
  results: Array<{ url?: string; username?: string; success: boolean; data?: unknown; error?: string }>;
  saved_file?: string;
}

export interface TrackedUser {
  username: string;
  data_points: number;
  first_tracked: string;
  last_tracked: string;
  is_page: boolean;
  current_followers: number;
  current_likes: number;
  current_posts: number;
}

export interface HistorySnapshot {
  scraped_at: string;
  followers: number;
  following: number;
  likes: number;
  posts: number;
  is_page: boolean;
}

export interface HistoryData {
  username: string;
  total_points: number;
  returned: number;
  snapshots: HistorySnapshot[];
}

export interface GrowthMetric {
  start: number;
  end: number;
  growth: number;
  growth_pct: number;
  avg_per_day: number;
}

export interface GrowthData {
  username: string;
  analyzed_at: string;
  platform: string;
  period: { start_date: string; end_date: string; days: number; data_points: number };
  followers: GrowthMetric;
  following: GrowthMetric;
  likes: GrowthMetric;
  posts: GrowthMetric;
  history: HistorySnapshot[];
}

export interface SnapshotInput {
  followers: number;
  following: number;
  likes: number;
  posts: number;
  is_page?: boolean;
}

// ============================================================================
//  ✅ TIPE UNTUK DEEP MONITORING
// ============================================================================

export interface DeepJobSummary {
  job_id: string;
  mode: "keyword" | "hashtag" | "trending";
  query: string;
  status: "pending" | "running" | "completed" | "cancelled" | "error";
  total_fetched: number;
  created_at: string;
  updated_at: string;
  error: string | null;
}

export interface DeepJobState extends DeepJobSummary {
  config: Record<string, unknown>;
  progress_log: string[];
}

export interface DeepPost {
  url: string;
  author: string;
  text: string;
  caption: string;
  timestamp: string;
  type: string;
  likes_count: number | null;
  comments_count: number | null;
  views_count: number | null;
  shares_count: number | null;
  metrics_valid?: boolean;
  metric_source?: string;
  metrics_error?: string | null;
  detail_status?: string;
  detail_final_url?: string;
  link_valid?: boolean;
  open_url_validated?: boolean;
  link_sync_error?: string;
  search_caption_mismatch?: boolean;
  caption_match_score?: number;
  caption_source?: string;
  metric_patterns?: Record<string, string>;
  viral_score?: number;
  viral_level?: "unknown" | "low" | "potential" | "viral" | "strong_viral" | "very_viral";
  viral_reason?: string;
  content_priority?: number;
  deep_source?: string;
  deep_source_tag?: string;
  deep_root_query?: string;
  deep_root_tag?: string;
  deep_query?: string;
  rank?: number;
  source?: string;
  // v4: comment scraping fields
  top_comments?: CommentItem[];
  other_comments?: CommentItem[];
  comments_scraped_count?: number;
  comments_scrape_failed?: boolean;
  engagement_score?: number;
  matched_via?: string;
  is_above_average_engagement?: boolean;
  group_name?: string;
  group_about?: string;
  group_members?: string;
}

export interface CommentItem {
  comment_author: string;
  comment_text: string;
  comment_likes: number;
  comment_timestamp: string;
  is_reply: boolean;
}
