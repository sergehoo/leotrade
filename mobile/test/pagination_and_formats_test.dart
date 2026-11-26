import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/core/format.dart';
import 'package:leotrade/core/network/page.dart';
import 'package:leotrade/features/portfolio/domain/models.dart';
import 'package:leotrade/features/wallet/domain/models.dart';

void main() {
  group('Page', () {
    Map<String, dynamic> body({Object? next, int count = 2}) => {
          'count': count,
          'next': next,
          'results': [
            {'id': 1},
            {'id': 2},
          ],
        };

    test('une page complète ne prétend pas être tronquée', () {
      final page = Page.fromJson(body(), (json) => json['id'] as int);

      expect(page.items, [1, 2]);
      expect(page.count, 2);
      expect(page.hasMore, isFalse);
    });

    test('une suite non chargée est signalée, pas tue', () {
      // `next` était jeté : au-delà de 25 éléments la liste était coupée
      // sans un mot, et l'élément absent passait pour inexistant.
      final page = Page.fromJson(
        body(next: 'http://exemple/?page=2', count: 180),
        (json) => json['id'] as int,
      );

      expect(page.hasMore, isTrue);
      expect(page.count, 180);
      expect(page.length, 2);
    });

    test('un corps sans results ne fait pas échouer la lecture', () {
      final page = Page.fromJson(const {}, (json) => json['id'] as int);

      expect(page.isEmpty, isTrue);
      expect(page.hasMore, isFalse);
    });
  });

  group('formatQuantity', () {
    test('les zéros de fin tombent, comme sur le web', () {
      // Le web montre 0,00045 ; le mobile affichait 0.00045000 pour la
      // même position.
      expect(formatQuantity('0.00045000'), '0,00045');
    });

    test('les milliers sont groupés', () {
      expect(formatQuantity('12500'), contains('12'));
      expect(formatQuantity('12500'), contains('500'));
    });

    test('une quantité illisible rend un tiret, jamais un zéro', () {
      expect(formatQuantity(null), '—');
      expect(formatQuantity(''), '—');
      expect(formatQuantity('indisponible'), '—');
    });
  });

  group('EquityCurve', () {
    test('sans verdict du serveur, on ne trace pas', () {
      // Défaut prudent : un graphique affirme plus fort qu'un nombre, et
      // relier des points épars donne à voir une trajectoire jamais
      // mesurée.
      final curve = EquityCurve.fromJson(const {'portfolio_id': 1});

      expect(curve.isPlottable, isFalse);
      expect(curve.points, isEmpty);
    });

    test('le motif du refus est lisible', () {
      final curve = EquityCurve.fromJson(const {
        'portfolio_id': 1,
        'point_count': 2,
        'minimum_points': 5,
        'is_plottable': false,
        'not_plottable_reasons': ['TOO_FEW_POINTS'],
      });

      expect(curve.tooFewPoints, isTrue);
      expect(curve.interrupted, isFalse);
      expect(curve.gapsTooWide, isFalse);
    });

    test('traçable et périmé sont deux verdicts distincts', () {
      // Une série régulière mais arrêtée il y a six mois se dessine très
      // bien, et décrit un état révolu.
      final curve = EquityCurve.fromJson(const {
        'portfolio_id': 1,
        'is_plottable': true,
        'is_stale': true,
        'points': [
          {'at': '2025-01-01T00:00:00Z', 'equity': '10000.00'},
          {'at': '2025-01-02T00:00:00Z', 'equity': '10250.00'},
        ],
        'point_count': 2,
      });

      expect(curve.isPlottable, isTrue);
      expect(curve.isStale, isTrue);
      expect(curve.points.first.equity, '10000.00');
    });

    test('les montants restent en chaîne', () {
      final curve = EquityCurve.fromJson(const {
        'portfolio_id': 1,
        'points': [
          {'at': '2025-01-01T00:00:00Z', 'equity': '10000.123456789'},
        ],
      });

      expect(curve.points.single.equity, isA<String>());
      expect(curve.points.single.equity, '10000.123456789');
    });
  });

  group('WithdrawalRequest', () {
    WithdrawalRequest parse(Map<String, dynamic> overrides) =>
        WithdrawalRequest.fromJson({
          'id': 3,
          'amount': '250.00',
          'fee_amount': '0.00',
          'currency': 'USD',
          'status': 'PENDING',
          'destination_masked': '•••• 4242',
          'failure_reason': '',
          'created_at': '2026-01-04T10:00:00Z',
          'reviewed_at': null,
          ...overrides,
        });

    test('une demande en attente garde les fonds verrouillés', () {
      final request = parse({});

      expect(request.isOpen, isTrue);
      expect(request.isRefused, isFalse);
      expect(request.statusLabel, 'En attente de revue');
    });

    test('un refus est reconnu comme tel', () {
      expect(parse({'status': 'REJECTED'}).isRefused, isTrue);
      expect(parse({'status': 'FAILED'}).isRefused, isTrue);
      expect(parse({'status': 'PAID'}).isRefused, isFalse);
      expect(parse({'status': 'PAID'}).isOpen, isFalse);
    });

    test('un statut inconnu est montré tel quel, jamais traduit à tort', () {
      final request = parse({'status': 'SOMETHING_NEW'});

      expect(request.status, WithdrawalStatus.unknown);
      expect(request.statusLabel, 'SOMETHING_NEW');
      expect(request.isOpen, isFalse,
          reason: 'un statut inconnu ne doit pas passer pour « en cours »');
    });

    test('le montant reste en chaîne', () {
      expect(parse({'amount': '250.55'}).amount, '250.55');
    });
  });
}
