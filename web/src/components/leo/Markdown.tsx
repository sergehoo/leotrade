import {
  AlertTriangle,
  Bot,
  Briefcase,
  CandlestickChart,
  Check,
  CircleAlert,
  Clock,
  Info,
  Lightbulb,
  LineChart,
  Lock,
  Minus,
  Plug,
  ShieldAlert,
  Target,
  TrendingDown,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react"
import { Fragment, type ReactNode } from "react"
import { Link } from "react-router-dom"

import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import {
  isKnownIcon,
  isKnownRoute,
  isSameOriginImage,
  isWebLink,
  type CalloutKind,
  type LeoIcon,
} from "./markdownGrammar"

/**
 * Rendu de la grammaire de Leo, en éléments React.
 *
 * Contrat partagé, décrit une fois pour toutes dans
 * `docs/LEO_MARKDOWN.md` et rendu à l'identique par
 * `mobile/lib/shared/widgets/markdown.dart`.
 *
 * Volontairement sans `dangerouslySetInnerHTML` : le texte vient d'un
 * modèle de langage, qui peut restituer n'importe quoi — y compris du
 * contenu fourni par un tiers via un outil. Construire des éléments
 * React rend l'injection structurellement impossible plutôt que filtrée.
 *
 * Ce qui n'est pas reconnu est rendu tel quel, en texte : mieux vaut un
 * astérisque visible qu'un contenu avalé.
 */
export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("space-y-2 text-sm leading-relaxed", className)}>
      {renderBlocks(content)}
    </div>
  )
}

// ── Icônes ────────────────────────────────────────────────────────────────

const ICONS: Record<LeoIcon, LucideIcon> = {
  gain: TrendingUp,
  perte: TrendingDown,
  neutre: Minus,
  alerte: AlertTriangle,
  danger: CircleAlert,
  info: Info,
  idee: Lightbulb,
  risque: ShieldAlert,
  verrou: Lock,
  horloge: Clock,
  cible: Target,
  graphique: LineChart,
  portefeuille: Briefcase,
  marche: CandlestickChart,
  broker: Plug,
  ia: Bot,
  valide: Check,
  refus: X,
}

/** Le vert et le rouge gardent leur sens financier, jamais décoratif. */
const ICON_TONE: Partial<Record<LeoIcon, string>> = {
  gain: "text-gain",
  valide: "text-gain",
  perte: "text-loss",
  refus: "text-loss",
  danger: "text-loss",
  alerte: "text-warning",
  risque: "text-warning",
  info: "text-info",
}

const CALLOUT_VARIANT: Record<CalloutKind, "info" | "warning" | "danger" | "success"> = {
  NOTE: "info",
  TIP: "success",
  IMPORTANT: "info",
  WARNING: "warning",
  CAUTION: "danger",
}

const CALLOUT_TITLE: Record<CalloutKind, string> = {
  NOTE: "À noter",
  TIP: "Conseil",
  IMPORTANT: "Important",
  WARNING: "Attention",
  CAUTION: "Danger",
}

// ── Motifs ────────────────────────────────────────────────────────────────

const HEADING = /^(#{1,6})\s+(.*)$/
const BULLET = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/
const ORDERED = /^\s*\d+[.)]\s+/
const TASK = /^\[([ xX])\]\s+(.*)$/
const RULE = /^\s*(-{3,}|\*{3,}|_{3,})\s*$/
const CALLOUT = /^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$/
const QUOTE = /^>\s?(.*)$/
const IMAGE_LINE = /^!\[([^\]]*)\]\(([^)\s]+)\)$/
const HTML_COMMENT = /<!--[\s\S]*?-->/g

