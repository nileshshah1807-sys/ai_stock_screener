import { cn } from "@/lib/utils"

/**
 * Placeholder block.
 *
 * A left-to-right sheen rather than a pulse. A pulse fades the whole block in
 * and out, which reads as "this element is disabled"; a sheen travels, which
 * reads as "work is in progress" -- the distinction matters when the wait is a
 * ~250ms round trip and the user is deciding whether the app is stuck.
 *
 * The sheen is a pseudo-element running on `transform` alone, so it composites
 * on the GPU and a full page of placeholders costs no layout work. Under
 * prefers-reduced-motion the global rule in globals.css collapses it to a
 * static block, which is still a perfectly good placeholder.
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "relative isolate overflow-hidden rounded-md bg-muted",
        "after:absolute after:inset-0 after:animate-sweep after:content-['']",
        "after:bg-linear-to-r after:from-transparent after:via-foreground/10 after:to-transparent",
        className,
      )}
      {...props}
    />
  )
}

export { Skeleton }
