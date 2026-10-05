"""Browse each source using its actual routes, filters and extension recipe."""
import hashlib
import time
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, quote_plus

from bs4 import BeautifulSoup

from animan.models.anime import AnimeResult
from animan.services.source_http import source_http
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.animepahe_service import animepahe_service
from animan.services.extension_service import extension_service
from animan.services.aniyomi_container import _safe_select, _safe_select_one, adapter_registry
from animan.services.container_adapters.hanime_adapter import get_hanime_catalog


class CatalogueError(ValueError):
    pass


class SourceCatalogueService:
    def __init__(self):
        self._filters = {}
        self._cursors = {}

    def provider(self, source_id):
        natives = {'french-manga': scraping_service, 'voir-anime': voiranime_service,
                   'animepahe': animepahe_service}
        service = natives.get(source_id) or extension_service.get_container_source_by_id(source_id)
        if service is None:
            raise CatalogueError('Source introuvable ou désactivée')
        return service

    def descriptor(self, source_id, service):
        recipe = getattr(service, 'recipe', None)
        adapter = adapter_registry.find_adapter(service.pkg, service.base_url) if recipe else None
        api_catalogue = bool(adapter and adapter.name in ('FRAnime', 'Hanime'))
        views = [{'id': 'latest', 'label': 'Dernières sorties'}] if not recipe or recipe.supports_latest else []
        if source_id == 'voir-anime' or (recipe and recipe.popular_request_path and recipe.popular_selector and not adapter):
            views.append({'id': 'popular', 'label': 'Populaires'})
        if source_id == 'french-manga':
            views.append({'id': 'featured', 'label': 'Coups de cœur'})
        if api_catalogue or not adapter or (recipe and recipe.popular_request_path and recipe.popular_selector):
            views.append({'id': 'catalogue', 'label': 'Catalogue'})
        views.append({'id': 'search', 'label': 'Recherche'})
        return {'id': source_id, 'name': getattr(service, 'name', None) or
                {'french-manga': 'French-Manga', 'voir-anime': 'VoirAnime', 'animepahe': 'AnimePahe'}.get(source_id, source_id),
                'baseUrl': service.base_url, 'lang': getattr(service, 'lang', 'en' if source_id == 'animepahe' else 'fr'),
                'type': 'imported' if recipe else 'native', 'isEnabled': True, 'views': views,
                'multiTags': source_id == 'voir-anime' or api_catalogue}

    def sources(self):
        entries = [self.descriptor(sid, self.provider(sid)) for sid in ('voir-anime', 'animepahe', 'french-manga')]
        active = {ext.pkg: ext for ext in extension_service.get_enabled_container_sources()}
        entries += [self.descriptor(sid, ext) for sid, ext in active.items()]
        # A compiled recipe represents an installed extension; repository listings
        # without a recipe remain in the Extensions store.
        for ext in extension_service.get_visible_extensions():
            if ext.get('recipe_json') and ext['pkg'] not in active:
                entries.append({'id': ext['pkg'], 'name': ext['name'], 'type': 'imported',
                                'lang': ext['lang'], 'baseUrl': ext.get('base_url') or '',
                                'isEnabled': False, 'views': [], 'multiTags': False})
        return entries

    async def html(self, service, url, method='GET', data=None):
        async with source_http.async_client(headers={'Referer': service.base_url + '/'}, timeout=15) as client:
            response = await client.request(method, url, data=data)
            response.raise_for_status()
            return response.text, str(response.url)

    async def filters(self, source_id):
        service = self.provider(source_id)
        key = (source_id, service.base_url)
        cached = self._filters.get(key)
        if cached and cached['expires'] > time.monotonic():
            return cached
        tags, orders = [], [{'id': 'source', 'label': 'Ordre de la source'},
                            {'id': 'title', 'label': 'Titre A → Z (page)'},
                            {'id': 'title_desc', 'label': 'Titre Z → A (page)'}]
        recipe = getattr(service, 'recipe', None)
        adapter = adapter_registry.find_adapter(service.pkg, service.base_url) if recipe else None
        if adapter and adapter.name in ('FRAnime', 'Hanime'):
            items = await self.api_catalogue(service, adapter)
            labels = sorted({label for item in items for label in item.genres}, key=str.casefold)
            tags = [{'id': hashlib.sha256(label.encode()).hexdigest()[:16], 'label': label,
                     'group': 'Genres', 'value': label} for label in labels]
            orders = [{'id': 'source', 'label': 'Ordre de la source'}, {'id': 'title', 'label': 'Titre A → Z'},
                      {'id': 'title_desc', 'label': 'Titre Z → A'}]
        elif source_id != 'animepahe':
            target = service.base_url + ('/?s=&post_type=wp-manga' if source_id == 'voir-anime' else '/')
            html, final_url = await self.html(service, target)
            soup = BeautifulSoup(html, 'html.parser')
            seen = set()
            for link in soup.select('a[href]'):
                href = urljoin(final_url, link['href'])
                path = urlparse(href).path
                label = link.get_text(' ', strip=True)
                if (urlparse(href).hostname != urlparse(final_url).hostname or not label or
                    not any(marker in path for marker in ('/genre/', '/anime-genre/', '/manga-genre/', '/tag/', '/xfsearch/'))):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                group = 'Tags' if '/tag/' in path or '/tagz/' in path else 'Genres'
                if '/version-serie/' in path: group = 'Langue'
                if '/serie-statut/' in path: group = 'Statut'
                ident = hashlib.sha256(href.encode()).hexdigest()[:16]
                tags.append({'id': ident, 'label': label, 'group': group, 'url': href,
                             'value': path.rstrip('/').split('/')[-1]})
            if source_id == 'voir-anime':
                # These values are exposed by VoirAnime's advanced search form.
                orders = [{'id': value, 'label': label} for value, label in
                          [('source', 'Ordre de la source'), ('latest', 'Date de mise à jour'), ('alphabet', 'Titre A → Z'),
                           ('rating', 'Note'), ('trending', 'Populaires'), ('views', 'Plus vues'), ('new-manga', 'Nouveautés')]]
        value = {'tags': tags, 'orders': orders, 'expires': time.monotonic() + 600}
        if len(self._filters) >= 64: self._filters.pop(next(iter(self._filters)))
        self._filters[key] = value
        return value

    async def api_catalogue(self, service, adapter):
        if adapter.name == 'FRAnime':
            entries = []
            for row in await adapter._catalogue(service):
                items = adapter._entries([row], service)
                for item in items:
                    item.genres = [str(g) for g in row.get('genres', [])]
                entries.extend(items)
            return entries
        rows = await get_hanime_catalog()
        rows = sorted(rows, key=lambda r: r.get('created_at_unix', 0) or r.get('released_at_unix', 0), reverse=True)
        return [AnimeResult(id=str(row.get('id') or row['slug']), title=row.get('name') or row['slug'],
                url=f"https://hanime.tv/videos/hentai/{row['slug']}", imageUrl=row.get('poster_url') or row.get('cover_url') or '',
                genres=[str(g) for g in row.get('tags', [])], version='EN') for row in rows if row.get('slug')]

    def parse_generic(self, html, url, service, selector=None):
        soup = BeautifulSoup(html, 'html.parser')
        recipe = getattr(service, 'recipe', None)
        cards = _safe_select(soup, selector or (recipe.popular_selector if recipe else '') or
                             '.anime-card, .movie-poster, .page-item-detail, article, .item')
        if not cards and service is animepahe_service:
            cards = soup.select('a[href*="/anime/"]')
        results, seen = [], set()
        for card in cards:
            link = _safe_select_one(card, (recipe.item_link_selector if recipe else '') or 'a[href]') or (card if card.name == 'a' else None)
            if not link or not link.get('href'): continue
            href = urljoin(url, link['href'])
            if href in seen or urlparse(href).scheme not in ('http', 'https'): continue
            image = _safe_select_one(card, (recipe.item_thumb_selector if recipe else '') or 'img')
            title_el = _safe_select_one(card, (recipe.item_title_selector if recipe else '') or 'h2, h3, h4, .title, .movie-title')
            title = (title_el.get_text(' ', strip=True) if title_el else '') or link.get('title') or (image.get('alt') if image else '') or link.get_text(' ', strip=True)
            if not title: continue
            seen.add(href)
            raw_image = (image.get('data-src') or image.get('data-lazy-src') or image.get('src') or '') if image else ''
            genres = [a.get_text(' ', strip=True) for a in card.select('a[href*="genre"], .genre, .genres a')]
            results.append(AnimeResult(id=hashlib.sha256(href.encode()).hexdigest()[:16], title=title,
                          url=href, imageUrl=urljoin(url, raw_image) if raw_image else '', genres=genres))
        return results

    def context(self, source_id, mode, query, tags, order):
        return (source_id, mode, query, tuple(sorted(tags)), order)

    def remember_cursor(self, context, target='', offset=0):
        self._cursors = {k: v for k, v in self._cursors.items() if v['expires'] > time.monotonic()}
        if len(self._cursors) >= 256: self._cursors.pop(next(iter(self._cursors)))
        ident = hashlib.sha256(repr((context, target, offset)).encode()).hexdigest()
        self._cursors[ident] = {'url': target, 'offset': offset, 'context': context, 'expires': time.monotonic()+1800}
        return ident

    def next_cursor(self, html, url, context, selector=''):
        soup = BeautifulSoup(html, 'html.parser')
        link = _safe_select_one(soup, selector) if selector else None
        if not link:
            link = soup.select_one('a[rel="next"], a.next, .next a, .pagination a[aria-label="Next"], .wp-pagenavi a.nextpostslink')
        # DLE uses a "next" anchor inside its navigation without rel/class.
        if not link:
            link = next((a for a in soup.select('.navigation a[href], .pagination a[href], .wp-pagenavi a[href]')
                         if a.get_text(strip=True) in ('»', '›', '→', 'Suivant', 'Next')), None)
        if not link or not link.get('href'): return None
        target = urljoin(url, link['href'])
        if urlparse(target)._replace(fragment='') == urlparse(url)._replace(fragment='') or urlparse(target).hostname != urlparse(url).hostname: return None
        return self.remember_cursor(context, target)

    async def browse(self, source_id, mode='latest', query='', tags=(), order='source', cursor=None):
        service = self.provider(source_id)
        recipe = getattr(service, 'recipe', None)
        adapter = adapter_registry.find_adapter(service.pkg, service.base_url) if recipe else None
        api_catalogue = bool(adapter and adapter.name in ('FRAnime', 'Hanime'))
        descriptor = self.descriptor(source_id, service)
        if mode not in [v['id'] for v in descriptor['views']]:
            raise CatalogueError('Ce catalogue n’est pas proposé par cette source')
        query = query.strip()
        if mode == 'search' and not query and not tags:
            return {'source': source_id, 'results': [], 'nextCursor': None, 'queryScope': 'catalogue'}
        context = self.context(source_id, mode, query, tags, order)
        html, url, selector, next_selector = '', '', '', ''
        selected, offset = [], 0
        if tags or order != 'source':
            filters = await self.filters(source_id)
            selected = [next((t for t in filters['tags'] if t['id'] == ident), None) for ident in tags]
            if any(t is None for t in selected): raise CatalogueError('Filtre inconnu ; actualisez les filtres de cette source')
            if len(selected) > 1 and not descriptor['multiTags']: raise CatalogueError('Cette source accepte un seul filtre à la fois')
            if order not in [o['id'] for o in filters['orders']]: raise CatalogueError('Tri inconnu')
        if cursor:
            saved = self._cursors.get(cursor)
            if not saved or saved['context'] != context or saved['expires'] < time.monotonic():
                raise CatalogueError('La page a expiré ; rechargez le catalogue')
            url = saved['url']
            offset = saved.get('offset', 0)

        if api_catalogue:
            items = await self.api_catalogue(service, adapter)
            if mode == 'latest' and adapter.name == 'FRAnime': items.reverse()
            if query: items = [i for i in items if query.casefold() in i.title.casefold()]
            if selected: items = [i for i in items if all(t['value'] in i.genres for t in selected)]
            if order in ('title', 'title_desc'):
                items.sort(key=lambda i: i.title.casefold(), reverse=order == 'title_desc')
            cursor = None
            if offset + 48 < len(items):
                cursor = self.remember_cursor(context, offset=offset+48)
            items = items[offset:offset+48]
        elif source_id == 'voir-anime':
            params = [('s', query), ('post_type', 'wp-manga')]
            if order != 'source': params.append(('m_orderby', order))
            elif mode == 'popular': params.append(('m_orderby', 'trending'))
            elif mode == 'latest': params.append(('m_orderby', 'latest'))
            params += [('genre[]', t['value']) for t in selected]
            if selected: params.append(('op', 'AND'))
            url = url or service.base_url + '/?' + urlencode(params)
            html, url = await self.html(service, url)
            items = service.parse_cards(html)
        elif source_id == 'french-manga':
            if query and not selected and mode == 'search':
                items = await service.search_anime(query)
            else:
                path = '/manga-streaming-1/coups-de-cur/' if mode == 'featured' else '/manga-streaming-1/'
                url = url or (selected[0]['url'] if selected else service.base_url + path)
                html, url = await self.html(service, url)
                items = service.parse_search_results(html)
                if query: items = [i for i in items if query.casefold() in i.title.casefold()]
        elif source_id == 'animepahe':
            if mode == 'search':
                items = await service.search_anime(query)
            elif mode == 'latest':
                page = '1'
                if url: page = parse_qs(urlparse(url).query).get('page', ['1'])[0]
                data = await service._fetch_api('/api?' + urlencode({'m': 'airing', 'page': page}), timeout=12)
                if data is None: raise CatalogueError('AnimePahe refuse l’accès ou est momentanément inaccessible')
                items = [AnimeResult(id=str(row.get('anime_id', row.get('id', ''))), title=row['anime_title'],
                         url=service.base_url + '/anime/' + row['anime_session'], imageUrl=row.get('snapshot') or '',
                         version='VOST / Sub', episodeInfo=f"Épisode {row.get('episode', '')}")
                         for row in data.get('data', []) if row.get('anime_title') and row.get('anime_session')]
                next_url = data.get('next_page_url')
                if next_url:
                    # Only a page number from the source API is accepted.
                    page_number = parse_qs(urlparse(next_url).query).get('page', [''])[0]
                    if page_number.isdigit():
                        target = service.base_url + '/api?' + urlencode({'m': 'airing', 'page': page_number})
                        cursor = self.remember_cursor(context, target)
                    else: cursor = None
                else: cursor = None
            else:
                html, url = await self.html(service, url or service.base_url + '/anime')
                items = self.parse_generic(html, url, service)
        else:
            recipe = service.recipe
            adapter = adapter_registry.find_adapter(service.pkg, service.base_url)
            if adapter and not selected and not url and mode in ('search', 'latest'):
                items = await service.search_anime(query) if mode == 'search' else await service.get_latest_releases()
            else:
                path = (recipe.search_request_path if mode == 'search' else
                        recipe.latest_request_path if mode == 'latest' else recipe.popular_request_path) or '/'
                path = path.replace('{page}', '1').replace('{query}', quote_plus(query))
                method, data = 'GET', None
                if mode == 'search':
                    method = recipe.search_method.upper()
                    if method == 'POST':
                        data = {k: v.replace('{query}', query) for k, v in recipe.search_post_params.items()}
                        data[recipe.search_query_param or 's'] = query
                    elif '{query}' not in (recipe.search_request_path or ''):
                        path += ('&' if '?' in path else '?') + urlencode({recipe.search_query_param or 's': query})
                url = url or (selected[0]['url'] if selected else urljoin(service.base_url+'/', path))
                if selected:
                    method, data = 'GET', None
                html, url = await self.html(service, url, method, data)
                selector = recipe.search_selector if mode == 'search' else recipe.latest_selector if mode == 'latest' else recipe.popular_selector
                next_selector = recipe.search_next_selector if mode == 'search' else recipe.latest_next_selector if mode == 'latest' else recipe.popular_next_selector
                items = self.parse_generic(html, url, service, selector)
                if query and selected: items = [i for i in items if query.casefold() in i.title.casefold()]
        page_query = bool(query and source_id != 'voir-anime' and not api_catalogue and (selected or mode != 'search'))
        if page_query:
            items = [i for i in items if query.casefold() in i.title.casefold()]
        if order in ('title', 'title_desc') and not api_catalogue:
            items = sorted(items, key=lambda i: i.title.casefold(), reverse=order == 'title_desc')
        seen, results = set(), []
        for item in items:
            item.source = source_id
            if item.url not in seen:
                seen.add(item.url)
                results.append(item)
        next_page = cursor if api_catalogue or source_id == 'animepahe' and mode == 'latest' else self.next_cursor(html, url, context, next_selector) if html else None
        return {'source': source_id, 'results': results, 'nextCursor': next_page,
                'queryScope': 'page' if page_query else 'catalogue'}


source_catalogue = SourceCatalogueService()
