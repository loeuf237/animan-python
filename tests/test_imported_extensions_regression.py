"""Regression cases based on upstream wire formats, not Kotlin DTO names."""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from animan.services.aniyomi_container import AniyomiContainerSource
from animan.services.aniyomi_dex_parser import SourceRecipe
from animan.services.container_adapters.franime_adapter import FrAnimeAdapter
from animan.services.container_adapters.aniworld_adapter import AniWorldAdapter
from animan.services.container_adapters.animesama_adapter import AnimeSamaAdapter
from animan.services.source_http import VerificationRequired


def container(name, **kwargs):
    return AniyomiContainerSource(SourceRecipe(pkg=f'eu.kanade.tachiyomi.animeextension.fr.{name}',
                                               base_url=f'https://{name}.example', **kwargs))


@pytest.mark.asyncio
async def test_franime_wire_fields_search_detail_and_player_indices():
    source = container('franime')
    adapter = FrAnimeAdapter()
    row = {'id': 13051, 'title': 'Boruto: Naruto Next Generations', 'titleO': 'Boruto',
           'titles': {'en_jp': 'Boruto'}, 'affiche': 'https://cdn.example/poster.jpg', 'themes': ['Action'],
           'saisons': [{'episodes': [{'title': 'Début', 'lang': {'vo': {'lecteurs': ['sibnet']},
                                                                 'vf': {'lecteurs': ['sendvid']}}}]}]}
    source._fetch_html = AsyncMock(return_value=json.dumps([row]))
    search, latest = await asyncio.gather(adapter.search_anime('naruto', source), adapter.get_latest_releases(source))
    assert len(search) == len(latest) == 2
    assert source._fetch_html.await_count == 1
    assert search[0].url.endswith('/anime/boruto?lang=vo&s=1')
    assert search[0].imageUrl == row['affiche']
    detail = await adapter.get_anime_detail(search[1].url, source)
    assert detail.genres == ['Action']
    assert detail.episodes[0].version == 'VF'
    source._fetch_html.return_value = 'https://sendvid.com/example'
    streams = await adapter.get_episode_sources(detail.episodes[0].playerUrl, source)
    assert streams[0]['server'] == 'sendvid'
    assert source._fetch_html.call_args.args[0].endswith('/anime/13051/0/0/vf/0')


@pytest.mark.asyncio
async def test_franime_invalid_catalogue_is_not_cached_as_empty():
    source = container('franime')
    source._fetch_html = AsyncMock(return_value='{"error":"maintenance"}')
    adapter = FrAnimeAdapter()
    with pytest.raises(ValueError):
        await adapter.search_anime('naruto', source)
    assert not adapter._catalogues


@pytest.mark.asyncio
async def test_animesama_current_release_cards_preserve_version_and_exclude_scans():
    source = container('animesama')
    source._fetch_html = AsyncMock(return_value='''<div id="containerSorties">
      <div class="as-carte as-carte-anime"><a href="/catalogue/blue-box/saison2/vf/">
      <img src="/box.jpg"><h3 class="as-carte-titre">Blue Box</h3></a></div>
      <div class="as-carte as-carte-scan"><a href="/catalogue/box/scan/vf/">Scans</a></div></div>''')
    results = await AnimeSamaAdapter().get_latest_releases(source)
    assert [(r.title, r.version) for r in results] == [('Blue Box', 'VF')]
    source._fetch_html.side_effect = VerificationRequired(source.base_url)
    with pytest.raises(VerificationRequired):
        await AnimeSamaAdapter().get_latest_releases(source)
    assert source._fetch_html.await_count == 2


@pytest.mark.asyncio
async def test_aniworld_json_search_and_challenge_propagation():
    source = container('aniworld')
    source._fetch_html = AsyncMock(return_value=json.dumps([{'name': '<em>Naruto</em>', 'link': 'naruto',
                                                           'cover': '/150x225/naruto.jpg'}]))
    results = await AniWorldAdapter().search_anime('naruto & boruto', source)
    assert results[0].title == 'Naruto'
    assert results[0].url.endswith('/anime/stream/naruto')
    assert '/220x330/' in results[0].imageUrl
    assert source._fetch_html.call_args.args[0].endswith('keyword=naruto+%26+boruto')
    source._fetch_html.side_effect = VerificationRequired(source.base_url)
    with pytest.raises(VerificationRequired):
        await AniWorldAdapter().search_anime('naruto', source)


def test_old_import_paths_repaired_without_overwriting_custom_paths():
    source = container('jetanime', latest_request_path='/page/', latest_selector='div.content article > div.poster')
    assert source.recipe.latest_request_path == '/page/1/'
    assert source.recipe.latest_selector == 'div.content article'
    assert container('jetanime', latest_request_path='/custom').recipe.latest_request_path == '/custom'
    source = container('vostfree', search_request_path='/animes-vostfr/page/')
    assert source.recipe.search_request_path == '/index.php?do=search'
    assert container('anisama', latest_request_path='/recently-added/?page=').recipe.latest_request_path.endswith('page=1')


@pytest.mark.asyncio
async def test_aniworld_season_pages_and_redirected_players(monkeypatch):
    source = container('aniworld')
    source._fetch_html = AsyncMock(side_effect=[
        '<div class="series-title"><h1><span>Naruto</span></h1></div><div id="stream"><ul><li><a href="/anime/stream/naruto/staffel-1">1</a></li></ul></div>',
        '<table class="seasonEpisodesList"><tbody><tr data-episode-season-id="1"><td class="seasonEpisodeTitle"><meta content="1"><a href="/anime/stream/naruto/staffel-1/episode-1"><span>Début</span></a></td></tr></tbody></table>',
        '<ul class="row"><li data-lang-key="3"><a class="watchEpisode" href="/redirect/123"><h4>VOE</h4></a></li></ul>',
    ])
    adapter = AniWorldAdapter()
    detail = await adapter.get_anime_detail(source.base_url + '/anime/stream/naruto', source)
    assert len(detail.episodes) == 1
    assert detail.episodes[0].title == 'Début'
    import httpx
    from animan.services.source_http import AsyncSourceClient
    response = httpx.Response(200, request=httpx.Request('GET', 'https://voe.sx/example'))
    monkeypatch.setattr(AsyncSourceClient, 'get', AsyncMock(return_value=response))
    streams = await adapter.get_episode_sources(detail.episodes[0].playerUrl, source)
    assert streams[0]['url'] == 'https://voe.sx/example'
    assert streams[0]['name'] == 'VOE (DE-SUB)'


@pytest.mark.asyncio
async def test_animesama_vf_detail_keeps_episode_language():
    source = container('animesama')
    source._fetch_html = AsyncMock(return_value="<h1>Blue Box</h1><script>var eps1 = ['https://sendvid.com/abc'];</script>")
    detail = await AnimeSamaAdapter().get_anime_detail(source.base_url + '/catalogue/blue-box/saison1/vf/', source)
    assert detail.version == 'VF'
    assert detail.episodes[0].version == 'VF'
