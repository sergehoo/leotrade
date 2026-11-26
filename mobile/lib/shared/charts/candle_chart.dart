import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

/// Une bougie prête à dessiner. Les montants sont déjà convertis : la
/// conversion a lieu une fois, à la frontière, jamais dans le painter.
class CandlePoint {
  const CandlePoint({
    required this.open,
    required this.high,
    required this.low,
    required this.close,
  });

  /// Construit depuis les chaînes de l'API. Renvoie `null` si l'une des
  /// valeurs est illisible : une bougie incomplète dessinée à zéro
  /// écraserait toute l'échelle.
  static CandlePoint? tryParse({
    String? open,
    String? high,
    String? low,
    String? close,
  }) {
    final o = double.tryParse(open ?? '');
    final h = double.tryParse(high ?? '');
    final l = double.tryParse(low ?? '');
    final c = double.tryParse(close ?? '');
    if (o == null || h == null || l == null || c == null) return null;
    if (!o.isFinite || !h.isFinite || !l.isFinite || !c.isFinite) return null;
    return CandlePoint(open: o, high: h, low: l, close: c);
  }

  final double open;
  final double high;
  final double low;
  final double close;

  bool get isUp => close >= open;
}

/// Graphique en chandeliers, sans dépendance externe.
///
/// L'échelle verticale couvre l'amplitude réelle de la série, avec une
/// marge symétrique : coller la série aux bords donnerait l'illusion que
/// le prix touche un plafond ou un plancher.
///
/// Le vert et le rouge gardent leur sens financier — hausse et baisse de
/// la bougie — et ne sont jamais décoratifs.
class CandleChart extends StatelessWidget {
  const CandleChart({
    super.key,
    required this.candles,
    this.height = 220,
    this.semanticsSuffix,
  });

  final List<CandlePoint> candles;
  final double height;

  /// Complément parlé : fraîcheur, unité de temps, source.
  final String? semanticsSuffix;

  @override
  Widget build(BuildContext context) {
    if (candles.isEmpty) return SizedBox(height: height);

    // Un `CustomPaint` ne restitue RIEN à un lecteur d'écran : sans
    // alternative, le graphique n'existe pas pour qui ne le voit pas. Le
    // résumé est porté par le widget plutôt que par chaque appelant,
    // pour qu'aucun usage ne puisse l'oublier.
    final first = candles.first.close;
    final last = candles.last.close;
    final direction = last > first
        ? 'en hausse'
        : last < first
            ? 'en baisse'
            : 'stable';

    return Semantics(
      label: 'Graphique en chandeliers, ${candles.length} bougies, '
          '$direction. Première clôture $first, dernière $last.'
          '${semanticsSuffix != null ? ' $semanticsSuffix' : ''}',
      image: true,
      excludeSemantics: true,
      child: SizedBox(
        height: height,
        width: double.infinity,
        child: CustomPaint(painter: _CandlePainter(candles)),
      ),
    );
  }
}

class _CandlePainter extends CustomPainter {
  _CandlePainter(this.candles);

  final List<CandlePoint> candles;

  @override
  void paint(Canvas canvas, Size size) {
    if (candles.isEmpty || size.width <= 0 || size.height <= 0) return;

    var minLow = candles.first.low;
    var maxHigh = candles.first.high;
    for (final candle in candles) {
      if (candle.low < minLow) minLow = candle.low;
      if (candle.high > maxHigh) maxHigh = candle.high;
    }

    var span = maxHigh - minLow;
    if (span <= 0) {
      // Série plate : on ouvre une fenêtre artificielle plutôt que de
      // diviser par zéro, et la ligne se dessine au centre.
      span = maxHigh.abs() > 0 ? maxHigh.abs() * 0.02 : 1;
      minLow -= span / 2;
      maxHigh += span / 2;
      span = maxHigh - minLow;
    }

    // Marge symétrique haut/bas, alignée sur `scaleMargins` du web
    // (CandleChart.tsx) : une marge différente cadre une amplitude
    // différente pour la même série.
    const margin = 0.12;
    final usable = size.height * (1 - 2 * margin);
    final top = size.height * margin;

    double y(double value) =>
        top + usable - ((value - minLow) / span) * usable;

    final slot = size.width / candles.length;
    final bodyWidth = (slot * 0.62).clamp(1.0, 14.0);

    final wick = Paint()
      ..strokeWidth = 1
      ..style = PaintingStyle.stroke;
    final body = Paint()..style = PaintingStyle.fill;

    for (var index = 0; index < candles.length; index++) {
      final candle = candles[index];
      final centerX = slot * index + slot / 2;
      final color = candle.isUp ? AppColors.gain : AppColors.loss;

      wick.color = color.withValues(alpha: 0.9);
      canvas.drawLine(
        Offset(centerX, y(candle.high)),
        Offset(centerX, y(candle.low)),
        wick,
      );

      body.color = color;
      final openY = y(candle.open);
      final closeY = y(candle.close);
      final rectTop = openY < closeY ? openY : closeY;
      // Hauteur minimale d'un pixel : une bougie doji doit rester visible.
      final rectHeight = (closeY - openY).abs().clamp(1.0, double.infinity);

      canvas.drawRect(
        Rect.fromLTWH(centerX - bodyWidth / 2, rectTop, bodyWidth, rectHeight),
        body,
      );
    }
  }

