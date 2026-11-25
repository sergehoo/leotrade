import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  AlertTriangle,
  CircleCheck,
  KeyRound,
  Plug,
  Plus,
  Star,
  Trash2,
  Pencil,
  Zap,
} from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import {
  BROKER_LABELS,
  SECRET_LABELS,
  createBroker,
  deleteBroker,
  fetchBrokerHealth,
  listBrokers,
  setDefaultBroker,
  testBrokerConnection,
  updateBroker,
  type BrokerAccount,
  type BrokerAccountPayload,
  type BrokerHealth,
  type CircuitState,
} from "@/api/brokers"
import { toApiError } from "@/api/client"
import { Alert } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Spinner } from "@/components/ui/spinner"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { useAuth } from "@/stores/auth"
import type { ApiError } from "@/types/api"
import BrokerFormDialog from "./BrokerFormDialog"

const BROKERS_KEY = ["brokers"] as const
const HEALTH_KEY = ["brokers", "health"] as const

export default function BrokersPage() {
  const queryClient = useQueryClient()
  const user = useAuth((s) => s.user)
  const canTradeLive = user?.capabilities.can_trade_live ?? false

  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<BrokerAccount | null>(null)
  const [formError, setFormError] = useState<ApiError | null>(null)
  const [pendingDeletion, setPendingDeletion] = useState<BrokerAccount | null>(null)
  const [deleteError, setDeleteError] = useState<ApiError | null>(null)

  const accounts = useQuery({ queryKey: BROKERS_KEY, queryFn: listBrokers })
  const health = useQuery({
    queryKey: HEALTH_KEY,
    queryFn: fetchBrokerHealth,
    // L'état du circuit breaker et la dernière synchro bougent sans action
    // de l'utilisateur : une valeur périmée masquerait une panne en cours.
    refetchInterval: 30_000,
  })

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: BROKERS_KEY })
    void queryClient.invalidateQueries({ queryKey: HEALTH_KEY })
    void queryClient.invalidateQueries({ queryKey: ["app-context"] })
  }

  const save = useMutation({
    mutationFn: (payload: BrokerAccountPayload) =>
      editing ? updateBroker(editing.id, payload) : createBroker(payload),
    onSuccess: (account) => {
      invalidate()
      setFormOpen(false)
      setFormError(null)
      toast.success(editing ? `« ${account.name} » mis à jour.` : `« ${account.name} » créé.`)
    },
    onError: (error) => setFormError(toApiError(error)),
  })

  const promote = useMutation({
    mutationFn: setDefaultBroker,
    onSuccess: (account) => {
      invalidate()
      toast.success(`« ${account.name} » est le compte par défaut.`)
    },
    onError: (error) => toast.error(toApiError(error).message),
  })

  const testConnection = useMutation({
    mutationFn: testBrokerConnection,
    onSuccess: (result) => {
      invalidate()
      toast.success(`Connexion établie avec « ${result.account.name} ».`)
    },
    onError: (error) => {
      invalidate()
      const parsed = toApiError(error)
      toast.error(
        parsed.code === "MISSING_SECRETS"
          ? "Identifiants incomplets : renseigne-les avant de tester."
          : `Connexion refusée : ${parsed.message}`,
      )
    },
  })

  const remove = useMutation({
    mutationFn: deleteBroker,
    onSuccess: () => {
      invalidate()
      setPendingDeletion(null)
      setDeleteError(null)
      toast.success("Compte broker supprimé.")
    },
    onError: (error) => setDeleteError(toApiError(error)),
  })

  const healthById = new Map<number, BrokerHealth>(
    (health.data?.results ?? []).map((row) => [row.id, row]),
  )

  function openCreate() {
    setEditing(null)
    setFormError(null)
    setFormOpen(true)
  }

  function openEdit(account: BrokerAccount) {
    setEditing(account)
    setFormError(null)
    setFormOpen(true)
  }

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold tracking-tight">Brokers</h1>
          <p className="text-sm text-muted-foreground">
            Comptes d'exécution. Les identifiants sont chiffrés au repos et ne sont
            jamais réaffichés.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus aria-hidden />
          Ajouter un compte
        </Button>
      </header>

      {!canTradeLive ? (
        <Alert variant="info" title="Mode Live verrouillé">
          Ton KYC n'est pas encore approuvé : les comptes restent limités au mode
          Paper. Le trading en simulation fonctionne sans restriction.
        </Alert>
      ) : null}

      {accounts.isPending ? (
        <TableSkeleton rows={3} columns={4} />
      ) : accounts.isError ? (
        <ErrorState error={toApiError(accounts.error)} onRetry={() => void accounts.refetch()} />
      ) : accounts.data.results.length === 0 ? (
        <EmptyState
          icon={Plug}
          title="Aucun compte broker"
          description={
            <>
              Un compte broker est le prérequis de toute exécution, y compris en
              simulation. Ajoute ton premier compte pour commencer.
            </>
          }
          action={
            <Button onClick={openCreate}>
              <Plus aria-hidden />
              Ajouter un compte
            </Button>
          }
        />
      ) : (
        <ul className="grid gap-3">
          {accounts.data.results.map((account) => (
            <li key={account.id}>
              <BrokerCard
                account={account}
                health={healthById.get(account.id)}
                busy={
                  (testConnection.isPending && testConnection.variables === account.id) ||
                  (promote.isPending && promote.variables === account.id)
                }
                onEdit={() => openEdit(account)}
                onPromote={() => promote.mutate(account.id)}
                onTest={() => testConnection.mutate(account.id)}
                onDelete={() => {
                  setDeleteError(null)
                  setPendingDeletion(account)
                }}
              />
            </li>
          ))}
        </ul>
      )}

      <BrokerFormDialog
        open={formOpen}
        onOpenChange={(open) => {
          setFormOpen(open)
          if (!open) setFormError(null)
        }}
        account={editing}
        canTradeLive={canTradeLive}
        pending={save.isPending}
        error={formError}
        onSubmit={(payload) => save.mutate(payload)}
      />

      <DeleteDialog
        account={pendingDeletion}
        error={deleteError}
        pending={remove.isPending}
        onCancel={() => {
          setPendingDeletion(null)
          setDeleteError(null)
        }}
        onConfirm={(account) => remove.mutate(account.id)}
      />
    </div>
  )
}