function renderBlocks(source: string): ReactNode[] {
  // Un commentaire n'a rien à faire à l'écran, et un commentaire à
  // moitié rendu est pire qu'un commentaire absent.
  const lines = source.replace(HTML_COMMENT, "").replace(/\r\n/g, "\n").split("\n")
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

    // ── Bloc de code ──
    if (line.trimStart().startsWith("```")) {
      const language = line.trim().slice(3).trim()
      const body: string[] = []
      index += 1
      while (index < lines.length && !lines[index].trimStart().startsWith("```")) {
        body.push(lines[index])
        index += 1
      }
      index += 1
      blocks.push(
        <pre
          key={key++}
          className="overflow-x-auto rounded-md border border-border bg-secondary/50 p-3 text-xs"
        >
          {language ? (
            <span className="mb-1 block text-[10px] uppercase tracking-wide text-muted-foreground">
              {language}
            </span>
          ) : null}
          <code>{body.join("\n")}</code>
        </pre>,
      )
      continue
    }

    // ── Encadré ──
    const callout = CALLOUT.exec(line)
    if (callout) {
      const kind = callout[1] as CalloutKind
      const body: string[] = callout[2].trim() ? [callout[2].trim()] : []
      index += 1
      while (index < lines.length && QUOTE.test(lines[index]) && !CALLOUT.test(lines[index])) {
        body.push(QUOTE.exec(lines[index])![1])
        index += 1
      }
      blocks.push(
        <Alert key={key++} variant={CALLOUT_VARIANT[kind]} title={CALLOUT_TITLE[kind]}>
          <div className="space-y-2">{renderBlocks(body.join("\n"))}</div>
        </Alert>,
      )
      continue
    }

    // ── Citation ──
    if (QUOTE.test(line)) {
      const body: string[] = []
      while (index < lines.length && QUOTE.test(lines[index]) && !CALLOUT.test(lines[index])) {
        body.push(QUOTE.exec(lines[index])![1])
        index += 1
      }
      blocks.push(
        <blockquote
          key={key++}
          className="border-l-2 border-primary/50 pl-3 text-muted-foreground"
        >
          <div className="space-y-2">{renderBlocks(body.join("\n"))}</div>
        </blockquote>,
      )
      continue
    }

    // ── Séparateur ──
    if (RULE.test(line)) {
      blocks.push(<hr key={key++} className="border-border" />)
      index += 1
      continue
    }

    // ── Tableau ──
    if (line.includes("|") && isTableSeparator(lines[index + 1])) {
      const header = splitRow(line)
      index += 2
      const rows: string[][] = []
      while (index < lines.length && lines[index].includes("|") && lines[index].trim()) {
        rows.push(splitRow(lines[index]))
        index += 1
      }
      blocks.push(<MarkdownTable key={key++} header={header} rows={rows} />)
      continue
    }

    // ── Titre ──
    const heading = HEADING.exec(line)
    if (heading) {
      const level = heading[1].length
      blocks.push(
        <p
          key={key++}
          className={cn(
            "font-semibold",
            level === 1 && "text-base",
            level === 2 && "text-[0.95rem]",
            level >= 3 && "text-sm",
            level >= 4 && "text-muted-foreground",
          )}
        >
          {renderInline(heading[2])}
        </p>,
      )
      index += 1
      continue
    }

    // ── Image seule sur sa ligne ──
    const image = IMAGE_LINE.exec(line.trim())
    if (image) {
      blocks.push(<MarkdownImage key={key++} alt={image[1]} src={image[2]} />)
      index += 1
      continue
    }

    // ── Liste ──
    if (BULLET.test(line)) {
      const start = index
      while (index < lines.length && (BULLET.test(lines[index]) || isContinuation(lines, index))) {
        index += 1
      }
      blocks.push(<Fragment key={key++}>{renderList(lines.slice(start, index))}</Fragment>)
      continue
    }

    // ── Paragraphe ──
    const paragraph: string[] = []
    while (index < lines.length && isParagraphLine(lines[index])) {
      paragraph.push(lines[index])
      index += 1
    }
    if (paragraph.length) {
      blocks.push(<p key={key++}>{renderInline(paragraph.join(" "))}</p>)
    } else {
      // Filet : une ligne qu'aucune règle n'a consommée ne doit pas
      // faire boucler le parseur indéfiniment.
      blocks.push(<p key={key++}>{renderInline(lines[index])}</p>)
      index += 1
    }
  }

  return blocks
}

