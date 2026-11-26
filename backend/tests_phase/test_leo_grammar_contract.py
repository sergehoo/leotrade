"""
tests_phase/test_leo_grammar_contract.py
========================================

Le contrat de formatage de Leo, tenu par trois fichiers.

Ce que Leo a le droit d'écrire est décidé dans le prompt système. Ce qui
s'affiche est décidé par deux rendus indépendants, l'un en TypeScript,
l'autre en Dart. Rien dans le langage ne force ces trois-là à dire la
même chose — et ils ne la disaient pas :

  - le prompt promettait ``==surlignage==``, ``> citation`` et ``---``
    qu'AUCUN des deux clients ne rendait : Leo les écrivait, ils
    s'affichaient en caractères parasites ;
  - sa liste blanche de routes était celle du panneau Django
    (``/trading/ideas/``, ``/risk/profile/``, ``/wallet/``), qui
    n'existe dans aucun des deux clients : chaque lien envoyait
    l'utilisateur dans le vide.

Ce module compare les trois sources. Il ne vérifie pas le rendu — les
tests de widgets s'en chargent — mais le VOCABULAIRE, qui est la seule
chose que les trois doivent partager mot pour mot.

Voir `docs/LEO_MARKDOWN.md`.
"""

import re
from pathlib import Path

import pytest

from ai_assistant.services import ASSISTANT_SYSTEM_PROMPT

REPO = Path(__file__).resolve().parents[2]
WEB_GRAMMAR = REPO / "web" / "src" / "components" / "leo" / "markdownGrammar.ts"
APP_GRAMMAR = REPO / "mobile" / "lib" / "shared" / "widgets" / "markdown_grammar.dart"
CONTRACT = REPO / "docs" / "LEO_MARKDOWN.md"


def _quoted_list(source: str, marker: str) -> set[str]:
    """Valeurs entre guillemets du littéral de liste qui suit `marker`.

    Volontairement rustique : lire le TypeScript et le Dart par
    expression régulière plutôt que d'outiller deux analyseurs. Le jour
    où la forme du littéral change, l'assertion de non-vacuité ci-dessous
    le signale.
    """
    start = source.index(marker)
    body = source[start : source.index("]", start)]
    values = {
        double or single
        for double, single in re.findall(r'"([^"]+)"|\'([^\']+)\'', body)
    }
    assert values, f"Aucune valeur lue pour {marker} — le littéral a changé de forme"
    return values


@pytest.fixture(scope="module")
def web_source() -> str:
    assert WEB_GRAMMAR.exists(), f"{WEB_GRAMMAR} manquant"
    return WEB_GRAMMAR.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def app_source() -> str:
    assert APP_GRAMMAR.exists(), f"{APP_GRAMMAR} manquant"
    return APP_GRAMMAR.read_text(encoding="utf-8")


class TestRoutes:

    def test_both_clients_accept_exactly_the_same_routes(self, web_source, app_source):
        """Un lien valable sur un client doit l'être sur l'autre.

        Sinon Leo apprend à citer une page que la moitié de ses
        utilisateurs ne peut pas ouvrir.
        """
        web = _quoted_list(web_source, "LEO_ROUTES")
        app = _quoted_list(app_source, "kLeoRoutes")

        assert web == app, (
            "Les listes blanches de routes ont divergé.\n"
            f"  web seulement    : {sorted(web - app)}\n"
            f"  mobile seulement : {sorted(app - web)}"
        )

    def test_the_prompt_advertises_only_routes_the_clients_serve(self, web_source):
        """Chaque chemin cité par le prompt doit exister côté client."""
        allowed = _quoted_list(web_source, "LEO_ROUTES")

        section = ASSISTANT_SYSTEM_PROMPT[
            ASSISTANT_SYSTEM_PROMPT.index("ROUTES RÉELLES") :
        ]
        section = section[: section.index("C'est TOUT.")]

        advertised = {
            path.rstrip("/") or "/"
            for path in re.findall(r"→ (/[\w/<>-]*)", section)
        }
        # `/marches/<id>` est le gabarit du détail d'un instrument.
        advertised.discard("/marches/<id>")

        unknown = advertised - allowed
        assert not unknown, (
            "Le prompt cite des chemins qu'aucun client ne sert : "
            f"{sorted(unknown)}"
        )

    def test_the_legacy_django_paths_are_gone_from_the_prompt(self):
        """Les chemins de l'ancien panneau envoyaient dans le vide.

        Ils restent mentionnés UNE fois, pour dire qu'ils n'existent
        plus — mais jamais comme destination recommandée.
        """
        legacy = ["/trading/ideas/", "/risk/profile/", "/wallet/", "/backtests/"]
        recommended = ASSISTANT_SYSTEM_PROMPT[
            ASSISTANT_SYSTEM_PROMPT.index("ROUTES RÉELLES") :
            ASSISTANT_SYSTEM_PROMPT.index("C'est TOUT.")
        ]

        present = [path for path in legacy if path in recommended]
        assert not present, (
            f"Chemins de l'ancien panneau encore recommandés : {present}"
        )


class TestIcons:

    def test_both_clients_know_the_same_icons(self, web_source, app_source):
        web = _quoted_list(web_source, "LEO_ICONS")
        app = _quoted_list(app_source, "kLeoIcons")

        assert web == app, (
            "Les jeux d'icônes ont divergé.\n"
            f"  web seulement    : {sorted(web - app)}\n"
            f"  mobile seulement : {sorted(app - web)}"
        )

    def test_the_prompt_advertises_only_known_icons(self, web_source):
        """Une icône inconnue s'affiche `:comme_ceci:` — autant ne pas
        l'enseigner à Leo."""
        known = _quoted_list(web_source, "LEO_ICONS")

        section = ASSISTANT_SYSTEM_PROMPT[
            ASSISTANT_SYSTEM_PROMPT.index("*Icônes*") :
        ]
        section = section[: section.index("*Liens et boutons*")]
        advertised = set(re.findall(r"`:([a-z]+):`", section))

        assert advertised, "Le prompt n'annonce plus aucune icône"
        unknown = advertised - known
        assert not unknown, f"Icônes annoncées mais non rendues : {sorted(unknown)}"


class TestContract:

    def test_the_written_contract_exists_and_is_referenced(self):
        """`docs/LEO_MARKDOWN.md` est la source unique ; le prompt y renvoie."""
        assert CONTRACT.exists(), "docs/LEO_MARKDOWN.md manquant"
        assert "docs/LEO_MARKDOWN.md" in ASSISTANT_SYSTEM_PROMPT

    @pytest.mark.parametrize(
        "syntax",
        [
            "==surlignage==",
            "> [!WARNING]",
            "~~barré~~",
            "- [ ]",
            "[[Ouvrir le Risk Control|/risque]]",
        ],
    )
    def test_the_prompt_teaches_what_the_clients_render(self, syntax):
        """Chaque syntaxe enseignée doit avoir un rendu.

        C'était précisément le défaut : le prompt enseignait trois
        formes que personne ne rendait.
        """
        assert syntax in ASSISTANT_SYSTEM_PROMPT
