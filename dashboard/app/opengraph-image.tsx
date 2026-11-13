import { readFile } from "node:fs/promises";
import { join } from "node:path";

import { ImageResponse } from "next/og";

export const alt = "Cupel: thousands of stocks in, a short list out. NSE and US stocks, quarterly results and earnings calls.";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

const INK = "#111113";
const MUTED = "#52525b";
const RULE = "#e4e4e7";

/** The landing's headline weight; next/og only bundles Geist Regular. Built once, so a failed fetch falls back. */
async function geistSemibold(): Promise<ArrayBuffer | null> {
  try {
    const css = await (await fetch("https://fonts.googleapis.com/css2?family=Geist:wght@600")).text();
    const url = css.match(/src: url\((.+?)\) format\('(?:truetype|opentype)'\)/)?.[1];
    return url ? await (await fetch(url)).arrayBuffer() : null;
  } catch {
    return null;
  }
}

/** The share card for every page: the landing's own headline, mark and colours. */
export default async function OpengraphImage() {
  const [semibold, regular, mark] = await Promise.all([
    geistSemibold(),
    // next/og's own copy of Geist: passing any font replaces its default, so the regular weight is named too.
    readFile(join(process.cwd(), "node_modules/next/dist/compiled/@vercel/og/Geist-Regular.ttf")),
    readFile(join(process.cwd(), "app/icon.svg")),
  ]);
  // Many stocks in, a short list out: forty pale bars, the last three in ink.
  const bars = Array.from({ length: 43 }, (_, index) => index);
  return new ImageResponse(
    (
      <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column", justifyContent: "space-between", background: "#ffffff", color: INK, padding: "64px 72px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
          <img src={`data:image/svg+xml;base64,${mark.toString("base64")}`} width={64} height={64} alt="" />
          <div style={{ fontSize: 40, fontWeight: 600, letterSpacing: "-0.02em" }}>Cupel</div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 26 }}>
          <div style={{ display: "flex", flexDirection: "column", fontSize: 84, fontWeight: 600, lineHeight: 1.04, letterSpacing: "-0.035em" }}>
            <div>Thousands of stocks in.</div>
            <div>A short list out.</div>
          </div>
          <div style={{ fontSize: 34, color: MUTED, letterSpacing: "-0.01em" }}>
            NSE and US stocks, quarterly results and earnings calls
          </div>
        </div>

        <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", borderTop: `2px solid ${RULE}`, paddingTop: 28 }}>
          <div style={{ fontSize: 30, color: MUTED }}>cupel.in</div>
          <div style={{ display: "flex", alignItems: "flex-end", gap: 7 }}>
            {bars.map((index) => {
              const kept = index >= bars.length - 3;
              return <div key={index} style={{ width: 8, height: kept ? 44 : 20, borderRadius: 4, background: kept ? INK : RULE }} />;
            })}
          </div>
        </div>
      </div>
    ),
    {
      ...size,
      fonts: [
        { name: "Geist", data: regular, weight: 400, style: "normal" },
        ...(semibold ? [{ name: "Geist", data: semibold, weight: 600 as const, style: "normal" as const }] : []),
      ],
    },
  );
}
