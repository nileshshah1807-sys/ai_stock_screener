"use client";

import { useState } from "react";

import { SegmentedControl } from "@/components/segmented-control";

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

  const select = (key: string) => {
    setActive(key);
    setVisited((seen) => (seen.has(key) ? seen : new Set(seen).add(key)));
    try {
      const url = new URL(window.location.href);
      if (key === tabs[0].key) url.searchParams.delete("tab");
      else url.searchParams.set("tab", key);
      window.history.replaceState(window.history.state, "", url);
    } catch {
      // A URL that cannot be rewritten only costs deep-linking, not the tab.
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex justify-center sm:justify-start">
        <SegmentedControl
          label="Stock sections"
          kind="tabs"
          size="md"
          idPrefix="stock"
          value={active}
          onChange={select}
          options={tabs.map((tab) => ({ value: tab.key, label: tab.label }))}
        />
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
