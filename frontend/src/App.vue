<script setup lang="ts">
import { onMounted } from 'vue'
import { useStore } from './store'
import MapView from './components/MapView.vue'
import SidePanel from './components/SidePanel.vue'
import TerrainProfile from './components/TerrainProfile.vue'

const store = useStore()

onMounted(async () => {
  await store.loadCatalogs()
  await store.loadNodes()
  await store.loadLinks()
})
</script>

<template>
  <div class="app">
    <SidePanel />
    <div class="main-content">
      <MapView />
      <TerrainProfile v-if="store.terrainProfileOpen" />
    </div>
  </div>
</template>

<style>
@import url('https://unpkg.com/leaflet@1.9.4/dist/leaflet.css');

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

:root {
  --bg-primary: #161b22;
  --bg-secondary: #1a1a2e;
  --bg-tertiary: #21262d;
  --bg-input: #0d1117;
  --text-primary: #e6edf3;
  --text-secondary: #8b949e;
  --text-muted: #6e7681;
  --border-color: #30363d;
  --accent-green: #3fb950;
  --accent-blue: #58a6ff;
  --accent-orange: #d29922;
  --accent-red: #f85149;
  --accent-teal: #39d2c0;
  --sidebar-width: 360px;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
  background: var(--bg-primary);
  color: var(--text-primary);
  overflow: hidden;
  height: 100vh;
}

#app {
  height: 100vh;
}

.app {
  display: flex;
  height: 100vh;
  overflow: hidden;
}

.main-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  position: relative;
  overflow: hidden;
}

input, select, textarea {
  background: var(--bg-input);
  color: var(--text-primary);
  border: 1px solid var(--border-color);
  border-radius: 4px;
  padding: 6px 10px;
  font-size: 13px;
  outline: none;
}

input:focus, select:focus {
  border-color: var(--accent-blue);
}

button {
  cursor: pointer;
  border: none;
  border-radius: 4px;
  padding: 8px 16px;
  font-size: 13px;
  font-weight: 500;
  transition: opacity 0.2s;
}

button:hover {
  opacity: 0.85;
}

button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

::-webkit-scrollbar {
  width: 6px;
}

::-webkit-scrollbar-track {
  background: var(--bg-primary);
}

::-webkit-scrollbar-thumb {
  background: var(--border-color);
  border-radius: 3px;
}

@media (max-width: 900px) {
  .app {
    flex-direction: column;
  }
}
</style>
