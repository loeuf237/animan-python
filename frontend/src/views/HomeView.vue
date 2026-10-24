<template>
  <div class="home-container">
    <!-- Hero Section -->
    <section class="hero fade-in compact-home-hero" id="search-panel">
      <div class="hero-panel">
        <h1 class="hero-title">{{ tx('Regardez vos animés sans interruption.') }}</h1>
        <p class="hero-subtitle">
          {{ tx('Recherchez, téléchargez et organisez vos séries préférées en VF et VOSTFR.') }}
        </p>

        <div class="home-search-actions">
          <SourceSelector
            v-model="selectedSource"
            :sources="sourceOptions"
            @update:model-value="preferences.setDefault"
          />
          <button type="button" class="btn btn-primary" @click="emitOpenPalette">
            {{ tx('Rechercher dans cette sélection') }}
          </button>
        </div>
      </div>

      <aside class="quick-panel">
        <div class="quick-row">
          <span>{{ tx('Favoris') }}</span>
          <strong>{{ tx(animeStore.homeFeed ? favoritesCount : '…') }}</strong>
        </div>
        <div class="quick-row">
          <span>{{ tx('Sources actives') }}</span>
          <strong style="color: var(--green)">{{
            tx(animeStore.homeFeed ? `${activeSourcesCount} actives` : 'Chargement…')
          }}</strong>
        </div>
        <div class="quick-row">
          <span>{{ tx('Téléchargements') }}</span>
          <router-link to="/downloads" class="btn btn-sm">{{
            tx('Ouvrir le gestionnaire')
          }}</router-link>
        </div>
      </aside>
    </section>

    <!-- Quick Favorites Section -->
    <section v-if="favorites.length > 0" class="section fade-in">
      <div
        style="
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 14px;
        "
      >
        <h2 class="section-title" style="margin: 0">
          <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg>
          {{ tx('Accès rapide aux favoris') }}
        </h2>
        <router-link to="/library" class="btn btn-sm" style="color: var(--accent)">{{
          tx('Voir tout')
        }}</router-link>
      </div>
      <div class="results-grid">
        <article v-for="fav in favorites.slice(0, 10)" :key="fav.url" class="anime-card">
          <router-link
            :to="{ path: '/anime', query: { url: fav.url, source: fav.source || 'french-manga' } }"
            class="card-link"
          >
            <div class="card-poster">
              <img :src="fav.imageUrl" :alt="tx(fav.title)" loading="lazy" />
              <div class="card-overlay">
                <span class="fav-badge">{{ tx('Favori') }}</span>
                <span v-if="fav.autoDownload" class="chip chip-auto">Auto-DL</span>
              </div>
            </div>
            <div class="card-info">
              <h3 class="card-title">{{ tx(fav.title) }}</h3>
              <span class="card-sub">{{ tx(fav.source || 'french-manga') }}</span>
            </div>
          </router-link>
        </article>
      </div>
    </section>

    <!-- Latest Releases Section with Tabs -->
    <section class="section fade-in">
      <p v-if="animeStore.error" role="alert">
        {{ tx(animeStore.error) }}
        <button class="btn" @click="refreshFeed">{{ tx('Réessayer') }}</button>
      </p>
      <div class="releases-tabs-header">
        <h2 class="section-title">
          <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5" /></svg> {{ tx('Dernières Sorties') }}
        </h2>
        <SourceSelector
          v-model="releaseTab"
          @update:model-value="preferences.setDefault"
          :sources="sourceOptions"
          :label="tx('Sorties de')"
          :include-all="false"
        />
      </div>

      <p v-if="feedChallenges.length" class="source-feed-notice">
        {{
          tx(
            'Cette source demande une vérification. Lancez une recherche pour voir les options d’accès.',
          )
        }}
        <button class="btn btn-secondary btn-sm" @click="emit('open-palette', '', releaseTab)">
          {{ tx('Rechercher') }}
        </button>
      </p>
      <p v-for="warning in feedErrors" :key="warning.source" role="alert">
        {{ tx(warning.message) }}
        <a v-if="warning.url" :href="warning.url" target="_blank" rel="noopener noreferrer">{{
          tx('Ouvrir le site')
        }}</a>
        <button class="btn" @click="refreshFeed">{{ tx('Réessayer') }}</button>
        <ProxyRotationButton v-if="warning.domain" :domain="warning.domain" :retry="refreshFeed" />
      </p>
      <!-- Releases Content -->
      <div v-if="isLoadingReleases" class="empty-state">
        <div class="spinner"></div>
        <h3>{{ tx('Chargement des sorties...') }}</h3>
      </div>

      <div v-else-if="currentReleases.length > 0" class="results-grid animate-fade-in">
        <article v-for="anime in currentReleases" :key="anime.url" class="anime-card">
          <router-link
            :to="{ path: '/anime', query: { url: anime.url, source: anime.source || releaseTab } }"
            class="card-link"
          >
            <div class="card-poster">
              <img
                :src="anime.imageUrl"
                :alt="tx(anime.title)"
                loading="lazy"
                @error="onImgError"
              />
              <div class="card-overlay">
                <span v-if="anime.version" class="version-badge">{{ tx(anime.version) }}</span>
                <span v-if="anime.latestEpisode || anime.episodeInfo" class="ep-badge">
                  {{ tx(anime.latestEpisode || anime.episodeInfo) }}
                </span>
              </div>
            </div>
            <div class="card-info">
              <h3 class="card-title">{{ tx(anime.title) }}</h3>
              <span class="card-type">{{ tx(anime.type || 'Anime') }}</span>
            </div>
          </router-link>
        </article>
      </div>

      <div
        v-else-if="!feedChallenges.length && !feedErrors.length && !animeStore.error"
        class="empty-state"
      >
        <h3>{{ tx('Aucune sortie trouvée pour cette source') }}</h3>
        <p>{{ tx('Actualisez le flux ou essayez une autre source ci-dessus.') }}</p>
        <button class="btn btn-primary" style="margin-top: 12px" @click="refreshFeed">
          {{ tx('Actualiser le flux') }}
        </button>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { language, tx } from '@/utils/locale'
