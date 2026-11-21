import { Status } from './types';

/** Problems and ideas go to GitHub issues, opened in the user's own browser: nothing is sent unless they submit it there. No analytics. */
export const REPO = 'silentco2/LinKit-All';

/**
 * A new-issue link. Bugs are pre-filled with facts that are never personal: app version, OS, Python, mode, AI provider,
 * UI language and, from a failed run, the error's stable code and stage. Never a message, path, job, company or CV.
 */
export function issueUrl(kind: 'bug' | 'feature', status: Status | null, lang: string, error?: { code: string; stage?: string | null }): string {
  const base = `https://github.com/${REPO}/issues/new`;
  if (kind === 'feature') return `${base}?template=feature_request.md&labels=enhancement`;
  const a = status?.about;
  const setup = a ? `LinKit All ${a.version}, ${a.os}, Python ${a.python}, AI: ${a.ai}, UI: ${lang}` : `UI: ${lang}`;
  const lines = [
    'For a security problem, do not use this form. See SECURITY.md.',
    '',
    '**What happened**',
    '',
    '**What you expected**',
    '',
    '**Steps to reproduce**',
    '',
    `**Mode**: ${status ? (status.apply_live ? 'Applying for real' : 'Practice mode') : ''}`,
    '',
    '**Site or ATS** (if about applying):',
    '',
    `**Setup**: ${setup}`,
    ...(error ? ['', `**Error code**: ${error.code}${error.stage ? ` (step: ${error.stage})` : ''}`] : []),
    '',
    '**Logs or screenshots**: remove personal details first. Never paste passwords, tokens or your full CV. `linkit doctor` output helps.',
  ];
  const params = new URLSearchParams({ labels: 'bug', title: error ? `Run stopped: ${error.code}` : '', body: lines.join('\n') });
  return `${base}?${params}`;
}
