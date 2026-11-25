import { zodResolver } from "@hookform/resolvers/zod"
import { ShieldCheck } from "lucide-react"
import { useState } from "react"
import { useForm } from "react-hook-form"
import { Navigate, useLocation, useNavigate } from "react-router-dom"
import { z } from "zod"

import { toApiError } from "@/api/client"
import { Alert } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Spinner } from "@/components/ui/spinner"
import { useAuth } from "@/stores/auth"
import type { ApiError } from "@/types/api"
import { isMfaChallenge } from "@/types/api"

const credentialsSchema = z.object({
  email: z.string().min(1, "Adresse email requise.").email("Adresse email invalide."),
  password: z.string().min(1, "Mot de passe requis."),
})

const mfaSchema = z.object({
  code: z.string().min(6, "Le code comporte au moins 6 caractères."),
})

export default function LoginPage() {
  const user = useAuth((s) => s.user)
  const mfaToken = useAuth((s) => s.mfaToken)
  const location = useLocation()

  if (user) {
    const from = (location.state as { from?: string } | null)?.from ?? "/"
    return <Navigate to={from} replace />
  }

  return (
    <div className="flex min-h-dvh items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-sm space-y-6">
        <div className="space-y-1.5 text-center">
          <p className="text-xl font-semibold tracking-tight">LeoTrade</p>
          <p className="text-sm text-muted-foreground">Trading assisté par intelligence artificielle</p>
        </div>
        {mfaToken ? <MfaStep /> : <CredentialsStep />}
      </div>
    </div>
  )
}

function CredentialsStep() {
  const login = useAuth((s) => s.login)
  const navigate = useNavigate()
  const location = useLocation()
  const [apiError, setApiError] = useState<ApiError | null>(null)

  const form = useForm<z.infer<typeof credentialsSchema>>({
    resolver: zodResolver(credentialsSchema),
    defaultValues: { email: "", password: "" },
  })

  const onSubmit = form.handleSubmit(async (values) => {
    setApiError(null)
    try {
      const result = await login(values.email, values.password)
      // Si un second facteur est exigé, le store bascule sur l'étape MFA :
      // on ne navigue pas, l'écran change en place.
      if (!isMfaChallenge(result)) {
        const from = (location.state as { from?: string } | null)?.from ?? "/"
        navigate(from, { replace: true })
      }
    } catch (error) {
      setApiError(toApiError(error))
    }
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connexion</CardTitle>
        <CardDescription>Accédez à votre espace de trading.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          {apiError ? (
            <Alert variant="danger" title="Connexion refusée">
              {apiError.message}
              {apiError.code === "EMAIL_NOT_VERIFIED" ? (
                <p className="mt-1">
                  Ouvrez le lien de vérification reçu par email, puis réessayez.
                </p>
              ) : null}
            </Alert>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor="email">Adresse email</Label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              autoFocus
              aria-invalid={!!form.formState.errors.email}
              {...form.register("email")}
            />
            {form.formState.errors.email ? (
              <p className="text-xs text-destructive">{form.formState.errors.email.message}</p>
            ) : null}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="password">Mot de passe</Label>
            <Input
              id="password"
              type="password"
              autoComplete="current-password"
              aria-invalid={!!form.formState.errors.password}
              {...form.register("password")}
            />
            {form.formState.errors.password ? (
              <p className="text-xs text-destructive">{form.formState.errors.password.message}</p>
            ) : null}
          </div>

          <Button type="submit" className="w-full" disabled={form.formState.isSubmitting}>
            {form.formState.isSubmitting ? <Spinner /> : null}
            Se connecter
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}

function MfaStep() {
  const submitMfa = useAuth((s) => s.submitMfa)
  const cancelMfa = useAuth((s) => s.cancelMfa)
  const navigate = useNavigate()
  const location = useLocation()
  const [apiError, setApiError] = useState<ApiError | null>(null)

  const form = useForm<z.infer<typeof mfaSchema>>({
    resolver: zodResolver(mfaSchema),
    defaultValues: { code: "" },
  })

  const onSubmit = form.handleSubmit(async (values) => {
    setApiError(null)
    try {
      await submitMfa(values.code.trim())
      const from = (location.state as { from?: string } | null)?.from ?? "/"
      navigate(from, { replace: true })
    } catch (error) {
      setApiError(toApiError(error))
      form.resetField("code")
    }
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-primary" aria-hidden />
          Vérification en deux étapes
        </CardTitle>
        <CardDescription>
          Saisissez le code de votre application d'authentification, ou l'un de vos
          codes de récupération.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={onSubmit} className="space-y-4" noValidate>
          {apiError ? (
            <Alert variant="danger" title="Code refusé">
              {apiError.message}
            </Alert>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor="code">Code de vérification</Label>
            <Input
              id="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              autoFocus
              className="tabular tracking-[0.3em]"
              aria-invalid={!!form.formState.errors.code}
              {...form.register("code")}
            />
            {form.formState.errors.code ? (
              <p className="text-xs text-destructive">{form.formState.errors.code.message}</p>
            ) : null}
          </div>

          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              className="flex-1"
              onClick={cancelMfa}
              disabled={form.formState.isSubmitting}
            >
              Retour
            </Button>
            <Button type="submit" className="flex-1" disabled={form.formState.isSubmitting}>
              {form.formState.isSubmitting ? <Spinner /> : null}
              Valider
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}
