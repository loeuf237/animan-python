<template>
  <div class="library-container">
    <div class="page-header">
      <div>
        <h1 class="page-title">Ma Bibliothèque</h1>
        <p class="page-sub">Gérez vos séries favorites et la surveillance automatique des nouveaux épisodes.</p>
      </div>

      <div style="display: flex; gap: 10px;">
        <button
          v-if="favorites.length > 0"
          class="btn btn-danger"
          @click="clearAll"
        >
          Tout effacer
        </button>
        <button class="btn btn-primary" @click="libraryStore.fetchFavorites">
          Actualiser
        </button>
      </div>
    </div>

    <!-- Stats Bar -->
    <div class="stats-grid" style="margin-bottom: 24px;">
      <div class="stat-card">
        <strong>{{ favorites.length }}</strong>
        <span>Séries suivies</span>
      </div>
      <div class="stat-card stat-blue">
        <strong>{{ autoDownloadCount }}</strong>
        <span>Téléchargement auto actif</span>
      </div>
      <div class="stat-card stat-green">
        <strong>{{ distinctSourcesCount }}</strong>
        <span>Sources représentées</span>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="!libraryStore.isLoading && favorites.length === 0" class="empty-state">
      <h3>Aucun animé dans votre bibliothèque</h3>
      <p>Parcourez les sorties ou utilisez la recherche pour ajouter des séries en favoris.</p>
      <router-link to="/" class="btn btn-primary" style="margin-top: 14px;">Découvrir les animés</router-link>
    </div>

    <!-- Favorites Grid -->
    <div v-else class="results-grid animate-fade-in">
      <article
        v-for="fav in favorites"
        :key="fav.url"
        class="anime-card"
      >
        <router-link
          :to="{ path: '/anime', query: { url: fav.url, source: fav.source || 'french-manga' } }"
          class="card-link"
        >
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

        <!-- Card Footer Actions -->
        <div style="display: flex; justify-content: space-between; align-items: center; padding: 10px 14px; border-top: 1px solid var(--line);">
          <label style="display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); cursor: pointer;">
            <input
              type="checkbox"
              :checked="fav.autoDownload"
              @change="toggleAuto(fav)"
            />
            <span>Auto-DL</span>
          </label>

          <button
            class="icon-button"
            style="width: 32px; height: 32px;"
            title="Supprimer des favoris"
            @click="removeFav(fav)"
          >
            ✕
          </button>
        </div>
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useLibraryStore } from '@/stores/library';
import type { FavoriteItem } from '@/types';

const libraryStore = useLibraryStore();

onMounted(() => {
  libraryStore.fetchFavorites();
});

const favorites = computed<FavoriteItem[]>(() => {
  return libraryStore.favorites;
});

const autoDownloadCount = computed(() => {
  return favorites.value.filter((f) => f.autoDownload).length;
});

const distinctSourcesCount = computed(() => {
  const s = new Set(favorites.value.map((f) => f.source));
  return s.size;
});

function toggleAuto(fav: FavoriteItem) {
  libraryStore.toggleAutoDownload(fav.url, fav.autoDownload);
}

function removeFav(fav: FavoriteItem) {
  libraryStore.toggleFavorite({
    url: fav.url,
    title: fav.title,
    imageUrl: fav.imageUrl,
    source: fav.source,
  });
}

async function clearAll() {
  if (confirm('Voulez-vous vraiment vider votre bibliothèque ?')) {
    await libraryStore.clearAllFavorites();
  }
}
</script>

<style scoped>
.library-container {
  display: flex;
  flex-direction: column;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  color: var(--muted);
  text-align: center;
}
</style>
