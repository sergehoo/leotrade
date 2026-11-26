import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, LineChart, Search, Star, StarOff } from "lucide-react"
import { useMemo, useState } from "react"
import { Link } from "react-router-dom"
import { toast } from "sonner"

import { toApiError } from "@/api/client"
import {
  followAsset,
  formatAge,
  listQuotes,
  listWatchlist,
  unfollowAsset,
  type Freshness,
  type Quote,
} from "@/api/market"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { formatPercent, signClass, signOf } from "@/lib/money"
import { cn } from "@/lib/utils"

const CLASSES = [
  { value: "ALL", label: "Toutes les classes" },
  { value: "CRYPTO", label: "Crypto" },
  { value: "FOREX", label: "Forex" },
  { value: "INDEX", label: "Indices" },
  { value: "COMMODITY", label: "Matières premières" },
  { value: "STOCK", label: "Actions" },
]

const TIMEFRAMES = ["1h", "4h", "1d", "1w"]

export default function MarketPage() {
  const queryClient = useQueryClient()
  const [search, setSearch] = useState("")
  const [assetClass, setAssetClass] = useState("ALL")
  const [timeframe, setTimeframe] = useState("1d")

  const quotes = useQuery({
    queryKey: ["market-quotes", search, assetClass, timeframe],
    queryFn: () =>
      listQuotes({
        search: search || undefined,
        asset_class: assetClass === "ALL" ? undefined : assetClass,
        timeframe,
      }),
  })

  const watchlist = useQuery({ queryKey: ["watchlist"], queryFn: listWatchlist })

  const followedByAsset = useMemo(() => {
    const map = new Map<number, number>()
    for (const item of watchlist.data?.results ?? []) map.set(item.asset, item.id)
    return map
  }, [watchlist.data])

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["watchlist"] })
  }

  const follow = useMutation({
    mutationFn: followAsset,
    onSuccess: () => {
      invalidate()
      toast.success("Instrument ajouté à ta liste de suivi.")
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  const unfollow = useMutation({
    mutationFn: unfollowAsset,
    onSuccess: () => {
      invalidate()
      toast.success("Instrument retiré de ta liste.")
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  const rows = quotes.data?.results ?? []
  const staleCount = rows.filter((row) => row.freshness === "STALE").length

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold tracking-tight">Marchés</h1>
        <p className="text-sm text-muted-foreground">
          Derniers cours connus. Chaque prix porte sa date et sa source.
        </p>
      </header>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[12rem] flex-1">
          <Search
            className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Rechercher un symbole…"
            aria-label="Rechercher un instrument"
            className="pl-8"
          />
        </div>

        <Select value={assetClass} onValueChange={setAssetClass}>
          <SelectTrigger className="w-auto min-w-[11rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {CLASSES.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={timeframe} onValueChange={setTimeframe}>
          <SelectTrigger className="w-auto min-w-[6rem]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {TIMEFRAMES.map((code) => (
              <SelectItem key={code} value={code}>
                {code}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {staleCount > 0 ? (
        <Alert variant="warning" title="Cours périmés">
          {staleCount} instrument{staleCount > 1 ? "s" : ""} sur {rows.length}{" "}
          {staleCount > 1 ? "affichent" : "affiche"} un cours trop ancien pour
          décider. La date de chaque ligne indique de quand il date.
        </Alert>
      ) : null}

      {quotes.isPending ? (
        <TableSkeleton rows={6} columns={5} />
      ) : quotes.isError ? (
        <ErrorState error={toApiError(quotes.error)} onRetry={() => void quotes.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={LineChart}
          title="Aucun instrument"
          description={
            search || assetClass !== "ALL" ? (
              <>Aucun instrument ne correspond à ces critères.</>
            ) : (
              <>
                Le catalogue est alimenté par les connecteurs de données. Aucun
                instrument n'est encore disponible.
              </>
            )
          }
        />
      ) : (
        <QuotesTable
          quotes={rows}
          followedByAsset={followedByAsset}
          onFollow={(assetId) => follow.mutate(assetId)}
          onUnfollow={(itemId) => unfollow.mutate(itemId)}
          busy={follow.isPending || unfollow.isPending}
        />
      )}
    </div>
  )
}

function QuotesTable({
  quotes,
  followedByAsset,
  onFollow,
  onUnfollow,
  busy,
}: {
  quotes: Quote[]
  followedByAsset: Map<number, number>
  onFollow: (assetId: number) => void
  onUnfollow: (itemId: number) => void
  busy: boolean
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[48rem] text-sm">
        <thead className="border-b border-border bg-secondary/40 text-left text-xs text-muted-foreground">
          <tr>
            <th scope="col" className="px-3 py-2 font-medium">Instrument</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Dernier cours</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Variation</th>
            <th scope="col" className="px-3 py-2 font-medium">Fraîcheur</th>
            <th scope="col" className="px-3 py-2 font-medium">Source</th>
            <th scope="col" className="px-3 py-2 text-right font-medium">Suivi</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {quotes.map((quote) => {
            const itemId = followedByAsset.get(quote.asset_id)
            return (
              <tr key={quote.asset_id} className="hover:bg-accent/40">
                <td className="px-3 py-2">
                  <Link
                    to={`/marches/${quote.asset_id}`}
                    className="font-medium underline-offset-2 hover:underline"
                  >
                    {quote.symbol}
                  </Link>
                  {quote.name && quote.name !== quote.symbol ? (
                    <span className="block text-xs text-muted-foreground">{quote.name}</span>
                  ) : null}
                </td>

                <td className="px-3 py-2 text-right tabular">
                  {quote.price === null ? (
                    <span className="text-muted-foreground">Aucune donnée</span>
                  ) : (
                    <span className={cn(quote.freshness === "STALE" && "text-muted-foreground")}>
                      {quote.price}
                    </span>
                  )}
                </td>

                <td
                  className={cn(
                    "px-3 py-2 text-right tabular",
                    quote.change_percent === null
                      ? "text-muted-foreground"
                      : signClass(signOf(quote.change_percent)),
                  )}
                >
                  {quote.change_percent === null ? "—" : formatPercent(quote.change_percent)}
                </td>

                <td className="px-3 py-2">
                  <FreshnessCell quote={quote} />
                </td>

                <td className="px-3 py-2 text-xs text-muted-foreground">{quote.source}</td>

                <td className="px-3 py-2 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    aria-label={
                      itemId ? `Ne plus suivre ${quote.symbol}` : `Suivre ${quote.symbol}`
                    }
                    onClick={() =>
                      itemId ? onUnfollow(itemId) : onFollow(quote.asset_id)
                    }
                  >
                    {itemId ? (
                      <Star className="fill-current text-warning" aria-hidden />
                    ) : (
                      <StarOff className="text-muted-foreground" aria-hidden />
                    )}
                  </Button>
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
 * Fraîcheur d'une cotation.
 *
 * Affiche la classe ET la date. Une pastille seule laisserait l'utilisateur
 * deviner ce que « périmé » veut dire — un jour ? cinq mois ? La date
 * tranche, la pastille attire l'œil.
 */
function FreshnessCell({ quote }: { quote: Quote }) {
  const variant: Record<Freshness, "gain" | "warning" | "loss" | "outline"> = {
    LIVE: "gain",
    DELAYED: "warning",
    STALE: "loss",
    NO_DATA: "outline",
  }

  return (
    <div className="space-y-0.5">
      <Badge variant={variant[quote.freshness]}>
        {quote.freshness === "STALE" ? (
          <AlertTriangle className="size-3" aria-hidden />
        ) : null}
        {quote.freshness_label}
      </Badge>
      {quote.as_of ? (
        <p className="text-xs text-muted-foreground tabular">
          {new Date(quote.as_of).toLocaleString("fr-FR", {
            day: "2-digit",
            month: "2-digit",
            year: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
          })}
          <span className="ml-1">({formatAge(quote.age_seconds)})</span>
        </p>
      ) : null}
    </div>
  )
}
