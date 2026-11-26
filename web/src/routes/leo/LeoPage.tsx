import { useQuery } from "@tanstack/react-query"
import { Bot, MessageSquare } from "lucide-react"

import { toApiError } from "@/api/client"
import { listConversations } from "@/api/leo"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { EmptyState, ErrorState, TableSkeleton } from "@/components/ui/states"

/**
 * Historique des conversations.
 *
 * La conversation elle-même se mène dans le dock, disponible sur toutes
 * les pages : dupliquer ici une seconde zone de saisie donnerait deux
 * fils parallèles pour un même assistant. Cette page sert à retrouver ce
 * qui a été dit.
 */
export default function LeoPage() {
  const conversations = useQuery({
    queryKey: ["leo-conversations"],
    queryFn: listConversations,
  })

  return (
    <div className="space-y-5">
      <header className="space-y-1">
        <h1 className="text-lg font-semibold tracking-tight">Leo</h1>
        <p className="text-sm text-muted-foreground">
          Tes échanges avec l'assistant. Pour lui parler, ouvre le panneau
          en bas à droite — il reste accessible depuis n'importe quelle page.
        </p>
      </header>

      {conversations.isPending ? (
        <TableSkeleton rows={4} columns={2} />
      ) : conversations.isError ? (
        <ErrorState
          error={toApiError(conversations.error)}
          onRetry={() => void conversations.refetch()}
        />
      ) : conversations.data.results.length === 0 ? (
        <EmptyState
          icon={Bot}
          title="Aucune conversation"
          description={
            <>
              Ouvre le panneau de Leo en bas à droite et pose-lui une
              question. Tes échanges seront conservés ici.
            </>
          }
        />
      ) : (
        <ul className="grid gap-3">
          {conversations.data.results.map((conversation) => (
            <li key={conversation.id}>
              <Card>
                <CardContent className="space-y-1.5 p-4">
                  <div className="flex flex-wrap items-center gap-2">
                    <MessageSquare className="size-4 text-muted-foreground" aria-hidden />
                    <span className="font-medium">
                      {conversation.title || "Conversation sans titre"}
                    </span>
                    {conversation.context_label ? (
                      <Badge variant="outline">{conversation.context_label}</Badge>
                    ) : null}
                    <span className="ml-auto text-xs text-muted-foreground tabular">
                      {conversation.message_count} message
                      {conversation.message_count > 1 ? "s" : ""}
                    </span>
                  </div>
                  {conversation.last_message_preview ? (
                    <p className="line-clamp-2 text-sm text-muted-foreground">
                      {conversation.last_message_preview}
                    </p>
                  ) : null}
                  <p className="text-xs text-muted-foreground tabular">
                    {new Date(conversation.updated_at).toLocaleString("fr-FR", {
                      day: "2-digit",
                      month: "2-digit",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </p>
                </CardContent>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
