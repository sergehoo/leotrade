import { cva, type VariantProps } from "class-variance-authority"
import { AlertTriangle, CircleAlert, Info, ShieldCheck } from "lucide-react"
import * as React from "react"

import { cn } from "@/lib/utils"

const alertVariants = cva(
  "relative flex w-full gap-3 rounded-lg border p-4 text-sm",
  {
    variants: {
      variant: {
        info: "border-info/30 bg-info/10 text-foreground",
        warning: "border-warning/35 bg-warning/10 text-foreground",
        danger: "border-destructive/40 bg-destructive/10 text-foreground",
        success: "border-gain/30 bg-gain/10 text-foreground",
      },
    },
    defaultVariants: { variant: "info" },
  },
)

const ICONS = {
  info: Info,
  warning: AlertTriangle,
  danger: CircleAlert,
  success: ShieldCheck,
} as const

export interface AlertProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "title">,
    VariantProps<typeof alertVariants> {
  /** `title` natif est une chaîne ; ici on accepte du contenu riche. */
  title?: React.ReactNode
}

export function Alert({ className, variant = "info", title, children, ...props }: AlertProps) {
  const Icon = ICONS[variant ?? "info"]
  const iconColor = {
    info: "text-info",
    warning: "text-warning",
    danger: "text-destructive",
    success: "text-gain",
  }[variant ?? "info"]

  return (
    <div
      role={variant === "danger" ? "alert" : "status"}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    >
      <Icon className={cn("mt-0.5 size-4 shrink-0", iconColor)} aria-hidden />
      <div className="min-w-0 flex-1 space-y-1">
        {title ? <p className="font-medium leading-snug">{title}</p> : null}
        {children ? <div className="text-muted-foreground">{children}</div> : null}
      </div>
    </div>
  )
}
