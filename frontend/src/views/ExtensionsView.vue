<template>
  <div class="settings-page-layout fade-in" style="max-width: 1200px; margin: 0 auto; padding: 24px 20px;">
    <!-- En-tête -->
    <header class="page-header" style="margin-bottom: 28px; display: flex; justify-content: space-between; align-items: flex-start; flex-wrap: wrap; gap: 16px;">
      <div>
        <h1 class="page-title" style="display: flex; align-items: center; gap: 12px;">
          <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#a78bfa" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
            <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/>
            <polyline points="3.27 6.96 12 12.01 20.73 6.96"/>
            <line x1="12" y1="22.08" x2="12" y2="12"/>
          </svg>
          Gestionnaire d'Extensions Aniyomi
        </h1>
        <p class="page-sub">Installez et activez des extensions tierces pour étendre vos sources de streaming.</p>
      </div>

      <div style="display: flex; gap: 10px; align-items: center;">
        <span class="badge" style="background: rgba(139, 92, 246, 0.15); color: #c4b5fd; border: 1px solid rgba(139, 92, 246, 0.3); padding: 8px 14px; border-radius: 9999px; font-weight: 500;">
          <strong>{{ enabledCount }}</strong> / {{ totalCount }} sources actives
        </span>
      </div>
    </header>

    <!-- Carte d'importation d'un magasin -->
    <section class="settings-card-pro" style="margin-bottom: 28px; padding: 24px;">
      <div style="display: flex; align-items: center; gap: 12px; margin-bottom: 12px;">
        <div style="width: 40px; height: 40px; border-radius: 10px; background: rgba(139, 92, 246, 0.2); display: flex; align-items: center; justify-content: center; color: #a78bfa;">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 14.899A7 7 0 1 1 15.71 8h1.79a4.5 4.5 0 0 1 2.5 8.242"/><path d="M12 12v9"/><path d="m8 17 4 4 4-4"/></svg>
        </div>
        <div>
          <h2 style="font-size: 1.15rem; font-weight: 600; color: var(--text); margin: 0;">Magasin d'extensions Aniyomi</h2>
          <p style="font-size: 0.85rem; color: var(--muted); margin: 2px 0 0 0;">Ajoutez un dépôt pour synchroniser automatiquement les extensions de visionnage.</p>
        </div>
      </div>

      <!-- Barre d'import -->
      <form @submit.prevent="handleImportRepo" style="margin-top: 16px;">
        <div style="display: flex; gap: 10px; flex-wrap: wrap;">
          <input
            v-model="repoUrl"
            type="url"
            class="input-premium"
            style="flex: 1; min-width: 320px; padding: 12px 16px; font-size: 0.95rem;"
            placeholder="https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json"
            required
          />
          <button
            type="submit"
            class="btn btn-primary"
            :disabled="isImporting"
            style="padding: 12px 24px; font-weight: 600; display: flex; align-items: center; gap: 8px;"
          >
            <div v-if="isImporting" class="spinner-sm"></div>
            <span>{{ isImporting ? 'Importation en cours...' : 'Importer le magasin' }}</span>
          </button>
        </div>
      </form>

      <!-- Raccourcis Dépôts Populaires -->
      <div style="margin-top: 14px; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 0.85rem; color: #9ca3af;">
        <span>Dépôts recommandés :</span>
        <button
          type="button"
          class="speed-preset-chip"
          @click="setRepoPreset('https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json')"
        >
          ⚡ Yuzono Anime Repo (254 extensions)
        </button>
        <button
          type="button"
          class="speed-preset-chip"
          @click="setRepoPreset('https://raw.githubusercontent.com/keiyoushi/extensions/repo/index.min.json')"
        >
          📦 Keiyoushi Repo
        </button>
      </div>

      <!-- Message d'information de règles -->
      <div style="margin-top: 16px; padding: 10px 14px; background: rgba(59, 130, 246, 0.08); border-left: 3px solid #60a5fa; border-radius: 4px; font-size: 0.82rem; color: #bfdbfe;">
        ℹ️ <strong>Règle de visibilité :</strong> Seules les sources présentes dans le <strong>dernier magasin ajouté</strong> sont affichées ci-dessous. Par défaut, toutes les sources importées sont <strong>désactivées</strong> : activez manuellement uniquement celles que vous souhaitez utiliser dans la recherche et le streaming.
      </div>
    </section>

    <!-- Informations sur le magasin actuellement actif -->
    <div
      v-if="activeRepo"
      style="display: flex; justify-content: space-between; align-items: center; background: var(--panel); border: 1px solid var(--line); padding: 14px 20px; border-radius: 12px; margin-bottom: 20px; flex-wrap: wrap; gap: 10px;"
    >
      <div style="display: flex; align-items: center; gap: 10px;">
        <span style="display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #10b981; box-shadow: 0 0 8px #10b981;"></span>
        <div>
          <span style="font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: var(--muted);">Dépôt actif :</span>
          <strong style="color: var(--text); margin-left: 6px; font-size: 0.95rem;">{{ activeRepo.name }}</strong>
        </div>
      </div>
      <div style="font-size: 0.85rem; color: #9ca3af; display: flex; align-items: center; gap: 16px;">
        <span>Catalogue : {{ totalCount }} sources</span>
        <span>Actives : {{ enabledCount }}</span>
      </div>
    </div>

    <!-- Barre d'outils de filtrage & Recherche instantanée -->
    <div style="display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;">
      <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'all' }"
          @click="filterLang = 'all'"
        >
          Toutes ({{ totalCount }})
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'fr' }"
          @click="filterLang = 'fr'"
        >
          🇫🇷 Français ({{ frCount }})
        </button>
        <button
          type="button"
          class="tab-btn"
          :class="{ active: filterLang === 'active' }"
          @click="filterLang = 'active'"
        >
          Sources actives uniquement ({{ enabledCount }})
        </button>
      </div>

      <div style="position: relative; min-width: 260px; flex: 1; max-width: 360px;">
        <input
          v-model="searchQuery"
          type="text"
          class="input-premium"
          style="width: 100%; padding: 8px 12px 8px 36px; font-size: 0.9rem;"
          placeholder="Filtrer une extension par nom ou package..."
        />
        <svg style="position: absolute; left: 12px; top: 50%; transform: translateY(-50%); color: #9ca3af;" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/></svg>
      </div>
    </div>

    <!-- Loading spinner -->
    <div v-if="isLoading" class="loading-state" style="padding: 60px 20px; text-align: center;">
      <div class="spinner" style="margin: 0 auto 16px;"></div>
      <p style="color: var(--muted);">Chargement du catalogue des extensions...</p>
    </div>

    <!-- Grille des extensions compacte et fluide -->
    <div
      v-else-if="filteredExtensions.length > 0"
      class="results-grid"
      style="grid-template-columns: repeat(auto-fill, minmax(290px, 1fr)); gap: 10px;"
    >
      <article
        v-for="ext in filteredExtensions"
        :key="ext.id"
        class="ext-card ext-card-compact"
      >
        <div class="ext-compact-left">
          <img
            v-if="ext.icon_url || ext.iconUrl"
            :src="ext.icon_url || ext.iconUrl!"
            :alt="ext.name"
            class="ext-icon-sm"
            @error="(e) => (e.target as HTMLElement).style.display = 'none'"
          />
          <div v-else class="ext-avatar-sm">
            {{ ext.name ? ext.name[0].toUpperCase() : 'E' }}
          </div>

          <div style="flex: 1; min-width: 0;">
            <div style="display:flex;align-items:center;gap:6px;">
              <h3 class="ext-title-text" :title="ext.name">{{ ext.name }}</h3>
              <span
                class="version-badge"
                :style="{
                  fontSize: '0.68rem',
                  padding: '1px 5px',
                  background: ext.lang === 'fr' ? '#2563eb' : (ext.lang === 'all' ? '#7c3aed' : '#4b5563')
                }"
              >
                {{ (ext.lang || 'ALL').toUpperCase() }}
              </span>
            </div>
            <div style="display:flex;align-items:center;gap:8px;font-size:0.75rem;color:#9ca3af;margin-top:2px;">
              <span>v{{ ext.version || '1.0' }}</span>
              <template v-if="ext.base_url || ext.baseUrl">
                <span>•</span>
                <a
                  :href="ext.base_url || ext.baseUrl!"
                  target="_blank"
                  rel="noopener noreferrer"
                  style="color: #818cf8; text-decoration: none; overflow:hidden; text-overflow:ellipsis; max-width:120px; white-space:nowrap;"
                  :title="ext.base_url || ext.baseUrl!"
                >
                  {{ formatDomain(ext.base_url || ext.baseUrl!) }}
                </a>
              </template>
            </div>
          </div>
        </div>

        <div style="display: flex; align-items: center; gap: 8px; flex-shrink: 0;">
          <label class="toggle-switch">
            <input
              type="checkbox"
              :checked="isExtensionActive(ext)"
              @change="handleToggleExtension(ext, ($event.target as HTMLInputElement).checked)"
            />
            <span class="toggle-slider"></span>
          </label>
        </div>
      </article>
    </div>

    <!-- Empty State -->
    <div
      v-else
      class="empty-state"
      style="padding: 60px 20px; text-align: center; background: rgba(18, 22, 40, 0.4); border-radius: 16px; border: 1px dashed rgba(255,255,255,0.1);"
    >
      <div style="font-size: 2.5rem; margin-bottom: 12px;">📦</div>
      <h3 style="font-size: 1.25rem; font-weight: 600; color: #f3f4f6; margin-bottom: 6px;">
        {{ extensions.length === 0 ? "Aucun magasin d'extensions actif" : "Aucune extension ne correspond aux filtres" }}
      </h3>
      <p style="color: #9ca3af; max-width: 460px; margin: 0 auto 20px auto; font-size: 0.9rem;">
        {{ extensions.length === 0 ? "Importez un catalogue d'extensions Aniyomi ci-dessus pour afficher et activer vos sources d'animation préférées." : "Modifiez votre recherche ou sélectionnez un autre filtre de langue." }}
      </p>
      <button
        v-if="extensions.length === 0"
        type="button"
        class="btn btn-primary"
        @click="setRepoPreset('https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json'); handleImportRepo();"
      >
        ⚡ Importer Yuzono Anime Repo en 1 clic
      </button>
    </div>

    <!-- Notification Toast -->
    <div v-if="toastMessage" class="toast-notification" :class="`toast-${toastType}`">
      <span>{{ toastMessage }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue';
import { api } from '@/api/client';
import type { ExtensionSource } from '@/types';

const extensions = ref<ExtensionSource[]>([]);
const activeRepo = ref<any>(null);
const isLoading = ref(false);
const isImporting = ref(false);
const repoUrl = ref('https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json');

const filterLang = ref<'all' | 'fr' | 'active'>('all');
const searchQuery = ref('');

const toastMessage = ref<string | null>(null);
const toastType = ref<'success' | 'error' | 'info'>('info');
let toastTimer: any = null;

function showToast(msg: string, type: 'success' | 'error' | 'info' = 'info') {
  toastMessage.value = msg;
  toastType.value = type;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastMessage.value = null;
  }, 4000);
}

