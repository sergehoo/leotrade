import { getAccessToken } from "./tokens"

/** Marqueur du sous-protocole JWT — doit correspondre à core/ws_auth.py. */
export const JWT_SUBPROTOCOL = "leotrade.jwt"

/**
 * Ouvre une liaison temps réel.
 *
 * Mutualisé depuis `openLeoSocket` : six canaux existent côté serveur —
 * portefeuille, ordres, notifications, tableau de bord, radar IA,
 * bougies — et aucun n'était branché hormis celui de Leo.
 *
 * Le jeton voyage dans le sous-protocole et non dans l'URL : une chaîne
 * de requête se retrouve dans les journaux d'accès du serveur, des
 * proxies et des CDN, où elle survit bien au-delà de ses 15 minutes de
 * validité. Voir backend/core/ws_auth.py.
 *
 * Renvoie `null` si aucun jeton n'est disponible — ouvrir une connexion
 * vouée au refus produirait une boucle de reconnexion silencieuse.
 */
export function openRealtimeSocket(path: string): WebSocket | null {
  const token = getAccessToken()
  if (!token) return null

  const origin = window.location.origin.replace(/^http/, "ws")
  return new WebSocket(`${origin}${path}`, [JWT_SUBPROTOCOL, token])
}

/** Délais de reconnexion, en millisecondes. La dernière valeur se répète. */
export const RECONNECT_DELAYS = [1000, 2000, 5000, 10000, 30000]

export type RealtimeStatus = "connecting" | "online" | "lost"

/** Enveloppe commune aux canaux non conversationnels. */
export interface RealtimeEvent {
  event: string
  payload: Record<string, unknown>
}
