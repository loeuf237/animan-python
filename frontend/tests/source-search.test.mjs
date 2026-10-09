import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import ts from 'typescript';
import {createPinia, setActivePinia} from 'pinia';
import {reactive, nextTick} from 'vue';

const inline = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
async function moduleUrl(path, replacements = {}, transform = s => s) {
  const source = transform(await readFile(new URL(path, import.meta.url), 'utf8'));
  let code = ts.transpileModule(source, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
  for (const [name, url] of Object.entries(replacements)) code = code.replaceAll(`'${name}'`, JSON.stringify(url));
  code = code.replaceAll("'@/utils/locale'", JSON.stringify(localeUrl)).replaceAll("'@/stores/sourcePreferences'", JSON.stringify(sourcePreferencesUrl));
  return inline(code);
}
const localeSource = await readFile(new URL('../src/utils/locale.ts', import.meta.url), 'utf8');
const english = JSON.parse(await readFile(new URL('../src/locales/en.json', import.meta.url), 'utf8'));
const localeCode = ts.transpileModule(localeSource, {compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText
  .replace("'vue'", JSON.stringify(import.meta.resolve('vue')))
  .replace("import english from '@/locales/en.json';", `const english=${JSON.stringify(english)};`);
const localeUrl = `data:text/javascript;base64,${Buffer.from(localeCode).toString('base64')}`;
// The preference module needs only the already initialized locale.
let sourcePreferencesUrl = '';
sourcePreferencesUrl = await moduleUrl('../src/stores/sourcePreferences.ts', {vue:import.meta.resolve('vue'),pinia:import.meta.resolve('pinia')});

const apiUrl = await moduleUrl('../src/api/client.ts');
const {api, ApiError} = await import(apiUrl);
const searchContextUrl = await moduleUrl('../src/stores/searchContext.ts', {vue:import.meta.resolve('vue'), pinia:import.meta.resolve('pinia')});
const notificationsUrl = await moduleUrl('../src/stores/notifications.ts', {vue:import.meta.resolve('vue'), pinia:import.meta.resolve('pinia')});
const browserUrl = await moduleUrl('../src/utils/browser.ts');
const shared = {'@/api/client':apiUrl, '@/utils/browser':browserUrl, '@/stores/notifications':notificationsUrl, vue:import.meta.resolve('vue'), pinia:import.meta.resolve('pinia')};
const verificationUrl = await moduleUrl('../src/stores/verification.ts', shared);
const {useVerificationStore} = await import(verificationUrl);
const {useAnimeStore} = await import(await moduleUrl('../src/stores/anime.ts', {...shared, './verification':verificationUrl}));

function mockApi(t) {
  const original = {...api};
  t.after(() => Object.assign(api, original));
  setActivePinia(createPinia());
  api.getNetworkSessions = async () => ({sessions:[],browsers:[{name:'installed'}],webviewAvailable:false});
  api.startNetworkVerification = async domain => ({id:domain,domain});
  api.completeNetworkVerification = async id => ({success:true,domain:id,resumed:0});
  api.getSources = async () => ({sources:[]});
}

test('native browser hint recognizes Edge before Chrome and installed verification matches it', async t => {
  mockApi(t);
  const {detectBrowser} = await import(browserUrl);
  assert.equal(detectBrowser('Mozilla Chrome/130.0 Safari/537.36 Edg/130.0').name, 'Microsoft Edge');
  assert.equal(detectBrowser('Mozilla Firefox/130.0').name, 'Firefox');
  assert.equal(detectBrowser('Chrome/130.0 Electron/40.0').name, '');
  assert.equal(detectBrowser('Unknown browser').installedHint, '');
  const original = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', {configurable:true, value:{userAgent:'Chrome/130.0 Edg/130.0'}});
  t.after(() => { if(original) Object.defineProperty(globalThis,'navigator',original); else delete globalThis.navigator; });
  api.getNetworkSessions = async () => ({sessions:[],browsers:[{name:'google-chrome'},{name:'microsoft-edge'}],webviewAvailable:false});
  const verification = useVerificationStore();
  await verification.refresh();
  assert.equal(verification.browser, 'microsoft-edge');
});

test('retry after rotation refreshes only the pending search for that domain', async t => {
  mockApi(t);
  let matched = 0, unrelated = 0;
  api.recheckNetworkSource = async domain => ({success:true, domain});
  const verification = useVerificationStore();
  verification.waitForVerification('one',[{domain:'one.example'}],async()=>{matched++;});
  verification.waitForVerification('two',[{domain:'two.example'}],async()=>{unrelated++;});
  await verification.retry('one.example');
  assert.equal(matched,1); assert.equal(unrelated,0);
  await verification.retry('one.example');
  assert.equal(matched,1);
});

test('search keeps partial results then retries automatically after cookie validation', async t => {
  mockApi(t);
  const requests = [];
  api.searchAnimeDetailed = async (q, source) => {
    requests.push({q, source});
    return {results:[{title:requests.length === 1 ? 'Partial' : 'Verified', url:'anime'}],
      challenges:requests.length === 1 ? [{domain:'source.example',code:'verification_required',error:'challenge'}] : [],errors:[]};
  };
  const search = useAnimeStore(), verification = useVerificationStore();
  await search.search('naruto','all');
  assert.equal(search.searchResults[0].title, 'Partial');
  assert.equal(search.searchChallenges.length, 1);
  await verification.start('source.example');
  await verification.complete();
  assert.equal(search.searchResults[0].title, 'Verified');
  assert.equal(search.searchChallenges.length, 0);
  assert.deepEqual(requests,[{q:'naruto',source:'all'},{q:'naruto',source:'all'}]);
});

test('failed verification does not retry and an obsolete search is never revived', async t => {
  mockApi(t);
  let calls = 0;
  api.searchAnimeDetailed = async () => { calls++; return {results:[],challenges:[{domain:'source.example',code:'verification_required',error:'challenge'}],errors:[]}; };
  const search = useAnimeStore(), verification = useVerificationStore();
  await search.search('old','voir-anime');
  await verification.start('source.example');
  api.completeNetworkVerification = async () => { throw new ApiError('challenge',409,{code:'verification_required'}); };
  await verification.complete();
  assert.equal(calls,1);
  await search.search('');
  api.completeNetworkVerification = async id => ({success:true,domain:id,resumed:0});
  await verification.complete();
  assert.equal(calls,1);
});

test('slow results cannot overwrite a newer search', async t => {
  mockApi(t);
  let finish;
  api.searchAnimeDetailed = q => q === 'old' ? new Promise(resolve => {finish=resolve;}) : Promise.resolve({results:[{title:'New',url:'new'}],challenges:[],errors:[]});
  const search = useAnimeStore();
  const old = search.search('old');
  await search.search('new');
  finish({results:[{title:'Old',url:'old'}],challenges:[],errors:[]});
  await old;
  assert.equal(search.searchResults[0].title,'New');
});

test('the actual command palette shows challenges and retries the same search', async t => {
  mockApi(t);
  const previousDocument = globalThis.document;
  globalThis.document = {body:{style:{overflow:''}},activeElement:null};
  t.after(() => {globalThis.document=previousDocument;});
  globalThis.__paletteProps = reactive({isOpen:false});
  t.after(() => {delete globalThis.__paletteProps;});
  let calls = 0;
  api.searchAnimeDetailed = async (q, source) => {
    assert.equal(q,'naruto'); assert.equal(source,'voir-anime'); calls++;
    return {results:calls > 1 ? [{title:'Naruto',url:'anime'}] : [],challenges:calls === 1 ? [{domain:'source.example',code:'verification_required',error:'challenge'}] : [],errors:[]};
  };
  const vueUrl = inline(`export {ref,computed,watch,nextTick} from '${import.meta.resolve('vue')}'; export const onMounted=()=>{}; export const onUnmounted=()=>{};`);
  const palette = await import(await moduleUrl('../src/components/CommandPaletteModal.vue', {
    '@/api/client':apiUrl, '@/stores/verification':verificationUrl, '@/stores/searchContext':searchContextUrl, vue:vueUrl,
    'vue-router':inline('export const useRouter=()=>({push:()=>{}});'),
  }, s => s.split('<script setup lang="ts">')[1].split('</script>')[0]
     .replace("import VerificationPrompt from './VerificationPrompt.vue';",'')
     .replace("import SourceSelector from './SourceSelector.vue';",'')
     .replace('const props = defineProps<{isOpen: boolean; initialQuery?: string; initialSource?: string}>();','const props = globalThis.__paletteProps;')
     .replace("const emit = defineEmits<{(e: 'close'): void}>();",'const emit=()=>{};')
     + '\nexport {query,results,challenges,executeSearch,close};'));
  globalThis.__paletteProps.initialSource = 'voir-anime';
  globalThis.__paletteProps.isOpen=true;
  await nextTick(); await nextTick();
  palette.query.value='naruto';
  await palette.executeSearch();
  assert.equal(palette.challenges.value.length,1);
  const verification = useVerificationStore();
  await verification.start('source.example'); await verification.complete();
  assert.equal(calls,2); assert.equal(palette.results.value[0].title,'Naruto');
  assert.equal(palette.challenges.value.length,0);
  palette.close();
  globalThis.__paletteProps.isOpen = false;
  await nextTick();
  globalThis.__paletteProps.isOpen = true;
  await nextTick(); await nextTick();
  assert.equal(palette.query.value, 'naruto');
  assert.equal(palette.results.value[0].title, 'Naruto');
  assert.equal(calls, 2, 'returning to completed results should reuse them');
  globalThis.__paletteProps.isOpen = false;
  await nextTick();
});

test('catalogue requests preserve tags and the pagination cursor', async () => {
  const previous=globalThis.fetch;
  let requested;
  globalThis.fetch=async url=>{requested=new URL(url,'http://localhost');return new Response(JSON.stringify({results:[]}));};
  try {
    await api.browseCatalogue('extension.example', {mode:'popular',q:'Naruto & Boruto',tags:['action','comedy'],order:'views',cursor:'next-page'});
    assert.equal(requested.searchParams.get('q'),'Naruto & Boruto');
    assert.deepEqual(requested.searchParams.getAll('tags'),['action','comedy']);
    assert.equal(requested.searchParams.get('cursor'),'next-page');
  } finally {globalThis.fetch=previous;}
});
