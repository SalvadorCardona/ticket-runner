import path from "node:path"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"
import { defineConfig } from "vite"

/* The console is served by Python, not by Node.
 *
 * `ticket-runner serve` is `http.server` and the standard library, and that is
 * not going to change: a tool whose whole claim is "no dependency to install"
 * cannot ask for a Node runtime on the machine it runs on. So this build writes
 * straight into the package — `src/ticket_runner/web/static` — and what it
 * writes is committed. Node is a thing *contributors* need; installing
 * ticket-runner still needs python3 and git and nothing else.
 *
 * Everything is served under `/static/`, which is the one route the server
 * hands files from, so that is the base every asset URL is written against.
 */
export default defineConfig({
  base: "/static/",
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "./src") },
  },
  build: {
    outDir: path.resolve(import.meta.dirname, "../src/ticket_runner/web/static"),
    emptyOutDir: true,
    // One file each, named without a hash: `Cache-Control: no-store` on every
    // response already settles staleness, and a diff that does not rename two
    // build artefacts on every commit is a diff you can read.
    rollupOptions: {
      output: {
        entryFileNames: "assets/console.js",
        chunkFileNames: "assets/[name].js",
        assetFileNames: "assets/console.[ext]",
      },
    },
  },
  server: {
    // `npm run dev` gives hot reload against a console you started yourself:
    //   ticket-runner serve      (127.0.0.1:8787, prints its token)
    //   npm run dev -- --open
    // The token rides on the cookie the real console set, so open the console
    // once on its own port first.
    proxy: {
      "/api": {
        target: process.env.TICKET_RUNNER_ORIGIN || "http://127.0.0.1:8787",
        changeOrigin: false,
      },
    },
  },
})
