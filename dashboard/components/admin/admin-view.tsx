"use client";

import Link from "next/link";
import { useActionState, useRef, useState } from "react";
import { ExternalLink, Loader2, Search, UserPlus } from "lucide-react";

import {
  changeTrial, deleteUser, inviteUser, renameUser, setComplimentary, undoTrialDenial, type AdminState,
} from "@/app/admin/actions";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { FILTERS, razorpayLinkLabel, razorpayUrl } from "@/lib/admin.mjs";
import { formatDate } from "@/lib/format";
import { NAME_MAX } from "@/lib/display-name.mjs";
import type { AdminRow } from "@/lib/admin";

const IDLE: AdminState = { status: "idle" };

const FILTER_LABEL: Record<string, string> = {
  all: "All users", trialing: "Trialing", active: "Active", past_due: "Past due", cancelled: "Cancelled", expired: "Expired",
  denied: "Trial denied", complimentary: "Complimentary", admin: "Admins", none: "No plan",
};

function Result({ state }: { state: AdminState }) {
  if (state.status === "idle" || !state.message) return null;
  return (
    <p role={state.status === "error" ? "alert" : "status"} className={state.status === "error" ? "text-sm text-destructive" : "text-sm text-positive"}>
      {state.message}
    </p>
  );
}

function Submit({ pending, disabled = false, children, variant = "default" }: { pending: boolean; disabled?: boolean; children: React.ReactNode; variant?: "default" | "destructive" | "outline" }) {
  return (
    <Button type="submit" size="sm" variant={variant} disabled={pending || disabled}>
      {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : null}
      {children}
    </Button>
  );
}

function Invite() {
  const [state, action, pending] = useActionState(inviteUser, IDLE);
  return (
    <form action={action} className="flex flex-col gap-2">
      <label htmlFor="invite-email" className="text-sm font-medium">Invite a user</label>
      <div className="flex flex-col gap-2 sm:flex-row">
        <Input key={state.status === "done" ? state.message : "new"} id="invite-email" name="email" type="email" required placeholder="name@example.com" autoComplete="off" className="h-9 sm:max-w-xs" />
        <Button type="submit" size="sm" className="h-9" disabled={pending}>
          {pending ? <Loader2 className="size-3.5 animate-spin" aria-hidden /> : <UserPlus className="size-3.5" aria-hidden />}
          Send invite
        </Button>
      </div>
      <Result state={state} />
    </form>
  );
}