function isParagraphLine(line: string): boolean {
  return (
    !!line.trim() &&
    !line.trimStart().startsWith("```") &&
    !HEADING.test(line) &&
    !BULLET.test(line) &&
    !QUOTE.test(line) &&
    !RULE.test(line) &&
    !IMAGE_LINE.test(line.trim())
  )
}

/** Ligne de continuation d'un élément de liste (indentée, non vide). */
function isContinuation(lines: string[], index: number): boolean {
  const line = lines[index]
  return !!line.trim() && /^\s{2,}\S/.test(line) && !BULLET.test(line)
}

// ── Listes imbriquées ─────────────────────────────────────────────────────

interface ListItem {
  content: string
  task: boolean | null
  children: string[]
}

function renderList(lines: string[]): ReactNode {
  const first = BULLET.exec(lines[0])!
  const baseIndent = first[1].length
  const ordered = ORDERED.test(lines[0])

  const items: ListItem[] = []
  for (const line of lines) {
    const match = BULLET.exec(line)
    if (match && match[1].length <= baseIndent) {
      const raw = match[3]
      const task = TASK.exec(raw)
      items.push({
        content: task ? task[2] : raw,
        task: task ? task[1].toLowerCase() === "x" : null,
        children: [],
      })
    } else if (items.length) {
      // Plus indenté : appartient à l'élément courant.
      items[items.length - 1].children.push(line.slice(baseIndent + 2))
    }
  }

  const rendered = items.map((item, index) => (
    <li key={index} className={item.task !== null ? "list-none -ml-5" : undefined}>
      {item.task !== null ? (
        <span className="mr-1.5 inline-block align-middle text-muted-foreground">
          {item.task ? "☑" : "☐"}
        </span>
      ) : null}
      {renderInline(item.content)}
      {item.children.some((child) => child.trim()) ? (
        <div className="mt-1">{renderBlocks(item.children.join("\n"))}</div>
      ) : null}
    </li>
  ))

  return ordered ? (
    <ol className="list-decimal space-y-1 pl-5">{rendered}</ol>
  ) : (
    <ul className="list-disc space-y-1 pl-5">{rendered}</ul>
  )
}

// ── Tableaux ──────────────────────────────────────────────────────────────

function isTableSeparator(line: string | undefined): boolean {
  if (!line) return false
  return /^\s*\|?[\s:|-]*$/.test(line) && line.includes("-") && line.includes("|")
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim())
}

