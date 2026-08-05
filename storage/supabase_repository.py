"""Minimal PostgREST adapter for private transcript data in Supabase."""

from __future__ import annotations

import os
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

    def list_transcripts_for_analysis(self, limit: int = 25) -> list[dict[str, Any]]:
        transcripts = self._request(
            "GET",
            "transcripts",
            params={
                "select": "id,document_id,symbol,quarter,call_date,cleaned_text,text_hash,token_count",
                "cleaned_text": "not.is.null",
                "order": "created_at.asc",
                "limit": str(limit),
            },
        )
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

    def latest_sentiments(self, symbols: list[str]) -> list[dict[str, Any]]:
        if not symbols:
            return []
        return self._request(
            "GET",
            "latest_transcript_sentiment",
            params={
                "symbol": f"in.({','.join(symbols)})",
                "select": "symbol,call_date,overall_score,optimism_score,guidance_score,"
                "risk_score,management_confidence,guidance_direction,optimism_qoq_delta",
            },
        )