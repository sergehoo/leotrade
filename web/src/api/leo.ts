import { request } from "./client"
import { getAccessToken } from "./tokens"
import type { Paginated } from "@/types/api"

/** Marqueur du sous-protocole JWT — doit correspondre à core/ws_auth.py. */
export const JWT_SUBPROTOCOL = "leotrade.jwt"

export type LeoRole = "USER" | "ASSISTANT" | "SYSTEM"

export interface LeoAction {
  id: number
  type: string
  params: Record<string, unknown>
  status: string
  rationale: string
}

export interface LeoMessage {
  id: number
  role: LeoRole
  content: string
  status: string
  error_message: string | null
  model_used: string | null
  provider: string | null
  actions: LeoAction[]
  created_at: string
}

export interface LeoConversation {
  id: number
  title: string
  context_type: string
  context_id: string | null
  context_label: string
  is_active: boolean
  archived: boolean
  message_count: number
  last_message_preview: string
  created_at: string
  updated_at: string
}

export function listConversations(): Promise<Paginated<LeoConversation>> {
  return request<Paginated<LeoConversation>>({
    method: "GET",
    url: "/assistant/conversations/",
  })
}

export function fetchConversationMessages(id: number): Promise<LeoMessage[]> {
  return request<{ results?: LeoMessage[] } | LeoMessage[]>({
    method: "GET",
    url: `/assistant/conversations/${id}/messages/`,
  }).then((body) => (Array.isArray(body) ? body : (body.results ?? [])))
}

export function confirmAction(id: number): Promise<unknown> {
  return request({ method: "POST", url: `/assistant/action-requests/${id}/confirm/` })
}

export function cancelAction(id: number): Promise<unknown> {
  return request({ method: "POST", url: `/assistant/action-requests/${id}/cancel/` })
}

// ── Temps réel ───────────────────────────────────────────────────────────

export type LeoServerEvent =
  | { type: "session"; session_id: number; history: LeoMessage[]; quota?: unknown }
  | { type: "thinking" }
  | { type: "chunk"; text: string; id: number }
  | { type: "done"; id: number; actions?: LeoAction[]; meta?: Record<string, unknown> }
  | { type: "action_update"; action_id: number; status: string }
  | { type: "error"; message: string }
  | { type: string; [key: string]: unknown }

/**
 * Ouvre la connexion temps réel de Leo.
 *
 * Le jeton voyage dans le sous-protocole et non dans l'URL : une chaîne
 * de requête se retrouve dans les journaux d'accès du serveur, des
 * proxies et des CDN, où elle survit bien au-delà de la validité du
 * jeton. Voir backend/core/ws_auth.py.
 *
 * Renvoie `null` si aucun jeton n'est disponible — ouvrir une connexion
 * vouée au refus produirait une boucle de reconnexion silencieuse.
 */
export function openLeoSocket(): WebSocket | null {
  const token = getAccessToken()
  if (!token) return null

  const origin = window.location.origin.replace(/^http/, "ws")
  return new WebSocket(`${origin}/ws/assistant/chat/`, [JWT_SUBPROTOCOL, token])
}