function MarkdownTable({ header, rows }: { header: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto rounded-md border border-border">
      <table className="w-full text-xs">
        <thead className="border-b border-border bg-secondary/40 text-left text-muted-foreground">
          <tr>
            {header.map((cell, index) => (
              <th key={index} scope="col" className="px-2.5 py-1.5 font-medium">
                {renderInline(cell)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className="px-2.5 py-1.5 tabular">
                  {renderInline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── Images ────────────────────────────────────────────────────────────────

function MarkdownImage({ alt, src }: { alt: string; src: string }) {
  if (!isSameOriginImage(src)) {
    // Une image distante est un pixel traceur : son chargement révèle
    // l'IP du lecteur et l'instant de la lecture, et l'URL peut encoder
    // ce qu'on veut exfiltrer. On montre, on ne charge pas.
    return (
      <p className="text-xs text-muted-foreground">
        {alt || "Image"}{" "}
        <span className="break-all">({src})</span>
      </p>
    )
  }
  return (
    <img
      src={src}
      alt={alt}
      loading="lazy"
      className="max-w-full rounded-md border border-border"
    />
  )
}

// ── Enrichissements en ligne ──────────────────────────────────────────────

const INLINE = new RegExp(
  [
    "\\[\\[[^\\]|]+\\|[^\\]]+\\]\\]", // bouton
    "!\\[[^\\]]*\\]\\([^)\\s]+\\)", // image en ligne
    "\\[[^\\]]+\\]\\([^)\\s]+\\)", // lien
    "\\*\\*[^*]+\\*\\*", // gras
    "__[^_]+__", // gras
    "~~[^~]+~~", // barré
    "==[^=]+==", // surlignage
    "`[^`\\n]+`", // code
    "\\*[^*\\n]+\\*", // italique
    "_[^_\\n]+_", // italique
    ":[a-z]+:", // icône
  ].join("|"),
  "g",
)

const BUTTON = /^\[\[([^\]|]+)\|([^\]]+)\]\]$/
const LINK = /^\[([^\]]+)\]\(([^)\s]+)\)$/
const INLINE_IMAGE = /^!\[([^\]]*)\]\(([^)\s]+)\)$/

function renderInline(text: string): ReactNode {
  const parts: ReactNode[] = []
  let last = 0
  let key = 0

  for (const match of text.matchAll(INLINE)) {
    const token = match[0]
    const start = match.index ?? 0
    if (start > last) parts.push(<Fragment key={key++}>{text.slice(last, start)}</Fragment>)
    parts.push(<Fragment key={key++}>{renderToken(token)}</Fragment>)
    last = start + token.length
  }
  if (last < text.length) parts.push(<Fragment key={key++}>{text.slice(last)}</Fragment>)

  return <>{parts}</>
}

function renderToken(token: string): ReactNode {
  // ── Bouton ──
  const button = BUTTON.exec(token)
  if (button) {
    const route = button[2].trim()
    // Un chemin inconnu ne devient pas un bouton mort : il redevient du
    // texte. La règle anti-hallucination s'applique à l'affichage, pas
    // seulement à la consigne donnée au modèle.
    if (!isKnownRoute(route)) return token
    return (
      <Button asChild size="sm" variant="secondary" className="my-1 mr-2 align-middle">
        <Link to={route}>{button[1].trim()}</Link>
      </Button>
    )
  }

  // ── Image en ligne ──
  const image = INLINE_IMAGE.exec(token)
  if (image) return <MarkdownImage alt={image[1]} src={image[2]} />

  // ── Lien ──
  const link = LINK.exec(token)
  if (link) {
    const label = link[1]
    const href = link[2]
    if (href.startsWith("/")) {
      if (!isKnownRoute(href)) return token
      return (
        <Link to={href} className="text-primary underline underline-offset-2">
          {label}
        </Link>
      )
    }
    if (!isWebLink(href)) {
      // `javascript:`, `data:`, `file:` — rendus en texte brut.
      return token
    }
    // L'adresse est MONTRÉE, jamais masquée derrière le libellé : un
    // modèle peut rapporter un lien venu d'un tiers, et un libellé
    // rassurant sur une adresse qui ne l'est pas est la forme même de
    // l'hameçonnage.
    return (
      <>
        <a
          href={href}
          target="_blank"
          rel="noreferrer noopener"
          className="text-primary underline underline-offset-2"
        >
          {label}
        </a>{" "}
        <span className="break-all text-xs text-muted-foreground">({href})</span>
      </>
    )
  }

  // ── Icône ──
  if (/^:[a-z]+:$/.test(token)) {
    const name = token.slice(1, -1)
    if (!isKnownIcon(name)) return token
    const Icon = ICONS[name]
    return (
      <Icon
        className={cn("inline-block size-[1em] align-[-0.125em]", ICON_TONE[name])}
        aria-label={name}
      />
    )
  }

  if (token.startsWith("**") || token.startsWith("__")) {
    return <strong>{token.slice(2, -2)}</strong>
  }
  if (token.startsWith("~~")) {
    return <s className="text-muted-foreground">{token.slice(2, -2)}</s>
  }
  if (token.startsWith("==")) {
    return (
      <mark className="rounded bg-primary/20 px-1 text-foreground">{token.slice(2, -2)}</mark>
    )
  }
  if (token.startsWith("`")) {
    return <code className="rounded bg-secondary px-1 py-0.5 text-[0.85em]">{token.slice(1, -1)}</code>
  }
  return <em>{token.slice(1, -1)}</em>
}
