import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/**
 * Formatage monétaire. Aucune valeur par défaut inventée : si le montant est
 * absent, on retourne le tiret cadratin plutôt qu'un zéro trompeur.
 */
export function formatMoney(
  value: number | string | null | undefined,
  currency = "USD",
  locale = "fr-FR",
): string {
  if (value === null || value === undefined || value === "") return "—"
  const n = typeof value === "string" ? Number(value) : value
  if (!Number.isFinite(n)) return "—"
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n)
}

export function formatPercent(
  value: number | string | null | undefined,
  locale = "fr-FR",
  digits = 2,
): string {
  if (value === null || value === undefined || value === "") return "—"
  const n = typeof value === "string" ? Number(value) : value
  if (!Number.isFinite(n)) return "—"
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n / 100)
}

export function formatQuantity(
  value: number | string | null | undefined,
  locale = "fr-FR",
  digits = 8,
): string {
  if (value === null || value === undefined || value === "") return "—"
  const n = typeof value === "string" ? Number(value) : value
  if (!Number.isFinite(n)) return "—"
  return new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(n)
}

/** Signe d'une variation, pour choisir la couleur sémantique gain/perte/plat. */
export function signOf(value: number | string | null | undefined): "gain" | "loss" | "flat" {
  if (value === null || value === undefined || value === "") return "flat"
  const n = typeof value === "string" ? Number(value) : value
  if (!Number.isFinite(n) || n === 0) return "flat"
  return n > 0 ? "gain" : "loss"
}
