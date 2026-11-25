import { useEffect, useMemo, useState } from "react"

import {
  BROKER_LABELS,
  SECRET_LABELS,
  type BrokerAccount,
  type BrokerAccountPayload,
  type BrokerKind,
  type SecretField,
  type TradingMode,
} from "@/api/brokers"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Spinner } from "@/components/ui/spinner"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import type { ApiError } from "@/types/api"
import { BROKER_FIELDS, secretsFor } from "./brokerFields"

const BROKERS: BrokerKind[] = ["DERIV", "MT5", "BINANCE"]

type FormState = {
  name: string
  broker: BrokerKind
  mode: TradingMode
  login: string
  server: string
  terminal_path: string
  deriv_app_id: string
  deriv_currency: string
  deriv_account_type: string
  is_active: boolean
  is_default: boolean
  notes: string
} & Record<SecretField, string>

function initialState(account: BrokerAccount | null): FormState {
  return {
    name: account?.name ?? "",
    broker: account?.broker ?? "DERIV",
    mode: account?.mode ?? "PAPER",
    login: account?.login ?? "",
    server: account?.server ?? "",
    terminal_path: account?.terminal_path ?? "",
    deriv_app_id: account?.deriv_app_id ?? "",
    deriv_currency: account?.deriv_currency ?? "USD",
    deriv_account_type: account?.deriv_account_type ?? "",
    is_active: account?.is_active ?? true,
    is_default: account?.is_default ?? false,
    notes: account?.notes ?? "",
    api_key: "",
    api_secret: "",
    password: "",
    deriv_token: "",
  }
}