function Manage({ row, adminId, razorpayKeyId, trialDays }: { row: AdminRow; adminId: string; razorpayKeyId: string; trialDays: number }) {
  const [trial, trialAction, trialPending] = useActionState(changeTrial, IDLE);
  const [comp, compAction, compPending] = useActionState(setComplimentary, IDLE);
  const [undo, undoAction, undoPending] = useActionState(undoTrialDenial, IDLE);
  const [rename, renameAction, renamePending] = useActionState(renameUser, IDLE);
  const [del, deleteAction, deletePending] = useActionState(deleteUser, IDLE);
  const dialog = useRef<HTMLDialogElement>(null);
  const [typed, setTyped] = useState("");
  const link = razorpayUrl(row.razorpay_subscription_id);
  const isAdminRow = row.role === "admin";
  const denied = row.guard?.result === "denied";

  // Sticky and as wide as the screen, so on a phone the panel stays in view while the table scrolls under it.
  return (
    <div className="sticky left-0 grid w-[calc(100vw-2rem-2px)] gap-6 border-t bg-(--control)/40 px-4 py-5 text-sm md:grid-cols-2 lg:w-auto">
      <form action={renameAction} className="space-y-2">
        <input type="hidden" name="id" value={row.id} />
        <label htmlFor={`name-${row.id}`} className="font-medium">Display name</label>
        <div className="flex gap-2">
          <Input id={`name-${row.id}`} name="name" defaultValue={row.name} placeholder="No name" maxLength={NAME_MAX + 20} className="h-9 max-w-xs" />
          <Submit pending={renamePending} variant="outline">Save</Submit>
        </div>
        <Result state={rename} />
      </form>

      <form action={trialAction} className="space-y-2">
        <input type="hidden" name="id" value={row.id} />
        <label htmlFor={`days-${row.id}`} className="font-medium">Trial</label>
        <div className="flex flex-wrap items-center gap-2">
          <Input id={`days-${row.id}`} name="days" type="number" min={1} max={365} defaultValue={7} className="h-9 w-20" aria-label="Days" />
          <span className="text-muted-foreground">days</span>
          <Button type="submit" name="mode" value="extend" size="sm" variant="outline" disabled={trialPending}>Extend</Button>
          <Button type="submit" name="mode" value="restart" size="sm" variant="outline" disabled={trialPending}>Restart</Button>
        </div>
        <p className="text-muted-foreground">Extend adds to the current end; restart counts from today and lifts a denial.</p>
        <Result state={trial} />
      </form>

      <div className="space-y-2">
        <p className="font-medium">Complimentary access</p>
        {isAdminRow ? (
          <p className="text-muted-foreground">An admin. The role is changed in SQL.</p>
        ) : (
          <form action={compAction} className="flex items-center gap-3">
            <input type="hidden" name="id" value={row.id} />
            <input type="hidden" name="grant" value={row.complimentary ? "0" : "1"} />
            <Submit pending={compPending} variant="outline">{row.complimentary ? "Remove access" : "Give access"}</Submit>
            <span className="text-muted-foreground">{row.complimentary ? "Has it now, with no end date." : "Free access with no end date."}</span>
          </form>
        )}
        <Result state={comp} />
      </div>

      <div className="space-y-2">
        <p className="font-medium">Trial guard</p>
        {row.guard ? (
          <p className="text-muted-foreground">
            {denied ? "Denied" : "Granted"}{row.guard.reason ? `: ${row.guard.reason}` : ""}
          </p>
        ) : (
          <p className="text-muted-foreground">No record.</p>
        )}
        {denied ? (
          <form action={undoAction}>
            <input type="hidden" name="id" value={row.id} />
            <Submit pending={undoPending} variant="outline">Undo denial ({trialDays}-day trial)</Submit>
          </form>
        ) : null}
        <Result state={undo} />
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t pt-4 md:col-span-2">
        {link ? (
          <a href={link} target="_blank" rel="noopener noreferrer" className="inline-flex items-center gap-1.5 underline-offset-2 hover:underline">
            {razorpayLinkLabel(razorpayKeyId)} <ExternalLink className="size-3.5" aria-hidden />
          </a>
        ) : (
          <span className="text-muted-foreground">No Razorpay subscription.</span>
        )}
        {row.id === adminId || isAdminRow ? (
          <span className="text-muted-foreground">{row.id === adminId ? "This is you." : "Admins are removed in SQL."}</span>
        ) : (
          <>
            <Button type="button" size="sm" variant="destructive" onClick={() => dialog.current?.showModal()}>Delete user</Button>
            <dialog ref={dialog} aria-labelledby={`del-${row.id}`} className="m-auto w-[min(26rem,calc(100vw-2rem))] rounded-lg border bg-card p-5 text-foreground shadow-lg backdrop:bg-black/40">
              <form action={deleteAction} className="space-y-3">
                <input type="hidden" name="id" value={row.id} />
                <h3 id={`del-${row.id}`} className="text-base font-semibold">Delete {row.email}?</h3>
                <p className="text-muted-foreground">
                  This removes the account for good.
                  {row.razorpay_subscription_id && !["cancelled", "expired"].includes(row.status ?? "")
                    ? " Its live Razorpay subscription is cancelled first, in the same step; refunds stay in Razorpay."
                    : ""}
                </p>
                <label htmlFor={`confirm-${row.id}`} className="block">Type the address to confirm</label>
                <Input id={`confirm-${row.id}`} name="confirm" value={typed} onChange={(event) => setTyped(event.target.value)} autoComplete="off" placeholder={row.email} className="h-9" />
                <Result state={del} />
                <div className="flex justify-end gap-2">
                  <Button type="button" size="sm" variant="outline" onClick={() => dialog.current?.close()}>Close</Button>
                  <Submit pending={deletePending} disabled={typed.trim().toLowerCase() !== row.email} variant="destructive">Delete user</Submit>
                </div>
              </form>
            </dialog>
          </>
        )}
      </div>
    </div>
  );
}

