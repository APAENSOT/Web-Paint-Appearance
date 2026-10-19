# Paint Appearance frontend

React 19 + TypeScript single-page app, built with Vite. Routing and data fetching use
TanStack Router and TanStack Query; styling is Tailwind CSS 4 with Radix UI primitives.
The browser computes no measurement numbers: every value, grade and status comes from
the API.

Setup, configuration and the full test commands are in the repository
[README](../README.md). In short (Node 24, pnpm 10.32.1):

```powershell
pnpm install --frozen-lockfile
Copy-Item .env.example .env.local     # VITE_API_BASE_URL=http://127.0.0.1:8000
pnpm dev                              # http://localhost:5173
```

| Command | What it does |
|---|---|
| `pnpm dev` | Dev server on port 5173 (`--port` to change it) |
| `pnpm build` | Production build into `dist/` |
| `pnpm types:generate` | Regenerate `src/api/types.ts` from `../docs/openapi.json` |
| `pnpm typecheck` | `tsc --noEmit` |
| `pnpm lint` | ESLint + Prettier rules |
| `pnpm test` | Unit tests with `node --test` (no browser, no API) |
| `pnpm exec playwright test` | Browser specs in `tests/browser/` against a running site (`FRONTEND_URL`) |

`VITE_API_BASE_URL` is baked into the build and visible to every user, so it must never
hold a secret. Leave it empty when the API serves the built files itself (one origin).

Layout: `src/routes/` (pages), `src/features/` (measurements, filmthickness, analysis,
intake, overview, admin, shell), `src/api/` (typed client and generated types),
`src/components/` (shared UI), `public/` (static files, including the 3D body models
and their attribution notes).
