import {
  Bot,
  Briefcase,
  LayoutDashboard,
  LineChart,
  LogOut,
  Plug,
  ShieldAlert,
  Wallet,
} from "lucide-react"
import { NavLink, Outlet } from "react-router-dom"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useAuth } from "@/stores/auth"

const NAV = [
  { to: "/", label: "Tableau de bord", icon: LayoutDashboard, end: true },
  { to: "/portefeuille", label: "Portefeuille", icon: Briefcase },
  { to: "/marches", label: "Marchés", icon: LineChart },
  { to: "/risque", label: "Risque", icon: ShieldAlert },
  { to: "/assistant", label: "Assistant IA", icon: Bot },
  { to: "/portefeuille-electronique", label: "Portefeuille électronique", icon: Wallet },
  { to: "/brokers", label: "Brokers", icon: Plug },
] as const

export default function AppShell() {
  const user = useAuth((s) => s.user)
  const logout = useAuth((s) => s.logout)

  return (
    <div className="flex min-h-dvh flex-col bg-background lg:flex-row">
      <aside className="shrink-0 border-b border-border lg:w-60 lg:border-b-0 lg:border-r">
        <div className="flex items-center justify-between gap-3 px-4 py-4 lg:block">
          <div>
            <p className="font-semibold tracking-tight">LeoTrade</p>
            <p className="text-xs text-muted-foreground">Intelligent Trading</p>
          </div>
        </div>

        <nav className="flex gap-1 overflow-x-auto px-2 pb-3 lg:flex-col lg:overflow-visible lg:px-2">
          {NAV.map(({ to, label, icon: Icon, ...rest }) => (
            <NavLink
              key={to}
              to={to}
              {...rest}
              className={({ isActive }) =>
                cn(
                  "flex shrink-0 items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                  isActive
                    ? "bg-secondary font-medium text-secondary-foreground"
                    : "text-muted-foreground hover:bg-accent hover:text-accent-foreground",
                )
              }
            >
              <Icon className="size-4 shrink-0" aria-hidden />
              <span className="whitespace-nowrap">{label}</span>
            </NavLink>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between gap-4 border-b border-border px-4 py-3 lg:px-6">
          <KycBanner />
          <div className="flex shrink-0 items-center gap-3">
            <span className="hidden text-sm text-muted-foreground sm:inline">{user?.email}</span>
            <Button variant="ghost" size="sm" onClick={() => void logout()}>
              <LogOut aria-hidden />
              <span className="hidden sm:inline">Déconnexion</span>
            </Button>
          </div>
        </header>

        <main className="min-w-0 flex-1 px-4 py-5 lg:px-6 lg:py-6">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

/** Rappelle l'état KYC quand il bloque réellement une capacité. */
function KycBanner() {
  const user = useAuth((s) => s.user)
  if (!user || user.kyc_status === "APPROVED") return null

  const label: Record<string, string> = {
    NOT_STARTED: "Vérification d'identité non commencée",
    PENDING: "Vérification d'identité en attente",
    UNDER_REVIEW: "Vérification d'identité en cours d'examen",
    REJECTED: "Vérification d'identité refusée",
  }

  return (
    <div className="flex min-w-0 items-center gap-2">
      <Badge variant={user.kyc_status === "REJECTED" ? "loss" : "warning"}>
        {label[user.kyc_status] ?? user.kyc_status}
      </Badge>
      <span className="hidden truncate text-xs text-muted-foreground md:inline">
        Trading réel et retraits indisponibles tant que l'identité n'est pas validée.
      </span>
    </div>
  )
}
