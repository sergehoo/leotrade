import { cva, type VariantProps } from "class-variance-authority"
import type * as React from "react"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        neutral: "border-border bg-secondary text-secondary-foreground",
        gain: "border-gain/30 bg-gain/10 text-gain",
        loss: "border-loss/30 bg-loss/10 text-loss",
        warning: "border-warning/30 bg-warning/10 text-warning",
        info: "border-info/30 bg-info/10 text-info",
        outline: "border-border text-muted-foreground",
        // Paliers d'instrument — cf. backend/risk/instruments.py
        core: "border-tier-core/30 bg-tier-core/10 text-tier-core",
        volatile: "border-tier-volatile/30 bg-tier-volatile/10 text-tier-volatile",
        speculative: "border-tier-speculative/30 bg-tier-speculative/10 text-tier-speculative",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
)

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> &
  VariantProps<typeof badgeVariants>

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />
}
