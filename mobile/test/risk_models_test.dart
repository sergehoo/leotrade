import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/features/risk/domain/models.dart';

Map<String, dynamic> _limit({
  String consumed = '0.00',
  String limit = '3.00',
  Object? usage = '0.00',
}) =>
    {
      'key': 'daily_loss',
      'label': 'Perte journalière',
      'consumed_percent': consumed,
      'limit_percent': limit,
      'usage_percent': usage,
    };

void main() {
  group('RiskLimit', () {
    test('une limite absente n\'est pas présentée comme respectée', () {
      // Afficher « 0 % utilisé » sans limite laisserait croire à une
      // protection qui n'existe pas.
      final limit = RiskLimit.fromJson(_limit(usage: null));

      expect(limit.hasLimit, isFalse);
      expect(limit.isBreached, isFalse);
      expect(limit.isNearLimit, isFalse);
    });

    test('une limite franchie est signalée', () {
      final limit = RiskLimit.fromJson(
        _limit(consumed: '3.50', limit: '3.00', usage: '116.67'),
      );

      expect(limit.isBreached, isTrue);
      expect(limit.isNearLimit, isFalse);
    });

    test('une limite proche est signalée avant d\'être franchie', () {
      // À 90 % d'une limite de perte, l'utilisateur doit être averti même
      // si rien n'est encore bloqué.
      final limit = RiskLimit.fromJson(
        _limit(consumed: '2.70', limit: '3.00', usage: '90.00'),
      );

      expect(limit.isNearLimit, isTrue);
      expect(limit.isBreached, isFalse);
    });

    test('une limite largement respectée n\'alerte pas', () {
      final limit = RiskLimit.fromJson(
        _limit(consumed: '0.30', limit: '3.00', usage: '10.00'),
      );

      expect(limit.isNearLimit, isFalse);
      expect(limit.isBreached, isFalse);
    });

    test('les pourcentages restent en chaîne', () {
      final limit = RiskLimit.fromJson(_limit());

      expect(limit.consumedPercent, isA<String>());
      expect(limit.limitPercent, '3.00');
    });
  });

  group('RiskSummary', () {
    Map<String, dynamic> summaryJson({
      bool killSwitch = false,
      List<Map<String, dynamic>>? limits,
      Map<String, dynamic>? profile,
    }) =>
        {
          'portfolio_id': 1,
          'kill_switch_active': killSwitch,
          'kill_switch_reason': killSwitch ? 'Limite journalière atteinte.' : '',
          'kill_switch_reason_code': killSwitch ? 'DAILY_LOSS_LIMIT' : '',
          'limits': limits ?? [_limit()],
          'open_positions': 2,
          'max_open_positions': 5,
          if (profile != null) 'profile': profile,
        };

    test('un kill switch actif compte comme un franchissement', () {
      final summary = RiskSummary.fromJson(summaryJson(killSwitch: true));

      expect(summary.hasBreach, isTrue);
      expect(summary.killSwitchReasonCode, 'DAILY_LOSS_LIMIT');
    });

    test('une limite franchie suffit à signaler un franchissement', () {
      final summary = RiskSummary.fromJson(summaryJson(
        limits: [_limit(consumed: '4.00', limit: '3.00', usage: '133.00')],
      ));

      expect(summary.hasBreach, isTrue);
    });

    test('tout au vert ne signale rien', () {
      final summary = RiskSummary.fromJson(summaryJson());

      expect(summary.hasBreach, isFalse);
    });

    test('un profil absent ne fait pas échouer la lecture', () {
      final summary = RiskSummary.fromJson(summaryJson());

      expect(summary.profile, isNull);
      expect(summary.openPositions, 2);
    });
  });

  group('RiskProfileSummary', () {
    test('en l\'absence d\'information, la préservation est présumée ACTIVE', () {
      // Et les instruments risqués présumés INTERDITS. L'erreur inverse
      // ferait croire à une liberté qui n'est pas accordée, ou à une
      // protection qui n'existe pas.
      final profile = RiskProfileSummary.fromJson({'id': 1, 'name': 'X'});

      expect(profile.preservationMode, isTrue);
      expect(profile.allowSpeculative, isFalse);
      expect(profile.allowVolatile, isFalse);
      expect(profile.requireStopLoss, isTrue);
    });

    test('reflète fidèlement un opt-in explicite', () {
      final profile = RiskProfileSummary.fromJson({
        'id': 1,
        'name': 'Agressif',
        'preservation_mode': false,
        'allow_speculative_instruments': true,
      });

      expect(profile.preservationMode, isFalse);
      expect(profile.allowSpeculative, isTrue);
    });
  });
}
