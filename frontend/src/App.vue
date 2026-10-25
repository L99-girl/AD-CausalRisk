<template>
  <router-view />
</template>

<script setup>
</script>

<style>
body {
  margin: 0;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: var(--color-fill-2, #f5f7fa);
  transition: background-color 0.2s ease;
}

#app {
  min-height: 100vh;
}

* {
  box-sizing: border-box;
}
</style>