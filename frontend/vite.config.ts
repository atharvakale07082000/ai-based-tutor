import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        // Vendor splitting, by package subtree rather than by package entry module.
        //
        // The previous object form (`{ react: ['react','react-dom'], charts: [...] }`)
        // only relocated each package's *index* module, so it emitted 0-byte junk
        // chunks (`react` 0.03 kB, `motion` 0.06 kB, an empty `hf`) while the real
        // weight stayed wherever the default algorithm put it — and it forced a
        // pointless `charts` chunk into the entry's modulepreload list.
        //
        // Rules are deliberately narrow. A manual chunk acts as an extra graph root:
        // if any module inside it is also reachable from the eager graph, Rollup
        // promotes the WHOLE chunk into the entry's static imports. Grouping
        // react-syntax-highlighter/react-markdown this way was measured to drag
        // ~630 kB onto every route (including the landing page), so those are
        // deliberately left to the default algorithm, which keeps them lazy.
        manualChunks(id) {
          if (!id.includes('node_modules')) return
          const pkg = id.split('node_modules/').pop() ?? ''

          // Code editor. Reached only via the lazy `import('@monaco-editor/react')`
          // in ModuleInterviewPage, so this chunk is fetched only when the editor
          // opens. The editor core is never bundled — @monaco-editor/loader pulls
          // monaco from a CDN at runtime, which is why this chunk is only ~15 kB.
          if (/^(@monaco-editor|monaco-editor)\//.test(pkg)) return 'vendor-monaco'

          if (/^(react|react-dom|scheduler|use-sync-external-store)\//.test(pkg)) return 'vendor-react'
          if (/^(react-router|react-router-dom|@remix-run)\//.test(pkg)) return 'vendor-router'
          if (/^@tanstack\//.test(pkg)) return 'vendor-query'

          return undefined
        },
      },
    },
  },
})
