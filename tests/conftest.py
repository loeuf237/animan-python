import pytest

from animan.config import settings


@pytest.fixture(autouse=True)
def _tmdb_test_key(monkeypatch):
    """Les tests TMDB mockent le réseau mais exigent une clé non vide.

    La clé n'est plus codée en dur dans la configuration : on injecte une valeur
    factice uniquement pour la durée des tests.
    """
    monkeypatch.setattr(settings, "TMDB_API_KEY", "test-key", raising=False)
