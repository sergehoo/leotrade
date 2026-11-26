import { request } from "./client"
import type { Paginated } from "@/types/api"

export type AssetClass = "CRYPTO" | "FOREX" | "STOCK" | "INDEX" | "COMMODITY" | string

/** LIVE | DELAYED | STALE | NO_DATA — relatif à l'unité de temps. */
export type Freshness = "LIVE" | "DELAYED" | "STALE" | "NO_DATA"

export interface Asset {
  id: number
  symbol: string
  name: string | null
  asset_class: AssetClass
  exchange: string
  base_asset: string | null
  quote_asset: string | null
  price_precision: number
  market_status: string
  is_active: boolean
  icon: string | null
}

/**
 * Cotation.
 *
 * Jamais un prix seul : toujours sa date, son âge et sa fraîcheur. Un
 * prix sans date est un prix qu'on croit courant, et c'est sur cette
 * croyance qu'on décide.
 */
export interface Quote {
  asset_id: number
  symbol: string
  name: string
  asset_class: AssetClass
  /** Place d'où vient le chiffre. */
  source: string
  timeframe: string | null
  price: string | null
  open: string | null
  high: string | null
  low: string | null
  volume: string | null
  change: string | null
  change_percent: string | null
  /** Horodatage de la bougie dont le prix est tiré. */
  as_of: string | null
  age_seconds: number | null
  freshness: Freshness
  freshness_label: string
  /** Statut porté par l'instrument — personne ne le met à jour. */
  declared_market_status: string
  /** Faux dès que la cotation n'est plus à jour. */
  is_tradable_quote: boolean
}

export interface Candle {
  open_time: string
  open: string | null
  high: string | null
  low: string | null
  close: string | null
  volume: string | null
}

export interface CandleHistory {
  asset_id: number
  symbol: string
  source: string
  timeframe: string | null
  as_of: string | null
  age_seconds: number | null
  freshness: Freshness
  freshness_label: string
  candles: Candle[]
}

export interface WatchlistItem {
  id: number
  asset: number
  symbol: string
  asset_class: AssetClass
  exchange: string
  position: number
  note: string
  created_at: string
}

export function listAssets(params?: {
  search?: string
  asset_class?: string
  page?: number
}): Promise<Paginated<Asset>> {
  return request<Paginated<Asset>>({ method: "GET", url: "/market/assets/", params })
}

export function listQuotes(params?: {
  search?: string
  asset_class?: string
  timeframe?: string
  page?: number
}): Promise<Paginated<Quote>> {
  return request<Paginated<Quote>>({
    method: "GET",
    url: "/market/assets/quotes/",
    params,
  })
}

export function fetchQuote(assetId: number, timeframe?: string): Promise<Quote> {
  return request<Quote>({
    method: "GET",
    url: `/market/assets/${assetId}/quote/`,
    params: timeframe ? { timeframe } : undefined,
  })
}

export function fetchCandles(
  assetId: number,
  params?: { timeframe?: string; limit?: number },
): Promise<CandleHistory> {
  return request<CandleHistory>({
    method: "GET",
    url: `/market/assets/${assetId}/candles/`,
    params,
  })
}

export function listWatchlist(): Promise<Paginated<WatchlistItem>> {
  return request<Paginated<WatchlistItem>>({ method: "GET", url: "/market/watchlist/" })
}

export function followAsset(assetId: number): Promise<WatchlistItem> {
  return request<WatchlistItem>({
    method: "POST",
    url: "/market/watchlist/",
    data: { asset: assetId },
  })
}

export function unfollowAsset(itemId: number): Promise<void> {
  return request<void>({ method: "DELETE", url: `/market/watchlist/${itemId}/` })
}

/** Libellé d'ancienneté, en clair. */
export function formatAge(seconds: number | null): string {
  if (seconds === null) return "—"
  if (seconds < 60) return "il y a moins d'une minute"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `il y a ${minutes} min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `il y a ${hours} h`
  const days = Math.floor(hours / 24)
  if (days < 31) return `il y a ${days} j`
  const months = Math.floor(days / 30)
  return `il y a ${months} mois`
}
