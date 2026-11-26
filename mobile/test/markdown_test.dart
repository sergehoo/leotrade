import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:leotrade/shared/widgets/markdown.dart';
import 'package:leotrade/shared/widgets/states.dart';

/// Concatène le texte de tous les spans rendus.
String _rendered(WidgetTester tester) {
  final buffer = StringBuffer();

  void writeSpan(InlineSpan span) {
    span.visitChildren((child) {
      if (child is TextSpan && child.text != null) buffer.write(child.text);
      return true;
    });
  }

  for (final widget in tester.allWidgets) {
    if (widget is SelectableText) {
      if (widget.textSpan != null) {
        writeSpan(widget.textSpan!);
      } else if (widget.data != null) {
        buffer.write(widget.data);
      }
    } else if (widget is Text) {
      if (widget.textSpan != null) {
        writeSpan(widget.textSpan!);
      } else if (widget.data != null) {
        buffer.write(widget.data);
      }
    }
  }
  return buffer.toString();
}

Future<void> _pump(WidgetTester tester, String source) {
  return tester.pumpWidget(
    MaterialApp(
      home: Scaffold(
        body: SingleChildScrollView(child: Markdown(source)),
      ),
    ),
  );
}

/// Harnais avec un vrai routeur : un bouton doit NAVIGUER, pas
/// seulement s'afficher. Un bouton qui ne mène nulle part est
/// exactement ce que le mandat interdit.
///
/// La preuve retenue est l'écran d'arrivée, pas l'URL interne du
/// routeur : c'est ce que l'utilisateur voit.
Future<void> _pumpRouted(WidgetTester tester, String source) async {
  final router = GoRouter(
    initialLocation: '/',
    routes: [
      GoRoute(
        path: '/',
        builder: (_, __) => Scaffold(
          body: SingleChildScrollView(child: Markdown(source)),
        ),
      ),
      GoRoute(
        path: '/risque',
        builder: (_, __) => const Scaffold(body: Text('ÉCRAN RISQUE')),
      ),
      GoRoute(
        path: '/portefeuille',
        builder: (_, __) => const Scaffold(body: Text('ÉCRAN PORTEFEUILLE')),
      ),
    ],
  );
  await tester.pumpWidget(MaterialApp.router(routerConfig: router));
  await tester.pumpAndSettle();
}

