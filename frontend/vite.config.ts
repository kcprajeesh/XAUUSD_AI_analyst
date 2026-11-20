import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { validateDisplayTimezone } from './src/preferences.ts';

const healthProxy = {
  '^/api/health$': { target: 'http://127.0.0.1:8000', rewrite: () => '/health' },
  '^/api/v1/analysis/': { target: 'http://127.0.0.1:8000' },
};

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', 'VITE_');
  for (const key of Object.keys(env)) {
    if (key !== 'VITE_DISPLAY_TIMEZONE') {
      throw new Error(`Unsupported public environment variable: ${key}`);
    }
  }
  validateDisplayTimezone(env.VITE_DISPLAY_TIMEZONE ?? 'Asia/Qatar');
  return {
    plugins: [react(), tailwindcss()],
    server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy: healthProxy },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy: healthProxy },
  };
});
