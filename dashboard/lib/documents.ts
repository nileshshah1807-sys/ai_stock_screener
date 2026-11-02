import "server-only";

import type { MarketCode } from "@/lib/markets";
import { createClient } from "@/lib/supabase/server";

export type DocumentRow = {
  kind: string;
  announced_at: string;
  title: string;
  url: string;
  period?: string | null;
};

const quarterEnd = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).replace("Sept", "Sep");

/**
 * A company's documents, as links. Results filings come from quarterly_filings
 * (no copy); the rest from company_documents (storage/company_documents_schema.sql,
 * applied by hand). Until that table exists its read fails and the tab shows the
 * filings alone; nothing else breaks. NSE only: no other market has a source.
 */
export async function getCompanyDocuments(market: MarketCode, symbol: string): Promise<DocumentRow[]> {
  if (market !== "NSE") return [];
  const supabase = await createClient();
  const code = symbol.toUpperCase();
  const [filings, documents] = await Promise.all([
    supabase
      .from("quarterly_filings")
      .select("period_end, is_consolidated, filed_at, document_url, viewer_url")
      .eq("market", market)
      .eq("symbol", code)
      .order("period_end", { ascending: false })
      .limit(12),
    supabase
      .from("company_documents")
      .select("kind, announced_at, title, url, period")
      .eq("market", market)
      .eq("symbol", code)
      .order("announced_at", { ascending: false })
      .limit(200),
  ]);
  const results: DocumentRow[] = (filings.data ?? []).flatMap((filing) => {
    const url = filing.viewer_url ?? filing.document_url;
    if (!url || !filing.filed_at) return [];
    const basis = filing.is_consolidated ? "consolidated" : "standalone";
    return [{ kind: "results", announced_at: filing.filed_at, title: `Quarter ended ${quarterEnd(filing.period_end)}, ${basis}`, url }];
  });
  return [...results, ...((documents.error ? [] : documents.data) ?? [])] as DocumentRow[];
}
