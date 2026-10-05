import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';
import ts from 'typescript';
import { createPinia, setActivePinia } from 'pinia';
import { createMemoryHistory, createRouter } from 'vue-router';

// Load the actual TypeScript modules with the same dependencies as the app.
async function moduleUrl(path, replacements = {}, transform = s => s) {
  const source = transform(await readFile(new URL(path, import.meta.url), 'utf8'));
  let code = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  for (const [name, url] of Object.entries(replacements)) {
    code = code.replaceAll(`'${name}'`, JSON.stringify(url));
  }
  return `data:text/javascript;base64,${Buffer.from(code).toString('base64')}`;
}

const apiUrl = await moduleUrl('../src/api/client.ts');
const { api } = await import(apiUrl);
const { useLibraryStore } = await import(await moduleUrl('../src/stores/library.ts', {
  '@/api/client': apiUrl,
  vue: import.meta.resolve('vue'),
  pinia: import.meta.resolve('pinia'),
}));
const { getRouterBase } = await import(await moduleUrl('../src/router/base.ts'));

test('navigation keeps the SPA prefix on entry and deep links', async () => {
  for (const [pathname, expected] of [
    ['/spa', '/spa/'], ['/spa/anime', '/spa/'], ['/app', '/app/'],
    ['/app/library', '/app/'], ['/', '/'], ['/spa-other', '/'],
  ]) {
    const base = getRouterBase(pathname);
    assert.equal(base, expected);
    const router = createRouter({
      history: createMemoryHistory(base),
      routes: [{ path: '/downloads', component: {} }],
    });
    await router.push('/downloads');
    assert.equal(router.resolve('/downloads').href, `${base}downloads`);
  }
});

