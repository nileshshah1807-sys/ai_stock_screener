// Renders the four customer emails to HTML files for a look in a browser: node scripts/preview-emails.mjs <out-dir>
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { compose } from "../lib/customer-email.mjs";

const out = process.argv[2] ?? "email-preview";
mkdirSync(out, { recursive: true });
const data = { paid: { period: "yearly" }, cancelled: { endsAt: "2027-12-31T18:29:59Z" }, trial_ending: { endsAt: "2027-11-09T10:00:00Z" }, refund: { amountPaise: 99900 } };
for (const [kind, d] of Object.entries(data)) writeFileSync(join(out, `${kind}.html`), compose(kind, d).html);
console.log(`wrote ${Object.keys(data).length} files to ${out}`);
