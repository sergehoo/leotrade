import { request } from "./client"

export interface ContextBroker {
  id: number
  name: string
  broker: string
  mode: "PAPER" | "LIVE"
  status: string
  is_active: boolean
}

export interface ContextPortfolio {
  id: number
  name: string
  base_currency: string
  current_balance: string
  available_cash: string
  locked_cash: string
  is_active: boolean
  broker_account: ContextBroker | null
}

export interface ContextWallet {
  id: number
  currency: string
  available_balance: string
  locked_balance: string
}

export interface AppContext {
  trading_mode: "PAPER" | "LIVE"
  /** Kill switch de plateforme : à false, aucune ouverture n'est acceptée. */
  trading_enabled: boolean
  portfolio: ContextPortfolio | null
  wallet: ContextWallet | null
}

export function fetchContext(): Promise<AppContext> {
  return request<AppContext>({ method: "GET", url: "/context/" })
}
