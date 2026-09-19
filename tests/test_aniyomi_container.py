import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from run import app
from animan.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
from animan.services.aniyomi_container import AniyomiContainerSource
from animan.services.extension_service import ExtensionService

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

def test_dex_parser_heuristics():
    """Vérifie la génération des heuristiques de scraping quand aucun APK n'est fourni."""
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.testsource",
        base_url="https://testsource.example.com"
    )
    AniyomiDexParser._fill_heuristics(recipe)

    assert recipe.search_request_path == "/?s={query}"
    assert "title" in recipe.item_title_selector
    assert "a[href]" in recipe.item_link_selector
    assert "img" in recipe.item_thumb_selector

@pytest.mark.asyncio
async def test_container_source_parsing():
    """Vérifie le parsing HTML dans le conteneur Aniyomi."""
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.testsource",
        name="TestSource",
        base_url="https://testsource.example.com",
        search_request_path="/search?q={query}",
        search_selector=".anime-entry",
        item_title_selector=".title",
        item_link_selector="a",
        item_thumb_selector="img",
        episode_list_selector=".episodes-list a",
    )
    source = AniyomiContainerSource(recipe)

    sample_search_html = """
    <html>
        <body>
            <div class="anime-entry">
                <a href="/anime/naruto-shippuden">
                    <img src="https://testsource.example.com/covers/naruto.jpg" />
                    <span class="title">Naruto Shippuden</span>
                </a>
            </div>
            <div class="anime-entry">
                <a href="/anime/bleach">
                    <img src="/covers/bleach.jpg" />
                    <span class="title">Bleach</span>
                </a>
            </div>
        </body>
    </html>
    """
    with patch.object(source, "_fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = sample_search_html
        results = await source.search_anime("naruto")
        assert len(results) == 2
        assert results[0].title == "Naruto Shippuden"
        assert results[0].url == "https://testsource.example.com/anime/naruto-shippuden"
        assert results[0].imageUrl == "https://testsource.example.com/covers/naruto.jpg"
        assert results[1].title == "Bleach"
        assert results[1].url == "https://testsource.example.com/anime/bleach"

    sample_detail_html = """
    <html>
        <head><title>Naruto Shippuden Details</title></head>
        <body>
            <h1 class="title">Naruto Shippuden</h1>
            <div class="synopsis">Un jeune ninja en quête de reconnaissance...</div>
            <div class="episodes-list">
                <a href="/watch/naruto-ep-1">Épisode 1</a>
                <a href="/watch/naruto-ep-2">Épisode 2</a>
            </div>
        </body>
    </html>
    """
    with patch("animan.services.aniyomi_container.is_safe_url", return_value=True):
        with patch.object(source, "_fetch_html", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = sample_detail_html
            detail = await source.get_anime_detail("https://testsource.example.com/anime/naruto-shippuden")
            assert detail is not None
            assert detail.title == "Naruto Shippuden"
            assert "jeune ninja" in detail.synopsis
            assert len(detail.episodes) == 2
            assert detail.episodes[0].number == 1
            assert detail.episodes[0].playerUrl == "https://testsource.example.com/watch/naruto-ep-1"
            assert detail.episodes[1].number == 2

@pytest.mark.asyncio
async def test_extension_service_business_rules(tmp_path):
    """
    Vérifie les deux règles d'or demandées par l'utilisateur:
    1. Règle du dernier magasin ajouté (seules ses sources sont visibles).
    2. Toutes les sources importées sont désactivées par défaut (is_enabled = 0).
    """
    db_file = str(tmp_path / "test_extensions.sqlite3")
    service = ExtensionService(db_path=db_file)

    # Dépôt 1 : 2 extensions
    repo1_data = [
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.fr.repo1_alpha",
            "name": "Repo1 Alpha",
            "lang": "fr",
            "version": "1.0",
            "apk": "repo1_alpha.apk",
            "sources": [{"baseUrl": "https://alpha.repo1.com"}],
        },
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.fr.repo1_beta",
            "name": "Repo1 Beta",
            "lang": "fr",
            "version": "1.0",
            "apk": "repo1_beta.apk",
            "sources": [{"baseUrl": "https://beta.repo1.com"}],
        }
    ]

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = repo1_data

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp1
        res1 = await service.import_repository("https://example.com/repo1/index.min.json")
        assert res1["success"] is True
        assert res1["count"] == 2

    # RÈGLE 2: Par défaut, toutes les sources importées sont désactivées
    visible1 = service.get_visible_extensions()
    assert len(visible1) == 2
    for ext in visible1:
        assert ext["is_enabled"] == 0, "Toutes les sources importées doivent être désactivées par défaut"

    assert len(service.get_enabled_container_sources()) == 0

    # RÈGLE 1: Importation d'un second dépôt -> Il devient le SEUL magasin actif visible
    repo2_data = [
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.en.repo2_gamma",
            "name": "Repo2 Gamma",
            "lang": "en",
            "version": "2.0",
            "apk": "repo2_gamma.apk",
            "sources": [{"baseUrl": "https://gamma.repo2.com"}],
        }
    ]

    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = repo2_data

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp2
        res2 = await service.import_repository("https://example.com/repo2/index.min.json")
        assert res2["success"] is True
        assert res2["count"] == 1

    # Vérification que SEUL le dernier magasin ajouté (repo2) est visible
    visible2 = service.get_visible_extensions()
    assert len(visible2) == 1
    assert visible2[0]["name"] == "Repo2 Gamma"
    assert visible2[0]["is_enabled"] == 0

    # Activation manuelle d'une extension par l'utilisateur
    gamma_id = visible2[0]["id"]
    with patch.object(service, "_compile_extension_recipe", new_callable=AsyncMock) as mock_compile:
        mock_compile.return_value = SourceRecipe(
            pkg="eu.kanade.tachiyomi.animeextension.en.repo2_gamma",
            name="Repo2 Gamma",
            base_url="https://gamma.repo2.com"
        ).to_dict()

        toggle_res = await service.toggle_extension(gamma_id, True)
        assert toggle_res["success"] is True
        assert toggle_res["is_enabled"] is True

    # Vérification en mémoire et whitelist SSRF
    enabled_sources = service.get_enabled_container_sources()
    assert len(enabled_sources) == 1
    assert enabled_sources[0].pkg == "eu.kanade.tachiyomi.animeextension.en.repo2_gamma"
    assert "gamma.repo2.com" in service.get_allowed_domains()

    # Désactivation
    toggle_off = await service.toggle_extension(gamma_id, False)
    assert toggle_off["is_enabled"] is False
    assert len(service.get_enabled_container_sources()) == 0
    assert "gamma.repo2.com" not in service.get_allowed_domains()

def test_api_extensions_routes(client):
    """Teste les routes API du routeur extensions."""
    # 1. Page HTML /extensions
    resp = client.get("/extensions")
    assert resp.status_code == 200
    assert "Magasins &amp; Extensions" in resp.text or "Extensions" in resp.text
    assert "Ajouter un magasin d'extensions" in resp.text

    # 2. Liste des extensions
    resp_list = client.get("/api/extensions/list")
    assert resp_list.status_code == 200
    data = resp_list.json()
    assert "extensions" in data
    assert isinstance(data["extensions"], list)
