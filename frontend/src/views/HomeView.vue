<template>
  <div class="home-container">
    <!-- Hero Section -->
    <section class="hero fade-in" id="search-panel">
      <div class="hero-panel">
        <h1 class="hero-title">Regardez vos animés sans interruption.</h1>
        <p class="hero-subtitle">Recherchez, téléchargez et organisez vos séries préférées en VF et VOSTFR.</p>

        <form class="search-form" @submit.prevent="onSearchSubmit">
          <div class="search-input-wrap">
            <input
              v-model="heroQuery"
              type="text"
              class="search-input"
              placeholder="Rechercher un anime, un épisode, un genre..."
              autocomplete="off"
              spellcheck="false"
              @click="emitOpenPalette"
              @focus="emitOpenPalette"
            />
            <svg class="search-icon" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
            <kbd class="kbd-shortcut-badge" title="Ctrl + K" @click="emitOpenPalette">Ctrl K</kbd>
          </div>

          <div class="source-tabs" role="radiogroup">
            <label class="source-tab">
              <input type="radio" value="french-manga" v-model="selectedSource" />
              <span>french-manga.net</span>
            </label>
            <label class="source-tab">
              <input type="radio" value="voir-anime" v-model="selectedSource" />
              <span>voir-anime.to</span>
            </label>
            <label class="source-tab">
              <input type="radio" value="animepahe" v-model="selectedSource" />
              <span>animepahe.pw</span>
            </label>
            <label
              v-for="ext in enabledExtensions"
              :key="ext.id || ext.pkg"
              class="source-tab"
              :title="ext.pkg"
            >
              <input type="radio" :value="ext.id || ext.pkg" v-model="selectedSource" />
              <span>📦 {{ ext.name }}</span>
            </label>
            <label class="source-tab">
              <input type="radio" value="all" v-model="selectedSource" />
              <span>Toutes les sources</span>
            </label>
          </div>

          <div style="display: flex; gap: 12px; align-items: center;">
            <button type="submit" class="btn btn-primary" style="flex: 1;">
              <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
              Rechercher
            </button>
          </div>
        </form>
      </div>

      <aside class="quick-panel">
        <div class="quick-row">
          <span>Favoris</span>
          <strong>{{ favoritesCount }}</strong>
        </div>
        <div class="quick-row">
          <span>Sources actives</span>
          <strong style="color: var(--green);">{{ activeSourcesCount }} actives</strong>
        </div>
        <div class="quick-row">
          <span>Téléchargements</span>
          <router-link to="/downloads" class="btn btn-sm">Ouvrir le gestionnaire</router-link>
        </div>
      </aside>
    </section>

    <!-- Quick Favorites Section -->
    <section v-if="favorites.length > 0" class="section fade-in">
      <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px;">
        <h2 class="section-title" style="margin: 0;">
          <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>
          Accès rapide aux favoris
        </h2>
        <router-link to="/library" class="btn btn-sm" style="color: var(--accent);">Voir tout</router-link>
      </div>
      <div class="results-grid">
        <article
          v-for="fav in favorites.slice(0, 10)"
          :key="fav.url"
          class="anime-card"
        >
          <router-link :to="{ path: '/anime', query: { url: fav.url, source: fav.source || 'french-manga' } }" class="card-link">
            <div class="card-poster">
              <img :src="fav.imageUrl" :alt="fav.title" loading="lazy" />
              <div class="card-overlay">
                <span class="fav-badge">Favori</span>
                <span v-if="fav.autoDownload" class="chip chip-auto">Auto-DL</span>
              </div>
            </div>
            <div class="card-info">
              <h3 class="card-title">{{ fav.title }}</h3>
              <span class="card-sub">{{ fav.source || 'french-manga' }}</span>
            </div>
          </router-link>
        </article>
      </div>
    </section>

    <!-- Latest Releases Section with Tabs -->
    <section class="section fade-in">
      <div class="releases-tabs-header">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>
          Dernières Sorties
        </h2>
        <div class="release-tabs">
          <button
            class="tab-btn"
            :class="{ active: releaseTab === 'french-manga' }"
            type="button"
            @click="releaseTab = 'french-manga'"
          >
            french-manga.net
          </button>
          <button
            class="tab-btn"
            :class="{ active: releaseTab === 'voir-anime' }"
            type="button"
            @click="releaseTab = 'voir-anime'"
          >
            voir-anime.to
          </button>
          <button
            class="tab-btn"
            :class="{ active: releaseTab === 'animepahe' }"
            type="button"
            @click="releaseTab = 'animepahe'"
          >
            animepahe.pw (VO/Sub)
          </button>
          <button
            v-for="ext in enabledExtensions"
            :key="ext.id || ext.pkg"
            class="tab-btn"
            :class="{ active: releaseTab === String(ext.id || ext.pkg) }"
            type="button"
            @click="releaseTab = String(ext.id || ext.pkg)"
          >
            📦 {{ ext.name }}
          </button>
        </div>
      </div>

      <!-- Releases Content -->
      <div v-if="isLoadingReleases" class="empty-state">
        <div class="spinner"></div>
        <h3>Chargement des sorties...</h3>
      </div>

      <div v-else-if="currentReleases.length > 0" class="results-grid animate-fade-in">
        <article
          v-for="anime in currentReleases"
          :key="anime.url"
          class="anime-card"
        >
          <router-link
            :to="{ path: '/anime', query: { url: anime.url, source: anime.source || releaseTab } }"
            class="card-link"
          >
            <div class="card-poster">
              <img
                :src="anime.imageUrl"
                :alt="anime.title"
                loading="lazy"
                @error="onImgError"
              />
              <div class="card-overlay">
                <span v-if="anime.version" class="version-badge">{{ anime.version }}</span>
                <span v-if="anime.latestEpisode || anime.episodeInfo" class="ep-badge">
                  {{ anime.latestEpisode || anime.episodeInfo }}
                </span>
              </div>
            </div>
            <div class="card-info">
              <h3 class="card-title">{{ anime.title }}</h3>
              <span class="card-type">{{ anime.type || 'Anime' }}</span>
            </div>
          </router-link>
        </article>
      </div>

      <div v-else class="empty-state">
        <h3>Aucune sortie trouvée pour cette source</h3>
        <p>Actualisez le flux ou essayez une autre source ci-dessus.</p>
        <button class="btn btn-primary" style="margin-top: 12px;" @click="refreshFeed">Actualiser le flux</button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useAnimeStore } from '@/stores/anime';
