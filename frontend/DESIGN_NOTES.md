# DeepTrace UI/UX Redesign Notes

## Core UX principle

The user is not an investigator. They may arrive stressed, angry, frightened or unsure what to do. The interface therefore prioritizes a single guided path:

**Reference identity (optional) → suspicious media → automatic preservation/analysis → plain-language findings → evidence report → official reporting link**

## What was intentionally removed from the old UI

- Dark “cyber/intelligence” visual language.
- Permanent forensic sidebar.
- Eight equal-priority tabs.
- Technical modules as the first thing a victim sees.
- Manual “Run analysis” as a normal step after upload.
- Emoji-heavy controls.
- Hardcoded Axios calls spread across components.
- Silent API failures.

## Government-service influence without impersonation

The design uses familiar public-service patterns: white background, navy navigation, restrained tricolour accent, accessibility affordance, clear section headings, strong form labels, simple bordered cards, and an official-reporting link.

It deliberately includes a visible statement that DeepTrace is a hackathon prototype and **not an official Government of India portal**.

## Victim-centred information hierarchy

1. **What do I do right now?** — Start evidence collection.
2. **What will this site do?** — Preserve, analyze, package.
3. **What did it find?** — Plain-language findings first.
4. **Can I trust the file record?** — SHA-256 integrity evidence.
5. **What should I do next?** — Keep URLs/screenshots, generate report, use official reporting channel.
6. **What are the technical details?** — Secondary disclosure only.

## Important backend gap exposed by the redesign

The current backend supports uploaded suspicious media, identity enrollment, analysis, evidence artifacts, timeline and PDF reports. However, source URL tracing exists in `services/tracing.py` but is not wired into the analysis route, and the current investigation upload route does not accept the victim's source URLs or additional screenshot/chat attachments.

For the product vision, the next backend increment should add:

- source URL capture and persistence,
- optional screenshot/chat/email evidence attachments,
- public-source tracing integration,
- inclusion of those records in the PDF report,
- explicit consent/authorization presentation in the frontend if identity enrollment is used.
