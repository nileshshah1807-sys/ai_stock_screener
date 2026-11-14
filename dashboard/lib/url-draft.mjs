/** A text control's URL value as its draft, and the draft as the URL value it stands for. */
export const asText = (url) => url;
export const trimmed = (text) => text.trim();

/**
 * What a control's draft becomes when its URL value changes to `url`.
 * `pending` are the values this control pushed that have not landed yet: one
 * landing is the URL catching up with the control (typing "abc" while the
 * push of "ab" lands), so the draft is kept and the pushes up to it are done.
 * Any other change (a saved view, a chip removed, Back) is followed: the
 * URL's value, unless the draft already says the same thing (`holds`).
 * @template T
 * @param {T} draft
 * @param {string} url
 * @param {(url: string) => T} from
 * @param {(draft: T) => string} holds
 * @param {string[]} [pending]
 * @returns {{ draft: T, pending: string[] }}
 */
export function draftAfterUrlChange(draft, url, from, holds, pending = []) {
  const own = pending.indexOf(url);
  if (own >= 0) return { draft, pending: pending.slice(own + 1) };
  return { draft: holds(draft) === url ? draft : from(url), pending: [] };
}
