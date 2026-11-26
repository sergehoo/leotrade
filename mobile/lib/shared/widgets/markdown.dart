import 'package:flutter/material.dart';

import '../../core/theme/app_theme.dart';

/// Rendu d'un sous-ensemble de Markdown, en widgets.
///
/// Miroir de `web/src/components/leo/Markdown.tsx` : les deux clients
/// reçoivent le même texte du même modèle et doivent le présenter de la
/// même façon. Sans ce rendu, le mobile affichait les `**` et les `|` de
/// tableau tels quels.
///
/// Construit des widgets, jamais du HTML interprété : le texte vient d'un
/// modèle de langage, qui peut restituer n'importe quoi — y compris du
/// contenu tiers rapporté par un outil. Assembler des widgets rend
/// l'injection structurellement impossible plutôt que filtrée.
///
/// Couvre ce qu'un assistant produit réellement : paragraphes, titres,
/// listes, tableaux, blocs de code, gras, italique, code en ligne et
/// liens. Le reste est rendu tel quel, en texte — mieux vaut un astérisque
/// visible qu'un contenu avalé.
class Markdown extends StatelessWidget {
  const Markdown(this.content, {super.key, this.baseStyle});

  final String content;
  final TextStyle? baseStyle;

  @override
  Widget build(BuildContext context) {
    final style = baseStyle ??
        const TextStyle(fontSize: 14, height: 1.45, color: AppColors.foreground);
    final blocks = _parseBlocks(content);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < blocks.length; i++) ...[
          if (i > 0) const SizedBox(height: 8),
          blocks[i].build(context, style),
        ],
      ],
    );
  }
}

// ── Blocs ────────────────────────────────────────────────────────────────

abstract class _Block {
  const _Block();
  Widget build(BuildContext context, TextStyle base);
}

class _Paragraph extends _Block {
  const _Paragraph(this.text);
  final String text;

  @override
  Widget build(BuildContext context, TextStyle base) =>
      SelectableText.rich(TextSpan(children: _inline(text, base)));
}

class _Heading extends _Block {
  const _Heading(this.level, this.text);
  final int level;
  final String text;

  @override
  Widget build(BuildContext context, TextStyle base) {
    final size = switch (level) { 1 => 18.0, 2 => 16.0, 3 => 15.0, _ => 14.0 };
    return SelectableText.rich(
      TextSpan(
        children: _inline(
          text,
          base.copyWith(fontSize: size, fontWeight: FontWeight.w600),
        ),
      ),
    );
  }
}

class _ListBlock extends _Block {
  const _ListBlock(this.items, {required this.ordered});
  final List<String> items;
  final bool ordered;

  @override
  Widget build(BuildContext context, TextStyle base) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < items.length; i++)
          Padding(
            padding: const EdgeInsets.only(bottom: 3),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                SizedBox(
                  width: 22,
                  child: Text(
                    ordered ? '${i + 1}.' : '•',
                    style: base.copyWith(color: AppColors.muted),
                  ),
                ),
                Expanded(
                  child: SelectableText.rich(
                    TextSpan(children: _inline(items[i], base)),
                  ),
                ),
              ],
            ),
          ),
      ],
    );
  }
}

class _CodeBlock extends _Block {
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
            child: SelectableText(
              body,
              style: base.copyWith(fontFamily: 'monospace', fontSize: 12),
            ),
          ),
        ],
      ),
    );
  }
}

class _TableBlock extends _Block {
  const _TableBlock(this.header, this.rows);
  final List<String> header;
  final List<List<String>> rows;

