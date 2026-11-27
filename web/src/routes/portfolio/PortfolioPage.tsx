import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  Briefcase,
  CloudOff,
  Link2,
  Plus,
  RefreshCw,
  Star,
  TrendingDown,
  TrendingUp,
  Zap,
} from "lucide-react"
import { useEffect, useState } from "react"
import { toast } from "sonner"

import { toApiError } from "@/api/client"
import {
  fetchEquityCurve,
  fetchPortfolioSummary,
  listPortfolios,
  listPositions,
  provisionPaperPortfolio,
  refreshPortfolio,
  setDefaultPortfolio,
  type EquityCurve,
  type Portfolio,
  type PortfolioSummary,
  type Position,
} from "@/api/portfolio"
import { EquityChart } from "@/components/charts/EquityChart"
import {
  usePortfolioRealtime,
  type LiveMetrics,
  type LivePosition,
  type PortfolioLive,
} from "@/hooks/usePortfolioRealtime"
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

  // Le canal `ws/portfolio/<id>/` existait côté serveur depuis
  // l'origine, avec ses émetteurs — passage d'un ordre, recalcul des
  // métriques, mark-to-market périodique. Aucun client ne s'y
  // connectait.
  const live = usePortfolioRealtime(portfolio.id)

  return (
    <div className="space-y-4">
      {!portfolio.is_simulated ? (
        <Alert variant="warning" title="Portefeuille réel">
          Les ordres passés depuis ce portefeuille atteignent le marché et
          engagent de l'argent réel.
        </Alert>
      ) : null}

      <LiveBadge live={live} />

      {summary.isPending ? (
        <TableSkeleton rows={2} columns={4} />
      ) : summary.isError ? (
        <ErrorState
          error={toApiError(summary.error)}
          onRetry={() => void summary.refetch()}
        />
      ) : (
        <SummaryGrid summary={summary.data} live={live.metrics} />
      )}

      <EquityCurveSection portfolioId={portfolio.id} />

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
            live={live.positions}
          />
        )}
      </section>
    </div>
  )
}

function SummaryGrid({
  summary,
  live,
}: {
  summary: PortfolioSummary
  live: LiveMetrics | null
}) {
  const currency = summary.base_currency
  const pnlSign = signOf(summary.total_pnl)

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Metric label="Valorisation" value={formatMoney(live?.equity ?? summary.equity, currency)} />
      <Metric
        label="Résultat total"
        value={formatMoney(summary.total_pnl, currency)}
        hint={formatPercent(summary.total_pnl_percent)}
        className={signClass(pnlSign)}
        icon={pnlSign === "gain" ? TrendingUp : pnlSign === "loss" ? TrendingDown : undefined}
      />
      <Metric
        label="Latent"
        value={formatMoney(live?.unrealized_pnl ?? summary.unrealized_pnl, currency)}
        className={signClass(signOf(live?.unrealized_pnl ?? summary.unrealized_pnl))}
      />
      <Metric
        label="Réalisé"
        value={formatMoney(summary.realized_pnl, currency)}
        className={signClass(signOf(summary.realized_pnl))}
      />

      <Metric label="Liquidités" value={formatMoney(live?.available_cash ?? summary.available_cash, currency)} />
      <Metric
        label="Immobilisé"
        value={formatMoney(live?.locked_cash ?? summary.locked_cash, currency)}
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
  live,
}: {
  positions: Position[]
  currency: string
  live: Record<number, LivePosition>
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
            // Un correctif ne remplace QUE les champs réellement reçus :
            // un champ absent garde la valeur chargée en REST, plutôt
            // que d'être écrasé par un zéro qui passerait pour une
            // mesure.
            const patch = live[position.id]
            const quantity = patch?.quantity ?? position.quantity
            const mark = patch?.mark_price ?? position.current_price
            const unrealized = patch?.unrealized_pnl ?? position.unrealized_pnl
            const sign = signOf(unrealized)
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
                  {formatQuantity(quantity)}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatMoney(position.average_entry_price, currency)}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatMoney(mark, currency)}
                </td>
                <td className="px-3 py-2 text-right tabular">
                  {formatMoney(position.exposure_value, currency)}
                </td>
                <td className={cn("px-3 py-2 text-right tabular font-medium", signClass(sign))}>
                  {formatMoney(unrealized, currency)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}


/**
 * Courbe de valorisation.
 *
 * Elle n'est tracée que si le serveur juge la série suffisante. Relier
 * cinq instantanés espacés de six semaines produit une ligne continue
 * qui raconte une trajectoire jamais mesurée : l'œil lit une tendance là
 * où il n'y a que des îlots. Quand le refus tombe, on montre les points
 * eux-mêmes, et on dit pourquoi on ne les relie pas.
 */
