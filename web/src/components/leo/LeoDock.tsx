import { Bot, Send, X } from "lucide-react"
import { useCallback, useEffect, useRef, useState } from "react"
import { useLocation } from "react-router-dom"

import {
  openLeoSocket,
  type LeoAction,
  type LeoActionRequest,
  type LeoClientEvent,
  type LeoMessage,
  type LeoServerEvent,
} from "@/api/leo"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Spinner } from "@/components/ui/spinner"
import { useAuth } from "@/stores/auth"
import { cn } from "@/lib/utils"
import { Markdown } from "./Markdown"

/** Émetteur de la socket, partagé par les cartes de décision. */
type Emitter = (payload: LeoClientEvent) => boolean

/** Message affiché : historique serveur ou réponse en cours de streaming. */
interface Turn {
  id: number | string
  role: "USER" | "ASSISTANT"
  content: string
  actions: LeoAction[]
  streaming?: boolean
  failed?: boolean
}

/**
 * Leo, accessible depuis toutes les pages.
 *
 * Monté dans l'AppShell plutôt que sur une route : l'assistant sert à
 * commenter ce que l'utilisateur regarde, ce qui n'a plus de sens s'il
 * faut quitter l'écran pour lui parler. Le chemin courant lui est transmis
 * comme contexte à chaque message.
 */
