import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme/app_theme.dart';
import 'markdown_grammar.dart';
import 'states.dart';

/// Rendu de la grammaire de Leo, en widgets.
///
/// Les liens et les boutons empruntent `context.go`, jamais
/// `context.push`. Les destinations de Leo sont des onglets de la
/// coquille (`StatefulShellRoute`) : les POUSSER reconstruit le
/// `Navigator` de la branche alors que sa `GlobalKey` est déjà prise par
/// celui qui tourne en dessous, et Flutter s'arrête sur
/// `!keyReservation.contains(key)`. `go` bascule sur l'onglet, ce qui
/// est de toute façon le geste attendu : on quitte la conversation pour
/// aller voir l'écran dont Leo parle.
///
/// Contrat partagé, décrit une fois pour toutes dans
/// `docs/LEO_MARKDOWN.md` et rendu à l'identique par
/// `web/src/components/leo/Markdown.tsx`.
///
/// Construit des widgets, jamais du HTML interprété : le texte vient
/// d'un modèle de langage, qui peut restituer n'importe quoi — y compris
/// du contenu tiers rapporté par un outil. Assembler des widgets rend
/// l'injection structurellement impossible plutôt que filtrée.
///
/// Ce qui n'est pas reconnu est rendu tel quel, en texte : mieux vaut un
/// astérisque visible qu'un contenu avalé.
class Markdown extends StatelessWidget {
  const Markdown(this.content, {super.key, this.baseStyle, this.selectable = false});

  final String content;
  final TextStyle? baseStyle;

  /// Faux par défaut — y compris pour les rendus imbriqués.
  ///
  /// La zone de sélection appartient à l'ÉCRAN, pas au bloc : une par
  /// message, c'était autant de `SelectableRegion` montées et démontées
  /// au défilement, chacune réservant sa place dans l'overlay du
  /// navigateur. Une seule, posée autour de la conversation entière,
  /// permet en prime de sélectionner une phrase qui enjambe deux
  /// messages.
  final bool selectable;

  @override
  Widget build(BuildContext context) {
    final style = baseStyle ??
        const TextStyle(fontSize: 14, height: 1.45, color: AppColors.foreground);
    final blocks = parseLeoBlocks(content);

    final body = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < blocks.length; i++) ...[
          if (i > 0) const SizedBox(height: 8),
          blocks[i].build(context, style),
        ],
      ],
    );

    return selectable ? SelectionArea(child: body) : body;
  }
}

// ── Icônes ────────────────────────────────────────────────────────────────

const Map<String, IconData> _icons = {
  'gain': Icons.trending_up,
  'perte': Icons.trending_down,
  'neutre': Icons.remove,
  'alerte': Icons.warning_amber_rounded,
  'danger': Icons.error_outline,
  'info': Icons.info_outline,
  'idee': Icons.lightbulb_outline,
  'risque': Icons.shield_outlined,
  'verrou': Icons.lock_outline,
  'horloge': Icons.schedule,
  'cible': Icons.my_location,
  'graphique': Icons.show_chart,
  'portefeuille': Icons.work_outline,
  'marche': Icons.candlestick_chart_outlined,
  'broker': Icons.power_outlined,
  'ia': Icons.smart_toy_outlined,
  'valide': Icons.check,
  'refus': Icons.close,
};

/// Le vert et le rouge gardent leur sens financier, jamais décoratif.
const Map<String, Color> _iconTone = {
  'gain': AppColors.gain,
  'valide': AppColors.gain,
  'perte': AppColors.loss,
  'refus': AppColors.loss,
  'danger': AppColors.loss,
  'alerte': AppColors.warning,
  'risque': AppColors.warning,
  'info': AppColors.info,
};

NoticeTone _calloutTone(CalloutKind kind) => switch (kind) {
      CalloutKind.note => NoticeTone.info,
      CalloutKind.tip => NoticeTone.success,
      CalloutKind.important => NoticeTone.info,
      CalloutKind.warning => NoticeTone.warning,
      CalloutKind.caution => NoticeTone.danger,
    };

