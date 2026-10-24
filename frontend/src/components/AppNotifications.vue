<template>
  <div class="notification-region" aria-label="Notifications">
    <div
      v-for="item in notifications.items"
      :key="item.id"
      class="app-notification"
      :class="`notification-${item.tone}`"
      @mouseenter="notifications.pause(item.id)"
      @mouseleave="notifications.resume(item.id)"
      @focusin="notifications.pause(item.id)"
      @focusout="notifications.resume(item.id)"
    >
      <span :role="item.tone === 'error' ? 'alert' : 'status'">{{ tx(item.message) }}</span>
      <button
        v-if="item.action"
        type="button"
        class="btn btn-sm"
        :disabled="item.busy"
        @click="notifications.act(item.id)"
      >
        {{ tx(item.busy ? 'En cours…' : item.action.label) }}
      </button>
      <button
        type="button"
        class="notification-close"
        :aria-label="tx('Fermer la notification')"
        :disabled="item.busy"
        @click="notifications.dismiss(item.id)"
      >
        ×
      </button>
    </div>
  </div>
</template>
<script setup lang="ts">
import { tx } from '@/utils/locale'
import { useNotifications } from '@/stores/notifications'
const notifications = useNotifications()
</script>
