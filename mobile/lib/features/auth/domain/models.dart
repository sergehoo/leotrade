// Modèles d'authentification, alignés sur backend/api/serializers/auth.py.
//
// Les montants et décimaux ne sont jamais convertis en `double` : Dart n'a
// pas de type décimal natif, et un arrondi binaire sur un solde est une
// erreur comptable. Ils restent en `String` jusqu'à l'affichage.

enum KycStatus { notStarted, pending, underReview, approved, rejected, unknown }

KycStatus kycStatusFrom(String? raw) => switch (raw) {
      'NOT_STARTED' => KycStatus.notStarted,
      'PENDING' => KycStatus.pending,
      'UNDER_REVIEW' => KycStatus.underReview,
      'APPROVED' => KycStatus.approved,
      'REJECTED' => KycStatus.rejected,
      _ => KycStatus.unknown,
    };

String kycStatusLabel(KycStatus status) => switch (status) {
      KycStatus.notStarted => "Vérification d'identité non commencée",
      KycStatus.pending => "Vérification d'identité en attente",
      KycStatus.underReview => "Vérification d'identité en cours d'examen",
      KycStatus.approved => "Identité vérifiée",
      KycStatus.rejected => "Vérification d'identité refusée",
      KycStatus.unknown => "État de vérification inconnu",
    };

class Capabilities {
  const Capabilities({
    required this.canTradeLive,
    required this.canTradePaper,
    required this.canWithdraw,
  });

  factory Capabilities.fromJson(Map<String, dynamic> json) => Capabilities(
        canTradeLive: json['can_trade_live'] as bool? ?? false,
        canTradePaper: json['can_trade_paper'] as bool? ?? false,
        canWithdraw: json['can_withdraw'] as bool? ?? false,
      );

  /// Repli volontairement fermé : en l'absence d'information, on n'autorise
  /// rien. Une capacité ouverte par défaut, c'est un ordre réel passé par
  /// quelqu'un qui n'y avait pas droit.
  static const closed = Capabilities(
    canTradeLive: false,
    canTradePaper: false,
    canWithdraw: false,
  );

  final bool canTradeLive;
  final bool canTradePaper;
  final bool canWithdraw;
}

class CurrentUser {
  const CurrentUser({
    required this.id,
    required this.email,
    required this.firstName,
    required this.lastName,
    required this.kycStatus,
    required this.kycRejectionReason,
    required this.mfaEnabled,
    required this.emailVerified,
    required this.capabilities,
  });

  factory CurrentUser.fromJson(Map<String, dynamic> json) => CurrentUser(
        id: json['id'] as int,
        email: json['email'] as String? ?? '',
        firstName: json['first_name'] as String? ?? '',
        lastName: json['last_name'] as String? ?? '',
        kycStatus: kycStatusFrom(json['kyc_status'] as String?),
        kycRejectionReason: json['kyc_rejection_reason'] as String? ?? '',
        mfaEnabled: json['mfa_enabled'] as bool? ?? false,
        emailVerified: json['email_verified'] as bool? ?? false,
        capabilities: json['capabilities'] is Map<String, dynamic>
            ? Capabilities.fromJson(json['capabilities'] as Map<String, dynamic>)
            : Capabilities.closed,
      );

  final int id;
  final String email;
  final String firstName;
  final String lastName;
  final KycStatus kycStatus;
  final String kycRejectionReason;
  final bool mfaEnabled;
  final bool emailVerified;
  final Capabilities capabilities;

  String get displayName {
    final full = '$firstName $lastName'.trim();
    return full.isEmpty ? email : full;
  }
}

/// Résultat d'une tentative de connexion : soit des jetons, soit un défi MFA.
sealed class LoginResult {
  const LoginResult();
}

class LoginSucceeded extends LoginResult {
  const LoginSucceeded(this.user);
  final CurrentUser user;
}

class MfaRequired extends LoginResult {
  const MfaRequired(this.mfaToken);
  final String mfaToken;
}

/// Issue d'une tentative de reprise de session au lancement.
///
/// Trois issues, et non deux : « pas de session » et « serveur injoignable »
/// se ressemblent sur un écran de connexion, mais pas du tout dans la main
/// de l'utilisateur. La première demande un mot de passe ; la seconde
/// demande d'attendre le réseau — et effacer le jeton dans ce cas obligerait
/// à se reconnecter pour une coupure de métro, avec une position ouverte.
sealed class RestoreResult {
  const RestoreResult();
}

/// Aucun jeton, ou jeton définitivement refusé par le serveur.
class NoSession extends RestoreResult {
  const NoSession();
}

class SessionRestored extends RestoreResult {
  const SessionRestored(this.user);
  final CurrentUser user;
}

/// Le serveur n'a pas pu être joint. Le jeton est CONSERVÉ.
class RestoreUnavailable extends RestoreResult {
  const RestoreUnavailable(this.message);
  final String message;
}
