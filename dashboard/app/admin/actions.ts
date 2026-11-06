"use server";

import { revalidatePath } from "next/cache";

import { adminContext, cancelRazorpay, logAdminAction } from "@/lib/admin";
import {
  cleanEmail, complimentaryPlan, exactLike, deletePlan, isEmail, namePlan, parseDays, trialPlan, undoDenialPlan,
} from "@/lib/admin.mjs";

export type AdminState = { status: "idle" | "done" | "error"; message?: string };

const fail = (message: string): AdminState => ({ status: "error", message });
const NOT_ADMIN = fail("Admin access is needed for this.");

type Ctx = NonNullable<Awaited<ReturnType<typeof adminContext>>>;
type Target = { id: string; email: string; role: string | null };

/** The target is looked up here, by id, only after the admin check: the form's id picks a row, never a permission. */
async function targetOf({ db }: Ctx, formData: FormData): Promise<Target | null> {
  const id = String(formData.get("id") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(id)) return null;
  const { data } = await db.auth.admin.getUserById(id);
  if (!data.user?.email) return null;
  const email = cleanEmail(data.user.email);
  const { data: member } = await db.from("dashboard_allowlist").select("role").ilike("email", exactLike(email)).maybeSingle();
  return { id: data.user.id, email, role: member?.role ?? null };
}

const record = (ctx: Ctx, action: string, target: Partial<Target>, detail = {}) => logAdminAction(ctx, action, target, detail);

const done = (message: string): AdminState => {
  revalidatePath("/admin");
  return { status: "done", message };
};

export async function inviteUser(_prev: AdminState, formData: FormData): Promise<AdminState> {
  const ctx = await adminContext();
  if (!ctx) return NOT_ADMIN;
  const email = cleanEmail(formData.get("email"));
  if (!isEmail(email)) return fail("Enter a valid email address.");
  const { data, error } = await ctx.db.auth.admin.inviteUserByEmail(email);
  if (error) return fail(error.message || "The invitation was not sent.");
  return done(`Invitation sent to ${email}.${await record(ctx, "invite", { id: data.user?.id, email })}`);
}

export async function changeTrial(_prev: AdminState, formData: FormData): Promise<AdminState> {
  const ctx = await adminContext();
  if (!ctx) return NOT_ADMIN;
  const target = await targetOf(ctx, formData);
  if (!target) return fail("User not found.");
  const mode = String(formData.get("mode"));
  const days = parseDays(formData.get("days"));
  const { data: sub } = await ctx.db.from("subscriptions").select("status, trial_ends_at").eq("user_id", target.id).maybeSingle();
  const plan = trialPlan(sub, mode, days ?? 0);
  if (!plan.ok) return fail(plan.message ?? "Not allowed.");
  const { error } = await ctx.db.from("subscriptions").update(plan.patch ?? {}).eq("user_id", target.id);
  if (error) return fail("The trial was not changed.");
  const action = mode === "restart" ? "trial_restart" : "trial_extend";
  return done(`Trial ${mode === "restart" ? "restarted" : "extended"}: ${days} days, ends ${String(plan.patch?.trial_ends_at).slice(0, 10)}.${await record(ctx, action, target, { days, ends: plan.patch?.trial_ends_at })}`);
}

export async function setComplimentary(_prev: AdminState, formData: FormData): Promise<AdminState> {
  const ctx = await adminContext();
  if (!ctx) return NOT_ADMIN;
  const target = await targetOf(ctx, formData);
  if (!target) return fail("User not found.");
  const grant = formData.get("grant") === "1";
  const plan = complimentaryPlan(target.role ? { role: target.role } : null, grant);
  if (!plan.ok) return fail(plan.message ?? "Not allowed.");
  // Never writes a role: a new row is a viewer, and a delete is limited to viewer rows.
  const { error } = plan.op === "insert"
    ? await ctx.db.from("dashboard_allowlist").insert({ email: target.email, role: "viewer" })
    : await ctx.db.from("dashboard_allowlist").delete().ilike("email", exactLike(target.email)).eq("role", "viewer");
  if (error) return fail("Access was not changed.");
  return done(`${grant ? "Complimentary access given" : "Complimentary access removed"}.${await record(ctx, grant ? "comp_grant" : "comp_remove", target)}`);
}

