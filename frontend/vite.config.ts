import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { tanstackRouter } from "@tanstack/router-plugin/vite";
import tsConfigPaths from "vite-tsconfig-paths";

// File routes without a Start server: https://tanstack.com/router/latest/docs/installation/with-vite
export default defineConfig({
  appType: "spa",
  plugins: [
    tanstackRouter({ target: "react", autoCodeSplitting: true }),
    react(),
    tailwindcss(),
    tsConfigPaths(),
  ],
  server: { host: "localhost", port: 5173, strictPort: true },
  preview: { host: "localhost", port: 3000, strictPort: true },
});
