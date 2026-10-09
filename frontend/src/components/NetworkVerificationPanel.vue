<template>
  <div v-if="verification.notice" class="verification-notice" role="status">
    {{ tx(verification.notice) }}
    <button class="btn btn-secondary" @click="verification.notice = ''">{{ tx("Masquer") }}</button>
  </div>
</template>
<script setup lang="ts">
import { tx } from '@/utils/locale';
import { useVerificationStore } from '@/stores/verification';
const verification = useVerificationStore();
</script>
<style scoped>
.verification-notice { padding: 12px 16px; display: flex; align-items: center; gap: 12px; flex-wrap: wrap; border: 1px solid var(--border); border-radius: var(--radius); margin-bottom: 16px; }
</style>
