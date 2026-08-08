"""Minimal PostgREST adapter for private transcript data in Supabase."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import requests


class SupabaseRepository:
    def __init__(self, url: str, service_role_key: str, timeout_seconds: int = 30):
        if not url or not service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required")
        self.base_url = f"{url.rstrip('/')}/rest/v1"
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        self.headers = {
            "apikey": service_role_key,
            "Authorization": f"Bearer {service_role_key}",
            "Content-Type": "application/json",
        }

    @classmethod
    def from_environment(cls) -> "SupabaseRepository":
        return cls(
            os.getenv("SUPABASE_URL", ""),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY", ""),
            int(os.getenv("SUPABASE_TIMEOUT_SECONDS", "30")),
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {**self.headers, **kwargs.pop("headers", {})}
        response = self.session.request(
            method,
            f"{self.base_url}/{path.lstrip('/')}",
            headers=headers,
            timeout=self.timeout_seconds,
            **kwargs,
        )
        response.raise_for_status()
        if not response.content:
            return None
        return response.json()

    def upsert_filing(self, filing: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "transcript_filings?on_conflict=exchange,seq_id",
            json=filing,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0]

    def update_filing(self, filing_id: str, **fields: Any) -> None:
        self._request(
            "PATCH",
            f"transcript_filings?id=eq.{filing_id}",
            json=fields,
            headers={"Prefer": "return=minimal"},
        )

    def find_document_by_sha256(self, sha256: str) -> dict[str, Any] | None:
        rows = self._request("GET", f"transcript_documents?sha256=eq.{sha256}&limit=1")
        return rows[0] if rows else None

    def create_document(self, document: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "transcript_documents",
            json=document,
            headers={"Prefer": "return=representation"},
        )
        return rows[0]

    def find_transcript_by_document_id(self, document_id: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "transcripts",
            params={"document_id": f"eq.{document_id}", "limit": "1"},
        )
        return rows[0] if rows else None

    def link_filing_document(self, filing_id: str, document_id: str) -> None:
        self._request(
            "POST",
            "transcript_filing_documents?on_conflict=filing_id",
            json={"filing_id": filing_id, "document_id": document_id},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        )

    def upsert_transcript(self, transcript: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "transcripts?on_conflict=document_id",
            json=transcript,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0]

    def get_sentiment(self, transcript_id: str, model_name: str, analysis_version: str) -> dict[str, Any] | None:
        rows = self._request(
            "GET",
            "transcript_sentiments",
            params={
                "transcript_id": f"eq.{transcript_id}",
                "model_name": f"eq.{model_name}",
                "analysis_version": f"eq.{analysis_version}",
                "limit": "1",
            },
        )
        return rows[0] if rows else None

    def list_transcripts_for_analysis(
        self,
        model_name: str,
        analysis_version: str,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        payload = {
            "requested_model_name": model_name,
            "requested_analysis_version": analysis_version,
            "requested_limit": max(1, int(limit)),
        }
        try:
            transcripts = self._request(
                "POST",
                "rpc/pending_transcripts_for_analysis",
                json=payload,
            )
        except requests.HTTPError as exc:
            if exc.response is None or exc.response.status_code not in {400, 404}:
                raise
            # Transitional compatibility with the previous two-argument RPC.
            payload.pop("requested_limit")
            transcripts = self._request(
                "POST",
                "rpc/pending_transcripts_for_analysis",
                json=payload,
            )[: max(1, int(limit))]
        company_names = self.company_names_by_document_id(
            [transcript["document_id"] for transcript in transcripts if transcript.get("document_id")]
        )
        for transcript in transcripts:
            transcript["company_name"] = company_names.get(transcript.get("document_id"), "")
        return transcripts

    def company_names_by_document_id(self, document_ids: list[str]) -> dict[str, str]:
        if not document_ids:
            return {}
        rows = self._request(
            "GET",
            "transcript_filing_documents",
            params={
                "select": "document_id,transcript_filings(company_name)",
                "document_id": f"in.({','.join(document_ids)})",
            },
        )
        company_names: dict[str, str] = {}
        for row in rows:
            filing = row.get("transcript_filings") or {}
            if isinstance(filing, list):
                filing = filing[0] if filing else {}
            company_name = str(filing.get("company_name") or "").strip()
            if company_name:
                company_names[row["document_id"]] = company_name
        return company_names

    def save_sentiment(self, sentiment: dict[str, Any]) -> dict[str, Any]:
        rows = self._request(
            "POST",
            "transcript_sentiments?on_conflict=transcript_id,model_name,analysis_version",
            json=sentiment,
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
        )
        return rows[0]

    def latest_sentiments(
        self,
        symbols: list[str],
        batch_size: int = 200,
    ) -> list[dict[str, Any]]:
        normalized = list(dict.fromkeys(
            str(symbol).strip().upper()
            for symbol in symbols
            if str(symbol).strip()
        ))
        if not normalized:
            return []
        base_select = (
            "symbol,call_date,overall_score,optimism_score,guidance_score,"
            "risk_score,management_confidence,guidance_direction,optimism_qoq_delta,"
            "uncertainty_qoq_delta,previous_guidance_direction"
        )
        rows: list[dict[str, Any]] = []
        include_structured_output = True
        safe_batch_size = max(1, int(batch_size))
        for start in range(0, len(normalized), safe_batch_size):
            batch = normalized[start:start + safe_batch_size]
            params = {
                "symbol": f"in.({','.join(batch)})",
                "select": (
                    f"{base_select},structured_output"
                    if include_structured_output
                    else base_select
                ),
            }
            try:
                batch_rows = self._request(
                    "GET",
                    "latest_transcript_sentiment",
                    params=params,
                )
            except requests.HTTPError as exc:
                if (
                    not include_structured_output
                    or exc.response is None
                    or exc.response.status_code != 400
                ):
                    raise
                # Transitional compatibility: once an older view rejects the
                # structured column, avoid repeating the failed probe for every
                # remaining symbol batch.
                include_structured_output = False
                params["select"] = base_select
                batch_rows = self._request(
                    "GET",
                    "latest_transcript_sentiment",
                    params=params,
                )
            rows.extend(batch_rows or [])
        return rows

    def upsert_red_flag_snapshots(self, snapshots: list[dict[str, Any]], batch_size: int = 250) -> int:
        fetched_at = datetime.now(timezone.utc).isoformat()
        rows = [{**snapshot, "fetched_at": fetched_at} for snapshot in snapshots]
        saved = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            self._request(
                "POST",
                "red_flag_snapshots?on_conflict=source,symbol",
                json=batch,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            saved += len(batch)
        return saved

    def upsert_red_flag_snapshot_history(
        self,
        snapshots: list[dict[str, Any]],
        observed_on: str,
        batch_size: int = 250,
    ) -> int:
        """Save one idempotent point-in-time observation per policy and day."""

        fetched_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for snapshot in snapshots:
            details = snapshot.get("snapshot") if isinstance(snapshot.get("snapshot"), dict) else {}
            rows.append({
                **snapshot,
                "policy": details.get("policy") or "legacy",
                "observed_on": observed_on,
                "fetched_at": fetched_at,
            })
        saved = 0
        for start in range(0, len(rows), batch_size):
            batch = rows[start:start + batch_size]
            self._request(
                "POST",
                "red_flag_snapshot_history?on_conflict=source,symbol,policy,observed_on",
                json=batch,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            )
            saved += len(batch)
        return saved

    def latest_red_flag_snapshots(self, symbols: list[str], batch_size: int = 200) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        normalized = list(dict.fromkeys(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
        for start in range(0, len(normalized), batch_size):
            batch = normalized[start:start + batch_size]
            rows.extend(self._request(
                "GET",
                "red_flag_snapshots",
                params={
                    "source": "eq.VIGIL",
                    "symbol": f"in.({','.join(batch)})",
                    "select": "source,symbol,severity,flag_count,summary,source_status,source_as_of,snapshot",
                },
            ))
        return rows
