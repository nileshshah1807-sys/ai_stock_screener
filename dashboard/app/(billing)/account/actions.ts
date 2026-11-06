"use server";

import { revalidatePath } from "next/cache";

import { getSession } from "@/lib/auth";
import { cleanDisplayName } from "@/lib/display-name.mjs";
import { createClient } from "@/lib/supabase/server";

export type NameState = { status: "idle" | "saved" | "error"; message?: string };

/**
 * Saves the display name in the person's own auth metadata (no table, no
 * schema change). Only the signed-in user can change their own: updateUser acts
 * on the session, never on an id from the form. An empty field clears the name.
 */
export async function saveDisplayName(_prev: NameState, formData: FormData): Promise<NameState> {
  if (!(await getSession())) return { status: "error", message: "Sign in again to change your name." };
  const cleaned = cleanDisplayName(formData.get("name"));
  if (!cleaned.ok) return { status: "error", message: cleaned.message };

  const supabase = await createClient();
  const { error } = await supabase.auth.updateUser({ data: { full_name: cleaned.name } });
  if (error) return { status: "error", message: "That did not save. Try again in a moment." };
  revalidatePath("/account");
  return { status: "saved", message: cleaned.name ? "Saved." : "Name removed." };
}
