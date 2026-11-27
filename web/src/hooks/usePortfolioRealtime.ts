import { useEffect, useRef, useState } from "react"

import {
  openRealtimeSocket,
  RECONNECT_DELAYS,
  type RealtimeEvent,
  type RealtimeStatus,
} from "@/api/realtime"

/**
 * Correctif reçu en direct. Chaque champ n'est renseigné que si le
 * serveur l'a envoyé : un champ absent laisse la valeur chargée en REST
 * intacte, au lieu d'être écrasée par un zéro qui passerait ensuite pour
 * une mesure.
 */
export interface LivePosition {
  id: number
  mark_price?: string
  unrealized_pnl?: string
  quantity?: string
}

export interface LiveMetrics {
  equity?: string
  available_cash?: string
  locked_cash?: string
  unrealized_pnl?: string
  realized_pnl?: string
}

export interface PortfolioLive {
  /**
   * Portefeuille auquel ces correctifs appartiennent.
   *
   * Porté par l'état plutôt que remis à zéro dans l'effet : au moment
   * où l'on change de portefeuille, l'ancien état est encore en
   * mémoire, et afficher le mark d'un AUTRE portefeuille, ne serait-ce
   * qu'une image, est exactement le chiffre faux que tout ce code
   * cherche à éviter.
   */
  portfolioId: number | null
  status: RealtimeStatus
  positions: Record<number, LivePosition>
  metrics: LiveMetrics | null
  /** Horodatage du dernier message REÇU — pas de la connexion. */
  lastEventAt: number | null
}

const SILENT: PortfolioLive = {
  portfolioId: null,
  status: "connecting",
  positions: {},
  metrics: null,
  lastEventAt: null,
}

function text(value: unknown): string | undefined {
  if (value === null || value === undefined) return undefined
  const raw = String(value).trim()
  return raw === "" ? undefined : raw
}

function readPosition(raw: Record<string, unknown>): LivePosition | null {
  if (typeof raw.id !== "number") return null
  return {
    id: raw.id,
    mark_price: text(raw.mark_price),
    unrealized_pnl: text(raw.unrealized_pnl),
    quantity: text(raw.quantity),
  }
}

/**
 * Liaison temps réel d'un portefeuille — `ws/portfolio/<id>/`.
 *
 * Les données REST restent la source : la socket ne fait que CORRIGER
 * des champs déjà chargés. Elle n'en fabrique aucun.
 */
export function usePortfolioRealtime(portfolioId: number | null): PortfolioLive {
  const [live, setLive] = useState<PortfolioLive>(SILENT)
  const attempts = useRef(0)

  useEffect(() => {
    if (portfolioId === null) return

    let socket: WebSocket | null = null
    let retry: number | undefined
    let stopped = false

    const open = () => {
      if (stopped) return
      socket = openRealtimeSocket(`/ws/portfolio/${portfolioId}/`)
      if (!socket) {
        setLive({ ...SILENT, portfolioId, status: "lost" })
        return
      }

      setLive({ ...SILENT, portfolioId, status: "connecting" })

      socket.onopen = () => {
        attempts.current = 0
        setLive((previous) => ({ ...previous, status: "online" }))
      }

      socket.onclose = () => {
        if (stopped) return
        setLive((previous) => ({ ...previous, status: "lost" }))
        const index = Math.min(attempts.current, RECONNECT_DELAYS.length - 1)
        attempts.current += 1
        retry = window.setTimeout(open, RECONNECT_DELAYS[index])
      }

      socket.onmessage = (raw) => {
        let message: RealtimeEvent
        try {
          message = JSON.parse(raw.data as string) as RealtimeEvent
        } catch {
          // Un message illisible ne doit pas faire tomber la liaison.
          return
        }
        const payload = message.payload
        if (!payload || typeof payload !== "object") return

        // La poignée de main n'est pas une mesure : elle ne compte pas
        // comme « dernière mise à jour ».
        if (message.event === "connection.established") return

        if (message.event === "position.update") {
          const patch = readPosition(
            (payload.position ?? {}) as Record<string, unknown>,
          )
          if (!patch) return
          setLive((previous) => ({
            ...previous,
            positions: { ...previous.positions, [patch.id]: patch },
            lastEventAt: Date.now(),
          }))
          return
        }

        if (message.event !== "portfolio.update") return

        if (payload.kind === "metrics_refresh") {
          setLive((previous) => ({
            ...previous,
            metrics: {
              equity: text(payload.equity),
              available_cash: text(payload.available_cash),
              locked_cash: text(payload.locked_cash),
              unrealized_pnl: text(payload.unrealized_pnl),
              realized_pnl: text(payload.realized_pnl),
            },
            lastEventAt: Date.now(),
          }))
          return
        }

        if (payload.kind === "positions_snapshot" && Array.isArray(payload.positions)) {
          const patches: Record<number, LivePosition> = {}
          for (const entry of payload.positions as Record<string, unknown>[]) {
            const patch = readPosition(entry)
            if (patch) patches[patch.id] = patch
          }
          // Un instantané fait foi : il remplace, il ne complète pas.
          setLive((previous) => ({
            ...previous,
            positions: patches,
            lastEventAt: Date.now(),
          }))
          return
        }

        // Une autre forme — un ordre passé, un instantané créé — vaut
        // signe de vie, mais ne corrige aucun chiffre.
        setLive((previous) => ({ ...previous, lastEventAt: Date.now() }))
      }
    }

    open()

    return () => {
      stopped = true
      window.clearTimeout(retry)
      if (socket) {
        socket.onclose = null
        socket.close()
      }
    }
  }, [portfolioId])

  // Les correctifs d'un autre portefeuille ne sortent jamais d'ici.
  return live.portfolioId === portfolioId ? live : SILENT
}
