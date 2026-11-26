// Run after `opennextjs-cloudflare build`, from dashboard/: copies each app/(static) page's
// prerendered HTML into .open-next/assets at its URL path (/ind/flows -> ind/flows.html), so
// Cloudflare serves it without running the Next server, and its RSC payload and segments beside
// it, which worker.mjs answers a client navigation with (lib/static-pages.mjs). Which pages:
// lib/static-pages.mjs. The pages and their payload headers go to .open-next/static-pages.json,
// which worker.mjs imports.
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { pagesNotWorkerFirst, rscHeaders, segmentFile, staticPages } from "../lib/static-pages.mjs";

const fail = (message) => {
  console.error(`static-pages: ${message}`);
  process.exit(1);
};
const json = (path) => JSON.parse(readFileSync(path, "utf8"));
const pages = staticPages(json(".next/server/app-paths-manifest.json"), json(".next/prerender-manifest.json"));
if (!pages.length) fail("no app/(static) page was prerendered; every one would cost the Worker a render");
for (const config of ["wrangler.jsonc", "wrangler.preview.jsonc"]) {
  const missing = pagesNotWorkerFirst(pages, readFileSync(config, "utf8"));
  if (missing.length) fail(`${config} assets.run_worker_first lacks ${missing.join(", ")}; links to them would reload the page`);
}

const headers = {};
for (const page of pages) {
  const from = `.next/server/app${page}`;
  const to = `.open-next/assets${page}`;
  for (const file of [".html", ".rsc", ".meta"]) if (!existsSync(from + file)) fail(`${from}${file} is missing`);
  mkdirSync(dirname(to), { recursive: true });
  copyFileSync(`${from}.html`, `${to}.html`);
  copyFileSync(`${from}.rsc`, `${to}.rsc`);
  if (existsSync(`${from}.segments`)) {
    mkdirSync(`${to}.segments`, { recursive: true });
    for (const file of readdirSync(`${from}.segments`, { recursive: true })) {
      if (!file.endsWith(".segment.rsc")) continue;
      const name = segmentFile(`/${file.split("\\").join("/").slice(0, -".segment.rsc".length)}`);
      if (!name) fail(`${from}.segments/${file} has no file name`);
      copyFileSync(`${from}.segments/${file}`, `${to}.segments/${name}`);
    }
  }
  headers[page] = rscHeaders(json(`${from}.meta`));
}
writeFileSync(".open-next/static-pages.json", JSON.stringify(headers));
console.log(`static-pages: ${pages.join(", ")} served from assets`);
