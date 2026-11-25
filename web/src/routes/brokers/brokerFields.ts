import type { BrokerKind, SecretField } from "@/api/brokers"

/**
 * Spécification des champs par broker.
 *
 * Miroir exact de `BrokerAccount.clean()` et de `REQUIRED_SECRETS`
 * (backend/brokers/). Le serveur reste l'autorité — ce tableau sert
 * seulement à n'afficher que les champs pertinents et à signaler une
 * omission avant l'aller-retour réseau.
 */
export interface BrokerFieldSpec {
  /** Champs de configuration affichés pour ce broker. */
  fields: Array<{
    name: "login" | "server" | "terminal_path" | "deriv_app_id" | "deriv_currency" | "deriv_account_type"
    label: string
    required: boolean
    placeholder?: string
    hint?: string
  }>
  /** Secrets sans lesquels aucune connexion réelle n'aboutit. */
  requiredSecrets: SecretField[]
  /** Secrets facultatifs mais acceptés. */
  optionalSecrets: SecretField[]
}

export const BROKER_FIELDS: Record<BrokerKind, BrokerFieldSpec> = {
  BINANCE: {
    fields: [],
    requiredSecrets: ["api_key", "api_secret"],
    optionalSecrets: [],
  },
  MT5: {
    fields: [
      { name: "login", label: "Login", required: true, placeholder: "12345678" },
      {
        name: "server",
        label: "Serveur",
        required: true,
        placeholder: "ICMarketsSC-Demo",
        hint: "Nom exact du serveur tel qu'affiché dans le terminal MetaTrader.",
      },
      {
        name: "terminal_path",
        label: "Chemin du terminal",
        required: false,
        placeholder: "C:\\Program Files\\MetaTrader 5\\terminal64.exe",
      },
    ],
    requiredSecrets: ["password"],
    optionalSecrets: [],
  },
  DERIV: {
    fields: [
      { name: "deriv_app_id", label: "App ID", required: true, placeholder: "1089" },
      { name: "deriv_currency", label: "Devise", required: true, placeholder: "USD" },
      {
        name: "deriv_account_type",
        label: "Type de compte",
        required: false,
        placeholder: "financial",
      },
    ],
    requiredSecrets: ["deriv_token"],
    optionalSecrets: [],
  },
}

export function secretsFor(broker: BrokerKind): SecretField[] {
  const spec = BROKER_FIELDS[broker]
  return [...spec.requiredSecrets, ...spec.optionalSecrets]
}
