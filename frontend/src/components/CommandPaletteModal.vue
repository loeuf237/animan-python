<template>
  <div v-if="isOpen" class="palette-backdrop" @click="close">
    <div class="palette-card" @click.stop>
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
          <button v-if="query" type="button" class="palette-clear-btn" @click="query = ''; results = []">✕</button>
          <kbd class="palette-esc-badge" @click="close">Échap</kbd>
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
            :key="ext.id || ext.pkg"
            type="button"
            class="palette-tab-chip palette-ext-chip"
            :class="{ active: selectedSource === String(ext.id || ext.pkg) }"
            @click="setSource(String(ext.id || ext.pkg))"
          >
            📦 {{ ext.name }}
          </button>
        </div>
      </div>

      <div class="palette-body">
        <!-- Spinner -->
        <div v-if="isLoading" class="palette-loading">
          <div class="spinner"></div>
          <span>Recherche multi-sources en cours...</span>
        </div>

        <!-- Results List -->
        <div v-else-if="results.length > 0" class="palette-results-list">
          <div
            v-for="(item, idx) in results"
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
          </div>
        </div>

        <!-- Empty State -->
        <div v-else-if="hasSearched" class="palette-empty-hint">
          <p>Aucun résultat trouvé pour "{{ query }}" sur cette source.</p>
        </div>

        <!-- Initial Hint -->
        <div v-else class="palette-empty-hint">
          <p>Tapez au moins 2 lettres pour lancer une recherche instantanée sur tous les catalogues.</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue';
import { useRouter } from 'vue-router';
import { api } from '@/api/client';
import { useAnimeStore } from '@/stores/anime';
import type { AnimeResult } from '@/types';

const props = defineProps<{
  isOpen: boolean;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
}>();

const router = useRouter();
const animeStore = useAnimeStore();

const query = ref('');
const selectedSource = ref('all');
const results = ref<AnimeResult[]>([]);
const isLoading = ref(false);
const hasSearched = ref(false);
const activeIdx = ref(0);
const inputRef = ref<HTMLInputElement | null>(null);

let debounceTimer: any = null;

const enabledExtensions = computed(() => {
  return animeStore.homeFeed?.enabledExtensions || [];
});

watch(
  () => props.isOpen,
  (open) => {
    if (open) {
      nextTick(() => {
        inputRef.value?.focus();
      });
    } else {
      query.value = '';
      results.value = [];
      hasSearched.value = false;
    }
  }
);

function close() {
  emit('close');
}

function setSource(src: string) {
  selectedSource.value = src;
  if (query.value.trim().length >= 2) {
    executeSearch();
  }
}

function onInput() {
  if (debounceTimer) clearTimeout(debounceTimer);
  if (!query.value.trim() || query.value.trim().length < 2) {
    results.value = [];
    hasSearched.value = false;
    return;
  }
  debounceTimer = setTimeout(() => {
    executeSearch();
  }, 300);
}

async function executeSearch() {
  if (!query.value.trim()) return;
  isLoading.value = true;
  hasSearched.value = true;
  activeIdx.value = 0;
  try {
    results.value = await api.searchAnime(query.value.trim(), selectedSource.value);
  } catch (e) {
    console.error('[CommandPalette] Search error:', e);
    results.value = [];
  } finally {
    isLoading.value = false;
  }
}

function navigateResults(delta: number) {
  if (!results.value.length) return;
  const next = activeIdx.value + delta;
  if (next >= 0 && next < results.value.length) {
    activeIdx.value = next;
  }
}

function selectActive() {
  if (results.value.length > 0 && results.value[activeIdx.value]) {
    openAnime(results.value[activeIdx.value]);
  }
}

function openAnime(item: AnimeResult) {
  close();
  router.push({
    path: '/anime',
    query: { url: item.url, source: item.source || 'french-manga' },
  });
}
</script>

<style scoped>
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
