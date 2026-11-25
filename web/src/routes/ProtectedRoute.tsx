import { Navigate, Outlet, useLocation } from "react-router-dom"

import { Spinner } from "@/components/ui/spinner"
import { useAuth } from "@/stores/auth"

export default function ProtectedRoute() {
  const user = useAuth((s) => s.user)
  const bootstrapping = useAuth((s) => s.bootstrapping)
  const location = useLocation()

  // Tant que la restauration de session n'a pas tranché, ne rien décider :
  // rediriger ici déconnecterait l'utilisateur à chaque rechargement.
  if (bootstrapping) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Spinner label="Restauration de la session…" />
      </div>
    )
  }

  if (!user) {
    return <Navigate to="/connexion" replace state={{ from: location.pathname }} />
  }

  return <Outlet />
}
