import { Component, computed, input } from '@angular/core';
import { TailorPatch } from '../types';

interface DiffOp { kind: 'same' | 'del' | 'ins'; word: string }

/** Word-level diff by longest common subsequence; CV segments are short, so O(n*m) is fine. */
function wordDiff(a: string, b: string): DiffOp[] {
  const x = a.split(/\s+/).filter(Boolean);
  const y = b.split(/\s+/).filter(Boolean);
  const lcs = Array.from({ length: x.length + 1 }, () => new Array<number>(y.length + 1).fill(0));
  for (let i = x.length - 1; i >= 0; i--) {
    for (let j = y.length - 1; j >= 0; j--) {
      lcs[i][j] = x[i] === y[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const ops: DiffOp[] = [];
  let i = 0;
  let j = 0;
  while (i < x.length || j < y.length) {
    if (i < x.length && j < y.length && x[i] === y[j]) {
      ops.push({ kind: 'same', word: x[i++] });
      j++;
    } else if (i < x.length && (j === y.length || lcs[i + 1][j] >= lcs[i][j + 1])) ops.push({ kind: 'del', word: x[i++] });
    else ops.push({ kind: 'ins', word: y[j++] });  // deletions first, so a replaced word reads old-then-new
  }
  return ops;
}

/** One CV edit as a red-line: old words struck through in red, new words underlined in green, the reason under it. */
@Component({
  selector: 'app-patch-diff',
  template: `
    <div class="rounded-lg border border-slate-200 p-3 text-sm dark:border-slate-700">
      <p class="leading-relaxed" dir="auto">
        @for (op of ops(); track $index) {
          @switch (op.kind) {
            @case ('del') { <del class="rounded line-through bg-rose-50 px-0.5 text-rose-700 dark:bg-rose-950 dark:text-rose-300">{{ op.word }}</del>{{ ' ' }} }
            @case ('ins') { <ins class="rounded underline bg-emerald-50 px-0.5 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300">{{ op.word }}</ins>{{ ' ' }} }
            @default { {{ op.word + ' ' }} }
          }
        }
      </p>
      @if (patch().reason) { <p class="mt-1 text-xs text-slate-500" dir="auto">{{ patch().reason }}</p> }
    </div>
  `,
})
export class PatchDiff {
  readonly patch = input.required<TailorPatch>();
  protected readonly ops = computed(() => wordDiff(this.patch().old_text ?? '', this.patch().new_text ?? ''));
}
