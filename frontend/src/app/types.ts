export type Tier = 'high' | 'mid' | 'low';
export const STAGES = ['discover', 'enrich', 'rank', 'score'] as const;
export type Stage = (typeof STAGES)[number];
export type Provider = 'codex_cli' | 'claude_cli' | 'litellm';

export interface RunState {
  running: boolean;
  run_id: number | null;
  stages: Stage[];
  stage: Stage | null;
  started_at: string | null;
  error: string | null;
  results: Record<string, Record<string, unknown>>;
}

export interface Status {
  profile_ready: boolean;
  cv_ready: boolean;
  search_ready: boolean;
  ai_ready: boolean;
  libreoffice: boolean;
  states: Record<string, number>;
  run: RunState;
}

export interface Profile {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  skills: string[];
  locked_facts: string[];
  cv_name?: string | null;
}

export interface Segment {
  id: number;
  text: string;
}

export interface SearchConfig {
  search: { queries: string[]; locations: string[]; posted_within_days: number; max_results_per_query: number };
  sources: { companies: string[]; jobspy: string[]; jobspy_country: string; regional: string[] };
  filters: {
    title_include: string[];
    title_exclude: string[];
    locations: string[];
    remote: 'any' | 'remote' | 'hybrid' | 'onsite';
    seniority: string[];
    salary_floor: number;
    company_blacklist: string[];
    one_per_company: boolean;
  };
  matching: { ai_max_jobs: number; tier_high: number; tier_mid: number; batch_size: number };
  ai: { provider: Provider | null; model: string | null };
}

export interface JobRow {
  id: number;
  title: string;
  company: string;
  location: string;
  source: string;
  state: string;
  tier: Tier | null;
  score: number | null;
  rank: number | null;
  remote: string | null;
  posted_at: string | null;
  ai: AIScore | null;
}

export interface AIScore {
  score: number;
  reasons: string[];
  missing_skills: string[];
  red_flags: string[];
}

export interface JobDetail extends JobRow {
  url: string;
  description: string;
  ats: string | null;
  apply_url: string | null;
  salary: { min: number | null; max: number | null; currency: string | null; interval: string | null };
  events: { at: string; from: string | null; to: string; message: string }[];
}

export interface LiveEvent {
  at: string;
  type: 'log' | 'stage' | 'run';
  level?: string;
  message?: string;
  stage?: Stage;
  status?: string;
  error?: string;
  result?: Record<string, unknown>;
}

/** "a\nb" <-> ["a", "b"] for one-per-line list fields. */
export const lines = (text: string): string[] => text.split('\n').map((l) => l.trim()).filter(Boolean);
export const unlines = (list: string[]): string => list.join('\n');
