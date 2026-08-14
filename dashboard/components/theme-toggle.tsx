"use client";

import { useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

const OPTIONS = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
] as const;

const subscribeToHydration = () => () => {};

export function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  // This is false during server rendering and the first hydration pass, which
  // keeps the placeholder icon consistent without an effect-driven re-render.
  const mounted = useSyncExternalStore(subscribeToHydration, () => true, () => false);

  const Icon = mounted
    ? (OPTIONS.find((option) => option.value === theme)?.icon ?? Monitor)
    : Monitor;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <Button variant="ghost" size="icon" aria-label="Change colour theme" />
        }
      >
        <Icon className="size-4" aria-hidden />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        {OPTIONS.map(({ value, label, icon: OptionIcon }) => (
          <DropdownMenuItem
            key={value}
            onClick={() => setTheme(value)}
            className="gap-2"
          >
            <OptionIcon className="size-4" aria-hidden />
            {label}
            {mounted && theme === value ? (
              <span className="ml-auto text-xs text-muted-foreground">✓</span>
            ) : null}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
