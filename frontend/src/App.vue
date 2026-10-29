<template>
  <router-view />
</template>

<script setup>
</script>

<style>
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: linear-gradient(135deg, #d4e8ff 0%, #e8f0fe 50%, #d9e2ec 100%) !important;
  transition: background-color 0.2s ease;
}

#app {
  min-height: 100vh;
  background: transparent !important;
}

* {
  box-sizing: border-box;
}
</style>