String _calloutTitle(CalloutKind kind) => switch (kind) {
      CalloutKind.note => 'À noter',
      CalloutKind.tip => 'Conseil',
      CalloutKind.important => 'Important',
      CalloutKind.warning => 'Attention',
      CalloutKind.caution => 'Danger',
    };

// ── Blocs ────────────────────────────────────────────────────────────────

abstract class LeoBlock {
  const LeoBlock();
  Widget build(BuildContext context, TextStyle base);
}

class _Paragraph extends LeoBlock {
  const _Paragraph(this.text);
  final String text;

  @override
  Widget build(BuildContext context, TextStyle base) =>
      Text.rich(TextSpan(children: inlineSpans(context, text, base)));
}

class _Heading extends LeoBlock {
  const _Heading(this.level, this.text);
  final int level;
  final String text;

  @override
  Widget build(BuildContext context, TextStyle base) {
    final size = switch (level) {
      1 => 18.0,
      2 => 16.0,
      3 => 15.0,
      _ => 14.0,
    };
    final style = base.copyWith(
      fontSize: size,
      fontWeight: FontWeight.w600,
      color: level >= 4 ? AppColors.muted : base.color,
    );
    return Text.rich(
      TextSpan(children: inlineSpans(context, text, style)),
    );
  }
}

class _Rule extends LeoBlock {
  const _Rule();

  @override
  Widget build(BuildContext context, TextStyle base) =>
      const Divider(color: AppColors.border, height: 12);
}

class _Quote extends LeoBlock {
  const _Quote(this.body);
  final String body;

  @override
  Widget build(BuildContext context, TextStyle base) {
    return Container(
      padding: const EdgeInsets.only(left: 12),
      decoration: const BoxDecoration(
        border: Border(
          left: BorderSide(color: AppColors.primary, width: 2),
        ),
      ),
      child: Markdown(
        body,
        baseStyle: base.copyWith(color: AppColors.muted),
      ),
    );
  }
}

class _Callout extends LeoBlock {
  const _Callout(this.kind, this.body);
  final CalloutKind kind;
  final String body;

  @override
  Widget build(BuildContext context, TextStyle base) {
    // Le bandeau de l'application, pas un encadré maison : un
    // avertissement de Leo porte ainsi exactement la teinte qu'un
    // franchissement de limite porte ailleurs dans l'interface.
    return NoticeBanner(
      tone: _calloutTone(kind),
      title: _calloutTitle(kind),
      child: Markdown(
        body,
        baseStyle: base.copyWith(color: AppColors.muted),
      ),
    );
  }
}

class _ListBlock extends LeoBlock {
  const _ListBlock(this.items, {required this.ordered});
  final List<_ListItem> items;
  final bool ordered;

  @override
  Widget build(BuildContext context, TextStyle base) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < items.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 4),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 24,
                  child: items[i].task != null
                      ? Icon(
                          items[i].task!
                              ? Icons.check_box_outlined
                              : Icons.check_box_outline_blank,
                          size: 16,
                          color: AppColors.muted,
                        )
                      : Text(
                          ordered ? '${i + 1}.' : '•',
                          style: base.copyWith(color: AppColors.muted),
                        ),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      Text.rich(
                        TextSpan(
                          children: inlineSpans(context, items[i].content, base),
                        ),
                      ),
                      if (items[i].children.trim().isNotEmpty)
                        Padding(
                          padding: const EdgeInsets.only(top: 4),
                          child: Markdown(items[i].children, baseStyle: base),
                        ),
                    ],
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _ListItem {
  _ListItem(this.content, {this.task});
  final String content;

  /// Null pour une puce ordinaire ; vrai/faux pour une case à cocher.
  final bool? task;
  String children = '';
}

