// Run after `opennextjs-cloudflare build`, from dashboard/: copies each app/(static) page's
// prerendered HTML into .open-next/assets at its URL path (/ind/flows -> ind/flows.html), so
// Cloudflare serves it without running the Worker. Which pages: lib/static-pages.mjs.
import { copyFileSync, existsSync, mkdirSync, readFileSync } from "node:fs";
import { dirname } from "node:path";

import { staticPages } from "../lib/static-pages.mjs";

const json = (path) => JSON.parse(readFileSync(path, "utf8"));
const pages = staticPages(json(".next/server/app-paths-manifest.json"), json(".next/prerender-manifest.json"));
if (!pages.length) {
  console.error("static-pages: no app/(static) page was prerendered; every one would cost the Worker a render");
  process.exit(1);
}
for (const page of pages) {
  const from = `.next/server/app${page}.html`;
  const to = `.open-next/assets${page}.html`;
  if (!existsSync(from)) {
    console.error(`static-pages: ${from} is missing`);
    process.exit(1);
  }
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(from, to);
}
console.log(`static-pages: ${pages.join(", ")} served from assets`);
