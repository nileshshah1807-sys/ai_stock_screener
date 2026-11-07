export const NAME_MAX = 60;

/**
 * A display name as it is stored: control characters removed, runs of white space
 * collapsed, trimmed. null means "no name" (an empty field clears it); a string over
 * NAME_MAX is an error rather than being cut, so the person sees what was kept.
 * @returns {{ok: true, name: string|null} | {ok: false, message: string}}
 */
export function cleanDisplayName(raw) {
  const name = String(raw ?? "")
    .replace(/[\p{Cc}\p{Cf}\p{Zl}\p{Zp}]/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
  if (name.length > NAME_MAX) return { ok: false, message: `Use ${NAME_MAX} characters or fewer.` };
  return { ok: true, name: name || null };
}

/** What the page calls the person: their name, else the part of the email before the @. */
export function shownName(name, email) {
  const clean = typeof name === "string" ? name.trim() : "";
  return clean || String(email ?? "").split("@")[0] || "Your account";
}

/** "Priya Shah" -> "PS"; one word, its first two letters; no name, the email's. */
export function initialsOf(name, email) {
  const words = (typeof name === "string" ? name : "").split(/\s+/).filter(Boolean);
  if (words.length > 1) return (words[0][0] + words[words.length - 1][0]).toUpperCase();
  if (words.length === 1) return Array.from(words[0]).slice(0, 2).join("").toUpperCase();
  const parts = String(email ?? "").split("@")[0].split(/[^a-zA-Z0-9]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : (parts[0] ?? "?").slice(0, 2)).toUpperCase();
}

export const INVOICE_NAME_MIN = 2;

/**
 * The invoice name asked before checkout: the same cleaning as the profile name,
 * and at least INVOICE_NAME_MIN characters. Returns the problem as a sentence, or null when fine.
 */
export function invoiceNameProblem(raw) {
  const cleaned = cleanDisplayName(raw);
  if (!cleaned.ok) return cleaned.message;
  if ((cleaned.name ?? "").length < INVOICE_NAME_MIN) return `Enter your name, at least ${INVOICE_NAME_MIN} characters.`;
  return null;
}
