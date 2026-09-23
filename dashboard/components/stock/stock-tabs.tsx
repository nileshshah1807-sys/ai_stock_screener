"use client";

import { useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { GlassTrack } from "@/components/glass-track";

export type StockTab = {
  key: string;
  label: string;
  content: React.ReactNode;
};

/**
 * Overview / Financials / Audit.
 *
 * Every tab's content is already rendered on the server, so switching is a
 * local state change with no round trip: the lens moves on pointer-down and the
 * panel is there on the same frame. The URL follows along (`?tab=financials`)
 * through `replaceState`, so a tab can be linked or reloaded without each
 * switch becoming a history entry the Back button has to walk through.
 *
 * A tab mounts the first time it is shown and then stays mounted. Mounting
 * everything up front would build the Overview's charts inside a hidden box,
 * where they measure zero width; mounting on every switch would throw away
 * scroll position and replay entrance motion.
 */
export function StockTabs({
  tabs,
  initial,
}: {
  tabs: StockTab[];
  initial: string;
}) {
  const first = tabs.some((tab) => tab.key === initial) ? initial : tabs[0].key;
  const [active, setActive] = useState(first);
  const [visited, setVisited] = useState<Set<string>>(() => new Set([first]));
  const buttons = useRef<Map<string, HTMLButtonElement>>(new Map());

  const select = (key: string, focus = false) => {
    setActive(key);
    setVisited((seen) => (seen.has(key) ? seen : new Set(seen).add(key)));
    if (focus) buttons.current.get(key)?.focus();
    try {
      const url = new URL(window.location.href);
      if (key === tabs[0].key) url.searchParams.delete("tab");
      else url.searchParams.set("tab", key);
      window.history.replaceState(window.history.state, "", url);
    } catch {
      // A URL that cannot be rewritten only costs deep-linking, not the tab.
    }
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    const index = tabs.findIndex((tab) => tab.key === active);
    const step =
      event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (event.key === "Home") {
      event.preventDefault();
      select(tabs[0].key, true);
    } else if (event.key === "End") {
      event.preventDefault();
      select(tabs[tabs.length - 1].key, true);
    } else if (step) {
      event.preventDefault();
      select(tabs[(index + step + tabs.length) % tabs.length].key, true);
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-center sm:justify-start">
        <GlassTrack
          label="Stock sections"
          role="tablist"
          className="gap-0.5 p-1"
          onKeyDown={onKeyDown}
        >
          {tabs.map((tab) => {
            const selected = tab.key === active;
            return (
              <button
                key={tab.key}
                ref={(node) => {
                  if (node) buttons.current.set(tab.key, node);
                  else buttons.current.delete(tab.key);
                }}
                type="button"
                role="tab"
                id={`stock-tab-${tab.key}`}
                aria-selected={selected}
                aria-controls={`stock-panel-${tab.key}`}
                tabIndex={selected ? 0 : -1}
                // Selection happens on pointer-down, the moment the finger
                // lands; click stays as the keyboard/assistive path.
                onPointerDown={(event) => {
                  if (event.button === 0) select(tab.key);
                }}
                onClick={() => select(tab.key)}
                className={cn(
                  "relative inline-flex min-h-9 items-center justify-center rounded-full px-5 text-sm",
                  "transition-[color,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring)",
                  "active:scale-[0.95] active:duration-(--duration-press) active:ease-out",
                  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1",
                  selected
                    ? "font-semibold text-foreground"
                    : "font-medium text-muted-foreground hover:text-foreground",
                )}
              >
                {tab.label}
              </button>
            );
          })}
        </GlassTrack>
      </div>

      {tabs.map((tab) =>
        visited.has(tab.key) ? (
          <div
            key={tab.key}
            role="tabpanel"
            id={`stock-panel-${tab.key}`}
            aria-labelledby={`stock-tab-${tab.key}`}
            hidden={tab.key !== active}
            // Arriving content fades up; a quick settle so figures are never
            // withheld. Reduced motion collapses it through the global rule.
            className="space-y-4 data-[shown=true]:animate-rise"
            data-shown={tab.key === active}
          >
            {tab.content}
          </div>
        ) : null,
      )}
    </div>
  );
}
