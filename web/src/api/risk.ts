import { request } from "./client"
import type { Paginated } from "@/types/api"

export interface RiskProfile {
  id: number
  portfolio: number
  portfolio_name: string
  name: string
  is_active: boolean
  is_default: boolean
  max_risk_per_trade: string
  max_daily_loss: string
  max_weekly_loss: string
  max_monthly_loss: string
  max_drawdown: string
  max_open_positions: number
  max_symbol_exposure_percent: string
  max_asset_class_exposure_percent: string
  max_correlated_exposure_percent: string
  max_leverage: string
  min_confidence: string
  allow_short: boolean
  allow_live_trading: boolean
  require_stop_loss: boolean
  block_on_high_correlation: boolean
  kill_switch_enabled: boolean
  /** Capital Preservation First — restreint l'univers aux instruments CORE. */
  preservation_mode: boolean
  allow_volatile_instruments: boolean
  allow_speculative_instruments: boolean
  notes: string | null
}

/** Limite et part déjà consommée. `usage_percent` est null si aucune limite. */
export interface RiskLimit {
  key: "daily_loss" | "weekly_loss" | "drawdown"
  label: string
  consumed_percent: string
  limit_percent: string
  usage_percent: string | null
}

export interface RiskSummary {
  portfolio_id: number
  has_profile: boolean
  profile: RiskSummaryProfile | null
  kill_switch_active: boolean
  kill_switch_reason: string
  kill_switch_reason_code: string
  kill_switch_triggered_at: string | null
  limits: RiskLimit[]
  open_positions: number
  max_open_positions: number
  positions_usage_percent: string | null
}

export interface RiskSummaryProfile {
  id: number
  name: string
  is_active: boolean
  max_risk_per_trade: string
  max_daily_loss: string
  max_weekly_loss: string
  max_monthly_loss: string
  max_drawdown: string
  max_open_positions: number
  max_leverage: string
  allow_short: boolean
  allow_live_trading: boolean
  require_stop_loss: boolean
  kill_switch_enabled: boolean
  preservation_mode: boolean
  allow_volatile_instruments: boolean
  allow_speculative_instruments: boolean
}

export function fetchRiskSummary(portfolioId: number): Promise<RiskSummary> {
  return request<RiskSummary>({
    method: "GET",
    url: `/risk-utils/summary/${portfolioId}/`,
  })
}

export function listRiskProfiles(portfolioId?: number): Promise<Paginated<RiskProfile>> {
  return request<Paginated<RiskProfile>>({
    method: "GET",
    url: "/risk-profiles/",
    params: portfolioId ? { portfolio: portfolioId } : undefined,
  })
}

export function updateRiskProfile(
  id: number,
  payload: Partial<RiskProfile>,
): Promise<RiskProfile> {
  return request<RiskProfile>({
    method: "PATCH",
    url: `/risk-profiles/${id}/`,
    data: payload,
  })
}

export function refreshRiskStates(portfolioId: number): Promise<unknown> {
  return request({
    method: "POST",
    url: "/risk-utils/refresh-states/",
    data: { portfolio_id: portfolioId },
  })
}

export function resolveKillSwitch(portfolioId: number): Promise<{ resolved_count: number }> {
  return request<{ resolved_count: number }>({
    method: "POST",
    url: "/kill-switch-events/resolve-for-portfolio/",
    data: { portfolio_id: portfolioId },
  })
}
