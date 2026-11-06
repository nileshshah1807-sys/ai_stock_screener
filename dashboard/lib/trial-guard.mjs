/**
 * Who may have a free trial: the matching rules, with no I/O so they can be tested.
 * The caller hashes the signals (lib/trial-guard.ts) and passes hashes in.
 */

/** A trial already given to the same IP counts this long. */
export const TRIAL_WINDOW_DAYS = 60;
/** Trials one IP may have had in the window before the next is refused (India's mobile CGNAT shares one IP among many people). */
export const IP_TRIAL_LIMIT = 3;

// shortcut: a short static list of the common throwaway providers; swap for a maintained list if abuse moves here.
const DISPOSABLE_DOMAINS = new Set([
  "mailinator.com", "guerrillamail.com", "guerrillamail.net", "guerrillamailblock.com", "sharklasers.com",
  "10minutemail.com", "10minutemail.net", "tempmail.com", "temp-mail.org", "temp-mail.io", "tempmailo.com",
  "yopmail.com", "yopmail.net", "throwawaymail.com", "trashmail.com", "getnada.com", "dispostable.com",
  "maildrop.cc", "mailnesia.com", "fakeinbox.com", "mintemail.com", "mohmal.com", "emailondeck.com",
  "burnermail.io", "discard.email", "spamgourmet.com", "moakt.com", "tmpmail.org", "tmail.ws", "inboxkitten.com",
]);

/** The address with the tricks that make one mailbox look like many removed. */
export function normalizeEmail(email) {
  const [rawLocal, rawDomain = ""] = String(email ?? "").trim().toLowerCase().split("@");
  const domain = rawDomain === "googlemail.com" ? "gmail.com" : rawDomain;
  let local = rawLocal.split("+")[0];
  if (domain === "gmail.com") local = local.replaceAll(".", "");
  return `${local}@${domain}`;
}

export function isDisposableEmail(email) {
  return DISPOSABLE_DOMAINS.has(normalizeEmail(email).split("@")[1] ?? "");
}

/** The part of an IP that identifies a subscriber: the address for IPv4, the /64 for IPv6. Null when there is none. */
export function ipKey(raw) {
  const ip = String(raw ?? "").split(",")[0].trim();
  if (!ip) return null;
  if (!ip.includes(":")) return ip;
  if (ip.startsWith("::ffff:") && ip.includes(".")) return ip.slice(7);
  const [head, tail = ""] = ip.split("::");
  const groups = head ? head.split(":") : [];
  const rest = tail ? tail.split(":") : [];
  const full = ip.includes("::") ? [...groups, ...Array(Math.max(0, 8 - groups.length - rest.length)).fill("0"), ...rest] : groups;
  return full.slice(0, 4).map((g) => g.padStart(4, "0")).join(":");
}

/**
 * @param {{ipHash: string|null, deviceHash: string|null, emailHash: string, disposable: boolean}} current
 * @param {{ip_hash: string|null, device_hash: string|null, email_hash: string}[]} priors trials GRANTED inside the window
 * @returns {{grant: boolean, reason: "ok"|"disposable_email"|"same_email"|"same_device"|"same_network"}}
 */
export function trialVerdict(current, priors) {
  if (current.disposable) return { grant: false, reason: "disposable_email" };
  if (priors.some((p) => p.email_hash === current.emailHash)) return { grant: false, reason: "same_email" };
  if (current.deviceHash && priors.some((p) => p.device_hash === current.deviceHash)) return { grant: false, reason: "same_device" };
  const sameIp = current.ipHash ? priors.filter((p) => p.ip_hash === current.ipHash).length : 0;
  if (sameIp >= IP_TRIAL_LIMIT) return { grant: false, reason: "same_network" };
  return { grant: true, reason: "ok" };
}
