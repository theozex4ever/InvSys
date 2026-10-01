import { defineConfig } from 'vite';

// Classic script + relative CSS work on file:// without module CORS or a server.
export default defineConfig({
  base: './',
  build: {
    lib: { entry: 'src/main.ts', name: 'InvSys', formats: ['iife'], fileName: () => 'app.js', cssFileName: 'style' },
  },
});
