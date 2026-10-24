<template>
  <nav class="bottom-nav" :aria-label="tx('Navigation mobile')">
    <router-link to="/" class="bottom-nav-link" active-class="active" exact-active-class="active">
      <svg viewBox="0 0 24 24">
        <path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z" />
      </svg>
      <span>{{ tx('Accueil') }}</span>
    </router-link>

    <router-link to="/sources" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24">
        <rect x="3" y="3" width="7" height="7" rx="1" />
        <rect x="14" y="3" width="7" height="7" rx="1" />
        <rect x="3" y="14" width="7" height="7" rx="1" />
        <rect x="14" y="14" width="7" height="7" rx="1" />
      </svg>
      <span>Sources</span>
    </router-link>

    <router-link to="/downloads" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24">
        <path d="M12 3v11" />
        <path d="m7 10 5 5 5-5" />
        <path d="M5 20h14" />
      </svg>
      <span>{{ tx('Téléchargements') }}</span>
      <span v-if="downloadStore.stats.activeCount > 0" class="bottom-nav-badge">
        {{ tx(downloadStore.stats.activeCount) }}
      </span>
    </router-link>

    <router-link to="/library" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24">
        <rect x="4" y="5" width="16" height="15" rx="2" />
        <path d="M8 5V3h8v2" />
        <path d="M8 11h8" />
      </svg>
      <span>{{ tx('Bibliothèque') }}</span>
    </router-link>
  </nav>
</template>

<script setup lang="ts">
import { tx } from '@/utils/locale'
import { useDownloadStore } from '@/stores/downloads'

const downloadStore = useDownloadStore()
</script>
