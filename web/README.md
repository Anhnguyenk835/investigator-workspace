# The Investigator — web

React + Vite + TypeScript frontend for The Investigator, with Tailwind CSS v4 and a hard-corner design system.

## Scripts

```bash
npm install
npm run dev      # http://localhost:5173
npm run build
npm run preview
npm run lint
npm run format
```

Copy `.env.example` to `.env` when the API is available.

## Structure

```
src/
  app/            App shell, providers, router
  components/     layout + ui primitives
  features/       product domains (empty)
  hooks/          shared hooks
  lib/            cn(), env
  pages/          route-level screens
  styles/         Tailwind + design tokens
  types/          shared types
```

Import with `@/` (`@/components/ui`). Design tokens live in `src/styles/index.css` (`@theme`). Primary is `#48AFF0` on a blue canvas; preview tokens at `/system`.
