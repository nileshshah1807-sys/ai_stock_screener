/**
 * Normalise a `[symbol]` route parameter.
 *
 * Ten NSE tickers contain an ampersand (M&M, GVT&D, J&KBANK, IL&FSENGG ...).
 * Whether a dynamic segment arrives percent-encoded depends on the host: the
 * local dev server hands back a decoded "M&M" for both /stocks/M&M and
 * /stocks/M%26M, but the deployed site 404s on /stocks/M%26M even though the
 * row is present and the database filter is built correctly -- which leaves
 * the parameter still carrying "%26" as the only candidate on that path.
 *
 * Decoding here is safe under either behaviour: no symbol in the universe
 * contains a percent sign, so decoding an already-decoded symbol returns it
 * unchanged. A malformed escape throws rather than returning a bad value, so
 * the raw segment is used instead of failing the request.
 */
export function decodeSymbolParam(raw) {
  if (typeof raw !== "string") return "";
  try {
    return decodeURIComponent(raw);
  } catch {
    return raw;
  }
}
