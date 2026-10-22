import { Button as ButtonPrimitive } from "@base-ui/react/button"
import { cva, type VariantProps } from "class-variance-authority"

import { cn } from "@/lib/utils"

/*
 * Buttons: 6px corners, near-black when the button is the primary action,
 * a white face with a hairline when it is a secondary one (outline), and no
 * face at all until hovered when it is a quiet one (ghost). Icon-only buttons
 * are squares with the same corners.
 *
 * Press feedback is a scale rather than the previous 1px nudge. `translate-y`
 * moved the button inside its own layout box, which makes a row of controls
 * appear to twitch; a transform-only scale about the centre cannot shift a
 * neighbour. The scale is skipped for menu triggers so a popover anchor stays
 * put while its panel is open.
 *
 * The press is asymmetric, the way UIKit's is: going down takes ~70ms with a
 * plain ease-out, so it lands on the frame the pointer went down on; coming
 * back up uses the 0.8-damped spring, because the release is the half of the
 * gesture that carries energy. `:active` swaps the duration and curve, so the
 * base values describe the release.
 *
 * Secondary and ghost-hover fills use --control, one step off the card.
 */
const buttonVariants = cva(
  "group/button inline-flex shrink-0 items-center justify-center rounded-md border border-transparent bg-clip-padding text-sm font-medium whitespace-nowrap outline-none select-none transition-[background-color,border-color,color,box-shadow,transform] duration-(--duration-spring-bouncy) ease-(--ease-spring) focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 active:not-aria-[haspopup]:scale-[0.97] active:duration-(--duration-press) active:ease-out disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive aria-invalid:ring-3 aria-invalid:ring-destructive/20 dark:aria-invalid:border-destructive/50 dark:aria-invalid:ring-destructive/40 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          "bg-primary text-primary-foreground shadow-xs hover:bg-primary/88",
        outline:
          "border-border bg-card text-foreground shadow-xs hover:bg-(--control) aria-expanded:bg-(--control) aria-expanded:text-accent-foreground",
        secondary:
          "bg-(--control) text-secondary-foreground hover:bg-(--control-hover) aria-expanded:bg-(--control-hover) aria-expanded:text-secondary-foreground",
        ghost:
          "hover:bg-(--control) hover:text-foreground aria-expanded:bg-(--control) aria-expanded:text-foreground",
        destructive:
          "bg-destructive/10 text-destructive hover:bg-destructive/20 focus-visible:border-destructive/40 focus-visible:ring-destructive/20 dark:bg-destructive/20 dark:hover:bg-destructive/30 dark:focus-visible:ring-destructive/40",
        link: "rounded-sm text-foreground underline-offset-4 hover:underline",
      },
      size: {
        default:
          "h-9 gap-1.5 px-3.5 has-data-[icon=inline-end]:pr-3 has-data-[icon=inline-start]:pl-3",
        xs: "h-6 gap-1 px-2.5 text-xs has-data-[icon=inline-end]:pr-2 has-data-[icon=inline-start]:pl-2 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1 px-3 text-[0.8rem] has-data-[icon=inline-end]:pr-2.5 has-data-[icon=inline-start]:pl-2.5 [&_svg:not([class*='size-'])]:size-3.5",
        lg: "h-10 gap-2 px-5 has-data-[icon=inline-end]:pr-4 has-data-[icon=inline-start]:pl-4",
        icon: "size-9",
        "icon-xs": "size-6 [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8",
        "icon-lg": "size-10",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
)

function Button({
  className,
  variant = "default",
  size = "default",
  ...props
}: ButtonPrimitive.Props & VariantProps<typeof buttonVariants>) {
  return (
    <ButtonPrimitive
      data-slot="button"
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  )
}

export { Button, buttonVariants }
