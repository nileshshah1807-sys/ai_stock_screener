/**
 * Resolve a published `logo_domain` into a domain a logo CDN can actually key on.
 *
 * RBI moved Indian banks onto the `.bank.in` zone, so Yahoo now reports issuer
 * websites like `hdfc.bank.in`. Brandfetch's public-suffix list does not carry
 * `.bank.in`, so it reduces every one of those to the registrable domain
 * `bank.in` — a domain it has branded as YES BANK. Left alone, all 40-odd
 * listed banks render YES BANK's mark.
 *
 * The zone is a rename, not a merger: the bank behind each label is known and
 * fixed, so the mapping below is a lookup rather than a rule. Anything under
 * `.bank.in` that is not in the table is rejected outright — a symbol lettermark
 * is honest, another bank's logo is not.
 */

/** Registered `.bank.in` label -> the domain the logo CDN indexes that bank under. */
const BANK_IN_ALIASES = new Map([
  ["au.bank.in", "aubank.in"],
  ["axis.bank.in", "axisbank.com"],
  ["bandhan.bank.in", "bandhanbank.com"],
  ["bankofbaroda.bank.in", "bankofbaroda.in"],
  ["bankofindia.bank.in", "bankofindia.co.in"],
  ["bankofmaharashtra.bank.in", "bankofmaharashtra.in"],
  ["canarabank.bank.in", "canarabank.com"],
  ["capital.bank.in", "capitalbank.co.in"],
  ["centralbank.bank.in", "centralbank.net.in"],
  ["cityunionbank.bank.in", "cityunionbank.com"],
  ["csb.bank.in", "csb.co.in"],
  ["dcb.bank.in", "dcbbank.com"],
  ["dhan.bank.in", "dhanbank.com"],
  ["equitas.bank.in", "equitasbank.com"],
  ["esaf.bank.in", "esafbank.com"],
  ["federal.bank.in", "federalbank.co.in"],
  ["fino.bank.in", "finobank.com"],
  ["hdfc.bank.in", "hdfcbank.com"],
  ["icici.bank.in", "icicibank.com"],
  ["idbi.bank.in", "idbibank.in"],
  ["idfcfirst.bank.in", "idfcfirstbank.com"],
  ["indianbank.bank.in", "indianbank.in"],
  ["indusind.bank.in", "indusind.com"],
  ["iob.bank.in", "iob.in"],
  ["jana.bank.in", "janabank.com"],
  ["jkb.bank.in", "jkbank.com"],
  ["karnatakabank.bank.in", "karnatakabank.com"],
  ["kotak.bank.in", "kotak.com"],
  ["kvb.bank.in", "kvb.co.in"],
  ["pnb.bank.in", "pnbindia.in"],
  ["punjabandsind.bank.in", "psbindia.com"],
  ["rbl.bank.in", "rblbank.com"],
  ["sbi.bank.in", "sbi.co.in"],
  ["southindianbank.bank.in", "southindianbank.com"],
  ["suryoday.bank.in", "suryodaybank.com"],
  ["tmb.bank.in", "tmb.in"],
  ["uco.bank.in", "ucobank.com"],
  ["ujjivansfb.bank.in", "ujjivansfb.in"],
  ["unionbankofindia.bank.in", "unionbankofindia.co.in"],
  ["utkarsh.bank.in", "utkarsh.bank"],
  ["yes.bank.in", "yesbank.in"],
]);

const DOMAIN_PATTERN = /^[a-z0-9-]+(\.[a-z0-9-]+)*\.[a-z]{2,}$/;

/**
 * @param {string | null | undefined} value
 * @returns {string | null} a lookup-ready domain, or null when none is usable.
 */
export function resolveLogoDomain(value) {
  const domain = value?.trim().toLowerCase().replace(/^www\./, "");
  if (!domain || !DOMAIN_PATTERN.test(domain)) return null;

  const alias = BANK_IN_ALIASES.get(domain);
  if (alias) return alias;

  // Unmapped `.bank.in` would collapse onto one shared brand, so send nothing.
  if (domain === "bank.in" || domain.endsWith(".bank.in")) return null;

  return domain;
}
