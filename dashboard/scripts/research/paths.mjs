// Where the study reads its cached data and writes its results: ./out,
// ignored by git (the cached data is ~75 MB).
import { mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const OUT = fileURLToPath(new URL("./out", import.meta.url));
mkdirSync(OUT, { recursive: true });
export const out = (name) => `${OUT}/${name}`;

/** The service-role client. Local research only; reads, never writes. */
export async function supabase() {
  const { createClient } = await import("@supabase/supabase-js");
  const { SUPABASE_URL: url, SUPABASE_SERVICE_ROLE_KEY: key } = process.env;
  if (!url || !key) throw new Error("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (see README.md).");
  return createClient(url, key, { auth: { persistSession: false } });
}

export async function pages(build) {
  const rows = [];
  for (let offset = 0; ; offset += 1000) {
    const { data, error } = await build().range(offset, offset + 999);
    if (error) throw error;
    rows.push(...data);
    if (data.length < 1000) return rows;
  }
}
