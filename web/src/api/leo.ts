import { request } from "./client"
import { openRealtimeSocket } from "./realtime"
import type { Paginated } from "@/types/api"

// Le marqueur vit avec le transport — `api/realtime.ts` — et non ici :
// le laisser dans ce module créait un cycle d'imports dès que le
// transport a été mutualisé. Réexporté pour les appelants existants.
export { JWT_SUBPROTOCOL } from "./realtime"

export type LeoRole = "USER" | "ASSISTANT" | "SYSTEM"

export interface LeoAction {
  id: number
  type: string
  params: Record<string, unknown>
  status: string
  rationale: string
}

/**
 * Demande de confirmation TRANSACTIONNELLE, mise en attente par le Risk
 * Engine (`AssistantActionRequest` côté serveur).
 *
 * À ne pas confondre avec `LeoAction`, qui est une simple proposition
 * attachée à un message (`AssistantAction`). Deux modèles, deux séquences
 * de clés primaires : les confondre fait confirmer une opération que
 * l'utilisateur n'a pas regardée.
 */
export interface LeoActionRequest {
  id: number
  intent?: string
  action_type: string
  status: string
  mode: string
  requires_double_confirmation: boolean
  confirmations_received: number
  summary: string
  risk_summary: string
  error_message: string | null
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

// Les décisions passent par la socket — voir `LeoClientEvent`. Deux
// fonctions postaient auparavant sur `/assistant/action-requests/<id>/`
// l'identifiant d'un `AssistantAction` : l'endpoint d'un AUTRE modèle.

// ── Temps réel ───────────────────────────────────────────────────────────

export type LeoServerEvent =
  | { type: "session"; session_id: number; history: LeoMessage[]; quota?: unknown }
  | { type: "thinking" }
  | { type: "chunk"; text: string; id: number }
  | {
      type: "done"
      id: number
      actions?: LeoAction[]
      clean_content?: string
      action_request?: LeoActionRequest | null
      meta?: Record<string, unknown>
    }
  | { type: "action_update"; action_id: number; status: string }
  | { type: "error"; message: string }
  | { type: string; [key: string]: unknown }

/** Ce que le client envoie. Les deux modèles ont chacun leur type. */
export type LeoClientEvent =
  | { type: "chat"; message: string; context?: Record<string, unknown> }
  | { type: "action_confirm"; action_id: number }
  | { type: "action_reject"; action_id: number }
  | { type: "action_request_confirm"; request_id: number }
  | { type: "action_request_cancel"; request_id: number }

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
  return openRealtimeSocket("/ws/assistant/chat/")
}
