// A company's documents for the stock page's Documents tab: links only, grouped
// by kind, newest first. Pure, so node --test can check the grouping.

/** Display order and names; `concall` is a transcript and its recording paired. */
export const DOCUMENT_GROUPS = [
  { kind: "presentation", label: "Investor presentations" },
  { kind: "concall", label: "Concalls" },
  { kind: "annual_report", label: "Annual reports" },
  { kind: "rating", label: "Credit ratings" },
  { kind: "results", label: "Results filings" },
];

const LINK_LABELS = { transcript: "Transcript", recording: "Recording" };

/**
 * rows: {kind, announced_at, title, url, period?} with kind one of presentation,
 * transcript, recording, rating, annual_report, results. A transcript and a
 * recording of the same period are one call; without a period they stay apart.
 * Returns [{kind, label, items: [{key, date, title, links: [{label, url}]}]}],
 * groups with nothing left out.
 * @param {{kind: string, announced_at: string, title: string, url: string, period?: string | null}[] | null | undefined} rows
 * @returns {{kind: string, label: string, items: {key: string, kind: string, date: string, title: string, links: {label: string, url: string}[]}[]}[]}
 */
export function groupDocuments(rows) {
  const items = new Map();
  for (const row of rows ?? []) {
    if (!row?.url || !row.announced_at) continue;
    const paired = (row.kind === "transcript" || row.kind === "recording") && row.period;
    const kind = row.kind === "transcript" || row.kind === "recording" ? "concall" : row.kind;
    const key = paired ? `concall:${row.period}` : `${row.kind}:${row.url}`;
    const link = { label: LINK_LABELS[row.kind] ?? row.title, url: row.url };
    const have = items.get(key);
    if (have) {
      have.links.push(link);
      if (row.announced_at > have.date) have.date = row.announced_at;
    } else {
      items.set(key, { key, kind, date: row.announced_at, title: row.title, links: [link] });
    }
  }
  return DOCUMENT_GROUPS.map(({ kind, label }) => ({
    kind,
    label,
    items: [...items.values()]
      .filter((item) => item.kind === kind)
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)),
  })).filter((group) => group.items.length > 0);
}