class _CodeBlock extends LeoBlock {
  const _CodeBlock(this.language, this.body);
  final String language;
  final String body;

  @override
  Widget build(BuildContext context, TextStyle base) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: AppColors.surfaceHigh,
        border: Border.all(color: AppColors.border),
        borderRadius: BorderRadius.circular(8),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          if (language.isNotEmpty)
            Padding(
              padding: const EdgeInsets.only(bottom: 5),
              child: Text(
                language.toUpperCase(),
                style: const TextStyle(
                  fontSize: 10,
                  letterSpacing: 0.6,
                  color: AppColors.muted,
                ),
              ),
            ),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Text(
              body,
              style: base.copyWith(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

class _TableBlock extends LeoBlock {
  const _TableBlock(this.header, this.rows);
  final List<String> header;
  final List<List<String>> rows;

  @override
  Widget build(BuildContext context, TextStyle base) {
    // Défilement horizontal : un tableau de marché déborde toujours d'un
    // écran de téléphone, et rogner une colonne de chiffres en
    // masquerait le sens.
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 34,
        dataRowMinHeight: 30,
        dataRowMaxHeight: 48,
        horizontalMargin: 8,
        columnSpacing: 18,
        columns: [
          for (final cell in header)
            DataColumn(
              label: Text(
                cell,
                style: base.copyWith(fontSize: 12, fontWeight: FontWeight.w600),
              ),
            ),
        ],
        rows: [
          for (final row in rows)
            DataRow(
              cells: [
                for (var i = 0; i < header.length; i++)
                  DataCell(
                    Text.rich(
                      TextSpan(
                        children: inlineSpans(
                          context,
                          i < row.length ? row[i] : '',
                          base.copyWith(fontSize: 12),
                        ),
                      ),
                    ),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

class _ImageBlock extends LeoBlock {
  const _ImageBlock(this.alt, this.src);
  final String alt;
  final String src;

  @override
  Widget build(BuildContext context, TextStyle base) {
    if (!isSameOriginImage(src)) {
      // Une image distante est un pixel traceur : son chargement révèle
      // l'IP du lecteur et l'instant de la lecture, et l'URL peut
      // encoder ce qu'on veut exfiltrer. On montre, on ne charge pas.
      return Text(
        '${alt.isEmpty ? 'Image' : alt} ($src)',
        style: base.copyWith(fontSize: 12, color: AppColors.muted),
      );
    }
    return ClipRRect(
      borderRadius: BorderRadius.circular(8),
      child: Image.network(
        resolveImageUrl(src),
        fit: BoxFit.contain,
        errorBuilder: (_, __, ___) => Text(
          alt.isEmpty ? 'Image indisponible.' : '$alt — image indisponible.',
          style: base.copyWith(fontSize: 12, color: AppColors.muted),
        ),
      ),
    );
  }
}

// ── Analyse ──────────────────────────────────────────────────────────────

final _heading = RegExp(r'^(#{1,6})\s+(.*)$');
final _bullet = RegExp(r'^(\s*)([-*+]|\d+[.)])\s+(.*)$');
final _ordered = RegExp(r'^\s*\d+[.)]\s+');
final _task = RegExp(r'^\[([ xX])\]\s+(.*)$');
final _rule = RegExp(r'^\s*(-{3,}|\*{3,}|_{3,})\s*$');
final _callout = RegExp(r'^>\s*\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(.*)$');
final _quote = RegExp(r'^>\s?(.*)$');
final _imageLine = RegExp(r'^!\[([^\]]*)\]\(([^)\s]+)\)$');
final _htmlComment = RegExp(r'<!--[\s\S]*?-->');
final _separator = RegExp(r'^\s*\|?[\s:|-]*$');
final _continuation = RegExp(r'^\s{2,}\S');

/// Découpe une réponse de Leo en blocs. Exposé pour les tests.
List<LeoBlock> parseLeoBlocks(String source) {
  // Un commentaire n'a rien à faire à l'écran, et un commentaire à
  // moitié rendu est pire qu'un commentaire absent.
  final lines = source
      .replaceAll(_htmlComment, '')
      .replaceAll('\r\n', '\n')
      .split('\n');
  final blocks = <LeoBlock>[];
  var i = 0;

  while (i < lines.length) {
    final line = lines[i];

    if (line.trim().isEmpty) {
      i++;
      continue;
    }

    // ── Bloc de code ──
    if (line.trimLeft().startsWith('```')) {
      final language = line.trim().substring(3).trim();
      final body = <String>[];
      i++;
      while (i < lines.length && !lines[i].trimLeft().startsWith('```')) {
        body.add(lines[i]);
        i++;
      }
      i++;
      blocks.add(_CodeBlock(language, body.join('\n')));
      continue;
    }

    // ── Encadré ──
    final callout = _callout.firstMatch(line);
    if (callout != null) {
      final kind = calloutKindFrom(callout.group(1)!)!;
      final body = <String>[];
      final head = callout.group(2)!.trim();
      if (head.isNotEmpty) body.add(head);
      i++;
      while (i < lines.length &&
          _quote.hasMatch(lines[i]) &&
          !_callout.hasMatch(lines[i])) {
        body.add(_quote.firstMatch(lines[i])!.group(1)!);
        i++;
      }
      blocks.add(_Callout(kind, body.join('\n')));
      continue;
    }

    // ── Citation ──
    if (_quote.hasMatch(line)) {
      final body = <String>[];
      while (i < lines.length &&
          _quote.hasMatch(lines[i]) &&
          !_callout.hasMatch(lines[i])) {
        body.add(_quote.firstMatch(lines[i])!.group(1)!);
        i++;
      }
      blocks.add(_Quote(body.join('\n')));
      continue;
    }

    // ── Séparateur ──
    if (_rule.hasMatch(line)) {
      blocks.add(const _Rule());
      i++;
      continue;
    }

    // ── Tableau ──
    if (line.contains('|') &&
        i + 1 < lines.length &&
        _isSeparator(lines[i + 1])) {
      final header = _cells(line);
      i += 2;
      final rows = <List<String>>[];
      while (i < lines.length &&
          lines[i].contains('|') &&
          lines[i].trim().isNotEmpty) {
        rows.add(_cells(lines[i]));
        i++;
      }
      blocks.add(_TableBlock(header, rows));
      continue;
    }

    // ── Titre ──
    final heading = _heading.firstMatch(line);
    if (heading != null) {
      blocks.add(_Heading(heading.group(1)!.length, heading.group(2)!));
      i++;
      continue;
    }

    // ── Image seule sur sa ligne ──
    final image = _imageLine.firstMatch(line.trim());
    if (image != null) {
      blocks.add(_ImageBlock(image.group(1)!, image.group(2)!));
      i++;
      continue;
    }

    // ── Liste ──
    if (_bullet.hasMatch(line)) {
      final start = i;
      while (i < lines.length &&
          (_bullet.hasMatch(lines[i]) || _isContinuation(lines[i]))) {
        i++;
      }
      blocks.add(_buildList(lines.sublist(start, i)));
      continue;
    }

    // ── Paragraphe ──
    final paragraph = <String>[];
    while (i < lines.length && _isParagraphLine(lines[i])) {
      paragraph.add(lines[i]);
      i++;
    }
    if (paragraph.isNotEmpty) {
      blocks.add(_Paragraph(paragraph.join('\n')));
    } else {
      // Filet : une ligne qu'aucune règle n'a consommée ne doit pas
      // faire boucler l'analyse indéfiniment.
      blocks.add(_Paragraph(lines[i]));
      i++;
    }
  }

  return blocks;
}

bool _isParagraphLine(String line) =>
    line.trim().isNotEmpty &&
    !line.trimLeft().startsWith('```') &&
    !_heading.hasMatch(line) &&
    !_bullet.hasMatch(line) &&
    !_quote.hasMatch(line) &&
    !_rule.hasMatch(line) &&
    !_imageLine.hasMatch(line.trim());

bool _isContinuation(String line) =>
    line.trim().isNotEmpty &&
    _continuation.hasMatch(line) &&
    !_bullet.hasMatch(line);

_ListBlock _buildList(List<String> lines) {
  final first = _bullet.firstMatch(lines.first)!;
  final baseIndent = first.group(1)!.length;
  final ordered = _ordered.hasMatch(lines.first);

  final items = <_ListItem>[];
  for (final line in lines) {
    final match = _bullet.firstMatch(line);
    if (match != null && match.group(1)!.length <= baseIndent) {
      final raw = match.group(3)!;
      final task = _task.firstMatch(raw);
      items.add(
        _ListItem(
          task != null ? task.group(2)! : raw,
          task: task != null ? task.group(1)!.toLowerCase() == 'x' : null,
        ),
      );
    } else if (items.isNotEmpty) {
      // Plus indenté : appartient à l'élément courant.
      final cut = baseIndent + 2;
      items.last.children +=
          '${line.length > cut ? line.substring(cut) : line.trimLeft()}\n';
    }
  }

  return _ListBlock(items, ordered: ordered);
}

bool _isSeparator(String line) =>
    _separator.hasMatch(line) && line.contains('-') && line.contains('|');

List<String> _cells(String line) {
  var trimmed = line.trim();
  if (trimmed.startsWith('|')) trimmed = trimmed.substring(1);
  if (trimmed.endsWith('|')) trimmed = trimmed.substring(0, trimmed.length - 1);
  return trimmed.split('|').map((cell) => cell.trim()).toList(growable: false);
}

// ── Enrichissements en ligne ─────────────────────────────────────────────

final _inline = RegExp(
  r'\[\[[^\]|]+\|[^\]]+\]\]' // bouton
  r'|!\[[^\]]*\]\([^)\s]+\)' // image en ligne
  r'|\[[^\]]+\]\([^)\s]+\)' // lien
  r'|\*\*[^*]+\*\*' // gras
  r'|__[^_]+__' // gras
  r'|~~[^~]+~~' // barré
  r'|==[^=]+==' // surlignage
  r'|`[^`\n]+`' // code
  r'|\*[^*\n]+\*' // italique
  r'|_[^_\n]+_' // italique
  r'|:[a-z]+:', // icône
);

final _button = RegExp(r'^\[\[([^\]|]+)\|([^\]]+)\]\]$');
final _link = RegExp(r'^\[([^\]]+)\]\(([^)\s]+)\)$');
final _inlineImage = RegExp(r'^!\[([^\]]*)\]\(([^)\s]+)\)$');
final _iconToken = RegExp(r'^:[a-z]+:$');

/// Découpe un fragment en spans. Ce qui n'est pas reconnu reste du texte.
List<InlineSpan> inlineSpans(
  BuildContext context,
  String text,
  TextStyle base,
) {
  final spans = <InlineSpan>[];
  var last = 0;

  for (final match in _inline.allMatches(text)) {
    if (match.start > last) {
      spans.add(TextSpan(text: text.substring(last, match.start), style: base));
    }
    spans.addAll(_tokenSpans(context, match.group(0)!, base));
    last = match.end;
  }

  if (last < text.length) {
    spans.add(TextSpan(text: text.substring(last), style: base));
  }
  return spans.isEmpty ? [TextSpan(text: text, style: base)] : spans;
}

List<InlineSpan> _tokenSpans(
  BuildContext context,
  String token,
  TextStyle base,
) {
  // ── Bouton ──
  final button = _button.firstMatch(token);
  if (button != null) {
    final route = button.group(2)!.trim();
    // Un chemin inconnu ne devient pas un bouton mort : il redevient du
    // texte. La règle anti-hallucination s'applique à l'affichage, pas
    // seulement à la consigne donnée au modèle.
    if (!isKnownRoute(route)) return [TextSpan(text: token, style: base)];
    return [
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 2, horizontal: 2),
          child: FilledButton.tonal(
            onPressed: () => context.go(route),
            style: FilledButton.styleFrom(
              minimumSize: const Size(0, 36),
              padding: const EdgeInsets.symmetric(horizontal: 14),
              textStyle: const TextStyle(fontSize: 13),
            ),
            child: Text(button.group(1)!.trim()),
          ),
        ),
      ),
    ];
  }

  // ── Image en ligne ──
  final image = _inlineImage.firstMatch(token);
  if (image != null) {
    return [
      WidgetSpan(
        child: _ImageBlock(image.group(1)!, image.group(2)!).build(context, base),
      ),
    ];
  }

  // ── Lien ──
  final link = _link.firstMatch(token);
  if (link != null) {
    final label = link.group(1)!;
    final href = link.group(2)!;

    if (href.startsWith('/')) {
      if (!isKnownRoute(href)) return [TextSpan(text: token, style: base)];
      return [
        WidgetSpan(
          alignment: PlaceholderAlignment.middle,
          child: InkWell(
            onTap: () => context.go(href),
            child: Text(
              label,
              style: base.copyWith(
                color: AppColors.primary,
                decoration: TextDecoration.underline,
                decorationColor: AppColors.primary,
              ),
            ),
          ),
        ),
      ];
    }

    if (!isWebLink(href)) {
      // `javascript:`, `data:`, `file:` — rendus en texte brut.
      return [TextSpan(text: token, style: base)];
    }

    // L'adresse est MONTRÉE, jamais masquée derrière le libellé : un
    // modèle peut rapporter un lien venu d'un tiers, et un libellé
    // rassurant sur une adresse qui ne l'est pas est la forme même de
    // l'hameçonnage.
    return [
      TextSpan(text: label, style: base.copyWith(color: AppColors.info)),
      TextSpan(
        text: ' ($href)',
        style: base.copyWith(fontSize: 12, color: AppColors.muted),
      ),
    ];
  }

  // ── Icône ──
  if (_iconToken.hasMatch(token)) {
    final name = token.substring(1, token.length - 1);
    if (!isKnownIcon(name)) return [TextSpan(text: token, style: base)];
    return [
      WidgetSpan(
        alignment: PlaceholderAlignment.middle,
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 1),
          child: Icon(
            _icons[name],
            size: (base.fontSize ?? 14) + 2,
            color: _iconTone[name] ?? base.color,
            semanticLabel: name,
          ),
        ),
      ),
    ];
  }

  if (token.startsWith('**') || token.startsWith('__')) {
    return [
      TextSpan(
        text: token.substring(2, token.length - 2),
        style: base.copyWith(fontWeight: FontWeight.w600),
      ),
    ];
  }
  if (token.startsWith('~~')) {
    return [
      TextSpan(
        text: token.substring(2, token.length - 2),
        style: base.copyWith(
          decoration: TextDecoration.lineThrough,
          color: AppColors.muted,
        ),
      ),
    ];
  }
  if (token.startsWith('==')) {
    return [
      TextSpan(
        text: token.substring(2, token.length - 2),
        style: base.copyWith(
          backgroundColor: AppColors.primary.withValues(alpha: 0.22),
          color: AppColors.foreground,
        ),
      ),
    ];
  }
  if (token.startsWith('`')) {
    return [
      TextSpan(
        text: token.substring(1, token.length - 1),
        style: base.copyWith(
          fontFamily: 'monospace',
          fontSize: (base.fontSize ?? 14) - 1,
          color: AppColors.primary,
        ),
      ),
    ];
  }
  return [
    TextSpan(
      text: token.substring(1, token.length - 1),
      style: base.copyWith(fontStyle: FontStyle.italic),
    ),
  ];
}
