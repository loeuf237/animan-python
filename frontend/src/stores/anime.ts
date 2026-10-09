import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { AnimeDetailResponse, AnimeResult, HomeFeedResponse } from '@/types';
import type { SourceChallenge } from '@/types';
import { useVerificationStore, challengeFromError } from './verification';

export const useAnimeStore = defineStore('anime', () => {
  const homeFeed = ref<HomeFeedResponse | null>(null);
  const currentDetail = ref<AnimeDetailResponse | null>(null);
  const searchResults = ref<AnimeResult[]>([]);
  const searchQuery = ref('');
  const selectedSource = ref('all');
  const isLoading = ref(false);
  const isDetailLoading = ref(false);
  const error = ref<string | null>(null);
  const searchChallenges = ref<SourceChallenge[]>([]);
  const searchWarnings = ref<{source: string; message: string; url?: string; domain?: string}[]>([]);
  let searchSequence = 0;

  async function fetchHomeFeed(force = false) {
    if (homeFeed.value && !force) return;
    isLoading.value = true;
    error.value = null;
    try {
      homeFeed.value = await api.getHomeFeed();
      useVerificationStore().waitForVerification('home-feed', homeFeed.value.challenges || [], async () => { await fetchHomeFeed(true); });
    } catch (err: any) {
      error.value = err.message || 'Impossible de charger le flux';
      console.error('[useAnimeStore] fetchHomeFeed error:', err);
    } finally {
      isLoading.value = false;
    }
  }

  async function search(query: string, source: string = 'all') {
    const sequence = ++searchSequence;
    const verification = useVerificationStore();
    verification.clearPending('anime-search');
    searchChallenges.value = [];
    searchWarnings.value = [];
    searchQuery.value = query;
    selectedSource.value = source;
    if (!query.trim()) {
      searchResults.value = [];
      isLoading.value = false;
      error.value = null;
      return;
    }

    isLoading.value = true;
    error.value = null;
    try {
      const response = await api.searchAnimeDetailed(query, source);
      if (sequence !== searchSequence) return;
      searchResults.value = response.results;
      searchChallenges.value = response.challenges;
      searchWarnings.value = response.errors;
      verification.waitForVerification('anime-search', [...response.challenges, ...response.errors.flatMap(e => e.domain ? [{domain: e.domain}] : [])], async () => {
        if (sequence === searchSequence) await search(query, source);
      });
    } catch (err: any) {
      if (sequence !== searchSequence) return;
      searchResults.value = [];
      const challenge = challengeFromError(err);
      if (challenge) {
        searchChallenges.value = [challenge];
        verification.waitForVerification('anime-search', [challenge], async () => {
          if (sequence === searchSequence) await search(query, source);
        });
      }
      error.value = err.message || 'Erreur lors de la recherche';
      console.error('[useAnimeStore] search error:', err);
    } finally {
      if (sequence === searchSequence) isLoading.value = false;
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
    searchChallenges, searchWarnings,
    fetchHomeFeed,
    search,
    fetchAnimeDetail,
    clearDetail,
  };
});
