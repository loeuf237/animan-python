<template>
  <div v-if="playerStore.isOpen" class="player-overlay" @click.self="playerStore.closePlayer">
    <div class="player-modal glass-panel">
      <!-- Player Header -->
      <div class="player-header">
        <div class="header-info">
          <div style="display:flex;align-items:center;gap:8px;">
            <h2 class="anime-title">{{ tx(playerStore.animeTitle) }}</h2>
            <span v-if="playerStore.isDownloaded" class="local-badge" :title="tx('Fichier disponible sur le disque dur')">
              💾 Local
            </span>
          </div>
          <span class="episode-title"> {{ tx("Épisode") }} {{ tx(playerStore.currentEpisode?.number) }} - {{ tx(playerStore.currentEpisode?.title || 'Streaming') }}
          </span>
        </div>

        <!-- Controls: Server, Quality, Subtitles & Close -->
        <div class="header-actions">
          <!-- Subtitle Selector -->
          <div v-if="playerStore.subtitles.length > 0" class="select-group">
            <label>{{ tx("💬 Sous-titres :") }}</label>
            <select
              :value="playerStore.selectedSubtitle || ''"
              class="header-select"
              @change="onSubtitleChange($event)"
            >
              <option value="">{{ tx("Désactivés") }}</option>
              <option
                v-for="sub in playerStore.subtitles"
                :key="sub.src"
                :value="sub.src"
              >
                {{ tx(sub.label || 'Français') }}
              </option>
            </select>
          </div>

          <!-- Server Selector -->
          <div v-if="playerStore.availableServers.length > 1" class="select-group">
            <label>{{ tx("Serveur :") }}</label>
            <select
              :value="playerStore.selectedServer"
              class="header-select"
              @change="onServerChange($event)"
            >
              <option v-for="srv in playerStore.availableServers" :key="srv" :value="srv">
                {{ tx(srv) }}
              </option>
            </select>
          </div>

          <!-- Quality Selector -->
          <div v-if="hasQualities" class="select-group">
            <label>{{ tx("Qualité :") }}</label>
            <select
              :value="playerStore.selectedQuality"
              class="header-select"
              @change="onQualityChange($event)"
            >
              <option v-for="q in Object.keys(playerStore.availableQualities)" :key="q" :value="q">
                {{ tx(q) }}
              </option>
            </select>
          </div>

          <button class="btn-icon" :title="tx('Fermer (Échap)')" @click="playerStore.closePlayer">✕</button>
        </div>
      </div>

      <!-- Player Body -->
      <div class="player-body">
        <!-- Video element -->
        <video
          ref="videoRef"
          class="video-element"
          controls
          autoplay
          playsinline
          crossorigin="anonymous"
          @timeupdate="onTimeUpdate"
          @loadedmetadata="onMetadataLoaded"
        >
          <track
            v-for="(sub, i) in playerStore.subtitles"
            :key="sub.src || i"
            :kind="sub.kind || 'captions'"
            :label="tx(sub.label || 'Français')"
            :srclang="sub.srclang || 'fr'"
            :src="sub.src"
            :default="playerStore.selectedSubtitle === sub.src || (i === 0 && playerStore.selectedSubtitle !== '')"
          />
        </video>

        <!-- Loading overlay -->
        <div v-if="playerStore.isLoading" class="player-state-overlay">
          <div class="spinner"></div>
          <p>{{ tx("Résolution du flux vidéo...") }}</p>
        </div>

        <!-- Error overlay -->
        <div v-if="playerStore.error" class="player-state-overlay error">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <line x1="12" y1="8" x2="12" y2="12"></line>
            <line x1="12" y1="16" x2="12.01" y2="16"></line>
          </svg>
          <p>{{ tx(playerStore.error) }}</p>
          <button class="btn-primary" @click="playerStore.resolveStream"> {{ tx("Réessayer") }} </button>
        </div>
      </div>

      <!-- Player Footer (Episode Navigation) -->
      <div class="player-footer">
        <button
          class="btn-secondary"
          :disabled="!playerStore.hasPrev"
          @click="playerStore.playPrev"
        > {{ tx("⏮ Épisode précédent") }} </button>

        <span class="source-tag"> {{ tx("Source :") }} {{ tx(playerStore.source) }} • {{ tx(playerStore.serverType || 'Direct') }}
        </span>

        <button
          class="btn-primary"
          :disabled="!playerStore.hasNext"
          @click="playerStore.playNext"
        > {{ tx("Épisode suivant ⏭") }} </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale';
import { ref, watch, onMounted, onUnmounted, computed } from 'vue';
import Hls from 'hls.js';
import { usePlayerStore } from '@/stores/player';
import { useLibraryStore } from '@/stores/library';

const playerStore = usePlayerStore();
const libraryStore = useLibraryStore();

const videoRef = ref<HTMLVideoElement | null>(null);
let hlsInstance: Hls | null = null;
let markedWatched = false;