// ── Carte d'un compte ────────────────────────────────────────────────────────

function BrokerCard({
  account,
  health,
  busy,
  onEdit,
  onPromote,
  onTest,
  onDelete,
}: {
  account: BrokerAccount
  health?: BrokerHealth
  busy: boolean
  onEdit: () => void
  onPromote: () => void
  onTest: () => void
  onDelete: () => void
}) {
  const circuit = health?.circuit_state
  const lastSync = health?.last_sync_at

  return (
    <Card>
      <CardContent className="flex flex-col gap-4 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="truncate font-medium">{account.name}</span>
              {account.is_default ? (
                <Badge variant="info">
                  <Star className="size-3" aria-hidden />
                  Par défaut
                </Badge>
              ) : null}
              <ModeBadge mode={account.mode} />
              {!account.is_active ? <Badge variant="outline">Inactif</Badge> : null}
            </div>
            <p className="text-sm text-muted-foreground">
              {BROKER_LABELS[account.broker]}
              {account.login ? ` · ${account.login}` : ""}
              {account.server ? ` · ${account.server}` : ""}
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-1.5">
            {!account.is_default ? (
              <Button variant="ghost" size="sm" onClick={onPromote} disabled={busy}>
                <Star aria-hidden />
                Par défaut
              </Button>
            ) : null}
            <Button variant="outline" size="sm" onClick={onTest} disabled={busy}>
              {busy ? <Spinner /> : <Zap aria-hidden />}
              Tester
            </Button>
            <Button variant="ghost" size="sm" onClick={onEdit}>
              <Pencil aria-hidden />
              <span className="sr-only sm:not-sr-only">Modifier</span>
            </Button>
            <Button
              variant="ghost"
              size="sm"
              onClick={onDelete}
              className="text-muted-foreground hover:text-destructive"
            >
              <Trash2 aria-hidden />
              <span className="sr-only">Supprimer</span>
            </Button>
          </div>
        </div>

        {account.missing_secrets.length > 0 ? (
          <Alert variant="warning" title="Identifiants incomplets">
            {account.missing_secrets.map((secret) => SECRET_LABELS[secret]).join(", ")} —
            aucune connexion réelle n'aboutira tant que ces champs sont vides.
          </Alert>
        ) : null}

        {account.status === "ERROR" && account.last_connection_error ? (
          <Alert variant="danger" title="Dernière connexion en échec">
            {account.last_connection_error}
          </Alert>
        ) : null}

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 text-sm sm:grid-cols-4">
          <Metric label="Connexion">
            {account.last_connection_status ? (
              <span className="inline-flex items-center gap-1 text-gain">
                <CircleCheck className="size-3.5" aria-hidden />
                Établie
              </span>
            ) : (
              <span className="text-muted-foreground">Jamais vérifiée</span>
            )}
          </Metric>
          <Metric label="Dernier test">{formatDateTime(account.last_connected_at)}</Metric>
          <Metric label="Circuit">
            {circuit ? <CircuitBadge state={circuit} /> : <Muted />}
          </Metric>
          <Metric label="Dernière synchro">{formatDateTime(lastSync ?? null)}</Metric>
        </dl>
      </CardContent>
    </Card>
  )
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="space-y-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="tabular">{children}</dd>
    </div>
  )
}

