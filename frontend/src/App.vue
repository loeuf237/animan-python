<template>
  <div class="app-shell">
    <!-- Left Navigation Sidebar -->
    <AppSidebar />

    <!-- Top Action Bar -->
    <AppTopbar @open-palette="openPalette" />

    <!-- Main Content Area -->
    <main class="main-content">
      <NetworkVerificationPanel />
      <router-view v-slot="{ Component }">
        <transition name="fade" mode="out-in">
          <component :is="Component" @open-palette="openPalette" />
        </transition>
      </router-view>
    </main>

    <!-- Mobile Bottom Navigation -->
    <AppBottomNav />

    <!-- Universal Command Palette Modal (Ctrl + K) -->
    <CommandPaletteModal :is-open="isPaletteOpen" :initial-query="paletteQuery" @close="isPaletteOpen = false" />

    <!-- Global Video Streaming Modal -->
    <VideoPlayerModal />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue';
import NetworkVerificationPanel from '@/components/NetworkVerificationPanel.vue';
import AppSidebar from '@/components/AppSidebar.vue';
import AppTopbar from '@/components/AppTopbar.vue';
import AppBottomNav from '@/components/AppBottomNav.vue';
import CommandPaletteModal from '@/components/CommandPaletteModal.vue';
import VideoPlayerModal from '@/components/VideoPlayerModal.vue';
import { useDownloadStore } from '@/stores/downloads';
import { useI18nStore } from '@/stores/i18n';

const downloadStore = useDownloadStore();
const i18nStore = useI18nStore();
const isPaletteOpen = ref(false);
const paletteQuery = ref('');
function openPalette(query = '') { paletteQuery.value = query; isPaletteOpen.value = true; }

function onKeyDown(e: KeyboardEvent) {
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    if (e.repeat) return;
    if (isPaletteOpen.value) isPaletteOpen.value = false;
    else openPalette();
  }
}

onMounted(() => {
  // Initialize i18n
  i18nStore.init();

  // Listen for Ctrl+K
  window.addEventListener('keydown', onKeyDown);

  // Start real-time downloads SSE stream
  downloadStore.startSSE();
  downloadStore.fetchTasks();
});

onUnmounted(() => {
  window.removeEventListener('keydown', onKeyDown);
  downloadStore.stopSSE();
});
</script>

<style>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.15s ease;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