const when = (value: string | null) => (value ? formatDate(value) : "–");

export function AdminView({ rows, total, q, status, adminId, razorpayKeyId, trialDays, initialOpen = null }: {
  rows: AdminRow[]; total: number; q: string; status: string; adminId: string; razorpayKeyId: string; trialDays: number; initialOpen?: string | null;
}) {
  const [open, setOpen] = useState<string | null>(initialOpen);
  return (
    <div className="space-y-6">
      <header>
        <p className="mb-2 text-sm"><Link href="/admin/plans" className="underline underline-offset-2 hover:text-foreground">Plans and prices</Link></p>
        <h1 className="text-title font-semibold tracking-tight">Users</h1>
        <p className="mt-1 text-sm text-muted-foreground">{rows.length === total ? `${total} users` : `${rows.length} of ${total} users`}. Every action here is logged.</p>
      </header>

      <section className="panel p-4"><Invite /></section>

      <form method="get" className="flex flex-col gap-2 sm:flex-row" role="search">
        <div className="relative sm:w-80">
          <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" aria-hidden />
          <Input name="q" defaultValue={q} placeholder="Search email or name" aria-label="Search by email or name" className="h-9 pl-8" />
        </div>
        <select name="status" defaultValue={status} aria-label="Filter by status" className="h-9 rounded-md border bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
          {FILTERS.map((f: string) => <option key={f} value={f}>{FILTER_LABEL[f]}</option>)}
        </select>
        <Button type="submit" size="sm" className="h-9">Apply</Button>
      </form>

      <section className="panel overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[56rem] border-collapse text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                {["User", "Plan", "Status", "Signed up", "Last sign-in", "Trial ends", "Next charge", "Trial guard", ""].map((h) => (
                  <th key={h || "manage"} scope="col" className="px-3 py-2 font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            {rows.map((row) => (
              <tbody key={row.id} className="border-t">
                <tr className="hover:bg-(--control)">
                  <td className="max-w-[14rem] px-3 py-2.5">
                    <span className="block truncate font-medium" title={row.email}>{row.email}</span>
                    {row.name ? <span className="block truncate text-xs text-muted-foreground">{row.name}</span> : null}
                  </td>
                  <td className="px-3 py-2.5">{row.plan_claim}</td>
                  <td className={`px-3 py-2.5 ${row.status === "active" ? "text-positive" : row.status === "past_due" ? "text-destructive" : ""}`}>{row.status ?? "–"}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-muted-foreground">{when(row.created_at)}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-muted-foreground">{when(row.last_sign_in_at)}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-muted-foreground">{row.status === "trialing" ? when(row.trial_ends_at) : "–"}</td>
                  <td className="tabular whitespace-nowrap px-3 py-2.5 text-muted-foreground">{when(row.next_charge)}</td>
                  <td className={`max-w-[12rem] px-3 py-2.5 ${row.guard?.result === "denied" ? "text-destructive" : ""}`}>
                    {row.guard ? `${row.guard.result === "denied" ? "Denied" : "Granted"}${row.guard.reason ? ` · ${row.guard.reason}` : ""}` : "–"}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    <Button type="button" size="xs" variant="outline" aria-expanded={open === row.id} onClick={() => setOpen(open === row.id ? null : row.id)}>
                      {open === row.id ? "Close" : "Manage"}
                    </Button>
                  </td>
                </tr>
                {open === row.id ? (
                  <tr><td colSpan={9} className="p-0"><Manage row={row} adminId={adminId} razorpayKeyId={razorpayKeyId} trialDays={trialDays} /></td></tr>
                ) : null}
              </tbody>
            ))}
          </table>
        </div>
        {rows.length === 0 ? <p className="px-4 py-8 text-center text-sm text-muted-foreground">No user matches.</p> : null}
      </section>
    </div>
  );
}
