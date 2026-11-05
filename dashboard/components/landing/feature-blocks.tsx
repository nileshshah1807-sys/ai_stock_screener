import { S2_CANDIDATE_RULE, STAGE_SAMPLE, STAGES } from "@/lib/landing.mjs";
import { cn } from "@/lib/utils";

/*
 * Two feature blocks for the landing page, each a short argument beside a
 * mock of the page it describes. Companies and figures are invented and every
 * mock is captioned so. No rating, return or recommendation appears.
 */

const caption = "mt-2 text-xs text-muted-foreground";

export function CallsBlock() {
  return (
    <div className="grid items-center gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] lg:gap-14">
      <div>
        <h2 className="text-title max-w-[22ch] text-balance">Hear what management said, without the hour-long call</h2>
        <p className="mt-4 max-w-[52ch] text-sm leading-relaxed text-muted-foreground">
          AI reads each earnings call of an Indian company and pulls out what management said about guidance, demand, margins, orders and capacity. Every quote is checked against the transcript, and the reading is one input to how a stock ranks.
        </p>
        <ul className="mt-4 flex max-w-[52ch] list-disc flex-col gap-2 pl-5 text-sm marker:text-brand text-pretty leading-relaxed text-muted-foreground">
          <li>Each call is compared with the company&apos;s previous call: improved, held or worsened.</li>
          <li>Raised guidance or stronger demand, margins or orders score higher; lowered guidance or weaker demand or margins score lower.</li>
          <li>The tailwinds and headwinds management names are tracked.</li>
        </ul>
      </div>
      <div>
        <figure className="panel p-4">
          <figcaption className="flex flex-wrap items-center justify-between gap-2 text-sm font-semibold">
            Navdeep Chemicals
            <span className="flex flex-wrap gap-1.5">
              <span className="rounded bg-(--control) px-2 py-0.5 text-xs font-medium text-muted-foreground">Management tone: Optimistic</span>
              <span className="rounded bg-(--control) px-2 py-0.5 text-xs font-medium text-muted-foreground">Kept to the previous call and improved on 3 of 5 items</span>
            </span>
          </figcaption>
          <blockquote className="mt-3 border-l-2 border-brand pl-3 text-sm leading-relaxed text-muted-foreground">
            “We expect volumes in the specialty range to keep growing through the second half as the new line ramps up.”
          </blockquote>
        </figure>
        <p className={caption}>Sample call with an invented company and quote, not live data.</p>
      </div>
    </div>
  );
}

export function StageBlock() {
  return (
    <div className="grid items-start gap-8 lg:grid-cols-[minmax(0,6fr)_minmax(0,5fr)] lg:gap-14">
      <div className="order-2 min-w-0 lg:order-1">
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[22rem] text-sm tabular-nums">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th scope="col" className="px-4 py-2 font-medium">Stock</th>
                <th scope="col" className="px-4 py-2 font-medium">Stage</th>
                <th scope="col" className="px-4 py-2 font-medium">RS rating</th>
              </tr>
            </thead>
            <tbody>
              {STAGE_SAMPLE.map((row) => (
                <tr key={row.symbol} className="border-b last:border-0">
                  <th scope="row" className="px-4 py-2.5 text-left font-medium">
                    {row.name} <span className="font-normal text-muted-foreground">{row.symbol}</span>
                  </th>
                  <td className={cn("px-4 py-2.5", row.stage === 2 ? "font-semibold" : "text-muted-foreground")}>Stage {row.stage}</td>
                  <td className="px-4 py-2.5">
                    <span className="flex items-center gap-2">
                      <span className="w-6 text-right">{row.rs}</span>
                      <span aria-hidden className="h-1.5 w-16 rounded-full bg-(--control)">
                        <span className="block h-full rounded-full bg-brand" style={{ width: `${row.rs}%` }} />
                      </span>
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={caption}>Sample rows with invented companies and placeholder figures, not live data.</p>
      </div>
      <div className="order-1 lg:order-2">
        <h2 className="text-title max-w-[22ch] text-balance">See where each stock is in its cycle</h2>
        <p className="mt-4 max-w-[48ch] text-sm leading-relaxed text-muted-foreground">
          Every stock is placed in Stage 1 to 4 from its daily 50, 150 and 200-day averages, and given a relative strength (RS) rating from 1 to 99: its weighted 3 to 12 month return ranked against the rest of its own market. It is relative strength, not a buy or sell rating. Filter the grid to Stage 2 and the Market page counts them each close.
        </p>
        <dl className="mt-5 grid gap-3">
          {STAGES.map((s) => (
            <div key={s.stage} className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 border-t pt-3 text-sm">
              <dt className="font-semibold">Stage {s.stage}<span className="block text-xs font-normal text-muted-foreground">{s.name}</span></dt>
              <dd className="text-muted-foreground">{s.rule}</dd>
            </div>
          ))}
          <div className="grid grid-cols-[5.5rem_minmax(0,1fr)] gap-3 border-t pt-3 text-sm">
            <dt className="font-semibold">S2 Candidate<span className="block text-xs font-normal text-muted-foreground">Pullback</span></dt>
            <dd className="text-muted-foreground">{S2_CANDIDATE_RULE}</dd>
          </div>
        </dl>
      </div>
    </div>
  );
}
