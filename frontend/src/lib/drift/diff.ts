/**
 * A word-level diff of a cited section's text before and after a document changed, for
 * the drift inbox. Pure; no React.
 */

export type DiffOp = "equal" | "insert" | "delete";

export interface DiffPart {
  op: DiffOp;
  text: string;
}

/**
 * The largest alignment table (tokens before x tokens after, once the shared start and
 * end are trimmed) worth computing. The gateway caps each side at 4 KB, so real
 * sections stay well under it; past it the diff is shown as a whole replacement.
 */
export const MAX_DIFF_CELLS = 1_000_000;

function tokenize(text: string): string[] {
  return text.match(/\s+|\S+/g) ?? [];
}

function push(parts: DiffPart[], op: DiffOp, text: string): void {
  if (!text) return;
  const last = parts.at(-1);
  if (last && last.op === op) last.text += text;
  else parts.push({ op, text });
}

/** Words and whitespace as equal / delete / insert runs; deletions come before insertions. */
export function diffWords(before: string | null, after: string | null): DiffPart[] {
  const parts: DiffPart[] = [];
  if (before === null || after === null) {
    if (before) push(parts, "delete", before);
    if (after) push(parts, "insert", after);
    return parts;
  }
  const a = tokenize(before);
  const b = tokenize(after);

  let start = 0;
  while (start < a.length && start < b.length && a[start] === b[start]) start++;
  let endA = a.length;
  let endB = b.length;
  while (endA > start && endB > start && a[endA - 1] === b[endB - 1]) {
    endA--;
    endB--;
  }

  push(parts, "equal", a.slice(0, start).join(""));
  const n = endA - start;
  const m = endB - start;
  if (n * m > MAX_DIFF_CELLS) {
    push(parts, "delete", a.slice(start, endA).join(""));
    push(parts, "insert", b.slice(start, endB).join(""));
  } else {
    // lcs[i * (m + 1) + j]: the longest common subsequence of a[start+i..] and b[start+j..].
    const width = m + 1;
    const lcs = new Uint32Array((n + 1) * width);
    for (let i = n - 1; i >= 0; i--) {
      for (let j = m - 1; j >= 0; j--) {
        lcs[i * width + j] =
          a[start + i] === b[start + j]
            ? lcs[(i + 1) * width + j + 1] + 1
            : Math.max(lcs[(i + 1) * width + j], lcs[i * width + j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < n || j < m) {
      if (i < n && j < m && a[start + i] === b[start + j]) {
        push(parts, "equal", a[start + i]);
        i++;
        j++;
      } else if (j >= m || (i < n && lcs[(i + 1) * width + j] >= lcs[i * width + j + 1])) {
        push(parts, "delete", a[start + i]);
        i++;
      } else {
        push(parts, "insert", b[start + j]);
        j++;
      }
    }
  }
  push(parts, "equal", a.slice(endA).join(""));
  return parts;
}
