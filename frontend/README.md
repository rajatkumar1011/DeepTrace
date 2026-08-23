# DeepTrace Frontend — Victim-Centred Redesign

This frontend replaces the original dark forensic-dashboard UI with a calmer, government-service-inspired evidence workflow.

## Design goals

- One primary action per screen.
- Victim-first language instead of analyst terminology.
- Evidence preservation is clearly separated from AI/model outputs.
- Technical model details are available, but hidden behind a secondary disclosure.
- Official reporting remains outside DeepTrace; the UI links to the National Cyber Crime Reporting Portal.
- No false claim that DeepTrace is an official Government of India service.

## Structure

- `src/config/constants.ts` — app constants, API routes, external links, labels.
- `src/lib/api/client.ts` — shared Axios instance and error handling.
- `src/lib/api/deeptrace.ts` — typed API functions.
- `src/types/index.ts` — frontend types.
- `src/components/` — shared header/footer/status/risk components.
- `src/app/page.tsx` — main guided flow and case views.
- `src/app/globals.css` — full design system and responsive styling.

## Run

```bash
npm install
npm run dev
```

Optional API override:

```bash
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

The redesign continues to use the existing FastAPI endpoints documented by the project backend.
