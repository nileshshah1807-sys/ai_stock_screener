/**
 * What the latest earnings call said, read out of a snapshot row's payload.
 *
 * The screener extracts each call's outlook with a language model
 * (sentiment/outlook.py) and compares it with the call of the quarter before.
 * Both arrive as payload fields rather than promoted columns: they are shown on
 * the stock page only, so they need no column, no filter and no migration.
 *
 * Returns null when the run carried no outlook for the stock -- no call, a call
 * the extraction drew nothing verifiable from, or a run before the feature --
 * so the page shows nothing instead of an empty panel that reads as "neutral".
 */

function number(value) {
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function list(value) {
  if (Array.isArray(value)) return value;
  if (typeof value !== "string" || value.trim() === "") return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

/** `guidance_raised` style reasons are already prose; only the first letter needs lifting. */
function sentence(value) {
  const trimmed = text(value);
  return trimmed ? trimmed[0].toUpperCase() + trimmed.slice(1) : "";
}

const CHANGE_ORDER = { worse: 0, better: 1, not_restated: 2, kept: 3 };

export function callOutlook(payload) {
  const source = payload ?? {};
  const score = number(source.Transcript_Outlook_Score);
  if (score === null) return null;

  const points = list(source.Transcript_Outlook_Points)
    .map((item) => ({ reason: sentence(item?.reason), points: number(item?.points) ?? 0 }))
    .filter((item) => item.reason && item.points !== 0)
    // Largest effect first, whichever way it points.
    .sort((a, b) => Math.abs(b.points) - Math.abs(a.points));

  const previousScore = number(source.Transcript_Outlook_Previous_Score);
  const changes = list(source.Transcript_Outlook_QoQ_Items)
    .map((item) => ({ change: text(item?.change), text: sentence(item?.text) }))
    .filter((item) => item.text && item.change in CHANGE_ORDER)
    .sort((a, b) => CHANGE_ORDER[a.change] - CHANGE_ORDER[b.change]);

  const count = (kind) => changes.filter((item) => item.change === kind).length;

  return {
    score,
    /** The median outlook of the run's calls: what "average" means here. */
    median: number(source.Transcript_Outlook_Neutral_Score),
    /** False when the call is too old to score, so the outlook is context only. */
    applied: source.Transcript_Outlook_Applied === true || source.Transcript_Outlook_Applied === "True",
    callDate: text(source.Transcript_Call_Date) || null,
    points,
    previous:
      previousScore === null
        ? null
        : {
            callDate: text(source.Transcript_Outlook_Previous_Call_Date) || null,
            score: previousScore,
            delta: number(source.Transcript_Outlook_QoQ_Delta) ?? score - previousScore,
            changes,
            kept: count("kept"),
            better: count("better"),
            worse: count("worse"),
          },
  };
}

/**
 * One line on whether management kept to the previous call.
 *
 * "Kept" means the second call restated what the first said, not that reported
 * results matched the guidance -- the wording stays on the calls for that reason.
 */
export function followThrough(previous) {
  if (!previous) return null;
  const compared = previous.kept + previous.better + previous.worse;
  if (compared === 0) return { tone: "muted", label: "Nothing comparable between the two calls" };
  if (previous.worse > 0) {
    return {
      tone: "negative",
      label: `${previous.worse} of ${compared} items weaker than the previous call`,
    };
  }
  if (previous.better > 0) {
    return {
      tone: "positive",
      label: `Kept to the previous call and improved on ${previous.better} of ${compared} items`,
    };
  }
  return { tone: "default", label: `Kept to the previous call on all ${compared} items` };
}
