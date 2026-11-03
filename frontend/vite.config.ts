import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// In development the Django server runs on :8000; Vite forwards API and admin calls to it
// so the browser sees one origin and the session cookie and CSRF token just work.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/admin": "http://localhost:8000",
      "/static": "http://localhost:8000",
    },
  },
});
