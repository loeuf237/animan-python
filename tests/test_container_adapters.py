import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from animan.services.container_adapters.registry import adapter_registry
from animan.services.container_adapters.hanime_adapter import HanimeAdapter
from animan.services.container_adapters.animesama_adapter import AnimeSamaAdapter
from animan.services.aniyomi_container import AniyomiContainerSource

from animan.services.aniyomi_dex_parser import SourceRecipe

def test_adapter_registry_matching():
    hanime = adapter_registry.find_adapter("eu.kanade.tachiyomi.animeextension.all.hanime", "https://hanime.tv")
    assert isinstance(hanime, HanimeAdapter)

    animesama = adapter_registry.find_adapter("eu.kanade.tachiyomi.animeextension.fr.animesama", "https://anime-sama.fr")
    assert isinstance(animesama, AnimeSamaAdapter)

    unknown = adapter_registry.find_adapter("eu.kanade.tachiyomi.animeextension.en.standardhtml", "https://example.com")
    assert unknown is None

@pytest.mark.asyncio
async def test_hanime_adapter_search_detail_sources():
    adapter = HanimeAdapter()
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.en.hanime",
        name="Hanime",
        base_url="https://hanime.tv",
    )
    container = AniyomiContainerSource(recipe)

    fake_catalog = [
        {
            "id": 101,
            "name": "Overflow Season 1",
            "slug": "overflow-season-1",
            "poster_url": "https://hanime-cdn.com/images/posters/overflow.jpg",
            "description": "<p>Super anime</p>",
            "tags": ["romance", "comedy"],
            "created_at_unix": 1700000000,
        },
        {
            "id": 102,
            "name": "Another Title",
            "slug": "another-title",
            "poster_url": "https://hanime-cdn.com/images/posters/another.jpg",
            "description": "Another description",
            "tags": ["action"],
            "created_at_unix": 1600000000,
        },
    ]

    with patch("animan.services.container_adapters.hanime_adapter.get_hanime_catalog", new_callable=AsyncMock) as mock_cat:
        mock_cat.return_value = fake_catalog

        # 1. Search
        search_res = await adapter.search_anime("overflow", container)
        assert len(search_res) == 1
        assert search_res[0].title == "Overflow Season 1"
        assert search_res[0].url == "https://hanime.tv/videos/hentai/overflow-season-1"

        # 2. Latest
        latest_res = await adapter.get_latest_releases(container)
        assert len(latest_res) == 2
        assert latest_res[0].title == "Overflow Season 1"

        # 3. Detail
        detail = await adapter.get_anime_detail("https://hanime.tv/videos/hentai/overflow-season-1", container)
        assert detail is not None
        assert detail.title == "Overflow Season 1"
        assert detail.synopsis == "Super anime"
        assert len(detail.episodes) == 1

        # 4. Sources
        fake_api_manifest = {
            "videos_manifest": {
                "servers": [
                    {
                        "name": "Server 1",
                        "streams": [
                            {"height": "1080", "url": "https://cdn.hanime.tv/1080p/manifest.m3u8"},
                            {"height": "720", "url": "https://cdn.hanime.tv/720p/manifest.m3u8"},
                        ]
                    }
                ]
            }
        }
        mock_api_resp = MagicMock(status_code=200)
        mock_api_resp.json.return_value = fake_api_manifest

        with patch("animan.services.source_http.AsyncSourceClient.get", new_callable=AsyncMock, return_value=mock_api_resp):
            sources = await adapter.get_episode_sources("https://hanime.tv/videos/hentai/overflow-season-1", container)
            assert len(sources) == 2
            assert sources[0]["server"] == "Server 1"
            assert sources[0]["quality"] == "1080p"

@pytest.mark.asyncio
async def test_animesama_adapter_js_array_extraction():
    adapter = AnimeSamaAdapter()
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.animesama",
        name="Anime-Sama",
        base_url="https://anime-sama.fr",
    )
    container = AniyomiContainerSource(recipe)

    fake_detail_html = '''
    <html>
        <body>
            <h1 id="titreAnime">Solo Leveling</h1>
            <img id="coverAnime" src="/images/solo_leveling.jpg" />
            <p id="synopsis">L'histoire du plus faible des chasseurs devenant le plus fort.</p>
            <script>
                var eps1 = ['https://video.sibnet.ru/shell.php?videoid=111', 'https://video.sibnet.ru/shell.php?videoid=222'];
                var eps2 = ['https://sendvid.com/ep1', 'https://sendvid.com/ep2'];
            </script>
        </body>
    </html>
    '''

    with patch.object(adapter, "_fetch_text", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = fake_detail_html

        detail = await adapter.get_anime_detail("https://anime-sama.fr/catalogue/solo-leveling/saison1/vostfr/", container)
        assert detail is not None
        assert detail.title == "Solo Leveling"
        assert len(detail.episodes) == 2
        assert detail.episodes[0].number == 1
        assert detail.episodes[0].playerUrl == "https://video.sibnet.ru/shell.php?videoid=111"
        assert detail.episodes[1].number == 2
        assert detail.episodes[1].playerUrl == "https://video.sibnet.ru/shell.php?videoid=222"

    # Test sources d'un épisode direct
    sources = await adapter.get_episode_sources("https://video.sibnet.ru/shell.php?videoid=111", container)
    assert len(sources) == 1
    assert sources[0]["server"] == "Sibnet"
    assert sources[0]["url"] == "https://video.sibnet.ru/shell.php?videoid=111"
