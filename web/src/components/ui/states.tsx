import type { LucideIcon } from "lucide-react"
import { Inbox, RefreshCw, ServerCrash } from "lucide-react"
import type { ReactNode } from "react"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { cn } from "@/lib/utils"
import type { ApiError } from "@/types/api"

/**
 * État vide.
 *
 * Règle du projet : aucune donnée fictive, jamais de ligne de démonstration
 * pour « remplir » un tableau. Un écran vide doit donc expliquer *pourquoi*
 * il est vide et *quoi faire* — c'est ce qui distingue un produit sérieux
 * d'un produit qui semble cassé.
 */
export function EmptyState({
  icon: Icon = Inbox,
  title,
  description,
  action,
  className,
}: {
  icon?: LucideIcon
  title: string
  description: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-dashed border-border px-6 py-12 text-center",
        className,
      )}
    >
      <Icon className="size-7 text-muted-foreground" aria-hidden />
      <div className="space-y-1.5">
        <p className="font-medium">{title}</p>
        <div className="mx-auto max-w-md text-sm text-muted-foreground">{description}</div>
      </div>
      {action ? <div className="pt-1">{action}</div> : null}
    </div>
  )
}

/** Échec de chargement : on affiche le message réel du serveur, pas un générique. */
export function ErrorState({
  error,
  onRetry,
  className,
}: {
  error: ApiError
  onRetry?: () => void
  className?: string
}) {
  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-6 py-12 text-center",
        className,
      )}
    >
      <ServerCrash className="size-7 text-destructive" aria-hidden />
      <div className="space-y-1.5">
        <p className="font-medium">Chargement impossible</p>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">{error.message}</p>
      </div>
      {onRetry ? (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RefreshCw aria-hidden />
          Réessayer
        </Button>
      ) : null}
    </div>
  )
}

/** Squelette de tableau — même gabarit que le contenu réel, sans fausse donnée. */
export function TableSkeleton({ rows = 5, columns = 4 }: { rows?: number; columns?: number }) {
  return (
    <div className="space-y-2" aria-busy="true" aria-live="polite">
      <span className="sr-only">Chargement des données</span>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex gap-3">
          {Array.from({ length: columns }).map((__, columnIndex) => (
            <Skeleton
              key={columnIndex}
              className={cn("h-9 flex-1", columnIndex === 0 && "max-w-[34%]")}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
