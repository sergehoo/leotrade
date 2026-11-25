import type { CurrentUser, LoginResult, TokenPair } from "@/types/api"

import { request } from "./client"
import { clearTokens, getRefreshToken, setAccessToken, setRefreshToken } from "./tokens"

export async function login(email: string, password: string): Promise<LoginResult> {
  const data = await request<LoginResult>({
    method: "POST",
    url: "/auth/login/",
    data: { email, password },
  })
  if ("access" in data) persist(data)
  return data
}

export async function loginMfa(mfaToken: string, code: string): Promise<TokenPair> {
  const data = await request<TokenPair>({
    method: "POST",
    url: "/auth/login/mfa/",
    data: { mfa_token: mfaToken, code },
  })
  persist(data)
  return data
}

export async function logout(): Promise<void> {
  const refresh = getRefreshToken()
  if (refresh) {
    try {
      // Révocation côté serveur : sans cet appel, le refresh resterait
      // valide jusqu'à expiration pour quiconque l'aurait intercepté.
      await request({ method: "POST", url: "/auth/logout/", data: { refresh } })
    } catch {
      /* déjà expiré ou révoqué : la déconnexion locale reste légitime */
    }
  }
  clearTokens()
}

export function fetchMe(): Promise<CurrentUser> {
  return request<CurrentUser>({ method: "GET", url: "/auth/me/" })
}

function persist(pair: TokenPair) {
  setAccessToken(pair.access)
  setRefreshToken(pair.refresh)
}
