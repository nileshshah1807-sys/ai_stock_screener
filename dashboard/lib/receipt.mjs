// Cupel's own receipt for one payment, as a printable HTML document built in the browser from a
// payment-history row. Razorpay's hosted receipt leaves "Issued to" blank for subscription invoices
// even when the invoice holds the customer (TEST, 16 Nov 2026), so the buyer is named here.

const ESCAPES = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
/** Every value here comes from Razorpay or the buyer: always escaped. */
export const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ESCAPES[c]);

/** @param {unknown} value */
function isRazorpayUrl(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === "https:" && (url.hostname === "rzp.io" || url.hostname === "razorpay.com" || url.hostname.endsWith(".razorpay.com"));
  } catch {
    return false;
  }
}

/**
 * @param {{id: string, date: string, paise: number, currency: string, method: string, status: string,
 *   buyerName?: string|null, buyerEmail?: string|null, item?: string|null, paymentId?: string|null, receiptUrl?: string|null}} row
 * @param {{service: string, operator: string, contactEmail: string}} seller
 * @param {{date: (iso: string) => string, amount: (row: any) => string}} format
 */
export function receiptHtml(row, seller, format) {
  const refunded = row.status === "refunded";
  // Razorpay's own copy, to verify or download; only a payment that was made, and only its own host.
  const official = (row.status === "paid" || refunded) && isRazorpayUrl(row.receiptUrl) ? row.receiptUrl : null;
  const buyer = [row.buyerName, row.buyerEmail].filter(Boolean).map(escapeHtml).join("<br>") || "Not recorded";
  /** @param {string} label @param {string} value */
  const line = (label, value) => `<tr><th>${label}</th><td>${value}</td></tr>`;
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Receipt ${escapeHtml(row.id)} · ${escapeHtml(seller.service)}</title>
<style>
body{font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;color:#111;background:#fff;margin:0;padding:32px 16px}
main{max-width:560px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}.muted{color:#555}
table{width:100%;border-collapse:collapse;margin:24px 0}th,td{text-align:left;vertical-align:top;padding:10px 0;border-bottom:1px solid #ddd}
th{width:40%;font-weight:500;color:#555}td{overflow-wrap:anywhere}.total td{font-size:18px;font-weight:600}
a{color:#0b57d0}button{font:inherit;padding:8px 16px;border:1px solid #bbb;border-radius:6px;background:#fff;cursor:pointer}
@media print{button{display:none}a{color:#111}body{padding:0}}
</style></head><body><main>
<h1>${escapeHtml(seller.service)} receipt</h1>
<p class="muted">${refunded ? "This payment was refunded." : "Payment received. Thank you."}</p>
<table>
${line("Receipt for invoice", escapeHtml(row.id))}
${row.paymentId ? line("Razorpay payment", escapeHtml(row.paymentId)) : ""}
${line(refunded ? "Paid on (since refunded)" : "Paid on", escapeHtml(format.date(row.date)))}
${line("Issued to", buyer)}
${line("Plan", escapeHtml(row.item || "Cupel subscription"))}
${line("Payment method", escapeHtml(row.method))}
<tr class="total"><th>Amount paid</th><td>${escapeHtml(format.amount(row))}</td></tr>
</table>
<p class="muted">Issued by ${escapeHtml(seller.service)}, operated by ${escapeHtml(seller.operator)}. Questions: ${escapeHtml(seller.contactEmail)}</p>
${official ? `<p><a href="${escapeHtml(official)}" target="_blank" rel="noopener noreferrer">View or download official Razorpay invoice</a></p>` : ""}
<button type="button" onclick="window.print()">Print or save as PDF</button>
</main></body></html>`;
}
