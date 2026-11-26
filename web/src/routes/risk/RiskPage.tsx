import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { OctagonAlert, RefreshCw, ShieldAlert, ShieldCheck } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { toApiError } from "@/api/client"
import { listPortfolios, type Portfolio } from "@/api/portfolio"
import {
  fetchRiskSummary,
  refreshRiskStates,
  resolveKillSwitch,
  updateRiskProfile,
  type RiskLimit,
  type RiskSummary,
} from "@/api/risk"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { Switch } from "@/components/ui/switch"
import { formatPercent } from "@/lib/money"
import { cn } from "@/lib/utils"

export default function RiskPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const portfolios = useQuery({ queryKey: ["portfolios"], queryFn: listPortfolios })
  const list = portfolios.data?.results ?? []
  const active = list.find((p) => p.id === selectedId) ?? list.find((p) => p.is_default) ?? list[0]

  if (portfolios.isPending) return <TableSkeleton rows={4} columns={3} />
  if (portfolios.isError) {
    return (
      <ErrorState
        error={toApiError(portfolios.error)}
        onRetry={() => void portfolios.refetch()}
      />
    )
  }

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold tracking-tight">Risque</h1>
        <p className="text-sm text-muted-foreground">
          Limites appliquées côté serveur avant chaque ordre. Les modifier ici
          change ce que le moteur autorise.
        </p>
      </header>

      {list.length === 0 ? (
        <EmptyState
          icon={ShieldAlert}
          title="Aucun portefeuille à surveiller"
          description={
            <>
              Le contrôle du risque s'applique à un portefeuille. Crées-en un
              depuis la section Portefeuille pour voir tes limites.
            </>
          }
        />
      ) : (
        <>
          {list.length > 1 ? (
            <PortfolioTabs
              portfolios={list}
              activeId={active?.id ?? null}
              onSelect={setSelectedId}
            />
          ) : null}
          {active ? (
            <RiskDetail portfolio={active} invalidate={() => {
              void queryClient.invalidateQueries({ queryKey: ["risk-summary"] })
            }} />
          ) : null}
        </>
      )}
    </div>
  )
}

function PortfolioTabs({
  portfolios,
  activeId,
  onSelect,
}: {
  portfolios: Portfolio[]
  activeId: number | null
  onSelect: (id: number) => void
}) {
  return (
    <div className="flex flex-wrap gap-2" role="tablist" aria-label="Portefeuilles">
      {portfolios.map((portfolio) => (
        <button
          key={portfolio.id}
          type="button"
          role="tab"
          aria-selected={portfolio.id === activeId}
          onClick={() => onSelect(portfolio.id)}
          className={cn(
            "rounded-md border px-3 py-1.5 text-sm transition-colors",
            portfolio.id === activeId
              ? "border-primary/40 bg-primary/10 text-foreground"
              : "border-border text-muted-foreground hover:bg-accent hover:text-accent-foreground",
          )}
        >
          {portfolio.name}
        </button>
      ))}
    </div>
  )
}

