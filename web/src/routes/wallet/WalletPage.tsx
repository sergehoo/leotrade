import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { ArrowDownToLine, Lock, ScrollText, Wallet as WalletIcon } from "lucide-react"
import { useState } from "react"
import { toast } from "sonner"

import { toApiError } from "@/api/client"
import {
  LEDGER_LABELS,
  WITHDRAWAL_LABELS,
  fetchWalletSummary,
  listLedger,
  listWithdrawals,
  requestWithdrawal,
  type LedgerEntry,
  type WalletSummary,
  type WithdrawalRequest,
} from "@/api/wallet"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"
import { formatMoney } from "@/lib/money"
import { useAuth } from "@/stores/auth"
import type { ApiError } from "@/types/api"

export default function WalletPage() {
  const queryClient = useQueryClient()
  const [withdrawOpen, setWithdrawOpen] = useState(false)

  const summary = useQuery({ queryKey: ["wallet-summary"], queryFn: fetchWalletSummary })
  const ledger = useQuery({ queryKey: ["wallet-ledger"], queryFn: listLedger })
  const withdrawals = useQuery({
    queryKey: ["wallet-withdrawals"],
    queryFn: listWithdrawals,
  })

  function invalidate() {
    void queryClient.invalidateQueries({ queryKey: ["wallet-summary"] })
    void queryClient.invalidateQueries({ queryKey: ["wallet-ledger"] })
    void queryClient.invalidateQueries({ queryKey: ["wallet-withdrawals"] })
  }

  if (summary.isPending) return <TableSkeleton rows={4} columns={4} />
  if (summary.isError) {
    return (
      <ErrorState error={toApiError(summary.error)} onRetry={() => void summary.refetch()} />
    )
  }

  const data = summary.data

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="space-y-1">
          <h1 className="text-lg font-semibold tracking-tight">
            Portefeuille électronique
          </h1>
          <p className="text-sm text-muted-foreground">
            Argent réel. Distinct du capital de tes portefeuilles de trading.
          </p>
        </div>
        {data.has_wallet ? (
          <Button variant="outline" onClick={() => setWithdrawOpen(true)}>
            <ArrowDownToLine aria-hidden />
            Demander un retrait
          </Button>
        ) : null}
      </header>

      {!data.has_wallet ? (
        <EmptyState
          icon={WalletIcon}
          title="Aucun portefeuille électronique"
          description={
            <>
              Ton portefeuille sera créé automatiquement au premier
              approvisionnement.
            </>
          }
        />
      ) : (
        <>
          {!data.is_reconciled ? (
            <Alert variant="warning" title="Une partie de ce solde n'est pas tracée">
              {formatMoney(data.unexplained_amount, data.currency ?? "USD")}{" "}
              n'apparaissent pas dans l'historique des mouvements. Ce montant
              existe sur ton solde mais aucune opération ne l'explique.
              Signale-le au support avant d'engager ces fonds.
            </Alert>
          ) : null}

          <BalanceGrid summary={data} />

          <WithdrawalsSection
            query={withdrawals}
            currency={data.currency ?? "USD"}
          />

          <LedgerSection query={ledger} currency={data.currency ?? "USD"} />
        </>
      )}

      <WithdrawDialog
        open={withdrawOpen}
        summary={data}
        onClose={() => setWithdrawOpen(false)}
        onDone={() => {
          invalidate()
          setWithdrawOpen(false)
        }}
      />
    </div>
  )
}

/**
 * Soldes.
 *
 * L'argent réel et le capital de trading sont séparés visuellement et
 * nommés distinctement : ce sont deux réserves différentes, et les
 * additionner mentalement est l'erreur qu'on veut rendre impossible.
 */
