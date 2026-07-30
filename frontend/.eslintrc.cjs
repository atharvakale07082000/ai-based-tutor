/* eslint-env node */
// ESLint 8 legacy config (v8 does not read flat config by default).
// Wires up the four plugins already in devDependencies for a React + TS + Vite app.
// `npm run lint` runs with --max-warnings 0, so warnings are failures here.
module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: [
    'dist',
    'dist-*',
    'node_modules',
    'coverage',
    '.eslintrc.cjs',
    'vite.config.ts',
    'tailwind.config.ts',
    'postcss.config.js',
  ],
  parser: '@typescript-eslint/parser',
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  plugins: ['@typescript-eslint', 'react-refresh'],
  settings: {
    react: { version: '18.3' },
  },
  rules: {
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],

    // `while (true) { … break }` is the canonical shape of the SSE read loops in
    // lib/api.ts and DoubtChatPage — the loop exits on `done`/`[DONE]`/abort, not
    // on the condition. Only loop conditions are exempted; `if (true)` still errors.
    'no-constant-condition': ['error', { checkLoops: false }],

    // Fire-and-forget cleanup (`try { await authAPI.logout() } catch {}`) is a
    // deliberate pattern here: logout/abort failures must never block navigation.
    'no-empty': ['error', { allowEmptyCatch: true }],
  },
  // No per-file overrides. The legacy `no-explicit-any` / `exhaustive-deps`
  // exception list was burned down to zero — keep it that way rather than
  // re-adding entries; both rules are error-level everywhere.
}
