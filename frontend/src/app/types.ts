export type Tier = 'high' | 'mid' | 'low';
export const STAGES = ['discover', 'enrich', 'rank', 'score', 'apply'] as const;
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
  apply: ApplySection;
}

export interface ApplySection {
  live: boolean;
  submit_without_asking: boolean;
  max_per_run: number;
  daily_cap_per_site: number;
  headless: boolean;
  min_pause_s: number;
  max_pause_s: number;
}

/** Null / empty means "ask me in the Action Center" for the sensitive fields. */
export interface ApplicationAnswers {
  first_name: string;
  last_name: string;
  city: string;
  country: string;
  current_company: string;
  current_title: string;
  linkedin: string;
  github: string;
  portfolio: string;
  years_experience: number | null;
  notice_period: string;
  heard_about: string;
  willing_to_relocate: boolean | null;
  authorized_countries: string[];
  needs_sponsorship: boolean | null;
  salary_expectation: string;
  salary_currency: string;
  eeo_gender: string | null;
  eeo_race: string | null;
  eeo_hispanic: string | null;
  eeo_veteran: string | null;
  eeo_disability: string | null;
  acknowledge_privacy: boolean | null;
  acknowledge_legal: boolean | null;
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
