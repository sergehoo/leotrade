import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/core/format.dart';
import 'package:leotrade/features/auth/domain/models.dart';

void main() {
  group('Capabilities', () {
    test('se ferme quand le serveur ne les fournit pas', () {
      // Garantie de sécurité : en l'absence d'information, aucune capacité
      // n'est ouverte. Un défaut permissif, c'est un ordre réel passé par
      // quelqu'un qui n'y avait pas droit.
      final user = CurrentUser.fromJson({
        'id': 1,
        'email': 'a@b.test',
        'kyc_status': 'NOT_STARTED',
      });
      expect(user.capabilities.canTradeLive, isFalse);
      expect(user.capabilities.canWithdraw, isFalse);
      expect(user.capabilities.canTradePaper, isFalse);
    });

    test('reflète fidèlement la réponse du serveur', () {
      final user = CurrentUser.fromJson({
        'id': 1,
        'email': 'a@b.test',
        'kyc_status': 'APPROVED',
        'capabilities': {
          'can_trade_live': true,
          'can_trade_paper': true,
          'can_withdraw': true,
        },
      });
      expect(user.kycStatus, KycStatus.approved);
      expect(user.capabilities.canTradeLive, isTrue);
    });

    test('un statut KYC inconnu ne passe jamais pour approuvé', () {
      final user = CurrentUser.fromJson({
        'id': 1,
        'email': 'a@b.test',
        'kyc_status': 'STATUT_INATTENDU',
      });
      expect(user.kycStatus, KycStatus.unknown);
      expect(user.kycStatus, isNot(KycStatus.approved));
    });
  });

  group('formatMoney', () {
    test('rend un tiret plutôt qu\'un zéro trompeur', () {
      // Une valeur absente n'est pas un solde nul : les confondre ferait
      // croire à un compte vide.
      expect(formatMoney(null, 'USD'), '—');
      expect(formatMoney('', 'USD'), '—');
      expect(formatMoney('pas-un-nombre', 'USD'), '—');
    });

    test('formate un montant décimal transmis en chaîne', () {
      final result = formatMoney('1234.50', 'USD');
      expect(result, contains('1'));
      expect(result, contains('234'));
      expect(result, contains('50'));
    });
  });

  group('signOf', () {
    test('distingue gain, perte et absence de mouvement', () {
      expect(signOf('12.5'), MoveSign.gain);
      expect(signOf('-3'), MoveSign.loss);
      expect(signOf('0'), MoveSign.flat);
      expect(signOf(null), MoveSign.flat);
    });
  });
}
