<template>
  <div class="sources-view">
    <div class="view-header">
      <div>
        <h1>Recherche & Catalogues</h1>
        <p class="subtitle">Explorez les catalogues multi-sources ou recherchez vos animés préférés.</p>
      </div>
    </div>

    <!-- Search Controls Bar -->
    <div class="search-bar-row glass-panel">
      <!-- Query input -->
      <div class="input-wrapper">
        <input
          v-model="query"
          type="text"
          placeholder="Titre d'animé (ex: Jujutsu Kaisen, Frieren)..."
          class="input-field"
          @keydown.enter="doSearch"
        />
      </div>

      <!-- Source selection -->
      <select v-model="selectedSource" class="source-select" @change="doSearch">
        <option value="all">Toutes les sources (Multi)</option>
        <option value="french-manga">French-Manga</option>
        <option value="voir-anime">VoirAnime</option>
        <option value="animepahe">AnimePahe</option>
        <option
          v-for="ext in enabledExtensions"
          :key="ext.id || ext.pkg"
          :value="ext.id || ext.pkg"
        >
          Extension: {{ ext.name }}
        </option>
      </select>

      <button class="btn-primary" @click="doSearch">
        Rechercher
      </button>
    </div>

    <!-- Results section -->
    <div class="results-section">
      <div v-if="animeStore.isLoading" class="loading-state">
        <div class="spinner"></div>
        <p>Recherche en cours sur les sources...</p>
      </div>

      <div v-else-if="animeStore.searchResults.length > 0" class="results-container">
        <div class="results-header">
          <h2>Résultats pour "{{ animeStore.searchQuery }}"</h2>
          <span class="badge badge-source">{{ animeStore.searchResults.length }} animés trouvés</span>
        </div>

        <div class="anime-grid">
          <AnimeCard
            v-for="anime in animeStore.searchResults"
            :key="anime.url"
            :anime="anime"
          />
        </div>
      </div>

      <div v-else-if="hasSearched" class="empty-state glass-panel">
        <p>Aucun résultat trouvé pour "{{ query }}".</p>
      </div>

      <div v-else class="initial-state glass-panel">
        <p>Entrez un terme de recherche ci-dessus pour interroger les catalogues disponibles.</p>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { useRoute } from 'vue-router';
import { useAnimeStore } from '@/stores/anime';
import AnimeCard from '@/components/AnimeCard.vue';

const route = useRoute();
const animeStore = useAnimeStore();

const query = ref('');
const selectedSource = ref('all');
const hasSearched = ref(false);

const enabledExtensions = computed(() => {
  return animeStore.homeFeed?.enabledExtensions || [];
});

onMounted(() => {
  if (!animeStore.homeFeed) {
    animeStore.fetchHomeFeed();
  }
  const q = route.query.q as string;
  if (q) {
    query.value = q;
    doSearch();
  }
});

async function doSearch() {
  if (!query.value.trim()) return;
  hasSearched.value = true;
  await animeStore.search(query.value.trim(), selectedSource.value);
}
</script>

<style scoped>
.sources-view {
  max-width: 1440px;
  margin: 0 auto;
  padding: 30px 24px 60px;
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.view-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.subtitle {
  color: var(--text-muted);
  font-size: 0.95rem;
}

.search-bar-row {
  display: flex;
  gap: 14px;
  padding: 16px 20px;
  align-items: center;
  flex-wrap: wrap;
}

.input-wrapper {
  flex: 1;
  min-width: 260px;
}

.source-select {
  padding: 12px 16px;
  background: rgba(16, 21, 34, 0.8);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  color: var(--text-main);
  font-size: 0.95rem;
  outline: none;
}

.results-section {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.results-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.anime-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(190px, 1fr));
  gap: 20px;
}

.empty-state,
.initial-state,
.loading-state {
  padding: 80px 20px;
  text-align: center;
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
}
</style>
