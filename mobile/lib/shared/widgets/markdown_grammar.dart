/// La grammaire de Leo — partie indépendante du rendu.
///
/// Contrat partagé avec `web/src/components/leo/markdownGrammar.ts` et
/// avec `ASSISTANT_SYSTEM_PROMPT` côté serveur. Voir
/// `docs/LEO_MARKDOWN.md`.
///
/// Ce fichier ne contient que des décisions — quels chemins sont
/// navigables, quelles icônes existent, quelle adresse d'image est
/// acceptable. Le rendu vit dans `markdown.dart`.
library;

import '../../core/config/env.dart';

/// Chemins vers lesquels Leo peut pointer.
///
/// Ceux de Flutter ET de React, à l'exclusion de la route de Leo
/// lui-même : un lien de Leo vers Leo n'a pas de sens.
///
/// Un chemin absent d'ici est rendu en TEXTE, jamais en lien ni en
/// bouton. La règle anti-hallucination du prompt est ainsi appliquée à
/// l'affichage, et pas seulement à la consigne : si le modèle invente
/// une page, l'interface ne fabrique pas un bouton mort pour autant.
const List<String> kLeoRoutes = [
  '/',
  '/portefeuille',
  '/marches',
  '/risque',
  '/portefeuille-electronique',
  '/brokers',
];

final RegExp _assetDetail = RegExp(r'^/marches/\d+$');

/// Vrai si ce chemin interne existe réellement dans les deux clients.
bool isKnownRoute(String path) {
  final clean = path.split(RegExp(r'[?#]')).first;
  final normalised =
      clean.length > 1 && clean.endsWith('/')
          ? clean.substring(0, clean.length - 1)
          : clean;
  return kLeoRoutes.contains(normalised) || _assetDetail.hasMatch(normalised);
}

/// Icônes que Leo peut nommer. Un nom absent reste du texte.
const List<String> kLeoIcons = [
  'gain',
  'perte',
  'neutre',
  'alerte',
  'danger',
  'info',
  'idee',
  'risque',
  'verrou',
  'horloge',
  'cible',
  'graphique',
  'portefeuille',
  'marche',
  'broker',
  'ia',
  'valide',
  'refus',
];

bool isKnownIcon(String name) => kLeoIcons.contains(name);

enum CalloutKind { note, tip, important, warning, caution }

CalloutKind? calloutKindFrom(String raw) => switch (raw.toUpperCase()) {
      'NOTE' => CalloutKind.note,
      'TIP' => CalloutKind.tip,
      'IMPORTANT' => CalloutKind.important,
      'WARNING' => CalloutKind.warning,
      'CAUTION' => CalloutKind.caution,
      _ => null,
    };

/// Une image n'est chargée que depuis l'origine de l'API.
///
/// Une image distante dans une réponse de modèle est un pixel traceur :
/// son chargement révèle l'adresse IP du lecteur et le moment de la
/// lecture, et l'URL peut encoder ce qu'on veut exfiltrer. Le texte
/// alternatif, lui, ne coûte rien à afficher.
bool isSameOriginImage(String url) {
  if (url.startsWith('//')) return false;
  if (url.startsWith('/')) return true;
  return url.startsWith('${Env.apiBaseUrl}/');
}

/// Adresse absolue d'une image de l'API, à partir d'un chemin relatif.
String resolveImageUrl(String url) =>
    url.startsWith('/') ? '${Env.apiBaseUrl}$url' : url;

/// Schémas qu'on accepte d'annoncer comme adresse web.
bool isWebLink(String href) =>
    RegExp(r'^https?://', caseSensitive: false).hasMatch(href);
