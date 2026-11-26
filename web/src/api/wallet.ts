import { request } from "./client"
import type { Paginated } from "@/types/api"

/**
 * Synthèse du portefeuille électronique.
 *
 * L'argent réel (`available_balance`) et le capital de trading
 * (`*_trading_capital`) sont deux réserves distinctes. Les confondre
 * conduit à croire qu'on dispose d'une somme qu'on n'a pas.
 */
export interface WalletSummary {
  has_wallet: boolean
  currency: string | null
  is_active: boolean
  available_balance: string | null
  locked_balance: string | null
  total_balance: string | null
  total_deposited: string | null
  total_withdrawn: string | null
  /** Portefeuilles dont les ordres n'atteignent aucun marché. */
  simulated_trading_capital: string | null
  /** Portefeuilles branchés sur un compte broker réel. */
  live_trading_capital: string | null
  pending_withdrawals_count: number
  pending_withdrawals_amount: string | null
  /** Faux quand le grand livre n'explique pas tout le solde. */
  is_reconciled: boolean
  unexplained_amount: string | null
  ledger_entry_count: number
  ledger_break_count: number
}

export type LedgerEntryType = "CREDIT" | "DEBIT" | "LOCK" | "UNLOCK" | "FEE" | "REFUND"

export interface LedgerEntry {
  id: number
  entry_type: LedgerEntryType
  amount: string
  currency: string
  balance_before: string
  balance_after: string
  description: string
  created_at: string
}

export type WithdrawalStatus =
  | "PENDING" | "UNDER_REVIEW" | "APPROVED" | "REJECTED"
  | "PAID" | "FAILED" | "CANCELLED"

export interface WithdrawalRequest {
  id: number
  amount: string
  fee_amount: string
  currency: string
  destination_type: "BANK" | "CARD"
  destination_masked: string | null
  status: WithdrawalStatus
  failure_reason: string
  created_at: string
  reviewed_at: string | null
}

export function fetchWalletSummary(): Promise<WalletSummary> {
  return request<WalletSummary>({ method: "GET", url: "/wallet/summary/" })
}

export function listLedger(): Promise<Paginated<LedgerEntry>> {
  return request<Paginated<LedgerEntry>>({ method: "GET", url: "/wallet/ledger/" })
}

export function listWithdrawals(): Promise<Paginated<WithdrawalRequest>> {
  return request<Paginated<WithdrawalRequest>>({
    method: "GET",
    url: "/wallet/withdrawals/",
  })
}

/**
 * Demande de retrait.
 *
 * Crée un enregistrement en attente de revue et verrouille les fonds.
 * Aucun mouvement d'argent n'est déclenché ici.
 */
export function requestWithdrawal(payload: {
  amount: string
  destination_type?: "BANK" | "CARD"
  destination_masked?: string
}): Promise<WithdrawalRequest> {
  return request<WithdrawalRequest>({
    method: "POST",
    url: "/wallet/withdrawals/",
    data: payload,
  })
}

export const WITHDRAWAL_LABELS: Record<WithdrawalStatus, string> = {
  PENDING: "En attente de revue",
  UNDER_REVIEW: "En cours d'examen",
  APPROVED: "Approuvée",
  REJECTED: "Refusée",
  PAID: "Payée",
  FAILED: "Échouée",
  CANCELLED: "Annulée",
}

export const LEDGER_LABELS: Record<LedgerEntryType, string> = {
  CREDIT: "Crédit",
  DEBIT: "Débit",
  LOCK: "Verrouillage",
  UNLOCK: "Déverrouillage",
  FEE: "Frais",
  REFUND: "Remboursement",
}
