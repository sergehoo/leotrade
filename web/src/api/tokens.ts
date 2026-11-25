/**
 * Stockage des jetons.
 *
 * Choix assumé : l'access token reste en mémoire (il meurt avec l'onglet),
 * le refresh token va dans localStorage pour survivre à un rechargement.
 * Ce n'est pas idéal face à un XSS — l'idéal serait un cookie httpOnly posé
 * par Django — mais c'est le compromis cohérent avec une API consommée aussi
 * par Flutter, qui ne peut pas s'appuyer sur un cookie de navigateur.
 * La contrepartie est assumée en amont : CSP stricte et aucun innerHTML
 * sur des données serveur.
 */

const REFRESH_KEY = "lyneci.refresh"

let accessToken: string | null = null

export function getAccessToken(): string | null {
  return accessToken
}

export function setAccessToken(token: string | null): void {
  accessToken = token
}

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_KEY)
  } catch {
    // Mode privé, stockage bloqué : on dégrade vers une session non
    // persistante plutôt que de planter l'application.
    return null
  }
}

export function setRefreshToken(token: string | null): void {
  try {
    if (token) localStorage.setItem(REFRESH_KEY, token)
    else localStorage.removeItem(REFRESH_KEY)
  } catch {
    /* stockage indisponible : la session ne survivra pas au rechargement */
  }
}

export function clearTokens(): void {
  setAccessToken(null)
  setRefreshToken(null)
}
