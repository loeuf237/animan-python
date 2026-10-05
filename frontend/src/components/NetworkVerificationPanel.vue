<template>
  <VerificationPrompt :challenges="challenges" />
  <div v-if="verification.notice" class="verification-notice" role="status">
    {{ verification.notice }}
    <button class="btn btn-secondary" @click="verification.notice = ''">Masquer</button>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue';
import VerificationPrompt from './VerificationPrompt.vue';
import { useVerificationStore } from '@/stores/verification';
const verification = useVerificationStore();
const challenges = computed(() => verification.sessions.filter(s => s.verificationRequired).map(s => ({domain: s.domain, code: 'verification_required', error: 'Vérification nécessaire'})));
let timer: ReturnType<typeof setInterval>;
onMounted(() => { void verification.refresh(); timer = setInterval(() => void verification.refresh(), 10000); });
onUnmounted(() => clearInterval(timer));
</script>
<style scoped>
.verification-notice { padding: 12px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 16px; }
</style>
