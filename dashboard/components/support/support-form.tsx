"use client";

import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { CATEGORIES, LIMITS } from "@/lib/support.mjs";

type Status = { kind: "idle" } | { kind: "sending" } | { kind: "sent" } | { kind: "error"; message: string };

const FIELD = "grid gap-1.5";

/** The contact form, for a signed-in visitor. A failed send (or JSM not set up) points at the mailto address. */
export function SupportForm({ email, name, contactEmail }: { email: string; name: string; contactEmail: string }) {
  const [status, setStatus] = useState<Status>({ kind: "idle" });
  const mail = <a href={`mailto:${contactEmail}`} className="underline underline-offset-2">{contactEmail}</a>;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    setStatus({ kind: "sending" });
    try {
      const response = await fetch("/api/support", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.fromEntries(new FormData(form))),
      });
      const payload = await response.json().catch(() => ({}));
      if (response.ok) return setStatus({ kind: "sent" });
      const shown = response.status === 400 || response.status === 429;
      setStatus({ kind: "error", message: shown && payload.error ? payload.error : "" });
    } catch {
      setStatus({ kind: "error", message: "" });
    }
  }

  if (status.kind === "sent") {
    return <p role="status" className="rounded-md border bg-card p-4 text-sm">Thanks, we have your message. We reply by email, usually within two working days.</p>;
  }

  return (
    <form onSubmit={submit} className="grid gap-4" noValidate>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className={FIELD}>
          <Label htmlFor="support-name">Name</Label>
          <Input id="support-name" name="name" defaultValue={name} maxLength={LIMITS.name} autoComplete="name" required />
        </div>
        <div className={FIELD}>
          <Label htmlFor="support-email">Email</Label>
          {/* The reply goes to the account's address, so it is shown, not typed. */}
          <Input id="support-email" value={email} readOnly aria-readonly />
        </div>
      </div>
      <div className={FIELD}>
        <Label htmlFor="support-category">Category</Label>
        <select
          id="support-category"
          name="category"
          defaultValue={CATEGORIES[0]}
          className="h-9 w-full rounded-md border border-input bg-card px-2.5 text-base shadow-xs outline-none hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
        >
          {CATEGORIES.map((category) => <option key={category}>{category}</option>)}
        </select>
      </div>
      <div className={FIELD}>
        <Label htmlFor="support-subject">Subject</Label>
        <Input id="support-subject" name="subject" maxLength={LIMITS.subject} required />
      </div>
      <div className={FIELD}>
        <Label htmlFor="support-message">Message</Label>
        <textarea
          id="support-message"
          name="message"
          rows={6}
          maxLength={LIMITS.message}
          required
          className="w-full min-w-0 rounded-md border border-input bg-card px-3 py-2 text-base shadow-xs outline-none placeholder:text-muted-foreground hover:border-border-strong focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 md:text-sm"
        />
      </div>
      {/* Honeypot: people never see it, form-filling bots do. */}
      <input name="website" tabIndex={-1} autoComplete="off" aria-hidden className="hidden" />
      <div className="flex flex-wrap items-center gap-3">
        <Button type="submit" disabled={status.kind === "sending"}>{status.kind === "sending" ? "Sending…" : "Send message"}</Button>
        {status.kind === "error" ? (
          <p role="alert" className="text-sm text-destructive">
            {status.message || <>That did not go through. Write to {mail} instead.</>}
          </p>
        ) : null}
      </div>
    </form>
  );
}
