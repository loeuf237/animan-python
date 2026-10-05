<template>
  <div v-if="isOpen" class="palette-backdrop" @click="close">
    <div class="palette-card" role="dialog" aria-modal="true" aria-label="Recherche d’animés" @click.stop>
      <div class="palette-header">
        <div class="palette-search-field">
          <svg viewBox="0 0 24 24" class="palette-search-icon"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
          <input
            ref="inputRef"
            v-model="query"
            type="text"
            class="palette-search-input"
            placeholder="Rechercher un animé, épisode, mot-clé..."
            autocomplete="off"
            spellcheck="false"
            @input="onInput"
            @keydown.down.prevent="navigateResults(1)"
            @keydown.up.prevent="navigateResults(-1)"
            @keydown.enter.prevent="selectActive"
            @keydown.esc="close"
          />
          <button v-if="query" type="button" class="palette-clear-btn" @click="clearQuery">✕</button>
          <button type="button" class="palette-esc-badge palette-close-button" aria-label="Fermer la recherche" @click="close">Fermer</button>
        </div>

        <div class="palette-tabs-bar">
          <button
            type="button"
            class="palette-tab-chip"
            :class="{ active: selectedSource === 'all' }"
            @click="setSource('all')"
          >
            Toutes
          </button>
          <button
            type="button"
            class="palette-tab-chip"
            :class="{ active: selectedSource === 'french-manga' }"
            @click="setSource('french-manga')"
          >
            french-manga.net
          </button>
          <button
            type="button"
            class="palette-tab-chip"
            :class="{ active: selectedSource === 'voir-anime' }"
            @click="setSource('voir-anime')"
          >
            voir-anime.to
          </button>
          <button
            type="button"
            class="palette-tab-chip"
            :class="{ active: selectedSource === 'animepahe' }"
            @click="setSource('animepahe')"
          >
            animepahe.pw
          </button>
          <button
            v-for="ext in enabledExtensions"
            :key="ext.id"
            type="button"
            class="palette-tab-chip palette-ext-chip"
            :class="{ active: selectedSource === ext.id }"
            @click="setSource(ext.id)"
          >
            📦 {{ ext.name }}
          </button>
        </div>
      </div>

      <div class="palette-body">
        <VerificationPrompt :challenges="challenges" />
        <p v-if="error" class="palette-error" role="alert">{{ error }}</p>
        <p v-for="warning in warnings" :key="warning.source" class="palette-error">{{ warning.source }} : {{ warning.message }}</p>
        <!-- Spinner -->
        <div v-if="isLoading" class="palette-loading">
          <div class="spinner"></div>
          <span>Recherche multi-sources en cours...</span>
        </div>

        <!-- Results List -->
        <div v-else-if="results.length > 0" class="palette-results-list">
          <button
            v-for="(item, idx) in results"
            type="button"
            :key="item.url"
            class="palette-result-item"
            :class="{ 'is-active': activeIdx === idx }"
            @click="openAnime(item)"
            @mouseenter="activeIdx = idx"
          >
            <img :src="item.imageUrl || '/static/placeholder.jpg'" class="palette-thumb" alt="" />
            <div class="palette-item-info">
              <span class="palette-item-title">{{ item.title }}</span>
              <div class="palette-item-meta">
                <span class="badge badge-source">{{ item.source }}</span>
                <span v-if="item.latestEpisode || item.episodeInfo" class="palette-item-ep">
                  {{ item.latestEpisode || item.episodeInfo }}
                </span>
                <span v-if="item.type" class="palette-item-type">{{ item.type }}</span>
              </div>
            </div>
            <span class="palette-enter-hint">Entrée ↵</span>
          </button>
        </div>

        <!-- Empty State -->
        <div v-else-if="hasSearched && !challenges.length && !error && !warnings.length" class="palette-empty-hint">
          <p>Aucun résultat trouvé pour "{{ query }}" sur cette source.</p>
        </div>

        <!-- Initial Hint -->
        <div v-else-if="!hasSearched" class="palette-empty-hint">
          <p>Tapez au moins 2 lettres pour lancer une recherche instantanée sur tous les catalogues.</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick, onMounted, onUnmounted } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '@/api/client';
