<template>
  <div class="anime-card" @click="goToDetail">
    <div class="anime-card-poster">
      <img
        :src="anime.imageUrl || '/static/placeholder.jpg'"
        :alt="anime.title"
        loading="lazy"
        @error="onImageError"
      />
      <div class="anime-card-overlay">
        <div class="play-action-icon">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor">
            <polygon points="5 3 19 12 5 21 5 3"></polygon>
          </svg>
        </div>
        <div class="top-badges">
          <span class="badge badge-source">{{ anime.source }}</span>
          <span v-if="anime.rating" class="badge badge-rating">
            ★ {{ Number(anime.rating).toFixed(1) }}
          </span>
        </div>
      </div>
    </div>
    <div class="anime-card-info">
      <h3 class="anime-card-title" :title="anime.title">{{ anime.title }}</h3>
      <div class="anime-card-meta">
        <span class="meta-tag">{{ anime.latestEpisode || anime.type || 'Animé' }}</span>
        <span v-if="anime.status" class="meta-status">{{ anime.status }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router';
import type { AnimeResult } from '@/types';

const props = defineProps<{
  anime: AnimeResult;
}>();

const router = useRouter();

function goToDetail() {
  router.push({
    path: '/anime',
    query: {
      url: props.anime.url,
      source: props.anime.source || 'french-manga',
    },
  });
}

function onImageError(event: Event) {
  const target = event.target as HTMLImageElement;
  target.src = 'https://images.unsplash.com/photo-1578632767115-351597cf2477?w=400&q=80';
}
</script>

<style scoped>
.top-badges {
  position: absolute;
  top: 10px;
  left: 10px;
  right: 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.play-action-icon {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%) scale(0.7);
  width: 46px;
  height: 46px;
  background: var(--accent-gradient);
  border-radius: var(--radius-full);
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  opacity: 0;
  transition: all var(--transition-normal);
  box-shadow: 0 0 20px rgba(99, 102, 241, 0.6);
}

.anime-card:hover .play-action-icon {
  opacity: 1;
  transform: translate(-50%, -50%) scale(1);
}

.meta-tag {
  color: var(--accent-secondary);
  font-weight: 500;
}

.meta-status {
  font-size: 0.75rem;
  color: var(--text-dim);
}
</style>