function EquityCurveSection({ portfolioId }: { portfolioId: number }) {
  const curve = useQuery({
    queryKey: ["equity-curve", portfolioId],
    queryFn: () => fetchEquityCurve(portfolioId),
  })

  if (curve.isPending) return <TableSkeleton rows={3} columns={1} />
  if (curve.isError) {
    return <ErrorState error={toApiError(curve.error)} onRetry={() => void curve.refetch()} />
  }

  const data = curve.data

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Valorisation dans le temps</h2>
      <Card>
        <CardContent className="space-y-3 p-4">
          {data.is_plottable ? (
            <>
              {/* Traçable n'est pas récent : une série régulière mais
                  arrêtée il y a six mois décrit un état révolu, et rien
                  dans le dessin ne le dit. */}
              {data.is_stale ? (
                <Alert variant="warning" title="Cette courbe ne décrit plus ton portefeuille">
                  La dernière mesure date du{" "}
                  {data.last_at ? new Date(data.last_at).toLocaleString("fr-FR") : "—"}.
                  Ce qui s'est passé depuis n'apparaît nulle part sur ce
                  graphique.
                </Alert>
              ) : null}
              <EquityChart points={data.points} />
              <p className="text-xs text-muted-foreground tabular">
                {data.point_count} mesures · dernière le{" "}
                {data.last_at ? new Date(data.last_at).toLocaleString("fr-FR") : "—"}
              </p>
              {/* Le graphique est aria-hidden : sans cette alternative, un
                  lecteur d'écran ne restituerait rien du tout. */}
              <p className="sr-only">
                Courbe de valorisation : {data.point_count} mesures, de{" "}
                {data.points[0]
                  ? formatMoney(data.points[0].equity, data.base_currency)
                  : "—"}{" "}
                à{" "}
                {data.points[data.points.length - 1]
                  ? formatMoney(
                      data.points[data.points.length - 1].equity,
                      data.base_currency,
                    )
                  : "—"}
                .
              </p>
            </>
          ) : (
            <NotPlottable curve={data} />
          )}
        </CardContent>
      </Card>
    </section>
  )
}

function NotPlottable({ curve }: { curve: EquityCurve }) {
  const tooFew = curve.not_plottable_reasons.includes("TOO_FEW_POINTS")
  const gaps = curve.not_plottable_reasons.includes("GAPS_TOO_WIDE")
  const interrupted = curve.not_plottable_reasons.includes("INTERRUPTED")

  return (
    <div className="space-y-3">
      <Alert variant="info" title="Pas encore de courbe">
        {tooFew ? (
          <>
            {curve.point_count} mesure{curve.point_count > 1 ? "s" : ""} enregistrée
            {curve.point_count > 1 ? "s" : ""} sur les {curve.minimum_points}{" "}
            nécessaires. Une courbe tracée sur si peu de points relierait des
            îlots en une ligne continue, et donnerait à voir une trajectoire
            qui n'a pas été mesurée.
          </>
        ) : interrupted ? (
          <>
            La série comporte une interruption de{" "}
            {curve.max_gap_seconds
              ? Math.round(curve.max_gap_seconds / 86400)
              : "—"}{" "}
            jours. Sur un graphique, l'axe du temps est ordinal : ce trou
            serait dessiné à la largeur d'un point, et le segment qui
            l'enjambe aurait la même pente apparente que ses voisins.
          </>
        ) : gaps ? (
          <>
            Les mesures sont trop espacées (environ{" "}
            {curve.median_gap_seconds
              ? Math.round(curve.median_gap_seconds / 3600)
              : "—"}{" "}
            h entre deux). Les relier inventerait tout l'intervalle.
          </>
        ) : (
          <>La série n'est pas encore assez fournie pour être tracée.</>
        )}
      </Alert>

      {curve.points.length > 0 ? (
        <ul className="space-y-1 text-sm">
          {curve.points.slice(-6).map((point) => (
            <li
              key={point.at}
              className="flex items-center justify-between gap-3 border-b border-border pb-1 last:border-0"
            >
              <span className="text-xs text-muted-foreground tabular">
                {new Date(point.at).toLocaleString("fr-FR", {
                  day: "2-digit",
                  month: "2-digit",
                  year: "2-digit",
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
              <span className="tabular">
                {formatMoney(point.equity, curve.base_currency)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}


/**
 * État de la liaison temps réel, dit sans le farder.
 *
 * Une liaison ouverte qui ne reçoit rien ressemble, à l'écran, à une
 * liaison qui tient les prix à jour. Sur une plateforme de trading,
 * croire qu'un chiffre est courant alors qu'il date de l'ouverture de la
 * page est précisément l'erreur qu'on ne peut pas se permettre — d'où
 * deux mentions distinctes : « connecté » et « à jour ».
 */
function LiveBadge({ live }: { live: PortfolioLive }) {
  const [, tick] = useState(0)

  // Un âge qui ne vieillit pas est un âge faux : on repeint chaque
  // seconde tant qu'une mesure est arrivée.
  useEffect(() => {
    if (live.lastEventAt === null) return
    const timer = window.setInterval(() => tick((n) => n + 1), 1000)
    return () => window.clearInterval(timer)
  }, [live.lastEventAt])

  const { icon: Icon, tone, label } =
    live.status === "connecting"
      ? { icon: RefreshCw, tone: "text-muted-foreground", label: "Connexion au flux…" }
      : live.status === "lost"
        ? {
            icon: CloudOff,
            tone: "text-warning",
            label: "Flux interrompu — nouvelle tentative",
          }
        : live.lastEventAt === null
          ? {
              icon: Link2,
              tone: "text-muted-foreground",
              label: "Flux ouvert — aucune mise à jour reçue",
            }
          : {
              icon: Zap,
              tone: "text-gain",
              label: `À jour ${since(live.lastEventAt)}`,
            }

  return (
    <p className={cn("flex items-center gap-1.5 text-xs", tone)}>
      <Icon className="size-3.5" aria-hidden />
      {label}
    </p>
  )
}

function since(moment: number): string {
  const seconds = Math.floor((Date.now() - moment) / 1000)
  if (seconds < 5) return "à l'instant"
  if (seconds < 60) return `il y a ${seconds} s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `il y a ${minutes} min`
  return `il y a ${Math.floor(minutes / 60)} h`
}
