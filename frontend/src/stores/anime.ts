import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { AnimeDetailResponse, AnimeResult, HomeFeedResponse } from '@/types';

export const useAnimeStore = defineStore('anime', () => {
  const homeFeed = ref<HomeFeedResponse | null>(null);
  const currentDetail = ref<AnimeDetailResponse | null>(null);
  const searchResults = ref<AnimeResult[]>([]);
  const searchQuery = ref('');
  const selectedSource = ref('all');
  const isLoading = ref(false);
  const isDetailLoading = ref(false);
  const error = ref<string | null>(null);

  async function fetchHomeFeed(force = false) {
    if (homeFeed.value && !force) return;
    isLoading.value = true;
    error.value = null;
    try {
      homeFeed.value = await api.getHomeFeed();
    } catch (err: any) {
      error.value = err.message || 'Impossible de charger le flux';
      console.error('[useAnimeStore] fetchHomeFeed error:', err);
    } finally {
      isLoading.value = false;
    }
  }

  async function search(query: string, source: string = 'all') {
    searchQuery.value = query;
    selectedSource.value = source;
    if (!query.trim()) {
      searchResults.value = [];
      return;
    }

    isLoading.value = true;
    error.value = null;
    try {
      searchResults.value = await api.searchAnime(query, source);
    } catch (err: any) {
      error.value = err.message || 'Erreur lors de la recherche';
      console.error('[useAnimeStore] search error:', err);
    } finally {
      isLoading.value = false;
    }
  }

  async function fetchAnimeDetail(url: string, source: string = 'french-manga') {
    isDetailLoading.value = true;
    error.value = null;
    try {
      const res = await api.getAnimeDetail(url, source);
      currentDetail.value = res;
      return res;
    } catch (err: any) {
      error.value = err.message || "Impossible de charger la fiche de l'animé";
      console.error('[useAnimeStore] fetchAnimeDetail error:', err);
      throw err;
    } finally {
      isDetailLoading.value = false;
    }
  }

  function clearDetail() {
    currentDetail.value = null;
  }

  return {
    homeFeed,
    currentDetail,
    searchResults,
    searchQuery,
    selectedSource,
    isLoading,
    isDetailLoading,
    error,
    fetchHomeFeed,
    search,
    fetchAnimeDetail,
    clearDetail,
  };
});
