/**
 * The facts the Terms, Privacy and Disclaimer pages state about who runs the
 * service, in one place so the three pages cannot disagree.
 *
 * shortcut: the bracketed values are placeholders. Fill them in, and have a
 * lawyer read the three pages, before the service takes money or is opened
 * beyond invited users.
 */
export const LEGAL = {
  service: "Cupel",
  operator: "Chirayu Shah",
  operatorForm: "an individual operating the service in India",
  address: "[Registered address]",
  contactEmail: "[contact email]",
  grievanceOfficer: "Chirayu Shah",
  grievanceEmail: "[grievance email]",
  jurisdiction: "[City], India",
  effective: "4 November 2026",
} as const;

export const LEGAL_PAGES = [
  { href: "/terms", label: "Terms" },
  { href: "/privacy", label: "Privacy" },
  { href: "/refunds", label: "Refunds" },
  { href: "/disclaimer", label: "Disclaimer & data" },
] as const;