const hasQualities = computed(() => {
  return Object.keys(playerStore.availableQualities || {}).length > 1;
});

function syncSubtitleTracks() {
  if (!videoRef.value) return;
  const tracks = videoRef.value.textTracks;
  const targetSrc = playerStore.selectedSubtitle;

  for (let i = 0; i < tracks.length; i++) {
    const track = tracks[i];
    if (!targetSrc) {
      track.mode = 'disabled';
    } else {
      const sub = playerStore.subtitles[i];
      if (sub && sub.src === targetSrc) {
        track.mode = 'showing';
      } else {
        track.mode = 'disabled';
      }
    }
  }
}

function onSubtitleChange(e: Event) {
  const target = e.target as HTMLSelectElement;
  playerStore.changeSubtitle(target.value || null);
  syncSubtitleTracks();
}

function onMetadataLoaded() {
  syncSubtitleTracks();
}

function setupVideo(url: string | null) {
  if (!url || !videoRef.value) return;
  markedWatched = false;

  if (hlsInstance) {
    hlsInstance.destroy();
    hlsInstance = null;
  }

  const isHls = url.includes('.m3u8');

  if (isHls && Hls.isSupported()) {
    hlsInstance = new Hls({
      enableWorker: true,
      lowLatencyMode: true,
    });
    hlsInstance.loadSource(url);
    hlsInstance.attachMedia(videoRef.value);
    hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
      videoRef.value?.play().catch(() => {});
      syncSubtitleTracks();
    });
  } else {
    videoRef.value.src = url;
    videoRef.value.play().catch(() => {});
    syncSubtitleTracks();
  }
}

watch(
  () => playerStore.videoUrl,
  (newUrl) => {
    setupVideo(newUrl);
  }
);

watch(
  () => playerStore.subtitles,
  () => {
    setTimeout(syncSubtitleTracks, 100);
  },
  { deep: true }
);

function onServerChange(e: Event) {
  const target = e.target as HTMLSelectElement;
  playerStore.changeServer(target.value);
}

function onQualityChange(e: Event) {
  const target = e.target as HTMLSelectElement;
  playerStore.changeQuality(target.value);
}

function onTimeUpdate() {
  if (!videoRef.value || markedWatched) return;
  const current = videoRef.value.currentTime;
  const total = videoRef.value.duration;
  if (total > 0 && current / total >= 0.85) {
    markedWatched = true;
    if (playerStore.currentEpisode) {
      libraryStore.markWatched(playerStore.animeUrl, playerStore.currentEpisode.number, true, playerStore.currentEpisode.version || '', playerStore.animeTitle);
    }
  }
}

function onKeyDown(e: KeyboardEvent) {
  if (!playerStore.isOpen) return;
  if (e.key === 'Escape') {
    playerStore.closePlayer();
  } else if (e.key === ' ' && e.target === document.body) {
    e.preventDefault();
    if (videoRef.value) {
      if (videoRef.value.paused) videoRef.value.play();
      else videoRef.value.pause();
    }
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeyDown);
});

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown);
  if (hlsInstance) {
    hlsInstance.destroy();
  }
});
</script>

<style scoped>
.player-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.88);
  backdrop-filter: blur(10px);
  z-index: 300;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  animation: fadeIn 0.25s ease;
}

.player-modal {
  width: 100%;
  max-width: 1100px;
  max-height: 92vh;
  display: flex;
  flex-direction: column;
  background: rgba(14, 18, 30, 0.95);
  border: 1px solid var(--border-highlight);
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.8), var(--accent-glow);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.player-header {
  padding: 14px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid var(--border-subtle);
  flex-wrap: wrap;
  gap: 12px;
}

.header-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  overflow: hidden;
}

.anime-title {
  font-size: 1.15rem;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.local-badge {
  font-size: 0.72rem;
  background: rgba(16, 185, 129, 0.2);
  color: #34d399;
  border: 1px solid rgba(16, 185, 129, 0.3);
  padding: 2px 7px;
  border-radius: 9999px;
  font-weight: 600;
}

.episode-title {
  font-size: 0.85rem;
  color: var(--accent-secondary);
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.select-group {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  color: var(--text-muted);
}

.header-select {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-sm);
  color: var(--text-main);
  padding: 4px 8px;
  font-size: 0.82rem;
  outline: none;
}

.player-body {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-element {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.player-state-overlay {
  position: absolute;
  inset: 0;
  background: rgba(10, 13, 20, 0.9);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  color: var(--text-main);
}

.player-state-overlay.error {
  color: var(--color-danger);
}

.spinner {
  width: 44px;
  height: 44px;
  border: 3px solid rgba(99, 102, 241, 0.2);
  border-top-color: var(--accent-primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.player-footer {
  padding: 14px 20px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-top: 1px solid var(--border-subtle);
  flex-wrap: wrap;
  gap: 10px;
}

.source-tag {
  font-size: 0.82rem;
  color: var(--text-dim);
}
</style>
