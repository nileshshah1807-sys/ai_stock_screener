"""Join precomputed red-flag snapshots to a scored universe in shadow mode."""

from __future__ import annotations

import numpy as np

from storage.supabase_repository import SupabaseRepository


class RedFlagEnricher:
    def __init__(self, config, repository=None):
        self.config = config
        self.repository = repository

    def enrich(self, scored_df):
        enriched = scored_df.copy()
        enriched["Red_Flag_Status"] = "No coverage"
        enriched["Red_Flag_Severity"] = np.nan
        enriched["Red_Flag_Count"] = 0
        enriched["Red_Flag_Summary"] = "No cached red-flag coverage"
        enriched["Red_Flag_Source"] = ""
        enriched["Red_Flag_As_Of"] = ""
        enriched["Red_Flag_Shadow_Mode"] = True

        repository = self.repository
        if repository is None:
            if not getattr(self.config, "SUPABASE_URL", "") or not getattr(
                self.config, "SUPABASE_SERVICE_ROLE_KEY", ""
            ):
                enriched["Red_Flag_Status"] = "Not configured"
                enriched["Red_Flag_Summary"] = "Red-flag store not configured"
                return enriched
            repository = SupabaseRepository(
                self.config.SUPABASE_URL,
                self.config.SUPABASE_SERVICE_ROLE_KEY,
                getattr(self.config, "SUPABASE_TIMEOUT_SECONDS", 30),
            )

        records = repository.latest_red_flag_snapshots(
            enriched["Symbol"].astype(str).str.upper().tolist()
        )
        by_symbol = {str(record.get("symbol") or "").upper(): record for record in records}
        for index, symbol in enriched["Symbol"].items():
            record = by_symbol.get(str(symbol).upper())
            if not record:
                continue
            source_status = str(record.get("source_status") or "unknown")
            enriched.at[index, "Red_Flag_Status"] = (
                "Available" if source_status == "current" else "Partial/stale"
            )
            enriched.at[index, "Red_Flag_Severity"] = record.get("severity")
            enriched.at[index, "Red_Flag_Count"] = record.get("flag_count", 0)
            enriched.at[index, "Red_Flag_Summary"] = record.get("summary") or "No observed flags"
            enriched.at[index, "Red_Flag_Source"] = record.get("source") or "VIGIL"
            enriched.at[index, "Red_Flag_As_Of"] = record.get("source_as_of") or ""
        return enriched
