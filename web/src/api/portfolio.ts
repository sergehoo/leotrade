import { request } from "./client"
import type { Paginated } from "@/types/api"
import type { TradingMode } from "./brokers"

export type PositionSide = "LONG" | "SHORT"
export type PositionStatus = "OPEN" | "CLOSED" | "PARTIAL" | string

export interface Portfolio {
  id: number
  name: string
  description: string | null
  base_currency: string
  starting_balance: string
  current_balance: string
  available_cash: string
  locked_cash: string
  equity: string
  unrealized_pnl: string
  realized_pnl: string
  margin_used: string
  max_equity: string
  current_drawdown_percent: number
  max_drawdown_percent: number
  is_active: boolean
  is_default: boolean
  broker_account: number
  broker_name: string
  broker_type: string
  /** Mode porté par le compte broker rattaché. */
  trading_mode: TradingMode
  /** Aucun ordre de ce portefeuille n'atteint un marché réel. */
  is_simulated: boolean
  created_at: string
  updated_at: string
}

export interface Position {
  id: number
  portfolio: number
  portfolio_name: string
  symbol: string
  asset_name: string | null
  side: PositionSide
  quantity: string
  entry_price: string
  average_entry_price: string
  current_price: string
  stop_loss: string | null
  take_profit: string | null
  leverage: string
  margin_used: string
  notional_value: string
  exposure_value: string
  unrealized_pnl: string
  realized_pnl: string
  status: PositionStatus
  source: string
  opened_at: string | null
  closed_at: string | null
}

export interface AssetClassExposure {
  asset_class?: string
  exposure?: string | number
  percent?: string | number
  [key: string]: unknown
}

/**
 * Synthèse consolidée. Les montants sont des chaînes : le backend calcule
 * en Decimal et les reconvertir en `number` rouvrirait les erreurs
 * d'arrondi que ce choix élimine. On ne les parse qu'à l'affichage.
 */
export interface PortfolioSummary {
  portfolio_id: number
  base_currency: string
  trading_mode: TradingMode
  is_simulated: boolean
  equity: string
  current_balance: string
  available_cash: string
  locked_cash: string
  margin_used: string
  unrealized_pnl: string
  realized_pnl: string
  total_pnl: string
  total_pnl_percent: string
  current_drawdown_percent: number
  max_drawdown_percent: number
  open_positions: number
  long_positions: number
  short_positions: number
  winning_positions: number
  losing_positions: number
  exposure_value: string
  exposure_percent: string
  asset_class_exposure: AssetClassExposure[]
}

export interface ProvisionPaperPayload {
  name?: string
  starting_balance?: string
  currency?: string
}

export function listPortfolios(): Promise<Paginated<Portfolio>> {
  return request<Paginated<Portfolio>>({ method: "GET", url: "/portfolios/" })
}

export function fetchPortfolioSummary(id: number): Promise<PortfolioSummary> {
  return request<PortfolioSummary>({ method: "GET", url: `/portfolios/${id}/summary/` })
}

export function listPositions(params?: {
  portfolio?: number
  status?: PositionStatus
  trading_mode?: TradingMode
}): Promise<Paginated<Position>> {
  return request<Paginated<Position>>({ method: "GET", url: "/positions/", params })
}

export function provisionPaperPortfolio(
  payload: ProvisionPaperPayload = {},
): Promise<Portfolio> {
  return request<Portfolio>({
    method: "POST",
    url: "/portfolios/provision-paper/",
    data: payload,
  })
}

export function refreshPortfolio(id: number): Promise<Portfolio> {
  return request<Portfolio>({ method: "POST", url: `/portfolios/${id}/refresh/` })
}

export function setDefaultPortfolio(id: number): Promise<{ status: string }> {
  return request<{ status: string }>({
    method: "POST",
    url: `/portfolios/${id}/set-default/`,
  })
}


export interface EquityPoint {
  at: string
  equity: string
  balance: string
  unrealized_pnl: string
  realized_pnl: string
  drawdown_percent: number
}

/**
 * Série de valorisation, avec le verdict de traçabilité.
 *
 * Un graphique affirme plus fort qu'un nombre : relier des points épars
 * donne à voir une trajectoire qui n'a jamais été mesurée. Le verdict
 * vient du serveur pour que deux clients ne tranchent pas différemment.
 */
export interface EquityCurve {
  portfolio_id: number
  base_currency: string
  points: EquityPoint[]
  point_count: number
  first_at: string | null
  last_at: string | null
  age_seconds: number | null
  /** Écart médian entre deux mesures. */
  median_gap_seconds: number | null
  is_plottable: boolean
  not_plottable_reasons: Array<"TOO_FEW_POINTS" | "GAPS_TOO_WIDE" | string>
  minimum_points: number
}

export function fetchEquityCurve(id: number, limit = 365): Promise<EquityCurve> {
  return request<EquityCurve>({
    method: "GET",
    url: `/portfolios/${id}/equity-curve/`,
    params: { limit },
  })
}
