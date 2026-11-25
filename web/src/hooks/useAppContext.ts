import { useQuery } from "@tanstack/react-query"

import { fetchContext } from "@/api/context"
import { useAuth } from "@/stores/auth"

export const APP_CONTEXT_KEY = ["app-context"] as const

/**
 * Contexte global. Volontairement court en fraîcheur : le mode de trading et
 * le kill switch de plateforme peuvent changer côté serveur sans action de
 * l'utilisateur, et afficher un mode périmé est un risque, pas un détail.
 */
export function useAppContext() {
  const user = useAuth((s) => s.user)
  return useQuery({
    queryKey: APP_CONTEXT_KEY,
    queryFn: fetchContext,
    enabled: !!user,
    staleTime: 30_000,
    refetchOnWindowFocus: true,
  })
}