function formatDomain(url: string) {
  return url.replace('https://', '').replace('http://', '').replace(/\/$/, '');
}

function isExtensionActive(ext: ExtensionSource) {
  return Boolean(ext.is_enabled ?? ext.enabled);
}

const totalCount = computed(() => extensions.value.length);
const enabledCount = computed(() => extensions.value.filter(isExtensionActive).length);
const frCount = computed(() => extensions.value.filter((e) => (e.lang || '').toLowerCase() === 'fr').length);

const filteredExtensions = computed(() => {
  return extensions.value.filter((ext) => {
    // Filter by language / active tab
    if (filterLang.value === 'fr' && (ext.lang || '').toLowerCase() !== 'fr') {
      return false;
    }
    if (filterLang.value === 'active' && !isExtensionActive(ext)) {
      return false;
    }

    // Filter by search query
    if (searchQuery.value.trim()) {
      const q = searchQuery.value.trim().toLowerCase();
      const matchName = (ext.name || '').toLowerCase().includes(q);
      const matchPkg = (ext.pkg || '').toLowerCase().includes(q);
      if (!matchName && !matchPkg) return false;
    }

    return true;
  });
});

async function fetchExtensions() {
  isLoading.value = true;
  try {
    const res = await api.getExtensions();
    if (res) {
      activeRepo.value = res.active_repo || null;
      extensions.value = res.extensions || res.installed || [];
    }
  } catch (e: any) {
    showToast(e.message || 'Erreur lors du chargement des extensions.', 'error');
  } finally {
    isLoading.value = false;
  }
}

