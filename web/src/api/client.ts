import axios, {
  AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from "axios"

import type { ApiError } from "@/types/api"

import {
  clearTokens,
  getAccessToken,
  getRefreshToken,
  setAccessToken,
  setRefreshToken,
} from "./tokens"

export const API_BASE = "/api/v1"

/** Appelé quand la session est définitivement perdue (refresh refusé). */
let onSessionExpired: (() => void) | null = null
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler
}

export const api: AxiosInstance = axios.create({
  baseURL: API_BASE,
  timeout: 30_000,
  headers: { "Content-Type": "application/json" },
})

api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = getAccessToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

/**
 * Rafraîchissement : une seule requête en vol.
 *
 * Un écran de trading déclenche facilement cinq requêtes en parallèle. Sans
 * cette mutualisation, un access expiré provoquerait cinq refresh simultanés ;
 * la rotation étant activée côté serveur, quatre d'entre eux présenteraient un
 * refresh déjà consommé et feraient tomber la session. Les appels concurrents
 * attendent donc la même promesse.
 */
let refreshInFlight: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refresh = getRefreshToken()
  if (!refresh) throw new Error("no-refresh-token")

  // Instance nue : ne pas repasser par les intercepteurs, sinon un refresh
  // qui échoue en 401 relancerait un refresh, en boucle.
  const response = await axios.post<{ access: string; refresh?: string }>(
    `${API_BASE}/auth/refresh/`,
    { refresh },
    { headers: { "Content-Type": "application/json" }, timeout: 15_000 },
  )

  setAccessToken(response.data.access)
  // La rotation est activée : le serveur renvoie un nouveau refresh et
  // révoque l'ancien. Ne pas le stocker condamnerait la session suivante.
  if (response.data.refresh) setRefreshToken(response.data.refresh)
  return response.data.access
}

interface RetriableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const config = error.config as RetriableConfig | undefined
    const status = error.response?.status

    // Routes où un 401 signifie « identifiants refusés », pas « jeton
    // expiré » : les rejouer après un refresh n'aurait aucun sens.
    // Ne PAS exclure tout /auth/ : /auth/me/ est l'appel qui restaure la
    // session au démarrage et doit justement pouvoir déclencher un refresh.
    const NO_REFRESH = ["/auth/login/", "/auth/login/mfa/", "/auth/refresh/"]
    const isCredentialRoute =
      typeof config?.url === "string" &&
      NO_REFRESH.some((route) => config.url?.startsWith(route))

    if (status === 401 && config && !config._retried && !isCredentialRoute) {
      config._retried = true
      try {
        refreshInFlight ??= refreshAccessToken().finally(() => {
          refreshInFlight = null
        })
        const token = await refreshInFlight
        config.headers.Authorization = `Bearer ${token}`
        return api.request(config)
      } catch {
        clearTokens()
        onSessionExpired?.()
      }
    }

    return Promise.reject(error)
  },
)

/** Traduit une erreur axios en message affichable, sans jamais inventer. */
export function toApiError(error: unknown): ApiError {
  if (!axios.isAxiosError(error)) {
    return { message: "Une erreur inattendue est survenue." }
  }

  const status = error.response?.status

  if (error.code === "ECONNABORTED") {
    return { message: "Le serveur met trop de temps à répondre.", status }
  }
  if (!error.response) {
    return { message: "Serveur injoignable. Vérifiez votre connexion.", status }
  }

  const data = error.response.data as Record<string, unknown> | undefined

  if (status === 429) {
    return {
      message: "Trop de tentatives. Réessayez dans un instant.",
      code: "THROTTLED",
      status,
    }
  }
  if (status === 403 && typeof data?.code === "string") {
    return {
      message: String(data.detail ?? "Accès refusé."),
      code: data.code,
      status,
    }
  }

  if (typeof data?.detail === "string") {
    return {
      message: data.detail,
      code: typeof data.code === "string" ? data.code : undefined,
      status,
    }
  }

  // Erreurs de validation DRF : {champ: ["message", …]}
  if (data && typeof data === "object") {
    const fields: Record<string, string[]> = {}
    for (const [key, value] of Object.entries(data)) {
      if (Array.isArray(value)) fields[key] = value.map(String)
      else if (typeof value === "string") fields[key] = [value]
    }
    const first = Object.values(fields)[0]?.[0]
    if (first) return { message: first, fields, status }
  }

  return { message: `Erreur ${status ?? ""}`.trim(), status }
}

export async function request<T>(config: AxiosRequestConfig): Promise<T> {
  const response = await api.request<T>(config)
  return response.data
}
