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
  /** Ce qui se produira réellement si un ordre est soumis. */
  trading_mode: "PAPER" | "LIVE"
  /** Ce que l'utilisateur a configuré sur ses comptes broker. */
  configured_trading_mode: "PAPER" | "LIVE"
  /**
   * Motif qui rend le mode réel inatteignable, ou chaîne vide.
   * Renseigné dès qu'un contrôle serveur interdirait une exécution
   * réelle — KYC non approuvé, notamment — que le mode réel ait été
   * demandé ou non. Pour parler d'un ÉCART, il faut donc le croiser avec
   * `configured_trading_mode === "LIVE"` : l'écart doit être expliqué à
   * l'utilisateur, jamais masqué.
   */
  live_blocked_reason: "" | "KYC_REQUIRED" | string
  /** Kill switch de plateforme : à false, aucune ouverture n'est acceptée. */
  trading_enabled: boolean
  portfolio: ContextPortfolio | null
  wallet: ContextWallet | null
}

export function fetchContext(): Promise<AppContext> {
  return request<AppContext>({ method: "GET", url: "/context/" })
}
