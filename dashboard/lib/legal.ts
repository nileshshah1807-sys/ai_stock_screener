/**
 * The facts the Terms, Privacy and Disclaimer pages state about who runs the
 * service, in one place so the three pages cannot disagree.
 *
 * There is no registered office, so no address is stated: contact is by email.
 * Have a lawyer read the three pages before the service takes money or is
 * opened beyond invited users.
 */
// Switch to support@cupel.in once forwarding to JSM works (support@cupel.in has no mailbox yet).
const SUPPORT_EMAIL = "support@cupel-team.atlassian.net";

export const LEGAL = {
  service: "Cupel",
  operator: "Chirayu Shah",
  operatorForm: "an individual operating the service in India",
  contactEmail: SUPPORT_EMAIL,
  grievanceOfficer: "Chirayu Shah",
  grievanceEmail: SUPPORT_EMAIL,
  /** The Jira customer portal page where a customer follows their own tickets. */
  requestsUrl: "https://cupel-team.atlassian.net/servicedesk/customer/user/requests",
  jurisdiction: "Bengaluru, India",
  effective: "7 November 2026",
} as const;

export const LEGAL_PAGES = [
  { href: "/terms", label: "Terms" },
  { href: "/privacy", label: "Privacy" },
  { href: "/refunds", label: "Refunds" },
  { href: "/disclaimer", label: "Disclaimer & data" },
] as const;
