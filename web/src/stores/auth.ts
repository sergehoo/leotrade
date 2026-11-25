import { create } from "zustand"

import { fetchMe, login as apiLogin, loginMfa as apiLoginMfa, logout as apiLogout } from "@/api/auth"
import { getRefreshToken, setAccessToken } from "@/api/tokens"
import type { CurrentUser, LoginResult } from "@/types/api"
import { isMfaChallenge } from "@/types/api"

interface AuthState {
  user: CurrentUser | null
  /** `true` tant qu'on n'a pas tranché entre « connecté » et « déconnecté ». */
  bootstrapping: boolean
  /** Défi MFA en cours, le cas échéant. */
  mfaToken: string | null

  bootstrap: () => Promise<void>
  login: (email: string, password: string) => Promise<LoginResult>
  submitMfa: (code: string) => Promise<void>
  cancelMfa: () => void
  logout: () => Promise<void>
  setUser: (user: CurrentUser) => void
}

export const useAuth = create<AuthState>((set, get) => ({
  user: null,
  bootstrapping: true,
  mfaToken: null,

  /**
   * Au démarrage, l'access token est perdu (il ne vit qu'en mémoire). S'il
   * reste un refresh, on tente de restaurer la session ; sinon on tranche
   * immédiatement pour ne pas laisser l'interface sur un écran de chargement.
   */
  bootstrap: async () => {
    if (!getRefreshToken()) {
      set({ user: null, bootstrapping: false })
      return
    }
    try {
      // L'intercepteur 401 rafraîchira l'access au premier appel.
      const user = await fetchMe()
      set({ user, bootstrapping: false })
    } catch {
      setAccessToken(null)
      set({ user: null, bootstrapping: false })
    }
  },

  login: async (email, password) => {
    const result = await apiLogin(email, password)
    if (isMfaChallenge(result)) {
      set({ mfaToken: result.mfa_token })
    } else {
      set({ user: result.user, mfaToken: null })
    }
    return result
  },

  submitMfa: async (code) => {
    const token = get().mfaToken
    if (!token) throw new Error("Aucun défi MFA en cours.")
    const pair = await apiLoginMfa(token, code)
    set({ user: pair.user, mfaToken: null })
  },

  cancelMfa: () => set({ mfaToken: null }),

  logout: async () => {
    await apiLogout()
    set({ user: null, mfaToken: null })
  },

  setUser: (user) => set({ user }),
}))
