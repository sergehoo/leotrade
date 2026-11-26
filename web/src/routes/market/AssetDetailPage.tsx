import { useQuery } from "@tanstack/react-query"
import { AlertTriangle, ArrowLeft, LineChart } from "lucide-react"
import { useState } from "react"
import { Link, useParams } from "react-router-dom"

import { toApiError } from "@/api/client"
import { fetchCandles, fetchQuote, formatAge, type Freshness } from "@/api/market"
import { CandleChart } from "@/components/charts/CandleChart"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { formatPercent, signClass, signOf } from "@/lib/money"

const TIMEFRAMES = ["1h", "4h", "1d", "1w"]

const FRESHNESS_VARIANT: Record<Freshness, "gain" | "warning" | "loss" | "outline"> = {
  LIVE: "gain",
  DELAYED: "warning",
  STALE: "loss",
  NO_DATA: "outline",
}

export default function AssetDetailPage() {
  const params = useParams()
  const assetId = Number(params.id)
  const [timeframe, setTimeframe] = useState("1d")

  const quote = useQuery({
    queryKey: ["asset-quote", assetId, timeframe],
    queryFn: () => fetchQuote(assetId, timeframe),
    enabled: Number.isFinite(assetId),
  })

  const history = useQuery({
    queryKey: ["asset-candles", assetId, timeframe],
    queryFn: () => fetchCandles(assetId, { timeframe, limit: 300 }),
    enabled: Number.isFinite(assetId),
  })

  if (!Number.isFinite(assetId)) {
    return <EmptyState icon={LineChart} title="Instrument inconnu" description="" />
  }

  return (
    <div className="space-y-5">
      <div>
        <Button variant="ghost" size="sm" asChild>
          <Link to="/marches">
            <ArrowLeft aria-hidden />
            Marchés
          </Link>
        </Button>
      </div>

      {quote.isPending ? (
        <TableSkeleton rows={2} columns={3} />
      ) : quote.isError ? (
        <ErrorState error={toApiError(quote.error)} onRetry={() => void quote.refetch()} />
      ) : (
        <>
          <header className="flex flex-wrap items-start justify-between gap-3">
            <div className="space-y-1">
              <h1 className="text-lg font-semibold tracking-tight">
                {quote.data.symbol}
              </h1>
              <p className="text-sm text-muted-foreground">
                {quote.data.name} · {quote.data.asset_class} · {quote.data.source}
              </p>
            </div>
            <div className="text-right">
              <p className="text-xl font-semibold tabular">
                {quote.data.price ?? "Aucune donnée"}
              </p>
              {quote.data.change_percent !== null ? (
                <p className={`text-sm tabular ${signClass(signOf(quote.data.change_percent))}`}>
                  {formatPercent(quote.data.change_percent)}
                </p>
              ) : null}
            </div>
          </header>

          <div className="flex flex-wrap items-center gap-2">
            {TIMEFRAMES.map((code) => (
              <Button
                key={code}
                variant={code === timeframe ? "secondary" : "ghost"}
                size="sm"
                onClick={() => setTimeframe(code)}
              >
                {code}
              </Button>
            ))}
            <Badge variant={FRESHNESS_VARIANT[quote.data.freshness]} className="ml-auto">
              {quote.data.freshness === "STALE" ? (
                <AlertTriangle className="size-3" aria-hidden />
              ) : null}
              {quote.data.freshness_label}
            </Badge>
          </div>

          {quote.data.freshness === "STALE" ? (
            <Alert variant="warning" title="Ce graphique ne montre pas le marché actuel">
              La dernière bougie date du{" "}
              {quote.data.as_of
                ? new Date(quote.data.as_of).toLocaleString("fr-FR")
                : "—"}{" "}
              ({formatAge(quote.data.age_seconds)}). Ce qui s'est passé depuis
              n'apparaît nulle part sur ce graphique.
            </Alert>
          ) : null}
        </>
      )}

      <Card>
        <CardContent className="p-4">
          {history.isPending ? (
            <TableSkeleton rows={4} columns={1} />
          ) : history.isError ? (
            <ErrorState
              error={toApiError(history.error)}
              onRetry={() => void history.refetch()}
            />
          ) : history.data.candles.length === 0 ? (
            <EmptyState
              icon={LineChart}
              title="Aucun historique"
              description={
                <>
                  Aucune bougie n'est enregistrée pour cet instrument sur cette
                  unité de temps.
                </>
              }
            />
          ) : (
            <div className="space-y-2">
              <CandleChart candles={history.data.candles} />
              {/* Le canevas est aria-hidden : sans cette alternative, un
                  lecteur d'écran ne restituerait rien du graphique. */}
              <p className="sr-only">
                Graphique en chandeliers, {history.data.candles.length} bougies
                sur {history.data.timeframe ?? "—"}. Première clôture{" "}
                {history.data.candles[0]?.close ?? "—"}, dernière{" "}
                {history.data.candles[history.data.candles.length - 1]?.close ?? "—"}.
                Fraîcheur : {history.data.freshness_label}.
              </p>
              <p className="text-xs text-muted-foreground tabular">
                {history.data.candles.length} bougie
                {history.data.candles.length > 1 ? "s" : ""} · {history.data.source} ·
                dernière le{" "}
                {history.data.as_of
                  ? new Date(history.data.as_of).toLocaleString("fr-FR")
                  : "—"}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