import type { AnimeResult, FavoriteItem } from '@/types';

const animeStore = useAnimeStore();

const heroQuery = ref('');
const selectedSource = ref('french-manga');
const releaseTab = ref('french-manga');

const emit = defineEmits<{
  (e: 'open-palette', q?: string): void;
}>();

onMounted(() => {
  animeStore.fetchHomeFeed();
});

const isLoadingReleases = computed(() => {
  return animeStore.isLoading && !animeStore.homeFeed;
});

const enabledExtensions = computed(() => {
  return animeStore.homeFeed?.enabledExtensions || [];
});

const favorites = computed<FavoriteItem[]>(() => {
  return animeStore.homeFeed?.favorites || [];
});

const favoritesCount = computed(() => {
  return favorites.value.length;
});

const activeSourcesCount = computed(() => {
  return 3 + enabledExtensions.value.length;
});

const currentReleases = computed<AnimeResult[]>(() => {
  const feed = animeStore.homeFeed;
  if (!feed) return [];

  // Check normalized map first
  if (feed.latestReleases && feed.latestReleases[releaseTab.value]) {
    return feed.latestReleases[releaseTab.value];
  }

  // Fallback to direct keys
  if (releaseTab.value === 'french-manga') {
    return feed.latestFrenchManga || [];
  }
  if (releaseTab.value === 'voir-anime') {
    return feed.latestVoirAnime || [];
  }
  if (releaseTab.value === 'animepahe') {
    return feed.latestAnimePahe || [];
  }

  // Check extensions
  if (feed.extensionsReleases && feed.extensionsReleases[releaseTab.value]) {
    return feed.extensionsReleases[releaseTab.value].releases || [];
  }

  return [];
});

function emitOpenPalette() {
  emit('open-palette', heroQuery.value);
}

function onSearchSubmit() {
  if (heroQuery.value.trim()) {
    emit('open-palette', heroQuery.value.trim());
  } else {
    emitOpenPalette();
  }
}

function refreshFeed() {
  animeStore.fetchHomeFeed(true);
}

function onImgError(e: Event) {
  const target = e.target as HTMLImageElement;
  target.src = 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80';
}
</script>

<style scoped>
.home-container {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.spinner {
  width: 36px;
  height: 36px;
  border: 3px solid var(--panel-subtle);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin-bottom: 12px;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 48px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--muted);
  text-align: center;
}
</style>
