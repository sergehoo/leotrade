import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Briefcase, Plus, RefreshCw, Star, TrendingDown, TrendingUp } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { toApiError } from "@/api/client"
import {
  fetchPortfolioSummary,
  listPortfolios,
  listPositions,
  provisionPaperPortfolio,
  refreshPortfolio,
  setDefaultPortfolio,
  type Portfolio,
  type PortfolioSummary,
  type Position,
} from "@/api/portfolio"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Spinner } from "@/components/ui/spinner"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { formatMoney, formatPercent, formatQuantity, signClass, signOf } from "@/lib/money"
import { cn } from "@/lib/utils"

const PORTFOLIOS_KEY = ["portfolios"] as const

export default function PortfolioPage() {
  const queryClient = useQueryClient()
  const [selectedId, setSelectedId] = useState<number | null>(null)

  const portfolios = useQuery({ queryKey: PORTFOLIOS_KEY, queryFn: listPortfolios })

  const list = portfolios.data?.results ?? []
  const active = list.find((p) => p.id === selectedId) ?? list.find((p) => p.is_default) ?? list[0]

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: PORTFOLIOS_KEY })
    void queryClient.invalidateQueries({ queryKey: ["portfolio-summary"] })
    void queryClient.invalidateQueries({ queryKey: ["positions"] })
    void queryClient.invalidateQueries({ queryKey: ["app-context"] })
  }

  const provision = useMutation({
    mutationFn: () => provisionPaperPortfolio(),
    onSuccess: (portfolio) => {
      invalidate()
      setSelectedId(portfolio.id)
      toast.success(`« ${portfolio.name} » créé avec son capital de départ.`)
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  const refresh = useMutation({
    mutationFn: refreshPortfolio,
    onSuccess: () => {
      invalidate()
      toast.success("Valorisation recalculée.")
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  const promote = useMutation({
    mutationFn: setDefaultPortfolio,
    onSuccess: () => {
      invalidate()
      toast.success("Portefeuille par défaut mis à jour.")
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  if (portfolios.isPending) return <TableSkeleton rows={4} columns={4} />
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
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold tracking-tight">Portefeuille</h1>
          <p className="text-sm text-muted-foreground">
            Valorisation, positions ouvertes et performance.
          </p>
        </div>
        {active ? (
          <div className="flex flex-wrap gap-1.5">
            {!active.is_default ? (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => promote.mutate(active.id)}
                disabled={promote.isPending}
              >
                <Star aria-hidden />
                Par défaut
              </Button>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              onClick={() => refresh.mutate(active.id)}
              disabled={refresh.isPending}
            >
              {refresh.isPending ? <Spinner /> : <RefreshCw aria-hidden />}
              Recalculer
            </Button>
          </div>
        ) : null}
      </header>

      {list.length === 0 ? (
        <EmptyState
          icon={Briefcase}
          title="Aucun portefeuille"
          description={
            <>
              Un portefeuille de simulation te permet d'utiliser toute la
              plateforme sans ouvrir de compte chez un courtier. Aucun ordre
              n'atteindra un marché réel.
            </>
          }
          action={
            <Button onClick={() => provision.mutate()} disabled={provision.isPending}>
              {provision.isPending ? <Spinner /> : <Plus aria-hidden />}
              Créer un portefeuille de simulation
            </Button>
          }
        />
      ) : (
        <>
          {list.length > 1 ? (
            <PortfolioSwitcher
              portfolios={list}
              activeId={active?.id ?? null}
              onSelect={setSelectedId}
            />
          ) : null}

          {active ? <PortfolioDetail portfolio={active} /> : null}

          <div>
            <Button
              variant="outline"
              size="sm"
              onClick={() => provision.mutate()}
              disabled={provision.isPending}
            >
              {provision.isPending ? <Spinner /> : <Plus aria-hidden />}
              Nouveau portefeuille de simulation
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

function PortfolioSwitcher({
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
      {portfolios.map((portfolio) => {
        const isActive = portfolio.id === activeId
        return (
          <button
            key={portfolio.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            onClick={() => onSelect(portfolio.id)}
            className={cn(
              "flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm transition-colors",
              isActive
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "border-border text-muted-foreground hover:bg-accent hover:text-accent-foreground",
            )}
          >
            <span className="truncate">{portfolio.name}</span>
            <ModeBadge portfolio={portfolio} />
          </button>
        )
      })}
    </div>
  )
}

/**
 * Le mode d'un portefeuille décide si un ordre engage de l'argent réel.
 * Il doit être lisible partout où un portefeuille est nommé, pas seulement
 * sur un écran de configuration.
 */
function ModeBadge({ portfolio }: { portfolio: Portfolio }) {
  if (!portfolio.is_simulated) {
    return <Badge variant="loss">Réel</Badge>
  }
  return <Badge variant="outline">Simulation</Badge>
}

function PortfolioDetail({ portfolio }: { portfolio: Portfolio }) {
  const summary = useQuery({
    queryKey: ["portfolio-summary", portfolio.id],
    queryFn: () => fetchPortfolioSummary(portfolio.id),
  })

  const positions = useQuery({
    queryKey: ["positions", portfolio.id],
    queryFn: () => listPositions({ portfolio: portfolio.id, status: "OPEN" }),
  })

  return (
    <div className="space-y-4">
      {!portfolio.is_simulated ? (
        <Alert variant="warning" title="Portefeuille réel">
          Les ordres passés depuis ce portefeuille atteignent le marché et
          engagent de l'argent réel.
        </Alert>
      ) : null}

      {summary.isPending ? (
        <TableSkeleton rows={2} columns={4} />
      ) : summary.isError ? (
        <ErrorState
          error={toApiError(summary.error)}
          onRetry={() => void summary.refetch()}
        />
      ) : (
        <SummaryGrid summary={summary.data} />
      )}

      <section className="space-y-2">
        <h2 className="text-sm font-medium">Positions ouvertes</h2>
        {positions.isPending ? (
          <TableSkeleton rows={3} columns={5} />
        ) : positions.isError ? (
          <ErrorState
            error={toApiError(positions.error)}
            onRetry={() => void positions.refetch()}
          />
        ) : positions.data.results.length === 0 ? (
          <EmptyState
            icon={Briefcase}
            title="Aucune position ouverte"
            description={
              <>
                Les positions apparaîtront ici dès qu'un ordre sera exécuté sur
                ce portefeuille.
              </>
            }
          />
        ) : (
          <PositionsTable
            positions={positions.data.results}
            currency={portfolio.base_currency}
          />
        )}
      </section>
    </div>
  )
}

function SummaryGrid({ summary }: { summary: PortfolioSummary }) {
  const currency = summary.base_currency
  const pnlSign = signOf(summary.total_pnl)

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric label="Valorisation" value={formatMoney(summary.equity, currency)} />
      <Metric
        label="Résultat total"
        value={formatMoney(summary.total_pnl, currency)}
        hint={formatPercent(summary.total_pnl_percent)}
        className={signClass(pnlSign)}
        icon={pnlSign === "gain" ? TrendingUp : pnlSign === "loss" ? TrendingDown : undefined}
      />
      <Metric
        label="Latent"
        value={formatMoney(summary.unrealized_pnl, currency)}
        className={signClass(signOf(summary.unrealized_pnl))}
      />
      <Metric
        label="Réalisé"
        value={formatMoney(summary.realized_pnl, currency)}
        className={signClass(signOf(summary.realized_pnl))}
      />

      <Metric label="Liquidités" value={formatMoney(summary.available_cash, currency)} />
      <Metric
        label="Immobilisé"
        value={formatMoney(summary.locked_cash, currency)}
        hint="Engagé sur des ordres en cours"
      />
      <Metric
        label="Exposition"
        value={formatMoney(summary.exposure_value, currency)}
        hint={formatPercent(summary.exposure_percent)}
      />
      <Metric
        label="Positions"
        value={String(summary.open_positions)}
        hint={
          summary.open_positions > 0
            ? `${summary.long_positions} long · ${summary.short_positions} short`
            : undefined
        }
      />
    </div>
  )
}

function Metric({
  label,
  value,
  hint,
  className,
  icon: Icon,
}: {
  label: string
  value: string
  hint?: string
  className?: string
  icon?: typeof TrendingUp
}) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={cn("flex items-center gap-1.5 text-lg font-semibold tabular", className)}>
          {Icon ? <Icon className="size-4" aria-hidden /> : null}
          {value}
        </p>
        {hint ? <p className="text-xs text-muted-foreground tabular">{hint}</p> : null}
      </CardContent>
    </Card>
  )
}

function PositionsTable({
  positions,
  currency,
}: {
  positions: Position[]
  currency: string
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[46rem] text-sm">
        <thead className="border-b border-border bg-secondary/40 text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Instrument</th>
            <th scope="col" className="px-3 py-2 font-medium">Sens</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Quantité</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Entrée</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Cours</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Exposition</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Latent</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {positions.map((position) => {
            const sign = signOf(position.unrealized_pnl)
            return (
              <tr key={position.id} className="hover:bg-accent/40">
                <td className="px-3 py-2">
                  <span className="font-medium">{position.symbol}</span>
                  {position.asset_name ? (
                    <span className="block text-xs text-muted-foreground">
                      {position.asset_name}
                    </span>
                  ) : null}
                </td>
                <td className="px-3 py-2">
                  <Badge variant={position.side === "LONG" ? "info" : "warning"}>
                    {position.side === "LONG" ? "Long" : "Short"}
                  </Badge>
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatQuantity(position.quantity)}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatMoney(position.average_entry_price, currency)}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatMoney(position.current_price, currency)}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatMoney(position.exposure_value, currency)}
                </td>
                <td className={cn("px-3 py-2 text-right tabular font-medium", signClass(sign))}>
                  {formatMoney(position.unrealized_pnl, currency)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