test('unwatch sends false and keeps separate VF/VOSTFR state', async () => {
  const previousFetch = globalThis.fetch;
  const bodies = [];
  globalThis.fetch = async (url, config) => {
    bodies.push(JSON.parse(config.body));
    return new Response(JSON.stringify({ success: true }));
  };
  try {
    await api.markEpisodeWatched({ animeUrl: 'anime', episodeNumber: 1, watched: false });
    assert.equal(bodies[0].watched, false);
    setActivePinia(createPinia());
    const library = useLibraryStore();
    assert.equal(library.isWatched('anime', 1, 'VF'), undefined);
    await library.markWatched('anime', 1, true, 'VF');
    await library.markWatched('anime', 1, true, 'VOSTFR');
    await library.markWatched('anime', 1, false, 'VF');
    assert.equal(library.isWatched('anime', 1, 'VF'), false);
    assert.equal(library.isWatched('anime', 1, 'VOSTFR'), true);
    assert.equal(bodies.at(-1).version, 'VF');
    assert.equal(bodies.at(-1).watched, false);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

const episodeUtilsUrl = await moduleUrl('../src/utils/episodes.ts');
const { episodeKey, episodeFileName } = await import(episodeUtilsUrl);
const { usePlayerStore } = await import(await moduleUrl('../src/stores/player.ts', {
  '@/api/client': apiUrl,
  '@/utils/episodes': episodeUtilsUrl,
  vue: import.meta.resolve('vue'), pinia: import.meta.resolve('pinia'),
}));

test('VF selection and subtitle overrides do not include the VOSTFR counterpart', () => {
  const vf = { number: 1, version: 'VF', playerUrl: 'https://anime/vf/1' };
  const vo = { number: 1, version: 'VOSTFR', playerUrl: 'https://anime/vo/1' };
  const selected = new Set([episodeKey(vf)]);
  assert.deepEqual([vf, vo].filter(ep => selected.has(episodeKey(ep))), [vf]);
  assert.notEqual(episodeFileName('Anime', vf), episodeFileName('Anime', vo));
  assert.notEqual(episodeKey(vf), episodeKey({...vf, playerUrl: 'https://other/vf/1'}));
});

test('player next and previous stay in the selected language', async () => {
  setActivePinia(createPinia());
  const player = usePlayerStore();
  const previous = api.resolveVideoStream;
  api.resolveVideoStream = async () => ({ streamUrl: 'https://cdn/video.mp4' });
  try {
    const episodes = [
      {number: 1, version: 'VF', playerUrl: 'https://vf/1'},
      {number: 1, version: 'VOSTFR', playerUrl: 'https://vo/1'},
      {number: 2, version: 'VF', playerUrl: 'https://vf/2'},
      {number: 2, version: 'VOSTFR', playerUrl: 'https://vo/2'},
    ];
    await player.openPlayer('Anime', 'anime', 'french-manga', episodes[0], episodes);
    await player.playNext();
    assert.equal(player.currentEpisode.version, 'VF');
    assert.equal(player.currentEpisode.number, 2);
    assert.equal(player.hasNext, false);
    await player.playPrev();
    assert.equal(player.currentEpisode.playerUrl, 'https://vf/1');
    assert.equal(player.hasPrev, false);
  } finally { api.resolveVideoStream = previous; }
});

test('single download sends the selected language and parent anime URL', async () => {
  const previousFetch = globalThis.fetch;
  let body;
  globalThis.fetch = async (url, config) => {
    body = JSON.parse(config.body);
    return new Response(JSON.stringify({success: true}));
  };
  try {
    await api.startEpisodeDownload({animeName:'Anime', animeUrl:'anime', episodeNumber:1, version:'VF', url:'https://vf/1'});
    assert.equal(body.version, 'VF');
    assert.equal(body.animeUrl, 'anime');
  } finally { globalThis.fetch = previousFetch; }
});


test('the actual detail view queues only the checked VF episode', async () => {
  const detail = {anime: {title:'Anime', url:'https://anime/title', episodes:[
    {number:1, version:'VF', playerUrl:'https://anime/vf/1'},
    {number:1, version:'VOSTFR', playerUrl:'https://anime/vo/1'},
  ]}, source:'french-manga', watchedEpisodes:[]};
  const captured = [];
  globalThis.__episodeTest = {detail, captured};
  const inline = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
  const code = await moduleUrl('../src/views/AnimeDetailView.vue', {
    '@/utils/episodes': episodeUtilsUrl,
    vue: inline(`export {ref,computed} from '${import.meta.resolve('vue')}'; export const onMounted=()=>{}; export const watch=()=>{};`),
    'vue-router': inline(`export const useRouter=()=>({push:()=>{}}); export const useRoute=()=>({query:{}});`),
    '@/stores/anime': inline(`export const useAnimeStore=()=>({currentDetail:globalThis.__episodeTest.detail});`),
    '@/stores/player': inline(`export const usePlayerStore=()=>({});`),
    '@/stores/library': inline(`export const useLibraryStore=()=>({isWatched:()=>undefined});`),
    '@/stores/downloads': inline(`export const useDownloadStore=()=>({startBatchDownload:async p=>{globalThis.__episodeTest.captured.push(p);return {success:true};}});`),
  }, s => s.split('<script setup lang="ts">')[1].split('</script>')[0] + '\nexport {toggleEpisodeSelection, downloadSelectedEpisodes, toggleEpSub, epSubtitles};');
  const view = await import(code);
  view.toggleEpisodeSelection(episodeKey(detail.anime.episodes[0]));
  view.toggleEpSub(detail.anime.episodes[0]);
  await view.downloadSelectedEpisodes();
  assert.equal(captured.length, 1);
  assert.equal(captured[0].episodes.length, 1);
  assert.equal(captured[0].episodes[0].version, 'VF');
  assert.equal(captured[0].episodes[0].url, 'https://anime/vf/1');
  assert.equal(captured[0].episodes[0].downloadSubtitles, true);
  assert.equal(view.epSubtitles.value[episodeKey(detail.anime.episodes[1])], undefined);
  delete globalThis.__episodeTest;
});
