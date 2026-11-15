"use client"

import { Switch as SwitchPrimitive } from "@base-ui/react/switch"

import { cn } from "@/lib/utils"

// role="switch" with aria-checked comes from Base UI; the after: inset gives a 44 px touch target around the 24 px track.
function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return (
    <SwitchPrimitive.Root
      data-slot="switch"
      className={cn(
        "peer relative inline-flex h-6 w-10 shrink-0 items-center rounded-full border border-border bg-input p-0.5 transition-colors duration-200 ease-out outline-none after:absolute after:-inset-x-1 after:-inset-y-2.5 focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 data-checked:border-transparent data-checked:bg-primary motion-reduce:transition-none dark:bg-input/80 dark:data-checked:bg-primary",
        className
      )}
      {...props}
    >
      <SwitchPrimitive.Thumb
        data-slot="switch-thumb"
        className="pointer-events-none block size-[1.125rem] rounded-full bg-background shadow-sm ring-0 transition-transform duration-200 ease-out data-checked:translate-x-4 motion-reduce:transition-none"
      />
    </SwitchPrimitive.Root>
  )
}

export { Switch }