function setRepoPreset(url: string) {
  repoUrl.value = url;
}

async function handleImportRepo() {
  const url = repoUrl.value.trim();
  if (!url) return;

  isImporting.value = true;
  try {
    const res = await api.importExtensionRepo(url);
    showToast(`Dépôt "${res.repo_name || 'Aniyomi'}" importé avec succès (${res.count || 0} extensions) !`, 'success');
    await fetchExtensions();
  } catch (e: any) {
    showToast(e.message || "Échec de l'importation du dépôt.", 'error');
  } finally {
    isImporting.value = false;
  }
}

async function handleToggleExtension(ext: ExtensionSource, enabled: boolean) {
  try {
    await api.toggleExtension(ext.id, enabled);
    ext.enabled = enabled;
    ext.is_enabled = enabled;
    showToast(`${ext.name} ${enabled ? 'activée' : 'désactivée'}.`, 'success');
  } catch (e: any) {
    showToast(e.message || "Erreur lors de l'activation/désactivation de l'extension.", 'error');
  }
}

onMounted(() => {
  fetchExtensions();
});
</script>

<style scoped>
.toast-notification {
  position: fixed;
  bottom: 24px;
  right: 24px;
  padding: 12px 20px;
  border-radius: var(--radius-sm);
  background: rgba(15, 23, 42, 0.95);
  border: 1px solid var(--border-highlight);
  color: #fff;
  font-size: 0.9rem;
  font-weight: 600;
  box-shadow: 0 10px 30px rgba(0,0,0,0.5);
  z-index: 500;
  animation: slideUp 0.25s ease;
}

.toast-success {
  border-left: 4px solid #10b981;
}

.toast-error {
  border-left: 4px solid #ef4444;
}

.toast-info {
  border-left: 4px solid #6366f1;
}

@keyframes slideUp {
  from { transform: translateY(20px); opacity: 0; }
  to { transform: translateY(0); opacity: 1; }
}

.spinner-sm {
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  display: inline-block;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
