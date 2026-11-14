"use client";

import { useState, type Dispatch, type SetStateAction } from "react";

import { draftAfterUrlChange } from "@/lib/url-draft.mjs";

/**
 * A control's editable copy of one URL value. When the URL changes from
 * elsewhere (a saved view, a chip removed, Back) the draft follows it
 * (lib/url-draft.mjs), so no control shows or writes back a stale value.
 */
export function useUrlDraft<T>(
  current: string,
  from: (url: string) => T,
  holds: (draft: T) => string,
): [T, Dispatch<SetStateAction<T>>] {
  const [draft, setDraft] = useState(() => from(current));
  const [synced, setSynced] = useState(current);
  if (current !== synced) {
    setSynced(current);
    setDraft(draftAfterUrlChange(draft, current, from, holds));
  }
  return [draft, setDraft];
}
