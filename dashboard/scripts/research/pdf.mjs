// Renders out/report.html to out/report.pdf with a headless Chromium.
// Playwright is not a dashboard dependency; install it where you run this:
//   npm i --no-save playwright && npx playwright install chromium
import { out } from "./paths.mjs";

let chromium;
try {
  ({ chromium } = await import("playwright"));
} catch {
  throw new Error("playwright is not installed: npm i --no-save playwright && npx playwright install chromium");
}
const browser = await chromium.launch();
const page = await browser.newPage();
await page.goto(`file://${out("report.html")}`, { waitUntil: "networkidle" });
await page.pdf({
  path: out("report.pdf"), format: "A4", printBackground: true,
  margin: { top: "16mm", bottom: "16mm", left: "15mm", right: "15mm" },
  displayHeaderFooter: true, headerTemplate: "<span></span>",
  footerTemplate: '<div style="font-size:7px;color:#94a3b8;width:100%;text-align:center;font-family:sans-serif">Winnow · Returns filter study · page <span class="pageNumber"></span> of <span class="totalPages"></span></div>',
});
await browser.close();
console.log(out("report.pdf"));
