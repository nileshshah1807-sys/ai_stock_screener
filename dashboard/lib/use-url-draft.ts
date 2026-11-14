"use client";

import { useCallback, useState, type Dispatch, type SetStateAction } from "react";

import { draftAfterUrlChange } from "@/lib/url-draft.mjs";

/**
 * A control's editable copy of one URL value. When the URL changes from
 * elsewhere (a saved view, a chip removed, Back) the draft follows it
 * (lib/url-draft.mjs), so no control shows or writes back a stale value.
 * Call `pushed(value)` as the control writes `value` to the URL, so its own
 * push landing late never snaps the draft back.
 */
export function useUrlDraft<T>(
  current: string,
  from: (url: string) => T,
  holds: (draft: T) => string,
): [T, Dispatch<SetStateAction<T>>, (value: string) => void] {
  const [draft, setDraft] = useState(() => from(current));
  const [synced, setSynced] = useState(current);
  const [pending, setPending] = useState<string[]>([]);
  if (current !== synced) {
    const next = draftAfterUrlChange(draft, current, from, holds, pending);
    setSynced(current);
    setPending(next.pending);
    if (next.draft !== draft) setDraft(next.draft);
  }
  // Stable: callers list it in effect dependencies.
  const pushed = useCallback((value: string) => setPending((list) => [...list, value]), []);
  return [draft, setDraft, pushed];
}