  @override
  bool shouldRepaint(covariant _CandlePainter oldDelegate) =>
      oldDelegate.candles != candles;
}

/// Courbe simple, pour une série de valeurs.
///
/// L'échelle inclut toujours zéro quand la série reste positive : un axe
/// calé sur le minimum observé transforme une variation de 0,5 % en pente
/// spectaculaire. C'est la manière la plus commune de mentir avec un
/// graphique par ailleurs exact.
class Sparkline extends StatelessWidget {
  const Sparkline({
    super.key,
    required this.values,
    this.height = 120,
    this.color = AppColors.primary,
    this.semanticsLabel,
  });

  final List<double> values;
  final double height;
  final Color color;

  /// Résumé parlé. Les montants formatés sont connus de l'appelant, pas
  /// d'ici : la courbe ne reçoit que des nombres.
  final String? semanticsLabel;

  @override
  Widget build(BuildContext context) {
    if (values.length < 2) return SizedBox(height: height);

    return Semantics(
      label: semanticsLabel ??
          'Courbe, ${values.length} mesures, '
              '${values.last > values.first ? 'en hausse' : values.last < values.first ? 'en baisse' : 'stable'}.',
      image: true,
      excludeSemantics: true,
      child: SizedBox(
        height: height,
        width: double.infinity,
        child: CustomPaint(painter: _SparklinePainter(values, color)),
      ),
    );
  }
}

class _SparklinePainter extends CustomPainter {
  _SparklinePainter(this.values, this.color);

  final List<double> values;
  final Color color;

  @override
  void paint(Canvas canvas, Size size) {
    if (values.length < 2 || size.width <= 0 || size.height <= 0) return;

    var minValue = values.reduce((a, b) => a < b ? a : b);
    var maxValue = values.reduce((a, b) => a > b ? a : b);

    // Ancrage bidirectionnel : zéro appartient toujours à la plage, que
    // la série soit positive, négative ou à cheval. N'ancrer que vers le
    // bas laissait une série entièrement négative se recaler sur son
    // amplitude observée — exactement l'amplification qu'on interdit.
    if (minValue > 0) minValue = 0;
    if (maxValue < 0) maxValue = 0;

    var span = maxValue - minValue;
    if (span <= 0) span = maxValue.abs() > 0 ? maxValue.abs() : 1;

    const margin = 0.12;
    final usable = size.height * (1 - 2 * margin);
    final top = size.height * margin;
    final step = size.width / (values.length - 1);

    final path = Path();
    for (var index = 0; index < values.length; index++) {
      final x = step * index;
      final y = top + usable - ((values[index] - minValue) / span) * usable;
      if (index == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }

    final fill = Path.from(path)
      ..lineTo(size.width, size.height)
      ..lineTo(0, size.height)
      ..close();

    canvas.drawPath(
      fill,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [color.withValues(alpha: 0.22), color.withValues(alpha: 0.01)],
        ).createShader(Rect.fromLTWH(0, 0, size.width, size.height)),
    );

    canvas.drawPath(
      path,
      Paint()
        ..color = color
        ..strokeWidth = 2
        ..style = PaintingStyle.stroke
        ..strokeJoin = StrokeJoin.round,
    );
  }

  @override
  bool shouldRepaint(covariant _SparklinePainter oldDelegate) =>
      oldDelegate.values != values || oldDelegate.color != color;
}