  @override
  Widget build(BuildContext context, TextStyle base) {
    // Défilement horizontal : un tableau de marché déborde toujours d'un
    // écran de téléphone, et rogner une colonne de chiffres en masquerait
    // le sens.
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: DataTable(
        headingRowHeight: 34,
        dataRowMinHeight: 30,
        dataRowMaxHeight: 44,
        horizontalMargin: 8,
        columnSpacing: 18,
        columns: [
          for (final cell in header)
            DataColumn(
              label: Text(
                cell,
                style: base.copyWith(
                  fontSize: 12,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
        ],
        rows: [
          for (final row in rows)
            DataRow(
              cells: [
                for (var i = 0; i < header.length; i++)
                  DataCell(
                    Text(
                      i < row.length ? row[i] : '',
                      style: base.copyWith(fontSize: 12),
                    ),
                  ),
              ],
            ),
        ],
      ),
    );
  }
}

// ── Analyse ──────────────────────────────────────────────────────────────

final _headingPattern = RegExp(r'^(#{1,4})\s+(.*)$');
final _bulletPattern = RegExp(r'^\s*([-*+]|\d+\.)\s+');
final _orderedPattern = RegExp(r'^\s*\d+\.\s+');
final _separatorPattern = RegExp(r'^\s*\|?[\s:|-]*$');

List<_Block> _parseBlocks(String source) {
  final lines = source.replaceAll('\r\n', '\n').split('\n');
  final blocks = <_Block>[];
  var i = 0;

  while (i < lines.length) {
    final line = lines[i];

    if (line.trim().isEmpty) {
      i++;
      continue;
    }

    // Bloc de code
    if (line.trimLeft().startsWith('```')) {
      final language = line.trim().substring(3).trim();
      final body = <String>[];
      i++;
      while (i < lines.length && !lines[i].trimLeft().startsWith('```')) {
        body.add(lines[i]);
        i++;
      }
      i++; // la clôture
      blocks.add(_CodeBlock(language, body.join('\n')));
      continue;
    }

    // Titre
    final heading = _headingPattern.firstMatch(line);
    if (heading != null) {
      blocks.add(_Heading(heading.group(1)!.length, heading.group(2)!));
      i++;
      continue;
    }

    // Tableau : une ligne de cellules suivie d'une ligne de séparation
    if (line.contains('|') &&
        i + 1 < lines.length &&
        _isSeparator(lines[i + 1])) {
      final header = _cells(line);
      i += 2;
      final rows = <List<String>>[];
      while (i < lines.length && lines[i].contains('|') && lines[i].trim().isNotEmpty) {
        rows.add(_cells(lines[i]));
        i++;
      }
      blocks.add(_TableBlock(header, rows));
      continue;
    }

    // Liste
    if (_bulletPattern.hasMatch(line)) {
      final ordered = _orderedPattern.hasMatch(line);
      final items = <String>[];
      while (i < lines.length && _bulletPattern.hasMatch(lines[i])) {
        items.add(lines[i].replaceFirst(_bulletPattern, ''));
        i++;
      }
      blocks.add(_ListBlock(items, ordered: ordered));
      continue;
    }

    // Paragraphe : jusqu'à la ligne vide ou le début d'un autre bloc
    final paragraph = <String>[];
    while (i < lines.length &&
        lines[i].trim().isNotEmpty &&
        !lines[i].trimLeft().startsWith('```') &&
        !_headingPattern.hasMatch(lines[i]) &&
        !_bulletPattern.hasMatch(lines[i])) {
      paragraph.add(lines[i]);
      i++;
    }
    if (paragraph.isNotEmpty) blocks.add(_Paragraph(paragraph.join('\n')));
  }

  return blocks;
}

bool _isSeparator(String line) =>
    _separatorPattern.hasMatch(line) && line.contains('-') && line.contains('|');

List<String> _cells(String line) {
  var trimmed = line.trim();
  if (trimmed.startsWith('|')) trimmed = trimmed.substring(1);
  if (trimmed.endsWith('|')) trimmed = trimmed.substring(0, trimmed.length - 1);
  return trimmed.split('|').map((cell) => cell.trim()).toList(growable: false);
}

// ── Enrichissements en ligne ─────────────────────────────────────────────

final _inlinePattern = RegExp(
  r'(\*\*[^*]+\*\*)'          // gras
  r'|(__[^_]+__)'             // gras
  r'|(\*[^*\n]+\*)'           // italique
  r'|(`[^`\n]+`)'             // code
  r'|(\[[^\]]+\]\([^)\s]+\))', // lien
);

final _linkPattern = RegExp(r'^\[([^\]]+)\]\(([^)\s]+)\)$');

/// Découpe un fragment en spans. Ce qui n'est pas reconnu reste du texte.
List<InlineSpan> _inline(String text, TextStyle base) {
  final spans = <InlineSpan>[];
  var last = 0;

  for (final match in _inlinePattern.allMatches(text)) {
    if (match.start > last) {
      spans.add(TextSpan(text: text.substring(last, match.start), style: base));
    }
    final token = match.group(0)!;

    if (token.startsWith('**') || token.startsWith('__')) {
      spans.add(TextSpan(
        text: token.substring(2, token.length - 2),
        style: base.copyWith(fontWeight: FontWeight.w600),
      ));
    } else if (token.startsWith('`')) {
      spans.add(TextSpan(
        text: token.substring(1, token.length - 1),
        style: base.copyWith(
          fontFamily: 'monospace',
          fontSize: (base.fontSize ?? 14) - 1,
          color: AppColors.primary,
        ),
      ));
    } else if (token.startsWith('[')) {
      final link = _linkPattern.firstMatch(token);
      final label = link?.group(1) ?? token;
      final href = link?.group(2) ?? '';
      final isWeb = RegExp(r'^https?://', caseSensitive: false).hasMatch(href);

      // L'adresse est montrée et non masquée derrière un libellé : un
      // modèle peut rapporter un lien venu d'un tiers, et un libellé
      // rassurant sur une adresse qui ne l'est pas est précisément la
      // forme que prend l'hameçonnage. Ce qui n'est pas http(s) — un
      // `javascript:` par exemple — reste du texte brut.
      spans.add(TextSpan(
        text: isWeb ? '$label ($href)' : token,
        style: isWeb
            ? base.copyWith(color: AppColors.info)
            : base,
      ));
    } else {
      spans.add(TextSpan(
        text: token.substring(1, token.length - 1),
        style: base.copyWith(fontStyle: FontStyle.italic),
      ));
    }
    last = match.end;
  }

  if (last < text.length) {
    spans.add(TextSpan(text: text.substring(last), style: base));
  }
  return spans.isEmpty ? [TextSpan(text: text, style: base)] : spans;
}