function RiskDetail({
  portfolio,
  invalidate,
}: {
  portfolio: Portfolio
  invalidate: () => void
}) {
  const queryClient = useQueryClient()
  const [confirmingResolve, setConfirmingResolve] = useState(false)

  const summary = useQuery({
    queryKey: ["risk-summary", portfolio.id],
    queryFn: () => fetchRiskSummary(portfolio.id),
  })

  function refetchAll() {
    void queryClient.invalidateQueries({ queryKey: ["risk-summary", portfolio.id] })
    invalidate()
  }

  const refresh = useMutation({
    mutationFn: () => refreshRiskStates(portfolio.id),
    onSuccess: () => {
      refetchAll()
      toast.success("États de risque recalculés.")
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  const resolve = useMutation({
    mutationFn: () => resolveKillSwitch(portfolio.id),
    onSuccess: (result) => {
      refetchAll()
      setConfirmingResolve(false)
      toast.success(
        result.resolved_count > 0
          ? "Arrêt d'urgence levé. L'ouverture de positions est de nouveau possible."
          : "Aucun arrêt d'urgence actif.",
      )
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  if (summary.isPending) return <TableSkeleton rows={3} columns={3} />
  if (summary.isError) {
    return (
      <ErrorState error={toApiError(summary.error)} onRetry={() => void summary.refetch()} />
    )
  }

  const data = summary.data

  return (
    <div className="space-y-4">
      {data.kill_switch_active ? (
        <Alert variant="danger" title="Arrêt d'urgence actif">
          <div className="space-y-3">
            <p>
              {data.kill_switch_reason ||
                "Une limite de risque a été franchie. Aucune nouvelle position ne peut être ouverte."}
            </p>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmingResolve(true)}
            >
              Lever l'arrêt d'urgence
            </Button>
          </div>
        </Alert>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3">
        <PreservationBadge profile={data.profile} />
        <Button
          variant="outline"
          size="sm"
          onClick={() => refresh.mutate()}
          disabled={refresh.isPending}
        >
          {refresh.isPending ? <Spinner /> : <RefreshCw aria-hidden />}
          Recalculer
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {data.limits.map((limit) => (
          <LimitCard key={limit.key} limit={limit} />
        ))}
        <PositionsCard summary={data} />
      </div>

      {data.profile ? (
        <PreservationPanel
          profile={data.profile}
          onSaved={refetchAll}
        />
      ) : null}

      <ResolveDialog
        open={confirmingResolve}
        pending={resolve.isPending}
        reason={data.kill_switch_reason}
        onCancel={() => setConfirmingResolve(false)}
        onConfirm={() => resolve.mutate()}
      />
    </div>
  )
}

/**
 * Jauge d'une limite.
 *
 * La couleur suit la consommation, pas la nature de la limite : à 90 %
 * d'une limite de perte, l'utilisateur doit voir du rouge même si rien
 * n'est encore bloqué.
 */
function LimitCard({ limit }: { limit: RiskLimit }) {
  const usage = limit.usage_percent === null ? null : Number(limit.usage_percent)
  const tone =
    usage === null ? "none" : usage >= 100 ? "breached" : usage >= 75 ? "warning" : "ok"

  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-xs text-muted-foreground">{limit.label}</p>
          {tone === "breached" ? (
            <Badge variant="loss">Dépassée</Badge>
          ) : tone === "warning" ? (
            <Badge variant="warning">Proche</Badge>
          ) : null}
        </div>

        <p className="text-lg font-semibold tabular">
          {formatPercent(limit.consumed_percent)}
          <span className="ml-1 text-sm font-normal text-muted-foreground">
            / {formatPercent(limit.limit_percent)}
          </span>
        </p>

        {usage === null ? (
          <p className="text-xs text-muted-foreground">
            Aucune limite définie — rien ne sera bloqué.
          </p>
        ) : (
          <>
            <div
              className="h-1.5 w-full overflow-hidden rounded-full bg-secondary"
              role="progressbar"
              aria-valuenow={Math.min(usage, 100)}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${limit.label} : ${limit.usage_percent} % de la limite`}
            >
              <div
                className={cn(
                  "h-full rounded-full transition-[width]",
                  tone === "breached" ? "bg-loss" : tone === "warning" ? "bg-warning" : "bg-gain",
                )}
                style={{ width: `${Math.min(usage, 100)}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground tabular">
              {formatPercent(limit.usage_percent)} de la limite
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function PositionsCard({ summary }: { summary: RiskSummary }) {
  const max = summary.max_open_positions
  return (
    <Card>
      <CardContent className="space-y-2 p-4">
        <p className="text-xs text-muted-foreground">Positions ouvertes</p>
        <p className="text-lg font-semibold tabular">
          {summary.open_positions}
          {max > 0 ? (
            <span className="ml-1 text-sm font-normal text-muted-foreground">/ {max}</span>
          ) : null}
        </p>
        <p className="text-xs text-muted-foreground">
          {max > 0
            ? `${Math.max(max - summary.open_positions, 0)} encore ouvrable(s)`
            : "Aucun plafond défini"}
        </p>
      </CardContent>
    </Card>
  )
}

function PreservationBadge({ profile }: { profile: RiskSummary["profile"] }) {
  if (!profile) return null
  if (profile.preservation_mode) {
    return (
      <Badge variant="gain">
        <ShieldCheck className="size-3" aria-hidden />
        Préservation du capital active
      </Badge>
    )
  }
  return (
    <Badge variant="warning">
      <ShieldAlert className="size-3" aria-hidden />
      Préservation désactivée
    </Badge>
  )
}

/**
 * Pilotage de la politique de préservation.
 *
 * Ces trois drapeaux décident de l'univers d'instruments autorisé. Ils
 * n'étaient pas exposés par l'API : la principale protection du capital
 * était invisible et non modifiable depuis l'interface.
 */
function PreservationPanel({
  profile,
  onSaved,
}: {
  profile: NonNullable<RiskSummary["profile"]>
  onSaved: () => void
}) {
  const save = useMutation({
    mutationFn: (payload: Record<string, boolean>) =>
      updateRiskProfile(profile.id, payload),
    onSuccess: () => {
      onSaved()
      toast.success("Politique de préservation mise à jour.")
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  return (
    <Card>
      <CardContent className="space-y-4 p-4">
        <div className="space-y-1">
          <h2 className="text-sm font-medium">Préservation du capital</h2>
          <p className="text-xs text-muted-foreground">
            Profil « {profile.name} ». Ces réglages sont appliqués par le
            serveur avant chaque ordre, pas seulement affichés ici.
          </p>
        </div>

        <PolicyRow
          id="preservation-mode"
          label="Mode préservation"
          description="Restreint l'univers aux instruments dont l'espérance n'est pas structurellement négative."
          checked={profile.preservation_mode}
          disabled={save.isPending}
          onChange={(checked) => save.mutate({ preservation_mode: checked })}
        />
        <PolicyRow
          id="allow-volatile"
          label="Instruments à volatilité élevée"
          description="Crypto, FX exotique, matières premières."
          checked={profile.allow_volatile_instruments}
          disabled={save.isPending}
          onChange={(checked) => save.mutate({ allow_volatile_instruments: checked })}
        />
        <PolicyRow
          id="allow-speculative"
          label="Instruments à espérance négative"
          description="Synthétiques Deriv et assimilés. Sur la durée, ces instruments perdent par construction."
          checked={profile.allow_speculative_instruments}
          disabled={save.isPending}
          onChange={(checked) => save.mutate({ allow_speculative_instruments: checked })}
          danger
        />
      </CardContent>
    </Card>
  )
}

function PolicyRow({
  id,
  label,
  description,
  checked,
  disabled,
  onChange,
  danger,
}: {
  id: string
  label: string
  description: string
  checked: boolean
  disabled: boolean
  onChange: (checked: boolean) => void
  danger?: boolean
}) {
  return (
    <div
      className={cn(
        "flex items-start justify-between gap-4 rounded-md border p-3",
        danger && checked ? "border-warning/40 bg-warning/5" : "border-border",
      )}
    >
      <div className="space-y-0.5">
        <Label htmlFor={id} className="cursor-pointer">
          {label}
        </Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch id={id} checked={checked} disabled={disabled} onCheckedChange={onChange} />
    </div>
  )
}

/**
 * Lever un arrêt d'urgence rouvre l'exécution. Une confirmation explicite
 * est le minimum : le déclencheur n'a pas disparu parce qu'on ferme la
 * bannière.
 */
function ResolveDialog({
  open,
  pending,
  reason,
  onCancel,
  onConfirm,
}: {
  open: boolean
  pending: boolean
  reason: string
  onCancel: () => void
  onConfirm: () => void
}) {
  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onCancel())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Lever l'arrêt d'urgence ?</DialogTitle>
          <DialogDescription>
            L'ouverture de nouvelles positions redeviendra possible
            immédiatement.
          </DialogDescription>
        </DialogHeader>

        <Alert variant="warning" title="Motif du déclenchement">
          {reason || "Une limite de risque a été franchie."}
          <p className="mt-2">
            La cause ne disparaît pas en levant l'arrêt. S'il s'est déclenché
            sur une limite de perte, celle-ci reste consommée.
          </p>
        </Alert>

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Annuler
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={pending}>
            {pending ? <Spinner /> : <OctagonAlert aria-hidden />}
            Lever l'arrêt
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