import { ref, computed, watch, onMounted, onActivated } from 'vue'
import { useSourcePreferences } from '@/stores/sourcePreferences'
import SourceSelector from '@/components/SourceSelector.vue'
import ProxyRotationButton from '@/components/ProxyRotationButton.vue'
import { useAnimeStore } from '@/stores/anime'
import type { AnimeResult, FavoriteItem } from '@/types'

defineOptions({ name: 'HomeView' })
const animeStore = useAnimeStore()
let firstActivation = true
onActivated(() => {
  if (firstActivation) firstActivation = false
  else if (!animeStore.homeFeed) void animeStore.fetchHomeFeed()
})

const preferences = useSourcePreferences()
const selectedSource = ref(preferences.defaultSource)
const releaseTab = ref(
  preferences.defaultSource === 'all'
    ? language.value === 'en'
      ? 'animepahe'
      : 'french-manga'
    : preferences.defaultSource,
)
watch(
  () => preferences.defaultSource,
  (source) => {
    selectedSource.value = source
    if (source !== 'all') releaseTab.value = source
  },
)

const emit = defineEmits<{
  (e: 'open-palette', q?: string, source?: string): void
}>()

onMounted(() => {
  animeStore.fetchHomeFeed()
})

const isLoadingReleases = computed(() => {
  return animeStore.isLoading && !animeStore.homeFeed
})

const enabledExtensions = computed(() => {
  return animeStore.homeFeed?.enabledExtensions || []
})

const favorites = computed<FavoriteItem[]>(() => {
  return animeStore.homeFeed?.favorites || []
})

const favoritesCount = computed(() => {
  return favorites.value.length
})

const activeSourcesCount = computed(() => {
  return 3 + enabledExtensions.value.length
})

const feedChallenges = computed(() =>
  (animeStore.homeFeed?.challenges || []).filter((c) => c.source === releaseTab.value),
)
const feedErrors = computed(() =>
  (animeStore.homeFeed?.errors || []).filter((c) => c.source === releaseTab.value),
)
const currentReleases = computed<AnimeResult[]>(() => {
  const feed = animeStore.homeFeed
  if (!feed) return []

  // Check normalized map first
  if (feed.latestReleases && feed.latestReleases[releaseTab.value]) {
    return feed.latestReleases[releaseTab.value]
  }

  // Fallback to direct keys
  if (releaseTab.value === 'french-manga') {
    return feed.latestFrenchManga || []
  }
  if (releaseTab.value === 'voir-anime') {
    return feed.latestVoirAnime || []
  }
  if (releaseTab.value === 'animepahe') {
    return feed.latestAnimePahe || []
  }

  // Check extensions
  if (feed.extensionsReleases && feed.extensionsReleases[releaseTab.value]) {
    return feed.extensionsReleases[releaseTab.value].releases || []
  }

  return []
})

const sourceOptions = computed(() => [
  { id: 'french-manga', name: 'French-Manga' },
  { id: 'voir-anime', name: 'VoirAnime' },
  { id: 'animepahe', name: 'AnimePahe' },
  ...enabledExtensions.value
    .filter((ext) => ext.supportsLatest !== false)
    .map((ext) => ({ id: String(ext.id || ext.pkg), name: ext.name.replace(/^Aniyomi:\s*/i, '') })),
])
function emitOpenPalette() {
  emit('open-palette', '', selectedSource.value)
}

async function refreshFeed() {
  await animeStore.fetchHomeFeed(true)
}

function onImgError(e: Event) {
  const target = e.target as HTMLImageElement
  target.src = 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80'
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
  to {
    transform: rotate(360deg);
  }
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
