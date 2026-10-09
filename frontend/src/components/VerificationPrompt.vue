<template>
  <section v-if="challenges.length" class="verification-prompt" :aria-label="tx('Accès au site bloqué')">
    <strong>{{ tx("Le site demande une vérification ou bloque l’accès") }}</strong>
    <p>{{ tx("Ouvrez le site, effectuez la vérification si elle est proposée, puis revenez dans Animan pour réessayer. Une visite manuelle ne transfère pas automatiquement les cookies à l’application.") }}</p>
    <div v-for="challenge in unique" :key="challenge.domain" class="verification-actions">
      <a class="verification-site-link" :href="siteUrl(challenge)" target="_blank" rel="noopener noreferrer">{{ tx("Ouvrir dans un nouvel onglet") }}<template v-if="currentBrowser.name"> ({{ currentBrowser.name }})</template> : {{ siteUrl(challenge) }}</a>
      <button class="btn btn-secondary" :disabled="verification.busy" @click="verification.retry(challenge.domain)">{{ tx("Je suis revenu, réessayer") }}</button>
      <ProxyRotationButton :domain="challenge.domain" :retry="() => verification.retry(challenge.domain)" />
      <template v-if="verification.job?.domain === challenge.domain">
        <button class="btn btn-primary" :disabled="verification.busy" @click="verification.complete">{{ tx("J’ai terminé la vérification") }}</button>
        <button class="btn btn-secondary" :disabled="verification.busy" @click="verification.cancel">{{ tx("Fermer la fenêtre") }}</button>
      </template>
      <details v-else class="managed-verification"><summary>{{ tx('Récupérer les cookies avec une fenêtre de vérification') }}</summary><div class="verification-actions">
        <select v-model="verification.browser" :aria-label="tx('Navigateur installé pour la vérification')">
          <option v-for="item in verification.browsers" :key="item.name" :value="item.name">{{ tx(item.name) }}</option>
        </select>
        <button class="btn btn-primary" :disabled="verification.busy || !!verification.job || !verification.browsers.length" @click="verification.start(challenge.domain)">{{ tx("Ouvrir une fenêtre de vérification") }}</button>
        <button v-if="verification.webviewAvailable && !verification.sessions.find(s => s.domain === challenge.domain)?.usesProxy" class="btn btn-secondary" :disabled="verification.busy || !!verification.job" @click="verification.start(challenge.domain, 'webview')">{{ tx("WebView (expérimental)") }}</button>
        <span v-if="!verification.browsers.length">{{ tx("Aucun navigateur compatible détecté sur la machine du serveur.") }}</span>
      </div></details>
    </div>
    <p>{{ tx("La fenêtre de vérification d’Animan permet de récupérer les cookies après validation.") }}</p>
    <p v-if="verification.error" role="alert">{{ tx(verification.error) }}</p>
    <p v-if="verification.job && !unique.some(c => c.domain === verification.job?.domain)"> {{ tx("Une vérification est déjà ouverte pour") }} {{ tx(verification.job.domain) }}.
      <button class="btn btn-secondary" :disabled="verification.busy" @click="verification.cancel">{{ tx("Fermer cette vérification") }}</button>
    </p>
  </section>
</template>
<script setup lang="ts">
import { tx } from '@/utils/locale';
import { computed, onMounted } from 'vue';
import { useVerificationStore } from '@/stores/verification';
import type { SourceChallenge } from '@/types';
import ProxyRotationButton from './ProxyRotationButton.vue';
import { detectBrowser } from '@/utils/browser';
const currentBrowser = detectBrowser(navigator.userAgent);
const props = defineProps<{challenges: SourceChallenge[]}>();
const verification = useVerificationStore();
function siteUrl(challenge: SourceChallenge) {
  try {
    const url = new URL(challenge.url || `https://${challenge.domain}/`);
    if (['http:', 'https:'].includes(url.protocol) && url.hostname === challenge.domain && !url.username && !url.password) return url.href;
  } catch { /* Use the known source domain. */ }
  return `https://${challenge.domain}/`;
}
const unique = computed(() => props.challenges.filter((c, i, all) => all.findIndex(x => x.domain === c.domain) === i));
onMounted(() => { void verification.refresh(); });
</script>
<style scoped>
.verification-prompt { padding: 16px; border: 1px solid var(--yellow, #d9a441); border-radius: var(--radius, 12px); background: var(--panel); }
.verification-prompt p { margin: 10px 0; color: var(--muted); line-height: 1.5; }
.verification-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.verification-site-link { width: 100%; overflow-wrap: anywhere; }
.verification-actions select { max-width: 200px; }
.managed-verification { width: 100%; color: var(--muted); }
.managed-verification summary { cursor: pointer; }
</style>
