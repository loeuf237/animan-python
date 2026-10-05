<template>
  <nav class="bottom-nav" aria-label="Navigation mobile">
    <router-link to="/" class="bottom-nav-link" active-class="active" exact-active-class="active">
      <svg viewBox="0 0 24 24"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/></svg>
      <span>Accueil</span>
    </router-link>

    <router-link to="/sources" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>
      <span>Sources</span>
    </router-link>

    <router-link to="/downloads" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24"><path d="M12 3v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/></svg>
      <span>Téléchargements</span>
      <span v-if="downloadStore.stats.activeCount > 0" class="bottom-nav-badge">
        {{ downloadStore.stats.activeCount }}
      </span>
    </router-link>

    <router-link to="/library" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 5V3h8v2"/><path d="M8 11h8"/></svg>
      <span>Bibliothèque</span>
    </router-link>

    <router-link to="/extensions" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24"><path d="M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5a2.5 2.5 0 0 0-5 0V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7 1.49 0 2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5a2.5 2.5 0 0 0 0-5z"/></svg>
      <span>Extensions</span>
    </router-link>

    <router-link to="/settings" class="bottom-nav-link" active-class="active">
      <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3H9.6L9.2 6.1a7 7 0 0 0-1.8 1L5 6.1l-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.4 3.1h4.8l.4-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"/></svg>
      <span>Paramètres</span>
    </router-link>
  </nav>
</template>

<script setup lang="ts">
import { useDownloadStore } from '@/stores/downloads';

const downloadStore = useDownloadStore();
</script>
