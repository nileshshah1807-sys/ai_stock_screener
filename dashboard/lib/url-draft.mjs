/**
 * What a control's draft becomes when its URL value changes from elsewhere:
 * the URL's value, unless the draft already says the same thing (`holds`).
 * @template T
 * @param {T} draft
 * @param {string} url
 * @param {(url: string) => T} from
 * @param {(draft: T) => string} holds
 * @returns {T}
 */
export function draftAfterUrlChange(draft, url, from, holds) {
  return holds(draft) === url ? draft : from(url);
}
