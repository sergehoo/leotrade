import { request } from "./client"
import type { Paginated } from "@/types/api"

export type BrokerKind = "BINANCE" | "MT5" | "DERIV"
export type TradingMode = "PAPER" | "LIVE"
export type BrokerStatus = "DRAFT" | "ACTIVE" | "INACTIVE" | "ERROR"
export type CircuitState = "CLOSED" | "OPEN" | "HALF_OPEN" | "UNAVAILABLE"

/** Champ de secret, côté formulaire. Le serveur ne renvoie jamais sa valeur. */
export type SecretField = "api_key" | "api_secret" | "password" | "deriv_token"

export interface SecretState {
  configured: boolean
  updated_at: string | null
  rotated_at: string | null
}

export interface BrokerAccount {
  id: number
  name: string
  broker: BrokerKind
  mode: TradingMode
  login: string | null
  server: string | null
  terminal_path: string | null
  deriv_app_id: string | null
  deriv_currency: string
  deriv_account_type: string | null
  is_active: boolean
  is_default: boolean
  status: BrokerStatus
  last_connection_status: boolean
  last_connection_error: string | null
  last_connected_at: string | null
  notes: string | null
  created_at: string
  updated_at: string
  secrets: Record<SecretField, SecretState>
  missing_secrets: SecretField[]
  required_secrets: SecretField[]
  is_ready_to_connect: boolean
}

export interface BrokerHealth {
  id: number
  name: string
  broker: BrokerKind
  mode: TradingMode
  is_default: boolean
  is_active: boolean
  status: BrokerStatus
  connected: boolean
  last_connected_at: string | null
  last_error: string
  circuit_state: CircuitState
  last_sync_at: string | null
  missing_secrets: SecretField[]
}

/** Charge utile d'écriture. Un secret omis ou vide conserve l'existant. */
export interface BrokerAccountPayload {
  name: string
  broker: BrokerKind
  mode: TradingMode
  login?: string
  server?: string
  terminal_path?: string
  deriv_app_id?: string
  deriv_currency?: string
  deriv_account_type?: string
  is_active?: boolean
  is_default?: boolean
  notes?: string
  api_key?: string
  api_secret?: string
  password?: string
  deriv_token?: string
}

export interface ConnectionTestResult {
  status: "ok"
  payload: unknown
  account: BrokerAccount
}

export const BROKER_LABELS: Record<BrokerKind, string> = {
  BINANCE: "Binance",
  MT5: "MetaTrader 5",
  DERIV: "Deriv",
}

export const SECRET_LABELS: Record<SecretField, string> = {
  api_key: "Clé API",
  api_secret: "Secret API",
  password: "Mot de passe",
  deriv_token: "Jeton Deriv",
}

export function listBrokers(): Promise<Paginated<BrokerAccount>> {
  return request<Paginated<BrokerAccount>>({ method: "GET", url: "/brokers/" })
}

export function fetchBrokerHealth(): Promise<{ results: BrokerHealth[]; count: number }> {
  return request<{ results: BrokerHealth[]; count: number }>({
    method: "GET",
    url: "/brokers/health/",
  })
}

export function createBroker(payload: BrokerAccountPayload): Promise<BrokerAccount> {
  return request<BrokerAccount>({ method: "POST", url: "/brokers/", data: payload })
}

export function updateBroker(
  id: number,
  payload: Partial<BrokerAccountPayload>,
): Promise<BrokerAccount> {
  return request<BrokerAccount>({ method: "PATCH", url: `/brokers/${id}/`, data: payload })
}

export function deleteBroker(id: number): Promise<void> {
  return request<void>({ method: "DELETE", url: `/brokers/${id}/` })
}

export function setDefaultBroker(id: number): Promise<BrokerAccount> {
  return request<BrokerAccount>({ method: "POST", url: `/brokers/${id}/set-default/` })
}

export function testBrokerConnection(id: number): Promise<ConnectionTestResult> {
  return request<ConnectionTestResult>({ method: "POST", url: `/brokers/${id}/test-connection/` })
}
