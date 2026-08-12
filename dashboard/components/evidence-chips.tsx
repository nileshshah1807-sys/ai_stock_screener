import {
  AlertTriangle,
  Check,
  CircleSlash,
  Lock,
  Minus,
  MessageSquare,
  ShieldAlert,
} from "lucide-react";

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/**
 * Compact evidence indicators for the grid.
 *
 * Each chip distinguishes three states the model treats differently and which
 * a naive UI would collapse into two:
 *
 *   present and applied  /  present but not eligible  /  absent
 *
 * The middle state matters most. A prior-cycle transcript or an unsupported
 * DCF is visible evidence that deliberately carries no score effect, and
 * showing it as either "good" or "missing" would misreport the model.
 */

type ChipTone = "neutral" | "applied" | "inert" | "warn" | "alert";

const TONES: Record<ChipTone, string> = {
  neutral: "text-muted-foreground/70",
  applied: "text-positive",
  inert: "text-muted-foreground/50",
  warn: "text-caution",
  alert: "text-negative",
};

function Chip({
  icon: Icon,
  tone,
  label,
  detail,
}: {
  icon: typeof Check;
  tone: ChipTone;
  label: string;
  detail: string;
}) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span
            className={cn("inline-flex cursor-help items-center", TONES[tone])}
            aria-label={`${label}: ${detail}`}
          />
        }
      >
        <Icon className="size-3.5" aria-hidden />
      </TooltipTrigger>
      <TooltipContent side="top" className="max-w-72">
        <p className="font-medium">{label}</p>
        <p className="text-xs opacity-90">{detail}</p>
      </TooltipContent>
    </Tooltip>
  );
}

export function TranscriptChip({
  status,
  eligible,
  guidance,
}: {
  status: string | null;
  eligible: boolean | null;
  guidance: string | null;
}) {
  if (!status || status === "No transcript") {
    return (
      <Chip
        icon={Minus}
        tone="neutral"
        label="No transcript"
        detail="No earnings call on file. Companies are not required to hold one, so this is neutral evidence and does not cap the rating."
      />
    );
  }
  if (!eligible) {
    return (
      <Chip
        icon={CircleSlash}
        tone="inert"
        label="Transcript not scoring-eligible"
        detail={`${status}. Retained for context; a prior-cycle or expired call has no score, rating, or rank effect.`}
      />
    );
  }
  return (
    <Chip
      icon={MessageSquare}
      tone="applied"
      label="Transcript applied"
      detail={`${status}. ${guidance ?? "No explicit guidance"}. Downside-only in v4: it can reduce conviction but never raise it.`}
    />
  );
}

export function RedFlagChip({
  status,
  severity,
  wouldChange,
}: {
  status: string | null;
  severity: number | null;
  wouldChange: boolean | null;
}) {
  if (!status || status === "No coverage" || status === "Not enabled") {
    return (
      <Chip
        icon={Minus}
        tone="neutral"
        label="No red-flag coverage"
        detail="This symbol is not in the VIGIL feed. Absence of coverage is not evidence of a clean issuer."
      />
    );
  }
  if (!severity) {
    return (
      <Chip
        icon={Check}
        tone="applied"
        label="No observed red flags"
        detail={`${status}. No credit, pledge, encumbrance, or surveillance events in the cached snapshot.`}
      />
    );
  }
  return (
    <Chip
      icon={severity >= 3 ? ShieldAlert : AlertTriangle}
      tone={severity >= 3 ? "alert" : "warn"}
      label={`Red flag severity ${severity}`}
      detail={`${status}. Shadow mode: the live score and rating are unchanged.${
        wouldChange
          ? " If the underlying filing were confirmed, the rating would be capped."
          : ""
      }`}
    />
  );
}

export function CappedChip({
  capped,
  reason,
}: {
  capped: boolean | null;
  reason: string | null;
}) {
  if (!capped) return null;
  return (
    <Chip
      icon={Lock}
      tone="warn"
      label="Rating capped"
      detail={reason || "A policy ceiling limits this rating below its score."}
    />
  );
}

/**
 * Fundamental and technical coverage, each against the minimum it is judged by.
 *
 * Coverage is a gate, not a nice-to-have: below the configured BUY minimum
 * (55% fundamental, 75% technical) the decision is capped under BUY regardless
 * of score. Each share is therefore coloured against its own threshold, since
 * the two are different numbers.
 */
const BUY_MIN_FUNDAMENTAL_COVERAGE = 0.55;
const BUY_MIN_TECHNICAL_COVERAGE = 0.75;

function share(value: number | null): string {
  if (value === null || value === undefined) return "—";
  return `${Math.round(value * 100)}%`;
}

export function CoverageCell({
  fundamental,
  technical,
}: {
  fundamental: number | null;
  technical: number | null;
}) {
  const fundamentalShort =
    fundamental !== null && fundamental < BUY_MIN_FUNDAMENTAL_COVERAGE;
  const technicalShort =
    technical !== null && technical < BUY_MIN_TECHNICAL_COVERAGE;

  return (
    <Tooltip>
      <TooltipTrigger render={<span className="tabular cursor-help text-xs" />}>
        <span className={fundamentalShort ? "text-caution" : "text-foreground"}>
          {share(fundamental)}
        </span>
        <span className="text-muted-foreground/60"> / </span>
        <span className={technicalShort ? "text-caution" : "text-foreground"}>
          {share(technical)}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-72">
        <p className="font-medium">Evidence coverage</p>
        <p className="text-xs opacity-90">
          Fundamental {share(fundamental)} of the fields the selected sector
          model expects; technical {share(technical)} of its components.
        </p>
        <p className="mt-1 text-xs opacity-90">
          BUY needs 55% / 75%, STRONG BUY 75% / 90%. Missing coverage is a gate
          failure, not neutral evidence.
        </p>
      </TooltipContent>
    </Tooltip>
  );
}