import VerificationPrompt from './VerificationPrompt.vue';
import { useVerificationStore, challengeFromError } from '@/stores/verification';
import type { AnimeResult, SourceChallenge, CatalogueSource } from '@/types';

const props = defineProps<{isOpen: boolean; initialQuery?: string}>();
const emit = defineEmits<{(e: 'close'): void}>();
const router = useRouter();
const verification = useVerificationStore();
const query = ref('');
const selectedSource = ref('all');
const results = ref<AnimeResult[]>([]);
const challenges = ref<SourceChallenge[]>([]);
const warnings = ref<{source: string; message: string}[]>([]);
const enabledExtensions = ref<CatalogueSource[]>([]);
const error = ref('');
const isLoading = ref(false);
const hasSearched = ref(false);
const activeIdx = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);
let debounceTimer: ReturnType<typeof setTimeout> | undefined;
let sequence = 0;

function invalidate() {
  sequence++;
  clearTimeout(debounceTimer);
  verification.clearPending('palette-search');
  challenges.value = []; warnings.value = []; error.value = ''; isLoading.value = false;
}
watch(() => props.isOpen, async open => {
  invalidate();
  if (open) {
    query.value = props.initialQuery || '';
    await nextTick(); inputRef.value?.focus();
    void api.getSources().then(res => { enabledExtensions.value = res.sources.filter(s => s.isEnabled && s.type === 'imported'); }).catch(() => {});
    if (query.value.trim().length >= 2) void executeSearch();
  } else {
    query.value = ''; results.value = []; hasSearched.value = false;
  }
});
function close() { invalidate(); emit('close'); }
function clearQuery() { query.value = ''; results.value = []; hasSearched.value = false; invalidate(); inputRef.value?.focus(); }
function setSource(src: string) {
  invalidate(); selectedSource.value = src; results.value = [];
  if (query.value.trim().length >= 2) void executeSearch();
}
function onInput() {
  invalidate(); results.value = [];
  if (query.value.trim().length < 2) { hasSearched.value = false; return; }
  debounceTimer = setTimeout(() => void executeSearch(), 300);
}
async function executeSearch() {
  if (!query.value.trim() || !props.isOpen) return;
  const current = ++sequence;
  const requestedQuery = query.value.trim(), source = selectedSource.value;
  verification.clearPending('palette-search');
  isLoading.value = true; hasSearched.value = true; activeIdx.value = 0; error.value = '';
  try {
    const response = await api.searchAnimeDetailed(requestedQuery, source);
    if (current !== sequence || !props.isOpen) return;
    results.value = response.results; challenges.value = response.challenges; warnings.value = response.errors;
    verification.waitForVerification('palette-search', [...response.challenges, ...response.errors.flatMap(e => e.domain ? [{domain: e.domain}] : [])], async () => {
      if (current === sequence && props.isOpen) await executeSearch();
    });
  } catch (exc) {
    if (current !== sequence || !props.isOpen) return;
    const challenge = challengeFromError(exc);
    results.value = [];
    if (challenge) {
      challenges.value = [challenge];
      verification.waitForVerification('palette-search', [challenge], async () => {
        if (current === sequence && props.isOpen) await executeSearch();
      });
    } else error.value = exc instanceof Error ? exc.message : 'La recherche a échoué.';
  } finally { if (current === sequence) isLoading.value = false; }
}
function navigateResults(delta: number) {
  const next = activeIdx.value + delta;
  if (next >= 0 && next < results.value.length) activeIdx.value = next;
}
function selectActive() {
  if (results.value[activeIdx.value]) openAnime(results.value[activeIdx.value]!);
  else if (!isLoading.value) void executeSearch();
}
function openAnime(item: AnimeResult) {
  close();
  void router.push({path: '/anime', query: {url: item.url, source: item.source || 'french-manga'}});
}
function onEscape(event: KeyboardEvent) {
  if (!props.isOpen) return;
  if (event.key === 'Escape') close();
  if (event.key === 'Tab') {
    const elements = [...document.querySelectorAll<HTMLElement>('.palette-card input, .palette-card button:not(:disabled), .palette-card select')].filter(el => el.getClientRects().length);
    const first = elements[0], last = elements.at(-1);
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
  }
}
onMounted(() => window.addEventListener('keydown', onEscape));
onUnmounted(() => { invalidate(); window.removeEventListener('keydown', onEscape); });
</script>