export async function undoTrialDenial(_prev: AdminState, formData: FormData): Promise<AdminState> {
  const ctx = await adminContext();
  if (!ctx) return NOT_ADMIN;
  const target = await targetOf(ctx, formData);
  if (!target) return fail("User not found.");
  const [{ data: sub }, { data: signal }] = await Promise.all([
    ctx.db.from("subscriptions").select("trial_denied_at").eq("user_id", target.id).maybeSingle(),
    ctx.db.from("trial_signals").select("granted").eq("user_id", target.id).maybeSingle(),
  ]);
  const plan = undoDenialPlan(sub, signal);
  if (!plan.ok) return fail(plan.message ?? "Not allowed.");
  const first = await ctx.db.from("subscriptions").update(plan.subscription ?? {}).eq("user_id", target.id);
  if (first.error) return fail("The denial was not undone.");
  const second = await ctx.db.from("trial_signals").update(plan.signal ?? {}).eq("user_id", target.id);
  if (second.error) return fail("The trial was granted but the guard record was not updated.");
  return done(`Denial undone: a 7-day trial starts now.${await record(ctx, "undo_denial", target)}`);
}

export async function renameUser(_prev: AdminState, formData: FormData): Promise<AdminState> {
  const ctx = await adminContext();
  if (!ctx) return NOT_ADMIN;
  const target = await targetOf(ctx, formData);
  if (!target) return fail("User not found.");
  const cleaned = namePlan(formData.get("name"));
  if (!cleaned.ok) return fail(cleaned.message);
  const { error } = await ctx.db.auth.admin.updateUserById(target.id, { user_metadata: { full_name: cleaned.name } });
  if (error) return fail("The name was not saved.");
  return done(`${cleaned.name ? "Name saved" : "Name removed"}.${await record(ctx, "rename", target, { name: cleaned.name })}`);
}

export async function deleteUser(_prev: AdminState, formData: FormData): Promise<AdminState> {
  const ctx = await adminContext();
  if (!ctx) return NOT_ADMIN;
  const target = await targetOf(ctx, formData);
  const { data: sub } = target
    ? await ctx.db.from("subscriptions").select("status, razorpay_subscription_id").eq("user_id", target.id).maybeSingle()
    : { data: null };
  const plan = deletePlan({ actorId: ctx.viewer.id, target, sub, typedEmail: String(formData.get("confirm") ?? "") });
  if (!plan.ok || !target) return fail(plan.ok ? "User not found." : (plan.message ?? "Not allowed."));

  // Cancel first: if Razorpay refuses, the user and their subscription are left as they were.
  if (plan.cancelFirst && !(await cancelRazorpay(plan.cancelFirst))) {
    return fail(`The Razorpay subscription ${plan.cancelFirst} could not be cancelled, so nobody was deleted. Check it in Razorpay and try again.`);
  }
  const { error } = await ctx.db.auth.admin.deleteUser(target.id);
  if (error) {
    const note = await record(ctx, "delete", target, { cancelled: plan.cancelFirst, deleted: false });
    return fail(`${plan.cancelFirst ? `Subscription ${plan.cancelFirst} was cancelled, but the` : "The"} user was not deleted.${note}`);
  }
  // A leftover complimentary row would give a person who signs up again with this address access.
  await ctx.db.from("dashboard_allowlist").delete().ilike("email", exactLike(target.email)).eq("role", "viewer");
  const note = await record(ctx, "delete", target, { cancelled: plan.cancelFirst, deleted: true });
  return done(`${target.email} deleted.${plan.cancelFirst ? ` Razorpay subscription ${plan.cancelFirst} was cancelled first.` : ""}${note}`);
}
