"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowDown } from "lucide-react";

import { createClient } from "@/lib/supabase/client";
import { clock, mergeLines, sampleLines } from "@/lib/live-calls.mjs";
import type { LiveLine } from "@/lib/live-calls";

const POLL_MS = 4000;
/** Within this many pixels of the page's end counts as reading the newest line. */
const NEAR_END = 160;

const nearEnd = () => window.innerHeight + window.scrollY >= document.body.scrollHeight - NEAR_END;

/**
 * A call's lines as they arrive: newest at the bottom, announced politely to a
 * screen reader. Polls `live_call_feed` by cursor (the last seq held) every
 * few seconds, not while the tab is hidden, with `live_call_state` beside it,
 * and stops once the call has ended. A sample call (tables not
 * applied) is generated here instead.
 */
export function LiveTranscript({
  callId,
  sample,
  startedAt,
  initialLines,
  initialState,
}: {
  callId: string;
  sample: boolean;
  startedAt: string | null;
  initialLines: LiveLine[];
  initialState: string;
}) {
  const [lines, setLines] = useState(initialLines);
  const [state, setState] = useState(initialState);
  const [failed, setFailed] = useState(false);
  const [unseen, setUnseen] = useState(0);
  const cursor = useRef(initialLines.at(-1)?.seq ?? 0);
  const follow = useRef(true);
  const end = useRef<HTMLDivElement>(null);

  const poll = useCallback(async () => {
    let incoming: LiveLine[];
    let next = state;
    if (sample) {
      const elapsed = (Date.now() - Date.parse(startedAt ?? new Date().toISOString())) / 1000;
      incoming = sampleLines(elapsed, cursor.current);
    } else {
      const supabase = createClient();
      // State is its own read: a poll past the cursor returns no row once the call has said its last line.
      const [lineRead, stateRead] = await Promise.all([
        supabase
          .from("live_call_feed")
          .select("seq, start_seconds, text")
          .eq("call_id", callId)
          .gt("seq", cursor.current)
          .order("seq", { ascending: true }),
        supabase.from("live_call_state").select("state").eq("call_id", callId).maybeSingle(),
      ]);
      if (lineRead.error || stateRead.error) return setFailed(true);
      setFailed(false);
      incoming = (lineRead.data ?? []).map((row) => ({ ...row, start_seconds: Number(row.start_seconds) }));
      next = stateRead.data?.state ?? state;
    }
    const fresh = incoming.filter((line) => line.seq != null && line.seq > cursor.current);
    setState(next);
    if (!fresh.length) return;
    follow.current = nearEnd();
    cursor.current = fresh[fresh.length - 1].seq;
    setLines((held) => mergeLines(held, fresh));
    if (!follow.current) setUnseen((count) => count + fresh.length);
  }, [callId, sample, startedAt, state]);

  useEffect(() => {
    if (state === "ended") return;
    const timer = setInterval(() => {
      if (!document.hidden) void poll();
    }, POLL_MS);
    return () => clearInterval(timer);
  }, [poll, state]);

  useEffect(() => {
    if (follow.current) end.current?.scrollIntoView({ block: "end" });
  }, [lines.length]);

  return (
    <div>
      {lines.length ? (
        <ol aria-live="polite" aria-label="Live transcript" className="panel divide-y">
          {lines.map((line) => (
            <li key={line.seq} className="flex gap-3 px-4 py-2.5 text-sm leading-relaxed">
              <time className="tabular w-12 shrink-0 pt-px font-mono text-xs text-muted-foreground">
                {clock(line.start_seconds)}
              </time>
              <span className="min-w-0 flex-1 break-words">{line.text}</span>
            </li>
          ))}
        </ol>
      ) : (
        <div aria-live="polite" className="panel px-5 py-10 text-center text-sm text-muted-foreground">
          Waiting for the first words&hellip;
        </div>
      )}
      <p className="mt-3 text-center text-xs text-muted-foreground" role="status">
        {state === "ended"
          ? "The call has ended."
          : failed
            ? "Connection lost; trying again."
            : "Updating every few seconds."}
      </p>
      <div ref={end} />
      {unseen ? (
        <button
          type="button"
          onClick={() => {
            follow.current = true;
            setUnseen(0);
            end.current?.scrollIntoView({ block: "end" });
          }}
          className="fixed bottom-5 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full border bg-card px-4 py-2 text-xs font-medium shadow-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <ArrowDown className="size-3.5" aria-hidden /> {unseen} new {unseen === 1 ? "line" : "lines"}
        </button>
      ) : null}
    </div>
  );
}
