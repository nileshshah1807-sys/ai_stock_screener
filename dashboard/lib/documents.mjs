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

/** How long after a call's recording notice its transcript may be filed and still be the same call. */
const PAIR_DAYS = 21;
const LINK_LABELS = { transcript: "Transcript", recording: "Recording" };

/**
 * rows: {kind, announced_at, title, url, period?} with kind one of presentation,
 * transcript, recording, rating, annual_report, results. A transcript and the
 * recording before it (see PAIR_DAYS) are one call; otherwise they stay apart.
 * Returns [{kind, label, items: [{key, date, title, links: [{label, url}]}]}],
 * groups with nothing left out.
 * @param {{kind: string, announced_at: string, title: string, url: string, period?: string | null}[] | null | undefined} rows
 * @returns {{kind: string, label: string, items: {key: string, kind: string, date: string, title: string, links: {label: string, url: string}[]}[]}[]}
 */
export function groupDocuments(rows) {
  const items = new Map();
  // http(s) only: a stored url is rendered as a link, so javascript: and data: never get that far.
  const usable = (rows ?? []).filter((row) => /^https?:\/\//i.test(row?.url ?? "") && row.announced_at);
  const callOf = new Map(); // transcript url -> its recording row
  const taken = new Set();
  // The notice for a call comes the evening it is held, the transcript days later:
  // a transcript pairs with the newest unpaired recording at most PAIR_DAYS before it.
  const recordings = usable.filter((row) => row.kind === "recording");
  for (const transcript of usable.filter((row) => row.kind === "transcript")) {
    const at = Date.parse(transcript.announced_at);
    const match = recordings
      .filter((rec) => !taken.has(rec.url) && (rec.period ? rec.period === transcript.period : true))
      .filter((rec) => {
        const gap = at - Date.parse(rec.announced_at);
        return gap >= 0 && gap <= PAIR_DAYS * 864e5;
      })
      .sort((x, y) => (x.announced_at < y.announced_at ? 1 : -1))[0];
    if (match) {
      taken.add(match.url);
      callOf.set(transcript.url, match);
    }
  }
  for (const row of usable) {
    if (taken.has(row.url)) continue;
    const call = callOf.get(row.url);
    if (call) {
      items.set(`concall:${row.url}`, {
        key: `concall:${row.url}`,
        kind: "concall",
        date: row.announced_at,
        title: "Earnings call",
        links: [
          { label: LINK_LABELS.transcript, url: row.url },
          { label: LINK_LABELS.recording, url: call.url },
        ],
      });
      continue;
    }
    const kind = row.kind === "transcript" || row.kind === "recording" ? "concall" : row.kind;
    items.set(`${row.kind}:${row.url}`, { key: `${row.kind}:${row.url}`, kind, date: row.announced_at, title: row.title, links: [{ label: row.title, url: row.url }] });
  }
  return DOCUMENT_GROUPS.map(({ kind, label }) => ({
    kind,
    label,
    items: [...items.values()]
      .filter((item) => item.kind === kind)
      .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0)),
  })).filter((group) => group.items.length > 0);
}
