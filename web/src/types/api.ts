/** Formes partagées de l'API v1. Alignées sur backend/api/serializers/. */

export interface Paginated<T> {
  count: number
  page: number
  pages: number
  page_size: number
  next: string | null
  previous: string | null
  results: T[]
}

export type KycStatus =
  | "NOT_STARTED"
  | "PENDING"
  | "UNDER_REVIEW"
  | "APPROVED"
  | "REJECTED"

export interface Capabilities {
  can_trade_live: boolean
  can_trade_paper: boolean
  can_withdraw: boolean
  kyc_required_for: string[]
}

export interface CurrentUser {
  id: number
  email: string
  first_name: string
  last_name: string
  date_joined: string
  last_login: string | null
  is_staff: boolean
  kyc_status: KycStatus
  kyc_rejection_reason: string
  mfa_enabled: boolean
  email_verified: boolean
  capabilities: Capabilities
}

export interface TokenPair {
  access: string
  refresh: string
  user: CurrentUser
}

export interface MfaChallenge {
  mfa_required: true
  mfa_token: string
  expires_in: number
}

export type LoginResult = TokenPair | MfaChallenge

export function isMfaChallenge(r: LoginResult): r is MfaChallenge {
  return (r as MfaChallenge).mfa_required === true
}

/** Erreur API normalisée, telle que l'UI doit l'afficher. */
export interface ApiError {
  /** Message prêt à l'affichage, en français. */
  message: string
  /** Code machine quand le backend en fournit un (EMAIL_NOT_VERIFIED, …). */
  code?: string
  status?: number
  /** Erreurs par champ, pour les formulaires. */
  fields?: Record<string, string[]>
}