function Muted() {
  return <span className="text-muted-foreground">—</span>
}

function ModeBadge({ mode }: { mode: "PAPER" | "LIVE" }) {
  // Le mode Live engage de l'argent réel : il doit se distinguer d'un coup
  // d'œil, sans reposer sur la seule lecture du mot.
  return mode === "LIVE" ? (
    <Badge variant="warning">
      <AlertTriangle className="size-3" aria-hidden />
      Live
    </Badge>
  ) : (
    <Badge variant="outline">Paper</Badge>
  )
}

function CircuitBadge({ state }: { state: CircuitState }) {
  const spec: Record<CircuitState, { label: string; variant: "gain" | "loss" | "warning" | "outline" }> = {
    CLOSED: { label: "Fermé", variant: "gain" },
    HALF_OPEN: { label: "Semi-ouvert", variant: "warning" },
    OPEN: { label: "Ouvert", variant: "loss" },
    UNAVAILABLE: { label: "Indisponible", variant: "outline" },
  }
  const { label, variant } = spec[state]
  return <Badge variant={variant}>{label}</Badge>
}

function formatDateTime(value: string | null) {
  if (!value) return <Muted />
  return new Date(value).toLocaleString("fr-FR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  })
}

// ── Suppression ──────────────────────────────────────────────────────────────

function DeleteDialog({
  account,
  error,
  pending,
  onCancel,
  onConfirm,
}: {
  account: BrokerAccount | null
  error: ApiError | null
  pending: boolean
  onCancel: () => void
  onConfirm: (account: BrokerAccount) => void
}) {
  return (
    <Dialog open={account !== null} onOpenChange={(open) => (open ? null : onCancel())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Supprimer « {account?.name} » ?</DialogTitle>
          <DialogDescription>
            Cette action est irréversible. Les identifiants chiffrés sont détruits
            avec le compte.
          </DialogDescription>
        </DialogHeader>

        {error ? (
          <Alert
            variant="warning"
            title={
              error.code === "LINKED_PORTFOLIOS" || error.code === "OPEN_POSITIONS"
                ? "Suppression refusée"
                : undefined
            }
          >
            {error.message}
          </Alert>
        ) : null}

        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={pending}>
            Annuler
          </Button>
          <Button
            variant="destructive"
            onClick={() => account && onConfirm(account)}
            disabled={pending || !account}
          >
            {pending ? <Spinner /> : <KeyRound aria-hidden />}
            Supprimer définitivement
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