void main() {
  group('Markdown', () {
    testWidgets('le gras perd ses astérisques', (tester) async {
      // Sans rendu, le mobile affichait littéralement « **BTCUSDT** ».
      await _pump(tester, 'Ton exposition sur **BTCUSDT** est élevée.');

      final text = _rendered(tester);
      expect(text, contains('BTCUSDT'));
      expect(text, isNot(contains('**')));
    });

    testWidgets('le code en ligne perd ses accents graves', (tester) async {
      await _pump(tester, 'Le champ `approved_quantity` est ambigu.');

      final text = _rendered(tester);
      expect(text, contains('approved_quantity'));
      expect(text, isNot(contains('`')));
    });

    testWidgets('une liste devient des puces', (tester) async {
      await _pump(tester, '- BTCUSDT\n- ETHUSDT\n- SOLUSDT');

      final text = _rendered(tester);
      expect(text, contains('BTCUSDT'));
      expect(text, contains('SOLUSDT'));
      expect(text, contains('•'));
      expect(text, isNot(contains('- BTC')));
    });

    testWidgets('un tableau devient un tableau', (tester) async {
      await _pump(
        tester,
        '| Symbole | Prix |\n|---|---|\n| BTCUSDT | 66385 |\n| ETHUSDT | 3200 |',
      );

      expect(find.byType(DataTable), findsOneWidget);
      final text = _rendered(tester);
      expect(text, contains('Symbole'));
      expect(text, contains('66385'));
      expect(text, isNot(contains('|')));
    });

    testWidgets('un bloc de code garde son contenu tel quel', (tester) async {
      await _pump(tester, '```dart\nfinal x = 1;\n```');

      final text = _rendered(tester);
      expect(text, contains('final x = 1;'));
      expect(text, isNot(contains('```')));
    });

    testWidgets(
      "l'adresse d'un lien est montrée, pas masquée",
      (tester) async {
        // Un modèle peut rapporter un lien venu d'un tiers. Un libellé
        // rassurant posé sur une adresse qui ne l'est pas est exactement
        // la forme que prend l'hameçonnage.
        await _pump(tester, 'Voir [la doc](https://exemple.test/doc).');

        final text = _rendered(tester);
        expect(text, contains('la doc'));
        expect(text, contains('https://exemple.test/doc'));
      },
    );

    testWidgets(
      "un schéma autre que http(s) reste du texte brut",
      (tester) async {
        await _pump(tester, 'Clique [ici](javascript:alert(1)).');

        final text = _rendered(tester);
        // Rendu tel quel : rien n'est présenté comme un lien utilisable.
        expect(text, contains('[ici](javascript:alert(1))'));
      },
    );

    testWidgets('du texte sans balisage traverse intact', (tester) async {
      const source = 'Ton portefeuille vaut 10 000,00 USD.';
      await _pump(tester, source);

      expect(_rendered(tester), contains(source));
    });

    testWidgets('une syntaxe inconnue est affichée, jamais avalée', (tester) async {
      // Mieux vaut un astérisque visible qu'un contenu disparu.
      await _pump(tester, 'Un calcul : 3 * 4 * 5 = 60.');

      expect(_rendered(tester), contains('60'));
      expect(_rendered(tester), contains('3'));
    });

    testWidgets('les six niveaux de titre sont rendus', (tester) async {
      await _pump(tester, '# Un\n## Deux\n### Trois\n#### Quatre\n##### Cinq\n###### Six');

      final text = _rendered(tester);
      for (final titre in ['Un', 'Deux', 'Trois', 'Quatre', 'Cinq', 'Six']) {
        expect(text, contains(titre));
      }
      expect(text, isNot(contains('#')));
    });

    testWidgets('le surlignage perd ses signes égal', (tester) async {
      // Le prompt l'enseignait déjà ; personne ne le rendait.
      await _pump(tester, 'Retiens surtout ==le drawdown à 22 %==.');

      final text = _rendered(tester);
      expect(text, contains('le drawdown à 22 %'));
      expect(text, isNot(contains('==')));
    });

    testWidgets('le barré perd ses tildes', (tester) async {
      await _pump(tester, 'Le seuil ~~de 0,60~~ est passé à 0,80.');

      final text = _rendered(tester);
      expect(text, contains('de 0,60'));
      expect(text, isNot(contains('~~')));
    });

    testWidgets('une citation perd son chevron', (tester) async {
      await _pump(tester, '> Je passerais mon tour.');

      final text = _rendered(tester);
      expect(text, contains('Je passerais mon tour.'));
      expect(text, isNot(contains('>')));
    });

    testWidgets('un séparateur devient une ligne', (tester) async {
      await _pump(tester, 'Avant\n\n---\n\nAprès');

      expect(find.byType(Divider), findsOneWidget);
      expect(_rendered(tester), isNot(contains('---')));
    });

    testWidgets(
      'un encadré emprunte le bandeau de l\'application',
      (tester) async {
        // Un avertissement de Leo porte ainsi la teinte qu'un
        // franchissement de limite porte ailleurs dans l'interface.
        await _pump(
          tester,
          '> [!WARNING] Drawdown à 22 %\n> La limite est à 25 %.',
        );

        final banner = tester.widget<NoticeBanner>(find.byType(NoticeBanner));
        expect(banner.tone, NoticeTone.warning);

        final text = _rendered(tester);
        expect(text, contains('Drawdown à 22 %'));
        expect(text, contains('La limite est à 25 %.'));
        expect(text, isNot(contains('[!WARNING]')));
      },
    );

    testWidgets('les cinq types d\'encadré ont chacun leur teinte', (tester) async {
      const attendu = {
        'NOTE': NoticeTone.info,
        'TIP': NoticeTone.success,
        'IMPORTANT': NoticeTone.info,
        'WARNING': NoticeTone.warning,
        'CAUTION': NoticeTone.danger,
      };

      for (final entry in attendu.entries) {
        await _pump(tester, '> [!${entry.key}] Titre\n> Corps.');
        final banner = tester.widget<NoticeBanner>(find.byType(NoticeBanner));
        expect(banner.tone, entry.value, reason: entry.key);
      }
    });

    testWidgets('une case à cocher est rendue, en lecture seule', (tester) async {
      await _pump(tester, '- [x] Broker connecté\n- [ ] KYC validé');

      expect(find.byIcon(Icons.check_box_outlined), findsOneWidget);
      expect(find.byIcon(Icons.check_box_outline_blank), findsOneWidget);

      final text = _rendered(tester);
      expect(text, contains('Broker connecté'));
      expect(text, isNot(contains('[x]')));
      expect(text, isNot(contains('[ ]')));
    });

    testWidgets('une liste imbriquée garde ses deux niveaux', (tester) async {
      await _pump(tester, '- Risque\n  - Drawdown\n  - Exposition\n- Marché');

      final text = _rendered(tester);
      expect(text, contains('Risque'));
      expect(text, contains('Drawdown'));
      expect(text, contains('Exposition'));
      expect(text, contains('Marché'));
    });

    testWidgets('une icône connue devient une icône', (tester) async {
      await _pump(tester, 'Position gagnante :gain: sur BTCUSDT.');

      expect(find.byIcon(Icons.trending_up), findsOneWidget);
      expect(_rendered(tester), isNot(contains(':gain:')));
    });

    testWidgets('une icône inconnue reste du texte', (tester) async {
      // Liste fermée : rien n'est inventé, et rien ne disparaît.
      await _pump(tester, 'Un truc :licorne: ici.');

      expect(_rendered(tester), contains(':licorne:'));
    });

    testWidgets('un commentaire ne parvient jamais à l\'écran', (tester) async {
      await _pump(tester, 'Visible <!-- invisible --> aussi.');

      final text = _rendered(tester);
      expect(text, contains('Visible'));
      expect(text, contains('aussi.'));
      expect(text, isNot(contains('invisible')));
    });

    testWidgets('une image distante n\'est pas chargée', (tester) async {
      // Une image distante dans une réponse de modèle est un pixel
      // traceur : son chargement révèle l'IP du lecteur et l'instant de
      // la lecture.
      await _pump(tester, '![Graphique](https://ailleurs.test/pixel.png)');

      expect(find.byType(Image), findsNothing);
      final text = _rendered(tester);
      expect(text, contains('Graphique'));
      expect(text, contains('https://ailleurs.test/pixel.png'));
    });
  });

  group('Liens et boutons', () {
    testWidgets('un bouton vers une route connue NAVIGUE', (tester) async {
      await _pumpRouted(
        tester,
        'Jette un œil : [[Ouvrir le Risk Control|/risque]]',
      );

      expect(find.text('Ouvrir le Risk Control'), findsOneWidget);
      expect(find.text('ÉCRAN RISQUE'), findsNothing);

      await tester.tap(find.text('Ouvrir le Risk Control'));
      await tester.pumpAndSettle();

      expect(find.text('ÉCRAN RISQUE'), findsOneWidget);
    });

    testWidgets(
      'un bouton vers une route inventée reste du texte',
      (tester) async {
        // La règle anti-hallucination appliquée à l'AFFICHAGE : si le
        // modèle invente une page, l'interface ne fabrique pas un
        // bouton mort pour autant.
        await _pumpRouted(tester, '[[Voir les idées|/trading/ideas/]]');

        expect(find.byType(FilledButton), findsNothing);
        expect(_rendered(tester), contains('[[Voir les idées|/trading/ideas/]]'));
      },
    );

    testWidgets('un lien interne connu navigue aussi', (tester) async {
      await _pumpRouted(tester, 'Regarde [tes positions](/portefeuille).');

      expect(find.text('ÉCRAN PORTEFEUILLE'), findsNothing);

      await tester.tap(find.text('tes positions'));
      await tester.pumpAndSettle();

      expect(find.text('ÉCRAN PORTEFEUILLE'), findsOneWidget);
    });

    testWidgets('un lien interne inconnu reste du texte', (tester) async {
      await _pumpRouted(tester, 'Va sur [le wallet](/wallet/).');

      expect(_rendered(tester), contains('[le wallet](/wallet/)'));
    });

    testWidgets(
      'un bouton depuis Leo rejoint un ONGLET sans faire tomber le routeur',
      (tester) async {
        // La forme réelle de l'application : Leo est une route de
        // premier niveau posée sur le navigateur racine, et ses
        // destinations sont des onglets d'une `StatefulShellRoute`.
        //
        // POUSSER une route de branche reconstruit le `Navigator` de
        // cette branche alors que sa `GlobalKey` est déjà prise par
        // celui qui tourne en dessous : Flutter s'arrête sur
        // `!keyReservation.contains(key)` et l'écran devient rouge. Le
        // harnais à routes plates ne pouvait pas le voir — seul le
        // téléphone l'a montré.
        final rootKey = GlobalKey<NavigatorState>();
        final router = GoRouter(
          navigatorKey: rootKey,
          // On démarre DANS la coquille, comme l'application : c'est
          // d'avoir une coquille déjà montée qui fait entrer en
          // collision la seconde, et c'est ce que le harnais précédent
          // ne reproduisait pas.
          initialLocation: '/',
          routes: [
            GoRoute(
              path: '/leo',
              parentNavigatorKey: rootKey,
              builder: (_, __) => Scaffold(
                body: SingleChildScrollView(
                  child: Markdown('[[Ouvrir le Risk Control|/risque]]'),
                ),
              ),
            ),
            StatefulShellRoute.indexedStack(
              builder: (_, __, shell) => Scaffold(body: shell),
              branches: [
                StatefulShellBranch(routes: [
                  GoRoute(
                    path: '/',
                    builder: (_, __) => const Scaffold(body: Text('ACCUEIL')),
                  ),
                ]),
                StatefulShellBranch(routes: [
                  GoRoute(
                    path: '/risque',
                    builder: (_, __) =>
                        const Scaffold(body: Text('ÉCRAN RISQUE')),
                  ),
                ]),
              ],
            ),
          ],
        );

        await tester.pumpWidget(MaterialApp.router(routerConfig: router));
        await tester.pumpAndSettle();
        expect(find.text('ACCUEIL'), findsOneWidget);

        // Leo s'ouvre PAR-DESSUS la coquille, comme depuis le bouton
        // flottant.
        router.push('/leo');
        await tester.pumpAndSettle();

        await tester.tap(find.text('Ouvrir le Risk Control'));
        await tester.pumpAndSettle();

        expect(tester.takeException(), isNull);
        expect(find.text('ÉCRAN RISQUE'), findsOneWidget);
      },
    );
  });
}
