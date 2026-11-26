import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:leotrade/shared/widgets/markdown.dart';

/// Concatène le texte de tous les spans rendus.
String _rendered(WidgetTester tester) {
  final buffer = StringBuffer();
  for (final widget in tester.allWidgets) {
    if (widget is SelectableText && widget.textSpan != null) {
      widget.textSpan!.visitChildren((span) {
        if (span is TextSpan && span.text != null) buffer.write(span.text);
        return true;
      });
    } else if (widget is SelectableText && widget.data != null) {
      buffer.write(widget.data);
    } else if (widget is Text && widget.data != null) {
      buffer.write(widget.data);
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
  });
}
