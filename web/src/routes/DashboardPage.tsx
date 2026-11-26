import { Briefcase, Plug } from "lucide-react"
import { Link } from "react-router-dom"

import { toApiError } from "@/api/client"
import type { AppContext } from "@/api/context"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { useAppContext } from "@/hooks/useAppContext"
import { formatMoney } from "@/lib/utils"

export default function DashboardPage() {
  const { data, isPending, isError, error, refetch } = useAppContext()

  if (isPending) return <TableSkeleton rows={3} columns={3} />
  if (isError) return <ErrorState error={toApiError(error)} onRetry={() => void refetch()} />

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold tracking-tight">Tableau de bord</h1>
        <TradingModeBadge context={data} />
      </header>

      {/* La condition porte AUSSI sur le mode configuré.
          `live_blocked_reason` ne décrit que ce qui empêcherait une
          exécution réelle — côté serveur il est renseigné dès que le KYC
          n'est pas approuvé, mode demandé ou non. Sur le seul motif, un
          utilisateur dont tous les comptes sont en simulation s'entendait
          dire que ses comptes « sont configurés en mode réel ». Le mobile
          posait déjà la bonne condition (`isLiveDowngraded`). */}
      {data.live_blocked_reason && data.configured_trading_mode === "LIVE" ? (
        <Alert variant="warning" title="Mode réel demandé, mais inactif">
          Tes comptes broker sont configurés en mode réel.{" "}
          {data.live_blocked_reason === "KYC_REQUIRED"
            ? "Tant que ton identité n'est pas validée, le serveur refusera toute exécution réelle : la plateforme fonctionne en simulation."
            : "Un contrôle serveur empêche l'exécution réelle : la plateforme fonctionne en simulation."}
        </Alert>
      ) : null}

      {!data.trading_enabled ? (
        <Alert variant="danger" title="Trading suspendu sur la plateforme">
          L'ouverture de nouvelles positions est désactivée pour l'ensemble des
          comptes. Les positions existantes restent visibles et peuvent être
          clôturées.
        </Alert>
      ) : null}

      {data.portfolio ? (
        <PortfolioSummary portfolio={data.portfolio} />
      ) : (
        <EmptyState
          icon={Plug}
          title="Aucun portefeuille configuré"
          description={
            <>
              Un portefeuille est rattaché à un compte broker. Connectez d'abord
              un broker — en mode simulation si vous découvrez la plateforme —
              puis créez le portefeuille qui lui correspond.
            </>
          }
          action={
            <Button asChild size="sm">
              <Link to="/brokers">Connecter un broker</Link>
            </Button>
          }
        />
      )}

      {data.wallet ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-sm font-medium text-muted-foreground">
              Portefeuille électronique
            </CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-8">
            <Metric
              label="Disponible"
              value={formatMoney(data.wallet.available_balance, data.wallet.currency)}
            />
            <Metric
              label="Verrouillé"
              value={formatMoney(data.wallet.locked_balance, data.wallet.currency)}
              hint="Fonds engagés dans un retrait en cours."
            />
          </CardContent>
        </Card>
      ) : null}
    </div>
  )
}

function PortfolioSummary({
  portfolio,
}: {
  portfolio: NonNullable<ReturnType<typeof useAppContext>["data"]>["portfolio"]
}) {
  if (!portfolio) return null
  const currency = portfolio.base_currency

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
        <CardTitle className="flex items-center gap-2 text-sm font-medium">
          <Briefcase className="size-4 text-muted-foreground" aria-hidden />
          {portfolio.name}
        </CardTitle>
        {portfolio.broker_account ? (
          <Badge variant="outline">
            {portfolio.broker_account.broker} · {portfolio.broker_account.name}
          </Badge>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-wrap gap-8">
        <Metric label="Valeur" value={formatMoney(portfolio.current_balance, currency)} />
        <Metric label="Liquidités" value={formatMoney(portfolio.available_cash, currency)} />
        <Metric
          label="Immobilisé"
          value={formatMoney(portfolio.locked_cash, currency)}
          hint="Réservé par des ordres en attente."
        />
      </CardContent>
      {!portfolio.is_active ? (
        <CardContent className="pt-0">
          <Alert variant="warning" title="Portefeuille inactif">
            Aucun ordre ne peut être transmis depuis ce portefeuille.
          </Alert>
        </CardContent>
      ) : null}
    </Card>
  )
}

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="space-y-1">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="tabular text-xl font-semibold">{value}</p>
      {hint ? <p className="max-w-[22ch] text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

/** Écran provisoire pour les sections dont l'API n'est pas encore exposée. */
/**
 * Pastille de mode.
 *
 * Affiche le mode EFFECTIF, celui qui décrit ce qui se produira. Quand il
 * diffère du mode configuré, la pastille le dit au lieu de laisser croire
 * que la configuration a été ignorée sans raison.
 */
function TradingModeBadge({ context }: { context: AppContext }) {
  const isLive = context.trading_mode === "LIVE"
  const downgraded = !isLive && context.configured_trading_mode === "LIVE"

  return (
    <Badge variant={isLive ? "loss" : downgraded ? "warning" : "info"}>
      Mode {isLive ? "réel" : "simulation"}
      {downgraded ? " — réel bloqué" : ""}
    </Badge>
  )
}
