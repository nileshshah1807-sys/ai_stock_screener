// The account page's payment history, shaped from what Razorpay returns for a subscription.
// Plain and dependency-free so the shaping is testable; the fetching is in app/api/billing/payments.

/** Most payments the page lists. A yearly plan has one a year and a monthly one twelve, so this is generous. */
export const PAYMENT_LIMIT = 24;

const NETWORKS = { visa: "Visa", mastercard: "Mastercard", rupay: "RuPay", amex: "Amex", diners: "Diners", maestro: "Maestro" };

/** A receipt is only ever a link to Razorpay's own host; anything else is dropped rather than rendered as a link. */
export function receiptUrl(value) {
  if (typeof value !== "string") return null;
  try {
    const url = new URL(value);
    const host = url.hostname;
    const ok = url.protocol === "https:" && (host === "rzp.io" || host === "razorpay.com" || host.endsWith(".razorpay.com"));
    return ok ? url.toString() : null;
  } catch {
    return null;
  }
}

/** How it was paid, in words: "Visa ending 4242", "UPI", "Bank autopay". Never a full card or UPI id. */
export function methodLabel(payment) {
  switch (payment?.method) {
    case "card": {
      const network = NETWORKS[String(payment.card?.network ?? "").toLowerCase()] ?? "Card";
      const last4 = /^\d{4}$/.test(String(payment.card?.last4 ?? "")) ? payment.card.last4 : null;
      return last4 ? `${network} ending ${last4}` : network;
    }
    case "upi":
      return "UPI";
    case "emandate":
    case "nach":
      return "Bank autopay";
    case "netbanking":
      return "Net banking";
    case "wallet":
      return "Wallet";
    default:
      return "Not recorded";
  }
}

/** @returns {"paid"|"refunded"|"failed"|"pending"} */
export function paymentStatus(invoice, payment) {
  if (payment?.status === "refunded" || (payment?.amount_refunded ?? 0) > 0) return "refunded";
  if (invoice?.status === "paid") return "paid";
  if (payment?.status === "failed" || ["cancelled", "expired", "deleted"].includes(invoice?.status)) return "failed";
  return "pending";
}

/**
 * Rows for the page, newest first. `invoices` are Razorpay's invoice objects for one
 * subscription; `paymentsById` maps payment id to its payment object (a payment that
 * could not be read is simply absent, and its method shows as not recorded).
 * Every field is chosen here: nothing else of Razorpay's reply reaches the browser.
 * @returns {{id: string, date: string, paise: number, currency: string, method: string, status: string, receiptUrl: string|null}[]}
 */
export function paymentRows(invoices, paymentsById = {}) {
  return (Array.isArray(invoices) ? invoices : [])
    .filter((invoice) => invoice && typeof invoice.id === "string" && Number.isFinite(invoice.amount) && invoice.status !== "draft")
    .map((invoice) => {
      const payment = invoice.payment_id ? paymentsById[invoice.payment_id] : undefined;
      const status = paymentStatus(invoice, payment);
      const at = status === "paid" || status === "refunded" ? (invoice.paid_at ?? payment?.created_at) : null;
      const seconds = at ?? invoice.issued_at ?? invoice.created_at;
      return {
        id: invoice.id,
        date: Number.isFinite(seconds) ? new Date(seconds * 1000).toISOString() : "",
        paise: invoice.amount_paid > 0 && status === "paid" ? invoice.amount_paid : invoice.amount,
        currency: typeof invoice.currency === "string" ? invoice.currency : "INR",
        method: methodLabel(payment),
        status,
        receiptUrl: receiptUrl(invoice.short_url),
      };
    })
    .filter((row) => row.date)
    .sort((a, b) => (a.date < b.date ? 1 : a.date > b.date ? -1 : 0))
    .slice(0, PAYMENT_LIMIT);
}

export const PAYMENT_STATUS_LABEL = { paid: "Paid", refunded: "Refunded", failed: "Failed", pending: "Pending" };