export default function LeoDock() {
  const user = useAuth((s) => s.user)
  const location = useLocation()

  const [open, setOpen] = useState(false)
  const [turns, setTurns] = useState<Turn[]>([])
  const [draft, setDraft] = useState("")
  const [connected, setConnected] = useState(false)
  const [thinking, setThinking] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [actionRequest, setActionRequest] = useState<LeoActionRequest | null>(null)

  const socketRef = useRef<WebSocket | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const streamingId = useRef<number | string | null>(null)

  const handleEvent = useCallback((event: LeoServerEvent) => {
    switch (event.type) {
      case "session": {
        const history = (event.history ?? []) as LeoMessage[]
        setTurns(
          history
            .filter((message) => message.role !== "SYSTEM")
            .map((message) => ({
              id: message.id,
              role: message.role === "USER" ? "USER" : "ASSISTANT",
              content: message.content,
              actions: message.actions ?? [],
            })),
        )
        setError(null)
        break
      }
      case "thinking":
        setThinking(true)
        break
      case "chunk": {
        const id = (event as { id: number }).id
        const text = (event as { text: string }).text ?? ""
        setThinking(false)
        setTurns((previous) => {
          const existing = previous.find((turn) => turn.id === id)
          if (existing) {
            return previous.map((turn) =>
              turn.id === id ? { ...turn, content: turn.content + text } : turn,
            )
          }
          streamingId.current = id
          return [
            ...previous,
            { id, role: "ASSISTANT", content: text, actions: [], streaming: true },
          ]
        })
        break
      }
      case "done": {
        const id = (event as { id: number }).id
        const actions = ((event as { actions?: LeoAction[] }).actions ?? []) as LeoAction[]
        const clean = (event as { clean_content?: string }).clean_content ?? ""
        const request =
          (event as { action_request?: LeoActionRequest | null }).action_request ?? null
        setThinking(false)
        streamingId.current = null

        // Une demande tranchée ne doit plus proposer de boutons.
        setActionRequest(
          request && (request.status === "WAITING" || request.status === "PENDING")
            ? request
            : null,
        )

        setTurns((previous) => {
          // `done` sans `chunk` préalable : c'est la forme que prend le
          // résultat d'un OUTIL côté serveur (`_send_tool_result`), y
          // compris la confirmation d'une opération. Sans ce repli, la
          // réponse disparaissait sans un mot.
          if (!previous.some((turn) => turn.id === id)) {
            if (!clean) return previous
            return [...previous, { id, role: "ASSISTANT", content: clean, actions }]
          }
          return previous.map((turn) =>
            turn.id === id ? { ...turn, actions, streaming: false } : turn,
          )
        })
        break
      }
      case "action_update": {
        const actionId = (event as { action_id: number }).action_id
        const status = (event as { status: string }).status
        setTurns((previous) =>
          previous.map((turn) => ({
            ...turn,
            actions: turn.actions.map((action) =>
              action.id === actionId ? { ...action, status } : action,
            ),
          })),
        )
        break
      }
      case "error":
        setThinking(false)
        setError((event as { message: string }).message || "Erreur de l'assistant.")
        break
      default:
        break
    }
  }, [])

  // Connexion ouverte seulement quand le dock est déployé : garder un
  // WebSocket vivant sur toutes les pages pour une fonctionnalité repliée
  // consomme une connexion serveur par onglet, sans rien apporter.
  useEffect(() => {
    if (!open || !user) return

    const socket = openLeoSocket()
    if (!socket) {
      setError("Session expirée. Reconnecte-toi pour parler à Leo.")
      return
    }

    socketRef.current = socket
    socket.onopen = () => setConnected(true)
    socket.onclose = () => {
      setConnected(false)
      setThinking(false)
    }
    socket.onerror = () =>
      setError("Connexion à Leo interrompue. Referme et rouvre le panneau.")
    socket.onmessage = (raw) => {
      try {
        handleEvent(JSON.parse(raw.data) as LeoServerEvent)
      } catch {
        // Un message illisible ne doit pas faire tomber le panneau.
      }
    }

    return () => {
      socket.onclose = null
      socket.close()
      socketRef.current = null
      setConnected(false)
    }
  }, [open, user, handleEvent])

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
  }, [turns, thinking])

  /**
   * Envoie un événement sur la socket. Retourne false si rien n'est parti.
   *
   * Les décisions passaient auparavant par `POST
   * /assistant/action-requests/<id>/confirm/` avec l'identifiant d'un
   * `AssistantAction` — l'endpoint d'un autre modèle. Deux séquences de
   * clés primaires : soit le bouton était mort, soit une demande portant
   * par hasard le même numéro était confirmée ET exécutée.
   */
  const emit = useCallback((payload: LeoClientEvent): boolean => {
    const socket = socketRef.current
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      setError("Leo est hors ligne : la décision n'a pas été transmise.")
      return false
    }
    socket.send(JSON.stringify(payload))
    return true
  }, [])

  function send() {
    const text = draft.trim()
    const socket = socketRef.current
    if (!text || !socket || socket.readyState !== WebSocket.OPEN) return

    socket.send(
      JSON.stringify({
        type: "chat",
        message: text,
        // Le chemin courant permet à Leo de commenter ce que l'utilisateur
        // a sous les yeux plutôt que de demander de quoi on parle.
        context: { page: location.pathname },
      }),
    )
    setTurns((previous) => [
      ...previous,
      { id: `local-${Date.now()}`, role: "USER", content: text, actions: [] },
    ])
    setDraft("")
    setError(null)
  }

  if (!user) return null

  return (
    <>
      {!open ? (
        <Button
          onClick={() => setOpen(true)}
          className="fixed bottom-5 right-5 z-40 h-12 gap-2 rounded-full px-5 shadow-lg"
          aria-label="Ouvrir Leo, l'assistant"
        >
          <Bot aria-hidden />
          Leo
        </Button>
      ) : null}

      {open ? (
        <aside
          className={cn(
            "fixed bottom-0 right-0 z-40 flex h-[min(34rem,85svh)] w-full flex-col",
            "border-l border-t border-border bg-card shadow-2xl",
            "sm:bottom-5 sm:right-5 sm:h-[min(34rem,80svh)] sm:w-[26rem] sm:rounded-lg sm:border",
          )}
          aria-label="Assistant Leo"
        >
          <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
            <div className="flex items-center gap-2">
              <LeoAvatar speaking={thinking} />
              <div>
                <p className="text-sm font-medium leading-none">Leo</p>
                <p className="text-xs text-muted-foreground">
                  {connected ? "En ligne" : "Connexion…"}
                </p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setOpen(false)}
              aria-label="Fermer le panneau de Leo"
            >
              <X aria-hidden />
            </Button>
          </header>

          <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
            {error ? <Alert variant="warning">{error}</Alert> : null}

            {turns.length === 0 && !error ? (
              <div className="pt-6 text-center text-sm text-muted-foreground">
                <p className="font-medium text-foreground">Leo t'écoute.</p>
                <p className="mt-1">
                  Pose-lui une question sur ton portefeuille, tes positions ou
                  tes limites de risque. Il voit la page que tu consultes.
                </p>
              </div>
            ) : null}

            {turns.map((turn) => (
              <TurnBubble key={turn.id} turn={turn} emit={emit} />
            ))}

            {thinking ? (
              <div className="flex items-center gap-2 text-xs text-muted-foreground">
                <Spinner />
                Leo réfléchit…
              </div>
            ) : null}
          </div>

          {actionRequest ? (
            <ActionRequestCard request={actionRequest} emit={emit} />
          ) : null}

          <form
            className="flex items-end gap-2 border-t border-border p-3"
            onSubmit={(event) => {
              event.preventDefault()
              send()
            }}
          >
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault()
                  send()
                }
              }}
              rows={1}
              placeholder="Écris à Leo…"
              aria-label="Message pour Leo"
              className={cn(
                "max-h-28 min-h-9 flex-1 resize-none rounded-md border border-input bg-background px-3 py-2 text-sm",
                "placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              )}
            />
            <Button
              type="submit"
              size="icon"
              disabled={!connected || !draft.trim()}
              aria-label="Envoyer"
            >
              <Send aria-hidden />
            </Button>
          </form>
        </aside>
      ) : null}
    </>
  )
}

