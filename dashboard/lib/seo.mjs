/** Public-site SEO helpers: the site's address, its indexable pages, and FAQ structured data. Plain .mjs so `node --test` covers it. */

export const SITE_URL = "https://cupel.in";

/** The pages meant to be found: the landing page, the price and the legal pages. Everything else is the signed-in app. */
export const PUBLIC_PATHS = ["/", "/pricing", "/help", "/terms", "/privacy", "/refunds", "/disclaimer"];

/** App and auth routes crawlers must leave alone (they are behind sign-in and noindex). */
export const APP_PATHS = ["/screener", "/account", "/admin", "/api/", "/auth/", "/login", "/no-access", "/ind", "/us", "/nse"];

/**
 * schema.org FAQPage JSON-LD for [question, answer] pairs, as a string safe to
 * put inside a <script> (a "<" is escaped so no answer can close the tag).
 */
export function faqJsonLd(pairs) {
  const json = {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    mainEntity: pairs.map(([q, a]) => ({ "@type": "Question", name: q, acceptedAnswer: { "@type": "Answer", text: a } })),
  };
  return JSON.stringify(json).replace(/</g, "\\u003c");
}
