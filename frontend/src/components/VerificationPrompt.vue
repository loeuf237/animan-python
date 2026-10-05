<template>
  <section v-if="challenges.length" class="verification-prompt" aria-label="Vérification Cloudflare">
    <strong>Cloudflare demande une vérification</strong>
    <p>Ouvrez la fenêtre, validez le CAPTCHA si demandé, puis confirmez ici. Les cookies seront récupérés et la recherche sera relancée automatiquement.</p>
    <div v-for="challenge in unique" :key="challenge.domain" class="verification-actions">
      <span>{{ challenge.domain }}</span>
      <template v-if="verification.job?.domain === challenge.domain">
        <button class="btn btn-primary" :disabled="verification.busy" @click="verification.complete">J’ai terminé la vérification</button>
        <button class="btn btn-secondary" :disabled="verification.busy" @click="verification.cancel">Fermer la fenêtre</button>
      </template>
      <template v-else>
        <select v-model="verification.browser" aria-label="Navigateur installé pour la vérification">
          <option v-for="item in verification.browsers" :key="item.name" :value="item.name">{{ item.name }}</option>
        </select>
        <button class="btn btn-primary" :disabled="verification.busy || !!verification.job || !verification.browsers.length" @click="verification.start(challenge.domain)">Ouvrir une fenêtre de vérification</button>
        <button v-if="verification.webviewAvailable && !verification.sessions.find(s => s.domain === challenge.domain)?.usesProxy" class="btn btn-secondary" :disabled="verification.busy || !!verification.job" @click="verification.start(challenge.domain, 'webview')">WebView (expérimental)</button>
        <span v-if="!verification.browsers.length">Aucun navigateur compatible détecté sur la machine du serveur.</span>
      </template>
    </div>
    <p v-if="verification.error" role="alert">{{ verification.error }}</p>
    <p v-if="verification.job && !unique.some(c => c.domain === verification.job?.domain)">
      Une vérification est déjà ouverte pour {{ verification.job.domain }}.
      <button class="btn btn-secondary" :disabled="verification.busy" @click="verification.cancel">Fermer cette vérification</button>
    </p>
  </section>
</template>
<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useVerificationStore } from '@/stores/verification';
import type { SourceChallenge } from '@/types';
const props = defineProps<{challenges: SourceChallenge[]}>();
const verification = useVerificationStore();
const unique = computed(() => props.challenges.filter((c, i, all) => all.findIndex(x => x.domain === c.domain) === i));
onMounted(() => { void verification.refresh(); });
</script>
<style scoped>
.verification-prompt { padding: 16px; border: 1px solid var(--yellow, #d9a441); border-radius: var(--radius, 12px); background: var(--panel); }
.verification-prompt p { margin: 10px 0; color: var(--muted); line-height: 1.5; }
.verification-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; margin-top: 12px; }
.verification-actions select { max-width: 200px; }
</style>
