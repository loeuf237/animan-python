import {defineConfig} from '@playwright/test';
export default defineConfig({
  testDir:'./tests/ui', testMatch:'*.spec.mjs', fullyParallel:true,
  workers:process.env.CI ? 2 : 3, timeout:30000, retries:process.env.CI ? 1 : 0,
  reporter:[['list'], ['html',{open:'never'}]],
  use:{baseURL:'http://127.0.0.1:5179', browserName:'chromium',
    launchOptions:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH ? {executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH} : {},
    trace:'retain-on-failure', screenshot:'only-on-failure', reducedMotion:'reduce', serviceWorkers:'block'},
  webServer:{command:'npm run dev -- --port 5179 --strictPort', url:'http://127.0.0.1:5179', reuseExistingServer:!process.env.CI},
});
