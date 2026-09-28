<template>
  <aside class="app-sidebar">
    <!-- Brand Logo & Name -->
    <router-link to="/" class="brand-mark" aria-label="Animan">
      <span class="brand-icon">
        <img src="/img/icon-192.png" alt="Animan Logo" class="brand-logo-img" />
      </span>
      <span class="brand-name">Ani<span>man</span></span>
    </router-link>

    <!-- Sidebar Menu -->
    <div class="sidebar-menu">
      <router-link to="/" class="side-link" active-class="active" exact-active-class="active">
        <svg viewBox="0 0 24 24"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/></svg>
        <span>{{ i18nStore.t('nav_home') || 'Accueil' }}</span>
      </router-link>

      <button type="button" class="side-link side-button" @click="emitOpenPalette">
        <svg viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
        <span>{{ i18nStore.t('nav_search') || 'Recherche' }}</span>
      </button>

      <router-link to="/downloads" class="side-link" active-class="active">
        <svg viewBox="0 0 24 24"><path d="M12 3v11"/><path d="m7 10 5 5 5-5"/><path d="M5 20h14"/></svg>
        <span>{{ i18nStore.t('nav_downloads') || 'Téléchargements' }}</span>
        <span v-if="downloadStore.stats.activeCount > 0" class="side-badge">
          {{ downloadStore.stats.activeCount }}
        </span>
      </router-link>

      <router-link to="/library" class="side-link" active-class="active">
        <svg viewBox="0 0 24 24"><rect x="4" y="5" width="16" height="15" rx="2"/><path d="M8 5V3h8v2"/><path d="M8 11h8"/></svg>
        <span>{{ i18nStore.t('nav_library') || 'Bibliothèque' }}</span>
      </router-link>

      <router-link to="/history" class="side-link" active-class="active">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/></svg>
        <span>{{ i18nStore.t('nav_history') || 'Historique' }}</span>
      </router-link>

      <router-link to="/extensions" class="side-link" active-class="active">
        <svg viewBox="0 0 24 24"><path d="M20.5 11H19V7c0-1.1-.9-2-2-2h-4V3.5a2.5 2.5 0 0 0-5 0V5H4c-1.1 0-1.99.9-1.99 2v3.8H3.5c1.49 0 2.7 1.21 2.7 2.7s-1.21 2.7-2.7 2.7H2V20c0 1.1.9 2 2 2h3.8v-1.5c0-1.49 1.21-2.7 2.7-2.7 1.49 0 2.7 1.21 2.7 2.7V22H17c1.1 0 2-.9 2-2v-4h1.5a2.5 2.5 0 0 0 0-5z"/></svg>
        <span>{{ i18nStore.t('nav_extensions') || 'Extensions' }}</span>
      </router-link>

      <router-link to="/settings" class="side-link" active-class="active">
        <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19 12a7 7 0 0 0-.1-1l2-1.5-2-3.4-2.4 1a7 7 0 0 0-1.8-1L14.4 3H9.6L9.2 6.1a7 7 0 0 0-1.8 1L5 6.1l-2 3.4L5 11a7 7 0 0 0 0 2l-2 1.5 2 3.4 2.4-1a7 7 0 0 0 1.8 1l.4 3.1h4.8l.4-3.1a7 7 0 0 0 1.8-1l2.4 1 2-3.4-2-1.5a7 7 0 0 0 .1-1Z"/></svg>
        <span>{{ i18nStore.t('nav_settings') || 'Paramètres' }}</span>
      </router-link>
    </div>
  </aside>
</template>

<script setup lang="ts">
import { useDownloadStore } from '@/stores/downloads';
import { useI18nStore } from '@/stores/i18n';

const downloadStore = useDownloadStore();
const i18nStore = useI18nStore();
const emit = defineEmits<{
  (e: 'open-palette', query?: string): void;
}>();

function emitOpenPalette() {
  emit('open-palette', '');
}
</script>