export default function BrokerFormDialog({
  open,
  onOpenChange,
  account,
  canTradeLive,
  pending,
  error,
  onSubmit,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** null = création. */
  account: BrokerAccount | null
  /** KYC approuvé ? Le serveur tranche, mais l'UI doit l'expliquer avant. */
  canTradeLive: boolean
  pending: boolean
  error: ApiError | null
  onSubmit: (payload: BrokerAccountPayload) => void
}) {
  const [form, setForm] = useState<FormState>(() => initialState(account))
  const isEdit = account !== null

  // Repartir de l'état du compte à chaque ouverture : sans cela, un champ
  // de secret saisi puis abandonné serait réenvoyé à l'ouverture suivante.
  useEffect(() => {
    if (open) setForm(initialState(account))
  }, [open, account])

  const spec = BROKER_FIELDS[form.broker]
  const secrets = useMemo(() => secretsFor(form.broker), [form.broker])
  const fieldErrors = error?.fields ?? {}

  function set<K extends keyof FormState>(key: K, value: FormState[K]) {
    setForm((previous) => ({ ...previous, [key]: value }))
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault()

    const payload: BrokerAccountPayload = {
      name: form.name.trim(),
      broker: form.broker,
      mode: form.mode,
      is_active: form.is_active,
      is_default: form.is_default,
      notes: form.notes.trim(),
    }

    for (const field of spec.fields) {
      payload[field.name] = form[field.name].trim()
    }
    // Un secret vide n'est jamais transmis : le serveur interprète l'absence
    // comme « conserver la valeur existante », ce qui permet de modifier un
    // compte sans ressaisir ses clés.
    for (const secret of secrets) {
      if (form[secret]) payload[secret] = form[secret]
    }

    onSubmit(payload)
  }

  const liveBlocked = form.mode === "LIVE" && !canTradeLive

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? `Modifier « ${account.name} »` : "Nouveau compte broker"}</DialogTitle>
          <DialogDescription>
            {isEdit
              ? "Laisse un champ de secret vide pour conserver la valeur chiffrée existante."
              : "Les identifiants sont chiffrés à l'enregistrement et ne sont jamais réaffichés."}
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit} className="flex min-h-0 flex-col gap-4">
          <div className="-mr-1 flex min-h-0 flex-col gap-4 overflow-y-auto pr-1">
            {error && !error.fields ? (
              <Alert variant="danger">{error.message}</Alert>
            ) : null}

            <div className="grid gap-1.5">
              <Label htmlFor="broker-name">Nom</Label>
              <Input
                id="broker-name"
                value={form.name}
                onChange={(e) => set("name", e.target.value)}
                placeholder="Deriv principal"
                required
                autoFocus
                aria-invalid={!!fieldErrors.name}
              />
              <FieldError messages={fieldErrors.name} />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div className="grid gap-1.5">
                <Label htmlFor="broker-kind">Broker</Label>
                <Select
                  value={form.broker}
                  onValueChange={(value) => set("broker", value as BrokerKind)}
                  disabled={isEdit}
                >
                  <SelectTrigger id="broker-kind">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {BROKERS.map((kind) => (
                      <SelectItem key={kind} value={kind}>
                        {BROKER_LABELS[kind]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {isEdit ? (
                  <p className="text-xs text-muted-foreground">
                    Le broker n'est pas modifiable : crée un autre compte pour en changer.
                  </p>
                ) : null}
              </div>

              <div className="grid gap-1.5">
                <Label htmlFor="broker-mode">Mode</Label>
                <Select value={form.mode} onValueChange={(value) => set("mode", value as TradingMode)}>
                  <SelectTrigger id="broker-mode">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="PAPER">Paper — simulation</SelectItem>
                    <SelectItem value="LIVE">Live — argent réel</SelectItem>
                  </SelectContent>
                </Select>
                <FieldError messages={fieldErrors.mode} />
              </div>
            </div>

            {liveBlocked ? (
              <Alert variant="warning">
                Le mode Live exige un KYC approuvé. Tant que ton dossier n'est pas
                validé, l'enregistrement sera refusé — le mode Paper reste
                disponible sans restriction.
              </Alert>
            ) : null}

            {spec.fields.length > 0 ? (
              <div className="grid gap-4 sm:grid-cols-2">
                {spec.fields.map((field) => (
                  <div key={field.name} className="grid gap-1.5">
                    <Label htmlFor={`broker-${field.name}`}>
                      {field.label}
                      {field.required ? null : (
                        <span className="ml-1 font-normal text-muted-foreground">(facultatif)</span>
                      )}
                    </Label>
                    <Input
                      id={`broker-${field.name}`}
                      value={form[field.name]}
                      onChange={(e) => set(field.name, e.target.value)}
                      placeholder={field.placeholder}
                      required={field.required}
                      aria-invalid={!!fieldErrors[field.name]}
                    />
                    {field.hint ? (
                      <p className="text-xs text-muted-foreground">{field.hint}</p>
                    ) : null}
                    <FieldError messages={fieldErrors[field.name]} />
                  </div>
                ))}
              </div>
            ) : null}

            {secrets.length > 0 ? (
              <fieldset className="grid gap-3 rounded-md border border-border p-3">
                <legend className="px-1 text-xs font-medium text-muted-foreground">
                  Identifiants — chiffrés, jamais réaffichés
                </legend>
                {secrets.map((secret) => {
                  const state = account?.secrets[secret]
                  return (
                    <div key={secret} className="grid gap-1.5">
                      <Label htmlFor={`broker-${secret}`}>{SECRET_LABELS[secret]}</Label>
                      <Input
                        id={`broker-${secret}`}
                        type="password"
                        autoComplete="new-password"
                        value={form[secret]}
                        onChange={(e) => set(secret, e.target.value)}
                        placeholder={state?.configured ? "•••••••• (inchangé)" : ""}
                        required={!isEdit && spec.requiredSecrets.includes(secret)}
                        aria-invalid={!!fieldErrors[secret]}
                      />
                      {state?.configured ? (
                        <p className="text-xs text-muted-foreground">
                          Enregistré{" "}
                          {state.updated_at
                            ? `le ${new Date(state.updated_at).toLocaleDateString("fr-FR")}`
                            : null}
                          . Saisis une valeur pour le remplacer.
                        </p>
                      ) : null}
                      <FieldError messages={fieldErrors[secret]} />
                    </div>
                  )
                })}
              </fieldset>
            ) : null}

            <div className="grid gap-3">
              <ToggleRow
                id="broker-active"
                label="Compte actif"
                description="Un compte inactif n'est jamais sollicité par l'exécution."
                checked={form.is_active}
                onCheckedChange={(checked) => set("is_active", checked)}
              />
              <ToggleRow
                id="broker-default"
                label="Compte par défaut"
                description="Utilisé quand aucun compte n'est explicitement choisi."
                checked={form.is_default}
                onCheckedChange={(checked) => set("is_default", checked)}
              />
            </div>

            <div className="grid gap-1.5">
              <Label htmlFor="broker-notes">
                Notes <span className="font-normal text-muted-foreground">(facultatif)</span>
              </Label>
              <Textarea
                id="broker-notes"
                value={form.notes}
                onChange={(e) => set("notes", e.target.value)}
                rows={2}
              />
            </div>
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Annuler
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? <Spinner /> : null}
              {isEdit ? "Enregistrer" : "Créer le compte"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}

function FieldError({ messages }: { messages?: string[] }) {
  if (!messages?.length) return null
  return (
    <p className="text-xs text-destructive" role="alert">
      {messages.join(" ")}
    </p>
  )
}

function ToggleRow({
  id,
  label,
  description,
  checked,
  onCheckedChange,
}: {
  id: string
  label: string
  description: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
}) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-md border border-border p-3">
      <div className="space-y-0.5">
        <Label htmlFor={id} className="cursor-pointer">
          {label}
        </Label>
        <p className="text-xs text-muted-foreground">{description}</p>
      </div>
      <Switch id={id} checked={checked} onCheckedChange={onCheckedChange} />
    </div>
  )
}
