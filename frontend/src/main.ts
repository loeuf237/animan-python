import { createApp } from 'vue'
import { createPinia } from 'pinia'
import router from './router'
import './style.css'
import App from './App.vue'

const app = createApp(App)
const pinia = createPinia()

app.use(pinia)
app.use(router)

app.mount('#app')

// Legacy pages registered the PWA worker; a SPA-only visit must also check for
// its updates. Never reload automatically while a user is watching or editing.
if ('serviceWorker' in navigator) {
  navigator.serviceWorker
    .getRegistration('/')
    .then((registration) => registration?.update())
    .catch((error) => console.warn('[AnimeLab] Service worker update failed', error))
}
