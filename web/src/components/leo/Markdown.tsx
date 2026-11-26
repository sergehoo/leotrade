import { Fragment, type ReactNode } from "react"

import { cn } from "@/lib/utils"

/**
 * Rendu d'un sous-ensemble de Markdown, en éléments React.
 *
 * Volontairement sans `dangerouslySetInnerHTML` : le texte vient d'un
 * modèle de langage, qui peut restituer n'importe quoi — y compris du
 * contenu fourni par un tiers via un outil. Construire des éléments React
 * rend l'injection structurellement impossible plutôt que filtrée.
 *
 * Couvre ce qu'un assistant produit réellement : paragraphes, titres,
 * listes, tableaux, blocs de code, gras, italique, code en ligne et liens.
 * Le reste est rendu tel quel, en texte — mieux vaut un astérisque visible
 * qu'un contenu avalé.
 */
export function Markdown({ content, className }: { content: string; className?: string }) {
  return (
    <div className={cn("space-y-2 text-sm leading-relaxed", className)}>
      {renderBlocks(content)}
    </div>
  )
}

function renderBlocks(source: string): ReactNode[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n")
  const blocks: ReactNode[] = []
  let index = 0
  let key = 0

  while (index < lines.length) {
    const line = lines[index]

    if (!line.trim()) {
      index += 1
      continue
    }

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

    const heading = /^(#{1,4})\s+(.*)$/.exec(line)
    if (heading) {
      const level = heading[1].length
      blocks.push(
        <p key={key++} className={cn("font-semibold", level <= 2 ? "text-base" : "text-sm")}>
          {renderInline(heading[2])}
        </p>,
      )
      index += 1
      continue
    }

    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const ordered = /^\s*\d+\.\s+/.test(line)
      const items: string[] = []
      while (index < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*([-*+]|\d+\.)\s+/, ""))
        index += 1
      }
      const content = items.map((item, itemIndex) => (
        <li key={itemIndex}>{renderInline(item)}</li>
      ))
      blocks.push(
        ordered ? (
          <ol key={key++} className="list-decimal space-y-1 pl-5">
            {content}
          </ol>
        ) : (
          <ul key={key++} className="list-disc space-y-1 pl-5">
            {content}
          </ul>
        ),
      )
      continue
    }

    const paragraph: string[] = []
    while (
      index < lines.length &&
      lines[index].trim() &&
      !lines[index].trimStart().startsWith("```") &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !/^\s*([-*+]|\d+\.)\s+/.test(lines[index])
    ) {
      paragraph.push(lines[index])
      index += 1
    }
    blocks.push(<p key={key++}>{renderInline(paragraph.join(" "))}</p>)
  }

  return blocks
}

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

/** Gras, italique, code en ligne et liens. */
function renderInline(text: string): ReactNode {
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g
  const parts = text.split(pattern).filter((part) => part !== "")

  return (
    <>
      {parts.map((part, index) => {
        if (part.startsWith("**") && part.endsWith("**")) {
          return <strong key={index}>{part.slice(2, -2)}</strong>
        }
        if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
          return <em key={index}>{part.slice(1, -1)}</em>
        }
        if (part.startsWith("`") && part.endsWith("`")) {
          return (
            <code key={index} className="rounded bg-secondary px-1 py-0.5 text-[0.85em]">
              {part.slice(1, -1)}
            </code>
          )
        }
        const link = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(part)
        if (link) {
          const href = link[2]
          // Seuls http(s) deviennent cliquables : un `javascript:` fabriqué
          // par le modèle ne doit pas se transformer en lien actif.
          if (!/^https?:\/\//i.test(href)) {
            return <Fragment key={index}>{link[1]}</Fragment>
          }
          return (
            <a
              key={index}
              href={href}
              target="_blank"
              rel="noreferrer noopener"
              className="text-primary underline underline-offset-2"
            >
              {link[1]}
            </a>
          )
        }
        return <Fragment key={index}>{part}</Fragment>
      })}
    </>
  )
}
