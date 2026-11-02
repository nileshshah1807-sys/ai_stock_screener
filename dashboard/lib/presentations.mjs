// The investor presentation that belongs to a result: the newest one filed from
// a day before the result's broadcast to a week after it (Kevin: 99% of
// presentations fall in that window). None in the window: no link.
const DAY = 864e5;

/**
 * @param {{announced_at: string, url: string}[]} rows one company's presentations
 * @param {string | null} broadcastAt when the result was announced
 * @returns {string | null}
 */
export function presentationFor(rows, broadcastAt) {
  const at = Date.parse(broadcastAt ?? "");
  if (Number.isNaN(at)) return null;
  const inWindow = (rows ?? []).filter((row) => {
    const t = Date.parse(row.announced_at);
    return t >= at - DAY && t <= at + 7 * DAY;
  });
  inWindow.sort((a, b) => Date.parse(b.announced_at) - Date.parse(a.announced_at));
  return inWindow[0]?.url ?? null;
}