<style scoped>
.palette-close-button { display: inline-flex !important; }
.palette-result-item { width: 100%; border: 0; background: transparent; color: inherit; text-align: left; font: inherit; }
.palette-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(8, 12, 22, 0.75);
  backdrop-filter: blur(12px);
  z-index: 500;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: min(12vh, 120px);
}

.palette-card {
  width: min(720px, 94vw);
  max-height: 75vh;
  display: flex;
  flex-direction: column;
  background: var(--panel);
  border: 1px solid var(--line-strong);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow);
  overflow: hidden;
}

.palette-header {
  padding: 18px 20px 14px;
  border-bottom: 1px solid var(--line);
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.palette-search-field {
  position: relative;
  display: flex;
  align-items: center;
}

.palette-search-icon {
  position: absolute;
  left: 14px;
  width: 20px;
  height: 20px;
  color: var(--muted);
  pointer-events: none;
}

.palette-search-input {
  width: 100%;
  height: 48px;
  background: var(--input-bg);
  border: 1px solid var(--input-border);
  border-radius: var(--radius-pill);
  color: var(--text);
  font-size: 16px;
  padding: 0 90px 0 46px;
  outline: none;
}

.palette-search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-container);
}

.palette-clear-btn {
  position: absolute;
  right: 68px;
  background: none;
  border: none;
  color: var(--muted);
  font-size: 14px;
  cursor: pointer;
}

.palette-esc-badge {
  position: absolute;
  right: 14px;
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  border-radius: var(--radius-sm);
  padding: 2px 8px;
  font-size: 11px;
  color: var(--faint);
  font-weight: 700;
  cursor: pointer;
}

.palette-tabs-bar {
  display: flex;
  gap: 8px;
  overflow-x: auto;
  padding-bottom: 4px;
}

.palette-tab-chip {
  padding: 4px 12px;
  border-radius: var(--radius-pill);
  background: var(--panel-subtle);
  border: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  white-space: nowrap;
}

.palette-tab-chip.active {
  background: var(--accent-container);
  color: var(--on-accent-container);
  border-color: var(--accent);
}

.palette-error { padding: 12px 16px; color: var(--yellow, #d9a441); }
.palette-body > .verification-prompt { margin: 12px; }
.palette-body {
  flex: 1;
  overflow-y: auto;
  min-height: 240px;
  max-height: 55vh;
  padding: 12px 14px;
}

.palette-loading,
.palette-empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 220px;
  color: var(--muted);
  gap: 12px;
  font-size: 14px;
}

.palette-results-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.palette-result-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 10px 14px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: all var(--transition);
}

.palette-result-item:hover,
.palette-result-item.is-active {
  background: var(--accent-container);
}

.palette-thumb {
  width: 40px;
  height: 56px;
  border-radius: 6px;
  object-fit: cover;
  background: var(--surface);
  flex-shrink: 0;
}

.palette-item-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  overflow: hidden;
}

.palette-item-title {
  font-weight: 700;
  font-size: 14px;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.palette-item-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.palette-item-ep {
  color: var(--accent);
  font-weight: 600;
}

.palette-item-type {
  color: var(--faint);
}

.palette-enter-hint {
  font-size: 11px;
  color: var(--faint);
  font-weight: 600;
  opacity: 0;
  transition: opacity var(--transition);
}

.palette-result-item.is-active .palette-enter-hint {
  opacity: 1;
}
</style>
