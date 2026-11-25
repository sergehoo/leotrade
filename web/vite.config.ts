import { fileURLToPath, URL } from "node:url"

import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig, loadEnv } from "vite"

// Le backend Django (ASGI/Daphne) sert l'API REST et les WebSocket.
// En dev on proxifie pour rester same-origin : les cookies de session et
// les en-têtes CSRF fonctionnent sans configuration CORS supplémentaire.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "")
  const backend = env.VITE_BACKEND_ORIGIN || "http://127.0.0.1:8000"
  const wsBackend = backend.replace(/^http/, "ws")

  return {
    plugins: [react(), tailwindcss()],
    resolve: {
      alias: {
        "@": fileURLToPath(new URL("./src", import.meta.url)),
      },
    },
    server: {
      port: 5173,
      proxy: {
        "/api": { target: backend, changeOrigin: true },
        "/ws": { target: wsBackend, ws: true, changeOrigin: true },
        "/media": { target: backend, changeOrigin: true },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: mode !== "production",
    },
  }
})
