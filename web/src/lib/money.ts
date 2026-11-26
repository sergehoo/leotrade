/**
 * Formatage des montants.
 *
 * Les valeurs arrivent en chaîne depuis l'API : le backend calcule en
 * `Decimal`, et JavaScript n'a pas d'équivalent natif. On ne les convertit
 * en `number` qu'ici, au tout dernier moment, et jamais pour un calcul.
 */
export function formatMoney(raw: string | null | undefined, currency = "USD"): string {
  if (raw === null || raw === undefined || raw === "") return "—"
  const value = Number(raw)
  if (!Number.isFinite(value)) return "—"
  return new Intl.NumberFormat("fr-FR", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

export function formatPercent(raw: string | number | null | undefined, digits = 2): string {
  if (raw === null || raw === undefined || raw === "") return "—"
  const value = Number(raw)
  if (!Number.isFinite(value)) return "—"
  return `${new Intl.NumberFormat("fr-FR", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value)} %`
}

export function formatQuantity(raw: string | null | undefined): string {
  if (!raw) return "—"
  const value = Number(raw)
  if (!Number.isFinite(value)) return "—"
  return new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 8 }).format(value)
}

export type MoveSign = "gain" | "loss" | "flat"

/** Signe d'une variation, pour choisir la couleur sémantique. */
export function signOf(raw: string | number | null | undefined): MoveSign {
  const value = Number(raw ?? "")
  if (!Number.isFinite(value) || value === 0) return "flat"
  return value > 0 ? "gain" : "loss"
}

export function signClass(sign: MoveSign): string {
  return sign === "gain" ? "text-gain" : sign === "loss" ? "text-loss" : "text-muted-foreground"
}
