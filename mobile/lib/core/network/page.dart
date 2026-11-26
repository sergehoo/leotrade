/// Page de résultats d'une liste paginée.
///
/// Les repositories ne lisaient que `results` et jetaient `next` : au-delà
/// de 25 éléments, la liste était tronquée sans que rien ne le dise. Sur
/// la liste de suivi, l'effet était pire qu'une simple troncature — le
/// bouton « Suivre » lit cette liste pour savoir ce qui est déjà suivi, et
/// un instrument suivi au-delà du 25e apparaissait comme non suivi.
class Page<T> {
  const Page({
    required this.items,
    required this.count,
    required this.hasMore,
  });

  factory Page.fromJson(
    Map<String, dynamic> json,
    T Function(Map<String, dynamic>) read,
  ) {
    final results = json['results'];
    return Page(
      items: results is List
          ? results
              .whereType<Map<String, dynamic>>()
              .map(read)
              .toList(growable: false)
          : const [],
      count: json['count'] as int? ?? 0,
      hasMore: json['next'] != null,
    );
  }

  final List<T> items;

  /// Total annoncé par le serveur, toutes pages confondues.
  final int count;

  /// Vrai s'il reste des pages non chargées. À dire à l'utilisateur
  /// plutôt qu'à taire.
  final bool hasMore;

  bool get isEmpty => items.isEmpty;
  int get length => items.length;
}

/// Plafond de `page_size` accepté par l'API — api/pagination.py.
const int kMaxPageSize = 200;
