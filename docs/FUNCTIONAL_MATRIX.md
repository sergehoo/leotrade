# Matrice fonctionnelle — contrat de non-régression

> Généré par cartographie parallèle de l'existant (10 agents, un par domaine,
> + un agent de complétude). **Source de vérité du périmètre à reprendre.**
> Toute fonctionnalité retirée doit être justifiée et validée explicitement.

## Vue d'ensemble

**340 fonctionnalités** recensées sur 10 domaines, plus 31 relevées par l'agent de complétude.

| État de l'API | Nombre | Part |
|---|---:|---:|
| Déjà consommable en REST | 49 | 14 % |
| Partiellement exposé | 79 | 23 % |
| Vue Django uniquement | 212 | 62 % |

- **93 fonctionnalités temps réel** (WebSocket / push).
- **241 fonctionnalités à porter sur mobile.**

> Lecture : seulement **14 % du produit est aujourd'hui atteignable par un client
> React ou Flutter**. L'essentiel du travail n'est pas de redessiner des écrans,
> mais de **remonter la logique des vues Django vers des services et une API**.

---

## Par domaine

### auth-accounts

`26 fonctionnalités` — API : **4 prêtes, 3 partielles, 19 à exposer**

**Modèles** : `KYCProfile (dashboard)`, `User (django.contrib.auth, modèle par défaut — aucun AUTH_USER_MODEL personnalisé)`, `EmailAddress (allauth.account)`, `EmailConfirmation (allauth.account)`, `Authenticator (allauth.mfa — TOTP et codes de récupération)`, `TOTPDevice / StaticDevice (django_otp — legacy, conservés pour la migration core.0002)`, `SocialAccount / SocialApp / SocialToken (allauth.socialaccount — app installée, aucun provider configuré, aucun flux social actif)`, `Site (django.contrib.sites, SITE_ID — utilisé pour les URLs des emails de confirmation)`, `Session (django.contrib.sessions, backend cached_db en production)`

**Tâches Celery** : `Aucune tâche Celery propre au domaine auth-accounts (ni dans CELERY_BEAT_SCHEDULE ni ailleurs)`, `notifications.tasks.send_notification_task — déclenchée indirectement par les notifications KYC_SUBMITTED / KYC_APPROVED / KYC_REJECTED ; idempotente (saute les notifications déjà SENT ou SUPPRESSED), 2 retries`

**Canaux WebSocket** : `ws/notifications/ — NotificationCenterConsumer, groupe user_notifications_{user.id} ; ferme avec le code 4401 si l'utilisateur n'est pas authentifié (seul point WS du domaine, l'authentification y est faite par AuthMiddlewareStack sur le cookie de session)`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Inscription par email** | ❌ | WEB/MOBILE |  | Aucun endpoint REST d'inscription : api/urls.py n'expose qu'un DefaultRouter métier. Il faut POST /api/v1/auth/register qui reproduit exactement : honeypot, anti-énumération, non-connexion après inscription, envoi de l'email de confirmation. |
| **Vérification d'adresse email obligatoire** | ❌ | WEB/MOBILE |  | Pas d'endpoint de confirmation ni de renvoi d'email en API. Prévoir POST /api/v1/auth/email/verify (clé) et POST /api/v1/auth/email/resend, plus un deep link mobile vers la clé de confirmation. |
| **Connexion par email / mot de passe (session Django)** | 🟡 | WEB/MOBILE |  | SessionAuthentication et JWTAuthentication sont déclarées dans REST_FRAMEWORK mais AUCUN endpoint de jeton n'existe (ni TokenObtainPairView, ni TokenRefreshView dans api/urls.py) et SIMPLE_JWT n'est pas configuré. Pour React/Flutter il faut : POST /api/v1/auth/login, /refresh, /logout, réglages SIMPLE_JWT (durées, rotation, blacklist) et une stratégie CSRF compatible avec CSRF_COOKIE_HTTPONLY. |
| **Déconnexion** | ❌ | WEB/MOBILE |  | Pas d'endpoint de logout API ; côté mobile il faudra invalider/blacklister le refresh token, comportement inexistant aujourd'hui. |
| **Réinitialisation du mot de passe par email** | ❌ | WEB/MOBILE |  | Aucun endpoint REST ; prévoir POST /api/v1/auth/password/reset et .../reset/confirm en conservant l'anti-énumération (réponse identique), plus un deep link mobile. |
| **Changement et définition du mot de passe** | ❌ | WEB/MOBILE |  | Pas d'endpoint API. Note : ces pages ne sont liées nulle part dans la navigation (accessibles par URL directe ou via le lien 'mot de passe oublié') — la refonte doit créer un véritable écran Sécurité du compte. |
| **Gestion des adresses email du compte** | ❌ | WEB |  | Aucun endpoint REST de gestion des emails ; prévoir un sous-ensemble /api/v1/auth/emails (list/add/primary/resend/delete) avec les mêmes garde-fous. |
| **Ré-authentification avant action sensible** | ❌ | WEB/MOBILE |  | Aucune notion de step-up auth en API. Il faut un mécanisme équivalent (jeton de ré-authentification court, ou re-saisie du mot de passe) avant les mutations sensibles du compte. |
| **MFA TOTP et codes de récupération** | ❌ | WEB/MOBILE |  | Pas d'endpoint MFA. Il faut exposer : statut MFA, activation TOTP (secret + QR/otpauth URI avec MFA_TOTP_ISSUER), validation, désactivation, génération/consommation des codes de récupération, et surtout l'étape de challenge dans le flux de login JWT. Côté UI, créer un écran Sécurité : aujourd'hui le MFA n'est atteignable que par URL directe. |
| **États de compte bloquant l'accès** | ❌ | WEB/MOBILE |  | Ces états doivent devenir des codes d'erreur API stables (ex. account_inactive, email_not_verified, signup_closed) pour que les clients affichent le bon écran. |
| **Login admin Django durci par allauth** | ❌ | WEB |  | Hors périmètre API (interface Django Admin conservée), mais le back-office KYC lui-même doit être repris en API (voir fonctionnalités KYC admin). |
| **Consultation de son dossier KYC** | ❌ | WEB/MOBILE |  | Aucun endpoint. Prévoir GET /api/v1/kyc/me renvoyant statut, motif de rejet, champs remplis et documents déjà fournis (sans exposer les fichiers en accès direct). |
| **Soumission et resoumission du dossier KYC** | ❌ | WEB/MOBILE |  | Aucun endpoint. Prévoir POST/PATCH /api/v1/kyc/me en multipart avec exactement les mêmes validations côté serveur (taille, extension, content_type, magic bytes), plus la prise de photo par la caméra mobile (selfie et recto/verso) et la reprise d'un dossier partiellement rempli. |
| **File de revue KYC (staff)** | ❌ | WEB |  | Aucun endpoint. Prévoir GET /api/v1/admin/kyc/ avec filtre status, recherche, pagination et permission staff (aujourd'hui aucune permission DRF staff n'existe, seul IsOwner est défini). |
| **Détail d'un dossier KYC (staff)** | ❌ | WEB |  | Aucun endpoint. Prévoir GET /api/v1/admin/kyc/<id>/ (staff) avec les métadonnées de présence des documents plutôt que des URLs de fichiers publiques. |
| **Téléchargement contrôlé des documents KYC** | ❌ | WEB |  | Aucun endpoint. Un équivalent API doit rester en streaming authentifié staff avec les mêmes entêtes no-store/nosniff, ou utiliser des URLs signées à durée très courte. Ne jamais exposer /media/kyc/ en statique. |
| **Approbation d'un dossier KYC** | ❌ | WEB |  | Aucun endpoint. Prévoir POST /api/v1/admin/kyc/<id>/approve (staff), idempotent, avec journalisation du relecteur. |
| **Rejet d'un dossier KYC** | ❌ | WEB |  | Aucun endpoint. Prévoir POST /api/v1/admin/kyc/<id>/reject (staff) en conservant la séparation note interne / motif client. |
| **Porte KYC sur les retraits de fonds** | ❌ | WEB/MOBILE |  | Le wallet n'est pas exposé en API ; lorsqu'il le sera, ce garde doit vivre dans le service métier (pas dans la vue) pour que l'API, l'admin et les tâches partagent la même règle. |
| **Cloisonnement des données par propriétaire (API)** | ✅ | WEB/MOBILE |  | — |
| **Rôles et habilitations (staff / superuser)** | 🟡 | WEB |  | Aucune permission DRF staff n'existe (api/permissions.py ne contient que IsOwner) : il faut une classe IsStaff et des endpoints d'administration pour que le back-office KYC et wallet existe hors des templates Django. |
| **Contexte de session global de l'utilisateur authentifié** | ❌ | WEB/MOBILE |  | Pas d'endpoint de contexte/profil courant (aucun /me dans l'API). Sans un GET /api/v1/me renvoyant utilisateur, rôles, statut KYC, wallet, portfolio par défaut et mode effectif, les clients React/Flutter réintroduiront la divergence d'affichage du mode de trading. |
| **Authentification des connexions WebSocket** | 🟡 | WEB/MOBILE | ⚡ | L'authentification WS dépend du cookie de session Django : une application Flutter authentifiée en JWT ne peut pas se connecter en l'état. Il faut un middleware WS acceptant un jeton (query string ou sous-protocole) en plus de la session. |
| **Traçabilité des requêtes et du contexte utilisateur** | ✅ | WEB/MOBILE |  | — |
| **Protection de l'endpoint de métriques** | ✅ | WEB |  | — |
| **Contrôles de configuration de sécurité au déploiement** | ✅ | WEB |  | — |

<details><summary>Règles métier invariantes à préserver</summary>

**Inscription par email**
<br>_Création de compte via django-allauth avec email + double saisie du mot de passe, honeypot anti-bot, et envoi immédiat d'un email de confirmation. Aucun username demandé._
<br>Points d'entrée : `backend/leoTrade/urls.py: path("accounts/", include("allauth.urls"))`, `backend/leoTrade/settings/base.py:205-231 (ACCOUNT_*)`, `backend/wallet/signals.py:create_user_wallet`

- ACCOUNT_SIGNUP_FIELDS = [email*, password1*, password2*] et ACCOUNT_LOGIN_METHODS={"email"} : l'email est l'identifiant, pas de username
- ACCOUNT_UNIQUE_EMAIL=True + ACCOUNT_PREVENT_ENUMERATION=True : un email déjà pris ne doit jamais être révélé (email account_already_exists_* envoyé à la place d'une erreur de formulaire)
- Le champ honeypot doit rester nommé exactement 'website' (ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD) : le template signup.html le pose en champ caché
- Après signup l'utilisateur N'EST PAS connecté : redirection vers account_email_verification_sent, EmailAddress.verified=False, pas de _auth_user_id en session (vérifié par tests_phase/test_registration_flow.py)
- Effet de bord obligatoire : post_save(User, created=True) crée le Wallet de l'utilisateur (devise WALLET_DEFAULT_CURRENCY). Toute création de compte par une API doit passer par le modèle User pour que ce signal se déclenche
- AUTH_PASSWORD_VALIDATORS : 4 validateurs Django (similarité, longueur min, mot de passe courant, non numérique)

**Vérification d'adresse email obligatoire**
<br>_Confirmation d'email par lien signé, obligatoire avant usage du compte, avec connexion automatique après confirmation._
<br>Points d'entrée : `backend/leoTrade/settings/base.py:205,214-216`, `backend/core/checks.py:production_configuration_checks (leotrade.E017)`

- ACCOUNT_EMAIL_VERIFICATION='mandatory' : le check de déploiement leotrade.E017 fait échouer la prod si on relâche cette règle
- ACCOUNT_CONFIRM_EMAIL_ON_GET=False : la confirmation ne s'opère QUE sur POST (le GET affiche une page de confirmation) — protège des scanners de liens des clients mail
- ACCOUNT_LOGIN_ON_EMAIL_CONFIRMATION=True : l'utilisateur est connecté automatiquement une fois l'email confirmé
- ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS=3
- Tous les emails transactionnels doivent rester multipart (txt + html), de marque LeoTrade, préfixe de sujet '[LeoTrade] ' (test_registration_flow.py verrouille les 11 familles d'emails)
- Les checks leotrade.E005/E015/E016 bloquent la prod si le SMTP est absent/placeholder : sans SMTP, inscription et reset sont cassés

**Connexion par email / mot de passe (session Django)**
<br>_Authentification allauth par email, session serveur, redirection vers le dashboard._
<br>Points d'entrée : `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/leoTrade/settings/base.py:156-158 (AUTHENTICATION_BACKENDS), 190-203 (REST_FRAMEWORK), 229-231`, `backend/leoTrade/settings/prod.py (cookies de session)`

- Deux backends d'auth : ModelBackend puis allauth AuthenticationBackend — l'ordre doit être conservé (admin Django + allauth)
- ACCOUNT_SESSION_REMEMBER=False : pas de 'se souvenir de moi', session non persistante
- Prod : SESSION_COOKIE_AGE=3600 + SESSION_SAVE_EVERY_REQUEST=True => session glissante d'1h, backend cached_db, cookies HttpOnly/Secure/SameSite=Lax
- Prod : CSRF_COOKIE_HTTPONLY=True — le JS ne peut pas lire le cookie CSRF ; le front doit lire le token injecté dans le HTML et l'envoyer en header X-CSRFToken (contrainte explicitement documentée dans prod.py)
- Le template de login ne doit afficher aucune donnée de marché simulée avant authentification (account/base.html + test_production_hardening.py:294)

**Déconnexion**
<br>_Déconnexion par POST avec page de confirmation, accessible depuis la sidebar._
<br>Points d'entrée : `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/leoTrade/settings/base.py:231 (ACCOUNT_LOGOUT_REDIRECT_URL)`

- La déconnexion effective exige un POST + CSRF (le GET n'affiche qu'une confirmation)
- Redirection post-logout forcée vers /accounts/login/
- ACCOUNT_LOGOUT_ON_PASSWORD_CHANGE=False : changer son mot de passe ne déconnecte pas les sessions existantes

**Réinitialisation du mot de passe par email**
<br>_Demande de lien de réinitialisation, puis définition d'un nouveau mot de passe via clé signée._
<br>Points d'entrée : `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/leoTrade/settings/base.py:209,217`

- Anti-énumération stricte : un email est envoyé même pour une adresse inconnue (contenu unknown_account_message, 'aucun compte LeoTrade') et la redirection est strictement identique dans les deux cas — verrouillé par tests_phase/test_registration_flow.py
- ACCOUNT_LOGIN_ON_PASSWORD_RESET=False : pas de connexion automatique après réinitialisation
- Le template from_key gère explicitement l'état 'lien invalide ou expiré' et propose un logout d'étape (le flux allauth connecte temporairement l'utilisateur pendant l'étape de clé)

**Changement et définition du mot de passe**
<br>_Changement de mot de passe avec ancien mot de passe, et définition d'un mot de passe pour un compte qui n'en a pas._
<br>Points d'entrée : `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/leoTrade/settings/base.py:161-165, 213`

- Le changement exige oldpassword + password1 + password2 ; la définition (set) n'est accessible que si le compte n'a pas de mot de passe utilisable
- ACCOUNT_EMAIL_NOTIFICATIONS=True : un email de notification part à chaque changement/définition de mot de passe — ne pas le supprimer, c'est un contrôle de sécurité
- Les 4 AUTH_PASSWORD_VALIDATORS s'appliquent

**Gestion des adresses email du compte**
<br>_Lister ses adresses, en ajouter une, définir la primaire, renvoyer la vérification, supprimer une adresse._
<br>Points d'entrée : `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/leoTrade/settings/base.py:206,213`

- Quatre actions distinctes sur le même endpoint, discriminées par le name du bouton submit (action_primary / action_send / action_remove / action_add)
- ACCOUNT_UNIQUE_EMAIL : une adresse ne peut appartenir qu'à un compte
- Les emails de notification (email_changed, email_deleted) partent automatiquement

**Ré-authentification avant action sensible**
<br>_allauth réclame le mot de passe à nouveau avant les opérations sensibles si l'authentification date de plus de 5 minutes._
<br>Points d'entrée : `backend/leoTrade/settings/base.py:219-220 (ACCOUNT_REAUTHENTICATION_REQUIRED, ACCOUNT_REAUTHENTICATION_TIMEOUT=300)`

- ACCOUNT_REAUTHENTICATION_REQUIRED=True + timeout 300 s : toute action sensible (changement d'email/mot de passe, gestion MFA) exige une ré-authentification au-delà de 5 minutes
- C'est un invariant de sécurité : une API sans step-up auth équivaut à une régression fonctionnelle

**MFA TOTP et codes de récupération**
<br>_Second facteur par application TOTP et codes de récupération, fourni par allauth.mfa._
<br>Points d'entrée : `backend/leoTrade/settings/base.py:78 (allauth.mfa dans INSTALLED_APPS), 263-266 (MFA_*)`, `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/core/migrations/0002_migrate_legacy_totp.py`

- MFA_SUPPORTED_TYPES=['totp','recovery_codes'] : pas de WebAuthn ni de SMS OTP aujourd'hui
- MFA_RECOVERY_CODES_SHOW_ONCE=True : les codes ne sont affichés qu'une seule fois
- MFA_TRUST_ENABLED=False : aucun appareil de confiance, le second facteur est redemandé à chaque connexion
- django_otp / otp_totp / otp_static restent installés UNIQUEMENT pour l'historique : OTPMiddleware n'est pas actif, django_otp n'authentifie rien
- La migration core.0002 convertit les TOTPDevice confirmés en Authenticator allauth (un seul par utilisateur, le plus récemment utilisé), est idempotente (saute les utilisateurs déjà migrés) et irréversible (reverse=noop) : ne pas la rejouer, ne pas supprimer la table otp_totp avant d'avoir vérifié la migration en production

**États de compte bloquant l'accès**
<br>_Écrans dédiés aux états qui empêchent l'usage : compte inactif, email non vérifié, inscriptions fermées._
<br>Points d'entrée : `backend/leoTrade/urls.py: include("allauth.urls")`, `backend/templates/account/*.html`

- Un User avec is_active=False est rejeté à la connexion avec un écran dédié (pas un message d'erreur générique)
- L'accès à une ressource exigeant un email vérifié renvoie vers la gestion des adresses email
- Ces trois états doivent exister comme états d'erreur explicites côté React/Flutter (contrainte 'gestion des erreurs et états vides')

**Login admin Django durci par allauth**
<br>_La page de login de l'admin Django est enveloppée par secure_admin_login d'allauth, donc soumise au flux allauth (MFA, limites de taux)._
<br>Points d'entrée : `backend/leoTrade/urls.py:20-27 (secure_admin_login)`, `backend/dashboard/admin.py:KYCProfileAdmin`

- L'import de secure_admin_login est protégé par try/except ImportError (compat allauth historique) : si l'import échoue, l'admin retombe silencieusement sur le login Django natif — à surveiller lors d'un changement de version d'allauth
- KYCProfileAdmin : created_at, updated_at, reviewed_at sont en lecture seule ; recherche par email utilisateur, nom complet, numéro de pièce

**Consultation de son dossier KYC**
<br>_Page utilisateur affichant le statut de son dossier KYC et le motif de rejet éventuel._
<br>Points d'entrée : `backend/dashboard/views.py:kyc_dashboard`, `backend/dashboard/models.py:KYCProfile`

- Le KYCProfile est créé à la volée par get_or_create à la première visite (aucun signal de création) : il ne faut pas supposer qu'il existe, tout accès doit être tolérant à l'absence (c'est ce que fait wallet/views.py:_user_kyc_status via getattr)
- Relation OneToOne stricte : un seul dossier par utilisateur, statut initial NOT_STARTED
- Cinq statuts : NOT_STARTED, PENDING, UNDER_REVIEW, APPROVED, REJECTED. UNDER_REVIEW existe en modèle et est géré par l'UI wallet mais aucune vue ne le positionne aujourd'hui (transition uniquement possible via l'admin Django)

**Soumission et resoumission du dossier KYC**
<br>_Formulaire multi-étapes d'identité (état civil, document d'identité, selfie, justificatif de domicile) avec upload de fichiers validés._
<br>Points d'entrée : `backend/dashboard/views.py:kyc_submit`, `backend/dashboard/form.py:KYCSubmissionForm._validate_uploaded_file`, `backend/notifications/shortcuts.py:notify`

- Champs obligatoires au clean() : full_name, date_of_birth, nationality, phone, address, id_document_type, id_document_number, id_document_front, selfie_photo, proof_of_address. Seul id_document_back est facultatif
- Validation de fichier en trois couches à préserver : taille <= settings.KYC_MAX_FILE_SIZE_BYTES (10 Mo par défaut ; prod plafonne aussi DATA_UPLOAD_MAX_MEMORY_SIZE/FILE_UPLOAD_MAX_MEMORY_SIZE à 10 Mo), extension dans {.jpg,.jpeg,.png,.pdf}, content_type dans {image/jpeg,image/png,application/pdf}, PUIS vérification des magic bytes (ff d8 ff / \x89PNG / %PDF-). Le contrôle de signature est le seul qui résiste à un content_type falsifié
- Le fichier est relu à l'offset 0 après lecture de l'entête (seek(0)) — toute réécriture doit conserver ce rembobinage sinon le fichier est enregistré tronqué
- À la soumission : status forcé à PENDING et rejection_reason vidé. Une resoumission efface donc le motif de rejet précédent
- Le document type doit appartenir à DOCUMENT_TYPE_CHOICES (NATIONAL_ID, PASSPORT, DRIVING_LICENSE, RESIDENCE_PERMIT)
- La notification KYC_SUBMITTED est envoyée via notify() qui est fail-safe : un échec de notification ne doit jamais faire échouer la soumission

**File de revue KYC (staff)**
<br>_Liste paginée et filtrable des dossiers KYC pour l'équipe conformité._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_list`

- Accès réservé via @staff_member_required (redirection vers le login admin, pas un 403)
- Recherche q sur user__email, full_name et id_document_number, combinée par union de querysets (|) — peut produire des doublons, comportement actuel à reproduire ou à corriger explicitement
- Pagination fixe à 30 éléments, tri par -updated_at
- Les choix de statut du filtre sont lus depuis KYCProfile.STATUS_CHOICES

**Détail d'un dossier KYC (staff)**
<br>_Fiche complète d'un dossier avec les informations déclarées, les liens vers les documents et les formulaires de décision._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_detail`

- Accès staff uniquement ; select_related('user','reviewed_by') pour afficher le relecteur
- Les liens vers les documents ne pointent jamais sur MEDIA_URL mais sur la vue de téléchargement contrôlée

**Téléchargement contrôlé des documents KYC**
<br>_Service de fichiers d'identité par une vue dédiée, jamais par une URL média publique._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_document`

- Liste blanche stricte des quatre champs autorisés (id_document_front, id_document_back, selfie_photo, proof_of_address) : tout autre field_name renvoie 404 — garde-fou contre la traversée d'attributs du modèle
- 404 si le champ est vide ou si le fichier est illisible sur le disque (FileNotFoundError/OSError interceptées)
- Entêtes imposés : Cache-Control 'private, no-store' et X-Content-Type-Options 'nosniff' — invariant anti-fuite de pièces d'identité (pas de mise en cache proxy/navigateur)
- Le content_type est deviné depuis le nom de fichier, défaut application/octet-stream
- MEDIA_ROOT n'est servi par aucune route dans leoTrade/urls.py : les documents ne sont accessibles que par cette vue

**Approbation d'un dossier KYC**
<br>_Validation du dossier par un membre du staff, avec note interne et notification au client._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_approve`, `backend/notifications/events.py: KYC_APPROVED`

- @staff_member_required + @require_POST : aucune approbation par GET
- Écrit status=APPROVED, reviewed_by=utilisateur staff courant, reviewed_at=now, admin_note depuis le POST, et VIDE rejection_reason — un dossier approuvé ne doit jamais conserver un ancien motif de rejet
- save(update_fields=[...]) explicite : ne pas remplacer par un save() complet sans vérifier les effets sur les autres champs
- APPROVED est la seule valeur qui débloque les retraits wallet : toute modification de la machine à états doit être évaluée contre wallet/views.py:_can_user_withdraw
- La notification KYC_APPROVED (catégorie ACCOUNT, priorité HIGH) passe par notify() fail-safe : un échec de notification ne doit pas annuler l'approbation

**Rejet d'un dossier KYC**
<br>_Rejet motivé du dossier, le motif étant communiqué au client et affiché sur sa page KYC._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_reject`, `backend/notifications/events.py: KYC_REJECTED`

- @staff_member_required + @require_POST
- rejection_reason est requis côté template mais le serveur applique un repli 'Dossier rejeté.' si la valeur est vide : un dossier REJECTED a toujours un motif non vide
- status=REJECTED, reviewed_by, reviewed_at et admin_note sont écrits dans la même opération
- La notification KYC_REJECTED transporte payload={'rejection_reason': ...} : les clients affichent ce motif
- Distinction à préserver : admin_note est une note interne jamais montrée au client, rejection_reason est le message client (affiché sur kyc_dashboard.html)

**Porte KYC sur les retraits de fonds**
<br>_Un retrait wallet n'est possible que si le dossier KYC de l'utilisateur est approuvé._
<br>Points d'entrée : `backend/wallet/views.py:_user_kyc_status`, `backend/wallet/views.py:_can_user_withdraw`, `backend/wallet/views.py:wallet_withdraw`, `backend/wallet/views.py:wallet_dashboard`

- Règle dure : status != 'APPROVED' => retrait refusé avec le message 'Votre dossier KYC doit être approuvé avant tout retrait.'
- Absence totale de KYCProfile (getattr renvoie None) => statut None => refus (fail-closed)
- Le garde est évalué AVANT toute validation de formulaire dans la branche POST, et redirige vers kyc-dashboard : aucun traitement de retrait ne doit démarrer sur un KYC non approuvé
- L'UI distingue trois états visuels (APPROVED / PENDING ou UNDER_REVIEW / autre) : à reproduire côté React et Flutter
- Le statut est aussi exposé en lecture dans le contexte des pages wallet (kyc_status, can_withdraw, withdraw_block_reason)

**Cloisonnement des données par propriétaire (API)**
<br>_Permission objet générique IsOwner combinée au filtrage systématique des querysets par utilisateur dans tous les ViewSets REST._
<br>Points d'entrée : `backend/api/permissions.py:IsOwner`, `backend/api/views/portfolio.py (get_queryset filter user=/portfolio__user=)`, `backend/api/views/execution.py`, `backend/api/views/risk.py`, `backend/api/views/ai.py`, `backend/api/views/brokers.py`, `backend/leoTrade/settings/base.py:190-203 (DEFAULT_PERMISSION_CLASSES=IsAuthenticated)`

- IsOwner n'implémente QUE has_object_permission : il ne filtre pas les listes. L'isolation des collections repose entièrement sur get_queryset — tout nouveau ViewSet qui oublie ce filtre provoque une fuite inter-utilisateurs
- Résolution du propriétaire dans IsOwner : obj.user_id, sinon obj.portfolio.user_id, sinon refus explicite (return False) — fail-closed à conserver
- DEFAULT_PERMISSION_CLASSES=IsAuthenticated : aucun endpoint API public par défaut
- Deux classes d'authentification acceptées simultanément : session (web) et JWT (mobile)

**Rôles et habilitations (staff / superuser)**
<br>_Le modèle d'autorisation repose uniquement sur les flags Django is_staff et is_superuser, sans modèle de rôle dédié._
<br>Points d'entrée : `backend/dashboard/views.py (staff_member_required x5)`, `backend/core/health.py:health_diagnostics`, `backend/strategies/models.py:15,22,31,45`, `backend/strategies/views.py:270,645`, `backend/ai_assistant/api.py:155`, `backend/notifications/shortcuts.py:notify_admins`

- Trois niveaux seulement : anonyme, utilisateur authentifié propriétaire de ses données, staff. Aucun groupe ni permission Django granulaire n'est utilisé
- is_staff donne accès en lecture/écriture aux dossiers KYC de TOUS les utilisateurs, y compris aux pièces d'identité : toute refonte RBAC doit garder ce privilège explicite et traçable (reviewed_by)
- is_staff contourne la propriété des stratégies (peut gérer celles des autres)
- notify_admins ne notifie que les superusers actifs (is_superuser=True, is_active=True)
- health_diagnostics renvoie 403 JSON pour un non-staff (et non une redirection) — comportement différent de staff_member_required utilisé ailleurs

**Contexte de session global de l'utilisateur authentifié**
<br>_Injection dans chaque page authentifiée du portefeuille par défaut, du wallet et du mode de trading effectif._
<br>Points d'entrée : `backend/core/context_processors.py:global_trading_context`, `backend/core/context_processors.py:portfolio_context`, `backend/core/context_processors.py:_resolve_trading_mode`

- Le mode de trading affiché n'est JAMAIS la session seule. Ordre de vérité : (1) mode du broker_account du portfolio par défaut, (2) vote des BrokerAccount actifs — un seul LIVE suffit à afficher LIVE, (3) valeur en session, (4) PAPER par défaut. Cet ordre corrige un incident réel (sidebar LIVE / broker PAPER sur l'ordre #41)
- La session est resynchronisée sur la vérité broker à chaque requête
- Les deux processeurs renvoient {} si l'utilisateur n'est pas authentifié
- Les accès base sont protégés contre ProgrammingError/OperationalError (migrations non appliquées) et renvoient None plutôt que de casser la page

**Authentification des connexions WebSocket**
<br>_Les WebSocket sont authentifiés par la session Django via AuthMiddlewareStack, avec isolation par groupe utilisateur._
<br>Points d'entrée : `backend/leoTrade/asgi.py (AllowedHostsOriginValidator + AuthMiddlewareStack)`, `backend/notifications/consumers.py:NotificationCenterConsumer.connect`, `backend/notifications/routing.py`

- Une connexion non authentifiée est fermée avec le code applicatif 4401 — code à conserver, les clients s'en servent pour déclencher un renouvellement de session
- Isolation stricte par groupe user_notifications_{user.id}
- accept() est appelé AVANT group_add : si Redis est indisponible, la socket reste vivante au lieu d'échouer (pattern de résilience explicite, à ne pas inverser)
- AllowedHostsOriginValidator : l'origine du client doit figurer dans ALLOWED_HOSTS

**Traçabilité des requêtes et du contexte utilisateur**
<br>_Identifiant de corrélation par requête et injection de l'utilisateur dans le contexte de log, plus un service d'audit applicatif._
<br>Points d'entrée : `backend/core/middleware.py:RequestIDMiddleware`, `backend/core/middleware.py:RequestContextMiddleware`, `backend/core/logging.py:set_request_context/clear_request_context`, `backend/audit/services.py:AuditLogService`

- X-Request-ID fourni par le client est réutilisé, sinon généré ; il est toujours renvoyé dans la réponse
- RequestContextMiddleware doit rester APRÈS AuthenticationMiddleware : c'est le seul endroit où request.user est disponible pour attacher user_id aux logs
- clear_request_context() est appelé en process_response ET en process_exception : sans cela le contexte d'un utilisateur fuite sur la requête suivante du même worker
- AuditLogService n'écrit pas en base : l'audit d'authentification est purement journalisé (aucun modèle d'historique de connexion n'existe)

**Protection de l'endpoint de métriques**
<br>_L'endpoint Prometheus /metrics est protégé par un bearer token, et fermé si aucun token n'est configuré hors DEBUG._
<br>Points d'entrée : `backend/core/middleware.py:MetricsAccessMiddleware`, `backend/leoTrade/settings/base.py:322 (METRICS_AUTH_TOKEN)`, `backend/core/checks.py (leotrade.E009)`

- Comparaison du token en temps constant via hmac.compare_digest — ne pas remplacer par ==
- Sans METRICS_AUTH_TOKEN et hors DEBUG, l'endpoint renvoie 503 (fail-closed) au lieu d'exposer les métriques
- Le check de déploiement leotrade.E009 échoue si le token est absent

**Contrôles de configuration de sécurité au déploiement**
<br>_Checks Django personnalisés qui bloquent un déploiement dont la configuration d'authentification, d'email ou de secrets est dangereuse._
<br>Points d'entrée : `backend/core/checks.py:production_configuration_checks`, `backend/leoTrade/settings/prod.py`

- leotrade.E017 : ACCOUNT_EMAIL_VERIFICATION doit valoir 'mandatory'
- leotrade.E005/E015/E016 : backend SMTP réel obligatoire, pas de placeholders REPLACE_, TLS et SSL mutuellement exclusifs — l'inscription et le reset de mot de passe en dépendent
- leotrade.E001/E002/E003/E004 : DEBUG off, ALLOWED_HOSTS explicite sans wildcard, SITE_BASE_URL en HTTPS et présent dans CSRF_TRUSTED_ORIGINS
- leotrade.E008 : FERNET_SECRET_KEY doit être une clé Fernet valide (base.py lève RuntimeError si elle est absente, au chargement des settings)
- prod.py refuse de démarrer si SECRET_KEY est faible (valeur par défaut, préfixe django-insecure-, moins de 50 caractères ou moins de 5 caractères distincts)
- prod.py impose SECURE_SSL_REDIRECT, HSTS 1 an avec preload, cookies Secure/HttpOnly, SECURE_PROXY_SSL_HEADER pour le reverse proxy

</details>

<details><summary>Pièges de migration repérés</summary>

- Aucun endpoint d'authentification REST n'existe : rest_framework_simplejwt est installé et déclaré dans DEFAULT_AUTHENTICATION_CLASSES, mais api/urls.py ne contient qu'un DefaultRouter métier et SIMPLE_JWT n'est pas configuré. Tout le flux de compte (signup, login, logout, reset, MFA, emails) n'existe qu'en vues allauth rendues en HTML. C'est le plus gros chantier du domaine pour Flutter.
- Aucun endpoint /me : le contexte utilisateur (portfolio par défaut, wallet, mode de trading, statut KYC) n'est disponible que via des context processors de templates (core/context_processors.py). Sans équivalent API, les clients vont le reconstruire et réintroduire la divergence 'sidebar LIVE / broker PAPER' que _resolve_trading_mode corrige.
- Tout le domaine KYC (utilisateur ET back-office) est en vues Django + templates, sans serializer ni service : la logique métier (validation des fichiers, forçage du statut PENDING, purge de rejection_reason, écriture de reviewed_by/reviewed_at) vit dans dashboard/form.py et dashboard/views.py. Il faut l'extraire dans un KYCService avant d'exposer l'API, sinon la règle sera dupliquée entre web et mobile.
- Le garde KYC des retraits est codé dans la vue (wallet/views.py:_can_user_withdraw) et non dans un service : une API wallet écrite à côté contournerait silencieusement l'obligation 'KYC APPROVED avant retrait'.
- IsOwner ne filtre que les objets, jamais les listes. Toute la non-fuite inter-utilisateurs repose sur le fait que chaque get_queryset filtre par user. Un ViewSet ajouté sans ce filtre expose les données de tous les comptes sans erreur visible.
- Le statut UNDER_REVIEW existe dans KYCProfile.STATUS_CHOICES et est traité par l'UI wallet, mais aucune vue ne le positionne : il n'est atteignable que par l'admin Django. Soit on l'implémente (prise en charge d'un dossier par un agent), soit on documente qu'il est vestigial.
- MFA fonctionnel mais invisible : allauth.mfa est configuré (TOTP + codes de récupération) et ses URLs sont montées via include('allauth.urls'), mais aucun template n'est personnalisé dans templates/ et aucun lien n'existe dans la navigation. Les pages MFA sont donc rendues avec le design allauth par défaut et atteignables seulement par URL directe. Même constat pour /accounts/password/change/ et /accounts/email/.
- Dette de version allauth : requirements.txt épingle django-allauth[mfa]==65.18.0 alors que le venv local contient django-allauth 0.57.2 et django-allauth-2fa 0.12.0 (incompatibles avec allauth.mfa). settings/base.py contient un branchement conditionnel sur la version (if version('django-allauth').startswith('0.')) et urls.py un try/except sur secure_admin_login : en cas de retour à une vieille version, le durcissement du login admin saute silencieusement.
- django_otp, otp_totp et otp_static restent dans INSTALLED_APPS sans OTPMiddleware : ils ne servent plus qu'à core/migrations/0002_migrate_legacy_totp.py. Supprimer ces apps avant d'avoir confirmé la migration en production détruirait les secrets TOTP historiques (la migration est irréversible, reverse=noop).
- CSRF_COOKIE_HTTPONLY=True en production : le SPA React ne pourra pas lire le cookie CSRF en JavaScript. Soit on bascule l'API sur JWT sans cookie, soit on relâche ce réglage en connaissance de cause (il est documenté comme un durcissement OWASP volontaire dans prod.py).
- core/rate_limit.py:SimpleRateLimitMiddleware est défini mais n'est référencé dans AUCUN MIDDLEWARE : c'est du code mort. Il n'existe donc aujourd'hui aucune limitation de taux applicative sur le login/signup autre que celle fournie par défaut par allauth (ACCOUNT_RATE_LIMITS n'est pas configuré ; les anciens ACCOUNT_LOGIN_ATTEMPTS_LIMIT/TIMEOUT sont dans le bloc commenté de base.py).
- Aucun journal d'audit en base pour l'authentification : AuditLogService n'écrit que des logs. Il n'existe ni historique de connexions, ni liste des sessions actives, ni notification de connexion suspecte effective (l'event SUSPICIOUS_LOGIN est déclaré dans notifications/events.py mais n'est émis nulle part dans le code).
- Les documents KYC sont des fichiers locaux (MEDIA_ROOT=media/, FileSystemStorage) servis uniquement par admin_kyc_document. Une migration vers un stockage objet ou l'ajout d'une route static(MEDIA_URL) ferait sauter les entêtes 'private, no-store' + nosniff et rendrait les pièces d'identité accessibles par URL devinable.
- CORS_ALLOWED_ORIGINS est piloté par variable d'environnement mais CORS_ALLOW_CREDENTIALS n'est pas défini : une authentification par cookie depuis un front React sur un autre domaine ne fonctionnera pas sans ce réglage.
- L'arborescence a été déplacée pendant la session : tout le projet Django se trouve désormais sous /Users/ogahserge/Documents/leoTrade/backend/ (monorepo backend/ web/ mobile/ infrastructure/ docs/). Les chemins cités ici sont relatifs à la racine du dépôt.

</details>

---

### brokers

`23 fonctionnalités` — API : **2 prêtes, 6 partielles, 15 à exposer**

**Modèles** : `BrokerAccount`, `BrokerCredential`, `BrokerConstraint`, `BrokerExternalRef`

**Tâches Celery** : `brokers.tasks.test_broker_connection_task`, `brokers.tasks.sync_broker_constraint_task`, `brokers.tasks.check_all_brokers_health_task (beat: */5 min)`, `brokers.tasks_deriv_sync.sync_deriv_balance_task (beat: toutes les 60 s)`, `brokers.tasks_deriv_sync.sync_deriv_positions_task (beat: toutes les 60 s)`, `brokers.tasks_deriv_sync.sync_single_deriv_contract_task (à la demande, countdown=5 s après submit_order Deriv)`

**Canaux WebSocket** : `AUCUN consumer Django Channels pour ce domaine — leoTrade/asgi.py n'inclut pas de routing brokers (seuls ai_assistant, notifications, execution, portfolio, trading, market)`, `Sortant (client WS) — wss://ws.binaryws.com/websockets/v3?app_id={app_id} : DerivStreamer, souscriptions balance / transaction / proposal_open_contract`, `Sortant (client WS) — URL OTP éphémère Deriv obtenue par POST /trading/v1/options/accounts/{id}/otp : DerivClient.connect_with_otp_url, seul chemin autorisant proposal/buy/sell`, `Sortant (client WS) — wss://api.derivws.com/trading/v1/options/ws/public : DerivClient.connect_public, données publiques uniquement (ne supporte PAS le trading)`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Liste des comptes broker** | 🟡 | WEB/MOBILE |  | L'API ne renvoie ni les agrégats de la page (active_brokers_count, default_broker) ni les indicateurs booléens "credentials configurés" par type de secret. Il faut des champs calculés en lecture seule (has_api_key, has_api_secret, has_password, has_deriv_token) pour reproduire l'écran sans jamais exposer les valeurs. |
| **Création d'un compte broker** | 🟡 | WEB/MOBILE |  | BrokerAccountSerializer n'expose aucun champ secret (api_key, api_secret, password, deriv_token) : un client React/Flutter ne peut pas configurer un broker de bout en bout. Il faut des champs write-only + le déclenchement de la notification BROKER_ACCOUNT_CREATED dans perform_create (aujourd'hui uniquement dans la vue Django), et la traduction des ValidationError de full_clean() en erreurs 400 par champ. |
| **Modification d'un compte broker** | 🟡 | WEB/MOBILE |  | Pas d'écriture des secrets via l'API et pas de notification BROKER_ACCOUNT_UPDATED (émise seulement par la vue Django). |
| **Suppression d'un compte broker** | ✅ | WEB/MOBILE |  | — |
| **Définir le broker par défaut** | ❌ | WEB/MOBILE |  | Aucune action DRF n'existe. Il faut POST /api/v1/brokers/{id}/set-default/ reproduisant exactement la séquence reset global → affectation, plus la notification BROKER_DEFAULT_CHANGED. |
| **Test de connexion broker** | 🟡 | WEB/MOBILE |  | L'action DRF fait le vrai test mais n'émet pas les notifications BROKER_CONNECTION_OK / BROKER_CONNECTION_FAILED que la vue Django envoie. À brancher dans le service, pas dans la vue. |
| **Centre Broker — santé des comptes** | 🟡 | WEB/MOBILE |  | Endpoint hors DRF: pas sous /api/v1/, pas d'authentification JWT (session uniquement), pas de serializer ni de schéma OpenAPI, pagination absente. Aucun template ne le consomme aujourd'hui — l'écran "Centre Broker" est donc à construire côté React/Flutter sur un endpoint DRF équivalent. |
| **Health check périodique des comptes actifs** | ❌ | WEB/MOBILE |  | Aucun endpoint pour déclencher un health check à la demande ni pour consulter le dernier résultat agrégé (checked/healthy). Le détail par compte n'est lisible que via /brokers/health/api/. |
| **Stockage chiffré des secrets broker et audit des accès** | ❌ | WEB/MOBILE |  | Aucun endpoint n'accepte ni n'expose de secret. Il faut des endpoints write-only d'upsert et de rotation par (compte, secret_type) et, en lecture, uniquement des booléens "configuré" + une date de dernière rotation. Ne jamais renvoyer de valeur, même tronquée. |
| **BrokerGateway — retry sélectif et circuit breaker par compte** | ❌ | WEB |  | L'état du circuit n'est lisible que via /brokers/health/api/ et aucun endpoint ne permet de le réarmer manuellement après résolution d'un incident. |
| **Synchronisation des contraintes d'instrument broker** | ✅ | WEB/MOBILE |  | — |
| **Normalisation quantité / prix avant envoi d'ordre** | ❌ | WEB/MOBILE |  | Aucun endpoint de "preview" ne restitue la quantité et le prix réellement normalisés avant envoi. Un client mobile ne peut pas afficher à l'utilisateur ce qui partira effectivement chez le broker. |
| **Connecteur Binance (spot)** | ❌ | WEB/MOBILE |  | Aucun endpoint n'expose les capacités ni l'état du connecteur (symboles disponibles, types d'ordre supportés, statut du rate limit). |
| **Connecteur MetaTrader 5** | ❌ | WEB/MOBILE |  | Aucun endpoint n'expose l'état du terminal MT5 ni la disponibilité de la plateforme (le connecteur est inutilisable hors Windows). |
| **Connecteur Deriv (sessions WebSocket one-shot)** | ❌ | WEB/MOBILE |  | Aucun endpoint n'expose les symboles/contrats disponibles (contracts_for, active_symbols) ni les paramètres de contrat (duration, duration_unit, multiplier) que le client doit choisir avant d'envoyer un ordre. |
| **Streamer WebSocket Deriv persistant** | ❌ | WEB/MOBILE | ⚡ | Le temps réel s'arrête au backend: aucun consumer Channels ne relaie ces événements vers un client. Pour React/Flutter il faut republier balance/contrats sur un canal WS applicatif (ou SSE) authentifié par utilisateur. |
| **Fallback Celery de synchronisation Deriv** | ❌ | WEB/MOBILE |  | Aucun endpoint "resynchroniser maintenant" pour un compte Deriv, alors que l'écran broker en a besoin (bouton de resync manuel). |
| **Réconciliation du solde Deriv vers le ledger du portefeuille** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint n'expose l'écart broker/local ni l'historique des ajustements BROKER_IMPORT, alors que c'est l'information la plus utile pour expliquer une différence de solde à l'utilisateur. |
| **Synchronisation des contrats Deriv (ouverture, clôture, import externe)** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint n'expose l'état broker d'un contrat ni les trois chemins de rattachement. Le détail d'ordre API ne renvoie pas les BrokerExternalRef associées (information présente uniquement dans le template Django de détail d'ordre). |
| **Journalisation des transactions Deriv** | ❌ | WEB | ⚡ | Aucun endpoint n'expose ce journal de transactions broker. |
| **Mapping interne ↔ identifiants broker (BrokerExternalRef)** | ❌ | WEB/MOBILE |  | Les refs d'un ordre ne sont exposées que dans le template Django de détail d'ordre. Il faut les sérialiser dans le détail d'ordre API pour que Web et Mobile puissent afficher le contract_id / ticket / orderId réel. |
| **Bascule PAPER / LIVE d'un compte broker** | 🟡 | WEB/MOBILE |  | Le passage en LIVE se fait aujourd'hui par un simple PATCH du champ mode, sans confirmation, sans vérification que les credentials fonctionnent, et sans notification. Il faut une action dédiée (POST /api/v1/brokers/{id}/set-mode/) avec test de connexion préalable, confirmation explicite côté client et notification LIVE_MODE_ENABLED. |
| **Administration Django des comptes et credentials** | ❌ | WEB |  | Pas de surface d'administration multi-utilisateur hors admin Django (le domaine n'a aucune notion de rôle au-delà de la propriété du compte). |

<details><summary>Règles métier invariantes à préserver</summary>

**Liste des comptes broker**
<br>_Affiche les comptes broker de l'utilisateur avec le nombre de comptes actifs, le broker par défaut et un indicateur "credentials configurés" par type de broker._
<br>Points d'entrée : `backend/brokers/views.py:BrokerAccountListView`, `backend/api/views/brokers.py:BrokerAccountViewSet.get_queryset`, `backend/templates/brokers/broker_list.html`

- Cloisonnement strict: le queryset est toujours filtré sur user=request.user, côté vue Django comme côté DRF
- Tri par name (vue Django et API)
- Le template dérive un état "API configurée / Token configuré / Login MT5" en lisant les propriétés déchiffrantes broker.api_key / broker.deriv_token — chaque rendu de la liste déclenche donc un déchiffrement Fernet et un log d'audit credential.decrypted par compte

**Création d'un compte broker**
<br>_Crée un compte broker (BINANCE / MT5 / DERIV) en mode PAPER ou LIVE, avec saisie des secrets qui sont chiffrés dans BrokerCredential._
<br>Points d'entrée : `backend/brokers/views.py:BrokerAccountCreateView.form_valid`, `backend/brokers/forms.py:BrokerAccountForm.save`, `backend/brokers/models.py:BrokerAccount.clean`, `backend/brokers/models.py:BrokerAccount.set_secret`

- BrokerAccount.save() appelle systématiquement full_clean() — la validation modèle n'est jamais contournable, y compris en écriture partielle
- unique_together (user, name): deux comptes du même utilisateur ne peuvent pas porter le même nom
- Un seul compte is_default=True par utilisateur (validé dans clean(), AUCUNE contrainte DB équivalente)
- MT5: login ET server obligatoires. DERIV: deriv_app_id ET deriv_currency obligatoires. Validation par broker, levée en ValidationError par champ
- Les secrets ne sont JAMAIS stockés sur BrokerAccount: set_secret chiffre via CryptoService (Fernet) et fait update_or_create sur (broker_account, secret_type) → une seule credential active par type
- Un champ secret laissé vide dans le formulaire conserve la valeur chiffrée existante (on n'écrase jamais un secret avec une chaîne vide)
- status par défaut = DRAFT tant qu'aucun test de connexion n'a réussi
- Notification BROKER_ACCOUNT_CREATED émise par la vue après succès
- Le log d'échec (broker.create.invalid) ne consigne que les NOMS des champs en erreur, jamais les valeurs

**Modification d'un compte broker**
<br>_Met à jour la configuration d'un compte broker et, optionnellement, ses secrets._
<br>Points d'entrée : `backend/brokers/views.py:BrokerAccountUpdateView`, `backend/brokers/forms.py:BrokerAccountForm.save`

- Queryset restreint à user=request.user (impossible d'éditer le compte d'un autre)
- Mêmes invariants que la création (full_clean, is_default unique, champs requis par broker)
- Un champ secret vide = conservation; une valeur non vide = update_or_create de la credential, l'ancienne valeur est écrasée sans historisation
- Notification BROKER_ACCOUNT_UPDATED émise par la vue
- Les champs status / last_connection_status / last_connection_error / last_connected_at sont read_only côté API: ils n'appartiennent qu'au moteur de connexion

**Suppression d'un compte broker**
<br>_Supprime un compte broker après page de confirmation._
<br>Points d'entrée : `backend/brokers/views.py:BrokerAccountDeleteView`, `backend/templates/brokers/broker_confirm_delete.html`

- Queryset restreint à user=request.user
- La suppression cascade sur BrokerCredential (on_delete=CASCADE) ET sur BrokerExternalRef (related_name=external_refs, CASCADE): tout le mapping ordres/contrats ↔ broker est détruit avec le compte
- AUCUN garde-fou actuel: ni vérification de positions ouvertes, ni d'ordres en vol, ni notification

**Définir le broker par défaut**
<br>_Marque un compte comme broker par défaut de l'utilisateur, en démarquant tous les autres._
<br>Points d'entrée : `backend/brokers/views.py:BrokerAccountSetDefaultView.post`

- ORDRE OBLIGATOIRE: le reset global (update is_default=False sur tous les comptes du user) doit se faire AVANT de poser is_default=True sur la cible, sinon le full_clean() déclenché par save() lève "Un seul broker par utilisateur peut être défini par défaut"
- Le reset utilise .update() (pas de save() → pas de full_clean) : c'est volontaire, un save() par compte revaliderait chaque compte et pourrait échouer sur un compte MT5/DERIV incomplet
- Compte introuvable ou appartenant à un autre user → message d'erreur + redirect, jamais de 404 brute
- Notification BROKER_DEFAULT_CHANGED après succès

**Test de connexion broker**
<br>_Vérifie que les credentials d'un compte permettent de joindre le broker, et persiste le résultat sur le compte._
<br>Points d'entrée : `backend/brokers/services_connection.py:BrokerConnectionService.test_connection`, `backend/api/views/brokers.py:BrokerAccountViewSet.test_connection`, `backend/brokers/views.py:BrokerAccountTestConnectionView.post`, `backend/brokers/tasks.py:test_broker_connection_task`

- RÉFÉRENCE = BrokerConnectionService.test_connection: @transaction.atomic, instancie le vrai client via BrokerClientFactory et appelle client.test_connection()
- Le résultat est TOUJOURS persisté, succès comme échec: last_connection_status, last_connection_error, last_connected_at, status (ACTIVE | ERROR). Le service ne laisse jamais remonter l'exception — il renvoie {success: False, error: str(exc)}
- Côté API, un échec est rendu en HTTP 400 avec {"status": "error", "error": ...}
- DIVERGENCE À NE PAS REPRENDRE: la vue Django BrokerAccountTestConnectionView ne teste rien — elle met ok=True en dur pour BINANCE, MT5 et DERIV, puis persiste status=ACTIVE et notifie BROKER_CONNECTION_OK sans le moindre appel broker. Seul un code broker inconnu produit un échec
- test_broker_connection_task ne traite que is_active=True et renvoie {"status": "missing"} sinon — jamais d'exception
- Notifications BROKER_CONNECTION_OK / BROKER_CONNECTION_FAILED (message tronqué à 500 caractères dans le payload)

**Centre Broker — santé des comptes**
<br>_Endpoint JSON exposant pour chaque compte: statut de connexion, état du circuit breaker, dernière erreur et date de dernière synchronisation._
<br>Points d'entrée : `backend/brokers/views.py:broker_health_api`, `backend/infrastructure/broker_clients/gateway.py:BrokerGateway.circuit_state`

- L'endpoint ne doit déclencher AUCUNE I/O broker: BrokerGateway est instancié avec client=object() pour ne lire que l'état Redis du circuit (indispensable, car construire un vrai client MT5 ferait un initialize/login bloquant)
- circuit_state ∈ CLOSED | OPEN | HALF_OPEN | UNAVAILABLE ; UNAVAILABLE signifie panne du cache, pas panne broker
- last_sync_at = max(BrokerExternalRef.last_seen_at) du compte
- Tri -is_default puis name
- Données réelles uniquement — aucune valeur simulée

**Health check périodique des comptes actifs**
<br>_Tâche planifiée qui teste tous les comptes broker actifs et persiste leur statut, alimentant le Centre Broker._
<br>Points d'entrée : `backend/brokers/tasks.py:check_all_brokers_health_task`

- Passe obligatoirement par BrokerGateway (retry + circuit breaker) et non par le client brut, pour ne pas déclencher de tempête de retries
- CircuitOpenError est traité comme un échec normal, SANS log warning: un circuit déjà ouvert n'est pas une anomalie nouvelle
- Toute autre exception est capturée, tronquée à 2000 caractères et loggée — la tâche ne doit jamais planter et ne doit jamais interrompre la boucle sur les comptes suivants
- last_connected_at est mis à jour même en échec (c'est la date du dernier CHECK, pas de la dernière connexion réussie)
- Ne traite que is_active=True
- Retourne {checked, healthy}

**Stockage chiffré des secrets broker et audit des accès**
<br>_Chiffrement Fernet des API keys, secrets, mots de passe et tokens, avec journalisation de chaque déchiffrement._
<br>Points d'entrée : `backend/brokers/models.py:BrokerCredential.get_secret_value`, `backend/core/crypto.py:CryptoService`, `backend/brokers/admin.py:BrokerCredentialAdmin`, `backend/brokers/forms.py:BrokerAccountForm`

- Chiffrement Fernet; FERNET_SECRET_KEY absente → RuntimeError explicite (jamais de stockage en clair en secours)
- Un déchiffrement impossible lève ValueError("Impossible de déchiffrer la valeur") et ne retourne jamais la valeur chiffrée brute
- CHAQUE déchiffrement est journalisé sur le logger leotrade.brokers.secret_access (event credential.decrypted) avec credential_id, broker_account_id, secret_type, key_version — JAMAIS la valeur déchiffrée
- get_secret retourne la credential active la plus récente (filter is_active=True, order_by -created_at) et une chaîne vide si aucune — jamais None, jamais d'exception
- Le formulaire n'affiche jamais un secret enregistré (PasswordInput render_value=False, autocomplete=new-password)
- L'admin exclut secret_value_encrypted du formulaire d'édition
- key_version et rotated_at existent sur le modèle mais AUCUNE rotation de clé n'est implémentée
- FUITE EXISTANTE À CORRIGER: templates/brokers/broker_detail.html affiche les 8 premiers caractères de la clé API en clair ({{ broker.api_key|slice:":8" }})

**BrokerGateway — retry sélectif et circuit breaker par compte**
<br>_Couche unique d'appel broker qui rejoue les lectures, n'a jamais le droit de rejouer une mutation, et ouvre un circuit partagé via Redis après échecs répétés._
<br>Points d'entrée : `backend/infrastructure/broker_clients/gateway.py:BrokerGateway.call`, `backend/infrastructure/broker_clients/gateway.py:BrokerGateway._call_once`, `backend/infrastructure/broker_clients/gateway.py:BrokerGateway._call_with_retry`, `backend/core/retry.py:is_retryable_exception`

- IDEMPOTENT_METHODS = {test_connection, fetch_balances, fetch_positions, fetch_open_orders, fetch_order, fetch_symbol_constraints} → retry autorisé: 3 tentatives max, backoff 0.5 * 2^(n-1), uniquement si is_retryable_exception (erreurs réseau/timeout/429/5xx). ValueError, rejets broker et erreurs de validation ne sont JAMAIS rejoués
- MUTATING_METHODS = {submit_order, cancel_order, close_position} → JAMAIS de retry automatique: un rejeu réseau dupliquerait un ordre réel
- Toute méthode hors de ces deux ensembles lève AttributeError — pas de passe-plat implicite vers le client
- Circuit par compte, état partagé entre workers dans Redis: broker:cb:failures:{account_id} (TTL 300 s) et broker:cb:open:{account_id} (TTL 60 s), seuil = 5 échecs consécutifs
- FAIL-CLOSED SUR MUTATION: si Redis est injoignable, _check_circuit(fail_closed=True) lève CircuitStateUnavailableError AVANT l'appel broker. L'exception est levée avant l'envoi précisément pour que l'OMS puisse libérer le cash sans classer l'état comme ambigu. CircuitStateUnavailableError porte retryable = False
- FAIL-OPEN SUR LECTURE: une lecture reste autorisée pendant une panne Redis — elle ne peut pas dupliquer un ordre et sert justement la réconciliation
- Un succès remet à zéro les deux clés (failures et open)
- L'ouverture du circuit notifie BROKER_ERROR (sévérité CRITICAL, priorité URGENT) avec dedupe_key=broker_circuit:{account_id} → une alerte par compte et par fenêtre de déduplication
- Une notification qui échoue ne doit jamais faire échouer l'appel broker (try/except pass)
- Une panne du cache ne doit jamais transformer une erreur broker en crash: tout _record_failure est encapsulé
- La boucle de retry s'interrompt immédiatement si le circuit s'ouvre en cours de tentatives

**Synchronisation des contraintes d'instrument broker**
<br>_Récupère et stocke les contraintes de trading par symbole (min/max quantité, pas, notional minimum, tick de prix, levier, taille de contrat)._
<br>Points d'entrée : `backend/brokers/services/base.py:BrokerConstraintSyncService.sync_symbol_constraint`, `backend/api/views/brokers.py:BrokerAccountViewSet.sync_constraint`, `backend/api/views/brokers.py:BrokerConstraintViewSet`, `backend/brokers/models_constraints.py:BrokerConstraint`

- @transaction.atomic + update_or_create idempotent sur (broker, symbol), avec le code broker normalisé en upper().strip()
- unique_together (broker, symbol): la table est GLOBALE par broker, pas par compte ni par utilisateur
- Passe par BrokerGateway.fetch_symbol_constraints → méthode idempotente, retry sûr
- symbol manquant dans la requête API → 400 {"detail": "symbol requis."}
- BrokerConstraintViewSet est strictement en lecture seule et filtre sur les CODES broker possédés par l'utilisateur (BrokerAccount.broker), pas sur ses comptes
- Deriv ne fait aucun appel réseau: fetch_symbol_constraints renvoie des valeurs constantes codées en dur (min_qty=1, max_qty=100000, qty_step=1, price_tick=0.01, levier 1/1)
- MT5 force leverage_max=100 ; Binance force leverage 1/1 (spot) et agrège les filtres LOT_SIZE, MIN_NOTIONAL et PRICE_FILTER
- La tâche ne traite que is_active=True et renvoie {"status": "missing"} sinon

**Normalisation quantité / prix avant envoi d'ordre**
<br>_Arrondit et valide quantité, prix et notional selon les contraintes du broker avant tout envoi, pour éviter les rejets broker._
<br>Points d'entrée : `backend/infrastructure/broker_clients/constraints.py:BrokerConstraintService.quantize_step`, `backend/infrastructure/broker_clients/constraints.py:BrokerConstraintService.normalize_quantity`, `backend/infrastructure/broker_clients/constraints.py:BrokerConstraintService.validate_notional`

- quantize_step tronque TOUJOURS vers le bas (ROUND_DOWN) — jamais d'arrondi supérieur, qui engagerait plus de capital que validé par le risk engine
- step <= 0 → la valeur est retournée telle quelle (pas de division par zéro)
- normalize_quantity lève ValueError si quantité < min_qty ; plafonne à max_qty requantifié si max_qty > 0
- validate_notional lève ValueError si notional < min_notional (et seulement si min_notional > 0)
- Un rejet de précision est une ValueError, donc NON retryable par le gateway: l'ordre n'est jamais renvoyé automatiquement
- Toute valeur illisible est convertie en Decimal par défaut plutôt que de lever (_d avec default)

**Connecteur Binance (spot)**
<br>_Client Binance spot: solde, holdings, ordres ouverts, envoi MARKET/LIMIT, annulation, fermeture de position et contraintes de symbole._
<br>Points d'entrée : `backend/infrastructure/broker_clients/binance_client.py:BinanceBrokerClient`, `backend/infrastructure/broker_clients/binance_client.py:_safe_client_order_id`, `backend/brokers/services/binance.py:BinanceClient`

- Credentials obligatoires à l'instanciation: api_key ou api_secret manquant → ValueError("Credentials Binance manquants.")
- IDEMPOTENCE: newClientOrderId est dérivé de order.idempotency_key — clé telle quelle si ≤ 36 caractères sans espace, sinon "LT" + sha1(clé)[:32]. La troncature naïve à 32 caractères est interdite: elle provoquait des collisions entre ordres partageant le même préfixe
- create_order n'est jamais rejoué: en cas de réponse perdue, c'est le newClientOrderId stable qui permet à la réconciliation de récupérer l'état ambigu
- fetch_order: le code d'erreur Binance -2013 (ordre inconnu) retourne None au lieu de lever — un ordre absent n'est pas une panne
- fetch_order reconstruit un fill agrégé depuis cummulativeQuoteQty / executedQty si get_my_trades ne renvoie aucun trade (metadata reconciliation_cumulative=True)
- fetch_balances ignore toute ligne dont free+locked <= 0
- fetch_positions exclut USDT/USDC/BUSD/FDUSD, reconstruit des pseudo-positions LONG au prix spot avec broker_position_id="SPOT-{symbol}" et cost_basis_status=UNKNOWN; un symbole dont le ticker échoue est simplement ignoré
- close_position n'accepte QUE la réduction d'une position LONG par un ordre SELL, sur le même symbole, d'une quantité ≤ position (NotImplementedError / ValueError sinon)
- Seuls MARKET et LIMIT (timeInForce GTC) sont supportés — tout autre type lève NotImplementedError
- Mapping de statut imposé: NEW→SUBMITTED, PARTIALLY_FILLED→PARTIALLY_FILLED, FILLED→FILLED, CANCELED→CANCELLED, REJECTED→REJECTED, EXPIRED→EXPIRED, défaut SUBMITTED
- Les contraintes sont lues en best-effort depuis la table locale BrokerConstraint; l'absence de contrainte ne bloque pas l'envoi (fallback 1e-8)
- brokers/services/binance.py gère à part le rate limit: 429 → BinanceRateLimitError avec Retry-After borné à [1, 60] et backoff exponentiel sur 3 tentatives; 418 → bannissement IP, erreur non rejouable

**Connecteur MetaTrader 5**
<br>_Client MT5: connexion au terminal, solde, positions, ordres, envoi d'ordres marché, fermeture de position, annulation d'ordre pending et contraintes de symbole._
<br>Points d'entrée : `backend/infrastructure/broker_clients/mt5_client.py:MT5BrokerClient`, `backend/infrastructure/broker_clients/mt5_client.py:_mt5_session`, `backend/brokers/services/mt5.py:MT5Client`

- Le module MetaTrader5 ne doit jamais faire échouer l'import de l'application: import protégé, et RuntimeError explicite seulement à l'instanciation si le package est absent
- SÉRIALISATION OBLIGATOIRE: le module MT5 est un singleton process-wide. TOUS les appels (login, order_send, fetch_order, close, cancel, fetch_symbol_constraints) passent par un RedisLock broker:mt5:{broker_account_id}, timeout 60 s, blocking_timeout 30 s. Deux workers appelant initialize/login/order_send en parallèle corrompent l'état du terminal et produisent des erreurs fantômes
- Échec d'acquisition du verrou → RuntimeError de timeout, jamais d'appel non protégé
- login/initialize sont faits sous verrou dans __init__; shutdown() est appelé avant chaque levée d'erreur de validation et dans __del__
- login doit être convertible en entier; password et server sont obligatoires — chaque manquement fait shutdown() puis lève ValueError
- type_filling est choisi d'après le bitmask filling_mode du symbole (1=FOK, 2=IOC, 4=RETURN). Coder IOC en dur est interdit: certains serveurs ECN le rejettent
- magic number stable par compte: 200_000_000 + (broker_account_id % 10_000_000)
- Le comment "LT-{order.id}" (ouverture) / "LT-close-{order.id}" (fermeture) est le seul moyen de retrouver un ordre quand broker_order_id est absent — fetch_order recherche sur ticket OU sur ce commentaire, dans orders_get ET history_orders_get sur 7 jours
- Un symbole non visible est activé par symbol_select avant envoi
- Retcodes acceptés: DONE / PLACED / DONE_PARTIAL pour submit et close; DONE / PLACED seulement pour cancel. Tout autre retcode lève ValueError avec le dict complet
- close_position vérifie dans l'ordre: ticket présent, position broker existante, symbole identique, sens de l'ordre strictement opposé au type de la position broker, quantité ≤ volume broker
- cancel_order = TRADE_ACTION_REMOVE sur un ordre pending — opération distincte de la fermeture d'une position ouverte; broker_order_id manquant → ValueError
- Le statut est déduit des deals: FILLED si quantité remplie ≥ approved_quantity, sinon PARTIALLY_FILLED; sans deal, mapping sur ORDER_STATE_*

**Connecteur Deriv (sessions WebSocket one-shot)**
<br>_Client Deriv pour authentification OTP, lecture du solde et du portefeuille, achat de contrat, vente (annulation/fermeture) et récupération de l'état d'un contrat._
<br>Points d'entrée : `backend/infrastructure/broker_clients/deriv_client.py:DerivBrokerClient._open_authenticated_ws`, `backend/infrastructure/broker_clients/deriv_client.py:DerivBrokerClient.submit_order`, `backend/brokers/services/deriv.py:DerivClient.get_otp_ws_url_with_retry`, `backend/brokers/services_connection.py:build_deriv_client_for_account`

- SÉQUENCE D'AUTHENTIFICATION INVARIANTE: REST list_options_accounts → sélection du compte selon deriv_account_type (défaut "demo", fallback = premier compte) → REST POST /accounts/{id}/otp → WS connect_with_otp_url → authorize(token). Aucune étape n'est contournable
- connect_public() ne sert QUE aux flux publics (ticks, actifs): elle ne supporte ni proposal ni buy
- L'OTP est retenté 3 fois, uniquement si l'erreur est un timeout; toute autre erreur sort immédiatement
- Token Deriv manquant → ValueError("Token Deriv manquant.") à l'instanciation; app_id par défaut "1089" si deriv_app_id absent
- build_deriv_client_for_account retourne None (et non une exception) si le compte n'est pas DERIV ou si le token est absent — les tâches de sync doivent pouvoir sauter le compte silencieusement
- submit_order: contracts_for → _validate_deriv_contract_available(contract_type, duration_unit) → proposal → buy. Un contrat indisponible lève ValueError AVANT tout envoi d'argent
- Mapping side → contract_type: BUY→CALL, SELL→PUT. Les symboles commençant par BOOM/CRASH basculent sur MULTUP/MULTDOWN avec un multiplier (défaut 100) et SANS duration ni duration_unit (le payload proposal les omet pour les contrats multiplier)
- Le stake (requested_stake_amount ou approved_notional) doit être strictement > 0
- CONVENTION DE SIZING DERIV: 1 contrat = 1 unité de position → quantity renvoyée TOUJOURS égale à 1, notional = stake = buy_price. C'est ce qui permet à FillProcessingService de basculer l'ordre en FILLED dès filled_quantity >= approved_quantity
- proposal sans id ou buy sans contract_id → RuntimeError (pas de silence)
- Après un buy réussi: upsert BrokerExternalRef CONTRACT et TRANSACTION, puis sync_single_deriv_contract_task en différé de 5 s. L'ÉCHEC DE CES DEUX ÉTAPES NE DOIT JAMAIS FAIRE ÉCHOUER L'ORDRE (try/except, log warning)
- cancel_order = vente du contrat au best price ({"sell": contract_id, "price": 0}); contract_id résolu via BrokerExternalRef — absence de ref → RuntimeError
- close_position refuse un contract_id manquant et une quantité supérieure à la position
- fetch_open_orders() retourne toujours [] : Deriv n'a pas de carnet d'ordres, les "ordres" actifs sont les contrats
- fetch_order renvoie TOUJOURS status FILLED: l'achat du contrat est un fill terminal de l'ordre d'ouverture, la suite du cycle de vie passe par BrokerExternalRef
- Toute trame WS contenant {"error": ...} est convertie en DerivClientError avec code et message
- La session WS est systématiquement fermée dans un finally, y compris en cas d'exception

**Streamer WebSocket Deriv persistant**
<br>_Worker long-running qui maintient une connexion WS par compte Deriv actif et pousse en base les mises à jour de solde, de transactions et de contrats._
<br>Points d'entrée : `backend/brokers/services/deriv_streamer.py:DerivStreamer.run_forever`, `backend/brokers/services/deriv_streamer.py:DerivStreamer._dispatch`, `backend/brokers/management/commands/run_deriv_streamer.py`

- Un streamer par BrokerAccount broker=DERIV et is_active=True, tous lancés en asyncio.gather
- Souscriptions à l'ouverture, dans cet ordre: authorize(token), balance subscribe=1, transaction subscribe=1, proposal_open_contract subscribe=1
- Un req_id incrémental est ajouté à chaque message sortant
- Reconnexion avec back-off exponentiel plafonné à 60 s, remis à 1 après une boucle saine; heartbeat ping_interval=30 s, ping_timeout=10 s; max_size 2 Mo
- Les trames d'erreur sont loggées et ignorées — elles ne doivent jamais interrompre la boucle de réception
- Chaque handler est encapsulé (_safe_on_balance / _safe_on_transaction / _safe_on_open_contract): une exception de persistance ne doit JAMAIS tuer le stream
- Les msg_type inconnus sont ignorés silencieusement
- Les handlers appelés sont exactement ceux du fallback Celery (brokers.services.deriv_sync) — la logique métier ne doit jamais être dupliquée entre les deux chemins
- Le streamer utilise wss://ws.binaryws.com/websockets/v3?app_id={app_id} avec authorize direct, PAS le flux OTP de DerivClient

**Fallback Celery de synchronisation Deriv**
<br>_Tâches planifiées qui rejouent en polling la synchronisation du solde et des contrats ouverts quand le streamer WS ne tourne pas, plus une synchronisation ponctuelle d'un contrat._
<br>Points d'entrée : `backend/brokers/tasks_deriv_sync.py:sync_deriv_balance_task`, `backend/brokers/tasks_deriv_sync.py:sync_deriv_positions_task`, `backend/brokers/tasks_deriv_sync.py:sync_single_deriv_contract_task`, `backend/brokers/tasks_deriv_sync.py:_redis_lock`

- Verrou Redis par tâche (lock:sync_deriv_balance_task / lock:sync_deriv_positions_task, TTL 55 s, blocking_timeout=0) pour interdire tout chevauchement entre deux passages du beat
- Si Redis est indisponible, le verrou dégrade en nullcontext — l'absence de cache ne doit pas faire échouer la tâche (notamment en test)
- Ne traite que broker=DERIV et is_active=True
- Les erreurs sont capturées PAR COMPTE, comptées (ok/err) et loggées, jamais propagées: le beat ne doit jamais être bloqué par un compte en panne
- Dans sync_deriv_positions_task, l'échec sur un contrat n'interrompt pas la boucle sur les autres contrats
- Le client Deriv est toujours fermé dans un finally
- Les handlers appelés (on_balance_update, on_open_contract_update) sont les mêmes que ceux du streamer et sont idempotents — exécuter les deux chemins simultanément ne doit créer aucun doublon
- sync_single_deriv_contract_task retourne {"ok": False, "error": ...} au lieu de lever, et None si le compte ou le client est introuvable

**Réconciliation du solde Deriv vers le ledger du portefeuille**
<br>_Applique un événement de solde broker au portefeuille lié, en écrivant un ajustement au ledger plutôt qu'en mutant le solde._
<br>Points d'entrée : `backend/brokers/services/deriv_sync.py:on_balance_update`, `backend/brokers/services/deriv_sync.py:_portfolio_for_broker_account`

- @transaction.atomic sur tout le handler
- ON NE MUTE JAMAIS portfolio.current_balance directement: tout écart passe par PortfolioAccountingService.add_ledger_entry(entry_type="BROKER_IMPORT", reference_type="BROKER_BALANCE_SYNC")
- Idempotence par snapshot: garde sur BrokerExternalRef(DERIV, TRANSACTION, "balance_snapshot:{payload.id | loginid | timestamp ISO}"). Si la ref existe, sortie immédiate sans écriture
- PortfolioService.recompute_cash_state est appelé AVANT toute comparaison
- FORMULE CRITIQUE: delta = solde_broker - (current_balance + locked_cash). Sans la réintégration de locked_cash, la fenêtre [lock_cash → register_fill] produit un faux delta positif (le broker n'a pas encore débité la mise alors que le verrou local l'a déjà fait) et insère un BROKER_IMPORT fantôme à corriger manuellement
- Tolérance d'un centime: |delta| < 0.01 → aucune écriture (évite le bruit d'arrondi)
- Le broker est source de vérité, le portefeuille est un miroir
- Compte ou portefeuille actif introuvable → warning et sortie, jamais d'exception
- Mise à jour de portfolio.last_reconciled_at après traitement
- La ref de snapshot est écrite avec internal_kind="ORDER" et internal_id=portfolio.id (placeholder assumé: un solde n'est lié à aucune entité interne)

**Synchronisation des contrats Deriv (ouverture, clôture, import externe)**
<br>_Route un événement proposal_open_contract vers l'ordre canonique, le contrat historique ou un import de position externe, et crée le fill de clôture._
<br>Points d'entrée : `backend/brokers/services/deriv_sync.py:on_open_contract_update`, `backend/brokers/services/deriv_sync.py:_handle_execution_order_update`, `backend/brokers/services/deriv_sync.py:_record_closing_fill_for_execution_order`, `backend/brokers/services/deriv_sync.py:_record_external_only_position`, `backend/brokers/services/deriv_sync.py:_map_deriv_status_to_execution_order`

- ORDRE DE DISPATCH INVARIANT (inverser ferait traiter deux fois un contrat déjà rattaché à un ordre canonique): 1) BrokerExternalRef(DERIV, CONTRACT, contract_id) → execution.Order ; 2) trading.DerivContract trouvé par contract_id → DerivSettlementService.handle_contract_update (chemin historique) ; 3) contrat inconnu → import de position externe
- @transaction.atomic sur tout le handler; payload sans contract_id → warning et sortie
- Mapping de statut: is_sold OU is_settleable OU status ∈ {won, lost, sold, expired, cancelled} → FILLED ; status ∈ {open, running} → SUBMITTED ; sinon AUCUN changement de statut (on ne régresse jamais un ordre)
- filled_at n'est posé qu'au premier passage en FILLED et n'est jamais écrasé
- LE FILL DE CLÔTURE N'EST CRÉÉ QU'UNE FOIS: garde d'idempotence sur BrokerExternalRef(DERIV, TRANSACTION, transaction_ids.sell) avec repli "contract_close:{contract_id}" quand Deriv ne fournit pas d'identifiant de vente
- Le fill de clôture porte liquidity_type="CLOSE", fee=0, et notional = sell_price
- PositionCloseService.apply_deriv_contract_settlement est appelé APRÈS la création du fill, dans un try/except: son échec est loggé mais ne doit pas annuler le fill déjà enregistré
- Path 2: la ref est réécrite avec internal_kind="TRADING_ORDER" et l'id de l'ordre trading (valeur hors INTERNAL_KIND_CHOICES, tolérée volontairement)
- Path 3 (import externe): position créée avec source="IMPORTED", cost_basis_status="ESTIMATED" et AUCUN débit cash — l'opération a déjà été réalisée côté broker. La quantité vaut le buy_price (la mise), PAS 1 : la valeur 1 cassait le calcul du P&L et du notional
- Path 3: upsert sur (portfolio, broker_position_id=contract_id) — rejouer l'événement ne duplique jamais la position; status CLOSED si is_sold, sinon OPEN
- Un échec de lookup DerivContract (table absente, import impossible) est capturé et traité comme "non trouvé", jamais propagé

**Journalisation des transactions Deriv**
<br>_Enregistre chaque événement transaction Deriv comme référence externe, à des fins de traçabilité secondaire._
<br>Points d'entrée : `backend/brokers/services/deriv_sync.py:on_transaction`

- @transaction.atomic ; idempotence par transaction_id (ou id) via BrokerExternalRef(DERIV, TRANSACTION, tx_id): si la ref existe, sortie immédiate
- Absence de transaction_id ou de portefeuille lié → sortie silencieuse, jamais d'exception
- TRACKING SECONDAIRE UNIQUEMENT: ce handler n'écrit RIEN au ledger et ne modifie aucun solde — la vérité comptable passe par on_balance_update et les fills
- Le lien interne est best-effort: internal_kind="ORDER" et internal_id = contract_id du payload ou "0"

**Mapping interne ↔ identifiants broker (BrokerExternalRef)**
<br>_Table pivot unique entre les entités internes (Order, ExecutionFill, Position, Trade) et les identifiants broker (contract_id Deriv, orderId/tradeId Binance, ticket MT5)._
<br>Points d'entrée : `backend/brokers/models_external_ref.py:BrokerExternalRef.upsert`, `backend/brokers/models_external_ref.py:BrokerExternalRef.resolve`, `backend/trading/views.py (contexte broker_refs)`, `backend/market/views.py (résolution du contract_id après exécution)`

- IDEMPOTENCE STRUCTURELLE: UniqueConstraint(broker, kind, external_id) — upsert() fait un update_or_create sur exactement ce triplet, jamais sur l'entité interne
- resolve() ne lève jamais: il retourne None quand la ref n'existe pas
- external_id et internal_id sont TOUJOURS stockés en str (un int et un str doivent résoudre vers la même ligne)
- last_seen_at est en auto_now: il sert de "dernière synchronisation" du compte dans le Centre Broker
- Cascade sur BrokerAccount: supprimer un compte détruit tout son historique de mapping
- Les lectures côté vues sont systématiquement protégées par try/except et forcées en list() pour capturer l'erreur dans la vue et non dans le template — héritage de la migration 0003 qui avait supprimé la table en base; une page ne doit jamais devenir fatale si la table manque
- last_status et last_payload ne sont qu'un snapshot de debug: aucune logique métier ne doit s'appuyer dessus

**Bascule PAPER / LIVE d'un compte broker**
<br>_Détermine si les ordres d'un compte sont simulés localement ou réellement envoyés au broker._
<br>Points d'entrée : `backend/brokers/management/commands/set_broker_mode.py`, `backend/execution/adapters/factory.py:BrokerAdapterFactory.build`, `backend/execution/adapters/paper.py:PaperBrokerAdapter`

- LE ROUTAGE DÉPEND UNIQUEMENT DE BrokerAccount.mode: mode=PAPER → PaperBrokerAdapter, aucun appel broker, fill simulé, broker_order_id "PAPER-{order.id}" ; mode=LIVE → LiveBinanceAdapter / LiveMT5Adapter / LiveDerivAdapter, seul mode qui atteint réellement le broker
- Un compte DERIV en PAPER avec un token configuré émet un warning structuré broker_adapter.paper_used_with_deriv_token — c'est le piège de configuration le plus fréquent ("je veux trader sur Deriv demo" alors que PAPER simule localement et n'envoie rien)
- PaperBrokerAdapter exige un prix de référence strictement positif (ValueError sinon) et applique la convention Deriv: quantity=1 et notional=stake pour un compte DERIV
- PaperBrokerAdapter.close_position vérifie le sens inverse et la quantité ≤ position, exactement comme les adapters live
- Code broker inconnu → ValueError("Broker non supporté")
- La commande set_broker_mode est idempotente: no-op explicite si le mode est déjà celui demandé

**Administration Django des comptes et credentials**
<br>_Back-office de consultation et de dépannage des comptes broker et de leurs credentials._
<br>Points d'entrée : `backend/brokers/admin.py:BrokerAccountAdmin`, `backend/brokers/admin.py:BrokerCredentialAdmin`

- BrokerCredentialAdmin exclut secret_value_encrypted: la valeur chiffrée n'est ni affichée ni éditable depuis l'admin
- created_at, updated_at et last_connected_at sont en lecture seule sur BrokerAccount; created_at/updated_at sur BrokerCredential
- La recherche porte sur name, user__email, login, server (comptes) et broker_account__name, broker_account__user__email (credentials) — jamais sur une valeur de secret
- L'admin écrit via save() donc déclenche full_clean(): les mêmes invariants de validation s'appliquent

</details>

<details><summary>Pièges de migration repérés</summary>

- STUB EN PRODUCTION — brokers/views.py:BrokerAccountTestConnectionView met ok=True en dur pour BINANCE/MT5/DERIV, puis persiste status=ACTIVE, last_connection_status=True et envoie la notification BROKER_CONNECTION_OK sans aucun appel broker. Le bouton "Tester la connexion" du web ment aujourd'hui. La refonte doit router ce bouton vers BrokerConnectionService (déjà correct côté API).
- LOGIQUE MÉTIER ENFOUIE DANS LES VUES — toutes les notifications du domaine (BROKER_ACCOUNT_CREATED, BROKER_ACCOUNT_UPDATED, BROKER_DEFAULT_CHANGED, BROKER_CONNECTION_OK, BROKER_CONNECTION_FAILED) sont émises dans brokers/views.py, pas dans les services. Passer exclusivement par l'API les ferait toutes disparaître silencieusement. Même problème pour la règle d'ordre du set-default et pour l'écriture des secrets, qui ne vit que dans BrokerAccountForm.save().
- L'API NE GÈRE AUCUN SECRET — api/views/brokers.py:BrokerAccountSerializer n'expose ni api_key, ni api_secret, ni password, ni deriv_token. Un client React/Flutter peut créer un compte broker mais pas le rendre fonctionnel. C'est le plus gros trou fonctionnel du domaine.
- BrokerAccount.save() appelle full_clean() à CHAQUE sauvegarde, y compris avec update_fields. Toute écriture partielle revalide le modèle entier: un compte MT5 auquel il manque login/server ne peut plus être sauvegardé, même pour mettre à jour last_connection_status. Les serializers DRF ne rejouent pas clean() de la même façon — vérifier que les erreurs par champ remontent bien en 400.
- UNICITÉ DU BROKER PAR DÉFAUT NON GARANTIE EN BASE — la règle "un seul is_default par utilisateur" n'existe que dans BrokerAccount.clean(). Aucune UniqueConstraint conditionnelle. Un .update() en masse (comme celui de BrokerAccountSetDefaultView) ou une écriture concurrente peut produire deux comptes par défaut. À durcir par une contrainte DB pendant la refonte.
- FUITE DE SECRET DANS LES LOGS — brokers/services/deriv.py:_send fait logger.warning("DERIV_WS_PAYLOAD=%s", payload) sur CHAQUE trame sortante, y compris {"authorize": token} : le token Deriv part en clair dans les logs applicatifs. deriv_client.py logge en plus DERIV_CONTRACTS_FOR. À supprimer avant toute mise en production de la refonte.
- FUITE DE SECRET DANS L'UI — templates/brokers/broker_detail.html affiche {{ broker.api_key|slice:":8" }} suivi de points: les 8 premiers caractères de la clé API Binance sont rendus en clair. Ne pas reproduire côté React/Flutter.
- RENDU = DÉCHIFFREMENT — broker_list.html et broker_detail.html lisent broker.api_key / broker.deriv_token pour afficher un simple "configuré / non configuré". Chaque affichage de la liste déclenche donc un déchiffrement Fernet et un log d'audit credential.decrypted par compte, ce qui pollue la piste d'audit. L'API doit exposer des booléens calculés sans déchiffrer.
- CODE MORT ET INCOHÉRENT — brokers/services/base.py:BrokerCredentialService n'a AUCUN appelant, et son REQUIRED_BY_BROKER attend des secret_type LOGIN / SERVER / TOKEN / APP_ID qui n'existent pas dans BrokerCredential.SECRET_TYPE_CHOICES (API_KEY, API_SECRET, PASSWORD, DERIV_TOKEN) : validate_required_credentials échouerait systématiquement pour MT5 et DERIV. De plus upsert_secret fait un get_or_create avec secret_value_encrypted="" et peut laisser une credential vide active si la suite échoue. Ne pas porter tel quel.
- CACHE DE CONTRAINTES JAMAIS INVALIDÉ — risk/engine.py met les BrokerConstraint en cache Redis 15 minutes sous la clé bc:{broker}:{symbol} et documente "la invalidation explicite est faite par BrokerConstraintSyncService après un sync réussi". Cette invalidation N'EXISTE PAS dans brokers/services/base.py (aucun cache.delete dans le domaine). Après un sync_constraint, le risk engine peut sizer jusqu'à 15 minutes sur une contrainte périmée.
- CONTRAINTES GLOBALES, PAS PAR UTILISATEUR — BrokerConstraint est unique sur (broker, symbol) sans rattachement à un compte. BrokerConstraintViewSet filtre par CODE broker possédé, donc un utilisateur lit des contraintes synchronisées par un autre. Pas de fuite de secret, mais le cloisonnement est partiel et la table est un point de contention partagé.
- api/permissions.IsOwner n'implémente que has_object_permission. La protection de la liste /api/v1/brokers/ repose uniquement sur get_queryset(user=request.user), et l'authentification sur le DEFAULT_PERMISSION_CLASSES global IsAuthenticated. Déclarer permission_classes=[IsOwner] sur un viewset fait perdre IsAuthenticated — piège à reproduire sur tout nouveau viewset du domaine.
- DEUX CHEMINS D'AUTHENTIFICATION DERIV DIVERGENTS — DerivClient utilise REST api.derivws.com + OTP WebSocket éphémère, alors que DerivStreamer se connecte directement à wss://ws.binaryws.com/websockets/v3?app_id=... avec authorize(token). Ce ne sont pas les mêmes endpoints ni le même protocole d'authentification: un token valide pour l'un n'est pas garanti pour l'autre. À unifier ou à documenter explicitement avant la refonte.
- CONSTRUCTION DE CLIENT = I/O BLOQUANTE — MT5BrokerClient.__init__ fait initialize + login sous verrou Redis dès l'instanciation, et BrokerClientFactory est appelé par BrokerGateway._get_client(). broker_health_api contourne cela en injectant client=object(). Un viewset DRF naïf qui instancierait un client pour lire un simple statut bloquerait la requête HTTP jusqu'à 30 s (blocking_timeout du verrou).
- MT5 INUTILISABLE HORS WINDOWS — le package MetaTrader5 est absent sur Linux/macOS, l'instanciation lève RuntimeError. Conséquence directe: check_all_brokers_health_task marquera tous les comptes MT5 en ERROR toutes les 5 minutes sur un déploiement Docker/Linux, ouvrira leur circuit breaker et enverra une notification BROKER_ERROR critique. Prévoir une exclusion explicite ou un connecteur distant.
- SUPPRESSION DESTRUCTIVE — supprimer un BrokerAccount cascade sur BrokerCredential ET sur BrokerExternalRef: tout le mapping ordres/fills/positions ↔ identifiants broker est perdu, sans aucune vérification de positions ouvertes ou d'ordres en vol. Ajouter un garde-fou (désactivation plutôt que suppression) avant d'exposer DELETE côté mobile.
- HISTORIQUE MIGRATOIRE FRAGILE — la migration 0003 a réellement DROP la table brokers_brokerexternalref en base (le modèle vivait dans models_external_ref.py et n'était pas chargé), elle a été neutralisée a posteriori, 0004_recreate_broker_external_ref la recrée par RunSQL idempotent et 0004_rename_* renomme des index. Toute migration de données sur ce domaine doit vérifier l'existence réelle de la table, et trading/views.py comme market/views.py enveloppent encore leurs lectures dans un try/except à cause de cet incident.
- DEUX NOTIONS D'ÉTAT NON RÉCONCILIÉES — BrokerAccount.status (DRAFT / ACTIVE / INACTIVE / ERROR), piloté uniquement par les tests de connexion, coexiste avec is_active (booléen manuel qui, lui, conditionne le traitement par les tâches Celery). Aucune règle de cohérence: un compte status=ERROR mais is_active=True reste synchronisé en boucle. INACTIVE n'est jamais posé par le code.
- sync_single_deriv_contract_task est déclenchée en apply_async(countdown=5) depuis DerivBrokerClient.submit_order, dans un try/except silencieux. Sans worker Celery, la confirmation du contrat n'arrive jamais et l'ordre reste SUBMITTED jusqu'au prochain passage du beat (60 s) — ou indéfiniment si le beat ne tourne pas non plus.
- La formule de réconciliation du solde Deriv (delta = solde_broker - (current_balance + locked_cash), tolérance 0,01) est la SEULE protection contre l'insertion d'écritures BROKER_IMPORT fantômes toutes les 60 secondes pendant la fenêtre [lock_cash → register_fill]. Toute refonte de la gestion du cash doit préserver cette formule exacte, sous peine de corrompre le ledger de façon récurrente et silencieuse.
- AUCUN TEMPS RÉEL CÔTÉ CLIENT — le domaine possède un streamer WS sortant mais aucun consumer Channels (leoTrade/asgi.py n'inclut pas de routing brokers). Les mises à jour de solde et de contrats n'atteignent le navigateur que via les canaux d'autres domaines (portfolio, execution). Le Centre Broker est aujourd'hui du polling HTTP pur.
- NOMENCLATURE À CONSERVER — le domaine ne supporte que trois brokers: BINANCE, MT5, DERIV (BrokerAccount.BROKER_CHOICES, BrokerClientFactory, BrokerExternalRef.BROKER_CHOICES, BrokerAdapterFactory). Il n'existe AUCUN connecteur Alpaca ni IBKR dans le code. "Paper" n'est pas un broker mais un MODE (BrokerAccount.mode) qui route vers PaperBrokerAdapter.

</details>

---

### market-data (apps `market` + `strategies`)

`41 fonctionnalités` — API : **0 prêtes, 9 partielles, 32 à exposer**

**Modèles** : `Asset`, `Timeframe`, `Candle`, `MarketFeature`, `Strategy`, `StrategyVersion`, `StrategyDeployment`, `StrategyRun`, `StrategyPrediction`, `Signal`, `StrategyPerformanceSnapshot`

**Tâches Celery** : `market.tasks.sync_binance_klines (beat: */5 min)`, `market.tasks.sync_binance_long_klines (NON planifiée en beat)`, `market.tasks.sync_deriv_candles (beat: */5 min)`, `market.tasks.sync_deriv_long_candles (NON planifiée en beat)`, `market.tasks.compute_market_features_task (beat: */5 min)`, `market.tasks.compute_market_features_long_task (NON planifiée en beat)`, `strategies.tasks.run_all_autonomous_strategies_task (beat: chaque minute, autoretry 3x backoff)`, `strategies.tasks.execute_deployed_signal_task (déclenchée à la demande via transaction.on_commit)`, `ai_engine.tasks.evaluate_predictions_task (beat: */10 min — évalue les StrategyPrediction du domaine)`

**Canaux WebSocket** : `route: ws/market/candles/<asset_id>/<timeframe>/ → market.servicess.consumers.CandleConsumer`, `groupe: candles_{asset_id}_{timeframe_code}`, `handler consumer: candle_update (lit event['data'])`, `codes de fermeture custom: 4401 non authentifié, 4403 accès refusé`, `seul émetteur réel: DerivCandleImporter.import_candles (group_send inline, type='candle_update')`, `core.realtime.RealtimeBroadcastService.broadcast_candle existe mais n'est appelé nulle part ET émet type='broadcast.message' que CandleConsumer n'implémente pas`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Catalogue des actifs (marchés)** | ❌ | WEB/MOBILE |  | Aucun endpoint DRF. Il faut un GET /api/v1/assets/ paginé avec filtres (q, asset_class, exchange, is_active), tri whitelisté, et un bloc stats agrégé calculé sur les mêmes filtres. |
| **Flux JSON des actifs + prix live (polling)** | 🟡 | WEB/MOBILE |  | JSON existe mais hors DRF/OpenAPI, non paginé, non versionné, sans sérialiseur typé et format de date localisé côté serveur. À remplacer par un endpoint DRF paginé renvoyant des dates ISO-8601 et un last_close numérique. |
| **Fiche détail d'un actif** | ❌ | WEB/MOBILE |  | Pas d'endpoint. Il faut GET /api/v1/assets/{id}/ renvoyant métadonnées + dernières bougies + variation, et un endpoint distinct pour les timeframes disponibles ; brokers/portefeuilles doivent venir de leurs propres endpoints de domaine, pas de celui-ci. |
| **Trade rapide depuis la fiche actif** | 🟡 | WEB/MOBILE |  | Endpoint POST existant mais en form-urlencoded hors DRF, sans idempotency-key, sans sérialiseur de validation ni OpenAPI. À exposer en JSON DRF avec clé d'idempotence (l'endpoint DRF équivalent api/views/execution.py:OrderViewSet.create_manual en possède une, pas celui-ci). |
| **Graphique chandelier temps réel** | ❌ | WEB/MOBILE | ⚡ | La page est une vue Django ; seul le sous-flux /candles/live/ est en JSON. Il faut un endpoint OHLCV paginé/borné (asset, timeframe, limit) et exposer l'URL WS (ou sa convention) dans la réponse API. |
| **Flux live des bougies (polling REST)** | 🟡 | WEB/MOBILE |  | JSON disponible mais hors DRF/OpenAPI, non versionné, non paginé, et le filtre timeframe est optionnel et silencieux. À reprendre en DRF avec timeframe obligatoire ou valeur par défaut explicite. |
| **Diffusion WebSocket des bougies** | 🟡 | WEB/MOBILE | ⚡ | Le canal existe mais l'authentification repose sur la session Django (scope['user']). Pour React/Flutter il faut une authentification WS par token JWT et un contrat de message versionné. |
| **Overlays des positions ouvertes sur le graphique** | ❌ | WEB/MOBILE |  | Pas d'endpoint : les overlays sont sérialisés dans le contexte du template. Il faut exposer les positions ouvertes par actif via l'API portfolio et les composer côté client. |
| **Liste brute des bougies (page cassée)** | ❌ | WEB |  | Aucun endpoint. Si la fonctionnalité est conservée, prévoir GET /api/v1/candles/ paginé avec filtres asset et timeframe. |
| **Import des bougies Binance** | ❌ | — |  | Tâche de fond sans surface API. Si un déclenchement manuel est souhaité côté admin, prévoir un endpoint protégé par rôle + un endpoint de lecture de l'état du dernier import. |
| **Import des bougies Deriv (avec diffusion temps réel)** | ❌ | — | ⚡ | Tâche de fond sans surface API. Prévoir au minimum une remontée d'état d'import (dernier succès, actifs en skipped/failed) pour un écran d'administration. |
| **Calcul des indicateurs techniques (MarketFeature)** | ❌ | — |  | Les MarketFeature ne sont exposés par AUCUNE vue ni endpoint — uniquement lus par le moteur de signaux et l'agent de régime de marché. Un endpoint de lecture (indicateurs par actif/timeframe) serait nécessaire pour afficher les indicateurs côté Web/Mobile. |
| **Pipeline d'indicateurs legacy (pandas/ta)** | ❌ | — |  | Commandes CLI uniquement. À arbitrer lors de la refonte : conserver une seule implémentation de référence. |
| **Bootstrap des données de marché** | ❌ | — |  | Commande d'exploitation, sans surface API ni besoin d'en avoir une. |
| **Référentiel des instruments (seed multi-marchés)** | ❌ | — |  | Commande d'administration. Si la gestion du référentiel doit devenir une fonctionnalité produit, il faut un CRUD Asset/Timeframe protégé par rôle (aucun n'existe aujourd'hui hors admin Django). |
| **Administration Django du domaine marché** | ❌ | WEB |  | Pas de CRUD exposé hors admin Django. À remplacer par des endpoints protégés par RBAC si l'administration doit passer sur le Web React. |
| **Liste des stratégies (cartes temps réel)** | 🟡 | WEB/MOBILE |  | Un JSON de lecture existe (/strategies/api/) mais hors DRF, non paginé, non filtrable, avec dates pré-formatées FR ; les filtres serveur et les actions restent en vues Django form-POST avec redirect + messages Django. |
| **Flux JSON des stratégies** | 🟡 | WEB/MOBILE |  | JSON non DRF, non paginé, sans filtres, last_signal_at formaté 'd/m H:i' côté serveur. À reprendre en DRF paginé avec dates ISO-8601. |
| **Détail d'une stratégie (tableau de bord)** | ❌ | WEB/MOBILE |  | Entièrement calculé dans la vue Django (score de santé, libellés, classes CSS Tailwind, JSON de graphiques). Il faut extraire le calcul dans un service et exposer un endpoint de métriques renvoyant des valeurs brutes + un code d'interprétation, en laissant les couleurs au client. |
| **Activer / désactiver une stratégie** | ❌ | WEB/MOBILE |  | Vue form-POST avec redirect et django.contrib.messages. Il faut un endpoint idempotent (PATCH) renvoyant le nouvel état et la liste des déploiements mis en pause par l'effet de bord. |
| **Basculer le mode autonome** | ❌ | WEB/MOBILE |  | Vue form-POST avec redirect/messages. Même besoin d'endpoint PATCH explicite renvoyant les déploiements impactés. |
| **Changer le statut d'une stratégie (cycle de vie)** | ❌ | WEB |  | Vue form-POST. Il faut un endpoint de transition renvoyant 422 avec le motif précis quand le garde-fou LIVE bloque, et la liste des déploiements mis en pause. |
| **Activer un déploiement (stratégie → portefeuille → broker)** | ❌ | WEB/MOBILE |  | Vue form-POST avec redirect/messages. Il faut un endpoint renvoyant les ValidationError champ par champ (clean() produit un message_dict aujourd'hui aplati en chaîne par StrategyDeploymentService._message). |
| **Mettre en pause un déploiement** | ❌ | WEB/MOBILE |  | Vue form-POST. Besoin d'un endpoint renvoyant le déploiement mis à jour. |
| **Résolution du déploiement au moment de l'ordre** | ❌ | — |  | Service interne, pas de surface propre. À conserver comme couche de domaine appelée par l'API d'exécution, sans jamais être court-circuitée par un nouvel endpoint. |
| **Liste des signaux** | ❌ | WEB/MOBILE |  | Aucun endpoint. Il faut GET /api/v1/signals/ paginé, filtrable (status, side, strategy, période) et cloisonné par la même logique visible_to. |
| **Détail d'un signal** | ❌ | WEB/MOBILE |  | Aucun endpoint. Prévoir GET /api/v1/signals/{id}/ incluant rr_ratio calculé serveur et le drapeau can_review. |
| **Approuver / rejeter un signal** | 🟡 | WEB/MOBILE |  | Les actions dédiées sont des vues Django form-POST avec redirect/messages. L'API ne couvre l'approbation que de façon implicite depuis la création d'ordre manuel. Il faut POST /api/v1/signals/{id}/approve et /reject renvoyant le signal mis à jour et un code d'erreur distinct pour expiré vs statut non révisable. |
| **Historique et diagnostic des runs de stratégie** | ❌ | WEB |  | Aucun endpoint. Prévoir GET /api/v1/strategy-runs/ paginé/filtrable avec un cloisonnement renforcé sur les snapshots (masquer portfolio_id / broker_account_id d'autres utilisateurs). |
| **Moteur de génération de signaux IA** | ❌ | — |  | Service interne sans surface API. Un déclenchement manuel de run (« tester la stratégie maintenant ») n'existe aujourd'hui nulle part : ni vue, ni endpoint, seulement Celery beat et la commande CLI. |
| **Routage d'exécution des signaux** | ❌ | — |  | Service interne. Les valeurs routing / routing_error stockées dans model_output constituent un état métier implicite à exposer explicitement dans l'API du signal. |
| **Auto-exécution d'un signal déployé** | ❌ | — |  | Tâche de fond sans surface API. L'état d'auto-exécution n'est lisible que dans le JSON model_output du signal : à exposer en champs structurés. |
| **Exécution planifiée des stratégies autonomes** | ❌ | — |  | Pas de déclenchement manuel exposé (ni vue, ni endpoint) : impossible aujourd'hui de lancer un run depuis l'interface. À prévoir comme endpoint POST protégé si la refonte le requiert. |
| **Garde-fous de risque au niveau stratégie** | ❌ | — |  | Service interne. Les motifs de refus ne sont exposés que via StrategyRun.error_message : à exposer comme codes de refus structurés. |
| **Chargement et inférence multi-backend des modèles ML** | ❌ | — |  | Service interne. Aucun endpoint d'upload, de test ou de validation de modèle n'existe ; model_path est un simple champ texte saisi en admin. |
| **Versionnage automatique des stratégies** | ❌ | WEB |  | Les versions sont affichées en lecture seule dans le détail stratégie ; aucune création/promotion de version n'est exposée. Si la gestion de version devient une fonctionnalité produit, il faut un CRUD avec promotion is_live respectant l'invariant d'unicité. |
| **Prédictions du modèle et évaluation prévision/réalité** | 🟡 | WEB/MOBILE |  | Les prédictions brutes ne sont listées que dans le template du détail stratégie (10 dernières). Le taux d'exactitude est exposé par ai_engine mais en vue Django. Prévoir un endpoint de prédictions paginé et un endpoint de métriques d'exactitude par stratégie. |
| **Snapshots de performance de stratégie** | ❌ | WEB/MOBILE |  | Ni endpoint ni producteur. À trancher lors de la refonte : implémenter le calcul périodique des snapshots, ou calculer les métriques à la volée et supprimer le modèle avec justification. |
| **Cloisonnement multi-tenant des stratégies et signaux** | 🟡 | WEB/MOBILE |  | La logique existe en QuerySets réutilisables côté Python ; seul api/views/execution.py l'applique déjà. Tout nouvel endpoint du domaine doit impérativement passer par ces QuerySets plutôt que par un filtrage ad hoc. |
| **Administration Django du domaine stratégies** | ❌ | WEB |  | Le CRUD de stratégie est entièrement absent du périmètre applicatif. La refonte doit décider explicitement s'il devient une fonctionnalité produit (création/édition de stratégie par l'utilisateur) ou reste réservé à l'administration. |
| **Lancement d'un backtest depuis la fiche stratégie** | ❌ | WEB |  | Surface appartenant au domaine leo_backtesting mais consommée depuis l'écran stratégie : à traiter comme un point d'intégration inter-domaines lors de la refonte. |

<details><summary>Règles métier invariantes à préserver</summary>

**Catalogue des actifs (marchés)**
<br>_Page listant tous les Asset avec recherche plein-texte, filtres classe/exchange/statut, 10 tris, pagination 20/page et bandeau de statistiques (total, actifs, inactifs, Deriv, Binance)._
<br>Points d'entrée : `backend/market/views.py:AssetListView`

- Les stats sont recalculées sur le MÊME jeu de filtres que la liste (hors tri/pagination) — elles ne doivent pas refléter la base entière.
- Seuls 10 tris sont autorisés via un dictionnaire d'allow-list ; toute valeur inconnue retombe sur 'symbol' (anti-injection ORM).
- Les annotations candles_count / last_candle_time / first_candle_time viennent d'un Count+Max+Min distinct sur les bougies.
- Aucun cloisonnement par utilisateur : les actifs sont globaux, seul LoginRequiredMixin protège la page.

**Flux JSON des actifs + prix live (polling)**
<br>_Endpoint AJAX renvoyant jusqu'à 100 actifs filtrés avec le close de leur dernière bougie ; consommé par un polling 10 s sur la liste des marchés qui fait clignoter les prix à la hausse/baisse._
<br>Points d'entrée : `backend/market/views.py:market_assets_api`

- Troncature dure à 100 actifs (qs[:100]) — non paginée, non configurable.
- La récupération du dernier close se fait par une requête par actif enveloppée dans un try/except silencieux : une erreur de prix ne doit jamais casser la réponse (last_close=None).
- Vue Django JsonResponse hors DRF, protégée par @login_required uniquement.
- Les dates sont pré-formatées côté serveur en 'd/m/Y H:i' (format métier FR).

**Fiche détail d'un actif**
<br>_Page actif : métadonnées, 10 dernières bougies du timeframe sélectionné, variation de prix absolue et %, timeframes réellement disponibles pour cet actif, brokers et portefeuilles actifs de l'utilisateur pour le panneau de trade._
<br>Points d'entrée : `backend/market/views.py:AssetDetailView`

- La variation n'est calculée que si la bougie précédente existe ET que son close est non nul (division protégée).
- Les timeframes proposés dans le sélecteur 'asset_timeframes' sont ceux pour lesquels cet actif a réellement des bougies (Timeframe.objects.filter(candle__asset=asset).distinct()).
- Les brokers et portefeuilles listés sont strictement ceux de request.user ET is_active=True.
- Si l'utilisateur n'a aucun broker actif, le panneau de trade est remplacé par un message d'invitation à en connecter un (pas de formulaire mort).

**Trade rapide depuis la fiche actif**
<br>_Passage d'ordre BUY/SELL immédiat sur un actif (mise USD, durée + unité pour les contrats Deriv) depuis la fiche actif, en réutilisant intégralement le pipeline d'exécution des trades IA._
<br>Points d'entrée : `backend/market/views.py:AssetQuickTradeView.post`, `strategies.services.deployment.StrategyDeploymentService.activate`, `execution.services.ExecutionOrchestrator.create_order + submit_order`

- Le chemin d'exécution DOIT rester unifié : RiskGuard → ExecutionOrchestrator.create_order → submit_order → BrokerAdapter → FillProcessingService → Position. Ne jamais réintroduire un appel direct à DerivExecutor, sinon la synchro broker→portefeuille et le ledger divergent.
- PortfolioService.recompute_cash_state(portfolio) est appelé AVANT création d'ordre pour disposer du cash exact.
- L'actif doit être is_active=True, sinon 404.
- Broker et portefeuille sont re-filtrés sur user=request.user ET is_active=True (le POST ne fait jamais confiance aux IDs envoyés).
- Validation : side ∈ {BUY, SELL}, montant Decimal > 0 ; durée invalide ou ≤ 0 retombe à 5 ; duration_unit hors {s,m,h,d,t} retombe à 'm'.
- Une Strategy système synthétique (owner=None) est créée/réutilisée par get_or_create sur le slug 'quick-trade-{symbol}-{broker}-{mode}' ; son statut est PAPER si broker.mode ∈ {PAPER, DEMO} sinon LIVE, et allow_live_execution uniquement si mode == LIVE.
- ATTENTION : duration/duration_unit ne sont persistés dans strategy.parameters qu'à la CRÉATION (defaults de get_or_create). La durée réellement appliquée doit voyager dans order.metadata — c'est ce que lit infrastructure/broker_clients/deriv_client.py.
- Le Signal créé est en statut APPROVED, confidence 0.99, price=Decimal('0') (pas de prix d'entrée connu en quick trade).
- Dimensionnement : pour DERIV approved_quantity = 1 (1 contrat = 1 unité) ; pour les autres brokers approved_quantity = montant, car ni stop-loss ni prix d'entrée ne sont connus.
- StrategyDeploymentService.activate est appelé avec auto_execute=False — effet de bord : il met en PAUSED tout autre déploiement ACTIVE de cette stratégie pour cet utilisateur.
- Le message de retour DOIT distinguer PAPER (simulé localement, rien envoyé au broker) de LIVE (envoyé, avec broker_order_id) — vérité-terrain exigée côté UI.
- Pour Deriv, le contract_id est remonté depuis BrokerExternalRef (broker=DERIV, internal_kind=ORDER, kind=CONTRACT) dans un try/except : son absence ne doit pas faire échouer l'ordre.
- Toute exception de submit_order marque l'ordre FAILED et libère le cash via le rollback intégré ; la vue renvoie 500 avec le message d'erreur et logge avec asset_id/broker_id/user_id.

**Graphique chandelier temps réel**
<br>_Page chart LightweightCharts : bougies OHLC + histogramme de volume, sélecteur de timeframe, Pause/Reprise du live, Rafraîchir manuel, barre de progression de cycle, tableau des bougies, badges BULLISH/BEARISH et flash de prix._
<br>Points d'entrée : `backend/market/views.py:CandleDetailView`

- Fenêtre bornée à MAX_CANDLES = 300 bougies, chargées en DESC puis inversées pour l'affichage chronologique ; le front retronque aussi à 300 à chaque insertion WS.
- Timeframe par défaut '1m' ; si le code demandé n'existe pas, repli sur le Timeframe de plus petite granularité (order_by('minutes').first()).
- L'URL WebSocket est construite côté serveur avec le schéma wss si request.is_secure() sinon ws.
- Les bougies sont sérialisées avec open_time en epoch secondes (pour LightweightCharts) ET en ISO ; valeurs None converties en 0.0.
- Pause ferme réellement la socket (destroySocket) ; Reprise rouvre la socket ET relance un refreshData().
- Reconnexion automatique à 3 s sur onclose, sauf si en pause, et jamais plus d'un timer de reconnexion à la fois.
- Les messages WS reçus pendant la pause sont ignorés.

**Flux live des bougies (polling REST)**
<br>_Endpoint JSON renvoyant jusqu'à 300 bougies d'un actif/timeframe plus la dernière bougie, la variation absolue et en %, et un bloc méta sur l'actif. Sert au bouton Rafraîchir et de repli quand le WebSocket est coupé._
<br>Points d'entrée : `backend/market/views.py:CandleLiveFeedView.get`

- 404 JSON {'detail': 'Actif introuvable.'} si l'actif n'existe pas.
- Si le paramètre timeframe est absent ou inconnu, AUCUN filtre de timeframe n'est appliqué — la réponse mélange alors toutes les granularités (comportement actuel, piège à conserver ou corriger explicitement).
- Borne dure MAX_CANDLES = 300, ordre renvoyé chronologique croissant.
- change / change_percent valent 0 s'il n'y a pas de bougie précédente ou si son close est nul.

**Diffusion WebSocket des bougies**
<br>_Canal temps réel par actif+timeframe poussant chaque bougie créée ou mise à jour (open/high/low/close/volume/trade_count + indicateur is_new) aux clients abonnés._
<br>Points d'entrée : `backend/market/routing.py`, `backend/market/servicess/consumers.py:CandleConsumer`, `backend/market/servicess/candle_importers/deriv.py:DerivCandleImporter.import_candles (group_send)`

- Double contrôle d'accès obligatoire à la connexion : (1) l'Asset existe et is_active=True → sinon close(4403) ; (2) l'utilisateur possède au moins un Portfolio actif (= abonnement) → sinon close(4403). Anonyme → close(4401). Sans ce contrôle, n'importe quel utilisateur authentifié pouvait s'abonner à n'importe quel flux (information disclosure).
- La vérification d'accès est volontairement SANS jointure Asset↔Portfolio : les actifs de marché sont globaux, seule la condition d'abonnement filtre.
- _check_asset_access est enveloppé dans un try/except qui renvoie False : toute erreur interne refuse l'accès (fail-closed).
- Le group_discard au disconnect n'est fait que si group_name a été défini (connexion refusée très tôt = pas de fuite).
- SEUL l'importateur Deriv émet sur ce canal : les actifs Binance n'ont aucun flux temps réel malgré l'UI 'LIVE ACTIF' de la page chart.
- L'émission a lieu bougie par bougie À L'INTÉRIEUR du bloc @transaction.atomic de l'import — les clients peuvent donc voir des bougies qu'un rollback annulerait.

**Overlays des positions ouvertes sur le graphique**
<br>_Les positions réelles OPEN / PARTIALLY_CLOSED de l'utilisateur sur l'actif sont injectées dans le chart sous forme de lignes de prix : entrée (tiretée, bleu=LONG / violet=SHORT), stop loss (pointillé rouge), take profit (pointillé vert), avec légende et compteur._
<br>Points d'entrée : `backend/market/views.py:CandleDetailView.get_context_data (bloc Position)`

- Strictement les positions de request.user via portfolio__user, statut ∈ {OPEN, PARTIALLY_CLOSED}, limitées aux 20 plus récentes.
- Aucune donnée simulée : si la requête échoue, le bloc retombe sur une liste vide (try/except) et le chart s'affiche sans overlay.
- entry_price = average_entry_price si présent, sinon entry_price ; SL/TP omis si nuls.

**Liste brute des bougies (page cassée)**
<br>_Vue de listing paginé des Candle (50/page) avec filtres par actif et par timeframe, et listes de choix d'actifs/timeframes dans le contexte._
<br>Points d'entrée : `backend/market/views.py:CandleListView`

- La vue est fonctionnelle côté Python mais son template backend/templates/market/candle_list.html fait 0 octet : la page rend un écran vide. À trancher lors de la refonte (implémenter ou supprimer avec justification), ne pas reconduire en l'état.

**Import des bougies Binance**
<br>_Importation périodique des klines Binance pour tous les actifs actifs d'exchange BINANCE, en upsert, sur timeframes courts (5m/15m/1h, limit 500) et longs (4h/1d/1w/1M, limit 300)._
<br>Points d'entrée : `backend/market/tasks.py:sync_binance_klines`, `backend/market/tasks.py:sync_binance_long_klines`, `backend/market/servicess/candle_importers/binance.py:BinanceCandleImporter.import_klines`

- Refus explicite (ValueError) si asset.exchange != 'BINANCE' et si le code de timeframe n'est pas dans BINANCE_INTERVAL_MAP.
- Idempotence par update_or_create sur la clé (asset, timeframe, open_time) — l'unique_together du modèle garantit l'absence de doublons.
- Import encapsulé dans @transaction.atomic : tout ou rien par couple actif/timeframe.
- Le client est instancié SANS clés (api_key='', api_secret='') — les klines sont des données publiques, aucune credential ne doit être exigée.
- Les timestamps Binance (ms) sont convertis en datetime UTC aware.
- Une exception sur un couple actif/timeframe est capturée, loggée et comptabilisée en 'failed' dans le résumé : elle ne doit JAMAIS interrompre la boucle sur les autres actifs.
- Le résumé renvoyé agrège ok/skipped/failed + détail par ligne (contrat de sortie de la tâche).
- Cet importateur n'émet AUCUN message WebSocket (contrairement à Deriv).

**Import des bougies Deriv (avec diffusion temps réel)**
<br>_Importation périodique des bougies Deriv via WebSocket authentifié (OTP), en upsert, avec diffusion immédiate de chaque bougie sur le canal temps réel._
<br>Points d'entrée : `backend/market/tasks.py:sync_deriv_candles`, `backend/market/tasks.py:sync_deriv_long_candles`, `backend/market/servicess/candle_importers/deriv.py:DerivCandleImporter.import_candles`

- Refus (ValueError) si asset.exchange != 'DERIV' ou si le timeframe n'est pas dans DERIV_GRANULARITY_MAP (conversion code → granularité en secondes).
- Le broker utilisé est résolu globalement : premier BrokerAccount DERIV actif trié par -is_default puis id. RuntimeError si aucun. Ce n'est PAS le broker de l'utilisateur — l'import est une tâche système.
- Le type de compte préféré vient de broker.deriv_account_type (défaut 'demo') ; à défaut de correspondance, le premier compte options est pris.
- Connexion en deux temps obligatoire : get_otp_ws_url_with_retry(account_id, retries=3, sleep=2 s) puis connect_with_otp_url.
- Dégradations gracieuses renvoyant status='skipped' (jamais 'failed') : no_options_account, invalid_account, invalid_symbol (DerivClientError contenant 'InvalidSymbol').
- Toute autre DerivClientError renvoie status='failed' avec la raison, sans lever — la boucle sur les autres actifs continue.
- client.close() est garanti par un bloc finally.
- close_time est calculé comme epoch + granularité (Deriv ne renvoie que l'epoch d'ouverture).
- Chaque bougie upsertée déclenche un group_send avec le flag is_new (créée vs mise à jour) — l'émission est faite à l'intérieur du @transaction.atomic.

**Calcul des indicateurs techniques (MarketFeature)**
<br>_Calcul et persistance des features techniques par actif/timeframe/bougie : RSI 14, MACD + signal, SMA 20/50, ATR 14, bandes de Bollinger haute/basse, returns 1 et 5, volatilité 20._
<br>Points d'entrée : `backend/market/servicess/features.py:FeatureComputationService.compute_for_asset_timeframe`, `backend/market/servicess/features.py:FeatureComputationService.build_feature_row`

- Minimum absolu de 20 bougies : en deçà la méthode renvoie {'computed': 0, 'reason': 'not_enough_candles'} sans rien écrire.
- Recalcul glissant : pour idx de 20 à len(candles), les features sont recalculées sur le préfixe candles[:idx] et attribuées à la DERNIÈRE bougie du sous-ensemble — c'est ce qui garantit l'absence de look-ahead bias.
- Idempotence par update_or_create sur (asset, timeframe, candle_time), sous @transaction.atomic.
- Chaque indicateur renvoie None (et non 0) quand l'historique est insuffisant pour sa fenêtre — distinction None vs 0.0 à préserver absolument côté API et ML.
- RSI : lissage de Wilder après la moyenne initiale ; avg_loss == 0 renvoie exactement 100.0.
- MACD : recalcul d'EMA12/EMA26 sur chaque préfixe (coût O(n²)), signal = EMA9 de la série MACD, None si moins de 35 points.
- Bollinger utilise pstdev (écart-type de population), pas stdev.
- ATR : lissage de Wilder après moyenne initiale des True Ranges.
- Tâche appliquée à TOUS les actifs is_active=True, quel que soit l'exchange.

**Pipeline d'indicateurs legacy (pandas/ta)**
<br>_Seconde implémentation, indépendante, de l'import Binance et du calcul des features, basée sur pandas et la librairie `ta`, pilotée par deux commandes de management._
<br>Points d'entrée : `backend/market/services.py:import_binance_klines`, `backend/market/services.py:compute_market_features`, `backend/market/services.py:get_asset_candles`, `backend/market/indicators.py:compute_indicators`

- DOUBLON FONCTIONNEL : ces fonctions écrivent dans les mêmes tables Candle et MarketFeature que market/servicess/, avec des algorithmes différents (ta.* vs implémentation maison) — les valeurs produites ne sont pas identiques.
- compute_market_features calcule les indicateurs sur l'intégralité de l'historique en une passe pandas puis écrit une ligne par bougie (pas de recalcul glissant par préfixe).
- Les NaN pandas sont convertis en None avant écriture.
- get_asset_candles impose de toujours filtrer par timeframe pour éviter de mélanger les granularités.
- import_binance_klines ne compte que les lignes réellement créées (pas les mises à jour) et instancie BinanceClient() sans arguments (contrairement à l'importateur moderne).

**Bootstrap des données de marché**
<br>_Commande d'amorçage : crée les 8 timeframes requis, importe les bougies Binance puis Deriv, puis calcule toutes les features._
<br>Points d'entrée : `backend/market/management/commands/bootstrap_market_data.py`

- Timeframes créés en get_or_create : 5m, 15m, 30m, 1h, 4h, 1d, 1w, 1M (avec leur nombre de minutes).
- Binance couvre 5m→1M ; Deriv est volontairement limité à 5m→1d (1w et 1M exclus par prudence) ; les features sont calculées sur 5m→1M.
- Chaque couple actif/timeframe est traité dans son propre try/except : un échec est affiché en erreur mais n'arrête pas le bootstrap.

**Référentiel des instruments (seed multi-marchés)**
<br>_Commande peuplant le référentiel : 12 paires crypto Binance, 12 instruments MT5 (forex + XAU/XAG classés COMMODITY) et 22 indices synthétiques Deriv (Volatility, Volatility 1s, Boom/Crash, Jump, Step, Range Break), plus les 8 timeframes._
<br>Points d'entrée : `backend/market/management/commands/seed_market_assets.py`

- Upsert par update_or_create sur `symbol` (clé unique du modèle) — rejouable sans doublon.
- XAUUSD et XAGUSD sont requalifiés en asset_class COMMODITY alors qu'ils figurent dans la liste FOREX_MT5.
- Les synthétiques Deriv sont tous classés asset_class='INDEX' avec base_asset et quote_asset à None.
- L'ensemble de la commande s'exécute sous @transaction.atomic.
- L'exchange 'MT5' est peuplé ici alors qu'aucun importateur de bougies MT5 n'existe : ces actifs n'ont jamais de Candle.

**Administration Django du domaine marché**
<br>_Back-office sur Asset (listage/filtres/recherche), Timeframe, Candle (avec date_hierarchy sur open_time) et MarketFeature._
<br>Points d'entrée : `backend/market/admin.py`

- Seul chemin d'écriture manuelle existant sur le référentiel : aucune vue applicative ne permet de créer ou modifier un Asset ou un Timeframe.
- AssetForm et TimeframeForm (backend/market/forms.py) ne sont référencés par aucune vue — code mort.

**Liste des stratégies (cartes temps réel)**
<br>_Page de pilotage : cartes de stratégie (nom, symbole, timeframe, type, statut, badges AUTO/INACTIF, signaux 24h / total, dernier signal), compteurs globaux, filtres côté client (Toutes/Actives/Autonomes/LIVE/PAPER/BACKTEST), polling 10 s, et actions Activer/Désactiver + Auto/Manuel en AJAX._
<br>Points d'entrée : `backend/strategies/views.py:StrategyListView`, `backend/strategies/views.py:strategy_list_api`

- La liste serveur applique Strategy.objects.visible_to(user) : staff voit tout ; sinon uniquement ses stratégies (owner=user) et les stratégies système (owner IS NULL) ; anonyme ne voit rien.
- Le contenu réellement affiché provient du polling /strategies/api/, pas du queryset serveur — les filtres GET (status, strategy_type, asset_class, q) n'agissent que sur le contexte summary/filters, pas sur les cartes.
- Les boutons d'action ne sont rendus que si can_manage (staff ou propriétaire), calculé côté API.
- L'AJAX de bascule retombe sur une soumission de formulaire classique en cas d'échec du fetch (dégradation gracieuse).

**Flux JSON des stratégies**
<br>_Endpoint renvoyant les stratégies visibles avec compteur de signaux total et sur 24 h, symbole, timeframe, statut, drapeaux is_active/is_autonomous, dernier signal et droit de gestion._
<br>Points d'entrée : `backend/strategies/views.py:strategy_list_api`

- Les compteurs signal_count et recent_signals sont filtrés sur les signaux VISIBLES par l'utilisateur (Signal.objects.visible_to) — un utilisateur ne doit jamais voir le volume de signaux d'un autre tenant sur une stratégie système partagée.
- La fenêtre 'récent' est de 24 h glissantes (timezone.now() - 24h).
- can_manage = is_staff OU owner_id == user.id.
- Tri : stratégies actives d'abord (-is_active), puis par nom.
- Les Count sont distinct=True pour éviter la multiplication par jointure.

**Détail d'une stratégie (tableau de bord)**
<br>_Vue la plus riche du domaine : score de santé 0-100, KPI de signaux par statut et par sens, activité 24h/7j, taux de succès des runs, métriques interprétées (win rate, Sharpe, drawdown, confiance moyenne, retour moyen) avec libellés et classes CSS, graphique de performance, donut de répartition des signaux, règles d'entrée/sortie rendues lisibles, paramètres de risque, derniers signaux, derniers runs, versions du modèle, prédictions récentes, dernier backtest, déploiements._
<br>Points d'entrée : `backend/strategies/views.py:StrategyDetailView`, `backend/strategies/views.py:StrategyDetailView._health_score`

- Formule de santé à préserver : win_rate min(wr/0.60,1)×40 + Sharpe min(max(s,0)/2.0,1)×30 + drawdown (20 pts si ≤0, sinon max(0, 1−dd/20)×20) + activité 7j min(n/3,1)×10, plafonné à 100 et arrondi à 1 décimale. Paliers : ≥75 Excellente, ≥55 Bonne, ≥35 Moyenne, sinon Faible.
- Seuils d'interprétation : win rate 0.65/0.50 ; Sharpe 2.0/1.0/0.5 ; drawdown 5/15 ; confiance 0.75/0.55.
- Toutes les agrégations de signaux passent par Signal.objects.visible_to(user) — un propriétaire ne voit jamais les signaux d'un autre utilisateur sur une stratégie système.
- Les StrategyRun et StrategyPerformanceSnapshot sont en revanche filtrés uniquement par strategy, SANS cloisonnement par utilisateur (asymétrie actuelle à trancher explicitement lors de la refonte).
- Les backtests sont filtrés sur requested_by=user sauf pour le staff, dans un try/except (l'app leo_backtesting peut être absente sans casser la page).
- can_manage_strategy = Strategy.objects.mutable_by(user) ; can_deploy_strategy = stratégie système (owner NULL) OU propriétaire.
- deployment_portfolios ne liste que les portefeuilles actifs de l'utilisateur.
- Les métriques de performance proviennent du DERNIER StrategyPerformanceSnapshot ; en son absence tout vaut 0.0 (et non null).
- Les bornes : 30 derniers signaux, 30 derniers runs, 120 snapshots, 10 prédictions.

**Activer / désactiver une stratégie**
<br>_Bascule du drapeau is_active d'une stratégie depuis la liste ou le détail._
<br>Points d'entrée : `backend/strategies/views.py:StrategyToggleActiveView.post`

- Opération sous @transaction.atomic.
- EFFET DE BORD CRITIQUE : désactiver une stratégie met immédiatement en PAUSED tous ses déploiements ACTIVE, force auto_execute=False et horodate paused_at. Cette cascade doit être conservée, sinon une stratégie désactivée continuerait d'exécuter des ordres.
- Seules les stratégies mutable_by(user) (staff ou propriétaire) sont modifiables ; sinon message d'erreur et redirection vers la liste.
- Les stratégies système (owner NULL) ne sont PAS mutables par un utilisateur non staff.

**Basculer le mode autonome**
<br>_Bascule du drapeau is_autonomous qui autorise la stratégie à être exécutée par le runner automatique._
<br>Points d'entrée : `backend/strategies/views.py:StrategyToggleAutonomousView.post`

- Opération sous @transaction.atomic.
- EFFET DE BORD CRITIQUE : retirer le mode autonome force auto_execute=False sur TOUS les déploiements de la stratégie. Invariant : auto_execute ne peut exister sans is_autonomous (également contrôlé dans StrategyDeployment.clean()).
- Réservé à mutable_by(user).

**Changer le statut d'une stratégie (cycle de vie)**
<br>_Transition de statut DRAFT → BACKTEST → PAPER → LIVE → PAUSED → ARCHIVED (ou FAILED), avec frise de cycle de vie dans l'UI._
<br>Points d'entrée : `backend/strategies/views.py:StrategySwitchStatusView.post`

- Le statut demandé doit appartenir à l'allow-list {DRAFT, BACKTEST, PAPER, LIVE, PAUSED, ARCHIVED, FAILED}.
- GARDE-FOU LIVE : passer en LIVE exige simultanément is_active=True, allow_live_execution=True ET au moins un déploiement ACTIVE en mode LIVE (restreint au propriétaire si la stratégie en a un). À défaut, refus avec message explicite.
- Après changement de statut, tous les déploiements ACTIVE dont execution_mode ne correspond pas au mode attendu (LIVE pour LIVE, PAPER pour PAPER) sont mis en PAUSED avec auto_execute=False et paused_at horodaté. Pour les autres statuts (DRAFT/BACKTEST/ARCHIVED…), expected_mode est None et AUCUN déploiement n'est mis en pause — comportement actuel à conserver ou corriger explicitement.
- Aucune machine à états formelle : toutes les transitions de l'allow-list sont permises dans n'importe quel ordre, hors garde-fou LIVE.
- Réservé à mutable_by(user).

**Activer un déploiement (stratégie → portefeuille → broker)**
<br>_Liaison contrôlée d'une stratégie à un portefeuille de l'utilisateur et à son broker, avec option d'auto-exécution. Une stratégie Live ne peut envoyer aucun ordre sans ce lien._
<br>Points d'entrée : `backend/strategies/views.py:StrategyDeploymentActivateView.post`, `backend/strategies/services/deployment.py:StrategyDeploymentService.activate`, `backend/strategies/models.py:StrategyDeployment.clean`

- Verrouillage pessimiste obligatoire : select_for_update sur la Strategy, le Portfolio et le StrategyDeployment, le tout sous @transaction.atomic — empêche deux activations concurrentes.
- Un déploiement en statut REVOKED ne peut JAMAIS être réactivé.
- UNICITÉ : activer met en PAUSED tout autre déploiement ACTIVE de ce couple (stratégie, utilisateur) — garanti aussi par la contrainte uniq_active_strat_user_dep. Contrainte uniq_strat_user_portfolio_dep : un seul déploiement par triplet (stratégie, utilisateur, portefeuille).
- execution_mode est IMPOSÉ par broker_account.mode, jamais choisi par l'utilisateur ; le broker est celui du portefeuille.
- StrategyDeployment.save() appelle full_clean() — les validations de clean() sont donc des invariants de base, pas de simples contrôles de formulaire.
- Validations de clean() : le déploiement appartient au propriétaire de la stratégie ; le portefeuille appartient à l'utilisateur ; le broker appartient à l'utilisateur ; le broker est celui du portefeuille ; la version appartient à la stratégie ; execution_mode == broker.mode.
- Validations supplémentaires quand status == ACTIVE : stratégie active, portefeuille actif, broker actif ; en mode LIVE : allow_live_execution requis, broker.status == 'ACTIVE' et last_connection_status vrai (connexion validée) ; auto_execute exige strategy.is_autonomous.
- L'activation réinitialise last_error, horodate activated_at, trace activated_by et remet paused_at à None.

**Mettre en pause un déploiement**
<br>_Suspension d'un déploiement actif : la stratégie cesse d'émettre des ordres sur ce portefeuille._
<br>Points d'entrée : `backend/strategies/views.py:StrategyDeploymentPauseView.post`, `backend/strategies/services/deployment.py:StrategyDeploymentService.pause`

- Double contrôle : la vue vérifie d'abord que le déploiement appartient à l'utilisateur ET à cette stratégie, puis le service refiltre par owned_by(user) avec select_for_update sous @transaction.atomic.
- Un déploiement REVOKED ne peut pas être modifié.
- La mise en pause force toujours auto_execute=False en plus du statut PAUSED — jamais de pause qui laisserait l'auto-exécution armée.

**Résolution du déploiement au moment de l'ordre**
<br>_Contrôle central appelé avant tout passage d'ordre issu d'un signal : détermine et valide le déploiement autorisé pour le couple utilisateur/portefeuille/broker._
<br>Points d'entrée : `backend/strategies/services/deployment.py:StrategyDeploymentService.resolve_for_order`

- RÈGLE DE SÉCURITÉ MAÎTRESSE : une stratégie dont le statut n'est pas LIVE ne peut pas émettre d'ordre sur un broker en mode LIVE (levée immédiate avant toute autre vérification).
- Un déploiement n'est EXIGÉ que si strategy.status == 'LIVE' ; hors LIVE, resolve_for_order peut renvoyer None et l'ordre passe sans déploiement.
- Si aucun déploiement n'est fourni et que la stratégie est LIVE, recherche d'un déploiement ACTIVE correspondant exactement à (stratégie, utilisateur, portefeuille, broker, execution_mode='LIVE') ; absence → erreur.
- Chaîne de vérifications non négociable : statut ACTIVE, user_id correspond, portfolio_id correspond, broker_account_id correspond, strategy_id correspond au signal, stratégie LIVE ⇒ déploiement LIVE, stratégie PAPER ⇒ déploiement PAPER.
- Un full_clean() final rejoue toutes les validations d'intégrité du modèle juste avant l'ordre — la validation à l'activation ne suffit pas, l'état a pu changer entre-temps.

**Liste des signaux**
<br>_Page de listing paginé (30/page) des signaux visibles avec filtres statut, sens et stratégie._
<br>Points d'entrée : `backend/strategies/views.py:SignalListView`

- Cloisonnement Signal.objects.visible_to(user) : staff tout ; sinon les signaux dont user == soi, OU les signaux sans destinataire dont la stratégie lui appartient, OU les signaux sans destinataire d'une stratégie système.
- Tri par -candle_time, select_related sur user/strategy/owner/asset/timeframe (anti N+1).
- ANOMALIE À NE PAS REPRODUIRE : le template signal_list.html n'affiche PAS les signaux — il rend le tableau des stratégies (variable `strategies` du contexte, destinée au filtre) avec le titre « Pilotage des stratégies ». La pagination et les filtres statut/side sont donc sans effet visible. La fonctionnalité « liste des signaux » est à reconstruire côté client.

**Détail d'un signal**
<br>_Fiche signal : sens, confiance, prix, ratio risque/rendement, stratégie, motif, statut, expiration, snapshot de features et sortie brute du modèle._
<br>Points d'entrée : `backend/strategies/views.py:SignalDetailView`, `backend/strategies/models.py:Signal.rr_ratio`

- Accès restreint à visible_to(user).
- can_review_signal est calculé séparément via reviewable_by(user) — plus strict que visible_to : exclut les signaux de stratégies système sans propriétaire, qui sont affichés en lecture seule avec la mention « Signal système en lecture seule ».
- Calcul du R/R : BUY → risk = entrée−SL, reward = TP−entrée ; SELL → risk = SL−entrée, reward = entrée−TP ; renvoie 0.0 si SL, TP ou prix manquant, si side == HOLD, ou si risk ≤ 0 (jamais de division par zéro ni de R/R négatif).

**Approuver / rejeter un signal**
<br>_Validation humaine d'un signal avant exécution : approbation ou rejet, avec traçabilité du validateur._
<br>Points d'entrée : `backend/strategies/views.py:SignalApproveView`, `backend/strategies/views.py:SignalRejectView`, `backend/strategies/services/signal_review.py:SignalReviewService.review`, `backend/api/views/execution.py:OrderViewSet.create_manual`

- Décision normalisée en majuscules et restreinte à {APPROVED, REJECTED} — toute autre valeur est rejetée.
- Verrouillage select_for_update sous @transaction.atomic : pas de double validation concurrente.
- Le signal doit être reviewable_by(user) : staff, destinataire, ou propriétaire d'une stratégie dont le signal n'a pas de destinataire. Les signaux système purs ne sont PAS validables.
- UN SIGNAL EXPIRÉ NE PEUT PLUS ÊTRE VALIDÉ : si expires_at est passé, refus explicite.
- Statuts d'origine autorisés : {NEW, SCORED, APPROVED, REJECTED}. Un signal QUEUED, EXECUTED, EXPIRED, CANCELLED ou FAILED ne peut plus être revalidé.
- approved_at est posé à l'instant de l'approbation et REMIS À None en cas de rejet (un rejet efface l'approbation antérieure).
- reviewed_by et reviewed_at sont toujours tracés.
- Dans l'API d'ordre manuel, un signal dont le statut n'est ni APPROVED ni QUEUED est approuvé automatiquement via ce même service — l'approbation implicite doit rester soumise aux mêmes règles (expiration, propriété, statut).

**Historique et diagnostic des runs de stratégie**
<br>_Liste paginée (30/page) des exécutions de stratégie avec filtres stratégie et statut, et page de détail affichant statut, durée en ms, candle_time, fin, message d'erreur et snapshots d'entrée/sortie JSON._
<br>Points d'entrée : `backend/strategies/views.py:StrategyRunListView`, `backend/strategies/views.py:StrategyRunDetailView`

- Les runs sont restreints aux stratégies visible_to(user) — un utilisateur ne voit pas les runs d'une stratégie d'un autre tenant, mais il VOIT tous les runs d'une stratégie système, y compris ceux déclenchés par les déploiements d'autres utilisateurs (input_snapshot contient deployment_id, portfolio_id, broker_account_id : fuite potentielle inter-tenant à corriger).
- input_snapshot et output_snapshot sont rendus bruts dans la page de détail.
- Les filtres du listing ne sont pas exposés dans le template de liste (pas de formulaire), uniquement via query string.

**Moteur de génération de signaux IA**
<br>_Chaîne complète : lecture du dernier MarketFeature, prédiction par le modèle, enregistrement de la prédiction, contrôles de risque, calcul du SL/TP sur ATR, création du Signal puis routage._
<br>Points d'entrée : `backend/strategies/services/signal_engine.py:SignalEngineService.predict_signal`, `backend/strategies/services/signal_engine.py:SignalEngineService.create_signal`, `backend/strategies/services/signal_engine.py:SignalEngineService.compute_sl_tp`, `backend/strategies/services/signal_engine.py:SignalEngineService.evaluate_and_route`

- Liste figée de 11 features consommées par le modèle, dans cet ordre : rsi_14, macd, macd_signal, sma_20, sma_50, atr_14, bb_high, bb_low, returns_1, returns_5, volatility_20.
- Les features None sont converties en 0.0 avant inférence (`getattr(...) or 0.0`) — attention, cela écrase aussi les 0.0 légitimes.
- Absence de MarketFeature pour (asset, timeframe) → ValueError « Aucune feature disponible » : le run échoue au lieu d'émettre un signal par défaut.
- La StrategyPrediction est créée AVANT tout contrôle de risque : on conserve donc la trace de toutes les prédictions, même celles qui ne deviendront jamais un signal (c'est la base du calcul d'exactitude du modèle).
- ORDRE DES GARDE-FOUS, à préserver : (1) can_emit_signal, (2) passes_confidence_threshold, (3) daily_signal_limit_ok — chacun lève une ValueError qui fait échouer le run.
- Le destinataire du signal est user explicite, sinon strategy.owner ; la limite quotidienne est comptée PAR UTILISATEUR quand il est connu (multi-tenant sur une stratégie système partagée).
- Le prix du signal est le close de la bougie dont open_time == feature.candle_time pour le timeframe de la stratégie ; 0 si introuvable.
- SL/TP calculés sur l'ATR : BUY → SL = prix − ATR×atr_stop_mult, TP = prix + ATR×atr_tp_mult ; SELL → inverse. Multiplicateurs lus dans strategy.parameters (défauts 1.5 et 3.0). ATR nul ou absent ⇒ (None, None), jamais de SL/TP inventé.
- expires_at = candle_time + 2 × run_interval_seconds — un signal non validé dans deux cycles n'est plus exécutable.
- Le signal est créé en statut NEW puis immédiatement routé.

**Routage d'exécution des signaux**
<br>_Décide du devenir d'un signal fraîchement créé : publication en lecture seule, approbation automatique, mise en file d'auto-exécution ou blocage pour défaut de déploiement._
<br>Points d'entrée : `backend/strategies/services/execution_router.py:StrategyExecutionRouter.route`, `backend/strategies/services/execution_router.py:StrategyExecutionRouter._enqueue`

- CAS 1 — signal sans destinataire ET stratégie sans propriétaire : statut SCORED, « Opportunité système publiée en lecture seule ». Jamais d'exécution.
- CAS 2 — stratégie PAPER + déploiement PAPER + auto_execute + is_autonomous : statut QUEUED, model_output enrichi de strategy_deployment_id et routing='AUTO_EXECUTION_QUEUED', mise en file.
- CAS 3 — stratégie non LIVE hors cas 2 : statut APPROVED avec approved_at = reviewed_at = maintenant (approbation automatique en mode non-live).
- CAS 4 — stratégie LIVE : résolution obligatoire du déploiement via resolve_for_order. Échec ⇒ statut SCORED avec routing='BLOCKED_NO_DEPLOYMENT' et routing_error conservé — le signal n'est jamais perdu, il devient consultable mais non exécutable.
- CAS 5 — LIVE + déploiement valide + auto_execute + is_autonomous : QUEUED + mise en file. Sinon SCORED avec routing='USER_APPROVAL_REQUIRED'.
- L'auto-exécution exige TOUJOURS la conjonction deployment.auto_execute ET strategy.is_autonomous — l'un sans l'autre ne suffit jamais.
- La mise en file passe par transaction.on_commit : la tâche Celery ne doit jamais partir avant que le signal soit réellement committé en base (sinon la tâche ne trouverait pas le signal).

**Auto-exécution d'un signal déployé**
<br>_Tâche Celery convertissant un signal QUEUED en ordre réel via l'orchestrateur d'exécution, avec dimensionnement calculé à partir du risque de la stratégie._
<br>Points d'entrée : `backend/strategies/tasks.py:execute_deployed_signal_task`, `backend/strategies/tasks.py:_strategy_stake`

- IDEMPOTENCE : si signal.status != 'QUEUED', la tâche sort en succès avec skipped=True — un rejeu Celery ne doit jamais produire un second ordre.
- Clé d'idempotence transmise à l'orchestrateur : 'strategy-deployment:{deployment_id}:signal:{signal_id}'.
- Signal ou déploiement introuvable ⇒ retour {'ok': False, 'reason': 'signal_or_deployment_missing'} sans exception (pas de retry infini).
- resolve_for_order est rejoué AVANT l'ordre, même si le routeur l'avait déjà validé : l'état a pu changer entre la mise en file et l'exécution.
- Dimensionnement _strategy_stake : equity (ou current_balance) × risk_per_trade_percent / 100, plafonné par max_position_size s'il est > 0, puis par available_cash s'il est > 0, arrondi à 0.01 et JAMAIS inférieur à 0.01.
- Le mode de l'ordre est imposé par deployment.execution_mode, source='STRATEGY'.
- Toute exception met le signal en FAILED et enregistre auto_execution_error dans model_output (trace de diagnostic conservée), avec log exception.
- En succès, execution_order_id et strategy_deployment_id sont écrits dans model_output — c'est le lien signal ↔ ordre.

**Exécution planifiée des stratégies autonomes**
<br>_Boucle exécutant chaque minute toutes les stratégies actives et autonomes, une exécution par déploiement actif compatible, avec journalisation complète en StrategyRun._
<br>Points d'entrée : `backend/strategies/services/strategy_runner.py:StrategyRunnerService.run_all_autonomous`, `backend/strategies/services/strategy_runner.py:StrategyRunnerService.run_one`, `backend/strategies/management/commands/run_strategies.py`

- Périmètre : is_active=True ET is_autonomous=True, en excluant les statuts PAUSED, ARCHIVED et FAILED.
- Appariement strict statut ⇄ mode : statut LIVE ⇒ seuls les déploiements execution_mode='LIVE' ; statut PAPER ⇒ seuls les PAPER ; TOUT AUTRE STATUT ⇒ liste de déploiements vidée (un DRAFT/BACKTEST ne s'exécute jamais contre un déploiement).
- Si la stratégie a un propriétaire, seuls les déploiements de ce propriétaire sont retenus.
- Stratégie LIVE sans aucun déploiement actif ⇒ un StrategyRun SKIPPED est créé avec le message « Aucun déploiement Live actif. » : la tentative est tracée, jamais silencieuse.
- Stratégie non LIVE sans déploiement ⇒ run_one est quand même appelé sans déploiement (génération de signal en mode non exécutant).
- Un déploiement passé à run_one doit appartenir à la stratégie, sinon ValueError.
- ISOLATION DES ÉCHECS : run_one capture TOUTE exception, marque le run FAILED avec error_message, renseigne strategy.last_error et last_run_at, puis RENVOIE le run au lieu de propager — l'échec d'une stratégie ne doit jamais interrompre les autres.
- En succès, last_error est explicitement vidé et le Signal généré est rattaché au run (signal.strategy_run) après coup.
- runtime_ms est mesuré avec time.perf_counter pour chaque run, succès comme échec.
- input_snapshot capture l'état d'entrée (stratégie, actif, timeframe, statut, autonomie, déploiement, portefeuille, broker) ; output_snapshot capture signal_id, side, statut et confiance.

**Garde-fous de risque au niveau stratégie**
<br>_Contrôles de risque préalables à l'émission d'un signal : état de la stratégie, seuil de confiance, quota quotidien, drawdown et exposition du portefeuille, état du wallet._
<br>Points d'entrée : `backend/strategies/services/risk_guard.py:StrategyRiskGuard`

- can_emit_signal : refus si is_active=False, ou si le statut est PAUSED, ARCHIVED ou FAILED.
- passes_confidence_threshold : refus si confidence < min_confidence_threshold (traité comme 0.0 si None).
- daily_signal_limit_ok : comptage des signaux du JOUR CALENDAIRE courant (created_at__date), filtré par utilisateur quand il est fourni ; refus si count >= max_signals_per_day. Un max_signals_per_day à 0 désactive la limite (valeur falsy).
- portfolio_risk_ok : refus si current_drawdown_percent >= max_daily_drawdown_percent ; refus si la somme des exposure_value des positions OPEN rapportée à l'equity atteint max_total_exposure_percent. Un portefeuille absent passe toujours.
- wallet_risk_ok : refus si wallet inactif ou available_balance <= 0 ; wallet absent passe toujours.
- ATTENTION : portfolio_risk_ok et wallet_risk_ok ne sont appelés nulle part dans le flux actuel de création de signal — seules les trois premières règles sont effectivement appliquées. À arbitrer explicitement lors de la refonte.
- Toutes les méthodes renvoient un tuple (bool, motif) : le motif est remonté tel quel dans le message d'erreur du run.

**Chargement et inférence multi-backend des modèles ML**
<br>_Service de chargement d'un modèle depuis un chemin et d'inférence normalisée, avec adaptateurs sklearn, XGBoost, LightGBM, CatBoost, PyTorch et TensorFlow._
<br>Points d'entrée : `backend/strategies/services/ml.py:StrategyModelService`, `backend/strategies/services/ml.py:BaseModelAdapter et ses 6 sous-classes`

- Fichier de modèle absent ⇒ StrategyModelServiceError explicite (jamais de modèle par défaut silencieux).
- Backend : valeur explicite de strategy.parameters['ml_backend'] si fournie, sinon auto-détection par inspection du module/classe du modèle, avec repli sur 'sklearn'.
- Chargement : tf.keras.models.load_model pour tensorflow, torch.load(map_location='cpu') pour pytorch, joblib.load sinon.
- Mapping de labels unifié et figé : 1/'1'/'BUY' → BUY, -1/'-1'/'SELL' → SELL, 0/'0'/'HOLD' → HOLD ; tout label inconnu retombe sur HOLD (jamais d'erreur ni de direction inventée).
- Si le modèle expose feature_names_in_, l'ORDRE des colonnes est imposé par le modèle et toute feature manquante lève une erreur listant les noms absents — garde-fou contre le désalignement de features.
- Toutes les valeurs de features sont converties en float ; une valeur non convertible lève une erreur nommant la feature fautive.
- Pour LightGBM/PyTorch/TensorFlow, une sortie à 3 composantes est interprétée dans l'ordre [SELL, HOLD, BUY] ; PyTorch applique un softmax stabilisé (exp(x − max)).
- Pour les sorties scalaires, le sens est déterminé par le signe et la confiance est la valeur absolue.
- La confiance vaut 0.0 quand aucune probabilité n'est disponible (jamais de confiance inventée), ce qui fait ensuite échouer le seuil de confiance si celui-ci est > 0.
- Les échecs de predict_proba sont avalés silencieusement (probabilités laissées à 0.0) pour ne pas casser l'inférence.
- La réponse est toujours enrichie de features_used et model_path (traçabilité de l'inférence).

**Versionnage automatique des stratégies**
<br>_Signaux Django maintenant les versions de stratégie et l'horodatage du dernier signal._
<br>Points d'entrée : `backend/strategies/services/signals.py:create_initial_strategy_version`, `backend/strategies/services/signals.py:ensure_single_live_version`, `backend/strategies/services/signals.py:update_strategy_last_signal`

- À la création d'une stratégie, une StrategyVersion '1.0.0' est générée automatiquement si aucune n'existe, copiant model_path, parameters, entry_rules et exit_rules.
- Cette version initiale est marquée is_live=True uniquement si le statut de la stratégie est PAPER ou LIVE.
- INVARIANT : une seule version is_live par stratégie — le pre_save bascule à False toutes les autres versions live de la stratégie avant d'enregistrer la nouvelle.
- À la création d'un Signal, Strategy.last_signal_at est mis à jour via un UPDATE direct (pas de save() complet) pour éviter de redéclencher les signaux Django.
- Unicité de version garantie par unique_together (strategy, version).

**Prédictions du modèle et évaluation prévision/réalité**
<br>_Enregistrement de chaque sortie brute du modèle (label, score, probabilités haut/bas, snapshot des features) puis confrontation a posteriori à la bougie réelle suivante pour calculer un taux d'exactitude._
<br>Points d'entrée : `backend/strategies/services/signal_engine.py:SignalEngineService.predict_signal (création)`, `backend/ai_engine/services_performance.py:PredictionEvaluationService.evaluate_pending`, `backend/ai_engine/services_performance.py:PredictionEvaluationService.accuracy`

- Seules les prédictions non encore évaluées (is_correct IS NULL) et avec un predicted_label non vide sont traitées, par lots de 500, triées par candle_time croissant.
- La « réalité » est la PREMIÈRE bougie strictement postérieure (open_time > candle_time) sur le même actif ET le même timeframe. Si elle n'existe pas encore, la prédiction est laissée en attente et sera réessayée — jamais marquée incorrecte par défaut.
- Direction réelle : close > open → UP, close < open → DOWN, égalité → FLAT.
- Vocabulaire de labels accepté : UP/BUY/LONG/BULLISH/CALL pour la hausse, DOWN/SELL/SHORT/BEARISH/PUT pour la baisse ; tout autre label (ex. NEUTRAL, HOLD) est jugé correct uniquement si la réalité est FLAT.
- L'évaluation est idempotente par construction (filtre is_correct IS NULL) et n'écrit que actual_label, is_correct et evaluated_at.
- accuracy() ne compte QUE les prédictions réellement évaluées sur la fenêtre demandée (30 jours par défaut) et renvoie accuracy=None si l'échantillon est vide — jamais de 0 % trompeur.

**Snapshots de performance de stratégie**
<br>_Modèle d'historisation des métriques de performance (nombre de signaux, signaux exécutés, win rate, retour moyen, Sharpe, drawdown max) servant les KPI et les courbes de la page détail._
<br>Points d'entrée : `backend/strategies/models.py:StrategyPerformanceSnapshot`, `backend/strategies/views.py:StrategyDetailView.get_context_data`

- AUCUN PRODUCTEUR DANS LE CODE : aucune tâche, service ni commande n'écrit de StrategyPerformanceSnapshot. La table n'est alimentée que manuellement (admin/shell/import). En conséquence, win rate, Sharpe, drawdown et retour moyen affichés valent 0.0 par défaut et le score de santé est structurellement sous-évalué.
- Les 120 snapshots les plus anciens (order_by('snapshot_time')[:120]) sont utilisés pour la courbe, et le DERNIER élément de cette tranche sert de « snapshot courant » — ce n'est pas nécessairement le plus récent en base si plus de 120 snapshots existent.
- Les snapshots ne sont PAS cloisonnés par utilisateur (filtre sur strategy seul).

**Cloisonnement multi-tenant des stratégies et signaux**
<br>_Couche de QuerySets définissant qui voit, modifie, valide et exécute quoi, y compris pour les stratégies système partagées en lecture seule._
<br>Points d'entrée : `backend/strategies/models.py:StrategyQuerySet.visible_to / mutable_by`, `backend/strategies/models.py:SignalQuerySet.visible_to / reviewable_by / executable_by / actionable_by`, `backend/strategies/models.py:StrategyDeploymentQuerySet.owned_by / active`, `backend/strategies/models.py:Signal.save / Signal.clean`, `backend/strategies/models.py:Strategy.save`

- Strategy.visible_to : staff → tout ; sinon owner=user OU owner IS NULL (stratégies système en lecture) ; anonyme → rien.
- Strategy.mutable_by : staff → tout ; sinon STRICTEMENT owner=user — les stratégies système ne sont pas modifiables par un utilisateur simple.
- Signal.visible_to : staff → tout ; sinon user=soi, OU (user NULL ET stratégie m'appartenant), OU (user NULL ET stratégie système).
- Signal.reviewable_by : plus strict — staff, user=soi, ou (user NULL ET stratégie m'appartenant). Les signaux système purs sont exclus.
- Signal.executable_by : ignore le statut staff et exige user=soi ou (user NULL ET stratégie m'appartenant) — même un administrateur ne doit pas exécuter le signal d'un autre. actionable_by est un alias d'executable_by.
- AUTO-ATTRIBUTION : à la création, un Signal sans user hérite automatiquement de strategy.owner_id si la stratégie a un propriétaire.
- Signal.clean (appelé systématiquement depuis save) : le strategy_run doit appartenir à la même stratégie ; le destinataire doit être le propriétaire de la stratégie si elle en a un.
- Contraintes d'unicité sur Strategy : (owner, name) et (owner, slug) uniques, plus unicité globale de name et slug pour les stratégies système (owner IS NULL).
- Génération de slug : slugify(name) avec suffixe incrémental -2, -3… en cas de collision POUR LE MÊME propriétaire.
- owner et user sont en on_delete=PROTECT : un utilisateur portant des stratégies ou des signaux ne peut pas être supprimé (à préserver pour l'audit).

**Administration Django du domaine stratégies**
<br>_Back-office sur Strategy (slug prérempli depuis le nom), Signal (hiérarchie de dates sur candle_time) et StrategyDeployment (champs d'horodatage en lecture seule)._
<br>Points d'entrée : `backend/strategies/admin.py`

- Seul chemin de CRÉATION et d'ÉDITION complète d'une Strategy : aucune vue applicative ne permet de créer ou modifier une stratégie (pas de CreateView/UpdateView câblée, StrategyForm est du code mort).
- StrategyVersion, StrategyRun, StrategyPrediction et StrategyPerformanceSnapshot ne sont PAS enregistrés dans l'admin.
- Sur StrategyDeployment, activated_at, paused_at, created_at et updated_at sont en lecture seule ; mais une édition en admin déclenche full_clean() via save() et peut donc échouer sur les invariants métier.

**Lancement d'un backtest depuis la fiche stratégie**
<br>_Boutons « Nouveau backtest » (avec confirmation navigateur) et « Dernier backtest » exposés sur la page de détail de la stratégie._
<br>Points d'entrée : `backend/strategies/views.py:StrategyDetailView.get_context_data (latest_backtest)`, `backend/leo_backtesting/urls.py:LaunchBacktestView / BacktestDetailView`

- Le bouton « Nouveau backtest » est rendu SANS vérification de can_manage_strategy, contrairement aux autres actions de la page — n'importe quel utilisateur voyant la stratégie (y compris une stratégie système) peut tenter un lancement ; le contrôle d'accès repose entièrement sur LaunchBacktestView.
- Le dernier backtest affiché est filtré sur requested_by=user sauf pour le staff.
- Confirmation navigateur obligatoire avant soumission (onsubmit confirm).

</details>

<details><summary>Pièges de migration repérés</summary>

- Le dépôt a été restructuré en monorepo PENDANT cette cartographie : tous les chemins cités sont désormais sous backend/ (backend/market/, backend/strategies/, backend/templates/...). Les imports Python restent `market.*` et `strategies.*`.
- DOUBLON D'IMPLÉMENTATION DES INDICATEURS : market/services.py + market/indicators.py (pandas + librairie `ta`) et market/servicess/features.py (implémentation maison en pur Python) écrivent dans la MÊME table MarketFeature avec des algorithmes différents (ex. Bollinger via pstdev vs ta.BollingerBands, recalcul glissant par préfixe vs passe unique). Selon le chemin emprunté (tâches Celery vs commandes import_binance_ohlcv/compute_features), les valeurs diffèrent. À unifier avant migration, sinon les signaux IA ne seront pas reproductibles.
- DOSSIER MAL NOMMÉ : market/servicess/ (double s) contient le code réellement utilisé en production (importateurs, features, consumer WS), tandis que market/services.py contient le code legacy. Piège de lecture et de refactoring.
- TEMPLATE VIDE : backend/templates/market/candle_list.html fait 0 octet. L'URL /market/candles/ (name=candle-list) répond 200 avec une page blanche. Ne pas reconduire en l'état : implémenter ou supprimer avec justification.
- TEMPLATE INVERSÉ : backend/templates/strategies/signal_list.html n'affiche PAS les signaux mais le tableau des stratégies (variable `strategies` du contexte, titre « Pilotage des stratégies »). La fonctionnalité « liste des signaux » n'existe donc pas réellement côté UI alors que la vue, la pagination et les filtres sont implémentés côté Python.
- BOUTON CASSÉ : dans asset_list.html, le bouton « Trader » pointe en GET vers {% url 'asset-quick-trade' %}, alors que AssetQuickTradeView n'implémente que post() → réponse 405. Le trade rapide n'est réellement accessible que depuis la fiche actif.
- TEMPS RÉEL PARTIEL : seul DerivCandleImporter émet sur le canal WebSocket. Les actifs Binance n'ont aucun flux live alors que la page chart affiche « LIVE ACTIF » et un badge vert clignotant. Les actifs MT5 n'ont même aucun importateur de bougies.
- CODE MORT TEMPS RÉEL : core.realtime.RealtimeBroadcastService.broadcast_candle n'est appelé nulle part ET émettrait type='broadcast.message', un handler que CandleConsumer n'implémente pas (il n'a que candle_update). Deux conventions de message incompatibles coexistent.
- ÉMISSION WS DANS UNE TRANSACTION : DerivCandleImporter diffuse chaque bougie par group_send à l'intérieur de son bloc @transaction.atomic. Un rollback laisserait les clients avec des bougies qui n'existent pas en base. Utiliser transaction.on_commit lors de la refonte.
- MODÈLE SANS PRODUCTEUR : StrategyPerformanceSnapshot est lu par la page détail stratégie mais AUCUN code ne l'écrit. Tous les KPI de performance (win rate, Sharpe, drawdown, retour moyen) et le score de santé sont donc à 0 en pratique. Il faut soit implémenter le calcul, soit le remplacer par un calcul à la volée.
- GARDE-FOUS INACTIFS : StrategyRiskGuard.portfolio_risk_ok et wallet_risk_ok sont implémentés mais n'ont aucun appelant. Les limites max_daily_drawdown_percent, max_total_exposure_percent et l'état du wallet ne sont donc PAS vérifiées avant l'émission d'un signal, malgré leur présence dans l'UI « Paramètres de risque ».
- CODE MORT DRF : market/serializers.py (Asset/Timeframe/Candle/MarketFeature) et strategies/serializers.py (Strategy/Signal) existent avec fields='__all__' mais ne sont référencés par AUCUNE vue. Ne pas les reprendre tels quels : fields='__all__' exposerait model_path, entry_rules, exit_rules et parameters.
- FORMULAIRES MORTS : market/forms.py (AssetForm, TimeframeForm) et strategies/forms.py (StrategyForm) ne sont câblés à aucune vue. Aucun CRUD applicatif de stratégie ni d'actif n'existe : tout passe par l'admin Django.
- LOGIQUE MÉTIER ENFOUIE DANS LES VUES : (a) AssetQuickTradeView.post orchestre création de stratégie système, création de signal, activation de déploiement et exécution d'ordre directement dans la vue (≈180 lignes) ; (b) StrategyDetailView contient la formule du score de santé, les seuils d'interprétation et jusqu'aux classes CSS Tailwind ('text-emerald-400'). Tout cela doit remonter en services avant toute exposition API.
- ÉTAT MÉTIER IMPLICITE DANS DU JSON : le routage des signaux (routing, routing_error, strategy_deployment_id, execution_order_id, auto_execution_error) est stocké dans le champ libre Signal.model_output, mélangé aux probabilités du modèle. Ces informations doivent devenir des champs explicites pour être consommables par React/Flutter.
- FUITE INTER-TENANT POTENTIELLE : StrategyRun est filtré uniquement sur les stratégies visible_to(user). Pour une stratégie système partagée, un utilisateur voit donc les runs déclenchés par les déploiements d'AUTRES utilisateurs, et input_snapshot y expose deployment_id, portfolio_id et broker_account_id. Même asymétrie pour StrategyPerformanceSnapshot (aucun cloisonnement).
- EFFETS DE BORD EN CASCADE NON DOCUMENTÉS CÔTÉ API : toggle-active met en pause les déploiements ACTIVE ; toggle-autonomous coupe auto_execute partout ; switch-status met en pause les déploiements de mode incompatible ; activate met en pause les autres déploiements actifs du couple (stratégie, utilisateur). Ces cascades sont des invariants de sécurité à préserver et à remonter explicitement dans les réponses API.
- DURÉE DERIV NON MISE À JOUR : AssetQuickTradeView écrit deriv_duration/deriv_duration_unit dans strategy.parameters uniquement via les defaults d'un get_or_create. Les appels suivants avec une durée différente ne mettent pas à jour la stratégie. La durée effectivement appliquée voyage dans order.metadata (lu par infrastructure/broker_clients/deriv_client.py) — ne jamais basculer la lecture sur strategy.parameters.
- TÂCHES NON PLANIFIÉES : sync_binance_long_klines, sync_deriv_long_candles et compute_market_features_long_task sont implémentées mais absentes de CELERY_BEAT_SCHEDULE. Les timeframes longs (4h, 1d, 1w, 1M) ne sont donc alimentés que par la commande bootstrap_market_data, exécutée manuellement.
- BROKER SYSTÈME POUR L'IMPORT DERIV : DerivCandleImporter._resolve_deriv_broker prend le premier BrokerAccount DERIV actif de la base (trié par -is_default), indépendamment de tout utilisateur. Les credentials d'un utilisateur alimentent donc les bougies de toute la plateforme — à clarifier (compte technique dédié) avant mise à l'échelle multi-tenant.
- FILTRE TIMEFRAME SILENCIEUX : CandleLiveFeedView n'applique aucun filtre de timeframe quand le paramètre est absent ou inconnu, et renvoie alors des bougies de granularités mélangées. Comportement piège à corriger explicitement dans l'API cible.
- PERFORMANCE : FeatureComputationService.compute_for_asset_timeframe boucle de 20 à N en recalculant tous les indicateurs sur chaque préfixe, et _macd recalcule lui-même EMA12/EMA26 sur chaque sous-préfixe — complexité cubique de fait, exécutée toutes les 5 minutes sur tous les actifs actifs × 3 timeframes. market_assets_api exécute aussi une requête de dernier close par actif (jusqu'à 100 requêtes). À optimiser avant de brancher des clients mobiles.
- FORMATS LOCALISÉS CÔTÉ SERVEUR : les endpoints JSON existants renvoient des dates déjà formatées en français ('d/m/Y H:i', 'd/m H:i') et des nombres en chaîne. Les clients React/Flutter attendent de l'ISO-8601 et des types numériques — rupture de contrat à prévoir et à gérer dans la matrice de non-régression.
- AUCUN DÉCLENCHEMENT MANUEL DE RUN : il n'existe ni vue ni endpoint pour exécuter une stratégie à la demande (« tester maintenant »). Seuls Celery beat et la commande run_strategies le permettent. Si la refonte l'introduit, elle doit passer par StrategyRunnerService.run_one et non par un nouveau chemin.

</details>

---

### portfolio

`28 fonctionnalités` — API : **5 prêtes, 8 partielles, 15 à exposer**

**Modèles** : `Portfolio`, `CashLedgerEntry`, `Position`, `PortfolioSnapshot`, `PortfolioAllocation`, `PositionCorrelation`, `Trade`, `Transfer`

**Tâches Celery** : `portfolio.tasks.update_marks_task (beat: toutes les 15s)`, `portfolio.tasks.broadcast_open_positions_task (beat: toutes les 30s)`

**Canaux WebSocket** : `ws/portfolio/<portfolio_id>/ -> PortfolioConsumer, groupe `portfolio_{id}``, `event `portfolio.update` (payloads kind=metrics_refresh | snapshot_created | positions_snapshot)`, `event `position.update` (payload {position: {...}})`, `event `connection.established` (envoyé à l'accept)`, `groupe `user_dashboard_{user_id}` -> event `dashboard.update` (payload kind=portfolio_metrics), émis par PortfolioService.refresh_portfolio_metrics`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Liste des portefeuilles + résumé** | 🟡 | WEB/MOBILE |  | Le bloc `summary` (count / active_count / default / total_equity) n'existe pas en API: il faut un endpoint d'agrégation (ou le dériver côté client). Pas de pagination/filtre/recherche déclarés sur le ViewSet. |
| **Détail portefeuille (page agrégée)** | 🟡 | WEB/MOBILE | ⚡ | Pas d'endpoint 'détail agrégé': il faut composer portfolios/{id}, snapshots?portfolio=, positions?portfolio=, portfolios/{id}/exposures, correlations. Les séries de graphiques (labels formatés, daily/monthly returns) sont construites en JSON côté template. Aucun filtre serveur par portfolio sur /positions/, /snapshots/, /ledger/ (tout est renvoyé pour l'utilisateur). |
| **Création / modification / suppression de portefeuille** | 🟡 | WEB/MOBILE |  | starting_balance est read_only dans PortfolioSerializer alors que le formulaire Django le pose à la création -> un client React/Flutter ne peut pas créer un portefeuille avec son solde initial. Champ `notes` exposé en API mais absent du template. Pas d'écran de confirmation de suppression ni de règle de blocage exposée. |
| **Définir le portefeuille par défaut** | ✅ | WEB/MOBILE |  | — |
| **Recalcul de l'état de trésorerie (recompute_cash_state)** | ❌ | — |  | Aucun endpoint dédié; c'est un invariant de service qui doit rester en backend et ne jamais être réimplémenté côté client. |
| **Rafraîchissement des métriques portefeuille** | ✅ | WEB/MOBILE | ⚡ | — |
| **Grand livre de trésorerie (CashLedgerEntry)** | 🟡 | WEB/MOBILE |  | Lecture seule, sans filtre par portfolio / entry_type / plage de dates, sans pagination déclarée, sans export CSV. Un relevé de compte utilisable côté React/Flutter demande ces filtres. |
| **Verrouillage de cash pour un ordre (ORDER_LOCK)** | ❌ | — |  | Invariant backend pur, ne doit jamais être exposé ni rejoué côté client. |
| **Libération de cash d'ordre (ORDER_RELEASE)** | ❌ | — |  | Invariant backend pur. |
| **Écriture des frais et du PnL réalisé au ledger** | ❌ | — |  | Invariant backend pur. |
| **Dépôt / retrait sur le portefeuille** | ❌ | — |  | Capacité métier existante mais non exposée. À arbitrer explicitement à la refonte: soit l'exposer, soit la supprimer au profit de TransferService — ne pas la laisser en zone grise. |
| **Transfert Wallet <-> Portfolio (double entrée)** | ❌ | WEB/MOBILE |  | Zéro API: pas de serializer ni de viewset pour Transfer. Il faut un POST /transfers/ portant `request_id` (clé d'idempotence fournie par le client — indispensable pour Flutter en réseau instable), `direction`, `portfolio_id`, `amount`, et la restitution des erreurs métier (solde insuffisant, portefeuille inactif) en codes/messages structurés plutôt qu'en `messages.error` Django. |
| **Historique des transferts Wallet <-> Portfolio** | ❌ | WEB/MOBILE |  | Aucun endpoint. Nécessite GET /transfers/ paginé avec filtres (statut, direction, portefeuille, période). |
| **Pont automatique Wallet -> Portfolio (signal)** | ❌ | — |  | Comportement serveur implicite, sans surface. À conserver tel quel; le client doit simplement rafraîchir le ledger après un dépôt. |
| **Positions — consultation** | 🟡 | WEB/MOBILE | ⚡ | ReadOnlyModelViewSet: aucune écriture possible en API alors que la vue Django offre create/update/delete. Pas de filtre par portfolio, statut ou symbole, pas de pagination déclarée. |
| **Positions — création / modification / suppression manuelles** | ❌ | WEB/MOBILE | ⚡ | Aucune écriture exposée en API. Il faut POST/PATCH/DELETE /positions/ avec la même règle de forçage de broker_account et le même refresh de métriques. Attention: le formulaire Django actuel est partiellement cassé (champ `symbol` requis par PositionForm mais absent du template) — la refonte doit décider de la saisie du symbole (libre ou dérivée de l'Asset). |
| **Mark-to-market temps réel des positions** | ❌ | WEB/MOBILE | ⚡ | Pas d'endpoint; c'est le WebSocket qui porte la donnée. Un client Flutter en arrière-plan / hors ligne aura besoin d'un endpoint de resynchronisation (snapshot des positions + marks) à la reconnexion. |
| **Broadcast périodique de l'état des positions (filet de rattrapage)** | ❌ | WEB/MOBILE | ⚡ | Le payload `positions_snapshot` est le contrat de resynchronisation du client; il doit être doublé d'un endpoint REST équivalent pour le démarrage à froid de l'app mobile. |
| **Canal WebSocket portefeuille** | 🟡 | WEB/MOBILE | ⚡ | Le canal existe mais l'authentification repose sur scope['user'] (session Django). Pour React/Flutter il faut une authentification WS par token (JWT) et une stratégie de reconnexion/backoff côté client. |
| **Snapshots de portefeuille** | 🟡 | WEB/MOBILE | ⚡ | Création et lecture OK, mais /snapshots/ n'offre ni filtre par portfolio ni plage de dates ni agrégation (daily/weekly) ni pagination — la courbe d'équité d'un portefeuille n'est pas requêtable efficacement. Aucune planification Celery du snapshot: seul un cron externe appelle la commande. |
| **Exposition par classe d'actifs** | ✅ | WEB/MOBILE |  | — |
| **Matrice de corrélation des positions** | ✅ | WEB/MOBILE |  | — |
| **Allocations cibles par actif** | 🟡 | WEB |  | Le CRUD API existe mais le ViewSet ne valide PAS que le portfolio ciblé appartient à l'utilisateur à la création (IsOwner n'agit qu'au niveau objet; PortfolioAllocationSerializer n'a pas de validate_portfolio, contrairement à PortfolioSerializer et PositionSerializer). Aucune UI. PortfolioAllocationForm existe mais n'est utilisé par aucune vue. |
| **Import des positions live depuis le broker** | ✅ | WEB/MOBILE | ⚡ | — |
| **Réconciliation automatique de la balance broker** | ❌ | — |  | Invariant backend pur. Au plus, exposer `last_reconciled_at` et l'historique des écritures BROKER_IMPORT en lecture. |
| **Trades (round-trips clos) et PnL réalisé** | ❌ | WEB/MOBILE |  | Lacune majeure: l'historique des trades clos — donc tout le journal de trading et les statistiques de performance (win rate, PnL par symbole, durée de détention via hold_time_seconds) — est totalement invisible côté client. Il faut un serializer + endpoint /trades/ en lecture, filtrable par portefeuille, symbole, période, avec agrégats. |
| **Métriques live recalculées sans écriture (PortfolioMetricsService)** | ❌ | — |  | Aucun endpoint. ATTENTION avant de l'exposer: sa formule de balance somme TOUT le ledger (y compris ORDER_LOCK/ORDER_RELEASE) alors que recompute_cash_state les exclut — les deux calculs divergent dès qu'un ordre est en vol. |
| **Administration Django du domaine** | ❌ | WEB |  | Back-office non couvert par l'API. À conserver en Django admin ou à remplacer par un back-office React distinct avec RBAC staff. |

<details><summary>Règles métier invariantes à préserver</summary>

**Liste des portefeuilles + résumé**
<br>_Liste des portefeuilles de l'utilisateur avec compteurs agrégés (total, actifs, portefeuille par défaut, equity totale) et tableau Nom/Broker/Balance/Equity/Devise/Statut._
<br>Points d'entrée : `backend/portfolio/views.py:PortfolioListView`, `backend/api/views/portfolio.py:PortfolioViewSet.get_queryset`, `backend/api/serializers/portfolio.py:PortfolioSerializer`

- Cloisonnement strict: queryset filtré sur user=request.user (vue) / IsOwner + filter(user=request.user) (API).
- Tri par name.
- `summary.total_equity` est calculé en Python dans la vue (somme des Portfolio.equity), pas en SQL — non exposé par l'API.

**Détail portefeuille (page agrégée)**
<br>_Page unique qui rafraîchit les métriques, affiche 6 KPI (balance, equity, PnL latent, PnL réalisé, drawdown, max DD), 3 graphiques (equity/balance/drawdown, returns daily/monthly, exposition par classe d'actifs), la table de corrélation et les positions ouvertes._
<br>Points d'entrée : `backend/portfolio/views.py:PortfolioDetailView.get_context_data`, `backend/templates/portfolio/portfolio_detail.html`

- Un simple GET déclenche des ÉCRITURES: refresh_portfolio_metrics (save Portfolio + toutes les Positions + 2 broadcasts WS) ET position_correlation_matrix (DELETE puis re-INSERT des PositionCorrelation) à chaque affichage.
- Fenêtre des snapshots: les 120 derniers par snapshot_time croissant, puis inversés pour l'affichage.
- Corrélations calculées en dur avec timeframe_code='1d' et lookback_bars=60 dans la vue (alors que l'API par défaut passe par CorrelationComputeSerializer).
- closed_positions (10 derniers), allocations et ledger_entries (20 derniers) sont bien calculés dans le contexte mais NE SONT PAS rendus par le template — fonctionnalité morte côté UI, mais la donnée existe.

**Création / modification / suppression de portefeuille**
<br>_CRUD portefeuille avec choix du broker account, devise de base, solde initial, drapeaux actif/défaut, description et notes._
<br>Points d'entrée : `backend/portfolio/views.py:PortfolioCreateView`, `backend/portfolio/views.py:PortfolioUpdateView`, `backend/portfolio/views.py:PortfolioDeleteView`, `backend/portfolio/forms.py:PortfolioForm`, `backend/api/views/portfolio.py:PortfolioViewSet.perform_create/perform_update`

- unique_together (user, name): un nom de portefeuille est unique par utilisateur.
- Portfolio.clean(): le broker_account doit appartenir au même user; un seul is_default=True par user; starting_balance >= 0.
- Portfolio.save(): à la création seulement, current_balance <- starting_balance, puis available_cash <- current_balance, equity <- current_balance, max_equity <- equity. full_clean() est appelé à CHAQUE save().
- Création/MAJ enchaînent systématiquement PortfolioService.refresh_portfolio_metrics (vue Django ET API).
- Le queryset du champ broker_account est restreint à request.user.broker_accounts (vue) et validé par PortfolioSerializer.validate_broker_account (API).
- Côté API, tous les champs monétaires y compris starting_balance sont read_only: on ne peut PAS créer un portefeuille avec un solde initial via l'API, contrairement au formulaire Django.
- La suppression est une CASCADE DB (positions, ledger, snapshots, allocations, corrélations) sans aucun garde-fou sur positions ouvertes / trades existants; Transfer protège par on_delete=PROTECT.

**Définir le portefeuille par défaut**
<br>_Marque un portefeuille comme défaut de l'utilisateur et démarque tous les autres._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioService.set_default_portfolio`, `backend/portfolio/views.py:PortfolioSetDefaultView`, `backend/api/views/portfolio.py:PortfolioViewSet.set_default`

- Atomique: UPDATE is_default=False sur tous les autres portefeuilles du user AVANT de poser is_default=True — sans cet ordre, Portfolio.clean() lèverait ValidationError sur l'unicité du défaut.
- Le portefeuille par défaut est utilisé comme cible implicite par le pont Wallet->Portfolio (wallet/signals.py: order_by('-is_default', '-created_at')) et comme tri dans l'écran de transfert.

**Recalcul de l'état de trésorerie (recompute_cash_state)**
<br>_Recalcule current_balance, available_cash et locked_cash à partir de starting_balance et du grand livre. Socle comptable de tout le domaine._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioService.recompute_cash_state`

- current_balance = starting_balance + Σ(amount des entrées de ledger HORS ORDER_LOCK/ORDER_RELEASE). Inclure les locks double-compterait le montant verrouillé (déjà soustrait via locked_cash) et casserait l'invariant current_balance = available_cash + locked_cash.
- locked_cash = abs(Σ(ORDER_LOCK + ORDER_RELEASE)) si cette somme est négative, sinon 0.
- available_cash = current_balance - locked_cash, borné à 0 (jamais négatif).
- Le débit réel du cash arrive au fill via TRADE_EXECUTION, jamais via le lock: lock/release sont des réservations, pas des mouvements.
- save() restreint à update_fields=[current_balance, available_cash, locked_cash, updated_at].

**Rafraîchissement des métriques portefeuille**
<br>_Recalcule mark-to-market des positions ouvertes, unrealized/realized PnL, margin_used, equity, max_equity, drawdown courant et max, puis broadcast WS._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioService.refresh_portfolio_metrics`

- Commence TOUJOURS par recompute_cash_state.
- Positions concernées: status in (OPEN, PARTIALLY_CLOSED).
- Branche Deriv: si broker_account.broker == 'DERIV', on NE recalcule PAS le PnL via price*quantity (faux pour une option binaire). On prend le stake (margin_used || notional_value || exposure_value || quantity) comme notional/exposure/margin et on conserve unrealized_pnl/pnl tels quels.
- equity = current_balance + Σ unrealized_pnl.
- realized_pnl du Portfolio = Σ(ledger PNL_REALIZED) + Σ(Position.realized_pnl des positions encore OPEN/PARTIALLY_CLOSED) — formule DIFFÉRENTE de PortfolioMetricsService (Σ Trade.realized_pnl).
- Garde-fou anti-corruption: si max_equity > current_balance * 10, max_equity est réinitialisé à current_balance (séquelle de métriques Deriv fantômes).
- max_equity est monotone croissant (jamais réduit sauf par le garde-fou ci-dessus); drawdown = (max_equity - equity)/max_equity*100 borné à >= 0; si max_drawdown historique > 100, il est réinitialisé sur le drawdown courant.
- Chaque position est traitée dans un try/except qui, en cas d'échec, retombe sur les valeurs déjà persistées — un calcul de position ne doit jamais faire échouer le refresh global.
- Deux broadcasts en fin de méthode: portfolio_{id} (kind=metrics_refresh) et user_dashboard_{user_id} (kind=portfolio_metrics).

**Grand livre de trésorerie (CashLedgerEntry)**
<br>_Journal append-only de tous les mouvements de cash du portefeuille, 9 types d'écriture, avec référence externe (reference_type/reference_id) et metadata JSON._
<br>Points d'entrée : `backend/portfolio/models.py:CashLedgerEntry`, `backend/portfolio/services.py:PortfolioAccountingService.add_ledger_entry`, `backend/api/views/portfolio.py:CashLedgerEntryViewSet`, `backend/api/serializers/portfolio.py:CashLedgerEntrySerializer`

- Types autorisés: DEPOSIT, WITHDRAWAL, ORDER_LOCK, ORDER_RELEASE, FEE, PNL_REALIZED, TRADE_EXECUTION, BROKER_IMPORT, MANUAL_ADJUSTMENT.
- Une écriture de montant 0 est INTERDITE (ValueError) — add_ledger_entry refuse amount == 0.
- Convention de signe stricte: sorties négatives (WITHDRAWAL, ORDER_LOCK, FEE, débit TRADE_EXECUTION), entrées positives.
- Tous les montants sont quantizés à 0.01 avec ROUND_HALF_UP.
- currency par défaut = portfolio.base_currency.
- Aucune mutation/suppression d'écriture: toute correction passe par une écriture compensatoire.
- L'idempotence des écritures est portée par les APPELANTS via (reference_type, reference_id) — add_ledger_entry n'applique aucune déduplication lui-même.

**Verrouillage de cash pour un ordre (ORDER_LOCK)**
<br>_Réserve le notionnel d'un ordre sur le cash disponible avant envoi au broker._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioAccountingService.lock_cash_for_order`, `backend/execution/services.py (lignes ~709 et ~1100)`

- SELECT FOR UPDATE sur la ligne Portfolio pour toute la transaction: sans ce verrou, deux workers concurrents lisent le même available_cash et approuvent deux débits -> solde négatif.
- Idempotence par (entry_type=ORDER_LOCK, reference_type, reference_id): si un lock existe déjà pour la même référence, on ne rejoue rien; si le montant diffère, on lève ValueError ('verrou de cash existe déjà avec un montant différent').
- Montant strictement positif obligatoire.
- Vérification available_cash >= amount APRÈS recompute_cash_state; sinon ValueError, qui est traduit en rejet d'ordre côté execution (mark_rejected + OrderRejected).
- Le lock n'est posé que pour order.mode == 'LIVE'.

**Libération de cash d'ordre (ORDER_RELEASE)**
<br>_Libère tout ou partie du cash réservé lors de l'annulation, du rejet, de l'échec, du fill ou de la réconciliation d'un ordre._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioAccountingService.release_cash_from_order`

- SELECT FOR UPDATE sur Portfolio.
- Calcule remaining_locked = abs(min(0, Σ ORDER_LOCK)) - Σ ORDER_RELEASE pour la référence; si <= 0, ne fait rien (sortie idempotente, pas d'erreur).
- La libération est PLAFONNÉE: release_amount = min(amount demandé, remaining_locked) — on ne peut jamais libérer plus que ce qui a été verrouillé.
- La metadata conserve requested_release_amount et remaining_locked_before pour l'audit.
- Au fill, le release précède toujours le débit réel TRADE_EXECUTION (ordre `unlock_before_consume` puis `cash_consumption` dans AccountingBridgeService.apply_fill_accounting).
- Les ordres reduce_only / closes_position ne libèrent PAS de cash (aucun lock n'avait été posé) — garde `is_reduce_only` répétée dans execution/tasks.py et execution/reconciliation.py.
- Un échec de libération est loggué (log.exception) mais ne doit pas empêcher le passage de l'ordre en REJECTED/FAILED.

**Écriture des frais et du PnL réalisé au ledger**
<br>_apply_fee (FEE, montant négatif) et apply_realized_pnl (PNL_REALIZED) écrivent au grand livre puis recalculent le cash._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioAccountingService.apply_fee`, `backend/portfolio/services.py:PortfolioAccountingService.apply_realized_pnl`

- apply_fee exige un montant strictement positif et l'inscrit en négatif.
- apply_realized_pnl avec amount == 0 est un no-op (retourne recompute_cash_state sans écrire).
- La clôture de position n'écrit PAS de PNL_REALIZED: une seule ligne TRADE_EXECUTION nette est inscrite (cf. execution/services_close.py), sinon double-comptage avec Trade.realized_pnl. Ne pas réactiver apply_realized_pnl dans ce chemin.

**Dépôt / retrait sur le portefeuille**
<br>_Services de dépôt et de retrait direct sur un portefeuille, avec contrôle du cash disponible pour le retrait._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioAccountingService.deposit`, `backend/portfolio/services.py:PortfolioAccountingService.withdraw`

- Montant strictement positif obligatoire (ValueError sinon).
- withdraw recompute_cash_state AVANT de contrôler available_cash >= amount, puis écrit WITHDRAWAL en négatif — le contrôle porte sur available_cash (hors cash verrouillé), pas sur current_balance.
- Les mouvements d'argent réels de l'utilisateur passent en pratique par TransferService (Wallet <-> Portfolio) et par le pont wallet/signals.py, pas par ces deux méthodes.

**Transfert Wallet <-> Portfolio (double entrée)**
<br>_Transfert atomique et idempotent entre le wallet plateforme et un portefeuille de trading, dans les deux sens, avec écran de saisie dédié._
<br>Points d'entrée : `backend/accounting/services.py:TransferService.transfer_wallet_to_portfolio`, `backend/accounting/services.py:TransferService.transfer_portfolio_to_wallet`, `backend/accounting/models.py:Transfer`, `backend/wallet/views.py:wallet_transfer_view`

- Idempotence par request_id unique: un rejeu avec le même request_id retourne le Transfer existant SANS rejouer aucune mutation. L'UI génère `ui:{user_pk}:{direction}:{uuid4[:16]}`.
- Invariant double entrée: Σ(variation wallet) + Σ(variation portfolio) == 0 pour un même Transfer.
- Wallet et Portfolio doivent appartenir au MÊME utilisateur (TransferError sinon).
- Sens wallet->portfolio: wallet et portfolio doivent être actifs; débit wallet via WalletLedgerService.debit avec external_event_id idempotent `transfer:{request_id}:wallet_debit`, puis crédit portfolio en DEPOSIT reference_type='WALLET_TRANSFER' reference_id=transfer.id, puis recompute_cash_state.
- Sens portfolio->wallet: recompute_cash_state d'abord, refus si available_cash < amount; puis WITHDRAWAL portfolio (négatif) PUIS credit wallet avec external_event_id `transfer:{request_id}:wallet_credit`.
- Le record Transfer est créé en PENDING AVANT le bloc atomique des mutations: si le bloc échoue, débit et crédit sont annulés ensemble mais le Transfer survit en FAILED avec error_message — la trace de l'échec ne doit jamais être perdue.
- InsufficientFundsError du wallet -> Transfer.status='FAILED' + TransferError('Solde wallet insuffisant').
- Montant strictement positif; request_id obligatoire; quantization 0.01 ROUND_HALF_UP.
- Les FK user/wallet/portfolio sont on_delete=PROTECT: un portefeuille ayant servi à un transfert ne peut pas être supprimé.

**Historique des transferts Wallet <-> Portfolio**
<br>_Liste paginée (20/page) des transferts de l'utilisateur, tous statuts confondus._
<br>Points d'entrée : `backend/wallet/views.py:transfer_history`, `backend/accounting/models.py:Transfer.as_dict`

- Filtré sur user=request.user, trié par -created_at, pagination Django Paginator de 20.
- Les statuts PENDING / COMPLETED / FAILED / REVERTED doivent rester visibles (un FAILED est une trace d'audit, pas un déchet à masquer).

**Pont automatique Wallet -> Portfolio (signal)**
<br>_Tout dépôt/retrait wallet passé en SUCCEEDED est reflété automatiquement dans le ledger du portefeuille par défaut de l'utilisateur._
<br>Points d'entrée : `backend/wallet/signals.py:sync_wallet_transaction_to_portfolio`

- Ne se déclenche que si status == 'SUCCEEDED' et tx_type in (DEPOSIT, WITHDRAWAL).
- Idempotence par existence d'une CashLedgerEntry avec reference_type='WALLET_TRANSACTION' et reference_id=str(transaction.id).
- Cible = premier Portfolio actif trié par ('-is_default', '-created_at'); si aucun portefeuille actif, on logge un warning et on ne fait RIEN (la transaction wallet ne doit pas échouer à cause de l'absence de portefeuille).
- Les retraits sont inscrits en montant négatif.
- Le signal est placé au niveau du modèle volontairement: le wallet est muté depuis plusieurs chemins (webhook provider, admin, tâche Celery) et le ledger portfolio doit rester synchronisé quel que soit le chemin.
- Tout le corps est encapsulé dans un try/except: un échec de synchronisation ne doit jamais faire échouer la WalletTransaction.

**Positions — consultation**
<br>_Lecture des positions (ouvertes, partiellement clôturées, clôturées) avec side, quantité, prix d'entrée/moyen/courant, SL/TP, levier, marge, notional, exposition, PnL latent et réalisé, source et statut de cost basis._
<br>Points d'entrée : `backend/portfolio/models.py:Position`, `backend/api/views/portfolio.py:PositionViewSet`, `backend/api/serializers/portfolio.py:PositionSerializer`

- Position.clean(): le broker_account de la position DOIT être celui du portefeuille; quantity >= 0 et quantity == 0 autorisé UNIQUEMENT si status == 'CLOSED'; entry_price et current_price >= 0; si status == 'CLOSED' sans closed_at, closed_at est posé automatiquement.
- Position.save(): average_entry_price <- entry_price si vide, puis full_clean() systématique.
- update_market_metrics(): si quantity<=0 ou price<=0 ou entry<=0, tout est mis à zéro; sinon notional = exposure = quantity*price, unrealized = (price-entry)*qty pour LONG, (entry-price)*qty pour SHORT, pnl = realized + unrealized, pnl_percent = unrealized / (entry*qty) * 100.
- Statuts: OPEN / PARTIALLY_CLOSED / CLOSED. Sources: MANUAL / IMPORTED / STRATEGY / AI_ASSISTED. Cost basis: KNOWN / ESTIMATED / UNKNOWN (une position importée sans coût connu doit rester marquée UNKNOWN/ESTIMATED).
- Cloisonnement: filter(portfolio__user=request.user); broker_account est read_only en API et toujours réaligné sur portfolio.broker_account dans create/update du serializer.

**Positions — création / modification / suppression manuelles**
<br>_Saisie manuelle d'une position dans un portefeuille, édition et suppression, depuis l'interface Django._
<br>Points d'entrée : `backend/portfolio/views.py:PositionCreateView`, `backend/portfolio/views.py:PositionUpdateView`, `backend/portfolio/views.py:PositionDeleteView`, `backend/portfolio/forms.py:PositionForm`

- Le portefeuille cible est résolu dans dispatch() avec filter(user=request.user); redirection vers portfolio-list s'il est introuvable.
- broker_account est TOUJOURS forcé à portfolio.broker_account (jamais saisi par l'utilisateur), en création comme en modification.
- Chaque opération (create/update/delete) est suivie de refresh_portfolio_metrics sur le portefeuille.
- La suppression est un hard delete de la Position; les Trade liés survivent (position FK on_delete=SET_NULL).

**Mark-to-market temps réel des positions**
<br>_Tâche Celery qui met à jour Position.current_price depuis le cache Redis mark:{symbol} toutes les 15 secondes, pousse chaque position modifiée en WebSocket et rafraîchit les métriques des portefeuilles touchés._
<br>Points d'entrée : `backend/portfolio/tasks.py:update_marks_task`

- Protégé par un verrou Redis single_run('lock:update_marks_task', ttl=25): si le verrou n'est pas acquis, la tâche sort avec {'skipped': True} — jamais d'exécution concurrente.
- Ne traite que les positions OPEN/PARTIALLY_CLOSED; ignore un mark absent, non décimal ou <= 0; ignore un mark identique au current_price (aucune écriture inutile).
- Écriture restreinte à update_fields=['current_price','updated_at'] — ne touche ni au PnL persisté ni au statut.
- Le PnL latent du payload WS est calculé à la volée ((mark-entry)*qty*sign) et quantizé à 0.01; il ne persiste rien.
- Un échec de broadcast est logué en warning et NE DOIT PAS interrompre la boucle ni la mise à jour des autres positions.
- Idem pour le refresh des métriques par portefeuille: chaque portefeuille est traité dans son propre try/except.

**Broadcast périodique de l'état des positions (filet de rattrapage)**
<br>_Toutes les 30 secondes, pousse un snapshot complet des positions ouvertes de chaque portefeuille actif pour rattraper un client qui aurait manqué un message live._
<br>Points d'entrée : `backend/portfolio/tasks.py:broadcast_open_positions_task`

- Verrou Redis single_run('lock:broadcast_open_positions_task', ttl=25).
- Ne parcourt que les Portfolio is_active=True et les positions OPEN/PARTIALLY_CLOSED.
- Aucune écriture DB: c'est un pur mécanisme de cohérence d'affichage.
- Un échec de broadcast sur un portefeuille est logué en warning et n'interrompt pas la boucle.

**Canal WebSocket portefeuille**
<br>_Connexion temps réel par portefeuille, avec contrôle d'accès, diffusant métriques, snapshots et mises à jour de positions._
<br>Points d'entrée : `backend/portfolio/consumers.py:PortfolioConsumer`, `backend/portfolio/routing.py`, `backend/core/realtime.py:RealtimeBroadcastService`

- Refus avec code 4001 si l'utilisateur n'est pas authentifié, 4003 si le portefeuille ne lui appartient pas (vérification DB Portfolio.objects.filter(id=..., user_id=...).exists()).
- Après accept, le serveur émet `connection.established` avec portfolio_id et nom du groupe.
- Le consumer est strictement descendant: receive() est un no-op, aucun message client n'est traité — aucune commande métier ne doit transiter par le WS.
- Désinscription du groupe à la déconnexion.
- Tous les payloads sortants portent un champ `version` (REALTIME_PROTOCOL_VERSION=1): les clients ignorent les versions supérieures à celle qu'ils connaissent, ce qui permet de faire évoluer le schéma sans casser les sessions ouvertes.
- Les Decimal/datetime/UUID sont normalisés en chaînes avant envoi.
- RealtimeBroadcastService.broadcast_after_commit existe pour les émissions depuis une transaction ouverte, afin de ne jamais publier un état qui sera rollbacké.

**Snapshots de portefeuille**
<br>_Photographie horodatée (balance, available/locked cash, equity, PnL latent et réalisé, marge, drawdown, rendements daily et monthly) utilisée pour les courbes d'équité et de performance._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioService.create_snapshot`, `backend/portfolio/models.py:PortfolioSnapshot`, `backend/portfolio/management/commands/create_portfolio_snapshots.py`, `backend/api/views/portfolio.py:PortfolioViewSet.snapshot`

- create_snapshot appelle TOUJOURS refresh_portfolio_metrics avant d'écrire — un snapshot ne doit jamais figer des métriques périmées.
- daily_return_percent est calculé par rapport au PREMIER snapshot du jour courant, monthly_return_percent par rapport au PREMIER snapshot du mois courant; si la référence est absente ou à 0, le rendement vaut 0.0 (pas de division par zéro).
- Un snapshot est immuable et purement additif (aucune MAJ/suppression dans le code).
- Broadcast `portfolio.update` kind='snapshot_created' après création.
- La commande de masse ne traite que les portefeuilles is_active=True et isole chaque portefeuille dans un try/except: l'échec d'un portefeuille ne doit pas arrêter la campagne.

**Exposition par classe d'actifs**
<br>_Répartition de l'exposition des positions ouvertes par asset_class, en valeur et en pourcentage, alimentant le donut du détail portefeuille._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioService.asset_class_exposure`

- Positions retenues: OPEN et PARTIALLY_CLOSED uniquement.
- Branche Deriv: pour un broker DERIV la valeur retenue est margin_used || notional_value || quantity (le stake), PAS exposure_value — sinon l'exposition d'une option binaire est fausse.
- Une position sans asset ou sans asset_class est classée 'UNKNOWN' (jamais exclue silencieusement).
- Si le total est 0, tous les pourcentages valent 0.0 (pas de division par zéro).
- Lecture pure, aucune écriture DB.
- Cette répartition est le pendant du plafond risk `max_asset_class_exposure_percent` (risk/services.py) — les deux doivent rester cohérents.

**Matrice de corrélation des positions**
<br>_Calcul des corrélations de Pearson entre les actifs des positions ouvertes sur une fenêtre de bougies, persistées en PositionCorrelation._
<br>Points d'entrée : `backend/portfolio/services.py:PortfolioService.position_correlation_matrix`, `backend/api/views/portfolio.py:PortfolioViewSet.compute_correlations`, `backend/api/serializers/actions.py:CorrelationComputeSerializer`

- Déduplication des actifs: une seule entrée par asset même si plusieurs positions le portent.
- Opération DESTRUCTIVE et idempotente par (portfolio, timeframe_code, lookback_bars): les lignes existantes pour ce triplet sont SUPPRIMÉES avant recalcul.
- Seules les paires d'actifs distincts sont calculées (itertools.combinations, 2 à 2).
- Les séries de clôtures sont lues en DESC puis remises en ordre chronologique; on tronque aux n = min(len(a), len(b)) dernières valeurs.
- Si n < 5, ou si la variance de l'une des séries est <= 0, la corrélation vaut 0.0 (jamais NaN, jamais d'exception).
- Corrélation de Pearson sur les PRIX de clôture, pas sur les rendements — comportement à préserver tel quel pour ne pas changer les valeurs affichées.
- Seuils d'affichage du template: > 0.7 = alerte (rouge), < -0.3 = favorable (vert).

**Allocations cibles par actif**
<br>_Définition d'un poids cible et d'un poids maximum par actif dans un portefeuille, activable/désactivable._
<br>Points d'entrée : `backend/portfolio/models.py:PortfolioAllocation`, `backend/api/views/portfolio.py:PortfolioAllocationViewSet`, `backend/portfolio/forms.py:PortfolioAllocationForm`

- unique_together (portfolio, asset): un seul enregistrement d'allocation par actif et par portefeuille.
- Valeurs par défaut: target_weight=0.0, max_weight=100.0, is_active=True.
- Tri par asset__symbol.
- Aucun service ne CONSOMME actuellement ces allocations (ni contrôle de dérive, ni rebalancement, ni blocage d'ordre) — c'est un référentiel déclaratif.

**Import des positions live depuis le broker**
<br>_Récupère les positions ouvertes et le cash distant via la passerelle broker, upsert les positions locales, clôture les positions disparues côté broker et aligne la trésorerie._
<br>Points d'entrée : `backend/portfolio/broker_import.py:BrokerImportService.import_live_positions`, `backend/portfolio/broker_import.py:BrokerImportService._upsert_position_from_payload`, `backend/api/views/portfolio.py:PortfolioViewSet.import_live`

- Garde API ABSENTE de la vue Django: l'endpoint API refuse en 409 si broker.mode != 'LIVE' ou not broker.is_active ou broker.status != 'ACTIVE'; la vue Django lance l'import sans ce contrôle. Cette garde doit être remontée dans le service lors de la refonte.
- Toute l'opération est dans une transaction atomique.
- Upsert par (portfolio, broker_position_id) quand le broker fournit un identifiant, sinon par (portfolio, symbol, status='OPEN', source='IMPORTED') — ce fallback est la clé de non-duplication.
- Les positions importées sont forcées en source='IMPORTED' et status='OPEN'; quantité en valeur absolue; side normalisé à LONG si invalide; cost_basis_status normalisé à UNKNOWN si inconnu.
- Le payload broker brut est conservé intégralement dans Position.metadata (traçabilité).
- Réconciliation descendante: toute position locale source=IMPORTED, status=OPEN, avec un broker_position_id ABSENT du flux distant est clôturée (status=CLOSED, closed_at=now). Une position importée sans broker_position_id n'est jamais clôturée automatiquement.
- Alignement cash: delta = cash distant - current_balance local; si delta != 0, une écriture BROKER_IMPORT (reference_type='BROKER_SYNC', reference_id=broker_account.id) est inscrite. Le broker est source de vérité, le portefeuille est miroir.
- Un Asset est créé à la volée si le symbole est inconnu (asset_class='CRYPTO' par défaut, is_active=True).
- Fin de parcours: refresh_portfolio_metrics puis last_reconciled_at = now.
- La vue Django enchaîne un create_snapshot après l'import; l'API aussi.
- Côté vue Django, toute exception est capturée et transformée en message d'erreur utilisateur — l'import ne doit pas renvoyer une 500.

**Réconciliation automatique de la balance broker**
<br>_Ajustement automatique du ledger portefeuille quand la balance distante diverge de la balance locale (flux Deriv et réconciliation d'exécution)._
<br>Points d'entrée : `backend/brokers/services/deriv_sync.py (~ligne 133)`, `backend/execution/reconciliation.py (~ligne 490)`, `backend/portfolio/services.py:PortfolioAccountingService.add_ledger_entry`

- RÈGLE CRITIQUE: on compare la balance distante à (current_balance + locked_cash), pas à current_balance seul. Pendant la fenêtre [lock_cash -> register_fill] le broker n'a pas encore débité la mise alors que le lock l'a déjà fait localement; sans cette correction un BROKER_IMPORT fantôme est inscrit puis doit être corrigé manuellement.
- Tolérance d'un centime: aucun ajustement si abs(delta) < 0.01 (évite le bruit d'arrondi).
- Idempotence Deriv par BrokerExternalRef (broker='DERIV', kind='TRANSACTION', external_id='balance_snapshot:{snapshot_id}') — un même snapshot de balance ne peut être appliqué deux fois.
- recompute_cash_state est appelé AVANT la comparaison.
- L'écriture porte entry_type='BROKER_IMPORT' avec reference_type='BROKER_BALANCE_SYNC' (Deriv) ou 'BROKER_BALANCE_RECONCILE' (execution), et conserve en metadata remote_balance / local_balance_before / local_locked_cash / adjusted_local_balance.
- Le broker reste source de vérité, le portefeuille est miroir.

**Trades (round-trips clos) et PnL réalisé**
<br>_Enregistrement immuable d'un aller-retour clos (entrée + sortie) avec quantité, prix moyens d'entrée et de sortie, PnL brut, frais, PnL net, cash investi et restitué, durée de détention._
<br>Points d'entrée : `backend/portfolio/models_trade.py:Trade`, `backend/execution/services_close.py:PositionCloseService.apply_closing_fill`, `backend/trading/services/deriv_settlement.py`

- Trade est la SEULE source de vérité du PnL réalisé: invariant déclaré Portfolio.realized_pnl == Σ Trade.realized_pnl pour ce portefeuille.
- realized_pnl est IMMUABLE une fois inscrit: toute correction passe par un nouveau Trade compensateur, jamais par une mise à jour.
- Formule canonique: LONG (exit - entry) * qty - fees; SHORT (entry - exit) * qty - fees. Pour Deriv (option binaire), le gross_pnl fourni par le broker (override_profit) remplace la formule — ne jamais recalculer un PnL prix*quantité sur Deriv.
- cash_returned = cash_invested + realized_pnl.
- Une fermeture partielle génère PLUSIEURS Trade pour une même Position (quantité décrémentée, status PARTIALLY_CLOSED tant que quantity > 0, CLOSED à 0).
- La clôture pose un select_for_update sur la Position et refuse une position dont le status n'est pas OPEN/PARTIALLY_CLOSED (PositionCloseError) — protection contre la double clôture concurrente.
- closing_qty = min(fill.quantity, position.quantity): on ne peut jamais clôturer plus que la quantité ouverte.
- UNE SEULE ligne TRADE_EXECUTION nette est inscrite au ledger pour la clôture; AUCUNE écriture PNL_REALIZED séparée, sinon double-comptage avec Trade.realized_pnl.
- Deriv: idempotence du crédit de règlement par recherche d'une CashLedgerEntry existante (reference_type='DERIV_CONTRACT', reference_id=contract.id, entry_type='TRADE_EXECUTION', amount>0). Comptabilité: ouverture -buy_price, clôture WON/SOLD +sell_price, LOST/EXPIRED aucune écriture (sell_price=0) -> solde net = profit.
- La notification de clôture (notifications.shortcuts.notify) est enveloppée dans un try/except: un échec de notification ne doit JAMAIS empêcher ou annuler la clôture du trade.
- broker_account est on_delete=PROTECT (un compte broker ayant des trades ne peut être supprimé); position est SET_NULL (la suppression d'une position ne détruit pas l'historique de PnL).

**Métriques live recalculées sans écriture (PortfolioMetricsService)**
<br>_Calcul en mémoire de balance, realized/unrealized PnL, equity, marge utilisée, marge libre, niveau de marge et nombre de positions ouvertes, à partir du ledger et de prix de marché fournis._
<br>Points d'entrée : `backend/portfolio/services_metrics.py:PortfolioMetricsService.compute_live`, `backend/portfolio/services_metrics.py:PortfolioMetrics`

- Règle déclarée: ces métriques ne sont JAMAIS persistées comme champs courants — seuls les PortfolioSnapshot horodatés le sont.
- realized_pnl = Σ Trade.realized_pnl (source de vérité unique), contrairement à refresh_portfolio_metrics.
- Cascade de repli du prix: mark_prices[symbol] -> position.current_price -> average_entry_price.
- used_margin = Σ (notional_value / leverage), levier <= 0 ramené à 1.
- free_margin = equity - used_margin; margin_level = equity / used_margin * 100, et vaut None (pas 0) s'il n'y a aucune marge utilisée — la distinction doit être conservée côté client.
- Aucune écriture DB.

**Administration Django du domaine**
<br>_Écrans d'administration pour Portfolio, Position, PortfolioSnapshot, PortfolioAllocation et PositionCorrelation, avec filtres et recherche._
<br>Points d'entrée : `backend/portfolio/admin.py`

- Filtres Portfolio: is_active, is_default, base_currency, broker_account__broker; recherche sur name, user__email, broker_account__name.
- Filtres Position: status, side, asset__asset_class.
- Aucun ModelAdmin pour Trade ni pour accounting.Transfer — ces deux modèles ne sont administrables par personne.
- Les écritures via l'admin passent par Model.save(), donc par full_clean() et les règles clean() — mais PAS par les services comptables: une modification manuelle de Portfolio ne recalcule ni le cash ni les métriques.

</details>

<details><summary>Pièges de migration repérés</summary>

- DOUBLE SOURCE DE VÉRITÉ DU PnL RÉALISÉ: PortfolioService.refresh_portfolio_metrics calcule realized_pnl = Σ(ledger PNL_REALIZED) + Σ(Position.realized_pnl des positions ENCORE OUVERTES), tandis que PortfolioMetricsService.compute_live et le docstring de Trade affirment realized_pnl = Σ Trade.realized_pnl. Les deux divergent structurellement (le premier ignore les positions totalement clôturées). Le chiffre affiché aujourd'hui vient de refresh_portfolio_metrics: toute harmonisation changera la valeur vue par l'utilisateur et doit être une décision explicite, pas un effet de bord de refonte.
- DEUX FORMULES DE BALANCE INCOMPATIBLES: recompute_cash_state EXCLUT ORDER_LOCK/ORDER_RELEASE de la somme du ledger (commentaire explicite sur le double-comptage), alors que PortfolioMetricsService.compute_live somme TOUT le ledger. Dès qu'un ordre est en vol, les deux donnent des balances différentes. Ne pas exposer compute_live sans aligner sa formule.
- VUE GET QUI MUTE LA BASE: PortfolioDetailView.get_context_data appelle refresh_portfolio_metrics (save du Portfolio + de toutes les positions + 2 broadcasts WS) ET position_correlation_matrix (DELETE puis re-INSERT des PositionCorrelation, avec N requêtes Candle). Un simple rafraîchissement de page écrit en base et pousse du temps réel. En API REST cette logique doit être scindée: GET pur côté lecture, POST explicites pour refresh et compute_correlations (ces endpoints existent déjà).
- FONCTIONNALITÉS CALCULÉES MAIS NON RENDUES: PortfolioDetailView construit closed_positions (10 derniers), allocations et ledger_entries (20 derniers) dans le contexte, mais le template portfolio_detail.html ne les affiche jamais. Il est impossible de savoir, depuis l'UI actuelle, si ces blocs étaient attendus. À arbitrer avec le métier plutôt qu'à reconduire à l'aveugle.
- FORMULAIRE DE POSITION CASSÉ: PositionForm déclare `symbol` (requis, pas de blank=True sur le modèle) parmi ses fields, mais position_form.html ne rend que asset, side, quantity, entry_price, current_price, stop_loss, take_profit, status, opened_at, closed_at — il n'y a ni boucle sur les champs ni rendu de symbol/asset_name/average_entry_price/leverage/margin_used/source/cost_basis_status. Le parcours 'Ajouter position' est donc vraisemblablement toujours invalide. Idem portfolio_form.html référence form.current_balance et form.equity qui n'existent pas dans PortfolioForm, et n'affiche pas form.notes. Ne pas transposer ces formulaires tels quels.
- GARDE MÉTIER UNIQUEMENT DANS LA COUCHE API: l'exigence 'broker LIVE actif et validé' pour l'import distant (409) n'existe QUE dans api/views/portfolio.py:import_live. La vue Django portfolio-import-live appelle le service sans contrôle. La règle doit descendre dans BrokerImportService, sinon la refonte peut la perdre ou la dupliquer.
- TRADE INVISIBLE: le modèle Trade — source de vérité du PnL réalisé — n'a ni serializer, ni viewset, ni template, ni ModelAdmin. Tout le journal de trading et les statistiques de performance sont absents des surfaces existantes; c'est le plus gros trou fonctionnel du domaine, et il n'apparaîtra dans aucune matrice établie à partir des seules URLs.
- ACCOUNTING SANS API: Transfer n'a aucun serializer ni endpoint. L'idempotence par request_id (indispensable pour un client Flutter sur réseau instable) est aujourd'hui générée côté serveur Django (`ui:{user}:{direction}:{uuid}`); en API, la clé doit être fournie PAR le client, ce qui change le contrat.
- PORTFOLIOALLOCATION: le ViewSet permet la création/modification mais le serializer n'a pas de validate_portfolio (contrairement à Portfolio et Position). IsOwner ne s'applique qu'à has_object_permission, pas à la création — un utilisateur peut potentiellement créer une allocation sur un portefeuille qui n'est pas le sien. À vérifier et corriger, pas à reproduire.
- BRANCHES DERIV DISPERSÉES: la logique 'si broker == DERIV' est dupliquée dans refresh_portfolio_metrics, asset_class_exposure, services_close (override_profit) et deriv_settlement. Elle neutralise le mark-to-market prix*quantité et substitue le stake. Toute centralisation doit préserver exactement ce comportement, sinon le PnL et l'exposition des options binaires deviennent faux.
- EXCEPTIONS AVALÉES DANS LA BOUCLE DE MÉTRIQUES: refresh_portfolio_metrics enveloppe le traitement de chaque position dans un try/except Exception nu qui retombe sur les valeurs persistées, sans log. Un bug de calcul sur une position est donc silencieux et se traduit par des métriques figées, pas par une erreur. Comportement à conserver (robustesse) mais à instrumenter.
- SUPPRESSION DE PORTEFEUILLE NON PROTÉGÉE: PortfolioDeleteView déclenche une CASCADE sur positions, ledger, snapshots, allocations et corrélations, sans aucune vérification de positions ouvertes ou de trades existants. Seul accounting.Transfer (PROTECT) bloque incidemment. Risque de destruction d'historique comptable.
- GARDE-FOUS HEURISTIQUES DE CORRECTION DE DONNÉES: refresh_portfolio_metrics réinitialise max_equity si max_equity > current_balance * 10, et max_drawdown si > 100%. Ce sont des rustines sur des données historiques corrompues, pas des règles métier. À documenter et à traiter par migration de données plutôt qu'à porter en l'état.
- COMPATIBILITÉ MORTE À NETTOYER: execution/services_close.py:_has_trade_execution_type() teste dynamiquement la présence de 'TRADE_EXECUTION' dans ENTRY_TYPE_CHOICES et retombe sur 'MANUAL_ADJUSTMENT'. Le choix existe depuis la migration 0005, donc la branche de repli est morte — mais d'anciennes écritures de clôture peuvent porter MANUAL_ADJUSTMENT en base et doivent rester interprétables.
- PORTFOLIOACCOUNTINGSERVICE.deposit/withdraw et PortfolioAllocationForm et PortfolioService... n'ont AUCUN appelant applicatif. Code vivant mais non exposé: décider explicitement de l'exposer ou de le retirer, et ne pas le compter comme fonctionnalité utilisateur existante.
- ALIAS D'URL LEGACY: /portofolio/ (faute de frappe) pointe sur le même urlconf que /portfolio/. Des liens externes ou des favoris peuvent en dépendre; prévoir une redirection 301 côté nouvelle plateforme.
- AUCUN FILTRE NI PAGINATION sur /positions/, /snapshots/, /ledger/, /correlations/: tous renvoient l'intégralité des objets de l'utilisateur, tous portefeuilles confondus. Inutilisable tel quel pour une app mobile; il faut ajouter filtres (portfolio, statut, symbole, période), tri et pagination — c'est un ajout, pas une régression.
- AUTHENTIFICATION WEBSOCKET PAR SESSION: PortfolioConsumer s'appuie sur scope['user'] (session Django). Pour React/Flutter il faut une authentification par token; la règle de cloisonnement (codes 4001/4003 et vérification DB d'appartenance) doit être préservée à l'identique.
- VERROUS REDIS ET IDEMPOTENCE DES TÂCHES: update_marks_task et broadcast_open_positions_task dépendent de core.redis_lock.single_run et retournent {'skipped': True} sans erreur si le verrou n'est pas acquis. Toute parallélisation ou tout changement de planification (15s / 30s) peut créer des écritures concurrentes sur Position.current_price.
- ORDRE DES OPÉRATIONS COMPTABLES AU FILL: AccountingBridgeService.apply_fill_accounting fait release(ORDER_RELEASE) PUIS débit réel(TRADE_EXECUTION) PUIS frais(FEE). Inverser cet ordre fausse transitoirement available_cash et peut faire échouer un contrôle de cash concurrent. L'ordre doit rester figé.

</details>

---

### execution-trading

`46 fonctionnalités` — API : **7 prêtes, 9 partielles, 30 à exposer**

**Modèles** : `execution.Order`, `execution.ExecutionFill`, `execution.ExecutionEvent`, `execution.BrokerSyncLog`, `execution.PositionProtection`, `execution.IdempotencyKey`, `trading.TradingIntent`, `trading.TradingIntentEvent`, `trading.Order (legacy)`, `trading.TradeExecution (legacy)`, `trading.DerivContract (legacy)`, `trading.TradeIdea`, `trading.TradeIdeaFeedback`, `trading.AgentRun`, `trading.MarketRegimeSnapshot`, `trading.TradeIdeaReview`, `trading.PortfolioAdvice`

**Tâches Celery** : `execution.tasks.submit_order_to_broker_task`, `execution.tasks.reconcile_portfolio_orders_task`, `execution.tasks.reconcile_all_active_portfolios_task`, `execution.tasks.recover_stale_execution_orders_task`, `execution.tasks.evaluate_position_protections_task`, `execution.tasks.refresh_daily_risk_states_task`, `execution.tasks.refresh_weekly_risk_states_task`, `execution.tasks.auto_enforce_kill_switch_task`, `execution.tasks_maintenance.cleanup_old_idempotency_keys_task`, `trading.tasks.sync_open_deriv_contracts_task`, `trading.tasks.sync_execution_deriv_contracts_task (définie mais NON planifiée dans CELERY_BEAT_SCHEDULE)`, `trading.tasks.scan_market_1m_task`, `trading.tasks.scan_market_5m_task`, `trading.tasks.expire_trade_ideas_task`, `trading.tasks.expire_old_trade_ideas`, `trading.tasks.learn_from_trade_ideas_task`, `trading.tasks.run_ai_market_cycle_1m`, `trading.tasks.run_ai_market_cycle_5m`, `trading.tasks.refresh_portfolio_advice`, `trading.tasks.run_hedge_fund_generation_cycle`, `trading.tasks.run_hedge_fund_execution_cycle`, `trading.tasks.run_learning_refresh_cycle`, `trading.tasks_ai.expire_market_opportunities_task`, `trading.tasks_ai.expire_trade_recommendations_task`, `trading.tasks_ai.generate_ai_recommendations_for_portfolio_task`, `trading.tasks_ai.generate_ai_recommendations_for_all_portfolios_task`

**Canaux WebSocket** : `ws/orders/ — execution.consumers.UserOrdersConsumer, groupe user_orders_{user_id}, events order.update / order.event`, `ws/dashboard/live/ — trading.consumers.DashboardConsumer, groupe user_dashboard_{user_id}, event dashboard.update`, `ws/ai/radar/ — trading.consumers_ai.AIRadarConsumer, groupe user_ai_{user_id}`, `execution.consumers.UserNotificationsConsumer (classe définie, groupe user_notifications_{user_id}, NON routée : /ws/notifications/ est servi par notifications.routing)`, `Topics outbox relayés vers ces groupes : execution.order.event.v1, execution.order.update.v1, execution.dashboard.update.v1, execution.portfolio.update.v1, execution.notification.update.v1`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Soumission d'ordre par intention (OrderIntent)** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint REST n'accepte un OrderIntent. L'API n'expose que create_manual (paramètres déjà sizés). Il faut un POST /api/v1/orders/intent/ acceptant OrderIntent + X-Idempotency-Key et retournant l'ordre créé. |
| **Création d'ordre canonique (create_order)** | ✅ | WEB/MOBILE | ⚡ | — |
| **Soumission effective au broker (worker)** | 🟡 | WEB/MOBILE | ⚡ | POST /api/v1/orders/{id}/submit/ appelle le chemin synchrone bloquant et ne gère ni les erreurs OrderRejected/ValueError (pas de mapping HTTP), ni l'idempotence. Un client mobile a besoin d'une réponse 202 + suivi par WebSocket plutôt que d'un appel broker bloquant. |
| **Annulation d'ordre** | ✅ | WEB/MOBILE | ⚡ | — |
| **Enregistrement idempotent des fills** | 🟡 | WEB/MOBILE | ⚡ | Les fills sont lisibles en API mais il n'existe aucun endpoint d'ingestion (webhook broker) ni de filtre par order_id documenté ; le client doit tout re-filtrer. |
| **Application d'un fill à la position (ouverture / renforcement)** | ❌ | WEB/MOBILE | ⚡ | Pas d'API propre à ce domaine (les positions sont exposées par l'app portfolio) ; aucun endpoint n'expose le lien ordre -> position créée. |
| **Clôture de position et création du Trade** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint REST ne permet de déclencher une clôture de position ni de lister les Trade du domaine exécution ; il faut un POST /api/v1/positions/{id}/close/ adossé à un ordre reduce_only. |
| **Comptabilité cash de l'exécution** | ❌ | WEB |  | Non exposé (le ledger est servi par /api/v1/ledger/ côté portfolio) ; aucun endpoint ne rapproche un ordre de ses écritures de cash. |
| **Journal d'événements d'exécution et diffusion temps réel** | ✅ | WEB/MOBILE | ⚡ | — |
| **Notifications de cycle de vie d'ordre** | 🟡 | WEB/MOBILE | ⚡ | Les notifications sont servies par l'app notifications (/api/notifications/) ; ce domaine n'expose pas le mapping notification -> ordre. Pas de push mobile branché sur ces événements. |
| **Protection de position (SL / TP / trailing) — configuration** | ❌ | WEB/MOBILE | ⚡ | Aucun serializer ni viewset : impossible de lire ou de modifier un SL/TP/trailing depuis un client. Il faut un CRUD /api/v1/position-protections/ (lecture + mise à jour des niveaux, activation du trailing). |
| **Protection de position — évaluation et déclenchement** | ❌ | WEB/MOBILE | ⚡ | Ni lecture d'état (ACTIVE/EXECUTING/trigger_reason/last_error) ni historique de déclenchement exposés. Une UI mobile de suivi de position a besoin de ces champs et d'un push sur déclenchement. |
| **Calcul trailing stop / break-even / paliers partiels** | ❌ | WEB |  | Pas d'endpoint de simulation ; un écran 'prévisualiser mon trailing' côté mobile nécessiterait un POST /api/v1/protections/simulate/. |
| **Réconciliation des ordres broker** | 🟡 | WEB |  | Seule la réconciliation des ORDRES est déclenchable par l'API ; positions, balance et full ne le sont pas. Le payload du BrokerSyncLog (unmatched_remote_orders / unmatched_local_orders) n'est pas structuré pour une UI. |
| **Réconciliation positions et balance broker** | ❌ | WEB |  | Aucun endpoint pour déclencher la réconciliation des positions ou de la balance depuis un client. |
| **Réconciliation complète d'un portefeuille** | ❌ | WEB |  | Non exposé. |
| **Reprise des ordres bloqués et gel automatique** | ❌ | WEB/MOBILE | ⚡ | Aucune visibilité client : un ordre en UNKNOWN_BROKER_STATE ou en manual_review n'est signalé que par notification. Il faut exposer ces états (et le compteur recovery_attempt) dans l'API ordres. |
| **Idempotence des commandes API** | ✅ | WEB/MOBILE |  | — |
| **Liste et détail des ordres (utilisateur)** | ✅ | WEB/MOBILE | ⚡ | — |
| **Filtres et statistiques d'en-tête des ordres** | 🟡 | WEB/MOBILE | ⚡ | L'API orders n'expose ni les filtres status/mode/symbol déclarés (pas de filterset_fields), ni un endpoint d'agrégats. Un client doit tout rapatrier pour compter. Prévoir ?status=&mode=&symbol= + /api/v1/orders/stats/. |
| **Flux temps réel des ordres (WebSocket)** | ✅ | WEB/MOBILE | ⚡ | — |
| **Routage et adaptateurs broker** | ❌ | WEB/MOBILE |  | Le mode effectif (PAPER simulé vs LIVE) n'est pas remonté explicitement dans la réponse d'ordre autrement que par le champ mode ; l'avertissement 'Deriv en PAPER' n'existe qu'en messages Django. |
| **Exécution manuelle d'un signal** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint REST 'exécuter un signal'. Il faut POST /api/v1/signals/{id}/execute/ (ou la variante OrderIntent) retournant l'ordre créé, avec idempotence. |
| **Exécution de signal par le service de compatibilité** | ❌ | WEB |  | Façade interne non exposée ; à ne pas reproduire côté client, le chemin cible est OrderIntent. |
| **Liste des signaux et polling JSON** | 🟡 | WEB/MOBILE |  | signal_list_api est un JsonResponse ad hoc (hors DRF, non versionné, non paginé, sans schéma OpenAPI). À migrer vers /api/v1/signals/ avec pagination et filtres. |
| **Génération automatique des opportunités (TradeIdea)** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint REST pour les TradeIdea (seules MarketOpportunity/TradeRecommendation de models_ai sont exposées). Il faut un /api/v1/trade-ideas/ complet (liste, filtres, détail). |
| **Liste et filtres des opportunités** | ❌ | WEB/MOBILE | ⚡ | Pas d'endpoint ; la liste n'existe que via le live feed JSON non paginé (50 éléments max). |
| **Live feed des opportunités (contexte marché et décision IA)** | 🟡 | WEB/MOBILE | ⚡ | C'est un JsonResponse ad hoc hors DRF (pas de pagination, pas de schéma OpenAPI, pas de versionnage). Toute la logique d'indicateurs et de décision IA est enfouie dans la vue : à extraire en service avant d'exposer un /api/v1/trade-ideas/live/. |
| **Détail d'une opportunité** | ❌ | WEB/MOBILE |  | Aucun endpoint. Nécessite GET /api/v1/trade-ideas/{id}/ incluant métriques, snapshot marché, broker_suggestions (preview de mise) et l'état kill switch des portefeuilles éligibles. |
| **Approbation / rejet manuel d'une opportunité** | ❌ | WEB/MOBILE |  | Pas d'endpoints. Prévoir POST /api/v1/trade-ideas/{id}/approve/ et /reject/. |
| **Exécution d'une opportunité (auto-trade) avec décharge de risque** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint. Il faut POST /api/v1/trade-ideas/{id}/execute/ avec broker_account_id, portfolio_id, amount, risk_override + motif, X-Idempotency-Key, et une réponse structurée (codes d'erreur HARD vs SOFT) au lieu des messages Django. |
| **Moteur d'exécution d'une opportunité (sizing + risque + ordre)** | ❌ | WEB/MOBILE | ⚡ | Service non exposé directement ; sa seule porte API est TradeRecommendation.execute. Il faut un endpoint d'exécution d'idée avec retour structuré (sizing, approval, risk_decision_id, broker_minimum_stake). |
| **Prévisualisation du minimum de mise par broker** | ❌ | WEB/MOBILE |  | Pas d'endpoint de preview. Indispensable pour le mobile : GET /api/v1/trade-ideas/{id}/preview/?broker_account_id=. |
| **Expiration automatique des opportunités** | ❌ | WEB/MOBILE |  | L'état expiré n'est pas poussé aux clients ; une UI mobile doit recalculer l'expiration à partir de expires_at. |
| **Feedback et apprentissage sur les opportunités exécutées** | ❌ | WEB |  | Le feedback (PnL, issue, latence) n'est exposé nulle part en API alors qu'il est la mesure de performance de l'IA côté utilisateur. |
| **Exécution autonome hedge fund** | ❌ | WEB/MOBILE | ⚡ | Aucun contrôle API : on ne peut ni activer/désactiver l'exécution autonome par portefeuille, ni consulter les rejets. C'est pourtant la fonctionnalité la plus sensible (argent réel sans action utilisateur). |
| **Intention de trading — création et formulaire** | ❌ | WEB/MOBILE |  | Aucun endpoint REST pour TradingIntent (liste, création, détail). Les validations du formulaire doivent être portées dans un serializer. |
| **Intention de trading — analyse IA et lancement** | ❌ | WEB/MOBILE |  | Aucun endpoint ; analyse et lancement ne sont accessibles qu'en POST Django avec redirection et messages. |
| **Intention de trading — monitoring des métriques** | ❌ | WEB |  | Non exposé ; de plus le recalcul est déclenché par une lecture de page, ce qui n'est pas transposable à une API idempotente (à déplacer en tâche). |
| **Contrats Deriv — consultation (historique)** | ❌ | WEB |  | Pas d'endpoint. À remplacer côté client par la lecture des ordres Deriv (execution.Order + références broker) plutôt que de reporter cette table historique. |
| **Règlement d'un contrat Deriv** | ❌ | WEB/MOBILE | ⚡ | Non exposé ; le résultat d'un contrat n'est visible qu'au travers du Trade et du ledger. |
| **Surveillance des contrats Deriv ouverts** | ❌ | WEB/MOBILE | ⚡ | Aucune visibilité du cycle de vie d'un contrat Deriv (ouvert / réglé) dans l'API ordres : un client voit FILLED alors que le contrat court encore. |
| **Recommandations IA — approbation, rejet et exécution** | ✅ | WEB/MOBILE | ⚡ | — |
| **Tableaux de bord hedge fund, risque et apprentissage** | 🟡 | WEB |  | risk_monitor_api et learning_monitor_api sont des JsonResponse hors DRF (pas de pagination, pas de schéma). De plus les agrégats d'idées du dashboard ne sont pas filtrés par utilisateur (voir risques) — à corriger avant exposition API. |
| **Données de marché de la page d'accueil** | 🟡 | WEB/MOBILE |  | JsonResponse hors DRF, non versionné, non documenté en OpenAPI. |
| **Administration des objets d'exécution** | ❌ | WEB |  | Outil interne ; aucune reprise client attendue, mais les capacités d'inspection (fills + events d'un ordre) doivent exister dans le back-office web. |

<details><summary>Règles métier invariantes à préserver</summary>

**Soumission d'ordre par intention (OrderIntent)**
<br>_Seule interface d'entrée canonique de l'OMS : une structure immuable OrderIntent est validée (risque, propriété, mode), un execution.Order est créé puis la soumission broker est déléguée à l'Outbox transactionnel._
<br>Points d'entrée : `backend/execution/intents.py:OrderIntent`, `backend/execution/services.py:ExecutionOrchestrator.submit`, `backend/execution/outbox.py:submit_order`

- is_trading_enabled() (kill switch global) est vérifié AVANT tout : sinon TradingDisabled, aucun ordre n'est créé.
- Un Order existant portant la même idempotency_key est renvoyé tel quel : submit() ne crée jamais de doublon.
- Le Portfolio est verrouillé (select_for_update) ; portfolio.user_id == intent.user_id et portfolio.broker_account_id == intent.broker_account_id sont obligatoires.
- intent.mode doit être identique à portfolio.broker_account.mode (pas de PAPER sur un compte LIVE et inversement).
- Si le RiskEngine lève une exception, l'ordre est REJETÉ (risk_engine_unavailable) : fail-closed strict, jamais de passage en force.
- Le signal non APPROVED/QUEUED est approuvé via SignalReviewService ; un signal n'appartenant pas à l'utilisateur fait échouer la soumission.
- Le lock cash (lock_cash_for_order) n'est posé que si order.mode == LIVE ; un cash insuffisant marque l'ordre REJECTED puis lève OrderRejected.
- L'appel broker n'a JAMAIS lieu dans cette transaction : l'event ORDER_SUBMIT_REQUESTED est enqueué dans l'outbox et traité après commit.
- OrderIntent.__post_init__ exige requested_quantity OU requested_stake_amount, side ∈ {BUY,SELL}, order_type et mode valides.

**Création d'ordre canonique (create_order)**
<br>_Crée un execution.Order après contrôles de propriété et de cohérence signal/opportunité/déploiement, journalise ORDER_CREATED et notifie l'utilisateur._
<br>Points d'entrée : `backend/execution/services.py:ExecutionOrchestrator.create_order`, `backend/api/views/execution.py:OrderViewSet.create_manual`

- portfolio.user_id == user.id, broker_account.user_id == user.id et portfolio.broker_account_id == broker_account.id : triple contrôle de cloisonnement.
- Si un Signal est fourni : il doit être executable_by(user), non expiré, en statut APPROVED ou QUEUED, de même side que l'ordre, de même symbole et de même asset que la stratégie du signal.
- trade_idea.user_id == user.id ; si signal ET trade_idea sont fournis et que trade_idea.signal_id est renseigné, il doit pointer sur ce même signal.
- StrategyDeploymentService.resolve_for_order est obligatoire : un ordre issu d'une stratégie sans déploiement actif est rejeté (OrderRejected).
- order.mode est TOUJOURS dérivé de broker_account.mode, jamais du payload client (champ read_only dans le serializer).
- Si closes_position est fourni, metadata reçoit reduce_only=True et closes_position_id : c'est ce flag qui autorisera la fermeture même sous kill switch.
- idempotency_key par défaut = {broker_id}-{portfolio_id}-{uuid4} ; champ unique en base.
- Un event ORDER_CREATED et une notification ORDER_CREATED sont émis systématiquement, plus un broadcast dashboard via outbox.

**Soumission effective au broker (worker)**
<br>_Revendication atomique de l'ordre, appel broker hors transaction, persistance du retour et des fills. C'est le seul chemin qui touche réellement le broker._
<br>Points d'entrée : `backend/execution/tasks.py:submit_order_to_broker_task`, `backend/execution/services.py:ExecutionOrchestrator.submit_order`, `backend/execution/adapters/factory.py:BrokerAdapterFactory.build`

- require_trading_enabled() / is_trading_enabled() revérifiés au moment de l'exécution, pas seulement à la création.
- Le kill switch du portefeuille bloque la soumission SAUF si l'ordre est reduce_only : on doit toujours pouvoir FERMER une position même portefeuille gelé. Cet ordre de test (reduce_only d'abord) est un invariant.
- Transition PENDING_SUBMIT -> SUBMITTING sous select_for_update : une seconde livraison outbox devient un noop (retour skipped), pas un double ordre broker.
- L'appel broker est fait HORS transaction DB (3 phases : lock+risk+cash, appel réseau, persistance) pour éviter le désync 'broker accepté / DB rollback'.
- Exception retryable (is_retryable_exception) => UNKNOWN_BROKER_STATE + demande de réconciliation ; le cash n'est PAS libéré (on ignore si le broker a accepté).
- Exception non retryable => libération du cash (LIVE et non reduce_only uniquement) puis FAILED.
- Si le broker a confirmé mais que la persistance échoue => UNKNOWN_BROKER_STATE en conservant broker_payload dans l'event : on ne perd jamais la confirmation.
- Ordre reduce_only : la position cible doit être OPEN/PARTIALLY_CLOSED, appartenir au même portfolio+broker, le side doit être l'inverse (SELL pour LONG) et approved_quantity <= position.quantity, sinon unsafe_reduce_only_order.
- Contrainte base uniq_active_close_order_position : un seul ordre de clôture actif par position.
- validate_strategy_deployment est rejoué avant envoi (un déploiement désactivé entre-temps bloque l'ordre).
- Le rejet kill-switch libère le cash avant de marquer REJECTED (_mark_rejected_and_release).

**Annulation d'ordre**
<br>_Annule un ordre encore ouvert chez le broker, libère le cash résiduel et rafraîchit les métriques du portefeuille._
<br>Points d'entrée : `backend/execution/services.py:ExecutionOrchestrator.cancel_order`, `backend/execution/views.py:CancelOrderView`, `backend/api/views/execution.py:OrderViewSet.cancel`

- Seul un ordre is_open (PENDING_SUBMIT, SUBMITTING, UNKNOWN_BROKER_STATE, SUBMITTED, PARTIALLY_FILLED) peut être annulé.
- Le cash libéré est approved_notional - filled_notional (jamais le notional complet si l'ordre est partiellement exécuté).
- mark_cancelled synchronise le Signal lié en CANCELLED (sauf s'il est déjà EXECUTED) et émet une notification ORDER_CANCELLED.
- L'appel broker est ici DANS la transaction (@transaction.atomic) — divergence assumée par rapport à submit_order.

**Enregistrement idempotent des fills**
<br>_Enregistre un fill broker, recalcule les agrégats de l'ordre, fait basculer le statut et déclenche soit l'ouverture de position soit la clôture._
<br>Points d'entrée : `backend/execution/services.py:FillProcessingService.register_fill`, `backend/execution/services.py:FillProcessingService._is_closing_fill`

- Idempotence : si un fill avec le même broker_fill_id existe déjà pour cet ordre, il est RENVOYÉ sans rien recréer (plus contrainte DB uniq_order_broker_fill_id). Sans cela les retries webhook/reconcile doublaient la comptabilité et créaient du faux PnL.
- L'ordre est verrouillé (select_for_update) pour sérialiser les écrivains concurrents.
- Les agrégats (filled_quantity, filled_notional, actual_fee, average_fill_price) sont RECALCULÉS à partir de l'ensemble des fills, jamais incrémentés.
- FILLED dès filled_quantity >= approved_quantity ; PARTIALLY_FILLED si > 0. FILLED synchronise le Signal en EXECUTED.
- Un fill est 'de clôture' si closes_position_id est posé, si metadata.reduce_only est True, ou s'il existe une position ouverte de side opposé sur le même symbole.
- Si la clôture (PositionCloseService) échoue, on NE retombe PAS sur apply_fill_to_position : cela ouvrirait une position dans le sens OPPOSÉ. On log et on laisse la réconciliation corriger. Invariant critique.
- apply_fill_accounting n'est appelé QUE pour les fills d'ouverture ; sur un fill de clôture c'est cash_returned qui fait l'écriture (sinon double comptage).
- Les broadcasts dashboard/portfolio passent par l'outbox avec des clés d'idempotence execution-fill:{id}:dashboard et :portfolio.

**Application d'un fill à la position (ouverture / renforcement)**
<br>_Crée ou renforce une Position à partir d'un fill d'ouverture, recalcule le prix moyen pondéré et synchronise la protection SL/TP._
<br>Points d'entrée : `backend/execution/services.py:PositionService.apply_fill_to_position`

- Le broker de l'ordre doit correspondre au broker du portefeuille, sinon ValueError (pas de mélange de comptes).
- BUY => position LONG, SELL => position SHORT ; on cherche une position OPEN/PARTIALLY_CLOSED du même symbole et side.
- Si la nouvelle quantité devient <= 0, la position est proprement CLOSED (quantity=0, closed_at) au lieu de rester OPEN avec une quantité invalide.
- Prix moyen = (ancien coût + nouveau coût) / nouvelle quantité, quantifié à 8 décimales.
- stop_loss / take_profit de l'ordre écrasent ceux de la position uniquement s'ils sont renseignés.
- Une PositionProtection est systématiquement synchronisée après création/renforcement (sync_from_position).
- La position créée porte metadata.origin_order_id (utilisé par le DerivExecutor de compatibilité) et cost_basis_status=KNOWN.

**Clôture de position et création du Trade**
<br>_Applique un fill de fermeture (totale ou partielle), calcule le PnL réalisé canonique, crée le Trade round-trip et écrit le retour de cash au ledger._
<br>Points d'entrée : `backend/execution/services_close.py:PositionCloseService.apply_closing_fill`, `backend/execution/services_close.py:PositionCloseService.apply_closing_fill_for_order`, `backend/execution/services_close.py:PositionCloseService.apply_deriv_contract_settlement`

- Position verrouillée en select_for_update ; statut OPEN ou PARTIALLY_CLOSED obligatoire sinon PositionCloseError.
- closing_qty = min(fill.quantity, position.quantity) : on ne sur-ferme jamais ; closing_qty <= 0 lève une erreur.
- Formule canonique : LONG (exit-entry)*qty - fees, SHORT (entry-exit)*qty - fees. Pour Deriv, override_profit du broker fait foi.
- cash_returned = cash_invested + realized_pnl ; UNE SEULE ligne ledger (TRADE_EXECUTION, fallback MANUAL_ADJUSTMENT si le type n'existe pas), AUCUNE entrée PNL_REALIZED séparée sous peine de double comptage avec Trade.realized_pnl.
- Fermeture totale => status CLOSED + PositionProtectionService.mark_completed ; sinon PARTIALLY_CLOSED.
- La notification POSITION_CLOSED est encapsulée dans try/except : un échec de notification ne doit JAMAIS empêcher la clôture comptable.
- Pour le règlement Deriv, la position cible est retrouvée d'abord par broker_order_id, sinon la plus ancienne position ouverte du même symbole/side.

**Comptabilité cash de l'exécution**
<br>_Pont entre l'OMS et la comptabilité du portefeuille : déverrouillage du cash réservé, débit réel du notional, frais, puis rafraîchissement des métriques._
<br>Points d'entrée : `backend/execution/services.py:AccountingBridgeService.apply_fill_accounting`

- Ordre strict des écritures : 1) release_cash_from_order (déverrouillage) 2) add_ledger_entry TRADE_EXECUTION de -fill_notional (débit réel) 3) apply_fee si fee > 0. Inverser cet ordre fausse le locked_cash.
- Chaque écriture porte reference_type=ORDER et reference_id=order.id : c'est la clé d'idempotence/traçabilité côté ledger.
- refresh_portfolio_metrics est appelé en fin de séquence pour que l'UI reste cohérente.

**Journal d'événements d'exécution et diffusion temps réel**
<br>_Chaque transition d'ordre écrit un ExecutionEvent et enqueue dans la même transaction la demande de diffusion temps réel (pattern outbox)._
<br>Points d'entrée : `backend/execution/services.py:ExecutionEventService.log`, `backend/execution/outbox.py:publish_order_update`, `backend/execution/event_topics.py`

- L'événement métier et sa demande de diffusion sont écrits dans LA MÊME transaction : pas d'event perdu ni de broadcast sans event.
- Le payload est systématiquement rendu JSON-safe (_json_safe gère Decimal, datetime, UUID, set, namedtuple) avant persistance.
- Clé d'idempotence de diffusion : execution-event:{event_id}:realtime.
- Un échec de livraison temps réel lève OutboxDeliveryError => l'event outbox sera rejoué, il n'est jamais silencieusement perdu.
- Types d'événements : ORDER_CREATED, ORDER_VALIDATED, ORDER_SUBMITTED, ORDER_ACKNOWLEDGED, ORDER_PARTIALLY_FILLED, ORDER_FILLED, ORDER_CANCELLED, ORDER_REJECTED, ORDER_FAILED, ORDER_STATE_UNKNOWN, RECONCILIATION_UPDATE.

**Notifications de cycle de vie d'ordre**
<br>_Notifications multicanales (centre de notifications + temps réel) à chaque étape : créé, soumis, exécuté, annulé, erreur, succès._
<br>Points d'entrée : `backend/execution/notifications.py:TradingNotificationService`

- En mode LIVE, le message est systématiquement préfixé '⚠ MODE LIVE — argent réel.' : distinction PAPER/LIVE obligatoire côté UI.
- Chaque notification enqueue un event outbox avec une clé d'idempotence order:{id}:realtime-{etat} : pas de double notification en cas de rejeu.
- notify_error / notify_success ne passent QUE par l'outbox (pas de notification persistée), ils ne doivent jamais faire échouer l'exécution.

**Protection de position (SL / TP / trailing) — configuration**
<br>_Crée ou met à jour une PositionProtection à partir de la position et des métadonnées de l'ordre, en déterminant le mode de protection supporté par le broker._
<br>Points d'entrée : `backend/execution/protection.py:PositionProtectionService.sync_from_position`, `backend/execution/protection.py:ProtectionCapabilityService.resolve`, `backend/execution/protection.py:PositionProtectionService._validate_levels`

- Capacité : PAPER => LOCAL_MONITORED ; MT5 sans trailing => NATIVE_BROKER (SL/TP posés à l'ouverture) ; MT5 avec trailing, BINANCE, DERIV => UNSUPPORTED.
- Mode UNSUPPORTED ou niveaux invalides => status DISABLED : on n'affiche jamais une protection comme active alors que rien ne la surveille.
- Validation des niveaux : LONG exige stop_loss < entry et take_profit > entry ; SHORT exige stop_loss > entry et take_profit < entry ; entry invalide => invalid_entry_price.
- Une protection en statut EXECUTING ou COMPLETED n'est jamais réécrite par une nouvelle synchronisation.
- Le flag trailing n'est modifié que si l'ordre porte explicitement trailing_stop_enabled/trailing_enabled, sinon on conserve la valeur existante.
- Relation OneToOne avec la Position : une seule protection par position.

**Protection de position — évaluation et déclenchement**
<br>_Boucle de surveillance (5 s) qui compare le prix courant aux niveaux, ajuste le trailing stop et crée l'ordre de clôture reduce_only quand un seuil est touché._
<br>Points d'entrée : `backend/execution/protection.py:PositionProtectionService.evaluate`, `backend/execution/protection.py:PositionProtectionService.evaluate_active`, `backend/execution/protection.py:PositionProtectionService._create_close_order`

- Si la position n'est plus OPEN/PARTIALLY_CLOSED, la protection est marquée COMPLETED (pas de déclenchement orphelin).
- Seules les protections ACTIVE et en mode LOCAL_MONITORED sont évaluées ; les autres modes ne font que mettre à jour last_evaluated_at.
- Prix absent OU plus vieux que POSITION_PROTECTION_MAX_PRICE_AGE_SECONDS (défaut 45 s) => skip avec last_error=stale_or_missing_market_price. On ne ferme JAMAIS une position sur un prix mort. Invariant critique.
- Le trailing ne peut que RESSERRER le stop (_is_tighter_stop) : jamais l'éloigner du prix.
- Déclencheur : LONG stop si prix <= SL, TP si prix >= TP ; SHORT l'inverse.
- Si un ordre de clôture actif existe déjà sur la position, on passe en EXECUTING et on le RÉUTILISE : jamais deux ordres de fermeture.
- L'ordre de clôture utilise l'idempotency_key déterministe position-protection:{id}:close et metadata reduce_only=True + protection_trigger.
- La boucle globale est protégée par un verrou Redis single_run('lock:evaluate_position_protections', ttl=4) : pas de double passe concurrente.
- Une exception sur une protection n'interrompt pas le lot (compteur errors), batch limité à 500, trié par last_evaluated_at (le plus ancien d'abord).
- mark_execution_failed / mark_execution_unknown n'écrasent jamais une protection déjà COMPLETED.

**Calcul trailing stop / break-even / paliers partiels**
<br>_Service pur calculant un nouveau stop (trailing % ou multiple d'ATR), le passage à break-even après N R et un ratio de clôture partielle à 1R/2R/3R._
<br>Points d'entrée : `backend/execution/trailing.py:TrailingStopService.compute`

- Si un ATR est fourni, la distance de trail = atr * atr_multiplier (défaut 2.0) ; sinon price * trail_percent (défaut 1.5 %).
- Break-even déclenché quand r_multiple >= break_even_after_r (défaut 1.0) et que le stop est encore défavorable : le trade ne peut plus devenir perdant.
- Paliers de clôture partielle : 1R => 0.33, 2R => 0.66, 3R => 1.0.
- Le service est PUR : il calcule mais n'applique rien au broker ; seul l'appelant décide. À préserver pour la testabilité.
- Entrées invalides (entry <= 0, price <= 0, side inconnu) renvoient l'état inchangé avec reason=invalid_inputs.

**Réconciliation des ordres broker**
<br>_Compare les ordres ouverts du broker avec les ordres locaux, applique les statuts distants, crée les fills manquants et trace tout dans un BrokerSyncLog._
<br>Points d'entrée : `backend/execution/reconciliation.py:BrokerReconciliationService.reconcile_orders`, `backend/execution/reconciliation.py:BrokerReconciliationService._sync_remote_fills`, `backend/execution/reconciliation.py:BrokerReconciliationService._apply_remote_order_state`

- Matching local : broker_order_id puis broker_client_order_id, toujours restreint au portefeuille.
- Mapping de statuts distants normalisé (NEW/OPEN/PLACED->SUBMITTED, CANCELED->CANCELLED, CLOSED/DONE->FILLED, défaut SUBMITTED).
- Déduplication des fills : par broker_fill_id si présent, sinon par empreinte quantity|price|fill_time. Sans cela chaque passe recréait des fills (Binance).
- Les fills marqués metadata.reconciliation_cumulative sont convertis en DELTA (quantité cumulée - filled_quantity) ; un delta <= 0 est ignoré.
- Libération du cash résiduel sur statut terminal uniquement si mode LIVE, ordre non reduce_only et remaining_notional > 0.
- Les ordres locaux SUBMITTING/UNKNOWN_BROKER_STATE/SUBMITTED/PARTIALLY_FILLED non vus dans la liste distante sont re-interrogés un par un (fetch_order) ; ceux introuvables sont listés comme unmatched_local_orders.
- Un ExecutionEvent RECONCILIATION_UPDATE est écrit à chaque passe.
- reconcile_portfolio_orders_task ignore les portefeuilles PAPER (skipped / paper_portfolio).
- Un échec de réconciliation notifie l'utilisateur (BROKER_RECONCILIATION_FAILED) avec dedupe_key par portefeuille.

**Réconciliation positions et balance broker**
<br>_Importe les positions live du broker et aligne le cash local sur la balance distante via une écriture d'ajustement._
<br>Points d'entrée : `backend/execution/reconciliation.py:BrokerReconciliationService.reconcile_positions`, `backend/execution/reconciliation.py:BrokerReconciliationService.reconcile_balance`

- Le cash local est d'abord RECALCULÉ depuis le ledger (recompute_cash_state) : le ledger est la source de vérité, pas le champ dénormalisé.
- La comparaison se fait sur (current_balance + locked_cash) : sans réintégrer le cash verrouillé, les ordres en vol génèrent un ajustement fantôme. Invariant.
- Un ajustement BROKER_IMPORT n'est écrit que si |delta| >= 0.01 ; un échec d'ajustement est tracé dans le payload mais ne fait pas échouer la réconciliation.
- La devise de référence est broker_account.deriv_currency, sinon portfolio.base_currency, sinon USD ; à défaut, la première balance retournée.
- reconcile_positions délègue à BrokerImportService.import_live_positions puis rafraîchit les métriques.

**Réconciliation complète d'un portefeuille**
<br>_Enchaîne ordres, positions et balance sous verrou Redis, puis crée un snapshot du portefeuille._
<br>Points d'entrée : `backend/execution/reconciliation.py:BrokerReconciliationService.reconcile_full`

- Verrou Redis reconcile_full:portfolio:{id} (timeout 300 s) : deux passes concurrentes créeraient des fills en double. Si le verrou n'est pas obtenu, la fonction retourne None sans erreur.
- Chaque sous-étape a sa PROPRE transaction : un échec de la réconciliation de balance ne doit jamais annuler des fills déjà appliqués. Invariant explicitement documenté dans le code.
- Le BrokerSyncLog parent passe en FAILED dès qu'une sous-étape échoue, mais les autres étapes sont quand même exécutées (pas d'arrêt au premier échec).
- Un snapshot de portefeuille est créé en fin de passe.

**Reprise des ordres bloqués et gel automatique**
<br>_Balaie périodiquement les ordres figés en PENDING_SUBMIT / SUBMITTING / UNKNOWN_BROKER_STATE et les répare sans jamais rejouer une mutation LIVE._
<br>Points d'entrée : `backend/execution/tasks.py:recover_stale_execution_orders_task`

- Règle cardinale : ne JAMAIS rejouer une mutation LIVE. Seul le PAPER est resoumis automatiquement.
- PENDING_SUBMIT sans event outbox ORDER_SUBMIT_REQUESTED => marqué manual_review_reason=pending_without_submit_event, pas de resoumission (on ignore si le broker a déjà reçu quelque chose).
- PENDING_SUBMIT avec event existant => réenqueue avec idempotency_key order:{id}:recovery-submit:{tentative}.
- Ordre PAPER bloqué => repassé en PENDING_SUBMIT avec paper_replay_after_worker_loss=True puis réenqueué.
- Ordre LIVE en SUBMITTING => UNKNOWN_BROKER_STATE (worker perdu pendant la soumission).
- Ordre LIVE en UNKNOWN_BROKER_STATE => demande de réconciliation du portefeuille ; si l'état dure plus de EXECUTION_UNKNOWN_ALERT_SECONDS (défaut 300 s), notification BROKER_ERROR + déclenchement du kill switch BROKER_STATE_UNKNOWN sur le portefeuille.
- Chaque ordre est traité sous select_for_update avec re-vérification de updated_at (évite de traiter deux fois le même ordre).
- Compteur recovery_attempt incrémenté dans metadata et intégré aux clés d'idempotence.

**Idempotence des commandes API**
<br>_Mécanisme de clé d'idempotence par utilisateur et par endpoint, avec rejeu de la réponse mémorisée et purge automatique._
<br>Points d'entrée : `backend/execution/idempotency.py:IdempotencyService`, `backend/execution/models_idempotency.py:IdempotencyKey`, `backend/api/views/execution.py:OrderViewSet.create_manual`

- Le header X-Idempotency-Key est OBLIGATOIRE sur create_manual : absence => 400.
- Même clé + payload différent (hash SHA-256 du JSON trié) => 409 CONFLICT. Protection contre la réutilisation accidentelle d'une clé.
- Un rejeu renvoie response_payload avec le status_code mémorisé (y compris les erreurs 4xx : un échec est aussi idempotent).
- Unicité en base sur (user, endpoint, key) : le cloisonnement inter-utilisateurs est garanti au niveau du schéma (migration 0006_scope_idempotency_keys).
- Clé vide ou > 120 caractères => ValueError.
- Course d'insertion gérée par IntegrityError puis relecture.
- Purge des clés de plus de 7 jours par tâche de maintenance.

**Liste et détail des ordres (utilisateur)**
<br>_Deux listes Django coexistent (execution:order_list et trading:order-list) plus l'API REST ; le détail affiche fills, événements et références broker externes._
<br>Points d'entrée : `backend/execution/views.py:OrderListView`, `backend/execution/views.py:OrderDetailView`, `backend/trading/views.py:OrderListView`, `backend/trading/views.py:OrderDetailView`, `backend/api/views/execution.py:OrderViewSet`

- Toutes les requêtes sont filtrées sur user=request.user (cloisonnement strict, aucun accès croisé).
- trading:order-list interroge execution.Order : trading.Order est orphelin et ne doit plus être lu (source de vérité unique).
- La vue de détail trading charge BrokerExternalRef dans un try/except et force l'évaluation du queryset pour qu'une table manquante dégrade la page au lieu de la casser (broker_refs_error).
- L'API est en lecture seule (ReadOnlyModelViewSet) + actions POST explicites : aucune écriture directe de champ d'ordre.
- Les champs mode, status, filled_*, broker_order_id, idempotency_key, horodatages sont read_only dans le serializer.
- Le serializer valide que portfolio et broker_account appartiennent au requêteur et sont rattachés l'un à l'autre.

**Filtres et statistiques d'en-tête des ordres**
<br>_Filtrage par statut, mode et symbole avec compteurs total / exécutés / ouverts / échoués au-dessus de la liste._
<br>Points d'entrée : `backend/trading/views.py:OrderListView.get_queryset`, `backend/trading/views.py:OrderListView.get_context_data`

- Filtre symbole en icontains ; filtres status et mode en égalité stricte.
- Les compteurs sont calculés sur le queryset COMPLET de l'utilisateur, pas sur la page filtrée.
- Groupes de statuts : ouverts = PENDING_SUBMIT/SUBMITTED/PARTIALLY_FILLED ; échoués = REJECTED/FAILED/CANCELLED/EXPIRED (UNKNOWN_BROKER_STATE et SUBMITTING ne sont comptés nulle part).
- Pagination 30 (trading) / 50 (execution).

**Flux temps réel des ordres (WebSocket)**
<br>_Canal par utilisateur poussant les mises à jour d'ordres et d'événements d'exécution, avec ping/pong et résilience Redis._
<br>Points d'entrée : `backend/execution/consumers.py:BaseUserStreamConsumer`, `backend/execution/consumers.py:UserOrdersConsumer`, `backend/execution/routing.py`

- Connexion refusée (code 4001) pour un utilisateur anonyme ; le groupe est strictement nominatif user_orders_{user_id}.
- accept() est fait AVANT group_add : si Redis est indisponible, la connexion reste vivante en mode isolé au lieu de provoquer une boucle de reconnexion client.
- Un échec d'envoi (broadcast corrompu, payload trop gros) est loggé mais ne ferme JAMAIS la socket.
- Protocole entrant minimal : action=ping => pong ; toute autre action => ack. Les frames binaires sont refusées.
- Sérialisation défensive (default=str) pour Decimal/datetime/UUID.

**Routage et adaptateurs broker**
<br>_Fabrique qui choisit l'adaptateur selon le mode et le broker : simulation locale en PAPER, passerelle réelle en LIVE (Deriv, Binance, MT5)._
<br>Points d'entrée : `backend/execution/adapters/factory.py:BrokerAdapterFactory.build`, `backend/execution/adapters/paper.py:PaperBrokerAdapter`, `backend/execution/adapters/live_deriv.py:LiveDerivAdapter`, `backend/execution/adapters/live_binance.py:LiveBinanceAdapter`, `backend/execution/adapters/live_mt5.py:LiveMT5Adapter`

- mode == PAPER => PaperBrokerAdapter QUEL QUE SOIT le broker : l'ordre est simulé localement et n'atteint jamais le broker. Un compte Deriv avec token en PAPER déclenche un warning structuré explicite (erreur de configuration la plus fréquente).
- mode == LIVE => adaptateur correspondant ; un broker non supporté lève ValueError.
- PaperBrokerAdapter : pour Deriv, prix de fill = requested_stake_amount et quantité = 1 (convention contrat) ; sinon prix = requested_price/limit_price et notional = prix * quantité.
- Un prix de référence <= 0 en PAPER lève une erreur (pas de fill à prix nul).
- PaperBrokerAdapter.close_position vérifie le side réducteur et que la quantité ne dépasse pas la position.
- broker_order_id PAPER = PAPER-{order_id}, broker_fill_id = PAPER-FILL-{order_id} : identifiants déterministes donc idempotents.

**Exécution manuelle d'un signal**
<br>_Depuis la liste des signaux, l'utilisateur déclenche l'évaluation du risque puis la création et la soumission immédiate de l'ordre._
<br>Points d'entrée : `backend/trading/views.py:ExecuteSignalView`

- Le signal doit être executable_by(request.user).
- Si la stratégie est en statut LIVE, un StrategyDeployment actif est OBLIGATOIRE et c'est SON portefeuille qui est utilisé ; sinon on prend le portefeuille par défaut de l'utilisateur.
- Décision RiskEngine == REJECT => le signal est rejeté via SignalReviewService.reject et aucun ordre n'est créé.
- Sinon le signal est approuvé (SignalReviewService.approve) AVANT la création de l'ordre : un ordre ne naît jamais d'un signal non approuvé.
- Les quantités/notional/stake proviennent exclusivement de la décision de risque, jamais d'une saisie utilisateur.
- source=AI_ASSISTED et metadata.source=signal_user_validation pour la traçabilité.
- submit_order est appelé en synchrone (chemin bloquant, contrairement au chemin outbox).

**Exécution de signal par le service de compatibilité**
<br>_Façade historique (ExecutionService / DerivExecutor) qui délègue entièrement à l'OMS canonique avec une clé d'idempotence déterministe._
<br>Points d'entrée : `backend/trading/services/execution/canonical_signal.py:CanonicalSignalExecutionService.execute`, `backend/trading/services/execution/base_execution.py:ExecutionService.execute_signal`, `backend/trading/services/execution/deriv_executor.py:DerivExecutor.execute_signal`

- Clé d'idempotence déterministe signal:{id}:portfolio:{id}:broker:{id} : rejouer la même exécution renvoie l'ordre existant, y compris après IntegrityError.
- Le signal HOLD ou une quantité <= 0 sont refusés.
- Scope vérifié : portefeuille du propriétaire du broker, broker rattaché au portefeuille, signal executable_by et en statut APPROVED/QUEUED.
- Sizing Deriv : quantity=1, stake=notional=approved_quantity (la quantité saisie EST la mise). Pour les autres brokers, notional = quantité * prix et un prix <= 0 est refusé.
- Les paramètres Deriv (duration, duration_unit, multiplier) sont lus dans strategy.parameters avec bornes et valeurs par défaut (5, 'm').
- Un TradingIntentEvent ORDER_CREATED est écrit si l'exécution provient d'une intention.
- DerivExecutor exige un broker DERIV et retrouve la position créée par metadata.origin_order_id.

**Liste des signaux et polling JSON**
<br>_Liste paginée des signaux visibles par l'utilisateur plus un endpoint JSON de rafraîchissement toutes les 5 s._
<br>Points d'entrée : `backend/trading/views.py:SignalListView`, `backend/trading/views.py:signal_list_api`

- Signal.objects.visible_to(user) : le cloisonnement passe par le manager de l'app strategies.
- L'endpoint JSON est limité à 50 lignes et accepte les filtres status, side, strategy_id.
- Le symbole affiché provient de strategy.asset.symbol, avec fallback '—' si la chaîne est incomplète.

**Génération automatique des opportunités (TradeIdea)**
<br>_Scan de marché périodique produisant des TradeIdea scorées, chacune adossée à un Signal, avec fenêtre d'expiration calculée._
<br>Points d'entrée : `backend/trading/services/trade_idea_generation.py:TradeIdeaGenerationService.generate`, `backend/trading/services/trade_idea_generation.py:TradeIdeaGenerationService.compute_levels`

- user non nul OBLIGATOIRE : les idées sont générées par utilisateur, jamais globalement (cloisonnement de données).
- Filtres de rejet successifs : overall_score < MIN_OVERALL_SCORE, direction HOLD, close <= 0 ou atr <= 0, niveaux calculés <= 0, expected_rr <= 0, bougie absente ou future, expiration déjà passée.
- expires_at = candle_time + timeframe_minutes * MAX_CANDLE_AGE_MULTIPLIER : une idée adossée à une bougie périmée n'est jamais créée.
- Déduplication : pas de nouvelle idée s'il en existe déjà une en statut NEW pour (user, scan_run, asset, timeframe, direction).
- Chaque TradeIdea crée son Signal (statut NEW, même expires_at, features_snapshot et model_output tracés) : l'idée sans signal ne sera pas exécutable.
- horizon_minutes = timeframe_minutes * 4.
- Une notification de synthèse AI_OPPORTUNITY_DETECTED est envoyée une fois par run avec la meilleure idée.

**Liste et filtres des opportunités**
<br>_Liste paginée des TradeIdea de l'utilisateur avec filtres statut, symbole et direction, synchronisés dans l'URL._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaListView`, `backend/trading/views_trade_ideas.py:TradeIdeaFilterMixin.get_filtered_queryset`

- Filtrage strict sur user=request.user.
- Tri par -created_at puis -overall_score ; pagination 30.
- Filtre symbole en icontains, statut et direction en égalité stricte.

**Live feed des opportunités (contexte marché et décision IA)**
<br>_Endpoint JSON rafraîchi toutes les 10 s qui enrichit chaque idée d'indicateurs techniques calculés à la volée, d'une décision IA, d'un résumé humain et d'un score de qualité d'exécution._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaLiveFeedView`, `backend/trading/views_trade_ideas.py:TradeIdeaLiveFeedView._get_market_context`, `backend/trading/views_trade_ideas.py:TradeIdeaLiveFeedView._compute_ai_decision`, `backend/trading/views_trade_ideas.py:TradeIdeaLiveFeedView._build_human_guidance`

- Décision IA : EXECUTE si overall >= 0.75 et confidence >= 0.70 et risk <= 0.45 ; PLAN si overall >= 0.60 et confidence >= 0.55 ; REJECT si risk >= 0.70 ; sinon WATCH.
- Indicateurs calculés sur les 80 dernières bougies : RSI 14, ATR 14, EMA 9/21 ; moins de 2 bougies => contexte 'UNKNOWN' (aucune donnée inventée).
- Volatilité : HIGH si atr/prix > 1.5 %, LOW si < 0.5 %, sinon MEDIUM. Liquidité déduite du ratio de volume (>=1.3 HIGH, >=0.8 MEDIUM, sinon LOW).
- Score de qualité d'exécution : base 50 + confidence*25 + min(rr,3)*6 - risk*20, ajusté par volatilité et liquidité, borné [0,100].
- Avertissements de risque cumulés : R/R < 1.5, confiance < 0.60, risk > 0.65, volatilité HIGH.
- Limité à 50 idées, triées -created_at puis -updated_at.
- La réponse porte detail_url pour la navigation.

**Détail d'une opportunité**
<br>_Page d'explication complète : métriques risque/récompense, snapshot marché recalculé, suggestions de mise par broker, bandeau kill switch actionnable et formulaire d'exécution._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaDetailView`, `backend/trading/views_trade_ideas.py:TradeIdeaDetailView._compute_market_snapshot`, `backend/trading/views_trade_ideas.py:TradeIdeaDetailView._build_broker_suggestions`, `backend/trading/mixins.py:UserScopedTradeIdeaMixin`

- Accès restreint à user=request.user (404 sinon).
- Décision IA du détail (règles différentes du live feed) : EXECUTE si overall >= 0.75, confidence >= 0.70 ET direction alignée sur la tendance EMA ; PLAN si overall >= 0.60 et aligné ; WATCH si overall >= 0.45 ; sinon REJECT.
- Les brokers listés sont uniquement ceux de l'utilisateur et actifs ; idem pour les portefeuilles (is_active).
- Pour chaque broker, TradeIdeaPreviewService fournit le minimum de mise ; le montant pré-rempli est le minimum des minima valides.
- Symboles BOOM*/CRASH* identifiés comme contrats Deriv MULTIPLIER (MULTUP/MULTDOWN, pas de durée) — l'UI bascule les champs en conséquence.
- La détection des kill switches actifs est encapsulée dans try/except : une indisponibilité du service de risque ne doit pas casser la page.
- Valeurs par défaut Deriv affichées : multiplier 100, durée 5, unité 's'.

**Approbation / rejet manuel d'une opportunité**
<br>_L'utilisateur approuve ou rejette une TradeIdea, ce qui déclenche une notification dédiée._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaApproveView`, `backend/trading/views_trade_ideas.py:TradeIdeaRejectView`

- Transition interdite si l'idée est déjà EXECUTED, EXPIRED ou CANCELLED (message d'avertissement, aucun changement).
- Notifications AI_OPPORTUNITY_APPROVED / AI_OPPORTUNITY_REJECTED avec payload idea_id/symbol/direction.
- L'approbation ne déclenche AUCUNE exécution : elle ne fait que changer le statut.

**Exécution d'une opportunité (auto-trade) avec décharge de risque**
<br>_Formulaire d'exécution d'une TradeIdea : choix du broker, du portefeuille et du montant, avec case de dérogation au risque tracée pour audit._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaAutoTradeView`

- Broker et portefeuille doivent appartenir à l'utilisateur et être actifs (get_object_or_404) ; montant > 0 obligatoire.
- Kill switch actif en mode non paper/demo = blocage HARD NON franchissable par l'override ; l'utilisateur est redirigé vers dashboard:resolve_kill_switch. Invariant : l'override ne lève jamais un kill switch LIVE.
- PortfolioAdvisorAgent en BLOCK_NEW_POSITIONS = blocage SOFT : franchissable si risk_override est coché, avec message d'avertissement et consignation.
- L'override est tracé avec user_id, motif (500 car. max), IP (X-Forwarded-For en priorité, 45 car.) et User-Agent (512 car.) : audit obligatoire.
- Mode PAPER : avertissement explicite que l'ordre est simulé et n'atteint pas le broker (message renforcé pour Deriv avec token).
- Le message de confirmation distingue PAPER (simulé) et LIVE (envoyé au broker, avec broker_order_id et statut) et rappelle l'override appliqué.
- Les erreurs contenant 'Kill switch' donnent l'URL de résolution ; les autres suggèrent la case 'Forcer l'exécution'.

**Moteur d'exécution d'une opportunité (sizing + risque + ordre)**
<br>_Service central qui dimensionne la position, fait valider le trade par le risk engine, crée l'ordre, le soumet et enregistre le feedback._
<br>Points d'entrée : `backend/trading/services/trade_idea_execution.py:TradeIdeaExecutionService.execute`, `backend/trading/services/trade_idea_execution.py:TradeIdeaExecutionService._build_deriv_sizing`, `backend/trading/services/trade_idea_execution.py:TradeIdeaExecutionService._build_deriv_order_metadata`

- Cohérence utilisateur triple : idea.user_id == portfolio.user_id == broker_account.user_id, et portfolio.broker_account_id == broker_account.id.
- Signal, asset et symbole obligatoires sur l'idée ; un signal non APPROVED/QUEUED est approuvé via SignalReviewService avant création de l'ordre.
- PortfolioAdvisorAgent (BLOCK_NEW_POSITIONS / CLOSE_WEAK_POSITIONS) bloque l'exécution — SAUF pour les brokers Deriv où l'agent n'est volontairement pas interrogé.
- Deriv : quantity = 1 et notional = stake (JAMAIS quantity = stake, sinon la position et le passage en FILLED sont faux) ; minimum de mise 1.00.
- Capital Preservation First : sur Deriv la mise EST la perte max, donc elle est plafonnée à equity * max_risk_per_trade% ajusté par le tier d'instrument (risk.instruments.effective_risk_pct). Ce plafond ne peut que réduire.
- Si le plafond de risque fait descendre la mise SOUS le minimum broker, le trade est REFUSÉ avec un message explicite (capital trop faible pour cet instrument) — on ne contourne pas le plafond.
- Hors Deriv : PositionSizingService.compute avec min_qty / qty_step / min_notional issus de BrokerConstraint (synchronisés à la demande) et instrument_tier.
- La RiskDecision est persistée AVANT le test BLOCK/REJECT : une décision de refus reste tracée en base.
- risk_decision_id est injecté dans order.metadata, ce qui rend ExecutionOrchestrator.validate_order_risk idempotent (pas de second contrôle ni de double réduction de taille).
- Un échec de soumission broker met l'ordre en FAILED (avec submit_error en metadata) ET l'idée en FAILED, puis lève ValueError.
- Le statut de l'idée est dérivé du statut de l'ordre (FILLED/PARTIALLY_FILLED => EXECUTED, REJECTED/FAILED/CANCELLED/EXPIRED => FAILED, sinon ORDER_SUBMITTED) via _safe_set_idea_status qui retombe sur une valeur autorisée par les choices.
- Un TradeIdeaFeedback est créé/mis à jour avec outcome dérivé (OPEN / FAILED / PENDING) et un learning_payload complet.
- Notifications et broadcast dashboard sont émis HORS transaction, après le commit : un échec de notification ne peut pas annuler le trade. Invariant.
- Les erreurs DatabaseError / TransactionManagementError sont re-levées telles quelles (pas de masquage).

**Prévisualisation du minimum de mise par broker**
<br>_Calcule, pour une idée et un compte broker, le minimum de mise broker, le minimum imposé par le risque et la suggestion affichée à l'utilisateur._
<br>Points d'entrée : `backend/trading/services/trade_idea_preview.py:TradeIdeaPreviewService.estimate_minimum_stake`

- Deriv : la mise est un stake fixe, on ne calcule JAMAIS prix * quantité ; minimum 1.00 et min_qty/qty_step/min_notional à zéro.
- Hors Deriv : minimum broker = max(entry * min_qty, min_notional) arrondi au centime SUPÉRIEUR (ROUND_CEILING, jamais au plus proche).
- Minimum de risque = |entry - stop| * min_qty si un stop valide et différent de l'entrée existe, sinon 0.
- Suggestion = max(minimum broker, minimum risque).
- entry <= 0 => ok=False avec reason=entry_invalid (pas de montant inventé).
- Les contraintes broker sont lues en base puis synchronisées à la demande ; un échec de synchronisation retourne None sans casser la page.

**Expiration automatique des opportunités**
<br>_Passe en EXPIRED les TradeIdea dont la fenêtre est dépassée._
<br>Points d'entrée : `backend/trading/tasks.py:expire_trade_ideas_task`, `backend/trading/tasks.py:expire_old_trade_ideas`

- Seuls les statuts NEW, REVIEW et APPROVED sont expirables : une idée EXECUTED ou REJECTED n'est jamais réécrite.
- expires_at <= now ; expire_old_trade_ideas ajoute expires_at__isnull=False.
- Mise à jour en masse (update) : aucun signal Django ni notification n'est émis.
- Les deux tâches sont redondantes et planifiées toutes les deux à la minute.

**Feedback et apprentissage sur les opportunités exécutées**
<br>_Rapproche chaque idée exécutée de sa position pour calculer le PnL, l'issue (WIN/LOSS/BREAKEVEN) et alimenter l'apprentissage._
<br>Points d'entrée : `backend/trading/tasks.py:learn_from_trade_ideas_task`, `backend/trading/tasks.py:run_learning_refresh_cycle`, `backend/trading/models.py:TradeIdeaFeedback`

- Seuls les feedbacks en outcome=OPEN et dont l'idée est EXECUTED sont traités.
- Issue dérivée du PnL de la position : > 0 => WIN + hit_take_profit, < 0 => LOSS + hit_stop_loss, = 0 => BREAKEVEN ; position encore OPEN => reste OPEN.
- Relation OneToOne idea <-> feedback : un seul feedback par idée (update_or_create).
- run_learning_refresh_cycle ne traite que les feedbacks WIN/LOSS/BREAKEVEN et rafraîchit un LearningSnapshot par stratégie concernée.

**Exécution autonome hedge fund**
<br>_Sélectionne la meilleure idée d'un portefeuille selon la confiance et le risque global, calcule la taille et l'exécute automatiquement._
<br>Points d'entrée : `backend/trading/services/hedge_fund/engine.py:AIHedgeFundEngine.execute_top_idea_for_portfolio`, `backend/trading/services/hedge_fund/engine.py:AIHedgeFundEngine._reject_idea`

- GlobalRiskAgent doit autoriser de nouvelles positions (allow_new_positions) sinon aucun trade pour ce portefeuille.
- Les idées candidates sont filtrées sur user=portfolio.user et statut NEW ou APPROVED, triées par priorité d'exécution puis confiance puis score.
- Confiance finale < MIN_EXECUTION_CONFIDENCE (0.65) => idée ignorée (pas rejetée).
- Binance en LIVE exige broker_account.last_connection_status validé, sinon arrêt.
- Une taille calculée <= 0 ou un échec de sizing rejette l'idée avec rejection_stage tracé dans ai_payload.
- Un rejet propage le statut REJECTED au Signal lié en y annexant la raison.
- Un seul ordre maximum par portefeuille et par cycle (return dès le premier succès).
- Le portefeuille sans broker actif est ignoré.

**Intention de trading — création et formulaire**
<br>_Création d'une mission de trading (capital, objectif, durée, risque, mode) avec validations croisées strictes._
<br>Points d'entrée : `backend/trading/forms.py:TradingIntentForm`, `backend/trading/views.py:TradingIntentCreateView`, `backend/trading/views.py:TradingIntentListView`, `backend/trading/views.py:TradingIntentDetailView`

- Bornes : capital > 0 et <= 1 000 000 ; objectif de rendement dans [0 ; 1000] % ; perte max dans [0 ; 100] % ; durée dans [1 ; 365] jours ; positions ouvertes dans [1 ; 50].
- Perte maximale > 50 % refusée (intention jugée ingérable).
- Ratio risque/récompense >= 1 obligatoire : target_return_percent doit être >= max_loss_percent.
- Les listes déroulantes portefeuille et broker sont restreintes aux objets de l'utilisateur.
- Toutes les vues filtrent sur user=request.user.

**Intention de trading — analyse IA et lancement**
<br>_Analyse de faisabilité produisant un plan IA, puis lancement effectif créant/activant une stratégie et son déploiement._
<br>Points d'entrée : `backend/trading/services/execution/base_execution.py:IntentExecutionService.analyze`, `backend/trading/services/execution/base_execution.py:IntentExecutionService.launch`, `backend/trading/services/execution/base_execution.py:AIPlanningService.build_plan`

- Faisabilité VERY_LOW (>= 200 % de rendement visé en <= 4 jours) combinée au mode LIVE => intention REJECTED : on n'autorise pas une mission irréaliste en argent réel.
- Le lancement exige un statut PLANNED/APPROVED/RUNNING et un ai_plan non vide.
- portfolio.user_id == intent.user_id ; le broker de l'intention doit être celui du portefeuille ; broker_account.mode doit être identique à intent.execution_mode.
- Si aucune stratégie n'est liée, elle est créée automatiquement (asset résolu par stratégie > première position > premier symbole du plan ; timeframe du plan sinon le plus court) ; l'absence d'asset exploitable lève une erreur explicite.
- La stratégie créée doit appartenir à l'utilisateur ; allow_live_execution est aligné sur execution_mode.
- Le déploiement est activé avec auto_execute=False : une intention lancée n'exécute pas d'elle-même sans validation.
- expires_at = maintenant + duration_days ; approved_by_user passé à True.
- Chaque transition écrit un TradingIntentEvent (ANALYZED, STARTED, ORDER_CREATED...).

**Intention de trading — monitoring des métriques**
<br>_Recalcule le PnL latent/réalisé et le rendement d'une mission, et la clôture automatiquement à expiration._
<br>Points d'entrée : `backend/trading/services/execution/base_execution.py:IntentMonitoringService.refresh_metrics`

- Le rafraîchissement n'est déclenché QUE si l'intention est RUNNING (limite les effets de bord sur une requête GET).
- unrealized_pnl agrège toutes les positions OPEN du portefeuille (pas seulement celles de l'intention) ; realized_pnl est figé à 0 — limite connue.
- Une intention RUNNING dont expires_at est dépassé passe en COMPLETED avec ended_at.
- actual_return_percent = (realized + unrealized) / capital_amount * 100, uniquement si capital_amount > 0.

**Contrats Deriv — consultation (historique)**
<br>_Liste et détail des DerivContract, table historique conservée pour les contrats achetés avant la bascule sur l'OMS canonique._
<br>Points d'entrée : `backend/trading/views_deriv.py:DerivContractListView`, `backend/trading/views_deriv.py:DerivContractDetailView`, `backend/trading/models.py:DerivContract`

- Filtrage sur portfolio__user=request.user.
- Aucune nouvelle exécution ne doit écrire dans cette table (la source de vérité est execution.Order + BrokerExternalRef).
- contract_id unique en base ; statuts OPEN/WON/LOST/SOLD/CANCELLED/EXPIRED/FAILED.
- Pagination 30.

**Règlement d'un contrat Deriv**
<br>_Applique le règlement terminal d'un contrat Deriv : statut, clôture de position, création du Trade et crédit du payout._
<br>Points d'entrée : `backend/trading/services/deriv_settlement.py:DerivSettlementService.handle_contract_update`, `backend/trading/services/deriv_settlement.py:DerivSettlementService._settle`

- Détermination du statut : is_sold => SOLD ; is_settleable => statut mappé (défaut WON) ; sinon mapping brut (won/lost/sold/expired/open/running).
- Si le contrat est DÉJÀ dans un statut terminal, on ne rejoue PAS le règlement : seul latest_contract_payload est rafraîchi. Idempotence de premier niveau.
- Idempotence du crédit : on vérifie qu'aucune CashLedgerEntry TRADE_EXECUTION positive n'existe déjà pour (portfolio, DERIV_CONTRACT, contract.id) avant de créditer.
- Comptabilité : ouverture -buy_price, clôture WON/SOLD +sell_price, LOST/EXPIRED aucun mouvement (le stake avait déjà été débité). Solde net = profit.
- La position est verrouillée (select_for_update) et re-testée après verrou avant clôture : pas de double clôture concurrente.
- Trade.opening_order et Trade.closing_fill sont NULL pour les contrats Deriv historiques (FK pointant vers execution.*) ; la traçabilité passe par Trade.metadata.
- L'absence de position ouverte est loggée en warning sans créer de Trade (on n'invente pas de round-trip).
- Les métriques du portefeuille sont rafraîchies en fin de règlement.

**Surveillance des contrats Deriv ouverts**
<br>_Interroge périodiquement Deriv pour les contrats encore ouverts et délègue le règlement au dispatcher._
<br>Points d'entrée : `backend/trading/tasks.py:sync_open_deriv_contracts_task`, `backend/trading/tasks.py:sync_execution_deriv_contracts_task`

- Le statut de l'execution.Order passe FILLED dès l'achat du contrat : il ne renseigne donc PAS sur le règlement. La source de vérité du cycle de vie est BrokerExternalRef.last_status (reste 'open' jusqu'au règlement). Invariant à préserver.
- Statuts terminaux reconnus : won, lost, sold, expired, cancelled, closed.
- Le compte Deriv utilisé est choisi selon broker_account.deriv_account_type (défaut 'demo'), sinon le premier compte disponible ; un compte invalide lève une erreur.
- Un payload proposal_open_contract vide est ignoré (pas de règlement sur données manquantes).
- Le règlement est TOUJOURS délégué à on_open_contract_update (jamais réimplémenté sur place).
- La connexion client est systématiquement fermée en finally ; une erreur sur un contrat n'interrompt pas la boucle (compteur failed).

**Recommandations IA — approbation, rejet et exécution**
<br>_Cycle de vie des TradeRecommendation : approuver, rejeter ou exécuter (création d'une TradeIdea puis passage par le moteur d'exécution)._
<br>Points d'entrée : `backend/trading/services/recommendation_actions.py:RecommendationActionService`, `backend/api/views/ai.py:TradeRecommendationViewSet`

- Exécution autorisée uniquement depuis les statuts APPROVED_BY_AI, APPROVED_BY_USER ou PENDING.
- L'exécution crée une TradeIdea en statut APPROVED à partir de l'opportunité, puis délègue à TradeIdeaExecutionService (toutes les règles de risque de ce service s'appliquent).
- Chaque action met à jour le DecisionAudit correspondant (final_decision, execution_output) : la piste d'audit est obligatoire.
- generate_for_portfolio exige un portfolio_id valide et actif de l'utilisateur ; la génération est asynchrone (202 implicite avec task_id).
- La génération ignore les opportunités ayant déjà une recommandation PENDING/APPROVED/EXECUTED pour ce portefeuille (pas de doublon), et se limite aux 20 meilleures opportunités ACTIVE.

**Tableaux de bord hedge fund, risque et apprentissage**
<br>_Trois écrans de supervision (synthèse hedge fund, moniteur de risque, moniteur d'apprentissage) avec endpoints JSON de rafraîchissement._
<br>Points d'entrée : `backend/trading/views_hedge_fund.py:HedgeFundDashboardView`, `backend/trading/views_hedge_fund.py:RiskMonitorView`, `backend/trading/views_hedge_fund.py:LearningMonitorView`, `backend/trading/views_hedge_fund.py:risk_monitor_api`, `backend/trading/views_hedge_fund.py:learning_monitor_api`

- Les portefeuilles, RiskState et positions sont filtrés sur l'utilisateur courant.
- Pour chaque portefeuille, seul le RiskState le plus récent est retenu (déduplication en Python sur un queryset trié).
- Les séries de graphes sont bornées (20 positions, 10 meilleures idées, 50 snapshots, 30 événements de renforcement).

**Données de marché de la page d'accueil**
<br>_Endpoint JSON public renvoyant les cotations agrégées affichées sur la landing, avec cache 30 s côté vue et 60 s côté service._
<br>Points d'entrée : `backend/trading/views.py:market_data_api`, `backend/trading/market_data.py:get_landing_market_data`

- Endpoint NON authentifié (seul de ce domaine).
- Double cache : 30 s sur la clé landing_market_data dans la vue, 60 s sur leotrade:market:landing dans le service, pour amortir le rate limit de la source externe.
- La réponse porte un drapeau available=False quand la source est indisponible : le frontend affiche un état dédié plutôt que des données vides ou inventées.

**Administration des objets d'exécution**
<br>_Interface d'administration Django pour inspecter ordres, fills, événements, journaux de synchronisation et protections._
<br>Points d'entrée : `backend/execution/admin.py`

- Les horodatages du cycle de vie (submitted_at, filled_at, cancelled_at, rejected_at, expired_at) et les champs de fill sont en lecture seule : on ne réécrit pas l'historique d'exécution à la main.
- Pour PositionProtection, triggered_at / completed_at / last_evaluated_at sont également en lecture seule.
- Recherche par symbole, broker_order_id, broker_client_order_id, idempotency_key et email utilisateur.
- L'admin de l'app trading est presque entièrement commenté : seuls les modèles d'exécution restent administrables.

</details>

<details><summary>Pièges de migration repérés</summary>

- URLs cassées dans les templates : templates/trading/intent_detail.html référence {% url 'intent-analyze' %}, 'intent-launch' et 'order-detail' SANS le namespace, alors que trading.urls est inclus avec namespace='trading'. Idem deriv_contract_detail.html ('signal-detail', 'order-detail'). Ces pages lèvent probablement NoReverseMatch — vérifier avant de considérer la fonctionnalité comme existante.
- ExecuteTradeIdeaView (backend/trading/views_trade_ideas.py:802) est implémentée mais n'est routée nulle part : le seul chemin d'exécution réel est TradeIdeaAutoTradeView. Ne pas porter deux parcours d'exécution différents.
- Le formulaire auto-trade envoie duration, duration_unit et multiplier mais TradeIdeaAutoTradeView ne les lit pas : ces paramètres Deriv sont en réalité dérivés de signal.metadata dans _build_deriv_order_metadata. Champs d'UI non fonctionnels à ne pas reproduire tels quels — décider si le client doit pouvoir les surcharger.
- Logique métier lourde dans la couche présentation : calcul RSI/ATR/EMA, régime de marché, décision IA, score de qualité d'exécution et guidance humaine sont implémentés DEUX FOIS avec des seuils DIFFÉRENTS dans TradeIdeaLiveFeedView et TradeIdeaDetailView. À extraire dans un service unique avant toute exposition API, sinon web et mobile afficheront des décisions divergentes.
- HedgeFundDashboardView calcule ideas, top_ideas et la quasi-totalité de stats sur TradeIdea.objects SANS filtre utilisateur : fuite de données inter-utilisateurs. À corriger obligatoirement lors du portage API.
- MarketScanRunViewSet et MarketOpportunityViewSet déterminent leur filtre utilisateur par une boucle try/except sur des kwargs de filtre : comportement implicite et fragile, à remplacer par un filtre explicite.
- Trois modèles historiques coexistent avec l'OMS canonique : trading.Order, trading.TradeExecution et trading.DerivContract. trading.Order n'est plus écrit mais reste référencé (DerivContract.order, DerivSettlementService, learn_from_trade_ideas_task). Toute reprise doit lire execution.Order exclusivement.
- learn_from_trade_ideas_task fait Position.objects.filter(portfolio__orders__id=feedback.order_id) : 'orders' pointe sur trading.Order (legacy, plus alimenté) alors que feedback.order_id contient un id d'execution.Order. Le rapprochement est très probablement cassé — vérifier avant de reconstruire l'écran de performance IA.
- trading.tasks.sync_execution_deriv_contracts_task (règlement des contrats Deriv du chemin canonique) n'est PAS dans CELERY_BEAT_SCHEDULE : le règlement repose uniquement sur brokers.tasks_deriv_sync.sync_deriv_positions_task. Dépendance implicite à documenter.
- Deux tâches d'expiration d'idées redondantes (expire_trade_ideas_task et expire_old_trade_ideas) planifiées toutes les deux chaque minute.
- ExecutionOrchestrator.cancel_order appelle le broker À L'INTÉRIEUR d'une transaction atomique, contrairement à submit_order qui a été corrigé en trois phases. Risque de verrou long et de désync broker/DB à la clôture.
- Le mode NATIVE_BROKER de PositionProtection n'envoie jamais de modification au broker : les SL/TP MT5 ne sont posés qu'à l'ouverture et le trailing est déclaré UNSUPPORTED. Ne pas promettre un trailing broker côté UI.
- L'auto-rafraîchissement de templates/trading/order_list.html fait un fetch de la page entière dont le résultat est jeté : faux temps réel, à remplacer par le WebSocket ou un endpoint JSON.
- execution.consumers.UserNotificationsConsumer est défini mais non routé (doublon avec notifications.routing) : code mort à ne pas porter.
- AIHedgeFundEngine.execute_top_idea_for_portfolio nomme 'order' le dict retourné par TradeIdeaExecutionService.execute : la valeur retournée n'est pas un Order. Le compteur executed_orders de la tâche reste correct par chance (dict truthy).
- État implicite dans Order.metadata : reduce_only, closes_position_id, risk_decision_id, recovery_attempt, manual_review_reason, broker_state_unknown, risk_override. Ces clés pilotent des décisions critiques (kill switch contourné, pas de second risk check, pas de resoumission) sans contrainte de schéma. À typer explicitement lors de la refonte.
- Couplage fort execution -> risk -> portfolio -> strategies : ExecutionOrchestrator.submit dépend de risk.engine.RiskEngine, risk.services.RiskGuardService, portfolio.services.PortfolioAccountingService et strategies.services.deployment/signal_review. L'ordre des blocages du RiskEngine (dont certains déclenchent le kill switch en effet de bord) est un invariant du domaine risk à ne pas réordonner depuis ce domaine.
- IntentMonitoringService.refresh_metrics est déclenché par une requête GET (effet de bord sur une lecture) et agrège le PnL de TOUT le portefeuille, pas seulement celui de l'intention ; realized_pnl est figé à 0.
- Les messages d'erreur métier remontent en texte libre via django.contrib.messages, avec un matching par sous-chaîne ('Kill switch' in err_str, 'minimum broker' in lower_message). Il faut des codes d'erreur structurés pour que React et Flutter distinguent blocage HARD, blocage SOFT franchissable et erreur technique.

</details>

---

### risk

`29 fonctionnalités` — API : **8 prêtes, 9 partielles, 12 à exposer**

**Modèles** : `RiskProfile`, `DailyRiskState`, `WeeklyRiskState`, `MonthlyRiskState`, `RiskDecision`, `KillSwitchEvent`, `StrategyCircuitBreakerEvent`, `RiskOverrideAudit`, `RiskAuditLog`

**Tâches Celery** : `risk.tasks.refresh_daily_risk_states_task (beat: */5 min)`, `risk.tasks.refresh_weekly_risk_states_task (beat: */15 min)`, `risk.tasks.refresh_monthly_risk_states_task (beat: */30 min)`, `risk.tasks.auto_enforce_kill_switch_task (beat: */2 min)`, `risk.tasks.evaluate_strategy_circuit_breakers_task (beat: */15 min)`, `execution.tasks.refresh_daily_risk_states_task (doublon non planifié)`, `execution.tasks.refresh_weekly_risk_states_task (doublon non planifié)`, `execution.tasks.auto_enforce_kill_switch_task (doublon non planifié)`

**Canaux WebSocket** : `ws/dashboard/live/ -> groupe user_dashboard_{user_id} (trading/consumers.py:DashboardConsumer) : événements dashboard.update avec payload kind=kill_switch_triggered et kind=kill_switch_resolved émis par RiskGuardService`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Profil de risque par portefeuille** | 🟡 | WEB/MOBILE |  | api/serializers/risk.py:RiskProfileSerializer liste ses champs en dur et a été oublié lors des migrations 0005/0007 : max_monthly_loss, preservation_mode, allow_volatile_instruments et allow_speculative_instruments ne sont ni lus ni écrits par /api/v1/risk-profiles/. RiskControlService.profile_snapshot ne renvoie pas non plus les 3 flags d'instruments ni max_symbol/asset_class/correlated_exposure_percent, block_on_high_correlation, require_stop_loss. Il faut un serializer unique et exhaustif. |
| **Modification auditée des limites de risque** | ✅ | WEB/MOBILE |  | — |
| **Mode préservation du capital & opt-in par classe d'instrument** | 🟡 | WEB/MOBILE |  | Les 3 flags sont absents de RiskProfileSerializer et de profile_snapshot : aucun client React/Flutter ne peut aujourd'hui LIRE l'état de l'opt-in, seulement l'écrire via PATCH /risk/api/profile/. Il manque aussi un endpoint renvoyant le tier et la policy d'un symbole donné (aujourd'hui uniquement calculé côté serveur dans le payload de décision). |
| **Classification d'instruments CORE/VOLATILE/SPECULATIVE** | ❌ | WEB/MOBILE |  | Aucun endpoint n'expose le tier, la policy ni la disclosure d'un symbole. L'UI Web/Flutter a besoin d'un GET (ex. /api/v1/risk/instruments/{symbol}/) renvoyant tier, label, max_risk_per_trade_pct, eligible_for_preservation, requires_explicit_optin et disclosure, pour afficher le badge de classe et le texte de transparence avant exécution. |
| **Dimensionnement de position (position sizing)** | ❌ | WEB/MOBILE |  | Aucun endpoint de simulation de sizing. Les clients React/Flutter ont besoin d'un POST de prévisualisation (symbole, prix, stop, stake) renvoyant SizingResult + reason, pour afficher la quantité avant de soumettre un ordre et éviter un aller-retour d'erreur. |
| **Volatility targeting (ATR)** | ❌ | WEB/MOBILE |  | Aucun appelant du code applicatif ne passe actuellement atr : RiskEngine et TradeIdeaExecutionService n'alimentent que instrument_tier. La fonctionnalité existe mais est dormante — à câbler sur une source d'ATR lors de la refonte, et à exposer dans la prévisualisation de sizing. |
| **Validation de trade — chaîne de contrôles du Risk Engine** | ❌ | WEB/MOBILE |  | Aucun endpoint de prévisualisation risque exposé publiquement : seul ai_assistant/services_guards.py:risk_preview l'appelle en interne. Un client React/Flutter ne peut pas afficher decision + block_code + block_severity + blocking_reason AVANT de soumettre. Endpoint de dry-run à créer, renvoyant RiskApprovalResult complet (block_code, block_severity, payload). |
| **Réduction automatique de taille sur exposition symbole / classe d'actifs** | 🟡 | WEB/MOBILE |  | La décision REDUCE est lisible a posteriori via /risk/api/decisions/, mais le client ne reçoit jamais la proposition de taille réduite au moment de l'exécution : il faut l'exposer dans la réponse de l'endpoint de dry-run pour permettre une confirmation « exécuter à taille réduite ». |
| **Contrôle d'exposition corrélée** | ❌ | WEB |  | Ni max_correlated_exposure_percent ni block_on_high_correlation ne sont dans profile_snapshot ; le seuil 0,80 n'est pas configurable ni visible. Aucune vue des corrélations côté risque. |
| **Décharge de risque (override) sur blocages SOFT** | ❌ | WEB/MOBILE |  | Fonctionnalité exposée exclusivement par un formulaire Django POST + redirect avec django.messages. Rien côté API : il faut un champ risk_override/risk_override_reason sur l'endpoint d'exécution d'ordre, la propagation serveur de l'IP et du user-agent, et le retour du couple block_code/block_severity pour que le client sache s'il peut proposer la décharge. C'est la fonctionnalité la plus exposée à l'oubli lors de la refonte. |
| **Audit immuable des décharges de risque** | ❌ | WEB |  | Aucun endpoint REST : ni liste, ni filtre, ni export. L'export CSV n'est accessible que par une action de l'admin Django. Il faut un endpoint paginé/filtrable (user, portefeuille, symbole, période) et un export côté API pour le Web, l'admin Django n'étant pas conservable tel quel dans une refonte React. |
| **Kill switch portefeuille — activation manuelle** | ✅ | WEB/MOBILE | ⚡ | — |
| **Kill switch portefeuille — désactivation / résolution** | ✅ | WEB/MOBILE | ⚡ | Le chemin dashboard (/premium/.../resolve-kill-switch/) est un POST HTML avec redirect + django.messages, à remplacer par l'endpoint REST existant. |
| **Kill switch automatique sur franchissement de limite** | ✅ | WEB/MOBILE | ⚡ | — |
| **Enforcement périodique du kill switch** | ❌ | WEB/MOBILE | ⚡ | Tâche de fond, pas d'API attendue. En revanche l'absence de notification et de broadcast temps réel sur ce chemin signifie qu'un kill switch posé par Celery n'apparaît pas en live dans l'UI : à corriger lors de la refonte pour que le mobile reçoive bien le push. |
| **Historique des événements kill switch** | ✅ | WEB/MOBILE |  | — |
| **États de risque journalier / hebdomadaire / mensuel** | 🟡 | WEB/MOBILE |  | MonthlyRiskState n'a ni serializer DRF ni viewset dans api/ : il n'est accessible que par GET /risk/api/states/ (30 dernières lignes, champs restreints, non paginé, non filtrable par période). Il manque la pagination, le filtre de dates et l'export pour alimenter des graphiques Web/Flutter. |
| **Rafraîchissement manuel des états de risque** | 🟡 | WEB |  | Le refresh mensuel manque (RiskStateService.refresh_monthly_state n'est pas appelé). À compléter lors de la refonte sous peine d'un état mensuel figé entre deux passages Celery. |
| **Historique des décisions du Risk Engine** | 🟡 | WEB/MOBILE |  | /risk/api/decisions/ renvoie 9 champs en dur, sans pagination ni filtre (décision, symbole, période) et sans le payload. Le viewset DRF renvoie tout mais sans filtres ni ordering déclarés. À uniformiser avec pagination + filtres pour la refonte. |
| **Façade RiskEngine sur signal** | ❌ | — |  | Service interne ; pas d'API attendue, mais sa décision doit rester la source de vérité unique des clients (ne jamais dupliquer la logique de sizing ou de blocage côté React/Flutter). |
| **Fermeture d'urgence d'une position** | ✅ | WEB/MOBILE |  | — |
| **Fermeture d'urgence des positions perdantes** | ✅ | WEB/MOBILE |  | — |
| **Fermeture d'urgence de toutes les positions** | ✅ | WEB/MOBILE |  | — |
| **Circuit breaker stratégie (kill switch intelligent)** | ❌ | WEB/MOBILE |  | Aucune API ni UI : les StrategyCircuitBreakerEvent ne sont ni sérialisés, ni exposés, ni même enregistrés dans l'admin Django (risk/admin.py ne les déclare pas). L'utilisateur ne voit nulle part pourquoi sa stratégie a été mise en pause. À exposer en liste + détail lors de la refonte. |
| **Résolution / réactivation d'un circuit breaker stratégie** | ❌ | WEB |  | Fonctionnalité réelle mais totalement inaccessible : ni route, ni action admin, ni API. Le message de notification promet pourtant une « réactivation possible après revue depuis l'admin ou la page stratégie ». À exposer (POST de résolution avec flag reactivate) sous peine d'avoir des stratégies définitivement bloquées. |
| **Journal d'audit du module Risk Control** | ❌ | WEB |  | Aucun endpoint : le journal n'est consultable que via l'admin Django. Il faut une liste paginée et filtrable (action, mode, succès, période) pour remplacer l'admin dans l'interface React. |
| **Vue d'ensemble Risk Control (snapshot)** | 🟡 | WEB/MOBILE |  | Le snapshot omet plusieurs champs du profil (expositions symbole/classe/corrélation, min_confidence, max_leverage, allow_short, require_stop_loss, block_on_high_correlation, les 3 flags d'instruments) et ne renvoie ni le nombre de positions ouvertes ni le compteur de limites atteintes. L'effet de bord de rafraîchissement doit être découplé pour supporter un polling mobile. |
| **Garde-fous risque de l'assistant IA** | 🟡 | WEB/MOBILE |  | risk_preview est la seule prévisualisation de risque existante mais elle n'est appelée que par l'assistant. À promouvoir en endpoint public de dry-run, réutilisable par le Web et le mobile avant tout envoi d'ordre. |
| **Diffusion temps réel des événements kill switch** | 🟡 | WEB/MOBILE | ⚡ | Le canal est lié au dashboard générique, pas au domaine risque, et resolved_count est calculé après l'update de la queryset (valeur potentiellement incorrecte). Pour Flutter il faut un canal/evénement risque dédié, plus un push mobile sur l'événement critique KILL_SWITCH_ACTIVATED. |

<details><summary>Règles métier invariantes à préserver</summary>

**Profil de risque par portefeuille**
<br>_Jeu de limites (risque/trade, pertes jour/semaine/mois, drawdown, positions max, expositions, levier, confiance min, autorisations short/live/stop-loss) attaché à un couple user+portfolio. Un profil par défaut est auto-créé si absent._
<br>Points d'entrée : `risk/models.py:RiskProfile`, `risk/services.py:RiskGuardService.get_default_profile`, `risk/services_control.py:RiskControlService.profile_snapshot`, `api/views/risk.py:RiskProfileViewSet`, `risk/api.py:profile`

- get_default_profile fait un get_or_create silencieux : un portefeuille sans profil n'est JAMAIS bloqué, il reçoit « Default Risk Profile » avec les valeurs par défaut du modèle
- Sélection du profil = is_active=True ET is_default=True, en premier résultat
- unique_together (portfolio, name) : impossible d'avoir deux profils de même nom sur un portefeuille
- set_default retire is_default de tous les autres profils du même portefeuille avant de poser le nouveau
- Valeurs par défaut porteuses de la politique : preservation_mode=True, allow_volatile_instruments=False, allow_speculative_instruments=False, allow_short=False, require_stop_loss=True, kill_switch_enabled=True

**Modification auditée des limites de risque**
<br>_Seul chemin de mutation légitime du profil : applique un diff champ par champ, journalise avant/après et notifie l'utilisateur._
<br>Points d'entrée : `risk/services_control.py:RiskSettingsUpdateService.update`, `risk/api.py:profile (branche PATCH)`

- Liste blanche stricte EDITABLE_FIELDS : tout champ hors liste est silencieusement ignoré (pas d'erreur)
- Les champs DECIMAL_FIELDS refusent les valeurs négatives (retour ok=False, aucune écriture)
- max_open_positions forcé à max(0, int(valeur))
- Les autres champs sont castés en bool()
- Seuls les champs réellement modifiés sont écrits (save(update_fields=...)) ; un diff vide renvoie ok=True sans audit ni notification
- Chaque mise à jour effective crée un RiskAuditLog action=RISK_SETTINGS_UPDATE avec before/after + IP + user-agent, et émet une notification SECURITY_ALERT
- C'est le SEUL mutateur qui accepte preservation_mode / allow_volatile_instruments / allow_speculative_instruments : sans lui, le message de blocage « active cette classe dans ton profil » n'a aucun chemin d'exécution

**Mode préservation du capital & opt-in par classe d'instrument**
<br>_Restreint l'univers tradable aux instruments CORE ; les classes VOLATILE et SPECULATIVE exigent un opt-in explicite, tracé et révocable._
<br>Points d'entrée : `risk/services.py:RiskGuardService.validate_trade (bloc 9bis)`, `risk/instruments.py:policy_for_tier`, `risk/models.py:RiskProfile.preservation_mode/allow_volatile_instruments/allow_speculative_instruments`

- ORDRE CRITIQUE : le bloc 9bis doit rester APRÈS les blocs 7/8/8bis/9 (pertes jour/semaine/mois, drawdown) car ceux-ci déclenchent le kill switch en EFFET DE BORD ; un retour anticipé masquerait cette protection plus forte
- Les deux blocages sont SOFT : franchissables par décharge explicite, ce qui trace l'opt-in dans RiskOverrideAudit
- SPECULATIVE est gouverné par allow_speculative_instruments, VOLATILE par allow_volatile_instruments ; CORE ne requiert jamais d'opt-in
- preservation_mode exclut tout instrument dont eligible_for_preservation=False (VOLATILE et SPECULATIVE)
- Le message de blocage inclut toujours la disclosure de la classe (transparence, aucune promesse de performance)

**Classification d'instruments CORE/VOLATILE/SPECULATIVE**
<br>_Classe un instrument en trois niveaux porteurs chacun d'une politique de risque (plafonds durs, éligibilité préservation, opt-in, disclosure)._
<br>Points d'entrée : `risk/instruments.py:classify`, `risk/instruments.py:policy_for`, `risk/instruments.py:policy_for_tier`, `risk/instruments.py:is_deriv_synthetic`, `risk/instruments.py:effective_risk_pct`

- Ordre de résolution NON négociable : motif de symbole -> exchange -> FX majeur -> asset_class -> fail-safe. asset_class n'est pas fiable (les synthétiques Deriv sont seedés en INDEX)
- Fail-safe restrictif : un instrument non reconnu est classé SPECULATIVE, jamais CORE
- Tout instrument dont l'exchange est DERIV est SPECULATIVE
- Le regex _DERIV_SYNTHETIC_RE doit couvrir R_*, 1HZ*V, BOOM/CRASH (avec suffixe N), JD*, STEPINDEX, STPRNG*, RB*, RDBEAR/RDBULL — 1HZ*V et stpRNG étaient manqués par l'ancien détecteur et ressortaient CORE
- Normalisation du symbole : majuscules, suppression de =X / .CASH / .SPOT et de tout caractère non [A-Z0-9_]
- Tolérance aux suffixes courtier sur les majeurs FX (EURUSDm, EURUSD.a, EURUSD_raw) : préfixe majeur + au plus 4 caractères, sinon EURUSD tomberait en VOLATILE et serait bloqué en préservation
- FOREX non majeur = VOLATILE ; STOCK/ETF/INDEX/BOND = CORE ; CRYPTO/COMMODITY = VOLATILE
- effective_risk_pct = min(risque du profil, plafond de la classe) : le plafond de classe ne peut QUE réduire, jamais augmenter
- Plafonds durs : CORE 0,50 % / VOLATILE 0,25 % / SPECULATIVE 0,25 % de risque par trade

**Dimensionnement de position (position sizing)**
<br>_Calcule la quantité et le notionnel approuvés à partir du risque autorisé, du stake demandé, du cash disponible et des contraintes broker._
<br>Points d'entrée : `risk/services.py:PositionSizingService.compute`, `risk/services.py:SizingResult`, `risk/engine.py:RiskEngine.evaluate`

- La quantité finale est le MINIMUM de : quantité par risque (risk_amount / stop_distance), par stake (stake / prix), par cash (cash / prix) et, si ATR fourni, par volatilité
- Le risque effectif = min(max_risk_per_trade du profil, plafond dur de la classe d'instrument) — le plafond de classe ne peut que réduire
- Pré-conditions dures levant ValueError : stake <= 0, prix d'entrée <= 0, stop_loss absent ou <= 0, cash disponible <= 0, equity <= 0, risque autorisé <= 0, distance au stop <= 0
- La quantité est tronquée (ROUND_DOWN) au qty_step du broker, jamais arrondie au-dessus
- Quatre ValueError distinctes et explicatives selon la contrainte violée (risque / stake / cash / arrondi), chacune indiquant le montant minimum requis — ces messages sont repris tels quels dans l'UI d'exécution
- approved_stake = min(notional, cash disponible)
- Le notionnel doit respecter min_notional du broker

**Volatility targeting (ATR)**
<br>_Borne supplémentaire de quantité pour qu'un mouvement de 1 ATR ne fasse pas varier l'équité au-delà du budget de volatilité._
<br>Points d'entrée : `risk/services.py:PositionSizingService.compute (branche atr_value > 0)`

- Activé uniquement si un ATR > 0 est fourni ; sinon aucun effet (rétrocompatible)
- Budget par défaut = le risque EFFECTIF déjà plafonné par la classe, pas une valeur figée : un budget figé à 1 % laisserait un mouvement d'1 ATR coûter 4x le plafond d'un SPECULATIVE (0,25 %)
- Complète le stop-based sizing : protège quand le stop est très serré sur un instrument très volatil (stop-out quasi certain)
- N'intervient qu'en réduction (ajouté à la liste des candidats du min)

**Validation de trade — chaîne de contrôles du Risk Engine**
<br>_Point de passage obligatoire avant toute création d'ordre : enchaîne 12 contrôles ordonnés et rend APPROVE / REDUCE / REJECT / BLOCK avec severity et code machine._
<br>Points d'entrée : `risk/services.py:RiskGuardService.validate_trade`, `risk/services.py:RiskApprovalResult`, `risk/services.py:RiskGuardService._build_block`, `risk/services.py:RiskGuardService._build_result`

- Ordre des contrôles IMMUABLE : 1 kill switch, 2 live interdit, 3 short interdit, 4 confiance IA, 5 stop loss requis, 6 positions max, 7 perte jour, 8 perte semaine, 8bis perte mois, 9 drawdown, 9bis classe d'instrument, puis exposition symbole, exposition classe d'actifs, corrélation
- Les blocs 7/8/8bis/9 déclenchent trigger_kill_switch EN EFFET DE BORD avant de rendre le blocage : tout réordonnancement ou retour anticipé supprime cette protection
- Trois codes HARD non franchissables, même avec override : KILL_SWITCH_LIVE, LIVE_TRADING_FORBIDDEN, SHORT_FORBIDDEN
- Tous les autres blocages sont SOFT (franchissables par décharge) ; SHORT_FORBIDDEN rend decision=REJECT, pas BLOCK
- En PAPER/DEMO, les contrôles 1, 6, 8, 8bis, 9 et l'exposition classe d'actifs ne bloquent pas : ils déposent un avertissement dans payload (kill_switch_warning, max_open_positions_warning, weekly/monthly_loss_warning, drawdown_warning, asset_class_exposure_warning). Le contrôle 7 (perte journalière) bloque MÊME en DEMO
- Le contrôle 5 (stop loss requis) est désactivé pour les trades Deriv (is_deriv)
- Pour un trade Deriv, approved_notional et approved_quantity sont écrasés par requested_stake juste avant le contrôle 6 (le stake EST la quantité)
- Réparations anti-données-contaminées obligatoires en entrée : drawdown > 100 % remis à 0 sur le portefeuille, pertes jour/semaine > 100 % remises à 0 avec payload.auto_repaired=True ; sinon un état corrompu gèlerait définitivement le trading
- Détection Deriv double : broker du portefeuille == DERIV OU préfixe de symbole (R_, 1HZ, HZ, JD, JUMP, CRASH, BOOM, STEP, VOL)
- Le comptage des positions ouvertes exclut, en Deriv, les positions sans broker_position_id
- Le champ d'exposition utilisé est margin_used en Deriv, exposure_value sinon
- Le calcul du R/R : expected_gain/expected_loss, et 0.0000 si expected_loss == 0

**Réduction automatique de taille sur exposition symbole / classe d'actifs**
<br>_Au lieu de bloquer, le moteur rend REDUCE avec un notionnel recalculé pour rester sous la limite d'exposition._
<br>Points d'entrée : `risk/services.py:RiskGuardService.validate_trade (blocs exposition symbole et classe d'actifs)`, `risk/services.py:RiskGuardService.symbol_open_exposure`, `risk/services.py:RiskGuardService.asset_class_open_exposure`

- reduced_notional = (limite % x equity) - exposition existante, borné à 0 minimum
- Si reduced_notional <= 0, le REDUCE devient un blocage SOFT avec decision forcée à REJECT (codes SYMBOL_EXPOSURE_MAX / ASSET_CLASS_EXPOSURE_MAX)
- L'exposition classe d'actifs ne bloque pas en PAPER/DEMO (avertissement seulement), l'exposition symbole bloque dans tous les modes
- Le consommateur DOIT appliquer la réduction : execution/services.py réécrit order.approved_quantity/approved_notional quand decision == REDUCE
- Si equity <= 0 le pourcentage d'exposition est forcé à 0 (pas de division par zéro, pas de blocage)

**Contrôle d'exposition corrélée**
<br>_Bloque l'ouverture si l'exposition cumulée aux actifs fortement corrélés dépasse la limite du profil._
<br>Points d'entrée : `risk/services.py:RiskGuardService.correlated_exposure`, `risk/services.py:RiskGuardService.validate_trade (bloc corrélation)`

- Contrôle exécuté uniquement si profile.block_on_high_correlation est True
- Seuil de corrélation en dur à 0,80 en valeur absolue (paramètre threshold du service, non exposé)
- Les paires sont lues dans portfolio.position_correlations, dans les deux sens (asset_a ou asset_b)
- Si asset est None, l'exposition corrélée vaut 0 (aucun blocage possible sans asset résolu)
- Blocage SOFT avec decision forcée à REJECT

**Décharge de risque (override) sur blocages SOFT**
<br>_Permet à l'utilisateur de forcer l'exécution en franchissant les blocages SOFT, avec motif libre et traçabilité complète._
<br>Points d'entrée : `risk/services.py:RiskGuardService.validate_trade (_soft_block_or_override)`, `trading/views_trade_ideas.py (lecture POST + IP + user-agent)`, `trading/services/trade_idea_execution.py:TradeIdeaExecutionService.execute`, `ai_assistant/services_guards.py`

- L'override ne franchit JAMAIS un blocage HARD (KILL_SWITCH_LIVE, LIVE_TRADING_FORBIDDEN, SHORT_FORBIDDEN) : ces trois-là retournent avant toute branche override
- Chaque code SOFT franchi est empilé dans payload['risk_override']['applied_to'] avec son motif ; la clé risk_override est posée dès que risk_override=True, même si aucun code n'est finalement franchi (l'intention est tracée)
- L'override couvre aussi le PortfolioAdvisorAgent côté vue (action BLOCK_NEW_POSITIONS devient un simple avertissement)
- Le motif est tronqué à 500 caractères, l'IP à 45, le user-agent à 512 ; l'IP est lue dans X-Forwarded-For en priorité puis REMOTE_ADDR
- Même avec override, la vue d'exécution refuse de continuer si un kill switch est actif en LIVE et redirige vers la page de résolution

**Audit immuable des décharges de risque**
<br>_Trace légale de chaque override effectif : utilisateur, portefeuille, trade, codes franchis, motif, IP, user-agent, snapshot du profil._
<br>Points d'entrée : `risk/models.py:RiskOverrideAudit.record`, `risk/services.py:RiskGuardService.validate_trade (hook de fin)`, `risk/admin.py:RiskOverrideAuditAdmin`, `risk/admin.py:_export_override_audit_csv`

- L'enregistrement n'est créé QUE si risk_override=True ET decision finale == APPROVE : un override tenté sur un blocage HARD ne produit aucun audit
- RiskOverrideAudit.record est fail-safe : toute exception est loguée (leotrade.risk.audit) et renvoie None, sans jamais remonter — un échec d'audit ne doit pas bloquer l'exécution du trade
- Le hook complet est lui aussi entouré d'un try/except pour la même raison
- profile_snapshot fige les valeurs clés du profil au moment de l'override, pour reconstituer le contexte si le profil change ensuite
- Admin strictement en lecture seule : has_add/has_change/has_delete_permission renvoient False ; tous les champs sont readonly
- L'export CSV écrit un BOM UTF-8 pour Excel et quote toutes les colonnes

**Kill switch portefeuille — activation manuelle**
<br>_Coupe toute nouvelle entrée sur un portefeuille, avec motif optionnel, audit et notification multicanale._
<br>Points d'entrée : `risk/services_control.py:KillSwitchService.activate`, `risk/services.py:RiskGuardService.trigger_kill_switch`, `risk/api.py:kill_switch_activate`

- Idempotent : si un événement actif existe déjà, renvoie already_active=True sans rien créer ni notifier
- trigger_kill_switch pose un select_for_update sur l'événement actif existant : un seul KillSwitchEvent actif par portefeuille, pas de course concurrente
- L'activation marque simultanément DailyRiskState, WeeklyRiskState ET MonthlyRiskState avec kill_switch_triggered=True et blocked_new_positions=True
- Notification critique multicanale avec dedupe_key=kill_switch:{event_id} : une seule notification par événement
- Pour les codes DAILY_LOSS_LIMIT / WEEKLY_LOSS_LIMIT / MONTHLY_LOSS_LIMIT / HIGH_DRAWDOWN, une notification SUPPLÉMENTAIRE de limite est émise, dédupliquée par jour (loss_limit:{code}:{portfolio_id}:{date})
- Le kill switch ne ferme AUCUNE position ouverte : il bloque seulement les nouvelles entrées (comportement affiché dans l'UI)
- L'audit RiskAuditLog KILL_SWITCH_ACTIVATE est écrit par KillSwitchService, pas par trigger_kill_switch — un déclenchement automatique ne produit donc pas de ligne RiskAuditLog
- La notification KILL_SWITCH_ACTIVATED est émise par trigger_kill_switch, jamais dupliquée par KillSwitchService

**Kill switch portefeuille — désactivation / résolution**
<br>_Lève tous les événements kill switch actifs d'un portefeuille et autorise la reprise du trading._
<br>Points d'entrée : `risk/services_control.py:KillSwitchService.deactivate`, `risk/services.py:RiskGuardService.resolve_kill_switch`, `api/views/risk.py:KillSwitchEventViewSet.resolve_for_portfolio`, `dashboard/views_premium.py:ResolveKillSwitchView`

- Idempotent : aucun événement actif renvoie already_inactive=True sans audit ni notification
- Tous les événements actifs sont résolus en lot avec le même resolved_at
- La notification KILL_SWITCH_DEACTIVATED n'est émise que s'il y avait au moins un événement actif
- La résolution NE remet PAS à zéro les flags kill_switch_triggered / blocked_new_positions des états jour/semaine/mois — ceux-ci seront ré-enforcés par auto_enforce_kill_switch_task si la condition persiste
- Diffusion temps réel kind=kill_switch_resolved sur le groupe dashboard de l'utilisateur

**Kill switch automatique sur franchissement de limite**
<br>_Déclenchement automatique lors de la validation d'un trade quand une limite de perte ou de drawdown est atteinte._
<br>Points d'entrée : `risk/services.py:RiskGuardService.validate_trade`, `risk/services.py:RiskGuardService.trigger_kill_switch`

- Déclenché uniquement si profile.kill_switch_enabled est True
- Codes émis : DAILY_LOSS_LIMIT, WEEKLY_LOSS_LIMIT, MONTHLY_LOSS_LIMIT, MAX_DRAWDOWN
- Le déclenchement a lieu AVANT le blocage SOFT correspondant : même si l'utilisateur franchit le blocage par override, le kill switch est déjà posé
- Le kill switch hebdo/mensuel/drawdown n'est PAS déclenché en PAPER/DEMO ; le kill switch journalier l'est dans tous les modes
- Un drawdown > 100 % est traité comme une anomalie de métrique (forcé à 0), jamais comme un signal de risque

**Enforcement périodique du kill switch**
<br>_Tâche Celery qui parcourt les profils actifs et pose un kill switch quand le drawdown dépasse la limite ou quand un état jour/semaine est déjà en blocage._
<br>Points d'entrée : `risk/tasks.py:auto_enforce_kill_switch_task`

- Ne traite que les RiskProfile is_active=True ET kill_switch_enabled=True
- Priorité des causes : drawdown d'abord (MAX_DRAWDOWN_BREACH), puis état journalier (DAILY_RISK_BREACH), puis hebdomadaire (WEEKLY_RISK_BREACH) — une seule cause par passage
- Idempotence par (portefeuille, profil, reason_code, is_active=True) : un événement équivalent déjà actif est compté en skipped, jamais re-créé
- Crée le KillSwitchEvent DIRECTEMENT (ORM), sans passer par trigger_kill_switch : aucune notification ni broadcast temps réel n'est émis par cette tâche — divergence de comportement à préserver ou à corriger consciemment
- max_drawdown doit être > 0 pour que la règle drawdown s'applique
- Chaque déclenchement est enveloppé dans transaction.atomic et renvoie un compteur checked/triggered/skipped

**Historique des événements kill switch**
<br>_Liste des déclenchements avec raison, horodatage et état résolu/actif._
<br>Points d'entrée : `risk/services_control.py:RiskControlService.kill_switch_events`, `api/views/risk.py:KillSwitchEventViewSet`

- Tri par triggered_at décroissant, limite par défaut 20
- Les champs exposés sont restreints : id, reason_code, reason, is_active, triggered_at, resolved_at (le payload n'est pas renvoyé par /risk/api/)

**États de risque journalier / hebdomadaire / mensuel**
<br>_Agrégats périodiques par portefeuille (PnL réalisé/latent, perte en montant et %, équité d'ouverture et courante, positions ouvertes, flags de blocage)._
<br>Points d'entrée : `risk/services.py:RiskStateService.refresh_daily_state`, `risk/services.py:RiskStateService.refresh_weekly_state`, `risk/services.py:RiskStateService.refresh_monthly_state`, `risk/services_control.py:RiskControlService.states`, `risk/tasks.py:refresh_daily/weekly/monthly_risk_states_task`

- Chaque refresh commence par PortfolioService.refresh_portfolio_metrics : l'état est toujours calculé sur des métriques fraîches
- Unicité stricte : (portfolio, day), (portfolio, week_start), (portfolio, month_start) — get_or_create, jamais de doublon
- Semaine = lundi (date - weekday) ; mois = premier jour du mois ; equity_open = équité du PREMIER snapshot de la période, sinon équité courante
- Garde-fous anti-contamination obligatoires : equity_current <= 0 retombe sur current_balance ; une equity aberrante (> 10x la balance) retombe sur la balance ; equity_open > 10x equity_current est ramenée à equity_current ; equity_open <= 0 est remplacée par equity_current
- Une perte > 100 % est neutralisée à 0 au lieu de bloquer le trading : c'est une anomalie de métrique, pas un signal de risque. Sans ce clamp, le champ Decimal(8,4) déborde (numeric field overflow)
- La correction s'applique aussi aux états DÉJÀ contaminés en base, à chaque refresh
- La perte ne peut pas être négative : drawdown_amount = max(0, equity_open - equity_current)
- Les tâches Celery délèguent intégralement au service — une réimplémentation locale a déjà provoqué des débordements numériques en production
- Les tâches ne traitent que les portefeuilles is_active=True ET broker_account__is_active=True, et isolent chaque portefeuille dans un try/except (un échec n'interrompt pas la boucle)

**Rafraîchissement manuel des états de risque**
<br>_Force le recalcul des états pour un portefeuille à la demande._
<br>Points d'entrée : `api/views/risk.py:RiskUtilityViewSet.refresh_states`

- Le portefeuille est filtré sur request.user : 404 si absent ou non possédé
- Ne rafraîchit QUE daily et weekly ; MonthlyRiskState est oublié

**Historique des décisions du Risk Engine**
<br>_Journal de toutes les décisions (APPROVE/REDUCE/REJECT/BLOCK) avec stake demandé/approuvé, R/R, motif de blocage et payload complet._
<br>Points d'entrée : `risk/services.py:RiskDecisionService.persist_decision`, `risk/services_control.py:RiskControlService.decisions`, `api/views/risk.py:RiskDecisionViewSet`, `dashboard/services.py`

- persist_decision est transaction.atomic et crée TOUJOURS une ligne, y compris pour un BLOCK ou un REJECT : l'historique des refus est une donnée de conformité
- La décision peut être liée à un Signal, une TradeIdea et/ou un Order (toutes nullables, on_delete=SET_NULL : la décision survit à la suppression de ses rattachements)
- execution/services.py réutilise une décision existante liée à l'ordre au lieu d'en recréer une, et la relie à l'ordre si ce n'était pas fait
- Le payload contient les métriques du contrôle (pertes %, drawdown, positions, tier d'instrument, expositions, avertissements PAPER/DEMO et bloc risk_override)

**Façade RiskEngine sur signal**
<br>_Enchaîne profil -> contraintes broker -> sizing -> validation -> persistance pour un objet Signal, et renvoie une décision unique._
<br>Points d'entrée : `risk/engine.py:RiskEngine.evaluate`, `risk/engine.py:RiskEngine._get_constraint`, `risk/engine.py:RiskEngine._compute_requested_stake`, `risk/engine.py:RiskEngineDecision`

- accepted = decision dans {APPROVE, REDUCE} : un REDUCE est accepté, pas rejeté
- Rejets précoces sans persistance de décision : prix d'entrée <= 0, stop loss absent ou <= 0, échec du sizing (reason = « Erreur sizing: ... »)
- Normalisation du sens : LONG/CALL -> BUY, SHORT/PUT -> SELL
- Le symbole vient de l'asset de la stratégie, sinon de signal.symbol, sinon ValueError
- Stake demandé par priorité : stake_amount, amount, requested_stake, capital (premier > 0), sinon heuristique min(10 % du cash, 4x le risque max), avec repli min(cash, 100)
- Contraintes broker en cache Redis 15 min (clé bc:{broker}:{symbol}), invalidée par BrokerConstraintSyncService ; chaîne cache -> DB -> sync réseau, l'échec de sync est silencieux
- evaluate() est transaction.atomic de bout en bout
- Le tier d'instrument est calculé sur le SYMBOLE seul ici (_classify_instrument(symbol=symbol)), sans passer l'asset — moins précis que dans TradeIdeaExecutionService

**Fermeture d'urgence d'une position**
<br>_Soumet un ordre opposé pour clôturer une position ouverte identifiée par son id._
<br>Points d'entrée : `risk/services_control.py:EmergencyPositionService.close_position`, `risk/services_control.py:EmergencyPositionService._close_one`, `risk/api.py:emergency_close_position`

- JAMAIS d'appel broker direct : la fermeture passe exclusivement par ExecutionOrchestrator.create_order puis submit_order avec metadata reduce_only=True et closes_position_id
- Sens inversé : LONG -> SELL, sinon BUY ; prix = current_price sinon average_entry_price
- Refus si le broker_account de la position est absent ou inactif, ou si la quantité calculée est <= 0
- Seules les positions OPEN ou PARTIALLY_CLOSED du portefeuille sont éligibles (filtrage avant tout traitement)
- confirm=true obligatoire ; en mode LIVE, confirm_live=true en plus (double confirmation, réponse requires_double_confirmation)
- Audit RiskAuditLog EMERGENCY_CLOSE_POSITION systématique, succès comme échec (avec error_message)
- Notification POSITION_CLOSED uniquement en cas de succès

**Fermeture d'urgence des positions perdantes**
<br>_Clôture en lot toutes les positions dont le PnL latent est négatif._
<br>Points d'entrée : `risk/services_control.py:EmergencyPositionService.close_all_losing`, `risk/services_control.py:EmergencyPositionService._close_batch`, `risk/api.py:emergency_close_all_losing`

- Sélection stricte : unrealized_pnl < 0 (une position à PnL nul n'est PAS fermée)
- Aucune position éligible renvoie ok=True avec un message explicite, pas une erreur
- ok=True dès qu'au moins un ordre est soumis (ok_count > 0) ; le détail par position est dans results
- confirm=true obligatoire, + confirm_live=true en LIVE
- Un seul RiskAuditLog EMERGENCY_CLOSE_LOSING agrégé pour le lot, avec le compteur ok/total

**Fermeture d'urgence de toutes les positions**
<br>_Action maximale : clôture toutes les positions ouvertes du portefeuille._
<br>Points d'entrée : `risk/services_control.py:EmergencyPositionService.close_all`, `risk/api.py:emergency_close_all`

- Double confirmation TOUJOURS exigée (confirm=true ET confirm_double=true), en PAPER comme en LIVE
- En LIVE s'ajoute une TROISIÈME exigence : confirm_live=true
- Même pipeline ordre opposé + audit EMERGENCY_CLOSE_ALL + notification agrégée que les autres fermetures

**Circuit breaker stratégie (kill switch intelligent)**
<br>_Met automatiquement en pause une stratégie dont les métriques d'apprentissage se dégradent, et conserve l'événement pour audit._
<br>Points d'entrée : `risk/services_circuit_breaker.py:StrategyCircuitBreakerService.evaluate_strategy`, `risk/services_circuit_breaker.py:StrategyCircuitBreakerService.trip`, `risk/services_circuit_breaker.py:StrategyCircuitBreakerService.evaluate_all`, `risk/models.py:StrategyCircuitBreakerEvent`

- Seuils d'échantillon et de qualité : MIN_TRADES=10, MIN_WIN_RATE=0.35, MIN_EXPECTANCY=0.0 — en-dessous de 10 trades, aucune coupure (évite de couper sur 2-3 trades malchanceux)
- Évaluation sur le DERNIER LearningSnapshot de la stratégie uniquement
- Deux causes distinctes : DEGRADED_WIN_RATE (expectancy < 0 ET win rate < 35 %) et NEGATIVE_EXPECTANCY (expectancy < 0 seule) ; l'ordre de test détermine le code enregistré
- Idempotent : une stratégie déjà coupée (événement is_active=True) n'est jamais re-coupée
- Une stratégie is_active=False est ignorée
- trip() est atomique : la stratégie passe is_active=False ET status=PAUSED, puis l'événement est créé
- Notification admins dédupliquée par circuit_breaker:{event_id}
- evaluate_all isole chaque stratégie dans un try/except : une stratégie en erreur n'interrompt pas le balayage

**Résolution / réactivation d'un circuit breaker stratégie**
<br>_Lève les coupures actives d'une stratégie et peut la réactiver après revue._
<br>Points d'entrée : `risk/services_circuit_breaker.py:StrategyCircuitBreakerService.resolve`

- Résout en lot tous les événements actifs (is_active=False, resolved_at, resolved_by)
- La réactivation n'a lieu que si reactivate=True ET qu'au moins un événement a été résolu
- À la réactivation, status ne repasse à PAPER que s'il valait PAUSED (un autre statut est préservé)

**Journal d'audit du module Risk Control**
<br>_Trace horodatée de toute action sensible de contrôle du risque, avec diff avant/après, mode PAPER/LIVE, IP et user-agent._
<br>Points d'entrée : `risk/models.py:RiskAuditLog`, `risk/services_control.py:_audit`, `risk/admin.py:RiskAuditLogAdmin`

- 6 actions tracées : KILL_SWITCH_ACTIVATE, KILL_SWITCH_DEACTIVATE, RISK_SETTINGS_UPDATE, EMERGENCY_CLOSE_POSITION, EMERGENCY_CLOSE_LOSING, EMERGENCY_CLOSE_ALL
- L'écriture est fail-safe : une exception est loguée et renvoie None, elle ne doit jamais interrompre l'action en cours
- summary et error_message sont tronqués à 2000 caractères, user_agent à 300
- Les échecs sont aussi journalisés (success=False + error_message), pas seulement les succès
- Aucune clé API ni secret ne doit transiter dans before/after/payload
- Admin strictement en lecture seule (readonly sur tous les champs, pas d'ajout ni de modification)

**Vue d'ensemble Risk Control (snapshot)**
<br>_Agrégat unique exposant portefeuille, limites du profil, drawdown courant/max, pertes jour/semaine/mois et état du kill switch._
<br>Points d'entrée : `risk/services_control.py:RiskControlService.profile_snapshot`

- L'appel RAFRAÎCHIT les trois états (daily/weekly/monthly) avant de répondre : c'est une lecture à effet de bord, potentiellement coûteuse (3x refresh_portfolio_metrics par appel)
- Le mode affiché vient du broker_account, avec repli PAPER si absent
- Toutes les valeurs monétaires sont sérialisées en chaîne (Decimal), les drawdowns en float

**Garde-fous risque de l'assistant IA**
<br>_Vérifications pré-action de l'assistant (KYC, broker, kill switch, fonds) et aperçu de la décision de risque sans exécution._
<br>Points d'entrée : `ai_assistant/services_guards.py:AssistantRiskValidationService.validate_trade_preparation`, `ai_assistant/services_guards.py:AssistantRiskValidationService.check_kill_switch`, `ai_assistant/services_guards.py:AssistantRiskValidationService.risk_preview`

- Un blocage est une RÉPONSE structurée (ok/code/message), jamais une exception remontée à l'assistant
- Ordre du pipeline : broker -> KYC (LIVE seulement) -> kill switch -> fonds ; le premier échec arrête la chaîne
- KYC approuvé obligatoire pour toute action LIVE
- risk_preview appelle validate_trade SANS override et renvoie decision, block_code et block_severity ; toute exception renvoie decision=ERROR au lieu de propager
- check_kill_switch est enveloppé d'un try/except : une panne du module risque n'autorise PAS implicitement le trade, elle renvoie _allow() — comportement permissif à revoir consciemment

**Diffusion temps réel des événements kill switch**
<br>_Pousse l'activation et la résolution du kill switch sur le canal dashboard de l'utilisateur._
<br>Points d'entrée : `risk/services.py:RiskGuardService.trigger_kill_switch`, `risk/services.py:RiskGuardService.resolve_kill_switch`, `core/realtime.py:RealtimeBroadcastService.broadcast_dashboard_update`

- Deux kinds de payload : kill_switch_triggered (portfolio_id, reason_code, reason) et kill_switch_resolved (portfolio_id, resolved_count)
- Le payload porte toujours un champ version (REALTIME_PROTOCOL_VERSION) permettant aux clients d'ignorer un schéma trop récent
- L'absence de channel layer est loguée et renvoie False : jamais d'exception, une diffusion ratée ne doit pas annuler le kill switch
- auto_enforce_kill_switch_task ne passe PAS par trigger_kill_switch : aucun broadcast n'est émis sur ce chemin

</details>

<details><summary>Pièges de migration repérés</summary>

- L'ORDRE des contrôles de validate_trade porte de la logique métier implicite : les blocs 7/8/8bis/9 déclenchent le kill switch EN EFFET DE BORD avant de rendre leur blocage. Tout refactoring en liste de validateurs indépendants, ou tout retour anticipé inséré avant eux (notamment le bloc 9bis classe d'instrument), supprime silencieusement la protection la plus forte du système.
- La distinction HARD / SOFT n'existe que dans deux constantes et des littéraux de chaîne (block_severity, HARD_BLOCK_CODES) et n'est lue nulle part côté API publique. Si elle n'est pas portée explicitement dans le contrat REST (block_code + block_severity), l'UI React/Flutter ne saura pas distinguer un blocage franchissable d'un blocage absolu, et pourra proposer une décharge sur un kill switch LIVE.
- Toute la fonctionnalité de décharge de risque (override) n'existe qu'en formulaire Django POST dans templates/trading/trade_idea_detail.html, avec redirect et django.messages. Aucun endpoint ne l'accepte. C'est la fonctionnalité la plus susceptible d'être perdue lors de la refonte, alors qu'elle conditionne l'audit légal (RiskOverrideAudit).
- api/serializers/risk.py:RiskProfileSerializer liste ses champs en dur et n'a pas suivi les migrations 0005 et 0007 : max_monthly_loss, preservation_mode, allow_volatile_instruments et allow_speculative_instruments sont invisibles de l'API DRF. Un client qui édite un profil via ce serializer n'a aucun moyen de voir ni modifier la politique Capital Preservation First.
- MonthlyRiskState n'a ni serializer ni viewset DRF, et RiskUtilityViewSet.refresh_states ne rafraîchit que daily et weekly : l'état mensuel est structurellement moins bien servi que les deux autres alors qu'il déclenche un kill switch (MONTHLY_LOSS_LIMIT).
- execution/tasks.py contient des réimplémentations concurrentes et divergentes de refresh_daily_risk_states_task, refresh_weekly_risk_states_task et auto_enforce_kill_switch_task. Elles ne sont pas planifiées dans Celery beat mais restent importables et appelables, et ne filtrent pas sur broker_account__is_active. Risque de double exécution et de régression si quelqu'un les planifie.
- auto_enforce_kill_switch_task crée les KillSwitchEvent directement en ORM au lieu d'appeler trigger_kill_switch : pas de notification, pas de broadcast temps réel, pas de marquage des états mensuels. Un kill switch posé par Celery est donc silencieux pour l'utilisateur — divergence de comportement à trancher explicitement avant migration.
- api/permissions.py:IsOwner ne définit que has_object_permission ; has_permission hérite de BasePermission et renvoie True. Les viewsets risque (RiskProfileViewSet, etc.) ne déclarent pas IsAuthenticated : la protection ne tient que par le filtrage get_queryset sur request.user, qui lèvera une erreur plutôt qu'un 401/403 propre pour un anonyme. À corriger dans la refonte (IsAuthenticated + IsOwner).
- RiskControlService.profile_snapshot rafraîchit les trois états de risque (donc trois PortfolioService.refresh_portfolio_metrics) à chaque appel. C'est le endpoint de la page d'accueil Risk Control et de la page actions d'urgence. En polling mobile, le coût est prohibitif : il faut séparer lecture et rafraîchissement.
- validate_trade mélange lecture et écriture : il répare le portefeuille et les états en base (auto_repaired), persiste des audits et déclenche des kill switchs. Un dry-run exposé en API héritera de ces effets de bord s'il n'est pas explicitement neutralisé, et un simple aperçu pourrait couper le trading de l'utilisateur.
- Le circuit breaker stratégie n'a aucune surface : StrategyCircuitBreakerEvent n'est pas enregistré dans risk/admin.py, n'a pas de serializer et resolve() n'est appelable que depuis les tests. Les stratégies coupées automatiquement ne peuvent être réactivées par aucun chemin applicatif existant.
- Dans PositionSizingService, les contraintes métier sont transportées par des ValueError dont le TEXTE est affiché à l'utilisateur et parsé par TradeIdeaExecutionService (recherche de 'minimum broker' / 'inférieure au minimum' dans le message). Un simple reformulage de message casse le branchement d'erreur. À convertir en exceptions typées avec code machine.
- risk/services.py définit trois fois la méthode is_paper_or_demo sur RiskGuardService (une staticmethod puis deux classmethods) : seule la dernière compte. Code mort dangereux à ne pas recopier tel quel.
- risk/services.py contient un bloc mort sur le levier ('if _d(profile.max_leverage) > 0 and ... : pass') : max_leverage est stocké, éditable et exposé mais N'EST JAMAIS APPLIQUÉ. Ne pas présenter cette limite comme fonctionnelle dans la nouvelle UI sans l'implémenter.
- risk/serializers.py (RiskProfileSerializer / RiskDecisionSerializer en fields='__all__') n'est importé nulle part : doublon mort de api/serializers/risk.py. risk/forms.py contient un PortfolioForm sans rapport avec le domaine et inutilisé. risk/models.py conserve ~70 lignes d'anciens modèles commentés.
- Le seuil de corrélation 0,80 et les seuils du circuit breaker (10 trades / 35 % / expectancy 0) sont codés en dur dans les services, hors profil de risque : ils ne sont ni visibles ni configurables, et seront invisibles dans la matrice si on se fie aux seuls champs du modèle.
- Le comportement PAPER/DEMO est une seconde grille de règles implicite : six contrôles deviennent de simples avertissements déposés dans payload, et la perte journalière reste bloquante alors que l'hebdo et le mensuel ne le sont pas. Cette asymétrie n'est documentée nulle part ailleurs que dans le corps de validate_trade.
- Le cas Deriv écrase approved_notional et approved_quantity avec requested_stake au milieu de validate_trade, change le champ d'exposition (margin_used au lieu d'exposure_value), exclut les positions sans broker_position_id du comptage et désactive l'exigence de stop loss. Quatre règles spécifiques enfouies dans le flux principal.

</details>

---

### ai

`44 fonctionnalités` — API : **14 prêtes, 15 partielles, 15 à exposer**

**Modèles** : `AssistantConversation`, `AssistantMessage`, `AssistantConversationParticipant`, `AssistantAttachment`, `AssistantAction`, `AssistantActionRequest`, `AIUserQuota`, `AIQuotaPayment`, `AIDecisionLog`, `MarketScanRun`, `MarketOpportunity`, `TradeRecommendation`, `AIModelRegistry`, `AIInferenceLog`, `DecisionAudit`, `TradeIdea`, `TradeIdeaFeedback`, `TradeIdeaReview`, `AgentRun`, `MarketRegimeSnapshot`, `PortfolioAdvice`, `MarketRegimeState`, `RiskState`, `RiskPolicy`, `ConfidenceAssessment`, `LearningSnapshot`, `ReinforcementEvent`, `StrategyPrediction`, `Signal`, `Strategy`

**Tâches Celery** : `ai_assistant.tasks.mark_stale_partials_task (beat */10min)`, `ai_engine.tasks.advise_open_trade_ideas_task (beat */3min)`, `ai_engine.tasks.evaluate_predictions_task (beat */10min)`, `trading.tasks_ai.expire_market_opportunities_task (beat */1min)`, `trading.tasks_ai.expire_trade_recommendations_task (beat */1min)`, `trading.tasks_ai.generate_ai_recommendations_for_portfolio_task (à la demande via API)`, `trading.tasks_ai.generate_ai_recommendations_for_all_portfolios_task (beat */5min)`, `trading.tasks.scan_market_1m_task (beat */1min — génère en timeframe 5m)`, `trading.tasks.scan_market_5m_task (beat */5min — génère en timeframe 15m)`, `trading.tasks.run_ai_market_cycle_1m (beat */1min)`, `trading.tasks.run_ai_market_cycle_5m (beat */5min)`, `trading.tasks.expire_trade_ideas_task (beat */1min)`, `trading.tasks.expire_old_trade_ideas (beat */1min — doublon fonctionnel)`, `trading.tasks.learn_from_trade_ideas_task (beat */5min)`, `trading.tasks.refresh_portfolio_advice (beat */5min)`, `trading.tasks.run_hedge_fund_generation_cycle (beat */5min)`, `trading.tasks.run_hedge_fund_execution_cycle (beat */5min)`, `trading.tasks.run_learning_refresh_cycle (beat */15min)`

**Canaux WebSocket** : `ws/assistant/chat/ → ai_assistant.consumers.AssistantConsumer (conversation résolue par contexte)`, `ws/assistant/conversation/<conversation_id>/ → AssistantConsumer (conversation épinglée)`, `groupe channel-layer assistant_conv_<conversation_id> → diffusion thinking/start/chunk/done de la génération détachée`, `ws/ai/radar/ → trading.consumers_ai.AIRadarConsumer`, `groupe channel-layer user_ai_<user_id> → RealtimeBroadcastService.broadcast_ai_update (event_type 'ai.update')`, `ws/dashboard/live/ → trading.consumers.DashboardConsumer (reçoit kind='recommendation_approved' via broadcast_dashboard_update)`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Chat IA temps réel en streaming** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint REST de chat streaming : seul le WebSocket produit du dialogue libre. /assistant/api/command/ ne couvre que les intents outillés et renvoie explicitement « utilise le chat WebSocket pour le dialogue libre » pour GENERAL_CHAT. Il faut soit un SSE/REST streaming, soit documenter le WS comme contrat officiel Flutter (auth JWT sur le scope WS à valider). |
| **Génération IA détachée du WebSocket** | ❌ | WEB/MOBILE | ⚡ | Mécanisme purement WS/asyncio. Pour Flutter il faut un endpoint de reprise d'état (polling du message PARTIAL) ou le WS ; aujourd'hui seul GET /assistant/api/conversations/<id>/messages/ permet de récupérer la réponse a posteriori. |
| **Reprise des générations interrompues** | ❌ | WEB/MOBILE |  | Le statut (SAVED/PARTIAL/FAILED) et error_message sont exposés par AssistantMessageSerializer ; aucun endpoint ne déclenche la tâche à la demande (non nécessaire). |
| **Conversations contextuelles persistantes** | ✅ | WEB/MOBILE | ⚡ | — |
| **Centre des conversations (liste, recherche, archivage, suppression)** | ✅ | WEB/MOBILE |  | — |
| **Historique global des messages IA** | ✅ | WEB/MOBILE |  | — |
| **Analytics d'usage de l'assistant IA** | ✅ | WEB |  | — |
| **Snapshot de contexte live injecté dans le prompt** | 🟡 | WEB/MOBILE |  | Le snapshot n'est lisible qu'a posteriori via le champ payload du message. Aucun endpoint ne permet de récupérer le contexte live courant pour l'afficher côté client (bandeau portefeuille / kill switch) sans ouvrir le WS. |
| **Garde-fous anti-hallucination du prompt assistant** | ❌ | WEB/MOBILE |  | Règles portées par une constante Python et par le post-traitement serveur. Aucun endpoint ne les expose ; à conserver strictement côté backend lors de la refonte (ne jamais déporter le parsing d'actions dans le client React/Flutter). |
| **Moteur d'intentions déterministe** | ✅ | WEB/MOBILE |  | — |
| **Registre d'outils backend de l'assistant** | ✅ | WEB/MOBILE |  | — |
| **Outils de lecture : opportunités, explication, portefeuille, risque** | ✅ | WEB/MOBILE |  | — |
| **Actions confirmables de l'assistant (AssistantActionRequest)** | ✅ | WEB/MOBILE | ⚡ | — |
| **Garde-fous pré-action et aperçu Risk Engine** | 🟡 | WEB/MOBILE |  | Les codes de blocage (KYC_REQUIRED, NO_BROKER, BROKER_INACTIVE, BROKER_ERROR, KILL_SWITCH_ACTIVE, INVALID_AMOUNT, INSUFFICIENT_FUNDS) ne sont renvoyés que dans data.block_code des réponses d'outil. Il manque un endpoint de pré-validation dédié (POST /ai/trade-preview) pour que React/Flutter affichent le blocage AVANT la saisie du montant. |
| **Exécution des actions confirmées via les services backend** | ✅ | WEB/MOBILE |  | — |
| **Commande en langage naturel hors WebSocket** | ✅ | MOBILE |  | — |
| **Actions inline proposées par le LLM (AssistantAction)** | 🟡 | WEB/MOBILE | ⚡ | Les actions sont lues via les serializers de message, mais confirm/reject/pending ne sont exposés que par des vues Django JsonResponse hors DRF (pas dans /assistant/api/) ET sont cassés (filtre message__session__user). Il faut les réimplémenter en DRF avec le bon lookup message__conversation__user. |
| **Quota d'utilisation de l'IA par utilisateur** | 🟡 | WEB/MOBILE | ⚡ | GET /assistant/quota/ est une vue Django hors DRF (pas de pagination/auth JWT garantie) et il n'existe AUCUN endpoint REST de paiement : pay_with_wallet et create_paystack_session ne sont joignables que par messages WebSocket (quota_pay_wallet / quota_pay_stripe). Pour Flutter il faut exposer POST /api/v1/ai/quota/ et POST /api/v1/ai/quota/checkout/. |
| **Paiement du quota IA par portefeuille LeoTrade** | ❌ | WEB/MOBILE | ⚡ | Uniquement accessible par WebSocket. Il faut un POST REST dédié (ex. /api/v1/ai/quota/pay-wallet/) renvoyant le quota mis à jour, le motif d'échec et le flag insufficient_funds. |
| **Paiement du quota IA par passerelle externe (Paystack / Stripe)** | 🟡 | WEB/MOBILE | ⚡ | Le webhook est un endpoint serveur-à-serveur correct, mais l'initialisation de session n'est accessible qu'en WebSocket et les retours sont des redirections HTML vers /dashboard/. Pour mobile il faut un POST REST renvoyant l'URL de checkout et un deep link de retour. |
| **Panel IA front et explication contextuelle d'opportunité** | ❌ | WEB/MOBILE | ⚡ | Entièrement en templates Django + JS vanilla global (window.LeoAssistant) couplé au DOM par identifiants. À reconstruire intégralement en composant React partagé et en widget Flutter ; le contrat WS est la seule partie réutilisable. |
| **Orchestrateur multi-provider d'avis IA (AITradeAdvisor)** | 🟡 | WEB/MOBILE |  | Exposé uniquement par une vue Django JsonResponse (/ai/advise/trade-idea/<id>/) hors DRF, sans serializer ni schéma OpenAPI. À porter en DRF sous /api/v1/. |
| **Providers IA (Claude, DeepSeek, Ollama, Heuristic)** | ❌ | — |  | Couche interne, non exposée et qui ne doit pas l'être. Seul le champ is_fallback est remonté au front — ni cost_usd, ni model_name complet, ni latency_ms. |
| **Avis IA à la demande sur une trade idea** | 🟡 | WEB/MOBILE |  | Vue Django login_required renvoyant un JsonResponse, hors DRF et hors /api/v1/ : pas d'authentification JWT, pas de serializer, pas de schéma OpenAPI. Le 403 est construit en enveloppant le contenu d'un JsonResponse dans un HttpResponseForbidden (Content-Type incorrect). |
| **Journal des décisions IA (AIDecisionLog)** | 🟡 | WEB/MOBILE |  | Vue Django JsonResponse non paginée et plafonnée à 50 sans filtre ni tri. À porter en ViewSet DRF paginé avec filtres (symbole, décision, provider, période). |
| **Avis IA périodique sur les trade ideas ouvertes** | ❌ | — |  | Tâche de fond sans déclencheur ni endpoint de supervision. Pour le front il faudrait au minimum exposer l'état du dernier passage (horodatage, compteurs ok/skipped/err). |
| **Centre de performance IA** | 🟡 | WEB/MOBILE |  | Vue Django JsonResponse hors DRF. Note : ?scope=platform donne accès aux statistiques de TOUTE la plateforme à n'importe quel utilisateur connecté (aucun contrôle is_staff, contrairement à /assistant/api/analytics/). |
| **Évaluation prévision vs réalité des prédictions de stratégie** | 🟡 | WEB |  | Accessible seulement en sous-bloc de /ai/performance/, non paginé et sans filtre par stratégie (le paramètre strategy du service n'est pas exposé par la vue). |
| **Scan de marché et calcul de features techniques** | ❌ | — |  | Aucun endpoint n'expose les MarketScanRun de ce scanner ni ne permet de déclencher un scan. (Le ViewSet /api/v1/scan-runs/ cible le MÊME modèle mais filtre sur des FK user/portfolio/broker_account que MarketScanRun ne possède pas — voir risques.) |
| **Scoring multi-facteurs des opportunités** | 🟡 | WEB/MOBILE |  | Les scores sont lisibles via les serializers de MarketOpportunity/TradeIdea, mais le détail explicatif (poids du régime, patterns, side_confidence, pattern_boost, feedback_multiplier) n'est accessible que dans les JSON bruts ai_payload/feature_snapshot, sans endpoint d'explicabilité dédié. |
| **Génération de trade ideas** | 🟡 | WEB/MOBILE |  | Les idées produites ne sont lisibles que par les vues Django (/trading/ideas/, live-feed JSON) : AUCUN ViewSet DRF ne sert TradeIdea. Il manque /api/v1/trade-ideas/ (liste filtrée/paginée, détail, approve, reject, execute) et un endpoint de déclenchement de scan. |
| **Cycle d'intelligence orchestré (régime + revue d'idées)** | ❌ | WEB |  | Ni AgentRun, ni TradeIdeaReview, ni MarketRegimeSnapshot ne sont exposés en API. Le résultat de la revue (decision, adjusted_score, reasoning, priority) n'est visible qu'en template et dans le live-feed (has_review / review_decision). |
| **Agent conseiller de portefeuille** | ❌ | WEB/MOBILE |  | Aucun endpoint n'expose PortfolioAdvice ni l'action recommandée. Le front ne peut pas afficher « nouvelles positions bloquées par l'agent » avant la soumission du formulaire. |
| **Opportunités de marché (MarketOpportunity) et expiration** | 🟡 | WEB/MOBILE |  | Les ViewSets sont en lecture seule et leur filtrage par utilisateur repose sur un essai successif de FK (user, portfolio__user, scan_run__user…) dans un try/except : MarketOpportunity et MarketScanRun ne possédant AUCUN de ces champs, le filtre ne s'applique pas comme prévu — il faut un cloisonnement explicite avant exposition. |
| **Recommandations IA de trade (TradeRecommendation)** | ✅ | WEB/MOBILE | ⚡ | — |
| **Approbation, rejet et exécution d'une recommandation IA** | ✅ | WEB/MOBILE | ⚡ | — |
| **Registre de modèles IA et logs d'inférence** | ✅ | WEB |  | — |
| **Audit de décision de bout en bout (DecisionAudit)** | ✅ | WEB |  | — |
| **AI Radar temps réel** | 🟡 | WEB/MOBILE | ⚡ | Le flux WS est réutilisable, mais l'affichage passe par un fragment HTML Django (AIPartialView) ; CockpitDataView renvoie du JSON mais n'est pas sous /api/v1/ et n'est pas versionné. |
| **Liste, détail et live feed des trade ideas** | ❌ | WEB/MOBILE |  | Tout est rendu en templates Django ; le live feed est un JsonResponse ad hoc hors DRF, non paginé, sans serializer ni schéma. Il manque un ViewSet /api/v1/trade-ideas/ exposant idée + contexte marché + décision IA + aperçus broker. |
| **Approbation, rejet et auto-trading d'une trade idea** | ❌ | WEB/MOBILE |  | Vues Django POST + redirect + django.contrib.messages, totalement inadaptées à un client React/Flutter. À porter en actions DRF renvoyant du JSON (statut, ordre créé, code de blocage, flag override_required, flag kill_switch_hard_block). |
| **Moteur hedge fund : cycles de génération et d'exécution autonomes** | ❌ | WEB/MOBILE |  | Aucune API : ni ConfidenceAssessment, ni RiskState, ni le déclenchement/supervision des cycles. L'utilisateur ne dispose d'aucun moyen de consulter ou d'interrompre le pilote automatique depuis un client. |
| **Boucle d'apprentissage et renforcement** | 🟡 | WEB |  | Deux endpoints AJAX Django (JsonResponse, non paginés, hors /api/v1/) et des pages en templates. learning_monitor_api ne filtre pas par utilisateur. Il manque des ViewSets DRF pour LearningSnapshot, ReinforcementEvent et RiskState. |
| **Tableau de bord hedge fund IA** | ❌ | WEB |  | Page template uniquement. À reconstruire en dashboard React alimenté par une API d'agrégats — en corrigeant au passage l'absence de cloisonnement par utilisateur sur les statistiques et les listes d'idées. |

<details><summary>Règles métier invariantes à préserver</summary>

**Chat IA temps réel en streaming**
<br>_Conversation libre avec « LeoTrade AI » via WebSocket : le texte arrive token par token depuis DeepSeek puis Claude en secours, avec fallback heuristique diagnostique si les deux échouent._
<br>Points d'entrée : `backend/ai_assistant/consumers.py:AssistantConsumer._handle_chat`, `backend/ai_assistant/services.py:AssistantStreamService.stream`, `backend/ai_assistant/services.py:AssistantStreamService._stream_deepseek`, `backend/ai_assistant/services.py:AssistantStreamService._stream_claude`, `backend/ai_assistant/services.py:AssistantStreamService._heuristic_response`

- Chaîne de providers stricte : AI_PRIMARY_PROVIDER puis AI_SECONDARY_PROVIDER, puis heuristique — le heuristique n'est JAMAIS silencieux : il affiche le diagnostic réel de chaque échec (401 clé invalide, 402 solde, 429 quota, SDK absent).
- Le message USER est persisté AVANT tout appel LLM (status SAVED) et un accusé {type:'user_saved'} est renvoyé immédiatement.
- Fenêtre d'historique envoyée au LLM = MAX_HISTORY_TURNS(10) × 2 messages, messages vides exclus.
- Le dernier message USER de l'historique est remplacé par la version enrichie du contexte live — jamais dupliqué.
- Un utilisateur anonyme est fermé avec le code 4401.

**Génération IA détachée du WebSocket**
<br>_La génération tourne dans une tâche asyncio indépendante de la connexion : fermer la page n'interrompt pas la réponse, qui est diffusée au groupe channel-layer de la conversation._
<br>Points d'entrée : `backend/ai_assistant/services_generation.py:AssistantGenerationService.launch`, `backend/ai_assistant/services_generation.py:AssistantGenerationService._run`, `backend/ai_assistant/services_generation.py:conversation_group`, `backend/ai_assistant/consumers.py:AssistantConsumer.assistant_stream`

- disconnect() ne coupe JAMAIS la génération : il quitte seulement le groupe channel-layer.
- Anti-duplication par un set _running en mémoire de process : un même message_id ne peut pas lancer deux générations dans le même worker.
- Persistance progressive : flush en base seulement quand les DEUX seuils sont atteints (≥0,8 s ET ≥400 caractères depuis le dernier flush).
- Le broadcast temps réel est best-effort : un échec de channel layer est loggué en warning et n'interrompt pas la génération — « la vérité est en base ».
- Fin normale → status SAVED + consommation de quota ; échec du stream → status FAILED, contenu partiel CONSERVÉ avec la note « réponse partielle conservée », et AUCUNE consommation de quota.
- Crash interne → _mark_failed + événement done avec status FAILED (jamais de silence côté client).

**Reprise des générations interrompues**
<br>_Les messages restés PARTIAL après un redémarrage serveur basculent en FAILED au bout de 10 minutes, en conservant le texte déjà généré._
<br>Points d'entrée : `backend/ai_assistant/tasks.py:mark_stale_partials_task`

- STALE_PARTIAL_MINUTES = 10 : seuls les messages ASSISTANT en PARTIAL non mis à jour depuis 10 min sont basculés.
- Le contenu partiel n'est JAMAIS effacé — seul le statut change, avec error_message='generation_interrupted_by_restart'.
- Le statut doit rester honnête : on ne fait jamais passer un partiel pour une réponse complète.

**Conversations contextuelles persistantes**
<br>_Une conversation indépendante par objet métier (trade idea, position, ordre, portefeuille, broker, signal, opportunité) plus dashboard et assistant général ; la résolution se fait depuis le contexte envoyé par le client._
<br>Points d'entrée : `backend/ai_assistant/services_conversation.py:ConversationService.resolve_context`, `backend/ai_assistant/services_conversation.py:ConversationService.get_or_create_for_context`, `backend/ai_assistant/services_conversation.py:ConversationService.get_owned`, `backend/ai_assistant/services_conversation.py:ConversationService.start_new`, `backend/ai_assistant/consumers.py:AssistantConsumer._switch_to_context`

- Ordre de résolution figé (_CONTEXT_ID_KEYS) : trade_idea_id > idea_id > position_id > order_id > portfolio_id > broker_account_id > broker_id > signal_id > opportunity_id > recommendation_id ; sinon page=dashboard → DASHBOARD ; sinon GENERAL.
- Une seule conversation ACTIVE et NON ARCHIVÉE par couple (user, context_type, context_id) — la plus récemment mise à jour est reprise.
- Contrôle d'ownership STRICT : get_owned filtre toujours sur user ; une conversation épinglée inconnue ferme le WS en 4404.
- start_new archive TOUTES les conversations non archivées du contexte avant d'en créer une neuve.
- À la création, un AssistantConversationParticipant OWNER est créé et le portefeuille par défaut (is_active, -is_default) est attaché.
- Le titre est auto-généré depuis le premier message (80 car. max + « … ») et n'est jamais réécrit s'il existe déjà.
- Chaque message de chat re-résout le contexte et bascule de conversation si nécessaire (bascule implicite, transparente pour l'utilisateur).

**Centre des conversations (liste, recherche, archivage, suppression)**
<br>_Interface type ChatGPT listant toutes les conversations de l'utilisateur, avec recherche plein texte, filtre par contexte, archivage/désarchivage, suppression définitive et reprise._
<br>Points d'entrée : `backend/ai_assistant/api.py:AssistantConversationViewSet`, `backend/ai_assistant/views.py:ConversationCenterView`, `backend/ai_assistant/serializers_api.py:AssistantConversationSerializer`, `backend/templates/assistant/conversations.html`

- Le queryset est TOUJOURS filtré sur request.user — aucune fuite inter-utilisateurs.
- Le filtre archived ne s'applique qu'à l'action list : le détail, la suppression et archive/désarchive doivent atteindre toutes les conversations (y compris archivées). archived=all désactive le filtre.
- Méthodes HTTP volontairement limitées à get/post/delete : pas de PUT/PATCH (on ne modifie pas une conversation hors archivage/titre).
- archive/ est un TOGGLE (inverse la valeur), pas un setter.
- La suppression est définitive (cascade sur messages, actions, action requests).
- La recherche ?q= porte sur title OU contenu des messages, avec .distinct() obligatoire (jointure multiple).
- Pagination : 20 conversations/page (max 100), 50 messages/page (max 200).

**Historique global des messages IA**
<br>_Fil des messages récents de l'utilisateur tous contextes confondus, avec recherche sur le contenu et rattachement à la conversation d'origine._
<br>Points d'entrée : `backend/ai_assistant/api.py:assistant_history`

- Filtré sur conversation__user=request.user.
- Chaque entrée est enrichie de conversation_id et conversation_title pour permettre la reprise directe.
- Tri antéchronologique, pagination MessagePagination (50/page).

**Analytics d'usage de l'assistant IA**
<br>_Statistiques réelles : nombre de conversations, messages, tokens in/out, coût USD, taux d'erreur, latence moyenne, répartition par modèle._
<br>Points d'entrée : `backend/ai_assistant/api.py:assistant_analytics`, `backend/ai_assistant/services_conversation.py:ConversationService.analytics`, `backend/ai_assistant/admin.py:AssistantMessageAdmin.changelist_view`

- scope=global n'est honoré QUE si request.user.is_staff ; sinon on retombe silencieusement sur les stats personnelles.
- error_rate et avg_latency_ms valent None (et non 0) quand il n'y a pas d'échantillon — pas de faux zéro.
- La latence moyenne exclut les messages à latency_ms=0 (jamais mesurés).
- per_model exclut les messages sans model_name, limité au top 10.

**Snapshot de contexte live injecté dans le prompt**
<br>_Avant chaque message, un instantané réel (portefeuille, positions ouvertes, état de risque, kill switch, signaux IA récents, opportunité analysée) est construit et sérialisé dans le prompt._
<br>Points d'entrée : `backend/ai_assistant/services.py:AssistantContextService.build`, `backend/ai_assistant/services.py:_format_context_for_prompt`

- Chaque bloc (portefeuille, positions, risque, signaux, opportunité) est protégé par try/except : une source indisponible ne doit JAMAIS bloquer la conversation — elle est simplement absente du snapshot.
- Positions limitées aux statuts OPEN/PARTIALLY_CLOSED, 10 max ; signaux IA limités aux TradeRecommendation PENDING/APPROVED, 5 max.
- Le portefeuille retenu est le premier actif trié par -is_default.
- Le snapshot est persisté dans AssistantMessage.context_snapshot : il doit rester reproductible pour l'audit.
- Le prompt système interdit explicitement de dire « je n'ai pas accès » : le snapshot fait foi.

**Garde-fous anti-hallucination du prompt assistant**
<br>_Prompt système figé décrivant l'architecture réelle de la plateforme, avec liste blanche de routes, règles de refus explicites et format d'action structuré._
<br>Points d'entrée : `backend/ai_assistant/services.py:ASSISTANT_SYSTEM_PROMPT`, `backend/ai_assistant/services.py:extract_actions`, `backend/ai_assistant/services_generation.py:AssistantGenerationService._finalize`

- Règle absolue : ne jamais inventer page, URL, bouton ou fonctionnalité ; ne recommander QUE les routes de la liste blanche vérifiée.
- Si la fonctionnalité demandée n'existe pas, réponse exacte imposée : « Cette fonctionnalité n'est pas encore disponible. Je peux proposer son intégration. »
- Le kill switch ne se contourne JAMAIS par instruction IA : expliquer la cause et orienter vers /risk/kill-switch/ (action auditée).
- Ne jamais promettre une fermeture « magique » : les clôtures passent par /risk/emergency-actions/ (ordre opposé, confirmation, audit, notification).
- Les blocs <<<ACTION>>>…<<<END_ACTION>>> sont parsés en JSON strict ; un bloc invalide est silencieusement ignoré et retiré du texte affiché.
- Un type d'action inconnu est RABATTU sur INFO — le LLM ne peut pas inventer un type d'action exécutable.
- Le prompt mentionne explicitement que le champ de risque s'appelle max_daily_loss et PAS max_daily_drawdown.

**Moteur d'intentions déterministe**
<br>_Détection par règles et regex FR/EN de 18 intentions (confirmer, annuler, kill switch, fermer/réduire position, annuler ordre, préparer trade, approuver/rejeter idée, scanner, analyser…) avec extraction d'entités (symbole, montant, pourcentage, #ID, mode PAPER/LIVE, périmètre perdantes/toutes)._
<br>Points d'entrée : `backend/ai_assistant/services_intent.py:AssistantIntentService.detect`, `backend/ai_assistant/services_intent.py:_extract_entities`, `backend/ai_assistant/consumers.py:AssistantConsumer._handle_intent`

- INVARIANT CENTRAL : les actions sensibles ne sont JAMAIS décidées par le LLM — la détection est déterministe ; tout texte non reconnu retombe en GENERAL_CHAT et part au LLM.
- L'ordre des règles EST la priorité : confirmation/annulation d'abord, puis kill switch/auto-trading, puis ordres/positions, puis broker/portefeuille, puis cycle de vie des idées, puis recherche d'opportunités, puis analyses.
- Piège explicitement traité : « coupe tout » déclenche le kill switch UNIQUEMENT s'il n'y a aucune mention de « position(s) » — sinon c'est une clôture de positions.
- Confirmation et annulation n'acceptent qu'une correspondance PLEINE (re.fullmatch) sur une liste fermée (oui/ok/go/confirme/valide/1… et non/annule/cancel/stop/2…) : un « oui » noyé dans une phrase ne déclenche rien.
- Normalisation crypto : BTC/ETH/SOL/XRP → paire USDT.
- percent est plafonné à 100 ; mode « réel/reel/live » → LIVE, « demo/paper » → PAPER.

**Registre d'outils backend de l'assistant**
<br>_14 outils internes (4 lecture, 10 action) mappés sur les intents, exécutables depuis le chat ou en REST, avec catalogue introspectable._
<br>Points d'entrée : `backend/ai_assistant/services_tools.py:AssistantToolRegistry.run`, `backend/ai_assistant/services_tools.py:AssistantToolRegistry.for_intent`, `backend/ai_assistant/services_tools.py:AssistantToolRegistry.describe`, `backend/ai_assistant/api.py:assistant_tools`, `backend/ai_assistant/api.py:action_requests`

- Contrat de sortie figé : {ok: bool, reply: markdown, action_request: dict|None, data: dict} — toute refonte doit le préserver.
- Deux familles distinctes : LECTURE = exécution immédiate ; ACTION = JAMAIS d'exécution directe, création obligatoire d'une AssistantActionRequest.
- Une exception d'outil n'est jamais propagée : elle est loggée et transformée en {ok:false, reply:'L'outil a rencontré une erreur…'} — un outil cassé ne doit pas casser la conversation.
- Un outil inconnu renvoie ok=false, pas une 500.
- Résolution d'une idée (_resolve_idea) par ordre strict : #ref_id > symbole parmi NEW/REVIEW/APPROVED > contexte conversationnel TRADE_IDEA > meilleure idée actionnable par -overall_score.

**Outils de lecture : opportunités, explication, portefeuille, risque**
<br>_find_trade_ideas (scan à la demande + top 5), explain_trade_idea (lecture des scores et indicateurs), analyze_portfolio (équité/solde/cash/PnL/drawdown + positions), analyze_risk (pertes jour/semaine/mois vs limites + kill switch)._
<br>Points d'entrée : `backend/ai_assistant/services_tools.py:find_trade_ideas`, `backend/ai_assistant/services_tools.py:explain_trade_idea`, `backend/ai_assistant/services_tools.py:analyze_portfolio`, `backend/ai_assistant/services_tools.py:analyze_risk`

- ZÉRO fake data : si aucune idée fiable n'existe, l'assistant REFUSE de recommander et le dit explicitement (« je préfère ne rien recommander… score ≥ 0,65 »), en mentionnant l'erreur de scan le cas échéant.
- find_trade_ideas lance un scan frais ; si le scan échoue, on retombe sur les idées en base ET on affiche l'erreur de scan — jamais de dégradation silencieuse.
- Seules les idées NEW/REVIEW/APPROVED de l'utilisateur sont listées, triées -overall_score puis -created_at, 5 max.
- analyze_risk rafraîchit réellement les états jour/semaine/mois (RiskStateService.refresh_*) avant de répondre : les chiffres affichés ne sont jamais périmés.
- Les seuils de lecture sont fixes : ≥0,80 fort / ≥0,65 modéré / sinon faible.

**Actions confirmables de l'assistant (AssistantActionRequest)**
<br>_Toute action sensible produit une demande à confirmer explicitement : résumé lisible, aperçu Risk Engine, mode PAPER/LIVE, jeton, TTL, double confirmation en LIVE._
<br>Points d'entrée : `backend/ai_assistant/services_actions.py:AssistantActionService.create_request`, `backend/ai_assistant/services_actions.py:AssistantActionService.latest_pending`, `backend/ai_assistant/services_actions.py:AssistantConfirmationService.confirm`, `backend/ai_assistant/services_actions.py:AssistantConfirmationService.cancel`, `backend/ai_assistant/api.py:action_request_confirm`, `backend/ai_assistant/api.py:action_request_cancel`

- RÈGLE ABSOLUE : l'assistant ne déclenche jamais une action sensible sur un simple texte — il crée une demande, l'utilisateur confirme, puis seulement l'exécution passe par les services backend.
- requires_double_confirmation est positionné UNIQUEMENT quand mode == 'LIVE' ; la 1re confirmation passe le statut à CONFIRMED sans exécuter et renvoie l'avertissement « argent réel », la 2e exécute.
- TTL strict : REQUEST_TTL_MINUTES = 10 ; une demande expirée bascule en EXPIRED au moment de la confirmation et n'est jamais exécutée.
- is_actionable = statut ∈ {WAITING, CONFIRMED} ET non expirée ; tout autre statut renvoie un refus explicite.
- confirmation_token unique (secrets.token_urlsafe(32)) ; la vérification n'est faite que si un token est fourni (la confirmation en session authentifiée s'en passe).
- latest_pending ne remonte que les demandes non expirées de l'utilisateur (optionnellement de la conversation) triées -created_at.
- cancel refuse de toucher une demande déjà EXECUTED ou CANCELLED et garantit « rien n'a été exécuté ».
- Si aucune demande en attente n'existe quand l'utilisateur dit « oui », l'intent N'ÉCHOUE PAS : on rend la main au LLM (le « oui » redevient du dialogue).

**Garde-fous pré-action et aperçu Risk Engine**
<br>_Avant de proposer une préparation de trade : vérification broker, KYC (LIVE), kill switch, cash disponible, puis appel du Risk Engine en mode aperçu (sans exécution)._
<br>Points d'entrée : `backend/ai_assistant/services_guards.py:AssistantRiskValidationService.validate_trade_preparation`, `backend/ai_assistant/services_guards.py:AssistantRiskValidationService.check_kyc`, `backend/ai_assistant/services_guards.py:AssistantRiskValidationService.check_broker`, `backend/ai_assistant/services_guards.py:AssistantRiskValidationService.check_kill_switch`, `backend/ai_assistant/services_guards.py:AssistantRiskValidationService.check_funds`, `backend/ai_assistant/services_guards.py:AssistantRiskValidationService.risk_preview`

- ORDRE DES GARDE-FOUS FIGÉ : broker → KYC → kill switch → fonds. Le premier blocage gagne et détermine le message affiché.
- Un blocage est une RÉPONSE structurée {ok, code, message}, jamais une exception remontée à l'assistant.
- KYC : seules les actions LIVE sont contrôlées ; profil absent ou status != 'APPROVED' → blocage KYC_REQUIRED.
- Broker : absent → NO_BROKER ; is_active=False → BROKER_INACTIVE ; status='ERROR' → BROKER_ERROR avec les 120 premiers caractères de last_connection_error.
- Kill switch actif → blocage KILL_SWITCH_ACTIVE ; une exception pendant la vérification est loggée mais NE débloque PAS silencieusement (elle laisse passer — comportement à durcir).
- Fonds : montant ≤ 0 → INVALID_AMOUNT ; available_cash < montant → INSUFFICIENT_FUNDS avec les deux montants.
- risk_preview est un APERÇU : il appelle RiskGuardService.validate_trade avec approved_quantity=0 et n'exécute rien ; un échec renvoie decision='ERROR' avec la raison tronquée à 300 caractères.
- Si l'aperçu renvoie BLOCK ou REJECT, l'assistant REFUSE de créer la demande d'action (« Je ne préparerai pas cet ordre »).

**Exécution des actions confirmées via les services backend**
<br>_13 exécuteurs : exécuter/préparer une trade idea, approuver/rejeter une idée, annuler un ordre, fermer/réduire une position, synchroniser le portefeuille, tester le broker, activer/désactiver le kill switch, activer/désactiver l'auto-trading._
<br>Points d'entrée : `backend/ai_assistant/services_actions.py:AssistantTradingCommandService.execute`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._exec_execute_trade_idea`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._close_or_reduce`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._exec_cancel_order`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._exec_sync_portfolio`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._exec_test_broker`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._exec_activate_kill_switch`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._exec_disable_auto_trading`

- L'assistant ne parle JAMAIS au broker : tout passe par TradeIdeaExecutionService, ExecutionOrchestrator, BrokerReconciliationService, PortfolioService, RiskGuardService, BrokerConnectionService.
- Le dispatch est nominatif (_exec_<action_type.lower()>) : un action_type non implémenté échoue proprement en FAILED, jamais d'exécution par défaut.
- Fermer/réduire une position = soumettre un ORDRE OPPOSÉ via l'orchestrateur (SELL si LONG, BUY sinon), source='AI_ASSISTED', metadata traçant assistant_action_request_id / closes_position_id / close_fraction.
- La fraction de réduction est bornée à [0,01 ; 1] et la quantité quantizée à 1e-8 ; une quantité nulle est refusée.
- Si TradeIdeaExecutionService ne renvoie pas d'ordre, c'est un blocage Risk Engine : audit final_decision='BLOCKED' avec blocking_reason, ok=false.
- disable_auto_trading repasse TOUTES les idées auto_trade_enabled=True en manuel ; la réactivation est volontairement ÉTROITE : uniquement les idées en statut APPROVED.
- L'activation du kill switch précise que les positions ouvertes ne sont PAS fermées automatiquement.
- Chaque exécution écrit un DecisionAudit et déclenche une notification — mais _notify ET _audit sont enveloppés dans try/except : un échec de notification ou d'audit ne doit JAMAIS faire échouer ni annuler l'action.

**Commande en langage naturel hors WebSocket**
<br>_Endpoint REST qui prend un texte libre, détecte l'intention, exécute l'outil correspondant ou traite la confirmation/annulation en attente._
<br>Points d'entrée : `backend/ai_assistant/api.py:assistant_command`

- Texte vide → 400 explicite.
- conversation_id est résolu via get_owned (ownership strict) ; à défaut, conversation du contexte par défaut.
- CONFIRM/CANCEL sans demande en attente → 400 « Aucune action en attente de confirmation. »
- Un intent GENERAL_CHAT renvoie 200 avec un message dirigeant vers le WebSocket — il ne produit PAS de réponse LLM.
- Prévu explicitement pour Flutter et les intégrations tierces.

**Actions inline proposées par le LLM (AssistantAction)**
<br>_Le LLM peut émettre des cartes d'action typées (DRAFT_ORDER, ADJUST_SL, ADJUST_TP, SUGGEST_SIZE, OPEN_MODAL, INFO) persistées et affichées sous sa réponse, avec boutons confirmer/rejeter._
<br>Points d'entrée : `backend/ai_assistant/services_generation.py:AssistantGenerationService._finalize`, `backend/ai_assistant/views.py:ActionConfirmView`, `backend/ai_assistant/views.py:ActionRejectView`, `backend/ai_assistant/views.py:PendingActionsView`, `backend/ai_assistant/consumers.py:AssistantConsumer._confirm_action`, `backend/ai_assistant/models.py:AssistantAction`

- Seuls les 6 types déclarés dans ACTION_TYPE_CHOICES sont acceptés ; tout autre type est rabattu sur INFO.
- DRAFT_ORDER ne passe AUCUN ordre : la confirmation ne fait que renvoyer {redirect:'draft_order', params} pour pré-remplir un formulaire côté client, puis marque l'action EXECUTED.
- Audit complet par horodatage dédié : confirmed_at, rejected_at, executed_at, result, error_message.
- Seules les actions en statut PROPOSED peuvent être confirmées ou rejetées.
- ATTENTION : ces vues et les handlers WS filtrent sur message__session__user, lookup INVALIDE (le FK s'appelle conversation) — ce chemin lève actuellement une FieldError.

**Quota d'utilisation de l'IA par utilisateur**
<br>_Plans FREE (20 msg), BASIC ($5 / 200), PRO ($20 / 1000), UNLIMITED, avec compteur, pourcentage d'usage, suspension administrative et options d'upgrade._
<br>Points d'entrée : `backend/ai_assistant/services.py:QuotaService.check`, `backend/ai_assistant/services.py:QuotaService.get_or_create`, `backend/ai_assistant/services.py:QuotaService.upgrade_options`, `backend/ai_assistant/models.py:AIUserQuota`, `backend/ai_assistant/views.py:QuotaStatusView`, `backend/ai_assistant/consumers.py:_serialize_quota`

- Le quota est contrôlé AVANT toute chose dans _handle_chat — y compris avant la détection d'intention : un quota épuisé bloque aussi les outils déterministes.
- is_suspended prime sur l'épuisement (reason='suspended') et ne propose AUCUN plan d'upgrade.
- UNLIMITED n'est jamais considéré comme épuisé.
- La consommation (quota.consume()) n'a lieu QUE lorsque la génération LLM a réussi (stream_ok) — ni les échecs, ni les réponses d'outil, ni les confirmations ne décomptent de message.
- top_up remet messages_used à 0, applique la limite du nouveau plan, cumule total_spent_usd et redémarre la période.
- monthly_reset ne remet à zéro QUE le plan FREE.

**Paiement du quota IA par portefeuille LeoTrade**
<br>_Débit direct du wallet plateforme pour activer un plan IA, avec transaction wallet idempotente et activation immédiate._
<br>Points d'entrée : `backend/ai_assistant/services.py:QuotaService.pay_with_wallet`, `backend/ai_assistant/consumers.py:AssistantConsumer._handle_quota_pay_wallet`

- Toute l'opération est @transaction.atomic avec Wallet verrouillé par select_for_update.
- Le débit passe OBLIGATOIREMENT par WalletLedgerService.debit avec un external_event_id idempotent de la forme ai-quota-wallet:<wallet_tx_id>.
- Double vérification de solde : has_sufficient_balance en amont PUIS capture d'InsufficientFundsError du ledger — en cas d'échec la WalletTransaction est marquée FAILED et horodatée.
- L'AIQuotaPayment n'est créé qu'APRÈS un débit réussi, directement en statut COMPLETED, puis quota.top_up(plan).
- Un plan sans prix strictement positif est refusé (« Plan invalide »).
- Wallet (crédit plateforme) et Portfolio (capital de trading) sont strictement indépendants : le capital broker ne peut jamais payer l'abonnement IA.

**Paiement du quota IA par passerelle externe (Paystack / Stripe)**
<br>_Initialisation d'une session de paiement Paystack (défaut Afrique) avec repli Stripe Checkout, pages de retour succès/annulation et webhook Stripe de validation._
<br>Points d'entrée : `backend/ai_assistant/services.py:QuotaService.create_paystack_session`, `backend/ai_assistant/services.py:QuotaService.create_stripe_session`, `backend/ai_assistant/views.py:stripe_webhook`, `backend/ai_assistant/views.py:QuotaSuccessView`, `backend/ai_assistant/views.py:QuotaCancelView`

- Paystack est la passerelle prioritaire ; Stripe n'est utilisé qu'en repli si PAYSTACK_SECRET_KEY est absent. Si aucune des deux n'est configurée → erreur explicite, jamais de faux succès.
- Le webhook Stripe refuse tout traitement si STRIPE_WEBHOOK_SECRET est absent (400) et vérifie la signature.
- Validation croisée STRICTE avant tout crédit : payment_status == 'paid' ET devise == USD ET amount_total/100 == payment.amount_usd ET user_id du metadata == quota.user_id ET plan identique — sinon 400 et log de mismatch.
- Le paiement est verrouillé par select_for_update et ne peut être traité que depuis le statut PENDING (idempotence anti-rejeu du webhook).
- Le webhook est @transaction.atomic : crédit du quota et passage COMPLETED sont indissociables.
- La page de succès ne confirme (quota_ok=1) que si un AIQuotaPayment COMPLETED existe réellement pour cette session ; sinon quota_processing=1.
- La référence Paystack est stockée dans stripe_session_id et l'URL dans stripe_payment_url (réutilisation assumée des champs).

**Panel IA front et explication contextuelle d'opportunité**
<br>_Panneau flottant global (statut connexion, barre de quota, pastilles de contexte, bandeau kill switch, suggestions rapides, modale d'upgrade) et boutons « LeoTrade AI » sur les cartes d'opportunité et les trade ideas._
<br>Points d'entrée : `backend/static/js/leo_assistant.js:explainOpportunity`, `backend/static/js/leo_assistant.js:openConversation`, `backend/templates/assistant/_panel.html`

- Le contexte de page est injecté automatiquement depuis document.body.dataset.leoPage et propagé au serveur (context_update) — la conversation suit la page.
- Reconnexion WebSocket avec backoff exponentiel (2 s → 30 s max).
- Le bandeau kill switch s'affiche à partir du meta.has_kill_switch renvoyé dans l'événement done.
- Pied de panneau rappelant en permanence : « Conseil uniquement · Aucune exécution auto ».
- Saisie bornée à 2000 caractères.

**Orchestrateur multi-provider d'avis IA (AITradeAdvisor)**
<br>_Point d'entrée unique pour obtenir un avis structuré (EXECUTE/PLAN/WATCH/REJECT/ABSTAIN) sur un setup, avec chaîne de providers, bascule automatique et journalisation systématique._
<br>Points d'entrée : `backend/ai_engine/services.py:AITradeAdvisor.advise`, `backend/ai_engine/services.py:AITradeAdvisor.get_provider_chain`, `backend/ai_engine/services.py:AITradeAdvisor._record_decision`, `backend/ai_engine/integrations.py:build_context_from_trade_idea`, `backend/ai_engine/integrations.py:advise_for_trade_idea`

- HeuristicProvider est TOUJOURS en fin de chaîne — filet de sécurité, le système ne peut jamais se retrouver sans réponse.
- AI_FORCE_FALLBACK=True court-circuite tous les LLM (test / économie).
- Un provider qui lève ProviderUnavailable n'arrête PAS la chaîne : on passe au suivant en enregistrant la tentative dans attempt_logs.
- fallback_used est vrai dès que l'index du provider retenu est > 0, et fallback_reason porte la dernière erreur (200 car.).
- TOUTE décision est persistée dans AIDecisionLog, y compris les ABSTAIN de rate limit et d'échec total.
- RGPD / hygiène : prompt_inputs ne stocke JAMAIS user_objective, recent_candles ni recent_outcomes ; aucun secret broker n'est journalisé.
- Un échec de _record_decision est loggué mais ne fait pas échouer l'avis.
- Le provider doit lever ProviderUnavailable plutôt que retourner une décision dégradée silencieusement.

**Providers IA (Claude, DeepSeek, Ollama, Heuristic)**
<br>_Quatre implémentations du contrat BaseAIProvider renvoyant un AIDecision typé avec scénario principal/alternatif, condition d'invalidation, probabilité estimée, tokens et coût._
<br>Points d'entrée : `backend/ai_engine/providers/base.py:BaseAIProvider`, `backend/ai_engine/providers/base.py:AIDecision`, `backend/ai_engine/providers/base.py:MarketContext`, `backend/ai_engine/providers/claude.py:ClaudeProvider`, `backend/ai_engine/providers/deepseek.py:DeepSeekProvider`, `backend/ai_engine/providers/ollama.py:OllamaProvider`, `backend/ai_engine/providers/heuristic.py:HeuristicProvider`

- Aucun provider n'écrit en base : la persistance est la responsabilité exclusive de AITradeAdvisor.
- Sortie JSON STRICTE imposée par le prompt ; une sortie non parsable → ProviderUnavailable → fallback (jamais d'interprétation approximative).
- Sécurité anti-injection de prompt : _sanitize_indicators ne conserve que des valeurs numériques (les booléens sont exclus car sous-classe d'int) et des clés identifiant Python ; régime et direction sont validés par regex.
- Le prompt impose : REJECT si les conditions ne sont pas claires, SL/TP basés sur l'ATR (rarement > 3×ATR), jamais plus que max_risk_per_trade_pct, et une « invalidation » objective et vérifiable.
- HeuristicProvider est toujours disponible, à coût et latence nuls, et renvoie WATCH/confidence 0.3 sur signaux contradictoires.
- Le coût DeepSeek distingue les tokens en cache (input_cache_hit) du prix plein ; Ollama est forcé à cost_usd=0 (local).
- Le client Claude est stocké en threading.local (pas de partage inter-threads).

**Avis IA à la demande sur une trade idea**
<br>_Endpoint POST qui déclenche un nouvel avis IA sur une idée précise et renvoie la décision, la confiance, les niveaux suggérés, les risques et le quota d'appels restant._
<br>Points d'entrée : `backend/ai_engine/views.py:advise_trade_idea_view`, `backend/ai_engine/views.py:_user_owns_trade_idea`, `backend/ai_engine/views.py:_ai_rate_limit_check`

- Vérification d'ownership CRITIQUE avant tout : idea.user, puis idea.portfolio.user, puis idea.broker_account.user — un accès refusé est loggué en warning (fuite de stratégies entre utilisateurs).
- Rate limiting par utilisateur sur fenêtre glissante d'1 h (AI_RATE_LIMIT_PER_HOUR, défaut 30 côté vue) avec en-tête Retry-After sur 429.
- Fail-open assumé : si Redis est indisponible, l'appel est AUTORISÉ et un warning est loggué (on ne bloque pas le trading sur une panne de cache).
- On N'EXPOSE PAS au front cost_usd, model_name complet ni latency_ms — uniquement un booléen is_fallback.
- Si l'idée n'a pas de portefeuille, on retombe sur le portefeuille actif par défaut de l'utilisateur.

**Journal des décisions IA (AIDecisionLog)**
<br>_Audit complet de chaque décision : provider réellement utilisé, fallback, modèle, décision, confiance, R/R, niveaux suggérés, rationale, risques, scénarios, tokens, latence, coût._
<br>Points d'entrée : `backend/ai_engine/models.py:AIDecisionLog`, `backend/ai_engine/views.py:list_decisions_view`, `backend/ai_engine/admin.py:AIDecisionLogAdmin`

- Filtré sur request.user, 50 entrées maximum, antéchronologique.
- La liste publique n'expose ni prompt_inputs, ni raw_response, ni cost_usd, ni tokens — ces champs restent réservés à l'admin et sont en lecture seule.
- Le champ analysis porte primary_scenario / alternative_scenario / invalidation / probability_estimate.

**Avis IA périodique sur les trade ideas ouvertes**
<br>_Tâche Celery qui demande un avis IA pour les idées NEW/REVIEW sans décision et ajuste automatiquement leur statut._
<br>Points d'entrée : `backend/ai_engine/tasks.py:advise_open_trade_ideas_task`

- Verrou Redis singleton (single_run 'lock:ai_advise_trade_ideas', TTL 120 s) : jamais deux exécutions concurrentes.
- AUTO-STATUT : decision='EXECUTE' ET confidence ≥ 0,75 → idée APPROVED ; decision='REJECT' → idée REJECTED. Tous les autres cas laissent le statut inchangé.
- Une idée ayant DÉJÀ un AIDecisionLog est ignorée — en pratique un seul avis par idée pour toute sa vie (le commentaire parle d'une heure mais aucune fenêtre temporelle n'est appliquée).
- TradeIdea n'a pas de FK portfolio : le portefeuille est résolu depuis l'utilisateur de l'idée (actif, -is_default, name) pour que l'IA raisonne avec les vraies contraintes de capital.
- Un échec sur une idée n'interrompt pas la boucle (compteur n_err).
- Plafond max_ideas=50 par exécution.
- Les appels système (user=None) ne sont PAS soumis au rate limit de AITradeAdvisor.

**Centre de performance IA**
<br>_Score de performance global (0-100), taux de réussite, calibration de la confiance, répartition par provider, historique des recommandations avec résultat réel, et précision des prédictions._
<br>Points d'entrée : `backend/ai_engine/views.py:ai_performance_view`, `backend/ai_engine/services_performance.py:AIPerformanceService.summary`, `backend/ai_engine/services_performance.py:AIPerformanceService.recommendation_history`

- Aucune donnée simulée : tout est calculé depuis la base ; les sections sans échantillon renvoient des compteurs à zéro avec sample_size=0 et des métriques à None (jamais un faux 0).
- Décisions « engagées » = EXECUTE et PLAN uniquement ; résultats pris en compte = WIN/LOSS/BREAKEVEN.
- Calibration : une IA bien calibrée a une confiance moyenne plus élevée sur ses gains que sur ses pertes (well_calibrated).
- Composition du score : hit_rate × 60 pts + calibration (25 si bien calibrée, sinon 10) + (1 − taux de fallback) × 15, plafonné à 100 ; score=None sans échantillon fermé.
- days est borné à [1, 365] ; une valeur invalide retombe sur 30.

**Évaluation prévision vs réalité des prédictions de stratégie**
<br>_Confrontation de chaque StrategyPrediction à la bougie réelle suivante pour persister actual_label et is_correct, puis calcul du taux de précision sur période._
<br>Points d'entrée : `backend/ai_engine/services_performance.py:PredictionEvaluationService.evaluate_pending`, `backend/ai_engine/services_performance.py:PredictionEvaluationService.accuracy`, `backend/ai_engine/tasks.py:evaluate_predictions_task`

- La « réalité » est la première bougie STRICTEMENT postérieure à candle_time (open_time__gt) du même asset et timeframe.
- Si la bougie suivante n'existe pas encore, la prédiction reste en attente et sera réessayée — jamais marquée incorrecte par défaut.
- Mapping des labels : {UP, BUY, LONG, BULLISH, CALL} → UP ; {DOWN, SELL, SHORT, BEARISH, PUT} → DOWN ; tout autre label est jugé correct uniquement si la bougie est FLAT (close == open).
- Seules les prédictions is_correct=NULL avec un predicted_label non vide sont traitées ; limite 500 par passage, ordonnées par candle_time croissant.
- accuracy renvoie None quand sample_size vaut 0.

**Scan de marché et calcul de features techniques**
<br>_Parcours de tous les actifs actifs, extraction de 200 bougies et calcul du jeu de features (RSI, MACD, SMA/EMA, Bollinger, ATR, volatilité, volume, retours) consigné dans un MarketScanRun._
<br>Points d'entrée : `backend/trading/services/market_scanner.py:MarketScannerService.scan`, `backend/trading/services/market_scanner.py:MarketScannerService._extract_features`, `backend/trading/services/ai/features.py:compute_features`, `backend/trading/services/market_scanner.py:MarketScannerService.get_or_create_timeframe`

- Un actif ayant moins de 30 bougies est IGNORÉ : le pipeline de features a besoin d'assez d'historique pour MACD, Bollinger et la détection de patterns.
- Un actif sans features exploitables est ignoré (pas de ligne vide propagée).
- Le MarketScanRun est finalisé en SUCCESS ou FAILED dans tous les cas, puis l'exception est re-levée.
- Introspection défensive du modèle Timeframe (code/slug/value, label/title/description, minutes, sort_order) : le scanner ne suppose pas un schéma figé.
- Seuls les Asset is_active=True sont scannés, triés par symbole.

**Scoring multi-facteurs des opportunités**
<br>_Pipeline modulaire : détection de régime (TREND_UP/TREND_DOWN/RANGE/HIGH_VOL/UNCLEAR), détection de patterns, scoring par dimensions (tendance, momentum, setup, volatilité, volume) pondérées par le régime, boost/malus de pattern et multiplicateur de feedback._
<br>Points d'entrée : `backend/trading/services/ai/scoring.py:score_opportunity`, `backend/trading/services/ai/regime.py:detect_regime`, `backend/trading/services/ai/patterns.py:detect_patterns`, `backend/trading/services/ai/feedback.py:update_strategy_confidence`, `backend/trading/services/opportunity_scoring.py:OpportunityScoringService.score`

- Le scoring est SIDE-AWARE : il produit explicitement BUY / SELL / HOLD et une confiance, pas un score aveugle (correction du défaut historique où un RSI survendu donnait un score élevé sans direction).
- Les poids dépendent du régime (_REGIME_WEIGHTS) : en TREND la tendance et le momentum pèsent 0,30 chacun ; en RANGE le setup pèse 0,40 ; en HIGH_VOL la volatilité pèse 0,40.
- Moins de volatilité = meilleur score : la composante volatilité entre dans l'agrégat sous la forme (1 − volatility_score).
- Un pattern aligné avec le side ajoute +0,10 × force ; un pattern contraire (non NEUTRAL) retire 0,05 × force.
- La confiance finale = clamp(overall + pattern_boost) × side_confidence × feedback_multiplier.
- Le multiplicateur de feedback est volontairement BORNÉ à [0,5 ; 1,5] : une série perdante ne peut pas vetoer une stratégie, une série gagnante ne peut pas contourner les plafonds de risque — le Risk Engine, pas le scorer, reste la source de vérité de ce qui s'exécute.
- Absence de features → OpportunityScore HOLD à 0 avec payload {reason:'no_features'} (jamais d'extrapolation).
- Chaque score porte un payload explicatif destiné à l'affichage (explicabilité).

**Génération de trade ideas**
<br>_Transformation du scan en TradeIdea + Signal : scoring, filtre de qualité, calcul des niveaux ATR, explication en langage naturel, fenêtre d'expiration et notification de synthèse._
<br>Points d'entrée : `backend/trading/services/trade_idea_generation.py:TradeIdeaGenerationService.generate`, `backend/trading/services/trade_idea_generation.py:TradeIdeaGenerationService.compute_levels`, `backend/trading/services/trade_idea_generation.py:TradeIdeaGenerationService.build_explanation`, `backend/trading/services/trade_idea_generation.py:TradeIdeaGenerationService._get_or_create_strategy`

- SEUIL DE QUALITÉ DUR : MIN_OVERALL_SCORE = 0.65 — une opportunité en dessous n'est jamais matérialisée en idée.
- generate() EXIGE un user non nul (ValueError sinon) : aucune idée orpheline, le cloisonnement par utilisateur est structurel.
- Direction HOLD → aucune idée.
- Niveaux ATR figés : stop = close ∓ 1,5 × ATR, take = close ± 3,0 × ATR ; ATR ≤ 0 est forcé à 0,001. Rejet si min(entry, stop, take) ≤ 0 ou si expected_rr ≤ 0.
- Fraîcheur obligatoire : candle_time est requis ; une bougie future de plus d'un timeframe est rejetée ; expires_at = candle_time + timeframe_minutes × MAX_CANDLE_AGE_MULTIPLIER(3) et une idée déjà expirée n'est pas créée.
- Déduplication stricte sur (user, scan_run, asset, timeframe, direction, status=NEW).
- Un Signal est TOUJOURS créé en amont de la TradeIdea et lui est rattaché (traçabilité).
- Une stratégie auto est créée au besoin, volontairement en status PAPER, is_autonomous=False, allow_live_execution=False.
- horizon_minutes = timeframe_minutes × 4.
- Toute la méthode est @transaction.atomic.
- Une seule notification AI_OPPORTUNITY_DETECTED par run et par utilisateur, portant la meilleure idée.

**Cycle d'intelligence orchestré (régime + revue d'idées)**
<br>_Enchaînement génération d'idées → analyse du régime global → revue multi-critères de chaque idée, avec mise à jour automatique du statut des idées._
<br>Points d'entrée : `backend/trading/services/agents/orchestrator.py:TradingIntelligenceOrchestrator.run_market_cycle`, `backend/trading/services/agents/market_regime_agent.py:MarketRegimeAgent.analyze`, `backend/trading/services/agents/trade_idea_review_agent.py:TradeIdeaReviewAgent.review`, `backend/trading/services/agents/base.py:BaseAgentService`

- Sans idée générée, le cycle s'arrête immédiatement (pas d'analyse de régime à vide).
- La revue AJUSTE le score mais ne le remplace pas : alignement avec le régime ±0,08/−0,10, VOLATILE −0,07, RANGE −0,02, risk_score > 0,75 → −0,08, expected_rr ≥ 2,0 → +0,05, confidence ≥ 0,80 → +0,05 ; adjusted_score borné à [0, 1].
- Seuils de décision figés : adjusted_score ≥ 0,78 → APPROVE ; ≤ 0,52 → REJECT ; sinon REVIEW.
- Le statut de l'idée est aligné sur la décision de revue : APPROVE → APPROVED, REJECT → REJECTED, sinon REVIEW.
- La priorité (1..n) est attribuée par ordre décroissant d'adjusted_score.
- update_or_create sur TradeIdeaReview : une idée n'a qu'UNE revue, réécrite à chaque passage.
- Chaque agent ouvre un AgentRun et le clôture en SUCCEEDED ou FAILED avec runtime_ms — en cas d'exception le run est finalisé FAILED PUIS l'exception est re-levée.

**Agent conseiller de portefeuille**
<br>_Évaluation du drawdown, du nombre de positions et de l'exposition pour recommander ALLOW_NEW_POSITIONS, REDUCE_RISK, BLOCK_NEW_POSITIONS ou CLOSE_WEAK_POSITIONS, persistée en PortfolioAdvice._
<br>Points d'entrée : `backend/trading/services/agents/portfolio_advisor_agent.py:PortfolioAdvisorAgent.advise`, `backend/trading/services/agents/portfolio_advisor_agent.py:PortfolioAdvisorAgent._persist_result`, `backend/trading/views_trade_ideas.py:TradeIdeaAutoTradeView.post`

- ORDRE DES TESTS CRITIQUE : capital initial invalide → BLOCK ; PUIS bypass PAPER/DEMO ; PUIS drawdown ≥ 30 % → CLOSE_WEAK_POSITIONS ; PUIS positions ≥ 25 → BLOCK ; PUIS drawdown ≥ 20 % → BLOCK ; PUIS drawdown ≥ 10 % ou exposition ≥ 80 % → REDUCE_RISK ; sinon ALLOW.
- Le bypass PAPER/DEMO est placé AVANT les blocages critiques : en simulation un drawdown ≥ 20 % donne REDUCE_RISK (paper_bypass=True) et non un blocage — déplacer ce test changerait le comportement du mode démo.
- BLOCK_NEW_POSITIONS est un blocage SOUPLE côté auto-trading : l'utilisateur peut passer outre en cochant « Forcer l'exécution », et l'override est tracé dans l'audit.
- confidence de l'avis = 1 − risk_score.
- Chaque avis crée systématiquement un AgentRun SUCCEEDED ET un PortfolioAdvice (traçabilité complète).
- @transaction.atomic sur advise.

**Opportunités de marché (MarketOpportunity) et expiration**
<br>_Objets d'opportunité scorés rattachés à un scan, avec cycle de vie NEW/ACTIVE/EXPIRED/CONSUMED/REJECTED et expiration automatique._
<br>Points d'entrée : `backend/trading/services/opportunity_engine.py:OpportunityEngine.create_opportunity`, `backend/trading/services/opportunity_engine.py:OpportunityEngine.start_scan`, `backend/trading/services/opportunity_engine.py:OpportunityEngine.finish_scan`, `backend/trading/services/opportunity_engine.py:OpportunityEngine.expire_old_opportunities`, `backend/api/views/ai.py:MarketOpportunityViewSet`

- create_opportunity naît directement en statut ACTIVE avec expires_at = now + 30 min par défaut.
- L'expiration ne touche que les statuts NEW et ACTIVE dont expires_at est dépassé — jamais une opportunité CONSUMED ou REJECTED.
- Tri par défaut -overall_score puis -created_at.
- Toutes les méthodes du moteur sont @transaction.atomic.

**Recommandations IA de trade (TradeRecommendation)**
<br>_Transformation d'une opportunité en recommandation chiffrée pour un portefeuille : inférence locale, sizing contraint par le broker et le profil de risque, aperçu Risk Engine, classification WATCH/PLAN/EXECUTE._
<br>Points d'entrée : `backend/trading/services/ai_engine.py:AIRecommendationService.compute_final_recommendation`, `backend/trading/services/ai_engine.py:AIRecommendationService.create_recommendation`, `backend/trading/services/ai_engine.py:AIInferenceService.infer`, `backend/trading/services/ai_engine.py:AIInferenceService.run_local_inference`, `backend/trading/tasks_ai.py:generate_ai_recommendations_for_portfolio_task`, `backend/api/views/ai.py:TradeRecommendationViewSet.generate_for_portfolio`

- Classification d'inférence locale : overall ≥ 0,80 ET confiance ≥ 0,70 → EXECUTE (10 % du cash) ; overall ≥ 0,60 → PLAN (5 %) ; sinon WATCH (2 %).
- Le stake final est le MINIMUM de (cash × pct, cash disponible, 4 × risque max en cash) — triple plafonnement.
- CAPITAL PRESERVATION FIRST : le tier d'instrument (risk.instruments.classify) est transmis au PositionSizingService et ne peut que RÉDUIRE la taille.
- Contraintes broker obligatoires : min_qty, qty_step, min_notional récupérés via BrokerConstraint puis synchronisés à la demande ; si le sizing lève ValueError, la recommandation est DÉGRADÉE en WATCH à montant 0 avec degraded_reason='broker_constraint_not_met' — jamais une recommandation non exécutable.
- Risk Engine : décision BLOCK ou REJECT → type forcé à WATCH ; décision REDUCE → on retient approved_stake / approved_quantity / approved_notional et non les valeurs demandées.
- Mapping statut figé : WATCH → PENDING, PLAN → APPROVED_BY_AI, EXECUTE → APPROVED_BY_AI.
- Chaque inférence est journalisée dans AIInferenceLog (succès ou échec, latence, hash du prompt) AVANT de lever l'erreur éventuelle.
- create_recommendation est @transaction.atomic et crée systématiquement un DecisionAudit (ai_output + sizing_output + risk_output).
- Déduplication : pas de nouvelle recommandation si une existe déjà pour (user, portfolio, opportunity) en PENDING/APPROVED_BY_AI/APPROVED_BY_USER/EXECUTED.
- Les tâches ne traitent que les portefeuilles is_active ET dont le broker_account est is_active, sur les 20 meilleures opportunités ACTIVE.
- expires_at de la recommandation est hérité de l'opportunité.

**Approbation, rejet et exécution d'une recommandation IA**
<br>_Actions utilisateur sur une recommandation : approuver, rejeter, ou exécuter (création d'une trade idea APPROVED puis exécution via le service d'exécution)._
<br>Points d'entrée : `backend/trading/services/recommendation_actions.py:RecommendationActionService.approve_by_user`, `backend/trading/services/recommendation_actions.py:RecommendationActionService.reject_by_user`, `backend/trading/services/recommendation_actions.py:RecommendationActionService.execute_recommendation`, `backend/api/views/ai.py:TradeRecommendationViewSet`, `backend/dashboard/views_premium.py:RecommendationExecuteView`

- Seuls les statuts APPROVED_BY_AI, APPROVED_BY_USER et PENDING sont exécutables — ValueError explicite sinon. (Conséquence : une recommandation WATCH, donc PENDING, reste exécutable.)
- L'exécution matérialise d'abord une TradeIdea en statut APPROVED copiant intégralement l'opportunité (prix, niveaux, scores, explication, features), puis appelle TradeIdeaExecutionService.execute avec le stake de la recommandation.
- Les trois actions sont @transaction.atomic et synchronisent le DecisionAudit lié (final_decision APPROVED_BY_USER / REJECTED_BY_USER / EXECUTED + execution_output).
- L'approbation notifie l'utilisateur ET diffuse un événement dashboard temps réel ; le rejet ne notifie pas.
- Les ViewSets DRF sont filtrés sur user ; les vues premium refiltrent explicitement sur user=request.user.

**Registre de modèles IA et logs d'inférence**
<br>_Catalogue versionné des modèles (LLM, classifier, ranker, regime, scorer) et journal de chaque inférence (payloads, latence, coût estimé, succès/erreur, hash de prompt)._
<br>Points d'entrée : `backend/trading/models_ai.py:AIModelRegistry`, `backend/trading/models_ai.py:AIInferenceLog`, `backend/trading/services/ai_engine.py:AIInferenceService.get_default_model`, `backend/trading/services/ai_engine.py:AIInferenceService.hash_payload`, `backend/api/views/ai.py:AIModelRegistryViewSet`, `backend/api/views/ai.py:AIInferenceLogViewSet`

- Unicité stricte du triplet (provider, model_name, version).
- Le modèle par défaut est le plus récent parmi les is_active=True.
- Le prompt_hash est un SHA-256 du payload trié (déduplication et traçabilité).
- L'AIInferenceLog est écrit MÊME en cas d'échec (success=False + error_message), puis l'erreur est levée — la trace précède toujours la remontée d'erreur.
- /api/v1/ai-models/ ne liste que les modèles actifs ; /api/v1/ai-inference-logs/ est filtré sur l'utilisateur.

**Audit de décision de bout en bout (DecisionAudit)**
<br>_Trace unifiée reliant sortie IA, sizing, décision de risque, exécution et décision finale, référençant opportunité, recommandation, RiskDecision et Order._
<br>Points d'entrée : `backend/trading/models_ai.py:DecisionAudit`, `backend/trading/services/ai_engine.py:AIRecommendationService.create_recommendation`, `backend/trading/services/recommendation_actions.py:RecommendationActionService`, `backend/ai_assistant/services_actions.py:AssistantTradingCommandService._audit`

- Toutes les FK métier sont en SET_NULL : la suppression d'un ordre ou d'une décision de risque ne doit jamais effacer la trace d'audit.
- Quatre blocs JSON distincts et non fusionnés : ai_output, sizing_output, risk_output, execution_output.
- final_decision est la valeur de référence (PENDING, APPROVED_BY_AI, APPROVED_BY_USER, REJECTED_BY_USER, EXECUTED, BLOCKED, APPROVED).
- L'écriture d'audit depuis l'assistant est enveloppée dans un try/except : un échec d'audit ne doit jamais annuler une action déjà exécutée.
- Queryset filtré sur l'utilisateur.

**AI Radar temps réel**
<br>_Flux WebSocket par utilisateur diffusant les événements IA (création de recommandation) et widget d'affichage des recommandations avec actions approuver/rejeter/exécuter._
<br>Points d'entrée : `backend/trading/consumers_ai.py:AIRadarConsumer`, `backend/core/realtime.py:RealtimeBroadcastService.broadcast_ai_update`, `backend/dashboard/views_fragments.py:AIPartialView`, `backend/dashboard/views_premium.py:CockpitDataView`

- Connexion refusée (code 4001) pour un utilisateur non authentifié ; groupe strictement nominatif user_ai_<id> — pas de diffusion croisée.
- Le consumer est en LECTURE SEULE : receive() ignore tout message entrant, aucune action n'est déclenchable par le WebSocket.
- Un message de confirmation connection.established est envoyé à l'ouverture.
- Le payload de recommendation_created porte recommendation_id, symbol, direction, type, statut, stake, notional et confiance.
- Le broadcast est best-effort : l'absence de channel layer est logguée et ne fait pas échouer la création de la recommandation.

**Liste, détail et live feed des trade ideas**
<br>_Pages de consultation des opportunités IA avec filtres (statut, symbole, direction), pagination, et flux JSON enrichi de contexte marché recalculé, décision IA, lecture humaine et indication de qualité d'exécution._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaListView`, `backend/trading/views_trade_ideas.py:TradeIdeaLiveFeedView`, `backend/trading/views_trade_ideas.py:TradeIdeaDetailView`, `backend/trading/views_trade_ideas.py:TradeIdeaFilterMixin.get_filtered_queryset`

- Tous les querysets sont filtrés sur user=request.user (TradeIdeaFilterMixin et get_queryset du détail).
- Le live feed RECALCULE à la volée le contexte marché depuis les 80 dernières bougies (RSI, ATR, EMA 9/21, régime, volatilité, liquidité par ratio de volume) : ces indicateurs ne sont pas ceux stockés dans features_snapshot.
- Moins de 2 bougies → contexte vide avec des UNKNOWN explicites (jamais de valeur inventée).
- Le détail recalcule une décision IA locale (EXECUTE ≥ 0,75 + confiance ≥ 0,70 + alignement tendance ; PLAN ≥ 0,60 + alignement ; WATCH ≥ 0,45 ; sinon REJECT) indépendante de AIDecisionLog.
- Absence de données marché → ai_decision='WATCH' avec le motif explicite.
- Le détail calcule les stakes minimums par broker via TradeIdeaPreviewService et détecte les symboles Deriv multiplicateur (BOOM/CRASH → MULTUP/MULTDOWN sans durée).
- Le live feed est plafonné à 50 idées.

**Approbation, rejet et auto-trading d'une trade idea**
<br>_Validation manuelle d'une opportunité IA, rejet, ou lancement de l'exécution avec choix du broker, du portefeuille, du montant et possibilité de passer outre un blocage de risque souple._
<br>Points d'entrée : `backend/trading/views_trade_ideas.py:TradeIdeaApproveView`, `backend/trading/views_trade_ideas.py:TradeIdeaRejectView`, `backend/trading/views_trade_ideas.py:TradeIdeaAutoTradeView`, `backend/trading/mixins.py:UserScopedTradeIdeaMixin`

- Une idée EXECUTED, EXPIRED ou CANCELLED ne peut plus être ni approuvée ni rejetée.
- Approbation et rejet émettent respectivement AI_OPPORTUNITY_APPROVED et AI_OPPORTUNITY_REJECTED.
- Le broker et le portefeuille doivent appartenir à l'utilisateur ET être is_active (get_object_or_404) ; montant strictement positif obligatoire.
- KILL SWITCH : en mode non PAPER/DEMO c'est un blocage DUR non franchissable même avec override — l'utilisateur est redirigé vers dashboard:resolve_kill_switch.
- Le PortfolioAdvisorAgent est un blocage SOUPLE : BLOCK_NEW_POSITIONS peut être franchi en cochant risk_override, avec avertissement et consignation dans l'audit.
- L'override est horodaté avec son motif (500 car. max), l'IP (X-Forwarded-For prioritaire sur REMOTE_ADDR, 45 car.) et le user-agent (512 car.) — il est ignoré pour les blocages HARD.
- Avertissement explicite en mode PAPER sur un compte Deriv tokenisé : l'ordre est simulé localement et n'atteint JAMAIS Deriv ; le type de compte Deriv (demo/réel) est contrôlé séparément par deriv_account_type.
- Les messages de succès distinguent toujours PAPER (simulé, broker_order_id local) et LIVE (envoyé au broker, statut réel).

**Moteur hedge fund : cycles de génération et d'exécution autonomes**
<br>_Cycle qui détecte le régime, génère des idées, calcule une confiance composite puis, pour chaque portefeuille, exécute automatiquement la meilleure idée après sizing intelligent._
<br>Points d'entrée : `backend/trading/services/hedge_fund/engine.py:AIHedgeFundEngine.run_generation_cycle`, `backend/trading/services/hedge_fund/engine.py:AIHedgeFundEngine.execute_top_idea_for_portfolio`, `backend/trading/services/hedge_fund/confidence_engine.py:ConfidenceEngine.assess`, `backend/trading/services/hedge_fund/position_sizer.py:IntelligentPositionSizer.compute_size`, `backend/trading/services/hedge_fund/risk_agent.py:GlobalRiskAgent.evaluate`

- SEUIL D'EXÉCUTION DUR : MIN_EXECUTION_CONFIDENCE = 0.65 sur la confiance finale — en dessous l'idée est seulement ignorée, PAS rejetée (elle reste candidate au cycle suivant).
- GlobalRiskAgent est évalué EN PREMIER : allow_new_positions=False arrête tout le portefeuille avant même de parcourir les idées.
- Binance en mode LIVE exige last_connection_status vrai : vérification en amont (retour None) ET re-vérification dans la boucle (ValueError).
- Confiance finale = confiance brute + ajustement régime (±0,08 / −0,08 HIGH_VOLATILITY / −0,03 SIDEWAYS) + ajustement apprentissage (multiplicateur − 1, moins 0,2 × pénalité de drawdown) + ajustement risque (BLOCK −0,30, REDUCE −0,12, CAUTION −0,05), bornée à [0, 1].
- Priorité d'exécution par paliers : ≥ 0,85 → 1 ; ≥ 0,75 → 2 ; ≥ 0,65 → 3 ; sinon 99. Les idées sont parcourues par execution_priority croissante puis -final_confidence puis -overall_score.
- Une taille calculée ≤ 0 REJETTE l'idée avec le motif consigné dans ai_payload (rejection_stage).
- Tout rejet d'exécution est matérialisé : statut REJECTED, ai_payload enrichi (execution_error, execution_rejected_at, rejection_stage) et Signal associé passé en REJECTED avec le motif concaténé à la raison existante.
- Le cycle d'exécution ne retient qu'UN seul ordre par portefeuille (return dès le premier ordre créé).
- Les idées candidates sont uniquement celles de l'utilisateur du portefeuille, en statut NEW ou APPROVED.
- Un échec d'évaluation de confiance sur une idée n'interrompt pas la boucle (log + continue).

**Boucle d'apprentissage et renforcement**
<br>_Rapprochement des idées exécutées avec le résultat réel des positions, calcul de métriques par stratégie (win rate, expectancy, payoff, sharpe-like, multiplicateurs) et journal des événements de renforcement._
<br>Points d'entrée : `backend/trading/tasks.py:learn_from_trade_ideas_task`, `backend/trading/tasks.py:run_learning_refresh_cycle`, `backend/trading/services/hedge_fund/learning_agent.py:LearningAgent.compute_metrics`, `backend/trading/services/hedge_fund/learning_agent.py:LearningAgent.refresh_for_strategy`, `backend/trading/services/hedge_fund/learning_agent.py:LearningAgent.reinforcement_from_feedback`, `backend/trading/views_hedge_fund.py:learning_monitor_api`, `backend/trading/views_hedge_fund.py:risk_monitor_api`

- Seuls les feedbacks OPEN dont l'idée est en statut EXECUTED sont évalués.
- Classification du résultat : position encore OPEN → OPEN ; PnL > 0 → WIN avec hit_take_profit ; PnL < 0 → LOSS avec hit_stop_loss ; sinon BREAKEVEN.
- ÉCHANTILLON MINIMUM : les multiplicateurs ne sont ajustés qu'à partir de 10 trades — en dessous ils restent neutres (1.0). Win rate ≥ 0,60 et expectancy > 0 → 1,10/1,10/1,08 ; win rate < 0,45 ou expectancy < 0 → 0,90/0,80/0,85.
- La pénalité de drawdown n'est appliquée qu'à partir de 5 trades avec autant ou plus de pertes que de gains, plafonnée à 0,5.
- Expectancy = (win_rate × gain moyen) − ((1 − win_rate) × perte moyenne absolue).
- Les snapshots sont HISTORISÉS (create, jamais update) sur les 200 derniers feedbacks clos — l'historique d'apprentissage ne doit pas être écrasé.
- Chaque feedback clos produit un ReinforcementEvent TRADE_CLOSED avec récompense, pénalité et valeur nette.
- Les API de monitoring risque filtrent sur les portefeuilles de l'utilisateur ; l'API d'apprentissage ne filtre PAS (snapshots globaux).

**Tableau de bord hedge fund IA**
<br>_Vue de synthèse : régime courant, états de risque par portefeuille, dernières idées et top idées, positions ouvertes, derniers snapshots d'apprentissage, statistiques agrégées et séries de graphiques._
<br>Points d'entrée : `backend/trading/views_hedge_fund.py:HedgeFundDashboardView`

- Les portefeuilles et positions sont filtrés sur l'utilisateur ; un seul état de risque (le plus récent) est retenu par portefeuille.
- Le régime affiché est le MarketRegimeState global le plus récent (non rattaché à l'utilisateur).
- ATTENTION : les compteurs d'idées (ideas_count, approved_ideas_count, executed_ideas_count, moyennes de scores) et les listes ideas/top_ideas portent sur TOUS les utilisateurs — aucun filtre user.
- Les séries de graphiques sont bornées (20 positions, 10 idées, 10 snapshots).

</details>

<details><summary>Pièges de migration repérés</summary>

- CHEMIN CASSÉ — AssistantAction : ai_assistant/views.py (ActionConfirmView, ActionRejectView, PendingActionsView) et ai_assistant/consumers.py (_confirm_action, _reject_action) filtrent sur `message__session__user`, lookup INVALIDE car AssistantMessage porte le FK `conversation` (related_name 'messages'). Tout le flux de confirmation des cartes d'action émises par le LLM (DRAFT_ORDER, ADJUST_SL…) lève une FieldError. Le lookup correct est `message__conversation__user`. À corriger AVANT de porter la fonctionnalité, sinon elle sera reproduite cassée.
- CONTEXTE DE RISQUE FAUX — AssistantContextService.build lit `getattr(profile, 'max_daily_drawdown', 5)` alors que le champ réel de RiskProfile est `max_daily_loss` (le prompt système le dit lui-même explicitement). Le snapshot injecté dans le prompt affiche donc TOUJOURS la valeur par défaut 5 %, et l'IA raisonne sur une limite inexistante.
- RATE LIMIT COMPTÉ EN DOUBLE — ai_engine/views.py:_ai_rate_limit_check et ai_engine/services.py:AITradeAdvisor._check_rate_limit utilisent la MÊME clé Redis `ai_rate:{user_id}` avec des plafonds par défaut différents (30 vs 60). Un seul POST /ai/advise/trade-idea/ incrémente le compteur deux fois. À unifier dans un service unique lors de la refonte.
- CLOISONNEMENT NON EFFECTIF — api/views/ai.py : MarketScanRunViewSet et MarketOpportunityViewSet tentent le filtrage par utilisateur via une boucle try/except sur des FK (user, portfolio__user, scan_run__user…) que ces modèles ne possèdent PAS. Le `qs.filter(**kwargs)` étant paresseux, l'exception n'est pas levée dans le try et le queryset est retourné SANS filtre réel : fuite potentielle des scans et opportunités entre utilisateurs. À remplacer par un cloisonnement explicite (ajouter un FK user/owner ou filtrer via les TradeIdea de l'utilisateur).
- FUITE DE STATISTIQUES — HedgeFundDashboardView calcule ideas_count, approved/executed_ideas_count, avg_confidence, avg_overall_score et les listes ideas/top_ideas sur TradeIdea.objects sans filtre user ; learning_monitor_api expose les LearningSnapshot et ReinforcementEvent de toute la plateforme ; ai_performance_view accepte ?scope=platform sans contrôle is_staff (contrairement à /assistant/api/analytics/ qui, lui, vérifie). À arbitrer explicitement avant exposition en API.
- LOGIQUE MÉTIER ENFOUIE DANS LES VUES — TradeIdeaDetailView._compute_market_snapshot et TradeIdeaLiveFeedView (_get_market_context, _compute_rsi/_atr/_ema, _compute_ai_decision, _build_ai_reason, _build_human_guidance) recalculent indicateurs, décision IA, lecture humaine et qualité d'exécution DANS la couche vue, avec des seuils différents de ceux du scoring (0,75/0,60/0,45 côté vue contre 0,80/0,65 côté moteur). Deux vérités coexistent. À extraire dans un service partagé AVANT d'écrire l'API, sinon React et Flutter afficheront des décisions divergentes.
- DUPLICATION DE PIPELINE IA — trois chaînes de décision coexistent sans arbitrage : (1) ai_engine.AITradeAdvisor (LLM Claude/DeepSeek/Ollama → AIDecisionLog), (2) trading.services.ai_engine.AIInferenceService.run_local_inference (heuristique par seuils → AIInferenceLog/TradeRecommendation), (3) trading.services.ai.scoring (scoring multi-facteurs → TradeIdea). Elles ont des seuils, des vocabulaires de décision et des journaux d'audit DIFFÉRENTS. Choisir la chaîne canonique ou documenter leurs rôles respectifs avant la refonte.
- DOUBLE TÂCHE D'EXPIRATION — trading.tasks.expire_trade_ideas_task et trading.tasks.expire_old_trade_ideas font le même travail et sont toutes deux planifiées à la minute : deux beats concurrents sur le même queryset.
- NOMMAGE DES TÂCHES DE SCAN TROMPEUR — scan_market_1m_task génère en timeframe '5m' et scan_market_5m_task en '15m' ; run_ai_market_cycle_1m utilise aussi '5m'. Le nom de la tâche ne correspond pas au timeframe traité : ne pas se fier aux noms lors du portage.
- AVIS IA UNIQUE PAR IDÉE — advise_open_trade_ideas_task déclare en commentaire « skip si déjà décidé dans la dernière heure » mais teste `AIDecisionLog.objects.filter(trade_idea=idea).exists()` SANS fenêtre temporelle : une idée ne reçoit qu'un seul avis pour toute sa vie. Si le comportement horaire est voulu, c'est un bug à corriger ; sinon le commentaire est à amender.
- ÉTAT IMPLICITE DE LA GÉNÉRATION — AssistantGenerationService._running est un set en mémoire de process : l'anti-duplication ne vaut QUE dans un worker ASGI. Avec plusieurs workers ou un redéploiement, un même message peut être régénéré. À remplacer par un verrou Redis (comme single_run du moteur IA) lors de la refonte.
- SCAN SYNCHRONE DANS LE CHAT — l'outil find_trade_ideas appelle TradeIdeaGenerationService.generate (scan de TOUS les actifs actifs, 200 bougies chacun) de façon synchrone via sync_to_async pendant la conversation. Sur un univers large, le message utilisateur bloque plusieurs secondes. À basculer en tâche asynchrone avec réponse différée.
- ATOMICITÉ TROP LARGE — TradeIdeaGenerationService.generate et MarketScannerService.scan sont tous deux @transaction.atomic : l'échec d'un seul actif annule l'intégralité du run, y compris l'enregistrement du MarketScanRun en FAILED (rollback). La trace de l'échec est donc perdue.
- QUOTA BLOQUE AUSSI LE DÉTERMINISTE — le contrôle de quota dans _handle_chat précède la détection d'intention : un quota épuisé empêche aussi les outils déterministes (analyser son risque, annuler un ordre, activer le kill switch) alors qu'ils ne consomment aucun token LLM. Décision produit à trancher explicitement.
- RESET MENSUEL JAMAIS DÉCLENCHÉ — AIUserQuota.monthly_reset() n'est appelé nulle part et aucune tâche Celery ne la planifie : les 20 messages du plan FREE ne se réinitialisent jamais en pratique.
- MODÈLES PRÉPARÉS MAIS SANS FONCTIONNALITÉ — AssistantAttachment (upload de documents) et AssistantConversationParticipant (mode équipe) n'ont ni endpoint, ni vue, ni service hors la création automatique du propriétaire. Ce sont des préparations, pas des fonctionnalités : ne pas les présenter comme existantes dans la refonte.
- PAIEMENTS PILOTÉS PAR WEBSOCKET — pay_with_wallet et create_paystack_session/create_stripe_session ne sont atteignables que par des messages WS (quota_pay_wallet / quota_pay_stripe) et les retours sont des redirections HTML vers /dashboard/. Inutilisable tel quel depuis Flutter : prévoir des endpoints REST et des deep links de retour, en conservant l'idempotence du ledger (external_event_id) et la validation croisée du webhook.
- FRONT ASSISTANT MONOLITHIQUE — static/js/leo_assistant.js (1050 lignes) manipule le DOM par identifiants globaux et expose window.LeoAssistant, appelé depuis des attributs onclick inline dans au moins trois templates (_ai_radar.html, trade_idea_list.html, trade_idea_detail.html). Le portage React/Flutter doit remplacer ce couplage par un contrat d'événements explicite ; seul le protocole WebSocket est réutilisable.
- SURFACE WEB SANS ÉQUIVALENT API — à migrer en priorité car exposées UNIQUEMENT en vues Django : trade ideas (liste, détail, live feed, approve, reject, auto-trade avec override de risque), tableau de bord et moniteurs hedge fund, centre de performance IA, journal des décisions IA, état et paiement du quota, actions inline de l'assistant. Ce sont les fonctionnalités les plus exposées au risque d'oubli.
- AUCUN MODE HORS LIGNE NI FILE D'ATTENTE — rien dans le domaine ne gère la reprise côté client : le chat dépend entièrement du WebSocket et les confirmations d'action ont un TTL de 10 minutes. Une confirmation émise hors ligne expirera. À concevoir explicitement pour Flutter (ne jamais rejouer une confirmation expirée).

</details>

---

### wallet-payments

`31 fonctionnalités` — API : **4 prêtes, 0 partielles, 27 à exposer**

**Modèles** : `Wallet`, `PaymentMethod`, `WalletTransaction`, `WithdrawalRequest`, `ProviderWebhookEvent`, `WalletLedgerEntry`, `PayoutDestination`, `PaymentProviderAccount`, `WalletTransferIntent`, `Transfer (app accounting, pont Wallet↔Portfolio)`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Création automatique du wallet à l'inscription** | ❌ | WEB/MOBILE |  | Aucun endpoint REST ne retourne le wallet courant. Il faut un GET /api/v1/wallet/me/ qui crée-ou-retourne le wallet (available_balance, locked_balance, total_balance, total_deposited, total_withdrawn, currency, is_active, can_withdraw). |
| **Tableau de bord wallet** | ❌ | WEB/MOBILE | ⚡ | Tout est calculé dans la vue template. Il faut un endpoint d'agrégation GET /api/v1/wallet/dashboard/ renvoyant soldes + summary + listes tronquées, ou laisser le client composer depuis plusieurs endpoints (wallet, transactions?limit=10, withdrawals?limit=5, payout-destinations, transfers?limit=5). |
| **Historique des transactions wallet (filtres + recherche + pagination)** | ❌ | WEB/MOBILE |  | Aucun endpoint. Il faut GET /api/v1/wallet/transactions/ avec filtres tx_type, status, search, pagination et tri, scope automatiquement au wallet du requérant. |
| **Détail d'une transaction wallet avec écritures de grand livre** | ❌ | WEB/MOBILE |  | Il faut GET /api/v1/wallet/transactions/<id>/ avec les ledger_entries imbriquées, et un filtrage explicite des champs de metadata exposés. |
| **Dépôt — initialisation du checkout Paystack** | ❌ | WEB/MOBILE |  | La vue répond par une redirection HTTP 303 vers le provider, inexploitable en React/Flutter. Il faut POST /api/v1/wallet/deposits/ renvoyant en JSON {transaction_id, provider, authorization_url, reference, expires_at} pour que le client ouvre une WebView / un onglet, plus un endpoint de polling du statut. |
| **Dépôt — Stripe Checkout Session** | ❌ | WEB/MOBILE |  | Même problème que Paystack : redirection 303. Il faut renvoyer session.url (ou le client_secret pour Stripe Elements / PaymentSheet mobile) en JSON. |
| **Dépôt — session Adyen** | ❌ | WEB/MOBILE |  | Le parcours Adyen est incomplet : le template se contente d'afficher le JSON de session dans un <pre>, le Drop-in/Components n'est jamais monté. Aucun paiement Adyen ne peut donc aboutir depuis l'UI actuelle. En API, exposer la session (id, sessionData, clientKey) pour un Drop-in Web et un Adyen Drop-in Flutter. |
| **Retour de paiement (callback de dépôt) avec vérification serveur Paystack** | ❌ | WEB/MOBILE |  | Vue HTML uniquement. Il faut POST /api/v1/wallet/deposits/<id>/verify/ (ou GET .../status/) renvoyant {status, transaction} pour que le client, de retour de WebView, puisse confirmer et rafraîchir le solde. |
| **Annulation de dépôt** | ❌ | WEB/MOBILE |  | Purement informatif ; à traiter côté client comme un simple état d'écran, aucun endpoint nécessaire. |
| **Webhook Stripe (source de vérité du crédit)** | ✅ | — |  | — |
| **Webhook Adyen (HMAC)** | ✅ | — |  | — |
| **Webhook Paystack (HMAC SHA512)** | ✅ | — |  | — |
| **Grand livre wallet atomique (WalletLedgerService)** | ❌ | WEB |  | Service interne, pas d'exposition directe souhaitable. En revanche les WalletLedgerEntry doivent être lisibles en API (GET /api/v1/wallet/ledger-entries/) pour la piste d'audit et les écrans de détail. |
| **Reconstruction du solde depuis le grand livre (audit)** | ❌ | — |  | Aucune surface. Utile à exposer en endpoint staff (GET /api/v1/admin/wallets/<id>/reconcile/) pour détecter les divergences en production. |
| **Demande de retrait avec verrouillage des fonds** | ❌ | WEB/MOBILE |  | Aucun endpoint. Il faut POST /api/v1/wallet/withdrawals/ (amount, destination_type, payout_destination_id) retournant 403/422 explicite sur blocage KYC avec un code machine (ex. KYC_NOT_APPROVED) pour que React et Flutter affichent le bon écran de remédiation, plus GET /api/v1/wallet/withdrawals/ pour la liste. |
| **Détail d'une demande de retrait (utilisateur)** | ❌ | WEB/MOBILE |  | Il faut GET /api/v1/wallet/withdrawals/<id>/ avec un serializer utilisateur distinct du serializer staff (admin_note et metadata exclus côté utilisateur). |
| **Gestion des destinations de payout (CRUD + défaut)** | ❌ | WEB/MOBILE |  | Aucun endpoint. Il faut un ViewSet /api/v1/wallet/payout-destinations/ (list, create, update, destroy) + action POST set-default, avec queryset scopé à request.user, is_verified en lecture seule et validation conditionnelle par destination_type. |
| **Transfert Wallet ↔ Portfolio (double entrée atomique)** | ❌ | WEB/MOBILE |  | Aucun endpoint. Il faut POST /api/v1/wallet/transfers/ (direction, portfolio_id, amount, request_id fourni par le client pour une idempotence de bout en bout, indispensable en mobile sur réseau instable) et GET /api/v1/wallet/transfers/ pour l'historique. |
| **Historique des transferts Wallet ↔ Portfolio** | ❌ | WEB/MOBILE |  | Couvert par le GET /api/v1/wallet/transfers/ évoqué ci-dessus ; ajouter filtres direction et status, absents de la version Django. |
| **Pont Wallet → Portfolio (reflet comptable automatique)** | ✅ | — |  | — |
| **Back-office staff — liste des wallets clients** | ❌ | WEB |  | Il faut GET /api/v1/admin/wallets/ avec une permission IsAdminUser (ou un rôle RBAC dédié de type OPS/FINANCE) et la recherche équivalente. |
| **Back-office staff — détail d'un wallet client** | ❌ | WEB |  | Il faut GET /api/v1/admin/wallets/<id>/ exposant soldes + transactions + withdrawals + ledger_entries. |
| **Back-office staff — file des demandes de retrait** | ❌ | WEB | ⚡ | Il faut GET /api/v1/admin/withdrawals/ avec filtre status sur l'ensemble des statuts du modèle, recherche par client et pagination. |
| **Back-office staff — détail et contrôle d'une demande de retrait** | ❌ | WEB |  | Il faut GET /api/v1/admin/withdrawals/<id>/ avec le serializer staff complet (admin_note, metadata, reviewed_by, transactions liées). |
| **Back-office staff — approuver un retrait** | ❌ | WEB |  | Il faut POST /api/v1/admin/withdrawals/<id>/approve/ avec admin_note, et un 409 explicite sur transition interdite. |
| **Back-office staff — rejeter un retrait et débloquer les fonds** | ❌ | WEB |  | Il faut POST /api/v1/admin/withdrawals/<id>/reject/ (reason obligatoire, admin_note optionnelle), idempotent et avec 409 sur transition interdite. |
| **Back-office staff — marquer un retrait comme payé** | ❌ | WEB |  | Il faut POST /api/v1/admin/withdrawals/<id>/mark-paid/ (provider, provider_reference, admin_note), idempotent et avec 409 sur transition interdite. |
| **Administration Django native des objets wallet** | ❌ | WEB |  | L'admin Django reste utilisable en parallèle. Les actions destructrices (édition directe des soldes) doivent être neutralisées avant d'exposer un back-office React. |
| **Solde wallet dans le contexte global de l'interface** | ❌ | WEB/MOBILE | ⚡ | En SPA, ce besoin devient un store global alimenté par GET /api/v1/wallet/me/ (ou un endpoint bootstrap /api/v1/me/ regroupant user + wallet + portfolio par défaut + trading_mode), rafraîchi après chaque mutation de solde. |
| **Paiement d'un abonnement IA par le wallet** | ❌ | WEB/MOBILE |  | Appartient fonctionnellement au domaine IA mais consomme le wallet. L'API de paiement d'abonnement devra réutiliser le même service et retourner un code d'erreur machine insufficient_funds pour déclencher l'écran de dépôt côté client. |
| **Garde-fou wallet pour l'émission de signaux de stratégie** | ❌ | — |  | Règle interne au moteur ; aucune surface client. Le motif de blocage doit cependant remonter dans l'API des stratégies pour être affiché. |

<details><summary>Règles métier invariantes à préserver</summary>

**Création automatique du wallet à l'inscription**
<br>_Un Wallet unique est créé automatiquement pour chaque nouvel utilisateur, dans la devise par défaut de la plateforme. Les vues font aussi un get_or_create défensif._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/signals.py:create_user_wallet`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:_get_or_create_wallet`

- Contrainte DB UniqueConstraint uniq_wallet_per_user : un seul wallet par utilisateur, jamais deux
- La devise vient de settings.WALLET_DEFAULT_CURRENCY (défaut USD) et n'est jamais choisie par l'utilisateur
- La création doit rester idempotente (get_or_create) : le signal et les vues peuvent s'exécuter dans le même cycle

**Tableau de bord wallet**
<br>_Vue d'ensemble : soldes (disponible, bloqué, total, total déposé, total retiré), agrégats dépôts/retraits en attente, 10 dernières transactions, 5 derniers retraits, 5 destinations de payout, statut KYC, portfolios actifs et 5 derniers transferts._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_dashboard`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/dashboard.html`

- L'agrégat summary est calculé côté serveur : pending_deposit = DEPOSIT+PENDING, successful_deposit = DEPOSIT+SUCCEEDED, pending_withdrawal = WITHDRAWAL + status in (PENDING, PROCESSING)
- Le badge « Capacité de retrait » est piloté par Wallet.can_withdraw = is_active AND available_balance > 0 — ne jamais le dériver du seul solde
- Seuls les portfolios is_active=True de l'utilisateur sont listés, triés -is_default puis name
- total_balance = available_balance + locked_balance : le solde bloqué reste visible mais non dépensable

**Historique des transactions wallet (filtres + recherche + pagination)**
<br>_Liste paginée (25/page) des WalletTransaction du wallet, filtrable par type et statut, avec recherche texte sur provider_reference, description et provider._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_history`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/history.html`

- Cloisonnement strict : la requête part de wallet.transactions, jamais de WalletTransaction.objects.all()
- Valeurs de filtre type exposées : DEPOSIT, WITHDRAWAL, ADJUSTMENT, TRADE_LOCK, TRADE_RELEASE, FEE, REFUND ; statut : PENDING, PROCESSING, SUCCEEDED, FAILED, CANCELLED
- La recherche q est un OR insensible à la casse sur provider_reference / description / provider
- Tri par défaut -created_at (Meta.ordering du modèle)

**Détail d'une transaction wallet avec écritures de grand livre**
<br>_Affiche une transaction (montant, type, provider, référence, description, metadata brute) et les WalletLedgerEntry rattachées avec balance_before/balance_after._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_transaction_detail`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/transaction_detail.html`

- get_object_or_404 filtré sur wallet=wallet du requérant : impossible de lire la transaction d'autrui (404, pas 403)
- Les ledger entries sont triées par created_at croissant pour que la piste d'audit se lise dans l'ordre réel des mutations
- Le template affiche transaction.metadata brute : en API il faut assainir (le payload provider peut contenir des données client/porteur)

**Dépôt — initialisation du checkout Paystack**
<br>_Crée une WalletTransaction DEPOSIT PENDING, initialise une transaction Paystack côté serveur et redirige (303) l'utilisateur vers l'authorization_url._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_deposit`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService.create_deposit_checkout`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService.amount_to_subunit`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/form.py:DepositForm`

- Le montant et la devise sont toujours recalculés côté serveur : le front n'est jamais source de vérité (clean_amount re-valide DEPOSIT_MIN=1.00 / DEPOSIT_MAX=100000.00)
- La devise du dépôt DOIT être strictement égale à wallet.currency — contrôle en double, dans DepositForm.clean et dans create_deposit_checkout
- Un e-mail utilisateur non vide est obligatoire pour Paystack, sinon PaymentGatewayValidationError
- Montants minimum par devise (NGN 50, USD 2, GHS 0.10, ZAR 1, KES 3, XOF 1) ; XOF refuse toute fraction ; refus si plus de 2 décimales
- La devise doit appartenir à PAYSTACK_SUPPORTED_CURRENCIES sinon refus
- Fail-closed : sans PAYSTACK_SECRET_KEY → PaymentGatewayConfigurationError, aucune transaction n'est initiée
- Hors DEBUG, l'API Paystack et le callback SITE_BASE_URL doivent être en HTTPS, sinon refus
- La référence est générée serveur : LEOTRADE-DEP-<tx.id>-<uuid16>, et Paystack doit renvoyer exactement la même référence sinon PaymentGatewayError
- Si l'appel Paystack échoue, la transaction PENDING est repassée à FAILED (update conditionné à status='PENDING') — jamais laissée en PENDING orpheline
- Les erreurs passerelle sont loguées par type d'exception uniquement et l'utilisateur reçoit un message générique : aucune fuite de détail provider

**Dépôt — Stripe Checkout Session**
<br>_Crée une WalletTransaction DEPOSIT PENDING et une Checkout Session Stripe, puis redirige (303) vers session.url._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_deposit`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:StripeWalletService.create_deposit_checkout_session`

- wallet_transaction_id et user_id sont injectés dans session.metadata, et client_reference_id = user.id : ce sont les trois ancrages vérifiés par le webhook, ils doivent rester
- provider_session_id stocke session.id — le webhook refuse l'événement si l'id de session ne correspond pas
- Montant converti en centimes via int(amount*100) ; mode='payment' uniquement
- success_url / cancel_url construits depuis settings.SITE_BASE_URL
- Si le SDK stripe n'est pas importable ou STRIPE_SECRET_KEY est vide, le service lève avant toute création de transaction

**Dépôt — session Adyen**
<br>_Crée une WalletTransaction DEPOSIT PENDING et une session /v71/sessions Adyen, puis réaffiche la page de dépôt avec le payload de session._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_deposit`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:AdyenWalletService.create_deposit_session`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/deposit.html`

- La référence marchande est déterministe : LEOTRADE-DEP-<tx.id>, et c'est elle que le webhook AUTHORISATION utilise pour retrouver la transaction PENDING — ne jamais changer ce format sans migrer le webhook
- base_url bascule checkout-live / checkout-test selon settings.ADYEN_ENV
- Refus immédiat si ADYEN_API_KEY ou ADYEN_MERCHANT_ACCOUNT est vide
- countryCode est codé en dur à 'US' dans le payload (incohérent avec les destinations XOF/CI : à traiter lors de la refonte)
- AdyenWalletService.verify_hmac est un stub qui retourne toujours True — la vraie vérification HMAC vit dans webhooks._adyen_verify_signature ; ne pas utiliser le stub

**Retour de paiement (callback de dépôt) avec vérification serveur Paystack**
<br>_Page de retour après paiement. Pour Paystack, vérifie la transaction auprès de l'API puis confirme et crédite si succès. Affiche un statut succeeded / failed / pending / unknown._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_deposit_success`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService.verify_and_confirm`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService.verify_transaction`

- verify_and_confirm est filtré sur wallet_id=wallet du requérant : un utilisateur ne peut pas confirmer la transaction d'un autre (test dédié existant)
- Si la transaction est déjà SUCCEEDED, retour immédiat sans ré-appel provider (idempotence)
- La référence doit matcher REFERENCE_PATTERN ^[A-Za-z0-9.=-]{1,255}$ avant tout appel sortant, et est url-quotée
- Les statuts finaux d'échec (abandoned, failed, reversed) basculent la transaction en FAILED ; tout autre statut reste 'pending' (jamais d'échec définitif sur un statut inconnu)
- external_event_id de confirmation = paystack:verify:<provider_id> — distinct de celui du webhook (paystack:webhook:<event_id>) : les deux chemins peuvent donc créer deux événements ledger différents pour le même paiement, c'est la protection tx.status != PENDING dans confirm_deposit qui empêche le double crédit, PAS l'idempotence ledger
- Le webhook reste la source de vérité ; cette page est un raccourci UX, elle ne doit jamais être le seul chemin de crédit

**Annulation de dépôt**
<br>_Page de retour lorsque l'utilisateur abandonne le paiement chez le provider ; affiche un message d'avertissement._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_deposit_cancel`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/deposit_cancel.html`

- Aucune mutation : la transaction PENDING n'est PAS annulée côté base — elle reste PENDING et pourra encore être confirmée par webhook si l'utilisateur paie finalement. Ne pas « corriger » cela en passant la tx à CANCELLED sans arbitrage métier.

**Webhook Stripe (source de vérité du crédit)**
<br>_Reçoit les événements Stripe signés, vérifie la signature, déduplique et crédite le wallet sur checkout.session.completed / async_payment_succeeded._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/webhooks.py:stripe_webhook`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/webhooks.py:_stripe_session_matches_transaction`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:WalletService.confirm_deposit`

- Signature obligatoire via stripe.Webhook.construct_event avec STRIPE_WEBHOOK_SECRET → 400 si invalide ; 503 si le SDK est indisponible (fail-closed, jamais 200)
- Idempotence ATOMIQUE : ProviderWebhookEvent.objects.select_for_update().get_or_create(provider, event_id) sous @transaction.atomic — c'est ce verrou qui empêche le double crédit sur retries concurrents. Un simple get_or_create suivi d'un save laisserait une fenêtre de course : ne pas régresser
- Rejet 400 si la session ne matche pas la transaction sur les 5 critères simultanés de _stripe_session_matches_transaction : payment_status == 'paid', amount_total/100 == tx.amount, currency == tx.currency, client_reference_id == tx.wallet.user_id, session.id == tx.provider_session_id
- metadata.user_id doit aussi égaler tx.wallet.user_id (double contrôle d'appartenance)
- La transaction est verrouillée (select_for_update) et recherchée avec status='PENDING' : une transaction déjà traitée est ignorée silencieusement en 200
- provider_reference = payment_intent sinon session.id
- Le payload stocké en provider_payload est réduit à id / payment_intent / payment_status : aucune donnée carte ne doit être persistée
- L'événement n'est marqué processed=True qu'à la toute fin, dans la même transaction atomique

**Webhook Adyen (HMAC) **
<br>_Reçoit les notificationItems Adyen, vérifie le HMAC-SHA256 de chaque item, déduplique par pspReference et crédite sur AUTHORISATION réussie._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/webhooks.py:adyen_webhook`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/webhooks.py:_adyen_verify_signature`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/webhooks.py:_adyen_compute_hmac`

- Le HMAC est calculé sur la concaténation ordonnée pspReference:originalReference:merchantAccountCode:merchantReference:amount.value:amount.currency:eventCode:success, avec échappement de '\\' puis ':' — l'ordre et l'échappement sont imposés par Adyen, toute modification invalide toutes les signatures
- Comparaison en temps constant via hmac.compare_digest
- Fail-closed en production : sans ADYEN_HMAC_KEY et DEBUG=False, le webhook est refusé ; en DEBUG la vérification est contournée avec un warning — ce comportement conditionné à DEBUG doit être conservé tel quel ou durci, jamais assoupli
- Un item dont la signature est rejetée est ignoré (continue) mais les autres items du lot continuent d'être traités
- Idempotence atomique par (provider=ADYEN, event_id=pspReference) avec select_for_update, même garantie que Stripe
- Le crédit n'a lieu que si eventCode == 'AUTHORISATION' ET success == 'true'
- La transaction est retrouvée par provider_reference == merchantReference ET status='PENDING', verrouillée select_for_update
- external_event_id = adyen:<pspReference>
- Réponse toujours {"notificationResponse": "[accepted]"} — Adyen l'exige, y compris quand des items ont été ignorés

**Webhook Paystack (HMAC SHA512)**
<br>_Reçoit les événements Paystack, vérifie la signature X-Paystack-Signature, déduplique et crédite le wallet sur charge.success._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/webhooks.py:paystack_webhook`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService.apply_success_payload`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService._validate_success_payload`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PaystackWalletService.sanitized_transaction_payload`

- Signature = HMAC-SHA512 du corps BRUT avec PAYSTACK_SECRET_KEY, comparée via compare_digest → 400 sinon ; 503 si le secret est absent (fail-closed)
- Le corps brut (request.body) doit être utilisé pour le HMAC : toute re-sérialisation du JSON casse la signature
- event_id composite = <event_type>:<data.id ou reference> — la déduplication est par type d'événement, pas seulement par transaction
- Idempotence atomique select_for_update sur ProviderWebhookEvent, dans un with transaction.atomic()
- Le payload PERSISTÉ est la version assainie (id, status, reference, amount, currency, channel, paid_at, fees, metadata, customer_code/email) : aucune donnée de carte n'est stockée — test de non-régression existant
- _validate_success_payload refuse si : référence ≠ tx.provider_reference, status ≠ 'success', devise ≠ tx.currency, montant en sous-unité ≠ amount_to_subunit(tx.amount) (protection anti-crédit d'un mauvais montant, test dédié), metadata.wallet_transaction_id ≠ tx.id
- Un booléen passé comme montant est explicitement rejeté (isinstance bool avant int())
- Transaction introuvable ou payload rejeté → log + réponse 200 : on ne fait jamais retenter Paystack sur une erreur métier définitive
- external_event_id = paystack:webhook:<event_id>

**Grand livre wallet atomique (WalletLedgerService)**
<br>_Couche unique de mutation des soldes : credit, debit, lock, unlock. Chaque mutation écrit une WalletLedgerEntry avec balance_before/balance_after._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/services_v2.py:WalletLedgerService.credit`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services_v2.py:WalletLedgerService.debit`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services_v2.py:WalletLedgerService.lock`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services_v2.py:WalletLedgerService.unlock`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services_v2.py:_resolve_existing_entry`

- RÈGLE D'OR documentée dans le module : aucune ligne de code hors de services_v2 et accounting.services.TransferService ne doit modifier wallet.available_balance ou wallet.locked_balance
- Chaque méthode est @transaction.atomic et fait un Wallet.objects.select_for_update() AVANT de lire les soldes : c'est ce qui élimine les races de double dépense (test test_concurrent_locks_no_overdraft)
- Idempotence par external_event_id : si une WalletLedgerEntry porte déjà ce metadata__external_event_id, l'entrée existante est retournée SANS aucune mutation de solde. Tout appelant doit donc fournir une clé déterministe et unique par événement métier
- Les mutations passent par Wallet.objects.filter(pk).update(F('available_balance') ± amount) — jamais par une affectation Python puis save(), sous peine de lost update
- debit et lock lèvent InsufficientFundsError si available_balance < amount : jamais de solde négatif
- unlock lève InsufficientFundsError si locked_balance < amount
- unlock(to_available=True) fait locked → available (rejet de retrait) ; unlock(to_available=False) sort les fonds définitivement et incrémente total_withdrawn (paiement effectué). Le signe de l'entry.amount encode ce sens : positif = retour vers available, négatif = sortie définitive
- credit incrémente systématiquement total_deposited, y compris pour un rapatriement Portfolio→Wallet — total_deposited n'est donc PAS égal à la somme des dépôts externes ; comportement existant à préserver ou à corriger explicitement
- Les montants sont quantifiés à 0.01 en ROUND_HALF_UP via _q ; un montant ≤ 0 lève ValueError
- balance_before/balance_after stockent le total (available + locked), pas seulement le disponible

**Reconstruction du solde depuis le grand livre (audit)**
<br>_Rejoue toutes les WalletLedgerEntry d'un wallet dans l'ordre pour recalculer available et locked, à des fins de test et d'audit de cohérence._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/services_v2.py:WalletLedgerService.reconstruct_balance_from_ledger`

- Rejeu dans l'ordre (created_at, id) : CREDIT et REFUND augmentent available ; DEBIT et FEE le diminuent ; LOCK déplace available→locked ; UNLOCK est interprété par le SIGNE du montant (positif = retour vers available, négatif = sortie définitive de locked)
- C'est l'invariant de contrôle : le résultat doit être égal aux soldes matérialisés du Wallet. Toute nouvelle entry_type doit être ajoutée ici, sinon l'audit diverge silencieusement

**Demande de retrait avec verrouillage des fonds**
<br>_L'utilisateur saisit un montant, un type de destination et éventuellement une destination enregistrée ; les fonds sont verrouillés et une WithdrawalRequest est créée puis mise en revue._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_withdraw`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:WalletService.lock_funds_for_withdrawal`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:PayoutService.submit_withdrawal`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/form.py:WithdrawalForm`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:_mask_destination`

- GARDE KYC BLOQUANTE : le statut dashboard.KYCProfile doit être exactement 'APPROVED', sinon redirection vers kyc-dashboard. Le contrôle est fait AVANT la validation du formulaire pour n'exécuter aucun traitement inutile — conserver cet ordre
- Bornes serveur : WITHDRAWAL_MIN=5.00, WITHDRAWAL_MAX=100000.00 par opération, plus refus si amount > wallet.available_balance (triple contrôle : form, puis InsufficientFundsError du ledger)
- La destination choisie est systématiquement re-filtrée sur user=request.user (get_object_or_404) : impossible de payer vers la destination d'un tiers
- Le libellé de destination affiché est recalculé serveur par _mask_destination (IBAN/téléphone/référence tronqués aux 4 derniers caractères) et écrase toute valeur destination_masked envoyée par le client — ne jamais faire confiance au masque fourni
- Le verrouillage passe par WalletLedgerService.lock avec external_event_id = 'withdrawal-lock:<tx.id>' : idempotent, et available→locked en une seule transaction
- Le lien WalletTransaction ↔ WithdrawalRequest est stocké dans metadata['wallet_transaction_id'] : c'est ce lien explicite qui évite plus tard de matcher par montant (ambiguïté quand deux retraits ont le même montant)
- Création de la transaction, lock, création de la demande et submit_withdrawal sont dans un seul with transaction.atomic() de la vue : un échec de submit annule le lock
- PayoutService.submit_withdrawal est aujourd'hui un STUB : il se contente de passer le statut à UNDER_REVIEW, aucun payout automatique n'est déclenché. Tout retrait exige donc une action humaine (staff)

**Détail d'une demande de retrait (utilisateur)**
<br>_Affiche montant, frais, type et masque de destination, provider, référence, réviseur, date de revue, note admin, motif d'échec et metadata._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_withdrawal_detail`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/withdrawal_detail.html`

- Filtré sur wallet=wallet du requérant (404 sinon)
- ATTENTION : le template expose admin_note et withdrawal.metadata à l'utilisateur final. admin_note est une note interne staff — décider explicitement lors de la refonte si elle reste visible côté client, sinon régression de confidentialité

**Gestion des destinations de payout (CRUD + défaut)**
<br>_Liste, création, modification, définition par défaut et suppression des destinations de retrait (BANK, CARD, MOBILE_MONEY, WALLET) de l'utilisateur._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:payout_destination_list`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:payout_destination_create`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:payout_destination_update`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:payout_destination_set_default`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:payout_destination_delete`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/form.py:PayoutDestinationForm`

- is_verified est VOLONTAIREMENT exclu du formulaire utilisateur (commentaire explicite dans le code) : seul un staff peut vérifier une destination. Ne jamais l'ajouter au serializer d'écriture utilisateur
- Unicité du défaut : à la création et à la mise à jour, si is_default=True, toutes les autres destinations de l'utilisateur sont passées à is_default=False. set_default fait d'abord un update global à False puis positionne la cible — il n'y a aucune contrainte DB, l'invariant est purement applicatif et doit être reporté tel quel (idéalement durci par une contrainte partielle unique)
- Toutes les vues filtrent sur user=request.user (get_object_or_404) : cloisonnement strict
- set-default et delete sont en @require_POST avec CSRF : ce sont des mutations, jamais des liens GET
- La suppression est une suppression DURE (destination.delete()). WithdrawalRequest.destination est en SET_NULL et le lien réel est copié dans metadata : l'historique des retraits survit, mais la destination disparaît. Préférer une désactivation (is_active=False, champ déjà présent et inutilisé par les vues) lors de la refonte
- Champs éditables : destination_type, label, account_name, bank_name, iban, phone_number, mobile_money_operator, country_code (défaut CI), currency (défaut XOF), provider_reference, is_default
- Aucune validation croisée type↔champs n'existe aujourd'hui (on peut créer une destination BANK sans IBAN) : trou métier à combler sans casser les données existantes

**Transfert Wallet ↔ Portfolio (double entrée atomique)**
<br>_Déplace du cash entre le wallet plateforme et un portfolio de trading, dans les deux sens, en une opération atomique et idempotente._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:wallet_transfer_view`, `/Users/ogahserge/Documents/leoTrade/backend/accounting/services.py:TransferService.transfer_wallet_to_portfolio`, `/Users/ogahserge/Documents/leoTrade/backend/accounting/services.py:TransferService.transfer_portfolio_to_wallet`, `/Users/ogahserge/Documents/leoTrade/backend/accounting/models.py:Transfer`

- INVARIANT ABSOLU documenté : Sum(variations wallet) + Sum(variations portfolio) == 0 pour un même Transfer
- Idempotence par request_id UNIQUE : un second appel avec le même request_id retourne le Transfer existant sans rejouer la moindre mutation. request_id vide → ValueError. La vue génère 'ui:<user_pk>:<direction>:<uuid16>'
- Wallet et Portfolio doivent appartenir au MÊME utilisateur, sinon TransferError — contrôle présent dans les deux sens
- Sens Wallet→Portfolio : wallet.is_active et portfolio.is_active obligatoires ; débit wallet via WalletLedgerService.debit (external_event_id 'transfer:<request_id>:wallet_debit') puis crédit portfolio via CashLedgerEntry puis recompute_cash_state
- Sens Portfolio→Wallet : recompute_cash_state AVANT le contrôle, puis refus si portfolio.available_cash < amount ; écriture portfolio négative puis WalletLedgerService.credit (external_event_id 'transfer:<request_id>:wallet_credit')
- Le record Transfer est créé en PENDING AVANT les mutations, et survit en FAILED avec error_message si une étape échoue : la trace de l'échec ne doit jamais être perdue (le rollback interne n'annule que les mutations de soldes, pas le record)
- InsufficientFundsError est traduit en TransferError('Solde wallet insuffisant') : message métier, pas d'exception technique remontée à l'UI
- Le montant est quantifié à 0.01 et doit être > 0
- Le portfolio est re-filtré sur user=request.user et is_active=True dans la vue avant d'atteindre le service
- Une direction inconnue est rejetée explicitement (pas de valeur par défaut silencieuse)

**Historique des transferts Wallet ↔ Portfolio**
<br>_Liste paginée (20/page) des Transfer de l'utilisateur avec direction, montant, portfolio et statut._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:transfer_history`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/transfer_history.html`

- Filtré sur user=request.user, tri -created_at, select_related('portfolio')
- Aucun filtre ni recherche aujourd'hui : seulement la pagination

**Pont Wallet → Portfolio (reflet comptable automatique)**
<br>_Dès qu'une WalletTransaction DEPOSIT ou WITHDRAWAL passe à SUCCEEDED, une CashLedgerEntry est créée sur le portfolio par défaut de l'utilisateur et les soldes du portfolio sont recalculés._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/signals.py:sync_wallet_transaction_to_portfolio`

- Déclenché UNIQUEMENT si status == 'SUCCEEDED' ET tx_type in (DEPOSIT, WITHDRAWAL) : une transaction PENDING ne doit jamais créer d'écriture portfolio (test de non-régression existant)
- Idempotence par (reference_type='WALLET_TRANSACTION', reference_id=str(tx.id)) : l'existence d'une CashLedgerEntry avec ce couple court-circuite toute nouvelle écriture — chaque sauvegarde ultérieure de la transaction repasse dans le signal
- Les retraits sont écrits en montant NÉGATIF dans le ledger portfolio, les dépôts en positif
- Le portfolio cible est le premier actif trié -is_default puis -created_at ; s'il n'y en a aucun, on log un warning et on sort sans erreur (test dédié : un dépôt sans portfolio ne doit pas crasher)
- Le bloc entier est entouré d'un try/except Exception avec log.exception : une défaillance du pont ne doit JAMAIS faire échouer la confirmation du dépôt ni le webhook appelant
- Le choix du signal plutôt que du service est délibéré (commenté dans le code) : le crédit arrive par webhook, admin ou tâche, et le signal garantit la synchro quel que soit le chemin

**Back-office staff — liste des wallets clients**
<br>_Liste paginée (30/page) de tous les wallets avec recherche par email ou username, affichant disponible, bloqué et total déposé._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_wallet_list`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/admin/wallet_list.html`

- @staff_member_required : réservé au staff Django, pas de rôle métier intermédiaire aujourd'hui
- Recherche OR insensible à la casse sur user__email et user__username
- Tri -updated_at

**Back-office staff — détail d'un wallet client**
<br>_Affiche le wallet d'un client avec ses 20 dernières transactions, 10 derniers retraits et 20 dernières écritures de ledger._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_wallet_detail`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/admin/wallet_detail.html`

- @staff_member_required ; aucun filtrage par propriétaire (c'est l'intention : vue transverse)
- Le template actuel n'affiche que les transactions ; withdrawals et ledger_entries sont passés au contexte mais NON rendus — fonctionnalité prévue mais incomplète, à finaliser en React plutôt qu'à reproduire telle quelle

**Back-office staff — file des demandes de retrait**
<br>_Liste paginée (30/page) de toutes les WithdrawalRequest, filtrable par statut (PENDING, UNDER_REVIEW, APPROVED, PAID)._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_withdrawal_queue`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/admin/withdrawal_queue.html`

- @staff_member_required, tri -created_at, select_related sur wallet, wallet__user, payment_method, reviewed_by
- Le filtre du template n'expose que 4 statuts alors que le modèle en compte 7 (REJECTED, FAILED, CANCELLED absents du select) : à compléter en refonte, c'est une lacune et non une règle

**Back-office staff — détail et contrôle d'une demande de retrait**
<br>_Fiche de contrôle d'un retrait avec destination, provider, référence, frais, transactions liées, et les trois formulaires d'action (approuver, rejeter, marquer payé)._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_withdrawal_detail`, `/Users/ogahserge/Documents/leoTrade/backend/templates/wallet/admin/withdrawal_detail.html`

- @staff_member_required
- related_transactions est calculé par (wallet, tx_type='WITHDRAWAL', amount=withdrawal.amount) : rapprochement par MONTANT, donc potentiellement ambigu — affichage uniquement, ne jamais s'en servir pour muter quoi que ce soit (le service utilise metadata['wallet_transaction_id'])

**Back-office staff — approuver un retrait**
<br>_Passe la demande en APPROVED, enregistre le réviseur, la date de revue et une note interne._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_withdrawal_approve`

- TRANSITION D'ÉTAT STRICTE : approbation autorisée uniquement depuis PENDING ou UNDER_REVIEW, sinon message d'erreur et aucune mutation
- @staff_member_required + @require_POST
- L'approbation NE touche PAS aux soldes : les fonds restent locked. Le déblocage n'intervient qu'à mark-paid (sortie définitive) ou reject (retour vers available)
- reviewed_by, reviewed_at et admin_note sont écrits dans la même sauvegarde que le statut

**Back-office staff — rejeter un retrait et débloquer les fonds**
<br>_Rejette la demande, restitue les fonds verrouillés vers le solde disponible et marque la transaction liée en FAILED._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_withdrawal_reject`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:WalletService.reject_withdrawal`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:WalletService._get_linked_transaction`

- TRANSITION STRICTE : rejet autorisé depuis PENDING, UNDER_REVIEW ou APPROVED (un retrait déjà APPROVED peut encore être rejeté), jamais depuis PAID
- Le déblocage passe par WalletLedgerService.unlock(to_available=True) avec external_event_id = 'withdrawal-rejected:<withdrawal.id>' : idempotent, un double clic ne crédite pas deux fois
- Un motif est obligatoire côté formulaire (textarea required) et un motif par défaut est appliqué côté serveur si vide
- La WalletTransaction liée est retrouvée en PRIORITÉ via metadata['wallet_transaction_id'], et seulement en repli par (montant + status PENDING + plus récente) — ce fallback est ambigu si deux retraits ont le même montant, il doit disparaître au profit d'un FK explicite
- La transaction liée ne bascule en FAILED que si elle est encore PENDING
- Tout le service est @transaction.atomic : déblocage et changement de statut sont indissociables

**Back-office staff — marquer un retrait comme payé**
<br>_Confirme le paiement externe : sortie définitive des fonds verrouillés, incrément de total_withdrawn, statut PAID et transaction liée en SUCCEEDED._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/views.py:admin_withdrawal_mark_paid`, `/Users/ogahserge/Documents/leoTrade/backend/wallet/services.py:WalletService.mark_withdrawal_paid`

- TRANSITION STRICTE : autorisé uniquement depuis APPROVED ou UNDER_REVIEW — jamais depuis PENDING (un retrait non revu ne peut pas être payé) ni depuis PAID
- unlock(to_available=False) avec external_event_id = 'withdrawal-paid:<withdrawal.id>' : les fonds sortent de locked SANS revenir dans available, et total_withdrawn est incrémenté. Idempotent
- provider par défaut = provider existant sinon 'MANUAL' ; provider_reference externe saisie par le staff
- La transaction liée ne passe à SUCCEEDED que si elle est encore PENDING — et ce passage à SUCCEEDED déclenche en cascade le signal sync_wallet_transaction_to_portfolio qui écrit une CashLedgerEntry NÉGATIVE sur le portfolio par défaut. Cet effet de bord est voulu : ne pas le rompre en changeant le statut autrement que via ce service
- @transaction.atomic sur l'ensemble

**Administration Django native des objets wallet**
<br>_ModelAdmin enregistrés pour Wallet, PaymentMethod, WalletTransaction, WithdrawalRequest et ProviderWebhookEvent, avec listes, filtres, recherche et champs en lecture seule._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/wallet/admin.py`

- Les champs created_at, updated_at, processed_at (transactions) et created_at, updated_at, reviewed_at, paid_at (retraits) sont en readonly_fields : les horodatages ne sont jamais éditables à la main
- ATTENTION : WalletAdmin rend available_balance et locked_balance éditables en liste, ce qui contourne entièrement la règle d'or du ledger. À verrouiller lors de la refonte (readonly + action d'ajustement passant par WalletLedgerService)
- PayoutDestination, WalletLedgerEntry, PaymentProviderAccount et WalletTransferIntent ne sont PAS enregistrés dans l'admin

**Solde wallet dans le contexte global de l'interface**
<br>_Le wallet de l'utilisateur connecté est injecté dans tous les templates (sidebar/header) via un context processor, aux côtés du portfolio par défaut et du mode de trading._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/core/context_processors.py:_safe_wallet`, `/Users/ogahserge/Documents/leoTrade/backend/core/context_processors.py:global_trading_context`

- Lecture défensive : ProgrammingError et OperationalError sont interceptées et renvoient None (le site doit rester affichable avant migrations ou en cas d'incident DB)
- Rien n'est renvoyé si l'utilisateur n'est pas authentifié

**Paiement d'un abonnement IA par le wallet**
<br>_Débite le wallet du prix du plan IA, crée une WalletTransaction de type FEE et active le quota. Consommateur externe du domaine wallet._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/ai_assistant/services.py:QuotaService.pay_with_wallet`

- select_for_update sur le Wallet puis contrôle has_sufficient_balance AVANT création de la transaction, et second filet via InsufficientFundsError du ledger
- La WalletTransaction FEE est créée en PENDING, puis passée à SUCCEEDED après le débit, ou à FAILED si le solde est insuffisant : aucune transaction FEE ne doit rester en PENDING
- external_event_id = 'ai-quota-wallet:<wallet_tx.id>' : idempotence par transaction, pas par plan
- L'ensemble est @transaction.atomic : pas de plan activé sans débit effectif
- Le type FEE n'est pas repris par le pont Wallet→Portfolio (limité à DEPOSIT/WITHDRAWAL) : un paiement d'abonnement n'impacte donc pas le ledger portfolio — comportement voulu

**Garde-fou wallet pour l'émission de signaux de stratégie**
<br>_Une stratégie ne peut pas émettre de signal si le wallet de l'utilisateur est inactif ou sans solde disponible._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/strategies/services/risk_guard.py:StrategyRiskGuard.wallet_risk_ok`

- wallet absent → autorisé (True) : l'absence de wallet ne bloque pas, seul un wallet explicitement inactif ou à solde nul bloque
- wallet.is_active == False → blocage 'Wallet inactif'
- wallet.available_balance <= 0 → blocage 'Aucun solde disponible' — c'est le solde DISPONIBLE, pas le total : des fonds verrouillés en retrait bloquent donc l'émission de signaux. Comportement à préserver

</details>

<details><summary>Pièges de migration repérés</summary>

- ZÉRO endpoint REST sur tout le domaine : les 20 URLs wallet sont des vues Django avec templates, redirections 303 vers les providers et messages framework. api/serializers/actions.py:DepositWithdrawSerializer existe mais n'est importé nulle part (code mort). Toute l'API wallet est à écrire de zéro.
- Logique métier enfouie dans les vues, à remonter en service avant de pouvoir la partager Web/Mobile : le contrôle KYC (_can_user_withdraw), le masquage de destination (_mask_destination), l'unicité de la destination par défaut (3 vues qui font chacune leur propre update is_default=False), la génération du request_id de transfert, le parsing du montant de transfert (Decimal sur une chaîne avec virgule), et les trois contrôles de transition d'état des retraits (approve/reject/mark-paid) qui sont codés dans les vues admin et non dans WalletService.
- Deux couches de service coexistent : WalletService (legacy) et WalletLedgerService (services_v2). WalletService.credit_wallet mute directement wallet.available_balance et total_deposited sans passer par le ledger, en violation de la règle d'or du module — elle n'est appelée nulle part aujourd'hui, c'est une bombe à retardement à supprimer plutôt qu'à porter.
- Le répertoire wallet/services/ est entièrement mort : wave.py, stripe.py, paystack.py, adyen.py, mtn_momo.py, orange_money.py, payout_service.py, wallet_service.py et reconciliation.py sont des fichiers VIDES (0 octet), il n'y a pas d'__init__.py (donc `from .services import` résout vers services.py), et BaseWalletProvider / WalletProviderRegistry ne sont importés nulle part. Ne pas les compter comme fonctionnalités : il n'y a ni Wave, ni MTN MoMo, ni Orange Money, ni CinetPay, ni réconciliation implémentés, malgré leur présence dans les PROVIDER_CHOICES des modèles.
- Trois modèles sont déclarés et migrés mais jamais utilisés par aucun service, vue ou template : PaymentProviderAccount (comptes fournisseurs, credentials, webhook_secret), WalletTransferIntent (intents de transfert, checkout_url, operator, external_reference) et, de fait, PaymentMethod (jamais créé, seulement FK sur WithdrawalRequest et exposé en admin). Les champs kind / source_provider / destination_provider / exchange_rate / gross_amount / net_amount / fee_amount / external_status / idempotency_key de WalletTransaction ne sont jamais renseignés par le code, idem gross_amount / net_amount / submitted_at / destination (FK) / payment_method de WithdrawalRequest. Migrer la structure sans inventer le comportement associé.
- Le parcours Adyen est un cul-de-sac fonctionnel : la session serveur est bien créée, mais le template affiche le JSON brut dans un <pre> et ne monte jamais le Drop-in. Aucun dépôt Adyen ne peut aboutir depuis l'UI. Le webhook Adyen, lui, est complet. Décider explicitement : finir l'intégration ou retirer Adyen de DepositForm.PROVIDER_CHOICES.
- PayoutService.submit_withdrawal est un stub documenté (« MVP ») qui se contente de passer le statut à UNDER_REVIEW. Aucun payout automatique n'existe : tout retrait exige une action staff manuelle (approve puis mark-paid). Ne pas présumer d'un virement automatisé dans l'UX cible.
- Idempotence du crédit de dépôt en demi-teinte : le chemin webhook (external_event_id 'paystack:webhook:<event>') et le chemin callback (external_event_id 'paystack:verify:<id>') produisent deux clés DIFFÉRENTES pour le même paiement. Ce qui empêche réellement le double crédit, c'est le select_for_update + le contrôle tx.status != PENDING dans WalletService.confirm_deposit. Toute refonte qui relâcherait ce contrôle d'état rouvrirait un double-crédit malgré le ledger idempotent.
- L'idempotence du ledger repose sur une recherche JSON non indexée : _resolve_existing_entry filtre sur metadata__external_event_id sans contrainte d'unicité ni index en base. Sous charge, deux appels concurrents avec la même clé peuvent passer les deux (la protection réelle vient du select_for_update sur Wallet, pas de cette lecture). Ajouter une colonne external_event_id UNIQUE sur WalletLedgerEntry lors de la migration.
- Rapprochement WithdrawalRequest ↔ WalletTransaction par MONTANT en repli (_get_linked_transaction) : si deux retraits PENDING ont le même montant, le mauvais objet peut être muté. Le FK explicite existe déjà côté WithdrawalRequest.metadata['wallet_transaction_id'] ; le fallback doit être supprimé et remplacé par un vrai ForeignKey en base.
- Unicité de la destination par défaut purement applicative, sans contrainte DB, implémentée trois fois (create, update, set_default) avec des portées différentes (exclude(pk) vs update global). Risque de deux destinations par défaut en concurrence.
- WalletAdmin rend available_balance et locked_balance directement éditables : un staff peut modifier un solde sans écriture au grand livre, ce qui casse l'invariant de reconstruction depuis le ledger. À neutraliser avant toute mise en service d'un back-office.
- Cohérence multi-devises non tenue : Wallet.currency vaut USD par défaut, PayoutDestination est en XOF/CI par défaut, le payload Adyen force countryCode='US', et aucune conversion n'existe (exchange_rate n'est jamais écrit). La règle « devise du dépôt == devise du wallet » est stricte, mais rien ne vérifie que la devise de la destination de retrait correspond à celle du wallet. Trou métier à arbitrer avant la refonte mobile.
- WalletLedgerService.credit incrémente total_deposited sur TOUT crédit, y compris un rapatriement Portfolio→Wallet : l'indicateur « Total déposé » affiché sur le dashboard surestime les dépôts externes. Corriger ce comportement changera des chiffres visibles par les utilisateurs — décision produit à prendre explicitement.
- Aucune tâche Celery, aucun consumer WebSocket et aucune notification (e-mail, push, in-app, SMS) sur ce domaine. Un dépôt crédité, un retrait approuvé, rejeté ou payé ne notifie personne et ne rafraîchit aucune UI. Les exigences temps réel et notifications de la refonte sont donc entièrement à construire ; règle à respecter dès la conception : une notification qui échoue ne doit jamais faire échouer le crédit ni le webhook (même discipline que le pont portfolio, protégé par un try/except global).
- admin_note (note interne staff) et withdrawal.metadata sont rendus dans le template utilisateur withdrawal_detail.html, et transaction.metadata brute dans transaction_detail.html. Prévoir deux serializers distincts (utilisateur / staff) sous peine de fuir des informations internes ou des payloads provider dans l'API publique.
- Pas de rate limiting ni de throttling sur les vues de dépôt, de retrait et de transfert (aucun décorateur ratelimit dans l'app). À ajouter au niveau DRF lors de l'exposition API, les endpoints monétaires étant des cibles privilégiées.
- RBAC limité à @staff_member_required (booléen is_staff) : il n'existe aucun rôle intermédiaire finance/ops, ni séparation des pouvoirs entre celui qui approuve et celui qui marque payé — un même staff peut enchaîner approve puis mark-paid sur la même demande. À arbitrer lors de la refonte RBAC.
- Le filtre de statut de la file des retraits n'expose que 4 statuts sur 7 (REJECTED, FAILED, CANCELLED absents) et le template admin_wallet_detail reçoit withdrawals et ledger_entries sans les afficher : ce sont des écrans inachevés, pas des règles métier. Ne pas reproduire ces lacunes à l'identique.
- Les statuts PROCESSING (WalletTransaction) et CANCELLED (WalletTransaction, WithdrawalRequest) ainsi que les types ADJUSTMENT, TRADE_LOCK, TRADE_RELEASE, REFUND sont proposés dans les filtres de l'historique mais aucun code ne les produit. Aucune fonctionnalité d'ajustement manuel, de remboursement ni d'annulation n'existe aujourd'hui.
- Aucun export (CSV/PDF) de l'historique des transactions ou des transferts n'existe, alors que la refonte en prévoit : fonctionnalité nouvelle, pas une reprise.

</details>

---

### notifications-realtime

`36 fonctionnalités` — API : **5 prêtes, 12 partielles, 19 à exposer**

**Modèles** : `Notification`, `NotificationPreference`, `NotificationTemplate`, `NotificationDeliveryLog`, `OutboxEvent (core, support du dispatch transactionnel)`

**Tâches Celery** : `notifications.tasks.send_notification_task`, `notifications.tasks.retry_failed_notifications_task (beat: */10 min)`, `notifications.tasks.send_daily_trading_report_task (beat: 07:00)`, `notifications.tasks.send_weekly_trading_report_task (beat: lundi 07:00)`, `notifications.tasks.cleanup_old_notifications_task (beat: 03:00)`, `core.tasks.publish_outbox_events_task (beat: 5s — publie NOTIFICATION_DISPATCH_REQUESTED et les broadcasts temps réel)`, `core.tasks.cleanup_published_outbox_events_task (beat: quotidien)`

**Canaux WebSocket** : `ws/notifications/ → NotificationCenterConsumer, groupe user_notifications_{user_id}`, `ws/orders/ → UserOrdersConsumer, groupe user_orders_{user_id}`, `ws/portfolio/<portfolio_id>/ → PortfolioConsumer, groupe portfolio_{portfolio_id}`, `ws/dashboard/live/ → DashboardConsumer, groupe user_dashboard_{user_id}`, `ws/ai/radar/ → AIRadarConsumer, groupe user_ai_{user_id}`, `ws/market/candles/<asset_id>/<timeframe>/ → CandleConsumer, groupe candles_{asset_id}_{timeframe}`, `ws/assistant/chat/ et ws/assistant/conversation/<conversation_id>/ → AssistantConsumer (domaine IA, même stack Channels)`, `Type channel-layer unique pour les broadcasts: 'broadcast.message' avec {event_type, payload}; exceptions: 'candle_update' (importer Deriv) et 'assistant.stream' (IA)`, `Backend channel layer: channels_redis (CHANNELS_REDIS_URL/REDIS_URL, db 2 par défaut), InMemoryChannelLayer en test`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Émission d'une notification (point d'entrée unique)** | ❌ | WEB/MOBILE | ⚡ | Émission purement interne, et c'est volontaire: aucun endpoint ne doit permettre à un client de fabriquer une notification. À conserver tel quel en refonte (service backend uniquement). |
| **Registre canonique des événements** | ❌ | WEB/MOBILE |  | Aucun endpoint n'expose la liste des événements/catégories/sévérités. Le centre web la reçoit par le contexte de template. Pour React/Flutter il faut un endpoint de référentiel (GET /notifications/event-types/ ou /meta/) sinon les filtres et l'écran de préférences devront dupliquer la liste côté client. |
| **Résolution des canaux effectifs** | ❌ | WEB/MOBILE |  | Logique purement serveur, ne doit jamais être réimplémentée côté client. Aucun gap: à garder dans le service. |
| **Anti-spam (rate limit par utilisateur et type d'événement)** | ❌ | WEB/MOBILE |  | Aucun endpoint; aucun besoin client. Attention en refonte: le compteur vit dans le cache Django (Redis en prod, LocMem en test) — ne pas le basculer vers un cache non partagé entre workers. |
| **Déduplication explicite par clé métier** | ❌ | WEB/MOBILE |  | Interne au backend, pas d'exposition nécessaire. |
| **Dispatch transactionnel via Outbox puis Celery** | ❌ | WEB/MOBILE | ⚡ | Infrastructure interne. Pas d'exposition client; à conserver intégralement, c'est ce qui garantit l'atomicité trade↔notification. |
| **Envoi multicanal + mise à jour du statut agrégé** | ❌ | WEB/MOBILE | ⚡ | Interne. |
| **Canal Email (prioritaire)** | ❌ | WEB/MOBILE |  | Canal serveur, sans surface client. Les gabarits email HTML/txt doivent être repris tels quels (pas de dépendance au front web). |
| **Canal In-app (push WebSocket)** | 🟡 | WEB/MOBILE | ⚡ | Le push existe mais le client Flutter ne peut pas s'authentifier: AuthMiddlewareStack n'accepte que le cookie de session, pas le JWT. Il manque une middleware d'auth WS par token, et il n'existe AUCUNE notification push native (zéro FCM/APNs dans le dépôt) — app fermée = aucune alerte, y compris pour un kill switch. |
| **Canal SMS (Twilio + agrégateur local Côte d'Ivoire)** | ❌ | WEB/MOBILE |  | Canal serveur. Côté client il manque uniquement la validation/format du numéro (voir préférences). |
| **Canal WhatsApp (Twilio WhatsApp + Meta Cloud API)** | ❌ | WEB/MOBILE |  | Canal serveur. |
| **Gabarits de notification (event × canal × langue)** | ❌ | WEB |  | Gestion des gabarits uniquement en admin Django. Si la refonte doit offrir un back-office de gabarits côté React, il faut créer un CRUD REST complet (aucun endpoint n'existe aujourd'hui). |
| **Journal de livraison par canal** | ❌ | WEB |  | Aucun endpoint. Si le support/admin doit diagnostiquer une livraison depuis le futur back-office React, il faut exposer les logs d'une notification (lecture seule, réservé staff). |
| **Retry automatique des livraisons échouées** | ❌ | WEB/MOBILE |  | Interne. |
| **Centre de notifications web (vue Django)** | 🟡 | WEB/MOBILE | ⚡ | La liste, les filtres et la pagination existent en API, mais trois éléments de cet écran n'y sont pas: le référentiel des choix (event_choices/severity_choices/priority_choices) est injecté par le contexte de template, le libellé lisible de l'événement (get_event_type_display) n'est pas sérialisé, et l'API ne renvoie pas le compteur non-lu dans la réponse de liste. À ajouter pour que React/Flutter reproduisent l'écran sans dupliquer le registre. |
| **Préférences de notification (vue Django)** | ✅ | WEB/MOBILE |  | — |
| **API REST — liste et détail des notifications** | ✅ | WEB/MOBILE |  | — |
| **API REST — compteur non lu** | ✅ | WEB/MOBILE | ⚡ | — |
| **API REST — marquer lu / tout marquer lu** | ✅ | WEB/MOBILE | ⚡ | — |
| **API REST — préférences (lecture et mise à jour partielle)** | ✅ | WEB/MOBILE |  | — |
| **WebSocket — centre de notifications temps réel** | 🟡 | WEB/MOBILE | ⚡ | Authentification WS par cookie de session uniquement (AuthMiddlewareStack) : inutilisable tel quel depuis Flutter avec JWT. Et le push de notification au groupe ne parvient pas au client à cause du handler manquant (voir risques). |
| **Badge non-lu et toasts temps réel (front web existant)** | 🟡 | WEB/MOBILE | ⚡ | Comportement à reproduire intégralement en React (badge + toast) et en Flutter (badge + notification locale). Il n'existe pas d'endpoint de snapshot initial combiné — aujourd'hui le compteur initial arrive par la WebSocket; prévoir GET /unread-count/ au démarrage si la WS n'est pas encore ouverte. |
| **Manager WebSocket client (résilience de connexion)** | 🟡 | WEB/MOBILE | ⚡ | Comportement front à réimplémenter: en React (hook/provider WS avec backoff, versionnement, heartbeat, badge d'état) et en Flutter (web_socket_channel + reconnexion, plus gestion du cycle de vie background/foreground que le code actuel n'a pas à gérer). |
| **Toasts temps réel non persistés (chemin Outbox NOTIFICATION_UPDATE)** | ❌ | WEB/MOBILE | ⚡ | Rien n'est récupérable après coup (aucun endpoint, aucune persistance). Pour la refonte mobile, ces messages doivent soit devenir de vraies Notifications persistées, soit être explicitement acceptés comme perdus hors-ligne. |
| **Rapport quotidien de trading** | 🟡 | WEB/MOBILE |  | Le rapport n'est consultable que comme notification (title/message + payload.report). Pas d'endpoint de rapport structuré: un écran 'Rapports' React/Flutter devrait lire payload.report de la notification, ou un nouvel endpoint doit être créé. |
| **Rapport hebdomadaire de performance** | 🟡 | WEB/MOBILE |  | Idem rapport quotidien. |
| **Purge des notifications anciennes** | ❌ | WEB |  | Interne. Point d'attention pour la migration de données: ne pas rejouer la purge sur la base de production migrée avant d'avoir vérifié les sauvegardes. |
| **Administration des notifications** | ❌ | WEB |  | Entièrement dépendant de l'admin Django. Si l'admin est conservé en refonte, aucun gap; s'il doit disparaître, il faut recréer: renvoi d'une notification, CRUD gabarits, consultation des logs (endpoints staff-only inexistants). |
| **Notification des administrateurs** | ❌ | WEB |  | Interne. |
| **Service de diffusion temps réel (socle)** | ❌ | WEB/MOBILE | ⚡ | Socle serveur. Le contrat d'événements (noms de groupes, event_type, version) doit être documenté et figé pour que React et Flutter partagent la même définition. |
| **Flux WebSocket ordres** | 🟡 | WEB/MOBILE | ⚡ | Auth WS par cookie de session uniquement → inutilisable en JWT depuis Flutter. |
| **Flux WebSocket portefeuille** | 🟡 | WEB/MOBILE | ⚡ | Auth WS par session uniquement; pas de réponse au heartbeat. |
| **Flux WebSocket tableau de bord** | 🟡 | WEB/MOBILE | ⚡ | Auth WS par session uniquement. |
| **Flux WebSocket radar IA** | 🟡 | WEB/MOBILE | ⚡ | Auth WS par session uniquement; pas de heartbeat. |
| **Flux WebSocket bougies de marché** | 🟡 | WEB/MOBILE | ⚡ | Auth WS par session uniquement. |
| **Outil de diagnostic temps réel** | ❌ | WEB | ⚡ | Interne. |

<details><summary>Règles métier invariantes à préserver</summary>

**Émission d'une notification (point d'entrée unique)**
<br>_Toute app du backend émet une notification via notify(user, EVENT_CODE, title, message, payload, severity, priority, channels, dedupe_key). La notification est persistée puis le dispatch est planifié via l'Outbox transactionnel._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/shortcuts.py:notify`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService.notify`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService._notify`

- notify() NE LÈVE JAMAIS vers l'appelant: double try/except (shortcuts + service). Un trade, un ordre ou une fermeture de position ne doit jamais échouer à cause d'une notification. C'est l'invariant n°1 du module.
- user None ou sans pk → retour None silencieux, aucune exception.
- severity et priority non fournis → valeurs par défaut du registre EVENTS (events.py), jamais codées en dur côté appelant.
- La création de la Notification et l'enqueue Outbox sont dans le MÊME transaction.atomic() → pas d'envoi d'une notification dont la ligne serait rollbackée.
- L'enqueue Outbox utilise idempotency_key='notification:{id}:dispatch' → un seul dispatch par notification même si le publisher rejoue.
- statut initial = SUPPRESSED si la catégorie est désactivée OU si la liste de canaux résolus est vide; PENDING sinon (seul PENDING déclenche l'Outbox).
- Aucun secret (clé API broker, token) ne doit transiter dans payload (règle documentée dans models.py et le gabarit email).

**Registre canonique des événements**
<br>_~50 EventSpec immuables (code, label, catégorie, sévérité, priorité, flag critique) servant de source de vérité pour les préférences, les gabarits, les filtres et les choices du modèle._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/events.py:EVENTS`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/events.py:get_event`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/events.py:CATEGORY_PREFERENCE_FIELD`

- get_event() sur un code inconnu retombe sur un EventSpec INFO/TRADE générique au lieu de lever — un code mal orthographié ne casse jamais le flux appelant.
- Événements critical=True: BROKER_ERROR, ORDER_FAILED, HIGH_DRAWDOWN, DAILY/WEEKLY/MONTHLY_LOSS_LIMIT, KILL_SWITCH_ACTIVATED, STRATEGY_CIRCUIT_BREAKER, SECURITY_ALERT, SUSPICIOUS_LOGIN, LIVE_MODE_ENABLED, LIVE_TRADE_CONFIRMATION, CELERY_CRITICAL_ERROR. Ce flag pilote à lui seul: exemption du rate limit, ignorance des quiet hours, forçage de tous les canaux, incompressibilité face à une catégorie désactivée.
- Catégorie ACCOUNT (KYC) est mappée sur le toggle security_events_enabled — il n'existe PAS de toggle KYC dédié.
- event_type est stocké en base avec choices=EVENT_CHOICES: retirer un code du registre casse les lignes historiques (migration de données obligatoire).

**Résolution des canaux effectifs**
<br>_Calcule la liste ordonnée des canaux d'envoi à partir de la criticité de l'événement, de la priorité, des toggles de canal, de la catégorie et des quiet hours._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/preferences.py:NotificationPreferenceService.resolve_channels`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/models.py:NotificationPreference.channel_allowed`

- ORDRE DE DÉCISION STRICT à préserver: (1) catégorie désactivée → sortie anticipée, (2) choix des candidats selon critical/priorité, (3) filtre par toggle de canal, (4) coupe quiet hours, (5) tri final. Inverser (1) et (2) ferait taire un kill switch.
- Catégorie désactivée + événement NON critique → [] avec raison 'category_disabled' → notification créée en SUPPRESSED (tracée, jamais perdue).
- Catégorie désactivée + événement CRITIQUE → retombe sur [IN_APP, EMAIL] filtrés par les toggles de canal. Un kill switch ou une alerte sécurité ne doit jamais passer inaperçu (couvert par test_disabled_category_cannot_silence_critical).
- critical OU priority==URGENT → candidats = [EMAIL, IN_APP, SMS, WHATSAPP]; sinon toujours [EMAIL, IN_APP] (HIGH et NORMAL/LOW donnent actuellement le même résultat).
- SMS autorisé seulement si sms_enabled ET phone_number non vide; WhatsApp seulement si whatsapp_enabled ET (whatsapp_number OU phone_number).
- Quiet hours: pour le NON critique, seul IN_APP survit. Un événement critique ignore totalement les quiet hours.
- Tri final imposé EMAIL(0) < IN_APP(1) < SMS(2) < WHATSAPP(3): l'email est le canal prioritaire par cahier des charges et doit rester en tête de channels_requested.
- Le paramètre `requested` (canaux forcés par l'appelant) court-circuite le choix par criticité mais PAS les filtres de toggle, de catégorie ni les quiet hours.

**Anti-spam (rate limit par utilisateur et type d'événement)**
<br>_Au plus 10 notifications par heure glissante pour un couple (user, event_type), compteur en cache Redis._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:RATE_LIMIT_MAX`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService._rate_limited`

- Les événements critical=True sont TOUJOURS exemptés du rate limit (test: le 11e ORDER_FILLED est bloqué, un KILL_SWITCH ne l'est jamais).
- Une notification rate-limitée n'est PAS créée en base du tout (retour None) — contrairement à une suppression par préférence qui, elle, crée une ligne SUPPRESSED. Cette asymétrie est volontaire et observée par les tests.
- Si le cache est indisponible, _rate_limited renvoie False (fail-open): on préfère spammer que perdre une alerte.
- Fenêtre = 3600 s, max = 10, par (user, event_type) — pas global par utilisateur.

**Déduplication explicite par clé métier**
<br>_dedupe_key optionnel garantissant une seule notification par événement métier unique (un kill switch, un circuit breaker, un ordre)._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService._notify`, `/Users/ogahserge/Documents/leoTrade/backend/risk/services_circuit_breaker.py (dedupe_key=f"circuit_breaker:{event.id}")`

- Implémenté avec cache.add() atomique: le premier gagne, les suivants retournent None. Fenêtre = RATE_LIMIT_WINDOW_SECONDS (1 h).
- Le test de dedupe est évalué AVANT le rate limit — un dedupe_key ne consomme donc pas de quota si la clé existe déjà.
- La dédup est scopée par utilisateur (user.pk dans la clé): notify_admins avec le même dedupe_key notifie bien chaque superuser une fois.
- Dédup en cache, pas en base: un flush Redis réautorise l'émission. Ne pas s'en servir comme garantie d'unicité forte (celle-ci est portée par l'idempotency_key de l'Outbox).

**Dispatch transactionnel via Outbox puis Celery**
<br>_La notification PENDING est publiée par l'Outbox (topic notifications.dispatch.requested.v1), qui déclenche send_notification_task avec un task_id dérivé de l'event_id._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/event_topics.py:NOTIFICATION_DISPATCH_REQUESTED`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/outbox.py:dispatch_notification`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/apps.py:NotificationsConfig.ready (enregistre le handler)`, `/Users/ogahserge/Documents/leoTrade/backend/core/outbox.py:OutboxService.enqueue`, `/Users/ogahserge/Documents/leoTrade/backend/core/outbox.py:OutboxPublisher.publish_pending`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:send_notification_task`

- Le handler Outbox est enregistré dans AppConfig.ready() via l'import de notifications.outbox — si cet import disparaît, publish_pending lève 'No outbox handler registered' et toutes les notifications finissent DEAD.
- task_id=f'outbox-{event.event_id}' → Celery déduplique le rejeu d'un même événement Outbox.
- send_notification_task est idempotente: elle saute les notifications déjà SENT ou SUPPRESSED. ATTENTION: une notification PARTIAL ou FAILED relancée RE-ENVOIE tous les canaux, y compris ceux déjà SENT (pas de filtrage par delivery log) — c'est le chemin du bouton admin 'Renvoyer'.
- Le claim Outbox utilise select_for_update(skip_locked) + statut PROCESSING: pas de double envoi entre workers.
- Backoff exponentiel Outbox (2s × 2^n, plafond 300 s), passage en DEAD après OUTBOX_MAX_ATTEMPTS (8). Les claims PROCESSING bloqués > OUTBOX_LOCK_TIMEOUT_SECONDS (300 s) sont automatiquement réarmés.
- send_notification_task a son propre retry (max_retries=2, delay 10 s) empilé par-dessus le retry Outbox.
- _nudge_publisher déclenche publish_outbox_events_task après commit, avec un verrou cache de 1 s pour éviter la tempête de tâches.

**Envoi multicanal + mise à jour du statut agrégé**
<br>_NotificationService.dispatch boucle sur channels_requested, crée un NotificationDeliveryLog par canal, appelle le service de canal et recalcule status + channels_sent._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService.dispatch`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:CHANNEL_SERVICES`

- Un canal qui lève est capté individuellement: UN CANAL EN ÉCHEC NE DOIT JAMAIS EMPÊCHER LES AUTRES CANAUX de partir (try/except par itération).
- Distinction ok / skipped / failed à préserver absolument: skipped = canal volontairement non envoyé (pas de numéro, provider non configuré) → NE COMPTE PAS comme échec; failed = vraie erreur → entre dans la boucle de retry.
- Calcul du statut agrégé: sent et pas de failed → SENT; sent et failed → PARTIAL; que des failed → FAILED; ni sent ni failed (tout skipped) → SUPPRESSED.
- La langue de rendu vient d'une seule lecture de NotificationPreference (preferred_language, défaut 'fr') et est passée à tous les canaux.
- request_payload du log ne contient que title / event_type / language — jamais le corps rendu ni de donnée sensible.
- Un CHANNEL_SERVICES.get() qui ne trouve pas le canal passe silencieusement (continue) sans créer de log.

**Canal Email (prioritaire)**
<br>_Envoi SMTP via django.core.mail avec gabarit HTML + texte brut, préfixe de sujet [LeoTrade], bandeau CRITIQUE/ATTENTION et CTA vers le centre de notifications._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/email.py:EmailNotificationService.send`, `/Users/ogahserge/Documents/leoTrade/backend/templates/notifications/email/notification.html`, `/Users/ogahserge/Documents/leoTrade/backend/templates/notifications/email/notification.txt`

- Utilisateur sans email → ok=False et skipped ABSENT → compté comme FAILED (asymétrie à noter: SMS/WhatsApp sans numéro sont SKIPPED, l'email sans adresse est FAILED et sera retenté).
- Sujet toujours préfixé '[LeoTrade] ' + sujet rendu par le gabarit.
- Email multipart obligatoire: corps texte + alternative HTML.
- fail_silently=False volontaire: l'erreur SMTP doit remonter dans error_message du delivery log pour alimenter le retry.
- Le pied de page affirme qu'aucune clé API ni donnée sensible ne transite par email — contrat à ne pas violer en ajoutant des variables de gabarit.
- Le CTA n'est affiché que si SITE_URL est défini.

**Canal In-app (push WebSocket)**
<br>_Pousse la notification sur le groupe channel-layer user_notifications_{user_id} avec l'événement notification.created._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/in_app.py:InAppNotificationService.send`, `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:RealtimeBroadcastService.broadcast_notification`

- La vérité est en PostgreSQL, le WebSocket n'est qu'un accélérateur: channel layer indisponible (delivered=False) → le canal est tout de même marqué SENT, avec response.ws_delivered=False. La notification reste lisible dans le centre. Ne jamais transformer ça en échec dur (sinon retry infini sur un Redis down).
- Le payload poussé est aplati: id, kind (severity en minuscules), title, message, event_type, severity, priority, created_at ISO, payload métier.
- 'kind' est dérivé de severity.lower() et sert de type de toast côté front (mapping critical→error, warning→info dans base.html).
- Le payload passe par _normalize_payload (Decimal/datetime/UUID → str) et reçoit automatiquement version=1 (REALTIME_PROTOCOL_VERSION).

**Canal SMS (Twilio + agrégateur local Côte d'Ivoire)**
<br>_Envoi SMS avec chaîne de providers et bascule automatique: primaire configurable (twilio ou local_ci), secours sur l'autre._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/sms.py:SMSNotificationService.send`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/sms.py:_twilio_send`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/sms.py:_local_ci_send`

- Pas de numéro dans les préférences → SKIPPED, jamais FAILED.
- Provider non configuré (credentials manquants) → skipped=True → on passe au suivant SANS log d'erreur; seul un vrai échec réseau/HTTP est loggué en warning puis bascule.
- L'ordre de la chaîne est piloté par NOTIFY_SMS_PRIMARY: 'local_ci' → [local_ci, twilio], sinon [twilio, local_ci].
- Corps tronqué à 320 caractères (2 segments GSM) et préfixé 'LeoTrade — {sujet}'.
- Timeout HTTP de 15 s sur chaque provider: un provider lent ne doit pas bloquer le worker indéfiniment.
- Aucune credential ne doit apparaître dans response_payload (seuls sid, status, http_status et un extrait de corps y sont stockés).

**Canal WhatsApp (Twilio WhatsApp + Meta Cloud API)**
<br>_Même schéma de chaîne de providers que le SMS, avec corps en gras markdown WhatsApp._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/whatsapp.py:WhatsAppNotificationService.send`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/whatsapp.py:_twilio_whatsapp_send`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/whatsapp.py:_cloud_api_send`

- Destinataire = whatsapp_number s'il existe, sinon repli sur phone_number. Absence des deux → SKIPPED.
- Ordre de chaîne piloté par NOTIFY_WHATSAPP_PRIMARY ('cloud_api' → Meta d'abord, sinon Twilio d'abord).
- Cloud API: le '+' initial est retiré du numéro (to.lstrip('+')), Twilio le conserve avec le préfixe whatsapp:.
- Corps tronqué à 1500 caractères, format '*LeoTrade — {sujet}*\n{corps}'.
- Provider non configuré → SKIPPED silencieux, jamais bloquant pour le flux de trading.

**Gabarits de notification (event × canal × langue)**
<br>_NotificationTemplate rendu par le moteur de template Django sur un contexte plat composé des champs standards + Notification.payload._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/renderer.py:NotificationTemplateRenderer.render`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/models.py:NotificationTemplate`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/migrations/0002_seed_templates.py`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/migrations/0003_rebrand_leotrade.py`

- CHAÎNE DE REPLI À 3 NIVEAUX, non négociable: (1) gabarit actif dans la langue demandée, (2) gabarit actif en 'fr', (3) title/message bruts de la Notification. Un gabarit manquant ne doit jamais produire un message vide.
- Une exception de rendu (variable manquante, syntaxe cassée) est capturée et retombe sur title/message bruts — un gabarit mal édité en admin ne doit pas faire échouer l'envoi.
- Sujet ou corps rendu vide → repli sur title/message.
- Contrainte d'unicité (event_type, channel, language) et filtre is_active.
- Le contexte écrase l'ordre: les clés de payload sont fusionnées APRÈS les champs standards — un payload contenant 'title' ou 'message' écrase la valeur standard.
- Les gabarits seedés (LIVE_MODE_ENABLED, LIVE_TRADE_CONFIRMATION, KILL_SWITCH_ACTIVATED, DAILY_LOSS_LIMIT, ORDER_FILLED, STOP_LOSS_HIT, TAKE_PROFIT_HIT, SECURITY_ALERT) sont des DONNÉES de production créées par migration: ils sont modifiables en admin et doivent être préservés lors de la migration (ne jamais rejouer un unseed).
- Seuls EMAIL et SMS ont des gabarits seedés, uniquement en 'fr'. Les variables attendues (symbol, side, stake, currency, stop_loss, take_profit, portfolio_name, reason, loss_percent, pnl, site_url…) doivent continuer d'être fournies par les appelants dans payload.

**Journal de livraison par canal**
<br>_Un NotificationDeliveryLog par tentative et par canal: provider, destinataire, statut, payloads requête/réponse, message d'erreur, compteur de retry, date d'envoi._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/models.py:NotificationDeliveryLog`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/admin.py:DeliveryLogInline`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/admin.py:NotificationDeliveryLogAdmin`

- Statuts: PENDING → SENT | FAILED | SKIPPED | RETRYING. Le log est créé en PENDING AVANT l'appel au provider, pour qu'un crash du worker laisse une trace.
- Entièrement en lecture seule dans l'admin (readonly_fields complet, pas d'ajout via l'inline) — c'est une piste d'audit.
- Cascade: supprimer une Notification supprime ses logs (impacte le cleanup, voir purge).
- error_message tronqué à 1000 caractères côté service et 2000 côté retry; response_payload limité aux métadonnées provider.
- Index (status, retry_count) dédié à la requête de la tâche de retry.

**Retry automatique des livraisons échouées**
<br>_Tâche beat toutes les 10 min qui rejoue les NotificationDeliveryLog FAILED récents et recalcule le statut de la notification._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:retry_failed_notifications_task`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:MAX_DELIVERY_RETRIES`

- Sélection: status=FAILED ET retry_count < 3 ET created_at >= now-24h, trié par created_at, limité à 100. Au-delà de 3 tentatives ou de 24 h, on abandonne définitivement — pas de retry éternel.
- Le backoff effectif EST l'intervalle du beat (10 min): il n'y a pas de backoff interne, ne pas raccourcir le beat sans revoir MAX_DELIVERY_RETRIES.
- Le canal est rejoué SEUL (pas toute la notification) — les canaux déjà SENT ne sont pas re-sollicités.
- Après succès, le canal est ajouté à channels_sent sans doublon, et le statut passe à SENT si channels_sent ⊇ channels_requested, sinon PARTIAL.
- Le statut est fixé à RETRYING avant l'appel au provider, puis SENT ou FAILED — l'état intermédiaire est observable.
- La langue est relue depuis les préférences au moment du retry (peut différer de l'envoi initial).

**Centre de notifications web (vue Django)**
<br>_Page listant les notifications de l'utilisateur avec filtres sévérité / type d'événement / non-lues, pagination 25, compteur non-lu, pastille de sévérité, canaux envoyés, statut, bouton 'Marquer lu' par ligne et 'Tout marquer lu'._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/views.py:notification_center`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/urls.py`, `/Users/ogahserge/Documents/leoTrade/backend/templates/notifications/center.html`

- Cloisonnement strict: queryset filtré sur request.user, @login_required.
- Tri imposé -created_at, pagination 25 par page, conservation des filtres dans les liens de pagination.
- État vide explicite et pédagogique (aucune donnée fictive) avec CTA vers les préférences — règle 'zéro fake data' du projet.
- Le JS de la page appelle déjà l'API DRF (/api/notifications/{id}/mark-read/ et /mark-all-read/) puis recharge la page: la logique métier est déjà côté API, seul le rendu est en template.
- Le filtre de sévérité de la vue web est sensible à la casse (égalité stricte) alors que l'API applique .upper() — comportement à uniformiser en refonte.

**Préférences de notification (vue Django)**
<br>_Formulaire de réglage des 4 canaux, des 6 catégories, des numéros SMS/WhatsApp, des quiet hours et de la langue._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/views.py:notification_preferences`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/preferences.py:NotificationPreferenceService.get_or_create`, `/Users/ogahserge/Documents/leoTrade/backend/templates/notifications/preferences.html`

- get_or_create: la préférence est créée à la volée à la première lecture — aucun utilisateur ne doit se retrouver sans préférence (et les valeurs par défaut valent consentement: email+in-app+toutes catégories activés, SMS/WhatsApp désactivés).
- Parsing POST manuel: une case absente vaut False (sémantique HTML des cases à cocher) — un POST partiel désactive donc tout ce qui n'est pas transmis. Point de vigilance majeur si React envoie un PATCH partiel sur ce même endpoint.
- Champs d'heure vides → None (quiet hours désactivées). Un format d'heure invalide est capté à pref.save() et transformé en message d'erreur, sans 500.
- Troncatures imposées: langue 5, phone_number 30, whatsapp_number 30 caractères.
- Redirection POST→GET après succès avec message Django (pattern PRG).
- Le texte de la page documente deux garanties visibles par l'utilisateur et qui doivent rester vraies: les critiques ignorent les quiet hours, et les critiques restent notifiés en in-app+email même catégorie coupée.

**API REST — liste et détail des notifications**
<br>_ViewSet DRF en lecture seule, paginé, avec 7 filtres de requête._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/api.py:NotificationViewSet.get_queryset`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/api.py:NotificationPagination`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/serializers.py:NotificationSerializer`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/urls_api.py`

- Isolation multi-utilisateur absolue: get_queryset filtre sur request.user → un id d'autrui renvoie 404, pas 403 (couvert par test_api_user_isolation).
- ReadOnlyModelViewSet: aucune création/suppression de notification via l'API, par conception.
- Tous les champs du serializer sont read_only — le client ne peut muter une notification que par les actions dédiées.
- severity, priority et status sont normalisés en majuscules côté serveur (?severity=critical fonctionne); event_type est comparé tel quel.
- unread n'accepte que 'true' ou '1'; since/until acceptent de l'ISO8601 et sont ignorés silencieusement si non parsables.
- Pagination PageNumber: 25 par défaut, 100 maximum.
- Tri figé -created_at.
- Auth: SessionAuthentication + JWT (rest_framework_simplejwt), permission IsAuthenticated.

**API REST — compteur non lu**
<br>_Renvoie le nombre de notifications non lues de l'utilisateur courant._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/api.py:NotificationViewSet.unread_count`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService.unread_count`

- Définition unique du non-lu: read_at IS NULL, sur le périmètre de l'utilisateur. La même méthode de service alimente l'API, le WebSocket et la vue web — ne jamais la dupliquer.
- Index composite (user, read_at) prévu pour cette requête.

**API REST — marquer lu / tout marquer lu**
<br>_Marque une notification lue, ou toutes les non-lues de l'utilisateur, et renvoie le compteur mis à jour._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/api.py:NotificationViewSet.mark_read`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/api.py:NotificationViewSet.mark_all_read`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/models.py:Notification.mark_read`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/services/core.py:NotificationService.mark_all_read`

- mark_read est IDEMPOTENT: si read_at est déjà renseigné, la date n'est pas écrasée (on garde la première lecture) et aucune écriture n'a lieu.
- mark_all_read fait un UPDATE en masse filtré read_at IS NULL (ne réécrit pas les déjà lues) et renvoie le nombre réellement marqué.
- La réponse embarque systématiquement le compteur non-lu recalculé, pour que le client n'ait pas à faire un second appel (contrat utilisé par center.html).
- mark_all_read ne met pas à jour updated_at (UPDATE direct, auto_now non déclenché) — à savoir si la refonte s'appuie sur updated_at pour une synchro delta.
- L'accès passe par get_object() → le cloisonnement par utilisateur s'applique (404 sur une notification d'autrui).

**API REST — préférences (lecture et mise à jour partielle)**
<br>_Lit ou met à jour les 15 champs de préférence via un seul endpoint._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/api.py:NotificationViewSet.preferences`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/serializers.py:NotificationPreferenceSerializer`

- get_or_create garantit une réponse même pour un utilisateur n'ayant jamais ouvert la page.
- PATCH strictement partiel: contrairement au POST de la vue web, un champ omis conserve sa valeur. Les deux surfaces ont donc des sémantiques opposées sur les booléens.
- L'utilisateur est implicite (request.user): aucun champ user dans le serializer, impossible de modifier les préférences d'autrui.
- Aucune validation de format des numéros de téléphone (ni E.164 ni longueur minimale) — un numéro invalide produira un échec de livraison, pas une erreur 400.

**WebSocket — centre de notifications temps réel**
<br>_Consumer /ws/notifications/ : envoie le badge non-lu à la connexion, relaie les nouvelles notifications et accepte les actions mark_read / mark_all_read / get_unread_count / ping._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/consumers.py:NotificationCenterConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/routing.py`, `/Users/ogahserge/Documents/leoTrade/backend/leoTrade/asgi.py`

- Utilisateur non authentifié → close(4401). AllowedHostsOriginValidator + AuthMiddlewareStack en amont.
- accept() AVANT group_add: si Redis est indisponible la WebSocket reste vivante en mode isolé au lieu de déclencher une boucle de reconnexion côté client. Pattern résilient commun à tous les consumers du projet, à conserver.
- Le badge non-lu est renvoyé après CHAQUE action mutante et à la connexion — le client n'a jamais à recalculer le compteur.
- mark_read via WS est filtré sur self.scope['user'] (pas d'accès croisé) et réutilise Notification.mark_read (donc idempotent).
- group_discard au disconnect est encapsulé dans un try/except silencieux.
- Format sortant {"type": …} spécifique à ce consumer, différent du {"event": …, "payload": …} des autres streams — base.html teste bien data.type.
- DÉFAUT CONNU: le consumer n'implémente PAS de handler broadcast_message alors que RealtimeBroadcastService envoie au groupe un message de type 'broadcast.message'. channels.consumer.dispatch lève alors ValueError('No handler for message type broadcast.message'). Le handler notification_created présent n'est jamais appelé car aucun émetteur n'envoie le type 'notification.created'.

**Badge non-lu et toasts temps réel (front web existant)**
<br>_La base de template ouvre la WebSocket notifications, met à jour le badge de la sidebar et affiche un toast LeoAnim pour chaque notification reçue._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/templates/layout/base.html`, `/Users/ogahserge/Documents/leoTrade/backend/static/js/leo_websocket.js`, `/Users/ogahserge/Documents/leoTrade/backend/static/js/leo_bootstrap.js`

- Badge masqué si compteur = 0, affiché '99+' au-delà de 99.
- Mapping de sévérité vers type de toast: critical→error, warning→info, tout type inconnu→info (liste blanche success/error/info).
- Le manager n'écrit jamais dans le DOM lui-même: tout passe par le callback onMessage, pour garder la maîtrise de l'échappement (règle de sécurité documentée dans leo_websocket.js).
- Absence de LeoWS → dégradation silencieuse (warning console), la page reste fonctionnelle.

**Manager WebSocket client (résilience de connexion)**
<br>_Couche LeoWS: reconnexion à backoff exponentiel avec jitter, heartbeat, buffer de sortie, déduplication des messages, contrôle de version de protocole et état de connexion partagé._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/static/js/leo_websocket.js`, `/Users/ogahserge/Documents/leoTrade/backend/templates/_partials/_disconnect_badge.html`, `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:REALTIME_PROTOCOL_VERSION`

- Backoff 1s→2s→4s…plafonné à 60 s, jitter ±20 % pour éviter l'effet troupeau à la reconnexion, plancher 500 ms.
- Versionnement du protocole: un payload dont payload.version > PROTOCOL_VERSION client est IGNORÉ. Le serveur force version=1 dans tout payload via _normalize_payload. Toute évolution de schéma doit incrémenter cette version, pas casser les onglets ouverts.
- Heartbeat client {action:'ping'} toutes les 25 s — tous les consumers doivent continuer de répondre à 'ping'.
- Déduplication des messages identiques dans une fenêtre de 200 ms (clé event|id|début du payload).
- Buffer d'envoi de 500 messages maximum pendant une coupure.
- Réutilisation d'une connexion vivante vers la même URL au lieu de la fermer/recréer (évite 'WebSocket is closed before the connection is established' sur double init Alpine).
- L'état global agrégé (online/reconnecting/offline) pilote tous les badges de la page, avec accessibilité role=status/aria-live.

**Toasts temps réel non persistés (chemin Outbox NOTIFICATION_UPDATE)**
<br>_Chemin parallèle au module notifications: TradingNotificationService.notify_error / notify_success poussent un message de toast vers user_notifications_{id} via l'Outbox, SANS créer de Notification en base._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/execution/notifications.py:TradingNotificationService.notify_error`, `/Users/ogahserge/Documents/leoTrade/backend/execution/notifications.py:TradingNotificationService.notify_success`, `/Users/ogahserge/Documents/leoTrade/backend/execution/outbox.py:publish_notification_update`, `/Users/ogahserge/Documents/leoTrade/backend/leo_backtesting/tasks.py:_notify_user_backtest_done`, `/Users/ogahserge/Documents/leoTrade/backend/leo_backtesting/tasks.py:_notify_user_backtest_failed`

- Ces messages sont ÉPHÉMÈRES: rien n'est persisté, ils n'apparaissent ni dans le centre ni dans le compteur non-lu. Un utilisateur déconnecté les perd définitivement — c'est le comportement actuel et il concerne des erreurs d'exécution d'ordre.
- Contrairement au canal in-app, ce chemin EXIGE la livraison: _require_delivery lève OutboxDeliveryError si le channel layer refuse, ce qui met l'événement Outbox en retry puis DEAD. Asymétrie délibérée à ne pas uniformiser sans décision.
- Appelé sans enveloppe de sécurité depuis execution/services.py (notify_error aux points d'échec de soumission/annulation) et execution/reconciliation.py.
- Les broadcasts de backtesting (leo_backtesting) passent directement par RealtimeBroadcastService, hors Outbox, et sont best-effort (try/except).

**Rapport quotidien de trading**
<br>_Tâche beat 07:00 calculant les statistiques réelles sur 24 h (ordres, trades clos, PnL réalisé, équité) et émettant DAILY_TRADING_REPORT._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:send_daily_trading_report_task`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:_portfolio_day_stats`

- ZÉRO RAPPORT VIDE: si l'utilisateur n'a aucun ordre, aucun trade clos et aucun portefeuille actif sur la période, _portfolio_day_stats renvoie None et aucune notification n'est créée. Règle 'zéro fake data' du projet.
- Ciblage: utilisateurs actifs avec notification_preference__reports_enabled=True — un utilisateur sans préférence (jointure absente) n'est PAS ciblé.
- Les données proviennent de l'exécution et du portefeuille réels (execution.Order, portfolio.Portfolio, portfolio.models_trade.Trade), jamais de valeurs simulées.
- orders_rejected agrège REJECTED + FAILED.
- L'import de Trade est en try/except: l'absence du modèle dégrade le rapport sans le faire échouer.
- Catégorie REPORT, sévérité INFO, priorité LOW → canaux [EMAIL, IN_APP], donc coupé par les quiet hours (non critique).

**Rapport hebdomadaire de performance**
<br>_Tâche beat lundi 07:00, même moteur de statistiques sur 7 jours, avec calcul du win rate, émettant WEEKLY_PERFORMANCE_REPORT._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:send_weekly_trading_report_task`

- Mêmes garde-fous que le rapport quotidien (pas d'activité → pas de rapport, filtrage reports_enabled).
- Win rate affiché '—' quand aucun trade n'est clos: jamais de division par zéro ni de 0 % trompeur.
- Le payload porte period='weekly' pour distinguer les deux rapports côté client.

**Purge des notifications anciennes**
<br>_Tâche beat quotidienne 03:00 supprimant les notifications lues de plus de 60 jours et les non lues de plus de 180 jours._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:cleanup_old_notifications_task`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:CLEANUP_READ_AFTER_DAYS`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/tasks.py:CLEANUP_UNREAD_AFTER_DAYS`

- Rétention asymétrique volontaire: 60 jours après LECTURE pour les lues, 180 jours après CRÉATION pour les non lues — une alerte jamais lue vit trois fois plus longtemps.
- Suppression DURE (delete), pas de soft-delete: les NotificationDeliveryLog partent en cascade, la piste d'audit de livraison disparaît avec la notification.
- Une notification non lue de plus de 180 jours est supprimée même si elle est critique: aucune exemption par sévérité aujourd'hui.

**Administration des notifications**
<br>_Back-office Django: consultation des notifications (filtres, recherche, hiérarchie de dates), inline des logs de livraison, action de renvoi en masse, administration des préférences et des gabarits._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/admin.py:NotificationAdmin.resend_notifications`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/admin.py:NotificationTemplateAdmin`, `/Users/ogahserge/Documents/leoTrade/backend/notifications/admin.py:NotificationPreferenceAdmin`

- Notification et DeliveryLog sont intégralement en lecture seule: un administrateur ne peut pas réécrire l'historique, seulement relancer un envoi.
- L'action de renvoi repasse le statut à PENDING puis appelle send_notification_task.delay() DIRECTEMENT (pas via l'Outbox) — elle contourne donc la garantie transactionnelle et re-déclenche TOUS les canaux, y compris ceux déjà livrés.
- Les gabarits sont la seule entité réellement éditable: l'admin est aujourd'hui le seul outil d'édition du contenu des messages.

**Notification des administrateurs**
<br>_notify_admins diffuse un événement à tous les superusers actifs (erreurs système, sécurité, circuit breaker de stratégie)._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/notifications/shortcuts.py:notify_admins`, `/Users/ogahserge/Documents/leoTrade/backend/risk/services_circuit_breaker.py`

- Cible = is_superuser=True ET is_active=True — un admin désactivé n'est plus notifié.
- Enveloppé dans un try/except global: une erreur d'énumération des admins ne casse jamais l'appelant (ici, la coupure d'une stratégie dégradée ne doit pas être annulée par un problème de notification).
- Chaque admin reçoit sa propre Notification (boucle), donc le dedupe_key fourni s'applique par utilisateur.

**Service de diffusion temps réel (socle)**
<br>_RealtimeBroadcastService: normalisation JSON des payloads, versionnement du protocole, nommage canonique des groupes et diffusion différée après commit._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:RealtimeBroadcastService._send`, `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:RealtimeBroadcastService._normalize_payload`, `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:RealtimeBroadcastService.broadcast_after_commit`

- _send ne lève JAMAIS: absence de channel layer → warning + retour False; exception → log + retour False. C'est l'appelant (ou l'Outbox) qui décide si l'échec est bloquant.
- Normalisation récursive obligatoire: Decimal, datetime/date et UUID sont convertis en chaînes avant envoi — indispensable car le channel layer sérialise en msgpack/JSON.
- version=REALTIME_PROTOCOL_VERSION est injecté par setdefault (une version fournie par l'appelant n'est pas écrasée). Les clients ignorent les versions supérieures.
- Le type de message channel-layer est TOUJOURS 'broadcast.message' (Channels le mappe sur le handler broadcast_message). Tout consumer abonné à un de ces groupes DOIT implémenter broadcast_message, sinon Channels lève ValueError et tue la connexion.
- broadcast_after_commit existe pour les appelants en transaction ouverte: un consumer ne doit jamais voir un événement correspondant à un état rollbacké. Repli sur envoi immédiat hors transaction.
- Les noms de groupes sont centralisés ici (portfolio_group, user_orders_group, user_notifications_group, dashboard_group, user_ai_group, candles_group) — ne jamais les reconstruire à la main ailleurs.

**Flux WebSocket ordres**
<br>_Stream par utilisateur des mises à jour d'ordres (création, soumission, exécution, annulation), alimenté par l'Outbox._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/execution/consumers.py:BaseUserStreamConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/execution/consumers.py:UserOrdersConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/execution/outbox.py:publish_order_update`, `/Users/ogahserge/Documents/leoTrade/backend/execution/notifications.py:TradingNotificationService`

- Anonyme → close(4001). Le groupe est dérivé de l'id utilisateur: pas de paramètre d'URL, donc pas d'accès croisé possible.
- accept() AVANT group_add (résilience Redis), et un échec de group_add ou du message d'établissement NE FERME PAS la connexion (correctif explicite contre la boucle de reconnexion 1-60 s).
- broadcast_message est protégé: un message corrompu est loggué mais ne tue pas la session WS.
- Les trames binaires sont refusées avec un message d'erreur; un JSON invalide renvoie une erreur sans fermer.
- Protocole entrant: 'ping' → 'pong' (echo du ts), toute autre action → 'ack'.
- Format sortant {"event", "payload"} — différent du consumer de notifications ({"type", …}).
- Chaque transition d'ordre a sa propre idempotency_key Outbox (order:{id}:realtime-created/-submitted/-filled/-cancelled): un rejeu ne duplique pas l'événement temps réel.

**Flux WebSocket portefeuille**
<br>_Stream par portefeuille des mises à jour de métriques et de positions._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/portfolio/consumers.py:PortfolioConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/execution/outbox.py:publish_portfolio_update`, `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:RealtimeBroadcastService.broadcast_position_update`

- CONTRÔLE D'ACCÈS OBLIGATOIRE: le portfolio_id vient de l'URL, donc l'appartenance est vérifiée en base (Portfolio.objects.filter(id, user_id).exists()) avant group_add. Refus → close(4003), non authentifié → close(4001). C'est le seul rempart contre la fuite de données entre utilisateurs sur ce flux.
- Contrairement aux autres consumers, group_add se fait AVANT accept() ici — un Redis indisponible fait échouer la connexion (comportement non aligné sur le pattern résilient).
- receive() ignore tout message entrant: ce consumer ne répond pas au ping du heartbeat client.

**Flux WebSocket tableau de bord**
<br>_Stream agrégé du dashboard hedge fund par utilisateur._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/trading/consumers.py:DashboardConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/execution/outbox.py:publish_dashboard_update`, `/Users/ogahserge/Documents/leoTrade/backend/risk/services.py`, `/Users/ogahserge/Documents/leoTrade/backend/portfolio/services.py`

- Anonyme → close(4001); groupe dérivé de l'id utilisateur.
- accept() avant group_add; échec de group_add → mode isolé, connexion maintenue.
- broadcast_message protégé: un échec d'envoi ne ferme jamais la connexion.
- Répond au ping du heartbeat LeoWS.
- Le message d'établissement porte version:1 dans son payload.

**Flux WebSocket radar IA**
<br>_Stream des mises à jour du moteur IA (opportunités, recommandations) par utilisateur._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/trading/consumers_ai.py:AIRadarConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/core/realtime.py:RealtimeBroadcastService.broadcast_ai_update`, `/Users/ogahserge/Documents/leoTrade/backend/trading/services/ai_engine.py`

- Anonyme → close(4001); groupe dérivé de l'id utilisateur.
- group_add AVANT accept (pattern non résilient, contrairement aux consumers ordres/dashboard/notifications).
- receive() ignore tout: ne répond pas au ping du heartbeat client.
- broadcast_message accède à event['event_type'] et event['payload'] sans défaut: un message malformé lève et tue la connexion.

**Flux WebSocket bougies de marché**
<br>_Stream des bougies live par actif et unité de temps, alimenté par l'importateur Deriv._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/market/servicess/consumers.py:CandleConsumer`, `/Users/ogahserge/Documents/leoTrade/backend/market/servicess/candle_importers/deriv.py`, `/Users/ogahserge/Documents/leoTrade/backend/market/routing.py`

- Double contrôle d'accès cumulatif avant abonnement: l'actif doit exister et être actif, ET l'utilisateur doit posséder au moins un portefeuille actif (équivaut à un abonnement). Refus → close(4403), anonyme → close(4401). Garde-fou anti-divulgation d'information explicitement documenté.
- Toute exception dans la vérification d'accès retourne False (fail-closed) — l'inverse du fail-open appliqué au rate limit des notifications.
- Ce consumer attend le type 'candle_update' avec event['data'] (format de l'importateur Deriv), pas le format 'broadcast.message' du socle réaltime.

**Outil de diagnostic temps réel**
<br>_Commande de gestion envoyant un broadcast de notification et un broadcast de métriques de portefeuille pour valider la chaîne Channels/Redis._
<br>Points d'entrée : `/Users/ogahserge/Documents/leoTrade/backend/core/management/commands/test_realtime.py`

- Outil d'exploitation uniquement; les valeurs qu'il pousse sont des données de test et ne doivent jamais être déclenchées en production sur un utilisateur réel (elles affichent un toast et des métriques fictives).
- Utile pour vérifier que le groupe user_notifications_{id} est bien joint par un client connecté.

</details>

<details><summary>Pièges de migration repérés</summary>

- BUG BLOQUANT — NotificationCenterConsumer (/ws/notifications/) n'implémente PAS de handler `broadcast_message`. Or RealtimeBroadcastService.broadcast_notification envoie au groupe user_notifications_{id} un message de type 'broadcast.message'. channels.consumer.dispatch lève alors ValueError('No handler for message type broadcast.message') et la connexion WebSocket tombe. Conséquence: le canal in-app est marqué SENT dans NotificationDeliveryLog alors que le client ne reçoit jamais rien, et le badge/toast ne se rafraîchit qu'au rechargement. Le handler `notification_created` présent dans le consumer est mort: aucun émetteur n'envoie ce type. L'ancien UserNotificationsConsumer (execution/consumers.py), qui avait bien `broadcast_message`, a été débranché du routing. À corriger impérativement avant de câbler React/Flutter dessus, sinon le défaut est reproduit à l'identique.
- Code mort à ne pas reprendre: execution.consumers.UserNotificationsConsumer n'est plus routé (commentaire explicite dans execution/routing.py) — ce n'est plus une fonctionnalité. De même market/routing.py contient un import commenté d'un second CandleConsumer.
- Incohérence de protocole entre consumers: /ws/notifications/ émet {"type": …}, tous les autres émettent {"event": …, "payload": …}, le flux bougies attend un type 'candle_update' avec clé 'data', et l'assistant IA un type 'assistant.stream'. RealtimeBroadcastService.broadcast_candle (core/realtime.py) envoie 'broadcast.message' et n'a donc AUCUN handler côté CandleConsumer: c'est un piège, seul le chemin de l'importateur Deriv fonctionne. Unifier le contrat d'événements avant d'écrire les clients React/Flutter.
- Pas d'authentification WebSocket par token: asgi.py n'utilise que AuthMiddlewareStack (cookie de session). Flutter ne peut pas se connecter avec le JWT déjà disponible sur l'API REST. Blocage majeur du temps réel mobile.
- Aucune notification push native: zéro trace de FCM, APNs ou Web Push dans le dépôt. Application mobile fermée = aucune alerte, y compris pour un kill switch ou une alerte sécurité — alors que ces événements sont justement ceux marqués critical=True. C'est le plus gros écart fonctionnel de la refonte mobile; il faut un cinquième canal (PUSH) dans events.Channel, NotificationPreference, CHANNEL_SERVICES et un modèle de device token.
- Sémantiques opposées entre les deux surfaces de préférences: la vue Django POST traite une case absente comme False (désactivation implicite de tout ce qui n'est pas transmis), alors que l'API PATCH est strictement partielle. Un client React qui enverrait un PATCH en réutilisant la logique du formulaire web, ou l'inverse, désactiverait silencieusement des canaux. À unifier sur la sémantique PATCH.
- Logique métier enfouie dans la vue Django: notification_preferences fait le parsing POST, la troncature des champs et la gestion d'erreur d'heure à la main, sans Form ni serializer. La règle 'format d'heure invalide' est un try/except autour de save() avec un message utilisateur générique. À extraire dans le serializer DRF (qui, lui, ne valide pas non plus le format des numéros de téléphone).
- Logique de référentiel enfouie dans les templates: event_choices, severity_choices et priority_choices n'existent que dans le contexte de notification_center. Aucun endpoint ne les expose — risque réel que React et Flutter recopient en dur les ~50 codes d'événements et divergent du registre events.py.
- Quiet hours en heure locale du SERVEUR (timezone.localtime()), pas dans le fuseau de l'utilisateur, et aucun champ de fuseau n'existe sur NotificationPreference. Pour une base d'utilisateurs multi-fuseaux (Côte d'Ivoire + autres), les heures de silence sont fausses. Changer ce comportement modifie une règle métier visible: à acter explicitement.
- Re-dispatch non filtré: send_notification_task ne saute que les statuts SENT et SUPPRESSED. Une notification PARTIAL ou FAILED relancée (notamment par l'action admin 'Renvoyer') ré-envoie TOUS les canaux de channels_requested, y compris ceux déjà livrés → doublons d'email/SMS. L'action admin contourne en plus l'Outbox en appelant .delay() directement.
- Asymétries de comportement subtiles mais testées, à ne pas 'nettoyer' par inadvertance: (a) une notification rate-limitée n'est pas persistée alors qu'une notification filtrée par catégorie est persistée en SUPPRESSED; (b) email sans adresse = FAILED (donc retenté) alors que SMS/WhatsApp sans numéro = SKIPPED (abandonné); (c) le canal in-app renvoie ok=True même quand le channel layer est indisponible, alors que le chemin Outbox NOTIFICATION_UPDATE exige la livraison et part en retry/DEAD.
- Dépendances au cache Redis non persistantes: rate limit et dedupe_key vivent uniquement dans le cache Django. Un flush ou un cache non partagé entre workers réautorise des doublons. Le fail-open du rate limit (cache indisponible → on laisse passer) est volontaire mais doit être conservé consciemment.
- Deux chemins d'émission concurrents pour le même groupe WebSocket: le module notifications (persisté, avec préférences, quiet hours et rate limit) et TradingNotificationService.notify_error/notify_success + leo_backtesting (éphémères, sans préférences ni persistance). Les seconds ignorent totalement les réglages utilisateur et sont perdus hors-ligne. Décider en refonte s'ils deviennent de vraies notifications.
- Gabarits de notification = données de production créées par data migration (0002) puis modifiées par une seconde migration de rebranding (0003) et éditables en admin. Toute migration de base doit les préserver; ne jamais rejouer l'opération inverse (unseed) qui les supprimerait. Seuls EMAIL et SMS sont couverts, uniquement en 'fr' — la langue 'en' proposée dans les préférences retombe systématiquement sur les gabarits français.
- Purge destructive: cleanup_old_notifications_task supprime en dur (cascade sur les logs de livraison) sans exemption pour les événements critiques. Sur la base de production migrée, vérifier les sauvegardes avant de laisser tourner le beat.
- Pas de schéma OpenAPI (aucune trace de drf-spectacular dans les settings ni les urls), alors que la cible impose OpenAPI. Les contrats d'API notifications devront être décrits de zéro.
- Couverture de test: tests_phase/test_notifications.py couvre bien la résolution de canaux, le rate limit, le dedupe, le dispatch, le renderer, l'API et le retry — mais AUCUN test WebSocket (pas de WebsocketCommunicator dans le dépôt), ce qui explique que le défaut de handler broadcast_message n'ait pas été détecté. Prévoir des tests Channels sur les consumers dans la refonte.
- Le badge non-lu initial arrive uniquement par la WebSocket (base.html). Si la WS ne s'ouvre pas, le badge reste masqué même avec des notifications non lues. React/Flutter doivent appeler GET /api/notifications/unread-count/ au démarrage en plus de la WS.

</details>

---

### dashboard-backtesting

`36 fonctionnalités` — API : **0 prêtes, 8 partielles, 28 à exposer**

**Modèles** : `KYCProfile`, `BacktestRun`

**Tâches Celery** : `leo_backtesting.tasks.run_backtest_task`, `leo_backtesting.tasks.recover_stale_backtest_runs_task (beat: recover-stale-backtests-every-5m, crontab */5)`

**Canaux WebSocket** : `ws/dashboard/live/ — trading.consumers.DashboardConsumer, groupe user_dashboard_<user_id>, event dashboard.update (consommé par fund_dashboard.html et cockpit.js)`, `ws/portfolio/<portfolio_id>/ — portfolio.consumers.PortfolioConsumer, event portfolio.update (consommé par cockpit.js et _positions_table.html)`, `ws/orders/ — execution.consumers.UserOrdersConsumer, event order.update (consommé par cockpit.js)`, `ws/notifications/ — notifications.consumers.NotificationCenterConsumer, groupe user_notifications_<id>, event notification.created (cible des notifications de fin/échec de backtest)`, `ws/ai/radar/ — trading.consumers_ai.AIRadarConsumer, groupe user_ai_<id>, event ai.update (consommé par cockpit.js)`

| Fonctionnalité | API | Cibles | RT | Ce qui manque côté API |
|---|:--:|:--:|:--:|---|
| **Landing page publique** | ❌ | WEB |  | Aucun endpoint. À recréer comme page React statique ; seul besoin API = état d'authentification (déjà couvert par l'auth). |
| **Dashboard Hedge Fund (rendu initial)** | ❌ | WEB/MOBILE | ⚡ | Aucun endpoint REST : le contexte complet (all_portfolios, stats, signaux, backtests) n'existe qu'en contexte de template. Il faut exposer GET /api/v1/dashboard/overview/ (ou composer portfolios + positions + orders + signals + backtests). |
| **Flux live du dashboard (JSON)** | 🟡 | WEB/MOBILE | ⚡ | Endpoint JSON maison (django.views.View + JsonResponse) : hors DRF, hors /api/v1/, sans serializer ni schéma OpenAPI, authentifié par session seulement. À porter en endpoint DRF versionné avec auth JWT pour être consommable par React/Flutter. |
| **Rafraîchissement live côté client (polling + WebSocket + pause)** | 🟡 | WEB/MOBILE | ⚡ | La WS existe et fonctionne, mais le protocole est « notification de changement + refetch HTTP ». À conserver tel quel ou à remplacer par des payloads complets ; côté Flutter il faut en plus l'auth WS hors cookie de session. |
| **Cockpit premium (page)** | ❌ | WEB/MOBILE | ⚡ | Vue template uniquement. Le contexte graphique (pnl_snapshots, allocation, risk_drawdown) est injecté en JSON inline dans le HTML ; à exposer en endpoints REST. |
| **Construction du contexte cockpit (service métier)** | ❌ | WEB/MOBILE |  | Logique d'agrégation réutilisable mais couplée au rendu (objets ORM dans le contexte). À exposer via un serializer DRF dédié ; c'est le candidat n°1 pour un endpoint /api/v1/cockpit/. |
| **Données cockpit (JSON de rafraîchissement)** | 🟡 | WEB/MOBILE | ⚡ | JsonResponse hors DRF, hors /api/v1/, sans serializer ni OpenAPI, valeurs numériques en string. Incomplet (opportunités, risk decisions, activity feed manquants). |
| **Fragment HTML AI Radar** | ❌ | WEB |  | Renvoie du HTML Django, inutilisable par React/Flutter. À remplacer par un endpoint JSON de recommandations (ou réutiliser /api/v1/recommendations/ déjà existant). |
| **AI Radar — liste des recommandations IA** | ❌ | WEB/MOBILE | ⚡ | Le rendu est templaté ; les actions sont des POST form + redirect. Il existe /api/v1/recommendations/ (TradeRecommendationViewSet) mais le cockpit ne l'utilise pas — il faut vérifier que ce ViewSet expose bien approve/reject/execute avant de brancher le front. |
| **Approuver une recommandation IA** | ❌ | WEB/MOBILE |  | POST form + redirect vers le cockpit, sans réponse JSON ni code d'erreur exploitable. Il faut une action DRF renvoyant la recommandation mise à jour. |
| **Rejeter une recommandation IA** | ❌ | WEB/MOBILE |  | POST form + redirect, pas de réponse JSON. |
| **Exécuter une recommandation IA** | ❌ | WEB/MOBILE |  | POST form + redirect ; l'erreur n'est restituée que par le framework de messages Django. Nécessite une action DRF renvoyant 200 avec l'ordre créé ou 4xx avec le code de blocage risque. |
| **Bandeau et résolution du kill switch** | ❌ | WEB/MOBILE | ⚡ | POST form + redirect côté dashboard. Il existe /api/v1/kill-switch-events/ en lecture ; l'action de résolution n'est pas exposée en API. |
| **Tableau des positions live du cockpit (sparklines)** | ❌ | WEB/MOBILE | ⚡ | Rendu template + mutation DOM. Nécessite un endpoint positions scopé portefeuille et un vrai historique de prix pour alimenter les sparklines. |
| **Tape des ordres du cockpit** | 🟡 | WEB/MOBILE |  | Les ordres existent en API via /api/v1/orders/ (OrderViewSet), mais le filtrage portefeuille + la limite à 15 et l'agrégation cockpit ne sont pas exposés. |
| **Risk Center du cockpit** | 🟡 | WEB/MOBILE |  | /api/v1/risk-decisions/ existe (RiskDecisionViewSet) mais le cockpit ne l'utilise pas ; vérifier que le filtrage par portefeuille et les champs approved_stake / expected_loss / blocking_reason y sont exposés. |
| **Fil d'activité du cockpit** | ❌ | WEB/MOBILE | ⚡ | Agrégat purement template + DOM. Nécessite un endpoint d'activité unifié (ou la composition client de 3 flux). |
| **Graphiques du cockpit (P&L, répartition, jauge de risque)** | 🟡 | WEB/MOBILE | ⚡ | Les séries sont servies par /premium/data/ (hors DRF). Aucun endpoint ne permet de filtrer par période — prérequis si les boutons 1h/4h/1d/1w doivent devenir fonctionnels. |
| **Bascule du mode de trading PAPER / LIVE** | ❌ | WEB/MOBILE |  | POST form + redirect + messages Django. Nécessite un endpoint (ex. POST /api/v1/trading/mode/) renvoyant l'état par compte et la liste structurée des warnings (comptes Deriv sans token, absence de broker). |
| **KYC — tableau de bord client** | ❌ | WEB/MOBILE |  | Aucun endpoint KYC en API. Il faut GET /api/v1/kyc/me/ renvoyant statut, motif de rejet et complétude du dossier. |
| **KYC — soumission / mise à jour du dossier** | ❌ | WEB/MOBILE |  | Formulaire multipart Django classique. Nécessite POST /api/v1/kyc/submit/ en multipart avec les MÊMES validations serveur (taille, extension, content-type, magic bytes) et des erreurs structurées par champ ; côté mobile, prévoir la capture caméra pour la pièce et le selfie. |
| **KYC — file de revue admin** | ❌ | WEB |  | Vue template staff. Nécessite un endpoint admin paginé avec filtres, protégé par un rôle RBAC explicite (pas is_staff implicite). |
| **KYC — détail d'un dossier admin** | ❌ | WEB |  | Vue template staff, aucune API. |
| **KYC — consultation sécurisée d'un document** | ❌ | WEB |  | Sert un flux binaire sous session staff. En API il faudra un endpoint authentifié équivalent (ou des URL signées à durée courte) en conservant no-store et nosniff. |
| **KYC — approbation d'un dossier** | ❌ | WEB |  | POST form + redirect. Nécessite une action API staff renvoyant le profil mis à jour. |
| **KYC — rejet d'un dossier** | ❌ | WEB |  | POST form + redirect ; la validation du motif n'existe que côté HTML. L'API devra rendre rejection_reason obligatoire côté serveur ou documenter le repli. |
| **Administration Django du KYC** | ❌ | WEB |  | Admin Django conservé hors refonte front ; à sécuriser ou à remplacer par un back-office React si l'admin disparaît. |
| **Liste et statistiques des backtests** | ❌ | WEB/MOBILE |  | Aucune route API. BacktestRunSerializer existe (leo_backtesting/serializers.py, tous champs en read_only) mais n'est câblé à AUCUN ViewSet ni à api/urls.py — code mort. Il faut exposer /api/v1/backtests/ avec le même cloisonnement et les compteurs. |
| **Lancement d'un backtest** | ❌ | WEB/MOBILE |  | POST form + redirect. Nécessite POST /api/v1/backtests/ renvoyant le run créé (201) ou le run déjà actif (409/200 avec son id), en conservant l'enqueue outbox dans la transaction. |
| **Détail d'un backtest** | ❌ | WEB/MOBILE |  | Vue template. BacktestRunSerializer couvre déjà tous les champs nécessaires (metrics, equity_curve, trades_log) mais n'est exposé nulle part. Prévoir une pagination/compression du trades_log pour le mobile. |
| **Suivi du statut d'un backtest (polling)** | 🟡 | WEB/MOBILE | ⚡ | Endpoint JSON hors DRF, hors /api/v1/, auth par session. À porter en DRF ; idéalement remplacer le polling par une souscription WebSocket côté React/Flutter. |
| **Exécution asynchrone d'un backtest (worker)** | ❌ | WEB/MOBILE | ⚡ | Tâche de fond, pas d'exposition API attendue, hormis la restitution de son état via l'endpoint de statut. |
| **Moteur de backtest SMA Cross et réconciliation** | ❌ | WEB/MOBILE |  | Moteur interne. L'API doit exposer ses sorties (metrics, equity_curve, trades_log, data_quality, checksum) sans réinterpréter les chiffres côté client. |
| **Persistance du résultat sous bail d'exécution** | ❌ | WEB/MOBILE |  | Interne. |
| **Récupération des backtests bloqués** | ❌ | WEB/MOBILE |  | Tâche de fond ; aucun pilotage API. Un écran d'exploitation (runs bloqués, tentatives) n'existe pas et serait à créer si souhaité. |
| **Notification temps réel de fin / échec de backtest** | 🟡 | WEB/MOBILE | ⚡ | La WS existe mais n'est pas doublée d'une notification persistée interrogeable en REST. Pour Flutter il faut en plus un push (FCM/APNs) et un historique /api/notifications/. |

<details><summary>Règles métier invariantes à préserver</summary>

**Landing page publique**
<br>_Page marketing d'accueil servie à la racine du site : hero, section LeoTrade, grille de 6 fonctionnalités, FAQ en accordéon Alpine, CTA d'inscription/connexion, footer._
<br>Points d'entrée : `backend/dashboard/views.py:LandingPageView`, `backend/templates/landing/home.html`

- Page entièrement statique : aucune donnée métier, aucun appel base de données.
- Seul comportement dynamique : l'en-tête affiche « Bonjour <first_name> » + lien Dashboard si request.user.is_authenticated, sinon les liens account_login / account_signup.
- Template autonome (ne hérite pas de layout/base.html) : charge son propre Tailwind buildé et Alpine via CDN.
- Les liens Confidentialité / Conditions / Contact du footer pointent sur href="#" — pas de pages cibles existantes.

**Dashboard Hedge Fund (rendu initial)**
<br>_Page principale /dashboard/ : sélecteur de portefeuille, 8 tuiles de stats, positions ouvertes, ordres récents, signaux et backtests récents, rendue côté serveur puis pilotée en live par JS._
<br>Points d'entrée : `backend/dashboard/views.py:HedgeFundDashboardView`, `backend/templates/dashboard/fund_dashboard.html`

- Portefeuille par défaut = Portfolio(user=request.user, is_active=True) trié par -is_default puis name, premier résultat.
- Lecture défensive de la table portfolio_portfolio : _existing_table_columns/_portfolio_safe_queryset ne sélectionnent que les colonnes réellement présentes et _hydrate_portfolio_defaults injecte des valeurs par défaut — la page ne doit jamais tomber en ProgrammingError/OperationalError pendant une transition de migrations.
- Si aucun portefeuille : stats toutes à zéro et listes vides, jamais d'erreur ni de 404.
- pnl_percent = (realized+unrealized)/current_balance*100 uniquement si balance > 0, sinon 0.
- Positions ouvertes = status in [OPEN, PARTIALLY_CLOSED] triées par -opened_at ; ordres récents limités à 12 (-created_at).
- Signaux : Signal.objects.visible_to(user) + strategy__is_active=True, puis restreints aux assets des positions du portefeuille si ces assets existent, limités à 10.
- Backtests : requested_by=request.user + strategy__is_active=True, mêmes assets si disponibles, limités à 5 — cloisonnement utilisateur obligatoire.
- winners_count/losers_count comptés en Python sur le champ pnl de chaque position (0 ni gagnant ni perdant).

**Flux live du dashboard (JSON)**
<br>_Endpoint AJAX qui alimente le dashboard temps réel : portefeuille actif, 16 stats recalculées côté serveur, positions enrichies (prix live, PnL, progression TP/SL, mini-chart de 40 bougies) et 12 derniers ordres._
<br>Points d'entrée : `backend/dashboard/views.py:HedgeFundDashboardLiveDataView`

- Sélection du portefeuille par ?portfolio_id ou ?portfolio, toujours filtrée sur user=request.user et is_active=True ; retombe sur le portefeuille par défaut si l'id est invalide ou absent.
- Si aucun portefeuille : renvoie un payload structuré avec portfolio=null et toutes les stats à 0 — jamais une 404 (le front ne gère pas l'erreur).
- Prix live = dernier close > 0 de la dernière bougie propre, sinon current_price de la position, sinon entry_price, sinon 0.
- Déduplication des bougies par open_time (on lit limit*3 lignes en -open_time,-id pour compenser les doublons, on garde la première occurrence de chaque open_time, on retrie en croissant et on conserve les 40 dernières).
- Actifs synthétiques Deriv (préfixes R_, JD, CRASH, BOOM, VOL, STEP, RDBEAR, RDBULL) : interdiction d'appliquer le PnL linéaire ; on utilise le premier champ non nul parmi unrealized_pnl, pnl, floating_pnl, profit, et pnl_percent = pnl / (entry_price*quantity) * 100. L'UI les marque SYNTH et affiche « indicatif » / « — ».
- PnL non synthétique : LONG=(current-entry)*qty, SHORT=(entry-current)*qty ; nul si entry<=0, current<=0 ou qty<=0.
- progress_to_tp calculé seulement si TP>entry (LONG) ou TP<entry (SHORT) ; progress_to_sl seulement si SL<entry (LONG) ou SL>entry (SHORT) ; les deux bornés à [0,100].
- equity : si le champ DB est égal à la balance (valeur obsolète/non réconciliée) il est recalculé en balance + PnL latent total.
- available_cash : si le champ DB vaut la balance (non réconcilié) il est estimé par max(0, balance - locked_cash - margin_used).
- unrealized_pnl des stats = somme des PnL recalculés position par position, pas le champ DB du portefeuille.

**Rafraîchissement live côté client (polling + WebSocket + pause)**
<br>_Boucle de surveillance du dashboard : connexion WS ws/dashboard/live/ via le manager LeoWS, fallback polling HTTP 5 s, barre de progression du cycle, bouton Pause/Reprendre, bouton Rafraîchir, horodatage de dernière mise à jour, badge WEBSOCKET LIVE / OFFLINE-FALLBACK._
<br>Points d'entrée : `backend/templates/dashboard/fund_dashboard.html:498-923`, `backend/trading/consumers.py:DashboardConsumer`

- Le polling HTTP ne tourne QUE si la WS n'est pas live et que le flux n'est pas en pause (if (!this.paused && !this.isLive)).
- Les messages WS ne transportent pas l'état : les kinds portfolio_metrics, dashboard_snapshot, fill, position_or_fill_update, order_created, event, kill_switch_triggered, kill_switch_resolved déclenchent simplement un refetch de l'endpoint live — le serveur reste la source de vérité.
- Si window.LeoWS est absent, on reste en polling HTTP pur sans spammer le serveur de reconnexions.
- Le DashboardConsumer accepte la connexion AVANT le group_add : si Redis tombe, la WS reste ouverte en mode isolé plutôt que de boucler en reconnexion.
- Un broadcast qui échoue ne ferme jamais la WebSocket (log uniquement).
- Ping/pong applicatif ({action:"ping"} → event pong) pour le keepalive.
- Les charts Chart.js sont détruits quand la position disparaît et mis à jour en update("none") sinon ; cleanup complet sur beforeunload.
- La modale de détail d'une position se referme automatiquement si la position n'existe plus dans le snapshot suivant.

**Cockpit premium (page)**
<br>_Tableau de bord hedge-fund avancé /dashboard/premium/ : bandeau kill switch, 5 hero stats, graphe d'évolution P&L, AI Radar, table des positions avec sparklines, tape des ordres, donut de répartition, jauge de drawdown, panneau portefeuille, risk center, fil d'activité._
<br>Points d'entrée : `backend/dashboard/views_premium.py:PremiumCockpitView`, `backend/templates/dashboard/premium/cockpit.html`, `backend/templates/dashboard/partials/_hero_stats.html`, `backend/templates/dashboard/partials/_portfolio_panel.html`

- Sélection du portefeuille par ?portfolio, filtrée sur user + is_active ; le select est un formulaire GET en auto-submit (rechargement complet de page).
- pnl_snapshots : 30 derniers PortfolioSnapshot triés -snapshot_time puis réinversés pour un ordre chronologique ; equity retombe sur total_value si absent.
- allocation : 8 premières PortfolioAllocation, target_weight converti en pourcentage (×100) et arrondi à 1 décimale ; les poids nuls sont exclus.
- risk_drawdown = current_drawdown_percent / max_drawdown_percent (ratio 0..1), 0 si max<=0 ; max par défaut 100.
- Chaque bloc de calcul graphique est encapsulé dans un try/except qui retombe sur une valeur vide — un snapshot ou une allocation corrompus ne doivent jamais casser la page.
- Si aucun portefeuille : message « Aucun portefeuille actif disponible » et aucun bloc n'est rendu (le script d'init n'est pas injecté).
- Les hero stats sont rendues brutes ({{ hero_stats.balance }}) sans formatage monétaire — régression d'affichage connue à corriger, pas à reproduire.

**Construction du contexte cockpit (service métier)**
<br>_Service central qui agrège recommandations IA, positions, ordres, opportunités de marché, décisions de risque, kill switch actif, audits décisionnels, fil d'activité et hero stats pour un couple (user, portfolio)._
<br>Points d'entrée : `backend/dashboard/services.py:DashboardPremiumService.build_cockpit_context`, `backend/dashboard/services.py:DashboardPremiumService.get_user_default_portfolio`

- Sans portefeuille, le service renvoie un dict complet avec toutes les clés présentes et vides — les templates et JsonResponse supposent ces clés existantes.
- Limites fixes à préserver : 12 recommandations, 15 positions (OPEN/PARTIALLY_CLOSED), 15 ordres (avec fills préchargés), 12 opportunités, 10 décisions de risque, 10 audits, 12 entrées d'activité.
- Recommandations, ordres et audits sont filtrés sur user ET portfolio ; positions et décisions de risque sur portfolio.
- MarketOpportunity n'a pas de propriétaire : les opportunités ACTIVE sont globales. Le cloisonnement se limite à une PRIORISATION (annotation Case/When priority=0 sur les assets des positions ouvertes) — ce n'est pas un filtrage de sécurité.
- Les positions sont chargées AVANT les opportunités car elles alimentent le filtre de priorisation — ordre à conserver.
- activity_feed = 5 ordres + 5 recommandations + 5 audits fusionnés, triés par time décroissant puis tronqués à 12.
- Un seul kill switch est remonté : le plus récent actif (is_active=True, -triggered_at).
- hero_stats.equity retombe sur balance si le champ equity est falsy ; total_pnl = realized + unrealized ; server_time inclus.

**Données cockpit (JSON de rafraîchissement)**
<br>_Endpoint JSON qui renvoie le même contexte cockpit sérialisé : portefeuille, hero stats, recommandations, ordres, positions, kill switch, snapshots P&L, allocation, drawdown._
<br>Points d'entrée : `backend/dashboard/views_premium.py:CockpitDataView`, `backend/dashboard/views_premium.py:_build_pnl_snapshots`, `backend/dashboard/views_premium.py:_build_allocation`, `backend/dashboard/views_premium.py:_build_risk_drawdown`, `backend/static/dashboard/js/cockpit.js:refreshCockpitData`

- Tous les hero_stats sont sérialisés via str() (y compris les Decimal et le datetime server_time) : le client reçoit des chaînes, pas des nombres.
- Filet de sécurité : rafraîchissement complet toutes les 90 s côté JS, plus un refresh différé de 500 ms après chaque événement WS d'ordre.
- Les trois helpers graphiques appliquent la même logique que la vue page (30 snapshots, 8 allocations, ratio de drawdown) — toute divergence entre les deux chemins est un bug.
- Le payload ne contient ni les opportunités, ni les décisions de risque, ni le fil d'activité (présents seulement au rendu initial) : le refresh HTTP ne met donc jamais à jour ces trois blocs.

**Fragment HTML AI Radar**
<br>_Endpoint qui re-rend uniquement le bloc AI Radar (liste des recommandations IA) en HTML partiel._
<br>Points d'entrée : `backend/dashboard/views_fragments.py:AIPartialView`, `backend/templates/dashboard/partials/_ai_radar.html`

- Le portefeuille est filtré sur user ; sans paramètre, le service retombe sur le portefeuille par défaut.
- Reconstruit TOUT le contexte cockpit pour n'en rendre qu'un fragment (coût assumé).
- Aucun appelant JS dans le code actuel — route exposée mais non consommée par le front.

**AI Radar — liste des recommandations IA**
<br>_Bloc du cockpit listant les recommandations IA : symbole, type, statut, résumé IA, confiance, stake, notional, ratio R/R, et actions Approuver / Rejeter / Exécuter + bouton d'explication par l'assistant LeoTrade._
<br>Points d'entrée : `backend/templates/dashboard/partials/_ai_radar.html`, `backend/dashboard/services.py:DashboardPremiumService.build_cockpit_context`

- Les trois actions sont des formulaires POST avec CSRF, pas des appels AJAX : chaque action recharge la page cockpit.
- Le bouton « LeoTrade AI » délègue à window.LeoAssistant.explainOpportunity avec id/direction/symbole/timeframe/score/confiance — no-op silencieux si l'assistant n'est pas chargé.
- État vide explicite : « Aucune recommandation IA disponible ».

**Approuver une recommandation IA**
<br>_Action utilisateur qui valide une recommandation produite par le moteur IA._
<br>Points d'entrée : `backend/dashboard/views_premium.py:RecommendationApproveView`, `backend/trading/services/recommendation_actions.py:RecommendationActionService.approve_by_user`

- Scoping obligatoire sur user=request.user : une recommandation d'un autre utilisateur est traitée comme introuvable (message d'erreur + redirect, jamais de 403/404 brute).
- Transaction atomique : status=APPROVED_BY_USER + approved_at, puis mise à jour de tous les DecisionAudit liés (final_decision=APPROVED_BY_USER).
- Émet une notification de succès et un broadcast dashboard kind=recommendation_approved — l'approbation N'EXÉCUTE PAS l'ordre.
- Aucune vérification d'état préalable : une recommandation déjà exécutée peut être ré-approuvée (comportement existant).

**Rejeter une recommandation IA**
<br>_Action utilisateur qui écarte une recommandation IA._
<br>Points d'entrée : `backend/dashboard/views_premium.py:RecommendationRejectView`, `backend/trading/services/recommendation_actions.py:RecommendationActionService.reject_by_user`

- Scoping sur user=request.user.
- Transaction atomique : status=REJECTED_BY_USER + mise à jour des DecisionAudit (final_decision=REJECTED_BY_USER).
- Asymétrie volontaire avec l'approbation : AUCUNE notification et AUCUN broadcast temps réel sur le rejet.

**Exécuter une recommandation IA**
<br>_Transforme une recommandation IA en TradeIdea puis en ordre réel via le pipeline d'exécution._
<br>Points d'entrée : `backend/dashboard/views_premium.py:RecommendationExecuteView`, `backend/trading/services/recommendation_actions.py:RecommendationActionService.execute_recommendation`

- Garde d'état stricte : exécution refusée (ValueError) si status n'est pas dans {APPROVED_BY_AI, APPROVED_BY_USER, PENDING} — empêche la double exécution d'une reco déjà EXECUTED ou REJECTED.
- Toute l'opération est atomique : création du TradeIdea (statut APPROVED, copie entry/SL/TP et tous les scores de l'opportunité), appel TradeIdeaExecutionService.execute(idea, broker_account, portfolio, stake_amount de la reco), puis status=EXECUTED + executed_at + DecisionAudit.execution_output {trade_idea_id, order_id, order_status}.
- Le stake vient de la recommandation (Decimal(str(...))), jamais d'une saisie utilisateur dans cette vue.
- Toute exception est capturée par la vue et transformée en message d'erreur UI (« Échec exécution : … ») — jamais de 500 pour l'utilisateur.
- C'est ce chemin qui traverse le Risk Engine / kill switch via TradeIdeaExecutionService : ne jamais court-circuiter ce service dans la refonte.

**Bandeau et résolution du kill switch**
<br>_Bandeau rouge affiché en tête de cockpit quand un kill switch est actif (code et motif) avec un bouton de résolution._
<br>Points d'entrée : `backend/dashboard/views_premium.py:ResolveKillSwitchView`, `backend/templates/dashboard/partials/_kill_switch_banner.html`, `backend/risk/services.py:RiskGuardService.resolve_kill_switch`

- Le portefeuille est filtré sur user + is_active ; sinon message d'erreur et redirection sans effet.
- resolve_kill_switch désactive TOUS les KillSwitchEvent actifs du portefeuille (is_active=False + resolved_at) et renvoie le nombre résolu.
- La notification KILL_SWITCH_DEACTIVATED n'est émise qu'une seule fois et seulement s'il y avait au moins un événement actif (flag had_active calculé AVANT la boucle).
- Broadcast dashboard kind=kill_switch_resolved systématique (même à 0) avec resolved_count.
- Redirection : POST['next'] > HTTP_REFERER > cockpit premium — comportement à conserver, il permet de revenir dans le contexte d'exécution d'une trade idea après avoir levé le blocage.
- Message distinct si aucun kill switch actif (info, pas succès).

**Tableau des positions live du cockpit (sparklines)**
<br>_Table des positions ouvertes du cockpit avec actif, side, quantité, prix d'entrée, prix actuel, P&L, pourcentage et sparkline, mise à jour en direct par WebSocket portefeuille._
<br>Points d'entrée : `backend/templates/dashboard/partials/_positions_table.html`

- Le side est affiché LONG si la valeur est BUY ou LONG, SHORT dans tous les autres cas.
- Code couleur figé : #00D4AA si P&L >= 0, #FF4C6A sinon (appliqué en style inline, pas en classes).
- Mise à jour live par DOM ciblé (data-position-current / data-position-pnl / data-position-pct) sans innerHTML — contrainte de sécurité explicite du module.
- La sparkline est initialisée avec un unique point (le P&L courant) puis alimentée par leoAddPoint à chaque message WS : il n'y a pas d'historique côté serveur.
- Le compteur positions-count est recalé sur la longueur du payload WS ; un payload sans positions est ignoré (return anticipé) et ne vide donc jamais la table.

**Tape des ordres du cockpit**
<br>_Table en lecture seule des 15 derniers ordres du portefeuille : symbole, side, mode, statut, quantité approuvée, quantité remplie, notional._
<br>Points d'entrée : `backend/templates/dashboard/partials/_orders_tape.html`, `backend/dashboard/services.py:DashboardPremiumService.build_cockpit_context`

- Affiche explicitement le champ mode (PAPER/LIVE) de l'ordre — information de sécurité à ne pas perdre dans la refonte.
- État vide explicite : « Aucun ordre récent ».
- Le contenu n'est pas rafraîchi par le JSON de refresh (orders-tape-body n'est jamais remis à jour par cockpit.js) : seul un rechargement de page le met à jour.

**Risk Center du cockpit**
<br>_Liste des 10 dernières décisions du moteur de risque pour le portefeuille : symbole, décision (APPROVE/REDUCE/autre), date, stake approuvé, perte attendue, motif de blocage._
<br>Points d'entrée : `backend/templates/dashboard/partials/_risk_center.html`, `backend/dashboard/services.py:DashboardPremiumService.build_cockpit_context`

- Code couleur sémantique : APPROVE=vert, REDUCE=ambre, toute autre décision (dont les blocages)=rouge.
- Le blocking_reason n'est affiché que s'il est renseigné — c'est la seule restitution à l'utilisateur du motif de refus du Risk Engine dans le cockpit, elle ne doit pas disparaître.
- État vide explicite : « Aucune décision de risque récente ».

**Fil d'activité du cockpit**
<br>_Flux chronologique fusionné des ordres, recommandations IA et audits décisionnels récents, complété en direct par les événements WebSocket._
<br>Points d'entrée : `backend/templates/dashboard/partials/_activity_feed.html`, `backend/dashboard/services.py:DashboardPremiumService.build_cockpit_context`, `backend/static/dashboard/js/cockpit.js:prependActivity`

- Rendu initial : 5 ordres + 5 recommandations + 5 audits, triés par date décroissante, tronqués à 12 entrées.
- Ajouts temps réel en tête de liste avec plafond dur de 20 éléments dans le DOM (les plus anciens sont supprimés).
- Construction exclusivement par createElement/textContent (jamais innerHTML) — contrainte de sécurité XSS explicite.
- Code couleur par type : order=bleu, ai=violet, risk=ambre, error=rouge, défaut=gris.
- Toasts LeoAnim déclenchés en parallèle : succès si ordre filled, erreur si rejected, info sinon.

**Graphiques du cockpit (P&L, répartition, jauge de risque)**
<br>_Courbe d'évolution P&L avec label et pourcentage, donut de répartition par actif, jauge de drawdown avec libellé « x% drawdown utilisé »._
<br>Points d'entrée : `backend/static/dashboard/js/cockpit.js`, `backend/static/js/leo_charts.js`, `backend/dashboard/views_premium.py:PremiumCockpitView`

- Données initiales injectées inline dans le HTML (pnl_snapshots_json, allocation_json, risk_drawdown) puis rafraîchies par /premium/data/.
- Le label P&L compare le premier et le dernier point de la série : variation absolue et pourcentage, vert si >= 0 sinon rouge.
- Chaque message WS portefeuille ajoute un point à la courbe P&L (addPnlPoint sur payload.equity), plafonné à maxPoints=60.
- La jauge de risque attend un ratio 0..1 : le flux WS portefeuille envoie un pourcentage et le divise par 100, tandis que le kind risk_update du flux dashboard envoie déjà un ratio — divergence d'unité à normaliser dans la refonte.
- Les boutons de période 1h/4h/1d/1w (classe leo-tf-btn, data-tf) n'ont AUCUN gestionnaire d'événement : ce sont des boutons morts, à implémenter ou à retirer (interdiction de boutons non fonctionnels).

**Bascule du mode de trading PAPER / LIVE**
<br>_Interrupteur global qui bascule tous les comptes broker actifs de l'utilisateur entre mode papier et mode réel, avec garde-fous et notification de sécurité._
<br>Points d'entrée : `backend/dashboard/views.py:trading_mode_toggle`, `backend/tests_phase/test_mode_toggle.py`

- INVARIANT CENTRAL : le mode est une propriété du BrokerAccount, pas de la session. Le persister uniquement en session fait afficher LIVE dans l'UI pendant que l'orchestrateur route toujours vers PaperBrokerAdapter (incident de l'ordre #41). La session n'est qu'un miroir d'affichage.
- La bascule s'applique à TOUS les BrokerAccount de l'utilisateur avec is_active=True ; les comptes inactifs ne sont jamais touchés ; les comptes des autres utilisateurs jamais touchés.
- Mode absent ou invalide → repli silencieux sur PAPER (jamais LIVE par défaut).
- Aucun compte actif → le mode est mémorisé en session et un warning explicite prévient qu'aucune exécution ne sera possible ; pas d'erreur.
- Un compte déjà dans le mode cible est ignoré (skipped) ; si rien n'a basculé, message d'information et non de succès.
- Deriv en LIVE sans deriv_token : la bascule est effectuée quand même mais un warning nominatif prévient que les ordres échoueront tant que l'OAuth n'est pas fait.
- Chaque transition est journalisée pour audit (broker_account_mode_toggled avec user_id, broker_account_id, broker, old_mode, new_mode).
- La notification LIVE_MODE_ENABLED (« argent réel ») n'est émise que si au moins un compte a effectivement basculé ET que le mode cible est LIVE.
- save() retente sans update_fields=['mode','updated_at'] si le champ updated_at n'existe pas.
- Redirection sur HTTP_REFERER, sinon dashboard.

**KYC — tableau de bord client**
<br>_Page où l'utilisateur consulte le statut de son dossier KYC, le motif de rejet éventuel et accède à la soumission._
<br>Points d'entrée : `backend/dashboard/views.py:kyc_dashboard`, `backend/templates/dashboard/kyc_dashboard.html`

- get_or_create du KYCProfile : tout utilisateur authentifié a toujours un profil (statut NOT_STARTED par défaut), jamais de 404.
- Mapping d'affichage : APPROVED→APPROUVÉ, PENDING ou UNDER_REVIEW→EN REVUE, REJECTED→REJETÉ, sinon NON COMMENCÉ.
- Le motif de rejet n'est affiché que s'il est renseigné.
- Le statut UNDER_REVIEW existe dans les choix mais n'est jamais positionné par le code applicatif (uniquement via l'admin Django).

**KYC — soumission / mise à jour du dossier**
<br>_Assistant en 4 étapes (profil civil, coordonnées, pièce d'identité, validation) pour déposer identité, adresse et documents justificatifs._
<br>Points d'entrée : `backend/dashboard/views.py:kyc_submit`, `backend/dashboard/form.py:KYCSubmissionForm`, `backend/templates/dashboard/submit.html`

- 10 champs obligatoires côté serveur : full_name, date_of_birth, nationality, phone, address, id_document_type, id_document_number, id_document_front, selfie_photo, proof_of_address. id_document_back est le SEUL champ fichier facultatif.
- Validation de chaque fichier en 4 passes, dans l'ordre, avec sortie au premier échec : taille <= settings.KYC_MAX_FILE_SIZE_BYTES (10 Mo par défaut), extension dans {.jpg, .jpeg, .png, .pdf}, content_type dans {image/jpeg, image/png, application/pdf}, puis vérification de la SIGNATURE BINAIRE (magic bytes JPEG FFD8FF, PNG 89504E47…, PDF %PDF-). Un fichier dont le contenu ne correspond pas à son extension est rejeté — garde-fou anti-upload malveillant à conserver impérativement.
- Le flux est remis à zéro (seek(0)) après lecture de l'en-tête pour ne pas corrompre l'enregistrement.
- À la soumission valide : status forcé à PENDING et rejection_reason vidé — c'est ce qui permet la resoumission après un rejet.
- Notification KYC_SUBMITTED à l'utilisateur, puis redirection vers le tableau de bord KYC.
- L'assistant en 4 étapes est purement client (Alpine) : aucune validation par étape côté serveur, tout est validé d'un bloc au POST final.
- Les classes CSS des champs sont appliquées par un script au chargement (le formulaire Django ne porte pas de widgets stylés).

**KYC — file de revue admin**
<br>_Liste paginée des dossiers KYC avec filtre de statut et recherche, réservée au staff._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_list`, `backend/templates/dashboard/admin/kyc_list.html`

- Accès restreint par @staff_member_required (redirection vers le login admin, pas un 403).
- Recherche q appliquée en UNION de querysets sur user__email, full_name et id_document_number (icontains).
- Filtre status appliqué seulement s'il est non vide ; tri par -updated_at ; pagination de 30.
- La liste déroulante des statuts est alimentée depuis KYCProfile.STATUS_CHOICES via le paginator — à remplacer par une source de vérité explicite dans la refonte.

**KYC — détail d'un dossier admin**
<br>_Fiche complète d'un dossier : identité déclarée, liens vers les documents confidentiels, formulaires d'approbation et de rejet._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_detail`, `backend/templates/dashboard/admin/kyc_detail.html`

- @staff_member_required ; get_object_or_404 avec select_related user et reviewed_by.
- Un lien de document n'est affiché que si le fichier correspondant est présent sur le profil.
- Les liens documents s'ouvrent en target=_blank avec rel=noopener.

**KYC — consultation sécurisée d'un document**
<br>_Service de fichier qui diffuse une pièce justificative KYC au staff sans jamais exposer d'URL média publique._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_document`

- Allowlist stricte des noms de champ {id_document_front, id_document_back, selfie_photo, proof_of_address} : toute autre valeur lève Http404 — protection contre la traversée de champ/chemin, à ne jamais assouplir.
- 404 si le champ est vide ou si le fichier est introuvable sur le stockage (FileNotFoundError/OSError), jamais de 500.
- Content-Type deviné par mimetypes avec repli application/octet-stream.
- En-têtes de sécurité obligatoires sur la réponse : Cache-Control: private, no-store et X-Content-Type-Options: nosniff — les documents d'identité ne doivent être ni mis en cache ni interprétés par sniffing.
- @staff_member_required : aucun accès client à ses propres documents par cette route.

**KYC — approbation d'un dossier**
<br>_Action staff qui valide définitivement un dossier KYC._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_approve`

- @staff_member_required + @require_POST (pas d'approbation par simple GET).
- Écrit status=APPROVED, reviewed_by=request.user, reviewed_at=now, admin_note depuis le POST, et VIDE rejection_reason — un dossier approuvé ne doit jamais conserver un ancien motif de rejet.
- Notification KYC_APPROVED à l'utilisateur.
- INVARIANT INTER-DOMAINE CRITIQUE : KYCProfile.status == 'APPROVED' est la condition unique qui autorise les retraits wallet (wallet/views.py:_can_user_withdraw) et les actions LIVE de l'assistant (ai_assistant/services_guards.py:TradingGuards.check_kyc). Toute modification de cette valeur ou de ce champ casse deux autres domaines.
- Mise à jour ciblée par update_fields (status, reviewed_by, reviewed_at, admin_note, rejection_reason, updated_at).

**KYC — rejet d'un dossier**
<br>_Action staff qui refuse un dossier avec un motif communiqué au client et une note interne._
<br>Points d'entrée : `backend/dashboard/views.py:admin_kyc_reject`

- @staff_member_required + @require_POST.
- rejection_reason est requis dans le formulaire HTML mais le serveur applique un repli « Dossier rejeté. » si la valeur est vide après strip — un dossier rejeté a TOUJOURS un motif non vide.
- Écrit status=REJECTED, reviewed_by, reviewed_at, admin_note.
- Notification KYC_REJECTED contenant le motif dans le message ET dans le payload, invitant explicitement à resoumettre.
- Le profil reste modifiable : la resoumission (kyc_submit) le repasse en PENDING et efface le motif.

**Administration Django du KYC**
<br>_Interface d'administration Django sur KYCProfile : liste, filtres, recherche et champs en lecture seule._
<br>Points d'entrée : `backend/dashboard/admin.py:KYCProfileAdmin`

- list_display : user, status, full_name, nationality, reviewed_by, updated_at ; list_filter : status, nationality, id_document_type ; search_fields : user__email, full_name, id_document_number.
- created_at, updated_at et reviewed_at sont en lecture seule.
- C'est le SEUL endroit où le statut UNDER_REVIEW peut être positionné — et l'admin permet de modifier le statut sans passer par les vues d'approbation/rejet, donc sans notification ni traçabilité reviewed_by/reviewed_at.

**Liste et statistiques des backtests**
<br>_Page /backtests/ : compteurs total / terminés / en cours / échoués, grille des stratégies lançables, table paginée des exécutions avec statut en direct._
<br>Points d'entrée : `backend/leo_backtesting/views.py:BacktestListView`, `backend/leo_backtesting/views.py:_backtests_for_user`, `backend/leo_backtesting/views.py:_available_strategies_for`, `backend/templates/leo_backtesting/backtest_list.html`

- Cloisonnement : le staff voit tous les runs, tout autre utilisateur uniquement requested_by=user (_backtests_for_user). Testé par test_users_cannot_read_each_others_backtests.
- Les compteurs sont calculés sur le queryset COMPLET, pas sur la page courante ; count_running agrège PENDING + RUNNING.
- Stratégies lançables = Strategy.objects.visible_to(user) (staff=tout, sinon owner=user OU owner NULL) filtrées sur is_active=True, triées par nom, limitées à 50.
- running_backtest_ids est sérialisé en JSON dans le template pour amorcer le polling client.
- Pagination de 20, tri -created_at.
- État vide dédié si aucune stratégie disponible (CTA vers /strategies/) et si aucun backtest.

**Lancement d'un backtest**
<br>_Bouton par stratégie qui planifie l'exécution d'un backtest en arrière-plan via l'outbox transactionnel._
<br>Points d'entrée : `backend/leo_backtesting/views.py:LaunchBacktestView`, `backend/leo_backtesting/services.py:execution_assumptions_for`, `backend/leo_backtesting/services.py:build_run_parameters`, `backend/leo_backtesting/outbox.py:enqueue_backtest_run`, `backend/tests_phase/test_backtesting_engine.py:test_launch_is_outbox_driven_deduplicated_and_user_scoped`

- La stratégie est résolue via _available_strategies_for(user) : une stratégie non visible ou inactive renvoie 404 — pas de lancement sur le bien d'autrui.
- Les hypothèses de coût sont dérivées de l'asset_class de la stratégie dans settings.BACKTEST_EXECUTION_COSTS, avec repli sur la clé DEFAULT ; initial_cash vient de BACKTEST_DEFAULT_INITIAL_CASH.
- start_date et end_date sont initialisés à la date du jour : ce sont des valeurs provisoires, RÉÉCRITES par le moteur avec les bornes réelles des bougies.
- parameters embarque un snapshot immuable de la stratégie (id, name, updated_at, parameters, entry_rules, exit_rules) : le résultat reste interprétable même si la stratégie est modifiée après coup.
- parameters['data']['requested_end_at'] = maintenant : la borne haute du jeu de données est FIGÉE au moment de la demande, pas au moment de l'exécution — garantit la reproductibilité malgré le délai de file.
- La création du run et l'enqueue outbox se font dans la MÊME transaction atomique, avec idempotency_key='backtest:<run_id>:attempt:1'. Interdiction absolue d'appeler run_backtest_task.delay() directement depuis la vue.
- Contrainte de base leo_bt_one_active_per_user_strategy : un seul run PENDING ou RUNNING par couple (requested_by, strategy). L'IntegrityError est rattrapée et redirige vers le run existant avec un warning — jamais de doublon, jamais de 500.
- Si l'IntegrityError survient sans run actif retrouvable, on logge l'exception et on renvoie un message d'erreur vers la liste.

**Détail d'un backtest**
<br>_Page de résultat : KPI, courbe d'équité, indicateurs, hypothèses d'exécution, traçabilité des données et journal des trades._
<br>Points d'entrée : `backend/leo_backtesting/views.py:BacktestDetailView`, `backend/templates/leo_backtesting/backtest_detail.html`

- Même cloisonnement que la liste (_backtests_for_user) : un run d'un autre utilisateur donne 404.
- KPI affichés : final_equity, return_pct, max_drawdown_pct, win_rate_pct, avec « — » si la métrique est absente (default_if_none).
- Indicateurs : trades_count, sharpe_ratio, profit_factor, exposure_time_pct, total_commission.
- Traçabilité affichée : data_points, metrics.data_quality.estimated_missing_candles, engine_version, data_checksum (empreinte SHA256) — bloc d'auditabilité à conserver intégralement.
- Hypothèses d'exécution affichées : initial_cash, commission, spread, slippage stockés sur le run (pas les settings courants).
- Si metrics.trades_log_truncated est vrai, un bandeau indique l'échantillonnage « stored_trades_count / trades_count » — l'utilisateur doit toujours savoir que le journal est partiel.
- Si status=FAILED, un encart rouge affiche failure_message avec repli « Erreur de calcul non détaillée. ».
- La courbe d'équité est transmise par json_script (pas d'interpolation JS directe) et rendue par Chart.js.

**Suivi du statut d'un backtest (polling)**
<br>_Endpoint JSON de statut interrogé toutes les 3 s par la liste pour les runs en cours, avec toast de fin et rechargement automatique._
<br>Points d'entrée : `backend/leo_backtesting/views.py:BacktestStatusView`, `backend/templates/leo_backtesting/backtest_list.html:228-293`

- Double garde de sécurité : queryset déjà scopé par _backtests_for_user PUIS re-vérification explicite `not request.user.is_staff and run.requested_by_id != request.user.id` → Http404. La redondance est volontaire, ne pas la supprimer.
- Payload : id, status, name, metrics, failure_message, started_at, completed_at, updated_at (dates en ISO ou null).
- Côté client : polling séquentiel toutes les 3 s, retrait de l'id de la liste dès DONE ou FAILED, toast de succès/échec, puis rechargement complet de la page 1,2 s après la fin de tous les runs.
- Les erreurs réseau du polling sont avalées silencieusement (catch vide) — le polling ne doit jamais casser la page.
- La cellule de statut est mise à jour par innerHTML depuis une table de correspondance figée (valeurs constantes, pas de données serveur interpolées).

**Exécution asynchrone d'un backtest (worker)**
<br>_Tâche Celery qui réserve un run PENDING, exécute le moteur, persiste le résultat ou marque l'échec, puis notifie l'utilisateur._
<br>Points d'entrée : `backend/leo_backtesting/tasks.py:run_backtest_task`, `backend/leo_backtesting/services.py:claim_backtest_run`, `backend/leo_backtesting/services.py:mark_backtest_failed`, `backend/leo_backtesting/outbox.py:enqueue_backtest_run`

- Tâche en acks_late=True + reject_on_worker_lost=True : un worker tué ne perd pas le message.
- Le task_id Celery est dérivé de l'événement outbox (`outbox-<event_id>`) : rejouer le même événement ne crée pas deux exécutions.
- claim_backtest_run est la barrière de concurrence : SELECT FOR UPDATE, n'accepte QUE status='PENDING', passe à RUNNING, pose worker_task_id et started_at, remet completed_at et failure_message à zéro et incrémente attempt_count. Un seul worker peut réserver un run (test_only_one_worker_can_claim_a_pending_run).
- Si le claim échoue : run introuvable → {ok:False, error:'not_found'} ; run déjà pris → {ok: status=='DONE', skipped:True} — jamais d'exception, jamais de duplication.
- En cas d'exception du moteur : mark_backtest_failed puis notification d'échec ; la tâche retourne un dict d'erreur sans relancer elle-même (la relance appartient au recovery).
- mark_backtest_failed est protégée : SELECT FOR UPDATE, ne touche jamais un run déjà DONE ou FAILED, et ignore l'appel si worker_task_id ne correspond pas au sien (un worker obsolète ne peut pas faire échouer le run d'un autre). Message tronqué à 1000 caractères et recopié dans metrics['error'].
- Logs structurés obligatoires : backtest.run.started / .completed / .failed / .skipped / .not_found.

**Moteur de backtest SMA Cross et réconciliation**
<br>_Cœur de calcul : stratégie de croisement de moyennes mobiles exécutée sur les bougies historiques avec coûts d'exécution, contrôles de données et réconciliation comptable fail-closed._
<br>Points d'entrée : `backend/leo_backtesting/services.py:_execute_backtest`, `backend/leo_backtesting/services.py:SmaCrossStrategy`, `backend/leo_backtesting/services.py:_configuration_from_run`, `backend/leo_backtesting/services.py:_load_and_validate_candles`, `backend/leo_backtesting/services.py:_validate_ohlcv_row`, `backend/leo_backtesting/services.py:_normalize_metrics`, `backend/leo_backtesting/services.py:_serialize_equity_curve`, `backend/leo_backtesting/services.py:_serialize_trades`, `backend/leo_backtesting/services.py:_checksum`

- Refus d'exécuter si run.status != 'RUNNING' (BacktestRunStateError) — le moteur ne s'auto-promeut jamais.
- Configuration : n1 et n2 entiers strictement positifs, n1 < n2 STRICT, n2 <= 5000 ; initial_cash dans [0.01, 1e18] ; commission dans [0, 0.10] ; spread et slippage dans [0, 0.05]. Ces bornes sont doublées par des CheckConstraint en base (leo_bt_cost_rates_valid, leo_bt_initial_cash_positive, leo_bt_dates_ordered).
- Données : Candle filtrées sur asset ET timeframe de la stratégie avec close_time <= now — JAMAIS de bougie non clôturée (anti look-ahead).
- Bornes de période : requested_start_at inclusive ; requested_end_at inclusive si c'est un datetime, exclusive au jour+1 à minuit si c'est une date. Une borne illisible lève BacktestConfigurationError.
- Volume maximal BACKTEST_MAX_CANDLES (200 000) : dépassement → BacktestDataError demandant une plage plus étroite.
- Minimum n2+2 bougies closes, sinon échec explicite (test_task_marks_missing_data_failed_without_creating_duplicate).
- Validation OHLCV ligne à ligne, fail-closed : valeurs numériques finies, OHLC strictement > 0, high >= max(open,close), low <= min(open,close), high >= low, volume >= 0, horodatages strictement croissants. Une bougie incohérente fait échouer tout le run (test_inconsistent_ohlc_data_fails_closed).
- Qualité des données mesurée et conservée : gap_count (écart > 1,5 × l'intervalle attendu du timeframe) et estimated_missing_candles, stockés dans metrics.data_quality et parameters.data.
- Moteur backtesting.py configuré en trade_on_close=False, hedging=False, exclusive_orders=True, finalize_trades=True. Le slippage est modélisé en s'AJOUTANT au spread (spread effectif = spread + slippage) ; le modèle est documenté dans parameters.execution.slippage_model='added_to_bid_ask_spread'.
- SmaCrossStrategy : achat au croisement haussier si pas déjà long ; en mode allow_short, vente au croisement baissier si pas déjà short ; sinon (long-only) fermeture de la position au croisement baissier.
- RÉCONCILIATION OBLIGATOIRE (BacktestInvariantError, le run part en FAILED) : (1) final_equity doit égaler initial_cash + (PnL brut des trades − commissions) à la tolérance max(0.01, initial×1e-8) ; (2) le dernier point de l'equity curve doit coïncider avec final_equity à la même tolérance ; (3) le Return [%] rapporté par le moteur doit coïncider avec le rendement recalculé à 1e-6. Un PnL non fini dans le registre des trades est également rejeté.
- La réconciliation utilise le PnL BRUT COMPLET (somme sur tous les trades), jamais le journal tronqué — la troncature du journal ne doit jamais fausser le contrôle (test_large_trade_journal_is_bounded_without_breaking_reconciliation).
- Equity curve sous-échantillonnée à BACKTEST_MAX_EQUITY_POINTS (5000) par pas régulier, en forçant toujours la présence du DERNIER point (sinon la réconciliation (2) échouerait).
- Journal des trades borné à BACKTEST_MAX_TRADE_LOG_ROWS (10 000) : moitié début + moitié fin, avec trades_log_truncated=True et stored_trades_count conservés dans les métriques.
- Empreinte SHA256 des lignes OHLCV brutes (open_time, close_time, O, H, L, C, V) stockée dans data_checksum — reproductibilité et auditabilité.
- start_date et end_date du run sont RÉÉCRITS avec les bornes réelles du dataframe ; parameters.data est enrichi (asset_id, symbole, timeframe, start_at, end_at, candle_count, checksum, qualité).
- Toutes les valeurs non finies (NaN/inf) sont normalisées en None à la sérialisation ; max_drawdown_pct et avg_drawdown_pct sont stockés en valeur absolue.
- Les coûts d'exécution doivent effectivement réduire l'équité simulée (test_execution_costs_reduce_simulated_equity).

**Persistance du résultat sous bail d'exécution**
<br>_Écriture finale du résultat d'un backtest, protégée contre l'écrasement par un worker périmé._
<br>Points d'entrée : `backend/leo_backtesting/services.py:_persist_result`

- L'écriture est un UPDATE conditionnel sur (pk, status='RUNNING', worker_task_id=<le sien>) — pas un save() d'instance.
- Si 0 ligne est mise à jour, on lève BacktestRunStateError('lost its execution lease') : un worker qui a perdu son bail (run requeué, repris par un autre, ou déjà terminé) ne peut JAMAIS écraser un résultat.
- L'UPDATE écrit d'un seul coup start_date, end_date, parameters, metrics, equity_curve, trades_log, data_points, data_checksum, engine_version, status='DONE', completed_at, updated_at et vide failure_message.

**Récupération des backtests bloqués**
<br>_Tâche périodique qui détecte les runs RUNNING figés et les requeue ou les fait échouer définitivement._
<br>Points d'entrée : `backend/leo_backtesting/tasks.py:recover_stale_backtest_runs_task`, `backend/tests_phase/test_backtesting_engine.py:test_stale_run_is_requeued_once_through_outbox`

- Cible les runs status='RUNNING' dont started_at est antérieur à now − BACKTEST_STALE_RUN_SECONDS (600 s par défaut), limités à 100 par passage.
- Chaque candidat est re-vérifié sous SELECT FOR UPDATE (status toujours RUNNING, started_at toujours périmé) avant toute action — protection anti-course avec un worker qui vient de finir.
- Si attempt_count >= BACKTEST_MAX_ATTEMPTS (2) : status=FAILED, failure_message='Backtest interrompu après plusieurs tentatives.', metrics={'error': ...}, completed_at renseigné, puis notification d'échec.
- Sinon : remise en PENDING avec worker_task_id, started_at et failure_message réinitialisés, puis ré-enqueue outbox avec idempotency_key='backtest:<id>:attempt:<attempt_count+1>'. LA CLÉ DOIT VARIER PAR TENTATIVE, sinon l'idempotence de l'outbox avale silencieusement la relance.
- La notification d'échec est envoyée APRÈS la sortie du bloc transaction.atomic (variable failed_run), jamais à l'intérieur.
- Renvoie un compteur {requeued, failed} et ne logge en warning que s'il y avait des candidats.

**Notification temps réel de fin / échec de backtest**
<br>_Diffusion WebSocket à l'utilisateur quand son backtest se termine ou échoue._
<br>Points d'entrée : `backend/leo_backtesting/tasks.py:_notify_user_backtest_done`, `backend/leo_backtesting/tasks.py:_notify_user_backtest_failed`, `backend/core/realtime.py:RealtimeBroadcastService.broadcast_notification`

- INVARIANT : toute exception de notification est capturée et seulement loggée — une notification qui échoue ne doit JAMAIS faire échouer ni rejouer le backtest, ni modifier son statut.
- Sortie immédiate sans rien envoyer si run.requested_by_id est NULL (run système sans demandeur).
- Payload de succès : kind='backtest_done', level='success', message 'Backtest #<id> terminé : <name>', backtest_id. Payload d'échec : kind='backtest_failed', level='error', message tronqué à 200 caractères, backtest_id.
- Ces messages sont UNIQUEMENT diffusés sur le channel layer : aucune ligne Notification n'est persistée. Si l'utilisateur n'est pas connecté au moment de la fin du run, l'information est perdue — écart à corriger dans la refonte (push mobile / notification persistée).
- La page liste des backtests ne consomme pas cette WS : elle utilise le polling HTTP de statut.

</details>

<details><summary>Pièges de migration repérés</summary>

- Le domaine n'a AUCUN endpoint dans api/urls.py : aucune des URLs dashboard/, premium/, kyc, backtests/ n'est exposée en REST. BacktestRunSerializer existe mais n'est importé nulle part (code mort), et BacktestRunForm non plus. Tout ce domaine est à créer en API, pas à brancher.
- Logique métier enfouie dans les vues : HedgeFundDashboardLiveDataView (views.py:293-707) contient le calcul du prix live, la déduplication des bougies, le traitement spécial des synthétiques Deriv, le recalcul d'equity et d'available_cash et les progressions TP/SL. Rien de tout cela n'est dans un service testable — à extraire avant portage, sinon la logique sera réimplémentée (et divergera) côté React et Flutter.
- Règle des actifs synthétiques Deriv (préfixes R_, JD, CRASH, BOOM, VOL, STEP, RDBEAR, RDBULL) : elle neutralise un faux PnL linéaire. Si elle est perdue, le dashboard affichera des PnL inventés sur ces instruments. La liste de préfixes est codée en dur dans la vue.
- Lecture défensive du schéma (_existing_table_columns, _portfolio_safe_queryset, _hydrate_portfolio_defaults) : ce sont des contournements d'un décalage modèle/table en production. Ils masquent des colonnes réellement absentes. Avant de les supprimer dans la refonte, il faut vérifier l'état réel du schéma de production, sinon le dashboard lèvera des ProgrammingError.
- Duplication de logique graphique dans views_premium.py : le calcul de pnl_snapshots, allocation et risk_drawdown est écrit DEUX fois (dans PremiumCockpitView.get_context_data et dans les helpers _build_* de CockpitDataView). Toute divergence produit un écart entre le rendu initial et le rafraîchissement.
- Deux cockpits coexistent avec deux stacks front différentes : fund_dashboard.html (Alpine + Chart.js inline + endpoint fund-dashboard-live) et premium/cockpit.html (vanilla JS + LeoWS/LeoAnim/LeoCharts + endpoint premium/data). Ils affichent les mêmes données avec des calculs différents (notamment equity et available_cash recalculés seulement côté fund-dashboard-live). Décider lequel fait foi avant de porter.
- Boutons morts à ne pas reproduire tels quels : les sélecteurs de période 1h/4h/1d/1w du graphe P&L du cockpit (classe leo-tf-btn) n'ont aucun gestionnaire d'événement et aucun endpoint ne supporte un filtre de période.
- Blocs non rafraîchis : le JSON /premium/data/ ne renvoie ni les opportunités, ni les décisions de risque, ni le fil d'activité ; la tape des ordres n'est jamais mise à jour par le JS. Ces blocs ne bougent qu'au rechargement complet de la page — régression silencieuse si on la reproduit à l'identique.
- Incohérence d'unité sur la jauge de drawdown : le flux WS portefeuille envoie un pourcentage que cockpit.js divise par 100, alors que le kind risk_update du flux dashboard envoie déjà un ratio 0..1. Normaliser une seule unité côté API.
- MarketOpportunity n'a pas de propriétaire : build_cockpit_context ne fait que PRIORISER les opportunités liées aux positions de l'utilisateur, il ne filtre pas. Les mêmes opportunités sont visibles par tous. Ne pas prendre ce tri pour un cloisonnement de données lors de la mise en place du RBAC.
- L'admin Django sur KYCProfile permet de changer le statut (y compris vers APPROVED) sans passer par admin_kyc_approve : ni notification, ni reviewed_by, ni reviewed_at, ni purge du rejection_reason. Comme APPROVED débloque les retraits wallet et les actions LIVE, c'est un contournement de contrôle à verrouiller.
- Le statut KYC UNDER_REVIEW est dans les choix du modèle et géré par le template, mais n'est jamais positionné par le code applicatif — soit un workflow inachevé, soit un état mort. À trancher avant de l'exposer dans la nouvelle UI.
- Les notifications de fin/échec de backtest ne sont pas persistées en base (broadcast_notification diffuse seulement sur le channel layer) : l'information est perdue si l'utilisateur n'est pas connecté. Bloquant pour Flutter, où l'application est le plus souvent en arrière-plan.
- État implicite en session : trading_mode_toggle écrit request.session['trading_mode'] pour l'affichage de la sidebar alors que la vérité est le champ mode des BrokerAccount. Un client React/Flutter sans cookie de session n'aura pas cet état — il faut le dériver des comptes broker, jamais le stocker côté client.
- Tous les endpoints JSON du domaine (fund-dashboard-live, premium/data, backtests/<pk>/status) sont authentifiés par session Django et protégés par CSRF sur les POST (formulaires). Le portage vers une auth par jeton doit couvrir aussi les WebSockets, qui s'appuient aujourd'hui sur scope['user'] issu du cookie de session.
- Les actions du cockpit (approve / reject / execute / resolve-kill-switch) et toutes les actions KYC sont des POST de formulaire suivis d'un redirect, avec restitution par le framework de messages Django. Il n'existe aucun code d'erreur structuré : la refonte doit définir des codes (reco non exécutable, blocage risque, KYC invalide) avant que le front puisse réagir correctement.
- dashboard/urls.py importe BacktestListView, BacktestDetailView et LaunchBacktestView sans jamais les utiliser dans urlpatterns (import mort). Les routes de backtest réelles sont dans leo_backtesting/urls.py monté sur /backtests/.
- run_backtest(strategy) sans backtest_run crée un run directement en RUNNING (worker_task_id 'sync-<uuid>', attempt_count=1) en contournant l'outbox et la contrainte d'unicité : ce chemin n'est utilisé que par les tests, mais il reste appelable et pourrait créer des runs concurrents s'il était utilisé en production.

</details>

---

## Oubliées par la cartographie par domaine

> Trouvées par un agent dédié relisant `urls.py`, les templates, les commandes
> de gestion, le beat Celery, le routing WebSocket, les signaux et l'admin.

| Fonctionnalité | Où | Pourquoi elle a été manquée | Cibles |
|---|---|---|:--:|
| **Sondes de santé applicative (liveness / readiness / diagnostics)** | `backend/core/health.py:health_live, health_ready, health_diagnostics — montées dans backend/leoTrade/urls.py sur /health/live/, /health/ready/, /health/diagnostics/` | Trois routes réelles sans template ni écran : les agents ont cartographié par page et par modèle, donc une route purement opérationnelle est passée au travers. Indispensable pour les healthchecks Docker/Dokploy demandés au point 9. | infrastructure/backend |
| **Contrat d'API publié : schéma OpenAPI, Swagger UI et Redoc** | `backend/api/urls.py:SpectacularAPIView / SpectacularSwaggerView / SpectacularRedocView (/api/v1/schema/, /api/v1/docs/, /api/v1/redoc/) + SPECTACULAR_SETTINGS dans backend/leoTrade/settings/base.py` | Pas une fonctionnalité utilisateur, donc hors radar des agents ; c'est pourtant la source de génération des clients TypeScript (web) et Dart (Flutter) de la refonte. | backend/web/mobile |
| **API REST v1 existante (24 ViewSets DRF + leurs actions)** | `backend/api/urls.py (router) et backend/api/views/{portfolio,execution,risk,ai,brokers}.py — actions : refresh, snapshot, set_default, import_live, exposures, compute_correlations, create_manual, submit, cancel, reconcile_portfolio, approve/reject/execute, generate_for_portfolio, test_connection, sync_constraint, resolve_for_portfolio, refresh_states` | Les agents ont recensé les écrans Django (vues/templates) et considéré l'API comme un détail d'implémentation ; or une grande partie du socle REST à reprendre existe déjà et doit être mise en correspondance route par route pour garantir l'absence de régression. | backend/web/mobile |
| **Supervision opérationnelle : snapshot système + alerting multicanal** | `backend/core/monitoring.py:collect_operational_snapshot / store_operational_snapshot / dispatch_operational_alerts ; backend/core/alerting.py:send_alert (email, Telegram, webhook) ; backend/core/tasks.py:collect_operational_snapshot_task (beat 30 s) et dispatch_operational_alerts_task` | Aucune URL, aucun template, aucun modèle : la fonctionnalité ne vit que dans des tâches Celery et du cache Redis. Elle est pourtant le filet de sécurité de production et mérite un écran back-office « Statut système ». | backend/infrastructure/back-office |
| **Métriques Prometheus métier (collector opérationnel)** | `backend/core/metrics.py:OperationalMetricsCollector, register_operational_metrics() — enregistré dans backend/core/apps.py:ready()` | Les agents n'ont retenu que la protection de l'endpoint /metrics (MetricsAccessMiddleware), pas le fait que des métriques métier personnalisées y sont publiées via un hook ready(). | infrastructure/backend |
| **Kill switch global de la plateforme (feature flag trading runtime)** | `backend/core/feature_flags.py:is_trading_enabled / set_trading_enabled / require_trading_enabled — consommé par backend/execution/services.py:578 et :1023 et backend/execution/tasks.py:389` | Confondu avec le kill switch par portefeuille (risk) déjà recensé. Il s'agit d'une coupure de TOUT le trading, à chaud, sans redéploiement (cf. commentaire backend/leoTrade/settings/prod.py:34). Aucune interface ne l'expose aujourd'hui : à exposer en back-office dans la refonte. | backend/back-office |
| **Limitation de débit HTTP globale (middleware) et throttles DRF scopés** | `backend/core/rate_limit.py:SimpleRateLimitMiddleware ; REST_FRAMEWORK DEFAULT_THROTTLE_RATES dans backend/leoTrade/settings/base.py (scopes auth 10/min, sensitive 30/min, ai 20/min)` | Protection transverse invisible depuis les écrans. Elle conditionne le comportement des clients React et Flutter (gestion du 429, backoff, file d'attente des retries). | backend/web/mobile |
| **Rétention de l'Outbox et rejeu administrable des événements morts** | `backend/core/tasks.py:cleanup_published_outbox_events_task (beat quotidien 3h15) et backend/core/admin.py:OutboxEventAdmin.retry_dead_events (action admin)` | L'Outbox transactionnel est bien recensé comme mécanisme de dispatch, mais ni sa purge planifiée ni l'exploitation manuelle des dead letters n'apparaissent. Ce sont deux capacités d'exploitation à reprendre. | backend/back-office |
| **Purge planifiée des clés d'idempotence** | `backend/execution/tasks_maintenance.py:cleanup_old_idempotency_keys_task (beat quotidien 3h00)` | L'idempotence des commandes API est listée, pas son cycle de vie côté rétention. À conserver sous peine de croissance non bornée de la table. | backend |
| **Export CSV de l'audit des décharges de risque (archivage légal)** | `backend/risk/admin.py:_export_override_audit_csv (« Exporter la sélection en CSV (archivage légal) ») + RiskOverrideAuditAdmin en lecture seule stricte (readonly_fields, pas d'ajout/modif/suppression)` | Les agents ont recensé « Audit immuable des décharges de risque » mais pas la fonction d'export, seul chemin d'extraction réglementaire existant. La mission demande explicitement les exports. | back-office/web |
| **Renvoi de notifications depuis l'administration** | `backend/notifications/admin.py:NotificationAdmin.actions = [resend_notifications]` | Action d'admin, donc hors des templates et des urls applicatives. C'est le seul outil de rattrapage manuel d'une livraison ratée. | back-office |
| **Expiration automatique des recommandations IA** | `backend/trading/tasks_ai.py:expire_trade_recommendations_task (beat toutes les minutes)` | Seules les expirations d'opportunités et de trade ideas ont été relevées ; la tâche équivalente sur TradeRecommendation (objet distinct, exposé dans l'AI Radar et l'API) a été oubliée. | backend |
| **Heures silencieuses, filtrage par catégorie et langue des notifications** | `backend/notifications/models.py:NotificationPreference.in_quiet_hours() et .channel_allowed() — catégories trade/risk/broker/ai/security/reports, preferred_language fr\|en, phone_number, whatsapp_number` | Les agents ont recensé l'écran et l'API de préférences, pas les règles métier qu'ils portent : fenêtre silencieuse chevauchant minuit, ignorée par les événements critiques, et canal désactivé automatiquement si le numéro est absent. Ce sont des règles à reporter telles quelles dans l'UI web et mobile. | backend/web/mobile |
| **Conversations IA partagées entre utilisateurs (participants et rôles)** | `backend/ai_assistant/models.py:AssistantConversationParticipant (rôles owner/viewer) + backend/ai_assistant/admin.py:ParticipantAdmin` | Modèle sans vue dédiée : le centre des conversations a été recensé comme mono-utilisateur. Le modèle prévoit pourtant un partage avec rôles, ce qui change le cloisonnement des données côté API. | backend/web/mobile |
| **Pièces jointes dans les conversations de l'assistant IA** | `backend/ai_assistant/models.py:AssistantAttachment (FileField upload_to="assistant/attachments/%Y/%m/", filename, content_type, size_bytes)` | Aucune route ni template ne l'expose aujourd'hui, donc aucun agent ne l'a vu. C'est exactement la brique « caméra / import de fichiers » demandée au point 6 de la mission : elle existe déjà en base et doit être reprise, pas réinventée. | backend/web/mobile |
| **Double confirmation des actions sensibles de l'assistant** | `backend/ai_assistant/models.py:AssistantActionRequest.requires_double_confirmation et .confirmations_received` | « Actions confirmables de l'assistant » a été recensé comme une confirmation unique. Le modèle gère un second palier de confirmation pour les actions à fort impact — à matérialiser dans les UI web et mobile. | backend/web/mobile |
| **Détection de patterns chartistes explicable** | `backend/trading/services/ai/patterns.py:detect_patterns, DetectedPattern (BREAKOUT_UP/DOWN, REVERSAL_UP/DOWN, TREND_CONTINUATION_UP/DOWN, SQUEEZE)` | Fondu dans « Scan de marché et calcul de features techniques » : c'est un module distinct, à base de règles et volontairement interprétable, dont les libellés et la force (0..1) sont destinés à être affichés à l'utilisateur. | backend/web/mobile |
| **Moteur de confiance hedge fund (ajustement régime / apprentissage / risque)** | `backend/trading/services/hedge_fund/confidence_engine.py:ConfidenceEngine.assess + modèle ConfidenceAssessment (backend/trading/models_hedge_fund.py)` | Les agents ont listé le moteur hedge fund, le sizing et la boucle d'apprentissage, mais pas l'étage qui recalcule le score de confiance d'une idée en fonction du régime de marché, du snapshot d'apprentissage et de l'état de risque. C'est lui qui produit le chiffre affiché à l'utilisateur. | backend/web/mobile |
| **Commande de configuration de l'identité publique du site** | `backend/core/management/commands/configure_site_identity.py (django.contrib.sites, domaine depuis SITE_BASE_URL, nom depuis BRAND_FULL_NAME)` | Commande de déploiement sans effet visible en runtime. Elle conditionne pourtant les liens absolus des e-mails allauth et des callbacks de paiement : à rejouer sur staging et production. | infrastructure |
| **Commande de diagnostic système exploitable par une sonde** | `backend/core/management/commands/system_diagnostics.py (options --fresh, --json, --no-fail ; vérifie DB, cache, snapshot opérationnel)` | Les agents ont retenu core/management/commands/test_realtime.py mais pas celle-ci, qui est le diagnostic global (sortie JSON destinée à une sonde externe). | infrastructure/backend |
| **Pages d'erreur personnalisées 400 / 403 / 404 / 500** | `backend/templates/400.html, 403.html, 404.html, 500.html (résolution automatique Django, sans handlerXXX explicite)` | Templates racine sans vue associée : invisibles d'une cartographie par urls.py. Le point 8 de la mission impose de reprendre la gestion des erreurs. | web |
| **Composants d'état d'interface mutualisés (vide, chargement, déconnexion, pagination)** | `backend/templates/_partials/_empty_state.html, _loading_skeleton.html, _disconnect_badge.html et backend/templates/partials/pagination.html — utilisés par strategy_list, portfolio_list, asset_list, order_list, order_detail, signal_list, backtest_list, kyc_list, withdrawal_queue, layout/base.html` | Partials réutilisables, donc rattachés à aucune fonctionnalité métier. Ils constituent pourtant le contrat UX existant (états vides, squelettes de chargement, badge de perte de connexion WebSocket, pagination) que la refonte doit reproduire en composants shadcn/ui et Flutter. | web/mobile |
| **Bibliothèque front de graphiques financiers et d'animations de valeurs** | `backend/static/js/leo_charts.js (pnlLine, portfolioDonut, riskGauge, candlestick, miniSparkline), backend/static/js/leo_animations.js (flashValue hausse/baisse, tickRow, toast, parseNumber format FR), backend/static/js/leo_bootstrap.js (toast sur bascule WebSocket, anti double-clic submit, respect de prefers-reduced-motion), backend/static/css/leo_animations.css` | Seul leo_websocket.js a été recensé (« Manager WebSocket client »). Le reste définit le langage visuel existant — flash vert/rouge sur changement de prix, sparklines, jauge de risque, accessibilité mouvement réduit — à transposer, pas à perdre. | web/mobile |
| **Coquille de navigation applicative (sidebar drawer mobile, en-tête contextuel)** | `backend/templates/layout/base.html (sidebar en drawer sous 1024 px avec overlay et aria-expanded, bascule PAPER/LIVE en en-tête, solde wallet avec raccourcis dépôt/retrait, badge non-lu, ticker marché via trading:market-data)` | Template de layout, rattaché à aucune fonctionnalité : chaque agent a décrit les pages, personne le châssis qui les contient. C'est pourtant la structure de navigation complète à reproduire en React et en Flutter (GoRouter shell). | web/mobile |
| **Validation des fichiers du dossier KYC à l'upload** | `backend/dashboard/form.py:KYCSubmissionForm._validate_uploaded_file (taille max settings.KYC_MAX_FILE_SIZE_BYTES = 10 Mo, extensions .jpg/.jpeg/.png/.pdf, content-type image/jpeg\|image/png\|application/pdf) sur id_document_front, id_document_back, selfie_photo, proof_of_address` | La soumission KYC a été recensée comme un écran ; ses règles de validation de fichier n'ont pas été remontées. Elles doivent être rejouées côté API et côté capture photo mobile avant envoi. | backend/web/mobile |
| **Journal d'audit applicatif structuré (métier / sécurité / erreur)** | `backend/audit/services.py:AuditLogService.log_business_event / log_security_event / log_error_event s'appuyant sur backend/core/logging.py:get_logger, log_event` | Le répertoire audit/ n'est pas une app Django installée (absent d'INSTALLED_APPS) et n'a ni modèle ni url : il est passé sous le radar. Distinct du RiskAuditLog du module Risk Control déjà recensé. | backend |
| **Planification dynamique des tâches et persistance des résultats Celery** | `INSTALLED_APPS dans backend/leoTrade/settings/base.py : django_celery_beat et django_celery_results (modèles PeriodicTask / TaskResult administrables), en complément du CELERY_BEAT_SCHEDULE statique (~45 entrées)` | Les agents ont lu le dictionnaire statique du planificateur mais pas le fait qu'un second canal de planification, modifiable en base depuis l'admin, est actif — avec risque de doublon d'exécution si les deux définissent la même tâche. | backend/back-office |
| **Socle d'exploitation : sauvegarde, déploiement, healthcheck et règles d'alerte** | `infrastructure/deploy/backup.sh, deploy.sh, healthcheck.sh, observability/leotrade-alerts.yml, PRODUCTION_RUNBOOK.txt, production.env.example ; infrastructure/docker/Dockerfile et docker-compose.yml` | Hors du répertoire backend/, donc hors du périmètre d'exploration des dix agents. Ce sont les briques directement concernées par les points 7 et 9 (migrations sécurisées, sauvegarde, rollback, staging/production). | infrastructure |
| **Registre extensible de fournisseurs de paiement (emplacements mobile money)** | `backend/wallet/services/registry.py:WalletProviderRegistry et backend/wallet/services/base.py:BaseWalletProvider (create_deposit_intent, create_payout, verify_webhook, parse_webhook_event) ; fichiers mtn_momo.py, orange_money.py, wave.py, payout_service.py, reconciliation.py présents mais VIDES (0 ligne)` | Les agents n'ont recensé que les trois intégrations réellement câblées (Paystack, Stripe, Adyen) implémentées dans backend/wallet/services.py et webhooks.py. Le point d'extension et l'intention produit mobile money Afrique de l'Ouest existent dans l'arborescence — à conserver comme décision d'architecture, sans les compter comme fonctionnalités livrées. | backend |
| **Back-office Django des objets trading : absent (code entièrement commenté)** | `backend/trading/admin.py — les 11 déclarations @admin.register (TradingIntent, TradingIntentEvent, Order, TradeExecution, DerivContract, TradeIdea, TradeIdeaFeedback, AgentRun, MarketRegimeSnapshot, TradeIdeaReview, PortfolioAdvice) sont commentées sur 859 lignes ; seul backend/trading/admin_ai.py est actif (MarketScanRun, MarketOpportunity, TradeRecommendation, AIModelRegistry, AIInferenceLog, DecisionAudit)` | La matrice affirme « Administration des objets d'exécution » ; en réalité le support d'exploitation sur le cœur trading n'existe plus. C'est un manque fonctionnel réel à arbitrer dans la refonte (back-office React ou réactivation), pas une simple ligne de code mort. | back-office |
| **Tolérance au décalage de schéma en base sur le tableau de bord** | `backend/dashboard/views.py:_existing_table_columns (introspection des colonnes réellement présentes), _hydrate_portfolio_defaults, _portfolio_safe_queryset, _safe_get_default_portfolio (capture de ProgrammingError / OperationalError)` | Comportement défensif invisible fonctionnellement : le dashboard fonctionne même si des colonnes de portfolio_portfolio manquent en base. Cela signale une dérive réelle entre les migrations et la production, à vérifier avant toute migration (point 7) — et à ne surtout pas reconduire dans l'API de la refonte. | backend/infrastructure |

## Préoccupations transverses

- Internationalisation et localisation : LANGUAGE_CODE = "fr-fr", USE_I18N = True, TIME_ZONE = "Africa/Abidjan" (= CELERY_TIMEZONE), USE_TZ = True — backend/leoTrade/settings/base.py:173-176. Tous les horodatages métier (états de risque journaliers, rapports 7h, heures silencieuses) sont calculés en heure d'Abidjan : le web et le mobile doivent convertir explicitement et ne jamais présumer le fuseau du device.
- Multi-devise des dépôts : XOF, NGN, GHS, KES, ZAR, USD, EUR (backend/wallet/form.py:CURRENCY_CHOICES) alors que WALLET_DEFAULT_CURRENCY = USD et que les portefeuilles de trading sont en USD. Aucune table de taux de change n'existe : la règle de conversion dépôt → solde est implicite et doit être tranchée et formalisée avant migration.
- Plafonds monétaires par opération codés en dur : DEPOSIT_MIN 1.00 / DEPOSIT_MAX 100 000.00, WITHDRAWAL_MIN 5.00 / WITHDRAWAL_MAX 100 000.00 (backend/wallet/form.py:18-21, commentaire « à ajuster en config selon le KYC tier »). À remonter en configuration serveur et à exposer à l'API pour que les formulaires web et mobile valident les mêmes bornes.
- Précision et arrondi monétaires : backend/core/precision.py et quantize(Decimal("0.01"), ROUND_HALF_UP) répété dans backend/accounting/services.py et les services wallet/portfolio. Le web (TypeScript) et le mobile (Dart) n'ont pas de Decimal natif : il faut interdire le float sur les montants dans les clients et faire porter tout calcul par l'API.
- Pagination normalisée côté API : backend/api/pagination.py:StandardPageNumberPagination (page_size 25, page_size_query_param, max_page_size 200, enveloppe avec page_size dans la réponse) et PAGE_SIZE = 25 — avec un commentaire explicite sur la saturation du client mobile. Les pages Django existantes utilisent des tailles hétérogènes (20, 25, 30, 50) à harmoniser.
- Filtres, recherche et tri : DEFAULT_FILTER_BACKENDS = DjangoFilterBackend + SearchFilter + OrderingFilter (backend/leoTrade/settings/base.py:205). Côté Django, la recherche est actuellement faite à la main par icontains dans backend/wallet/views.py (transactions, wallets admin), backend/dashboard/views.py (file KYC), backend/strategies/views.py et backend/ai_assistant/api.py — à unifier sur les filtres DRF.
- Versionnement d'API : DEFAULT_VERSIONING_CLASS = URLPathVersioning, DEFAULT_VERSION = "v1", ALLOWED_VERSIONS = ["v1"], tout monté sous /api/v1/. Le contrat de version existe déjà et doit être respecté par les clients React et Flutter.
- Limitation de débit par scope : THROTTLE_AUTH 10/min, THROTTLE_SENSITIVE 30/min, THROTTLE_AI 20/min (ScopedRateThrottle), appliquée jusqu'au rafraîchissement de jeton (ThrottledTokenRefreshView dans backend/api/urls.py). Les clients doivent gérer le 429 avec backoff, en particulier le flux de renouvellement automatique de session.
- Durcissement de l'inscription et de l'authentification : honeypot anti-bot ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "website", ACCOUNT_PREVENT_ENUMERATION (messages indifférenciés), ACCOUNT_EMAIL_CONFIRMATION_EXPIRE_DAYS = 3, ACCOUNT_CONFIRM_EMAIL_ON_GET = False (confirmation en POST uniquement, donc pas de lien cliquable direct), ACCOUNT_REAUTHENTICATION_TIMEOUT = 300 s — backend/leoTrade/settings/base.py:262-277. Ces règles conditionnent les écrans d'inscription et les deep links de confirmation en mobile.
- Révocation réelle des sessions : rest_framework_simplejwt.token_blacklist installé, avec le commentaire « déconnexion réelle, pas seulement l'oubli du token côté client ». La déconnexion doit passer par l'endpoint serveur, pas par une simple suppression du stockage local.
- Durcissement des cookies et du transport en production : SECURE_SSL_REDIRECT, HSTS 1 an avec includeSubDomains et preload, SESSION_COOKIE_SECURE/HTTPONLY, CSRF_COOKIE_SECURE/HTTPONLY, SAMESITE Lax, SESSION_COOKIE_AGE 3600 s, SECURE_REFERRER_POLICY, SECURE_CROSS_ORIGIN_OPENER_POLICY (backend/leoTrade/settings/prod.py). SameSite Lax + cookies HttpOnly contraint le choix entre cookies de session et JWT pour un front React servi sur un autre domaine.
- Origines autorisées : CORS_ALLOWED_ORIGINS et CSRF_TRUSTED_ORIGINS pilotés par variables d'environnement, et WebSocket protégé par AllowedHostsOriginValidator dans backend/leoTrade/asgi.py. Chaque nouvel hôte front (staging web, WebView mobile) doit être déclaré aux trois endroits sous peine d'échec silencieux des WebSocket.
- Contexte global injecté dans chaque rendu : backend/core/context_processors.py:global_trading_context et portfolio_context (portefeuille par défaut, solde wallet, mode PAPER/LIVE résolu depuis la session). Sans templates Django, cet état partagé doit devenir un endpoint de bootstrap unique consommé au démarrage par React et Flutter.
- Traçabilité des requêtes : backend/core/middleware.py:RequestIDMiddleware et RequestContextMiddleware, exploités par le logging structuré de backend/core/logging.py. Les clients doivent propager l'identifiant de corrélation et le restituer dans les écrans d'erreur pour rendre le support exploitable.
- Stockage des fichiers : STORAGES / MEDIA_ROOT = BASE_DIR/"media" en système de fichiers local (backend/leoTrade/settings/base.py:183-193) pour les documents KYC et les pièces jointes de l'assistant. Incompatible avec plusieurs instances derrière Dokploy : un stockage objet est à prévoir, et la migration des fichiers existants fait partie de la préservation des données historiques.
- Transport des e-mails : EMAIL_BACKEND par défaut sur la console (backend/leoTrade/settings/base.py:290) alors que l'e-mail est le canal prioritaire des notifications et le support de la vérification d'adresse et de la réinitialisation de mot de passe. Un vrai backend doit être configuré et vérifié en staging avant toute bascule.
