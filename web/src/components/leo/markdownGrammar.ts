/**
 * La grammaire de Leo — partie indépendante du rendu.
 *
 * Contrat partagé avec `mobile/lib/shared/widgets/markdown.dart` et avec
 * `ASSISTANT_SYSTEM_PROMPT` côté serveur. Voir `docs/LEO_MARKDOWN.md`.
 *
 * Ce module ne contient que des décisions — quels chemins sont
 * navigables, quelles icônes existent, quelle adresse d'image est
 * acceptable. Le rendu lui-même vit dans `Markdown.tsx`.
 */

/**
 * Chemins vers lesquels Leo peut pointer.
 *
 * Ceux de React ET de Flutter, à l'exclusion de la route de Leo
 * lui-même : un lien de Leo vers Leo n'a pas de sens.
 *
 * Un chemin absent d'ici est rendu en TEXTE, jamais en lien ni en
 * bouton. La règle anti-hallucination du prompt est ainsi appliquée à
 * l'affichage, et pas seulement à la consigne : si le modèle invente une
 * page, l'interface ne fabrique pas un bouton mort pour autant.
 */
export const LEO_ROUTES = [
  "/",
  "/portefeuille",
  "/marches",
  "/risque",
  "/portefeuille-electronique",
  "/brokers",
] as const

/** `/marches/<id>` — le détail d'un instrument prend un identifiant. */
const ASSET_DETAIL = /^\/marches\/\d+$/

/** Vrai si ce chemin interne existe réellement dans les deux clients. */
export function isKnownRoute(path: string): boolean {
  const clean = path.split(/[?#]/)[0]
  const normalised =
    clean.length > 1 && clean.endsWith("/") ? clean.slice(0, -1) : clean
  return (
    (LEO_ROUTES as readonly string[]).includes(normalised) ||
    ASSET_DETAIL.test(normalised)
  )
}

/** Icônes que Leo peut nommer. Un nom absent reste du texte. */
export const LEO_ICONS = [
  "gain",
  "perte",
  "neutre",
  "alerte",
  "danger",
  "info",
  "idee",
  "risque",
  "verrou",
  "horloge",
  "cible",
  "graphique",
  "portefeuille",
  "marche",
  "broker",
  "ia",
  "valide",
  "refus",
] as const

export type LeoIcon = (typeof LEO_ICONS)[number]

export function isKnownIcon(name: string): name is LeoIcon {
  return (LEO_ICONS as readonly string[]).includes(name)
}

export type CalloutKind = "NOTE" | "TIP" | "IMPORTANT" | "WARNING" | "CAUTION"

export const CALLOUT_KINDS: CalloutKind[] = [
  "NOTE",
  "TIP",
  "IMPORTANT",
  "WARNING",
  "CAUTION",
]

/**
 * Une image n'est chargée que depuis l'origine de l'API.
 *
 * Une image distante dans une réponse de modèle est un pixel traceur :
 * son chargement révèle l'adresse IP du lecteur et le moment de la
 * lecture, et l'URL peut encoder ce qu'on veut exfiltrer. Le web étant
 * servi par la même origine que l'API, « sur l'origine » se dit ici
 * « chemin relatif ».
 */
export function isSameOriginImage(url: string): boolean {
  if (!url.startsWith("/") || url.startsWith("//")) return false
  return true
}

/** Schémas qu'on accepte de rendre cliquables. */
export function isWebLink(href: string): boolean {
  return /^https?:\/\//i.test(href)
}
