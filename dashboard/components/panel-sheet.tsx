"use client";

import { useSyncExternalStore } from "react";
import { X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetClose, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

// Side sheet from sm up, bottom sheet below: the same panel either way.
const WIDE = "(min-width: 40rem)";
const subscribe = (change: () => void) => {
  const list = window.matchMedia(WIDE);
  list.addEventListener("change", change);
  return () => list.removeEventListener("change", change);
};
const useWide = () => useSyncExternalStore(subscribe, () => window.matchMedia(WIDE).matches, () => false);

// One motion for every panel: a 240 ms ease-out slide with a fade; instant under reduced motion.
const MOTION = "duration-[240ms] ease-out motion-reduce:transition-none";

/**
 * The app's one panel (Filters, Your score): slides in from the right on a
 * wide screen and up from the bottom on a phone, with the same header
 * (title, an optional aside, X), a scrolling body and a sticky footer (a
 * muted note on the left, the actions on the right). Modal: focus stays in
 * it and Escape closes it (Base UI Dialog).
 */
export function PanelSheet({
  trigger,
  open,
  onOpenChange,
  title,
  description,
  aside,
  header,
  note,
  actions,
  initialFocus,
  children,
}: {
  /** A SheetTrigger, when the panel opens from its own button. */
  trigger?: React.ReactNode;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  description?: React.ReactNode;
  /** Beside the title: a count, a clear-all. */
  aside?: React.ReactNode;
  /** Under the title, still pinned: a search field. */
  header?: React.ReactNode;
  /** The footer's left side; announced politely when it changes. */
  note?: React.ReactNode;
  actions: React.ReactNode;
  initialFocus?: React.ComponentProps<typeof SheetContent>["initialFocus"];
  children: React.ReactNode;
}) {
  const wide = useWide();
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      {trigger}
      <SheetContent
        side={wide ? "right" : "bottom"}
        showCloseButton={false}
        initialFocus={initialFocus}
        overlayClassName={MOTION}
        className={cn(
          "gap-0 p-0 outline-none",
          "data-[side=right]:w-[calc(100%-1rem)] data-[side=right]:sm:max-w-md data-[side=bottom]:max-h-[85dvh]",
          MOTION,
        )}
      >
        <header className="space-y-3 border-b border-border/70 px-5 pt-3 pb-3">
          <div className="flex min-h-11 items-center gap-2">
            <SheetTitle className="text-base font-semibold">{title}</SheetTitle>
            {aside}
            <span className="flex-1" />
            <SheetClose render={<Button variant="ghost" size="icon" className="-mr-2 size-11" aria-label="Close" />}>
              <X className="size-4" aria-hidden />
            </SheetClose>
          </div>
          {description ? <SheetDescription className="-mt-2 text-xs leading-relaxed">{description}</SheetDescription> : null}
          {header}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-5">{children}</div>

        {/* On a phone the note takes its own line above the actions; from sm up they share one. */}
        <footer className="flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-border/70 px-5 pt-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]">
          <p className="min-w-0 flex-1 text-xs leading-snug text-muted-foreground max-sm:basis-full" aria-live="polite">
            {note}
          </p>
          <div className="ml-auto flex items-center gap-2">{actions}</div>
        </footer>
      </SheetContent>
    </Sheet>
  );
}