function BalanceGrid({ summary }: { summary: WalletSummary }) {
  const currency = summary.currency ?? "USD"

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric
          label="Disponible"
          value={formatMoney(summary.available_balance, currency)}
          hint="Mobilisable immédiatement"
        />
        <Metric
          label="Verrouillé"
          value={formatMoney(summary.locked_balance, currency)}
          hint={
            summary.pending_withdrawals_count > 0
              ? `${summary.pending_withdrawals_count} retrait(s) en attente`
              : "Aucun engagement en cours"
          }
          icon={Lock}
        />
        <Metric
          label="Total"
          value={formatMoney(summary.total_balance, currency)}
          hint="Disponible + verrouillé"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Metric
          label="Capital en simulation"
          value={formatMoney(summary.simulated_trading_capital, currency)}
          hint="N'atteint aucun marché — cet argent n'existe pas"
          muted
        />
        <Metric
          label="Capital engagé en réel"
          value={formatMoney(summary.live_trading_capital, currency)}
          hint="Portefeuilles branchés sur un broker réel"
        />
      </div>
    </div>
  )
}

function Metric({
  label,
  value,
  hint,
  icon: Icon,
  muted,
}: {
  label: string
  value: string
  hint?: string
  icon?: typeof Lock
  muted?: boolean
}) {
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          {Icon ? <Icon className="size-3.5" aria-hidden /> : null}
          {label}
        </p>
        <p
          className={
            muted
              ? "text-lg font-semibold tabular text-muted-foreground"
              : "text-lg font-semibold tabular"
          }
        >
          {value}
        </p>
        {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      </CardContent>
    </Card>
  )
}

