import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { useEffect } from "react"
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom"
import { Toaster } from "sonner"

import { setSessionExpiredHandler } from "@/api/client"
import AppShell from "@/components/layout/AppShell"
import DashboardPage, { PendingSection } from "@/routes/DashboardPage"
import BrokersPage from "@/routes/brokers/BrokersPage"
import LoginPage from "@/routes/LoginPage"
import ProtectedRoute from "@/routes/ProtectedRoute"
import { useAuth } from "@/stores/auth"

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (failureCount, error) => {
        // Inutile de réessayer ce que le serveur a refusé volontairement.
        const status = (error as { response?: { status?: number } })?.response?.status
        if (status && status >= 400 && status < 500) return false
        return failureCount < 2
      },
      staleTime: 15_000,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  const bootstrap = useAuth((s) => s.bootstrap)

  useEffect(() => {
    void bootstrap()
    // Session définitivement perdue : on vide le cache pour qu'aucune donnée
    // du compte précédent ne reste affichée.
    setSessionExpiredHandler(() => {
      useAuth.setState({ user: null, mfaToken: null, bootstrapping: false })
      queryClient.clear()
    })
  }, [bootstrap])

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/connexion" element={<LoginPage />} />
          <Route element={<ProtectedRoute />}>
            <Route element={<AppShell />}>
              <Route index element={<DashboardPage />} />
              <Route
                path="portefeuille"
                element={<PendingSection title="Portefeuille" scope="Le détail des positions" />}
              />
              <Route
                path="marches"
                element={<PendingSection title="Marchés" scope="Les données de marché" />}
              />
              <Route
                path="risque"
                element={<PendingSection title="Risque" scope="Le Risk Control" />}
              />
              <Route
                path="assistant"
                element={<PendingSection title="Assistant IA" scope="L'assistant conversationnel" />}
              />
              <Route
                path="portefeuille-electronique"
                element={<PendingSection title="Portefeuille électronique" scope="Les dépôts et retraits" />}
              />
              <Route path="brokers" element={<BrokersPage />} />
            </Route>
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
      <Toaster position="top-right" richColors closeButton />
    </QueryClientProvider>
  )
}