function LeoAvatar({ speaking }: { speaking: boolean }) {
  return (
    <span
      className={cn(
        "flex size-8 items-center justify-center rounded-full border border-primary/30 bg-primary/10 text-primary",
        speaking && "animate-pulse",
      )}
      aria-hidden
    >
      <Bot className="size-4" />
    </span>
  )
}

function TurnBubble({ turn, emit }: { turn: Turn; emit: Emitter }) {
  const isUser = turn.role === "USER"

  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[88%] rounded-lg px-3 py-2",
          isUser
            ? "bg-primary/15 text-foreground"
            : "border border-border bg-secondary/30",
        )}
      >
        {isUser ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{turn.content}</p>
        ) : (
          <Markdown content={turn.content} />
        )}

        {turn.actions.length > 0 ? (
          <div className="mt-3 space-y-2">
            {turn.actions.map((action) => (
              <ActionCard key={action.id} action={action} emit={emit} />
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/**
 * Action proposée par Leo.
 *
 * Rien n'est exécuté sans un clic explicite : l'assistant propose, il ne
 * dispose pas. Le libellé indique ce qui se produira, pas ce que Leo
 * suggère — c'est l'utilisateur qui engage l'opération.
 */
function ActionCard({ action, emit }: { action: LeoAction; emit: Emitter }) {
  const [pending, setPending] = useState(false)

  // Le statut n'est plus tenu localement : il vient du serveur, par
  // `action_update`. Afficher « Confirmée » sans l'avoir obtenu est, sur
  // une action qui engage de l'argent, pire qu'une erreur.
  const status = action.status
  const settled = status !== "PENDING" && status !== "PROPOSED"

  useEffect(() => {
    if (settled) setPending(false)
  }, [settled])

  function decide(confirm: boolean) {
    setPending(
      emit(
        confirm
          ? { type: "action_confirm", action_id: action.id }
          : { type: "action_reject", action_id: action.id },
      ),
    )
  }

  return (
    <div className="rounded-md border border-warning/35 bg-warning/5 p-2.5 text-xs">
      <p className="font-medium">{action.type}</p>
      {action.rationale ? (
        <p className="mt-1 text-muted-foreground">{action.rationale}</p>
      ) : null}

      {settled ? (
        <p className="mt-2 text-muted-foreground">
          {status === "CONFIRMED" ? "Confirmée." : "Annulée."}
        </p>
      ) : (
        <div className="mt-2 flex gap-2">
          <Button size="sm" disabled={pending} onClick={() => decide(true)}>
            {pending ? <Spinner /> : null}
            Confirmer
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={pending}
            onClick={() => decide(false)}
          >
            Annuler
          </Button>
        </div>
      )}
    </div>
  )
}

/**
 * Demande de confirmation transactionnelle mise en attente par le Risk
 * Engine.
 *
 * La clé `action_request` du message `done` n'était pas lue : aucune
 * carte n'apparaissait pour les opérations qui passent par le moteur de
 * risque — c'est-à-dire précisément celles qui engagent de l'argent.
 */
function ActionRequestCard({
  request,
  emit,
}: {
  request: LeoActionRequest
  emit: Emitter
}) {
  const [pending, setPending] = useState(false)
  const live = request.mode === "LIVE"
  const awaitsSecond =
    request.requires_double_confirmation && request.confirmations_received < 2

  function decide(confirm: boolean) {
    setPending(
      emit(
        confirm
          ? { type: "action_request_confirm", request_id: request.id }
          : { type: "action_request_cancel", request_id: request.id },
      ),
    )
  }

  return (
    <div
      className={cn(
        "mx-3 mb-2 rounded-md border p-3 text-xs",
        live ? "border-loss/45 bg-loss/10" : "border-warning/40 bg-warning/5",
      )}
    >
      <p className={cn("font-semibold", live ? "text-loss" : "text-warning")}>
        {live ? "Confirmation — ARGENT RÉEL" : "Confirmation — simulation"}
      </p>
      {request.summary ? <p className="mt-1.5 text-sm">{request.summary}</p> : null}
      {request.risk_summary ? (
        <p className="mt-1 text-muted-foreground">{request.risk_summary}</p>
      ) : null}
      {request.error_message ? (
        <p className="mt-1 text-loss">{request.error_message}</p>
      ) : null}
      {awaitsSecond && request.confirmations_received > 0 ? (
        <p className={cn("mt-1", live ? "text-loss" : "text-warning")}>
          Deuxième confirmation requise ({request.confirmations_received}/2).
        </p>
      ) : null}
      <div className="mt-2.5 flex flex-wrap gap-2">
        <Button
          size="sm"
          variant={live ? "destructive" : "default"}
          disabled={pending}
          onClick={() => decide(true)}
        >
          {awaitsSecond && request.confirmations_received > 0
            ? "Confirmer définitivement"
            : "Confirmer"}
        </Button>
        <Button
          size="sm"
          variant="outline"
          disabled={pending}
          onClick={() => decide(false)}
        >
          Annuler
        </Button>
      </div>
    </div>
  )
}
