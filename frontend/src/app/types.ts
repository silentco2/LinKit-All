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
  vault: { initialized: boolean; unlocked: boolean };
  states: Record<string, number>;
  actions_open: number;
  apply_live: boolean;
  run: RunState;
  /** The headed Chrome window opened from the Action Center, if any. */
  app_browser: { open: boolean; item_id: number | null };
  /** Modified time (epoch seconds) of the newest live screenshot, null when none is fresh. */
  live_shot: number | null;
  next_run: string | null;
}

export interface Profile {
  full_name: string;
  email: string;
  phone: string;
  location: string;
  skills: string[];
  locked_facts: string[];
  cv_name?: string | null;
  cv_source_format?: 'docx' | 'odt' | 'pdf' | 'tex';
  /** False when the program that renders this CV (LibreOffice, or Tectonic for LaTeX) is missing. */
  cv_renderer_ok?: boolean;
  /** False for a converted PDF until the user approves it; tailoring refuses until then. */
  cv_approved?: boolean;
}

export interface Segment {
  id: number;
  text: string;
}

export type WorkMode = 'remote' | 'hybrid' | 'onsite';

/** One query per alternative: "React/Next.JS Developer" -> "React Developer", "Next.JS Developer". Mirrors the server. */
export function expandQueries(queries: string[]): string[] {
  const seen = new Map<string, string>();
  for (const q of queries) {
    let out = [''];
    for (const word of q.split(/\s+/).filter(Boolean)) {
      const alts = word.includes('/') ? word.split('/') : [word];
      out = out.flatMap((prefix) => alts.map((a) => `${prefix} ${a}`.trim()));
    }
    for (const e of out) if (e && !seen.has(e.toLowerCase())) seen.set(e.toLowerCase(), e);
  }
  return [...seen.values()];
}

export interface SearchConfig {
  search: { queries: string[]; locations: string[]; posted_within_days: number; max_results_per_query: number };
  sources: { companies: string[]; jobspy: string[]; jobspy_country: string; regional: string[] };
  filters: {
    title_include: string[];
    title_exclude: string[];
    locations: string[];
    work_modes: WorkMode[];
    seniority: string[];
    salary_floor_monthly: number;
    salary_currency: string;
    company_blacklist: string[];
    one_per_company: boolean;
  };
  matching: { ai_max_jobs: number; tier_high: number; tier_mid: number; batch_size: number; auto_apply_low: boolean };
  ai: { provider: Provider | null; model: string | null; api_base: string | null };
  apply: ApplySection;
  email: { imap_host: string; imap_user: string; timeout_s: number; poll_s: number };
  schedule: ScheduleSection;
}

export interface ScheduleSection {
  enabled: boolean;
  /** 0 = Monday .. 6 = Sunday */
  days: number[];
  /** "HH:MM", 24 h, local time */
  times: string[];
  new_run: boolean;
}

export interface ApplySection {
  live: boolean;
  submit_without_asking: boolean;
  max_per_run: number;
  daily_cap_per_site: number;
  headless: boolean;
  min_pause_s: number;
  max_pause_s: number;
  parallel_sites: number;
  generic_agent: boolean;
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

export interface TailorPatch {
  segment_id: number;
  old_text: string;
  new_text: string;
  /** Why it was made; for a rejected patch, why it was refused. */
  reason: string;
}

export interface Tailoring {
  created_at: string;
  status: 'tailored' | 'unchanged' | 'rolled_back';
  patches: TailorPatch[];
  rejected: TailorPatch[];
  verify: { ok: boolean; pages: [number, number]; min_ssim: number; reason: string } | null;
}

export interface JobDetail extends JobRow {
  tailoring: Tailoring | null;
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

export type ActionKind = 'unknown_question' | 'confirm_submit' | 'captcha' | 'validation_error' | 'login_issue' | 'two_factor';
export type ActionDecision = 'answer' | 'confirm' | 'retry' | 'applied_by_hand' | 'skip';
export type AnswerValue = string | boolean | string[];

export interface AnswerEntry {
  id: number;
  question: string;
  answer: AnswerValue;
  source: 'user' | 'ai';
  sensitive: boolean;
  uses: number;
  updated_at: string;
}

export interface ActionQuestion {
  label: string;
  kind: string; // text, textarea, email, tel, number, url, date, select, radio, combobox, yesno, checkbox, multi, file
  options: string[];
  required: boolean;
  reason: string;
  sensitive: boolean;
}

export interface ActionItem {
  id: number;
  kind: ActionKind;
  status: string;
  message: string;
  questions: ActionQuestion[];
  /** What was filled: label -> value and where it came from (profile, sensitive, bank, ai, file). */
  answers: Record<string, { value: unknown; source: string }>;
  screenshots: number;
  created_at: string;
  job: { id: number; title: string; company: string; location: string; score: number | null; url: string; apply_url: string };
}

export interface VaultEntry {
  id: number;
  kind: string;
  site: string;
  username: string;
  meta: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface VaultState {
  initialized: boolean;
  unlocked: boolean;
  entries: VaultEntry[];
}

export interface EmailState {
  imap_host: string;
  imap_user: string;
  connected: boolean;
  vault: { initialized: boolean; unlocked: boolean };
}

export interface ApiKeyProvider {
  name: string;
  label: string;
  fields: { name: string; label: string; secret: boolean }[];
  signup_url: string;
  note: string;
  configured: boolean;
  /** Saved non-secret values; secret fields appear only as a masked hint. */
  current: Partial<Record<string, string>>;
}

export interface OutcomeRow {
  name: string;
  found: number;
  applied: number;
  failed: number;
  skipped: number;
  needs_user: number;
}

export interface Report {
  funnel: { step: string; count: number }[];
  tiers: Record<string, number>;
  states: Record<string, number>;
  sources: Record<string, Partial<Record<string, number>>>;
  per_platform: { source: OutcomeRow[]; ats: OutcomeRow[] };
  per_board: OutcomeRow[];
  per_run: (Omit<OutcomeRow, 'name'> & { run_id: number; status: string; started_at: string })[];
  over_time: { date: string; applied: number; failed: number; skipped: number; needs_user: number }[];
  filter: { run_id: number | null; since: string | null };
}