function WithdrawalsSection({
  query,
  currency,
}: {
  query: ReturnType<typeof useQuery<{ results: WithdrawalRequest[] }>>
  currency: string
}) {
  if (query.isPending) return <TableSkeleton rows={2} columns={3} />
  if (query.isError) return <ErrorState error={toApiError(query.error)} />

  const rows = query.data?.results ?? []
  if (rows.length === 0) return null

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Demandes de retrait</h2>
      <ul className="grid gap-2">
        {rows.map((row) => (
          <li
            key={row.id}
            className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 text-sm"
          >
            <span className="tabular font-medium">
              {formatMoney(row.amount, row.currency || currency)}
            </span>
            <span className="text-xs text-muted-foreground">
              {row.destination_masked || row.destination_type}
            </span>
            <Badge variant={statusVariant(row.status)}>
              {WITHDRAWAL_LABELS[row.status] ?? row.status}
            </Badge>
            <span className="text-xs text-muted-foreground tabular">
              {new Date(row.created_at).toLocaleDateString("fr-FR")}
            </span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function statusVariant(status: WithdrawalRequest["status"]) {
  if (status === "PAID") return "gain" as const
  if (status === "REJECTED" || status === "FAILED") return "loss" as const
  if (status === "CANCELLED") return "outline" as const
  return "warning" as const
}

/**
 * Grand livre.
 *
 * C'est l'historique qui doit expliquer le solde. Chaque ligne porte le
 * solde avant et après : c'est ce qui permet de vérifier la chaîne plutôt
 * que de faire confiance à un total.
 */
function LedgerSection({
  query,
  currency,
}: {
  query: ReturnType<typeof useQuery<{ results: LedgerEntry[] }>>
  currency: string
}) {
  if (query.isPending) return <TableSkeleton rows={3} columns={4} />
  if (query.isError) return <ErrorState error={toApiError(query.error)} />

  const rows = query.data?.results ?? []

  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">Historique des mouvements</h2>
      {rows.length === 0 ? (
        <EmptyState
          icon={ScrollText}
          title="Aucun mouvement"
          description={
            <>
              Les crédits, débits et verrouillages apparaîtront ici, chacun
              avec le solde qu'il laisse derrière lui.
            </>
          }
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[40rem] text-sm">
            <thead className="border-b border-border bg-secondary/40 text-left text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Date</th>
                <th scope="col" className="px-3 py-2 font-medium">Type</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Montant</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Solde après</th>
                <th scope="col" className="px-3 py-2 font-medium">Libellé</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {rows.map((entry) => (
                <tr key={entry.id}>
                  <td className="px-3 py-2 text-xs text-muted-foreground tabular">
                    {new Date(entry.created_at).toLocaleString("fr-FR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </td>
                  <td className="px-3 py-2">
                    <Badge variant="outline">
                      {LEDGER_LABELS[entry.entry_type] ?? entry.entry_type}
                    </Badge>
                  </td>
                  <td className="px-3 py-2 text-right tabular">
                    {formatMoney(entry.amount, entry.currency || currency)}
                  </td>
                  <td className="px-3 py-2 text-right tabular text-muted-foreground">
                    {formatMoney(entry.balance_after, entry.currency || currency)}
                  </td>
                  <td className="px-3 py-2 text-xs text-muted-foreground">
                    {entry.description || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}

/**
 * Demande de retrait.
 *
 * La fiche énonce ce qui va se passer : les fonds sont verrouillés, pas
 * envoyés, et une revue humaine décide. Laisser croire qu'un retrait est
 * immédiat serait une promesse que le produit ne tient pas.
 */
function WithdrawDialog({
  open,
  summary,
  onClose,
  onDone,
}: {
  open: boolean
  summary: WalletSummary
  onClose: () => void
  onDone: () => void
}) {
  const user = useAuth((s) => s.user)
  const [amount, setAmount] = useState("")
  const [destination, setDestination] = useState("")
  const [error, setError] = useState<ApiError | null>(null)

  const canWithdraw = user?.capabilities.can_withdraw ?? false
  const currency = summary.currency ?? "USD"

  const submit = useMutation({
    mutationFn: () =>
      requestWithdrawal({
        amount,
        destination_type: "BANK",
        destination_masked: destination.trim() || undefined,
      }),
    onSuccess: () => {
      toast.success("Demande enregistrée. Les fonds sont verrouillés en attente de revue.")
      setAmount("")
      setDestination("")
      setError(null)
      onDone()
    },
    onError: (raw) => setError(toApiError(raw)),
  })

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? null : onClose())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Demander un retrait</DialogTitle>
          <DialogDescription>
            Les fonds sont verrouillés immédiatement, puis versés après revue.
            Rien n'est envoyé à ce stade.
          </DialogDescription>
        </DialogHeader>

        {!canWithdraw ? (
          <Alert variant="warning" title="Vérification d'identité requise">
            Les retraits sont bloqués tant que ton dossier KYC n'est pas
            approuvé.
          </Alert>
        ) : null}

        {error ? <Alert variant="danger">{error.message}</Alert> : null}

        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault()
            setError(null)
            submit.mutate()
          }}
        >
          <div className="grid gap-1.5">
            <Label htmlFor="withdraw-amount">Montant ({currency})</Label>
            <Input
              id="withdraw-amount"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              inputMode="decimal"
              placeholder="100.00"
              required
              aria-invalid={!!error?.fields?.amount}
            />
            <p className="text-xs text-muted-foreground">
              Disponible : {formatMoney(summary.available_balance, currency)}. Entre
              5 et 100 000 par opération.
            </p>
            {error?.fields?.amount ? (
              <p className="text-xs text-destructive" role="alert">
                {error.fields.amount.join(" ")}
              </p>
            ) : null}
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="withdraw-destination">
              Destination <span className="font-normal text-muted-foreground">(facultatif)</span>
            </Label>
            <Input
              id="withdraw-destination"
              value={destination}
              onChange={(event) => setDestination(event.target.value)}
              placeholder="•••• 4242"
              aria-invalid={!!error?.fields?.destination_masked}
            />
            <p className="text-xs text-muted-foreground">
              Indique seulement les derniers chiffres — un numéro complet sera
              refusé.
            </p>
            {error?.fields?.destination_masked ? (
              <p className="text-xs text-destructive" role="alert">
                {error.fields.destination_masked.join(" ")}
              </p>
            ) : null}
          </div>

          <DialogFooter>
            <Button type="button" variant="outline" onClick={onClose} disabled={submit.isPending}>
              Annuler
            </Button>
            <Button type="submit" disabled={submit.isPending || !canWithdraw || !amount}>
              {submit.isPending ? <Spinner /> : null}
              Demander le retrait
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
