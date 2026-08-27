/**
 * DeepTrace — SIH 2026 Round 2.2 final-round evaluation deck.
 *
 * Every figure on these slides is read from a real artefact in this repository:
 * data/benchmark/latest.json, data/benchmark/robustness.json, the service source,
 * and the pytest run. Nothing is estimated. Slide 4 is the one exception and is
 * marked FILL-IN, because the Round 2.1 evaluator feedback is not recorded
 * anywhere in the repo and must come from the team.
 */

const pptxgen = require("pptxgenjs");

// ─── Palette ──────────────────────────────────────────────────────────────────
// Navy dominant, ice blue supporting, and two accents that carry meaning rather
// than decoration: green marks a figure measured against an external public
// corpus, amber marks a figure DeepTrace itself reports as weak. The deck
// colour-codes epistemic status, which is the project's whole argument.
const NAVY = "1E2761";
const NAVY_DEEP = "141B45";
const ICE = "CADCFC";
const ICE_SOFT = "EEF3FC";
const WHITE = "FFFFFF";
const INK = "1B2030";
const GREY = "5A6272";
const GREY_LT = "8FA6D9";
const GREEN = "1F6B4D";
const GREEN_SOFT = "E6F2EC";
const AMBER = "B06A00";
const AMBER_SOFT = "FCF1DF";

const SANS = "Calibri";
const SERIF = "Cambria";

const M = 0.55;           // slide margin
const W = 13.3 - M * 2;   // usable content width

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.3 x 7.5 — must be set before any slide is added
pres.author = "Team Algorythm — SIH26_28";
pres.title = "DeepTrace — SIH 2026 Round 2.2";

// ─── Helpers ──────────────────────────────────────────────────────────────────
// Each helper builds fresh option objects on every call: pptxgenjs converts
// option values to EMU in place, so a shared object silently corrupts the second
// shape that uses it.

const shadow = () => ({ type: "outer", color: "8A93A8", blur: 8, offset: 2, angle: 90, opacity: 0.22 });

function head(slide, kicker, title, dark) {
  slide.addText(String(kicker).toUpperCase(), {
    x: M, y: 0.32, w: W, h: 0.26, margin: 0,
    fontFace: SANS, fontSize: 11.5, bold: true, charSpacing: 2.2,
    color: dark ? GREY_LT : "6E7A99",
  });
  slide.addText(title, {
    x: M, y: 0.58, w: W - 2.9, h: 0.78, margin: 0, valign: "top",
    fontFace: SERIF, fontSize: 32, bold: true,
    color: dark ? WHITE : NAVY,
  });
}

/** Rubric pill, top-right — tells the evaluator which criterion the slide answers. */
function rubric(slide, text) {
  slide.addShape(pres.ShapeType.roundRect, {
    x: 13.3 - M - 2.75, y: 0.36, w: 2.75, h: 0.42, rectRadius: 0.21,
    fill: { color: NAVY }, line: { color: NAVY, width: 0.75 },
  });
  slide.addText(text, {
    x: 13.3 - M - 2.75, y: 0.36, w: 2.75, h: 0.42, margin: 0,
    align: "center", valign: "middle",
    fontFace: SANS, fontSize: 11, bold: true, color: ICE,
  });
}

function card(slide, x, y, w, h, tone) {
  const fill = tone === "green" ? GREEN_SOFT : tone === "amber" ? AMBER_SOFT : tone === "navy" ? NAVY : ICE_SOFT;
  slide.addShape(pres.ShapeType.roundRect, {
    x, y, w, h, rectRadius: 0.09,
    fill: { color: fill }, line: { color: fill, width: 0.5 },
    shadow: shadow(),
  });
}

/** Numbered disc — the deck's one repeated motif. */
function disc(slide, x, y, d, label, tone) {
  const bg = tone === "green" ? GREEN : tone === "amber" ? AMBER : NAVY;
  slide.addShape(pres.ShapeType.ellipse, {
    x, y, w: d, h: d, fill: { color: bg }, line: { color: bg, width: 0.5 },
  });
  slide.addText(label, {
    x, y, w: d, h: d, margin: 0, align: "center", valign: "middle",
    fontFace: SANS, fontSize: d > 0.5 ? 15 : 12, bold: true, color: WHITE,
  });
}

function bullets(slide, items, opts) {
  slide.addText(
    items.map((t, i) => ({
      text: t,
      options: { bullet: true, breakLine: i !== items.length - 1 },
    })),
    Object.assign({
      margin: 0, fontFace: SANS, fontSize: 14, color: INK,
      paraSpaceAfter: 7, lineSpacing: 19,
    }, opts)
  );
}

function statBlock(slide, x, y, w, value, label, tone) {
  const c = tone === "green" ? GREEN : tone === "amber" ? AMBER : NAVY;
  slide.addText(value, {
    x, y, w, h: 0.62, margin: 0, align: "center",
    fontFace: SERIF, fontSize: 34, bold: true, color: c,
  });
  slide.addText(label, {
    x, y: y + 0.6, w, h: 0.5, margin: 0, align: "center", valign: "top",
    fontFace: SANS, fontSize: 11, color: GREY,
  });
}

const light = () => { const s = pres.addSlide(); s.background = { color: WHITE }; return s; };
const dark = () => { const s = pres.addSlide(); s.background = { color: NAVY_DEEP }; return s; };

// ══ 1 · Title ═════════════════════════════════════════════════════════════════
{
  const s = dark();
  s.addText("Team Algorythm  ·  SIH26_28  ·  Defence & National Security", {
    x: M, y: 1.5, w: W, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 13.5, bold: true, charSpacing: 1.4, color: GREY_LT,
  });
  s.addText("DeepTrace", {
    x: M, y: 1.95, w: W, h: 1.15, margin: 0,
    fontFace: SERIF, fontSize: 62, bold: true, color: WHITE,
  });
  s.addText("Intelligent Digital Impersonation Detection\n& Forensic Evidence Preservation", {
    x: M, y: 3.12, w: 8.6, h: 1.0, margin: 0,
    fontFace: SANS, fontSize: 21, color: ICE, lineSpacing: 28,
  });
  s.addText("Every other tool asks “is this fake?”\nDeepTrace asks “is this you — and can you prove it?”", {
    x: M, y: 4.32, w: 8.6, h: 0.8, margin: 0, italic: true,
    fontFace: SERIF, fontSize: 15.5, color: GREY_LT, lineSpacing: 22,
  });

  const stats = [["19", "services"], ["9,769", "lines"], ["149", "tests pass"], ["23", "report sections"]];
  stats.forEach(([v, l], i) => {
    const x = M + i * 2.24;
    s.addText(v, {
      x, y: 5.55, w: 2.0, h: 0.5, margin: 0,
      fontFace: SERIF, fontSize: 27, bold: true, color: ICE,
    });
    s.addText(l, {
      x, y: 6.04, w: 2.0, h: 0.3, margin: 0,
      fontFace: SANS, fontSize: 11, color: GREY_LT,
    });
  });

  s.addText("Round 2.2 — Final Round  ·  27 August 2026", {
    x: 13.3 - M - 4.4, y: 6.72, w: 4.4, h: 0.32, margin: 0, align: "right",
    fontFace: SANS, fontSize: 12, color: GREY_LT,
  });
  s.addNotes(
    "0:00-0:30 | Open on the tagline, not the tech. One sentence: an impersonation victim " +
    "cannot prove the media is not them, and an investigator cannot act on a screenshot. " +
    "DeepTrace closes that gap. Do not read the stats aloud — they are there for the eye."
  );
}

// ══ 2 · Problem & Objective ═══════════════════════════════════════════════════
{
  const s = light();
  head(s, "Problem & Objective", "The gap is proof, not detection");

  card(s, M, 1.58, 5.95, 4.5, "amber");
  s.addText("The problem", {
    x: M + 0.32, y: 1.82, w: 5.3, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 16, bold: true, color: AMBER,
  });
  bullets(s, [
    "AI-generated media can impersonate a real person's face, voice or identity.",
    "The victim cannot prove the media is not them.",
    "Existing tools return a fake/real score — no identity link, no evidence.",
    "Investigators receive screenshots, not preserved evidence with verifiable integrity.",
    "Compression breaks byte-level matching, so re-uploaded copies go untracked.",
  ], { x: M + 0.32, y: 2.22, w: 5.35, h: 3.6, fontSize: 13.5 });

  card(s, M + 6.25, 1.58, 5.95, 4.5, "plain");
  s.addText("The objective", {
    x: M + 6.57, y: 1.82, w: 5.3, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 16, bold: true, color: NAVY,
  });
  bullets(s, [
    "Confirm whether a specific consented identity is present — face and voice.",
    "Detect and localize manipulation indicators, with frames and timestamps.",
    "Locate other pages publishing the same media, and verify each locally.",
    "Preserve evidence with server-side SHA-256 and a timestamped chain of custody.",
    "Produce a 23-section forensic report an investigating officer can file.",
  ], { x: M + 6.57, y: 2.22, w: 5.35, h: 3.6, fontSize: 13.5 });

  card(s, M, 6.24, W, 0.72, "navy");
  s.addText(
    "Scope, stated honestly:  DeepTrace produces forensic indicators for expert review — not a verdict, " +
    "not creator identification, not internet-wide surveillance.",
    { x: M + 0.32, y: 6.24, w: W - 0.64, h: 0.72, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 13, color: ICE }
  );
  s.addNotes(
    "0:30-1:15 | Land the reframe: every competing tool answers 'is this fake'. That is the wrong " +
    "question — a score proves nothing and names nobody. The victim's question is 'is this me'. " +
    "Read the scope line at the bottom out loud. Volunteering the limits early buys credibility " +
    "for every number that follows."
  );
}

// ══ 3 · Completion ════════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 1", "100% of proposed scope delivered");
  rubric(s, "Criterion 1  ·  20 marks");

  const rows = [
    ["1", "Identity enrolment", "Consented face + voice reference, with submitter record and consent text"],
    ["2", "Manipulation analysis", "DeepfakeBench Xception on MTCNN face crops, per-frame, 12 frames per video"],
    ["3", "Localization", "Suspicious frames, time intervals, face region, residual overlay images"],
    ["4", "Identity & voice match", "FaceNet cosine similarity; ECAPA-TDNN speaker verification"],
    ["5", "Provenance estimator", "Reverse-image lookup, then every candidate re-fetched and verified locally"],
    ["6", "Evidence preservation", "Server-side SHA-256, chain of custody, integrity re-verification endpoint"],
    ["7", "Response & report", "Victim guidance, cybercrime.gov.in routing, 23-section forensic PDF"],
  ];
  rows.forEach(([n, t, d], i) => {
    const y = 1.56 + i * 0.685;
    card(s, M, y, W - 2.5, 0.6, "plain");
    disc(s, M + 0.16, y + 0.13, 0.34, n);
    s.addText(t, {
      x: M + 0.64, y: y, w: 2.85, h: 0.6, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 13.5, bold: true, color: NAVY,
    });
    s.addText(d, {
      x: M + 3.5, y: y, w: 6.1, h: 0.6, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 11.5, color: GREY,
    });
    s.addText("DELIVERED", {
      x: M + 9.6, y: y, w: 1.05, h: 0.6, margin: 0, valign: "middle", align: "right",
      fontFace: SANS, fontSize: 10, bold: true, color: GREEN,
    });
  });

  card(s, 13.3 - M - 2.3, 1.56, 2.3, 4.79, "green");
  ["149 / 150", "tests passing", "24", "API endpoints", "7", "database tables", "0", "mocked outputs"].forEach((t, i) => {
    const isVal = i % 2 === 0;
    s.addText(t, {
      x: 13.3 - M - 2.3, y: 1.78 + Math.floor(i / 2) * 1.18 + (isVal ? 0 : 0.5), w: 2.3, h: isVal ? 0.5 : 0.32,
      margin: 0, align: "center",
      fontFace: isVal ? SERIF : SANS, fontSize: isVal ? 27 : 11, bold: isVal,
      color: isVal ? GREEN : GREY,
    });
  });

  s.addText(
    "No feature in the Round 2.1 proposal was dropped. Where a module cannot run, the UI and the report " +
    "print “Unavailable / Inconclusive” — never a fabricated success screen.",
    { x: M, y: 6.5, w: W, h: 0.5, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "1:15-2:15 | Walk the seven rows fast — one clause each, do not read the right column. " +
    "The sentence that matters is the italic line: nothing was dropped, and unavailable modules say so. " +
    "If asked to prove 149 tests, you can run pytest live from the terminal."
  );
}

// ══ 4 · Round 2.1 feedback — FILL IN ══════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 2", "Round 2.1 feedback, and what changed");
  rubric(s, "Criterion 2  ·  10 marks");

  s.addText("FILL IN BEFORE PRESENTING — the exact evaluator wording is not recorded in the repo.", {
    x: M, y: 1.5, w: W, h: 0.34, margin: 0,
    fontFace: SANS, fontSize: 12, bold: true, color: AMBER,
  });

  const hdr = ["Round 2.1 feedback", "What we changed", "Where to see it in the demo"];
  hdr.forEach((t, i) => {
    s.addText(t, {
      x: M + i * 4.07, y: 1.95, w: 3.85, h: 0.3, margin: 0,
      fontFace: SANS, fontSize: 12, bold: true, charSpacing: 1, color: GREY,
    });
  });

  const fb = [
    ["FEEDBACK 1 — replace with the evaluator's words",
     "Provenance was presented as Content Credentials, which almost no real file carries. Replaced with a Provenance estimator that locates published copies and verifies each one locally.",
     "Case #35 — “10 found · 4 matched”"],
    ["FEEDBACK 2 — replace with the evaluator's words",
     "Added scripts/robustness.py: 16 real ffmpeg transforms measuring score stability under compression, re-upload and screen recording. Figures print in report section 22.",
     "Report PDF — section 22"],
    ["FEEDBACK 3 — replace with the evaluator's words",
     "Benchmarked every layer against public corpora (LFW, 140k Real-and-Fake) and published the numbers, confidence intervals and caveats — including the weak ones.",
     "Benchmark panel + slide 9"],
  ];
  fb.forEach((row, i) => {
    const y = 2.34 + i * 1.42;
    card(s, M, y, W, 1.28, i === 0 ? "plain" : "plain");
    s.addText(row[0], {
      x: M + 0.26, y: y + 0.06, w: 3.6, h: 1.16, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 12, bold: true, color: AMBER,
    });
    s.addText(row[1], {
      x: M + 4.07, y: y + 0.06, w: 4.0, h: 1.16, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 11.5, color: INK,
    });
    s.addText(row[2], {
      x: M + 8.28, y: y + 0.06, w: 3.6, h: 1.16, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 11.5, bold: true, color: NAVY,
    });
  });

  s.addText(
    "Each change is demonstrable live — not described. Point at the screen for every row.",
    { x: M, y: 6.68, w: W, h: 0.4, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "2:15-3:00 | ACTION REQUIRED: replace the three amber cells with the evaluator's actual Round 2.1 " +
    "wording. The middle and right columns are real changes already in the build, so slot the feedback " +
    "that each one answers. If a piece of feedback has no matching change, say so plainly and give the " +
    "reason — an honest 'we judged this out of scope because…' scores better than a vague claim."
  );
}

// ══ 5 · Workflow ══════════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "The workflow", "Six stages, one case record");

  const steps = [
    ["Match", "Identity", "Is the consented\nface / voice present?"],
    ["Analyze", "Manipulation", "Per-frame indicators\non cropped faces"],
    ["Localize", "Where & when", "Frames, intervals,\nresidual overlays"],
    ["Trace", "Provenance", "Published copies,\nverified locally"],
    ["Preserve", "Integrity", "SHA-256, chain\nof custody"],
    ["Respond", "Action", "Victim guidance,\nforensic report"],
  ];
  const cw = 1.92, gap = 0.13;
  steps.forEach(([verb, tag, body], i) => {
    const x = M + i * (cw + gap);
    card(s, x, 1.72, cw, 2.4, "plain");
    disc(s, x + cw / 2 - 0.25, 1.92, 0.5, String(i + 1));
    s.addText(verb, {
      x, y: 2.52, w: cw, h: 0.36, margin: 0, align: "center",
      fontFace: SERIF, fontSize: 18, bold: true, color: NAVY,
    });
    s.addText(tag.toUpperCase(), {
      x, y: 2.88, w: cw, h: 0.26, margin: 0, align: "center",
      fontFace: SANS, fontSize: 9.5, bold: true, charSpacing: 1.1, color: GREY,
    });
    s.addText(body, {
      x: x + 0.14, y: 3.22, w: cw - 0.28, h: 0.9, margin: 0, align: "center", valign: "top",
      fontFace: SANS, fontSize: 11, color: INK, lineSpacing: 15,
    });
  });

  card(s, M, 4.55, W, 0.86, "green");
  s.addText(
    "Order is the argument. Identity is established first, so every later finding is about a named " +
    "protected person — not about media in the abstract.",
    { x: M + 0.3, y: 4.55, w: W - 0.6, h: 0.86, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 13.5, color: GREEN }
  );

  s.addText(
    "Pipeline progress is reported at 13 checkpoints: metadata 5% → frames 15% → audio 30% → manipulation 45% " +
    "→ localization 60% → identity 70% → speaker 78% → A/V 84% → credentials 88% → copy search 89% " +
    "→ local index 92% → risk fusion 96% → complete 100%.",
    { x: M, y: 5.75, w: W, h: 0.9, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: GREY, lineSpacing: 16 }
  );
  s.addNotes(
    "3:00-3:45 | Say the six verbs in order, then the green line — that sentence is the entire " +
    "differentiator and the answer to 'how is this different from any deepfake detector'. " +
    "The checkpoint list at the bottom is proof the pipeline is real and observable, not a black box."
  );
}

// ══ 6 · Live demo script ══════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 3", "Live demo — the route we will drive");
  rubric(s, "Criterion 3  ·  20 marks");

  const beats = [
    ["Enrol", "Consented reference identity — face photo plus voice sample, with consent text on record."],
    ["Submit", "Upload the suspect media. Validated for type, size and filename before anything touches it."],
    ["Watch", "The 13 pipeline checkpoints advance live. No pre-rendered screens, no simulated progress."],
    ["Read", "Plain-language findings: identity match, manipulation indicators, localized frames with overlays."],
    ["Trace", "Provenance estimator — “10 found · 4 matched”. Discovery and verification stay separate numbers."],
    ["Verify", "Re-verify integrity on demand: recompute the hash and confirm the stored evidence is untampered."],
    ["Export", "Download the 23-section forensic PDF, open section 22 and show the measured robustness figures."],
  ];
  beats.forEach(([t, d], i) => {
    const col = i < 4 ? 0 : 1;
    const row = i < 4 ? i : i - 4;
    const x = M + col * 6.25;
    const y = 1.6 + row * 1.02;
    disc(s, x, y + 0.09, 0.4, String(i + 1));
    s.addText(t, {
      x: x + 0.54, y: y, w: 1.5, h: 0.34, margin: 0,
      fontFace: SANS, fontSize: 14, bold: true, color: NAVY,
    });
    s.addText(d, {
      x: x + 0.54, y: y + 0.32, w: 5.35, h: 0.66, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 11.5, color: GREY, lineSpacing: 15,
    });
  });

  card(s, M + 6.25, 5.72, 5.95, 1.22, "amber");
  s.addText("Demo on cases #31, #34, #35 or #36", {
    x: M + 6.55, y: 5.86, w: 5.4, h: 0.3, margin: 0,
    fontFace: SANS, fontSize: 13, bold: true, color: AMBER,
  });
  s.addText(
    "#35 shows 10 found · 4 matched. #34 shows 10 found · 0 matched — the honest case, and a better " +
    "story. Cases #1–#28 predate ffmpeg on this machine.",
    { x: M + 6.55, y: 6.18, w: 5.4, h: 0.66, margin: 0,
      fontFace: SANS, fontSize: 11, color: INK, lineSpacing: 14 }
  );

  card(s, M, 5.72, 5.95, 1.22, "green");
  s.addText("Fallback if the network drops", {
    x: M + 0.3, y: 5.86, w: 5.4, h: 0.3, margin: 0,
    fontFace: SANS, fontSize: 13, bold: true, color: GREEN,
  });
  s.addText(
    "Everything except the reverse-image lookup runs fully offline on localhost. The estimator then " +
    "reports “Search not configured” — a truthful state, not a crash.",
    { x: M + 0.3, y: 6.18, w: 5.4, h: 0.66, margin: 0,
      fontFace: SANS, fontSize: 11, color: INK, lineSpacing: 14 }
  );
  s.addNotes(
    "3:45-7:00 | THE DEMO. Longest block — 3 minutes 15. Do not narrate every field; drive the seven " +
    "beats and let the screen talk. Two rules: open a case that already has results in a second browser " +
    "tab as insurance, and if the reverse-image lookup fails live, say the fallback line out loud " +
    "rather than clicking around. A graceful truthful degradation is itself a scoring moment."
  );
}

// ══ 7 · Architecture ══════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 4", "Architecture — deliberately not distributed");
  rubric(s, "Criterion 4  ·  15 marks");

  const layers = [
    ["Next.js 15 · React · TypeScript", "Victim-facing UI. Plain language, no forensic vocabulary to learn."],
    ["FastAPI · Python 3.11", "24 endpoints. Validation, size limits, filename sanitisation, path-traversal guards."],
    ["AI & forensics — 19 services", "4 trained models plus perceptual hashing, residual analysis and signal statistics."],
    ["SQLite · local evidence store", "7 tables. Server-side SHA-256, chain of custody, additive migrations only."],
    ["Output", "React case view for the victim; 23-section PDF for the investigating officer."],
  ];
  layers.forEach(([t, d], i) => {
    const y = 1.6 + i * 0.94;
    card(s, M, y, 8.6, 0.82, "plain");
    disc(s, M + 0.2, y + 0.19, 0.44, String(i + 1));
    s.addText(t, {
      x: M + 0.8, y: y + 0.09, w: 7.6, h: 0.32, margin: 0,
      fontFace: SANS, fontSize: 13.5, bold: true, color: NAVY,
    });
    s.addText(d, {
      x: M + 0.8, y: y + 0.41, w: 7.6, h: 0.34, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: GREY,
    });
    if (i < layers.length - 1) {
      s.addText("▼", {
        x: M + 0.28, y: y + 0.8, w: 0.3, h: 0.16, margin: 0, align: "center",
        fontFace: SANS, fontSize: 9, color: ICE,
      });
    }
  });

  card(s, M + 8.9, 1.6, 3.3, 4.16, "navy");
  s.addText("Choices we will defend", {
    x: M + 9.16, y: 1.82, w: 2.8, h: 0.3, margin: 0,
    fontFace: SANS, fontSize: 13, bold: true, color: ICE,
  });
  const defence = [
    ["SQLite, not Postgres", "One custodian, one evidence store. A network hop adds attack surface, not integrity."],
    ["Monolith, not microservices", "Chain of custody is easier to prove when one process owns the file."],
    ["Local models, not an API", "Evidence must never leave the machine it was preserved on."],
  ];
  defence.forEach(([t, d], i) => {
    const y = 2.24 + i * 1.16;
    s.addText(t, {
      x: M + 9.16, y, w: 2.8, h: 0.3, margin: 0,
      fontFace: SANS, fontSize: 11.5, bold: true, color: WHITE,
    });
    s.addText(d, {
      x: M + 9.16, y: y + 0.28, w: 2.8, h: 0.78, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 10, color: GREY_LT, lineSpacing: 13,
    });
  });

  s.addText(
    "No Kubernetes, no cloud, no message queue. Nothing was added for appearance — every layer earns its place " +
    "in the custody argument.",
    { x: M, y: 6.42, w: W, h: 0.5, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "7:00-7:45 | Read the five layers as a sentence, then spend most of the time on the navy card. " +
    "Evaluators reward defended simplicity over undefended complexity. The killer line: 'we did not add " +
    "Postgres or Kubernetes, because for a chain-of-custody argument a network hop is a liability, not a feature.'"
  );
}

// ══ 8 · Models ════════════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 4", "Four trained models, and what is not one");
  rubric(s, "Criterion 4  ·  15 marks");

  const models = [
    ["DeepfakeBench\nXception", "Manipulation", "Face crop → 256px → 2-class CNN → softmax P(fake). Threshold 0.50."],
    ["MTCNN", "Face detection", "Crops and aligns first — the checkpoint was trained on faces, not full frames."],
    ["FaceNet\nInceptionResnetV1", "Face identity", "512-dim embedding, cosine similarity against the consented reference."],
    ["ECAPA-TDNN\nVoxCeleb", "Voice identity", "Speaker embedding. Threshold 0.25 is ECAPA's own published figure."],
  ];
  models.forEach(([n, role, how], i) => {
    const x = M + i * 3.1;
    card(s, x, 1.58, 2.92, 2.32, "plain");
    disc(s, x + 0.2, 1.76, 0.4, String(i + 1));
    s.addText(role.toUpperCase(), {
      x: x + 0.68, y: 1.8, w: 2.0, h: 0.26, margin: 0,
      fontFace: SANS, fontSize: 9.5, bold: true, charSpacing: 1.1, color: GREY,
    });
    s.addText(n, {
      x: x + 0.2, y: 2.24, w: 2.55, h: 0.68, margin: 0, valign: "top",
      fontFace: SERIF, fontSize: 14.5, bold: true, color: NAVY, lineSpacing: 18,
    });
    s.addText(how, {
      x: x + 0.2, y: 2.98, w: 2.55, h: 1.0, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 10.5, color: INK, lineSpacing: 14,
    });
  });

  s.addText("Deliberately not a model — and labelled as such everywhere it surfaces", {
    x: M, y: 4.3, w: W, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 14, bold: true, color: AMBER,
  });

  const notModels = [
    ["Localization overlay", "High-frequency residual — not a trained segmentation mask"],
    ["Audio-video consistency", "Face presence vs audio energy — not SyncNet"],
    ["Audio editing indicators", "Container probe + PCM statistics — no model"],
    ["Copy detection", "Perceptual hashing: pHash, dHash, aHash"],
    ["Final risk score", "Transparent weighted sum — not a black box"],
  ];
  notModels.forEach(([t, d], i) => {
    const x = M + i * 2.45;
    card(s, x, 4.7, 2.28, 1.42, "amber");
    s.addText(t, {
      x: x + 0.16, y: 4.84, w: 1.96, h: 0.42, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 11.5, bold: true, color: AMBER, lineSpacing: 14,
    });
    s.addText(d, {
      x: x + 0.16, y: 5.26, w: 1.96, h: 0.76, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 9.5, color: INK, lineSpacing: 12,
    });
  });

  card(s, M, 6.28, W, 0.7, "navy");
  s.addText(
    "Risk fusion weights:  manipulation 0.35  ·  face identity 0.25  ·  voice 0.12  ·  A/V consistency 0.10  " +
    "·  provenance 0.08  ·  audio editing 0.05  ·  propagation 0.05",
    { x: M + 0.3, y: 6.28, w: W - 0.6, h: 0.7, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 12, color: ICE }
  );
  s.addNotes(
    "7:45-8:30 | The amber row is the point of this slide. Any team can list four models; almost none " +
    "will tell you which of their features are heuristics. Say it explicitly: 'the heatmap is a residual " +
    "visualisation, not a trained mask, and our own UI and PDF say so.' That single admission is worth " +
    "more in Q&A than the model list above it."
  );
}

// ══ 9 · Measured performance ══════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criteria 4 & 7", "Measured — including the weak numbers");
  rubric(s, "Criteria 4 + 7");

  card(s, M, 1.56, 3.9, 2.34, "green");
  statBlock(s, M + 0.2, 1.74, 3.5, "91.5%", "Face identity accuracy — LFW public pairs, n = 200", "green");
  s.addText("Precision 1.00  ·  Specificity 1.00\nZero false matches in 200 pairs", {
    x: M + 0.3, y: 2.9, w: 3.3, h: 0.86, margin: 0, align: "center",
    fontFace: SANS, fontSize: 11.5, bold: true, color: GREEN, lineSpacing: 16,
  });

  card(s, M + 4.2, 1.56, 3.9, 2.34, "green");
  statBlock(s, M + 4.4, 1.74, 3.5, "87.5%", "Decision stability under compression — 80 paired transforms", "green");
  s.addText("16 real ffmpeg transforms\n95% CI  0.785 – 0.931", {
    x: M + 4.5, y: 2.9, w: 3.3, h: 0.86, margin: 0, align: "center",
    fontFace: SANS, fontSize: 11.5, bold: true, color: GREEN, lineSpacing: 16,
  });

  card(s, M + 8.4, 1.56, 3.8, 2.34, "amber");
  statBlock(s, M + 8.6, 1.74, 3.4, "46.6%", "Manipulation accuracy, out-of-distribution — n = 500", "amber");
  s.addText("ROC-AUC 0.417 on StyleGAN faces\nWe report this, we do not hide it", {
    x: M + 8.5, y: 2.9, w: 3.6, h: 0.86, margin: 0, align: "center",
    fontFace: SANS, fontSize: 11.5, bold: true, color: AMBER, lineSpacing: 16,
  });

  s.addText("Why the third number is low — and why it does not sink the system", {
    x: M, y: 4.06, w: W, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 14, bold: true, color: NAVY,
  });
  bullets(s, [
    "It is a cross-generator test. The Xception checkpoint was trained on FaceForensics++ face swaps; the corpus is StyleGAN whole-face synthesis. A lower bound, not an in-distribution figure.",
    "We used a corpus we could license and publish; FaceForensics++ and Celeb-DF need signed EULAs.",
    "It is why DeepTrace outputs indicators, never a verdict — identity signals combined (0.37) outweigh manipulation (0.35).",
    "A 10-point threshold sweep and Wilson intervals ship with it, so the operating point is inspectable.",
  ], { x: M, y: 4.44, w: W, h: 2.0, fontSize: 12.5 });

  card(s, M, 6.5, W, 0.62, "navy");
  s.addText(
    "Every figure computed by scripts/benchmark.py running the real pipeline. No value is estimated, " +
    "copied from a paper, or carried over from another dataset.",
    { x: M + 0.3, y: 6.5, w: W - 0.6, h: 0.62, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 12, italic: true, color: ICE }
  );
  s.addNotes(
    "8:30-9:15 | THE HIGH-RISK, HIGH-REWARD SLIDE. Lead with 91.5% and zero false matches — that is the " +
    "layer the whole thesis rests on. Then go to the amber card BEFORE anyone asks. Exact words: 'our " +
    "manipulation detector scores 0.47 on an out-of-distribution corpus. We built the harness that found " +
    "that, we publish it with confidence intervals, and it is the reason this tool reports indicators " +
    "instead of verdicts.' Teams claiming 99% cannot survive the follow-up question. You can."
  );
}

// ══ 10 · Compression ══════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 4", "Compression — measured, not assumed");
  rubric(s, "Criterion 4  ·  15 marks");

  const cols = [
    ["1", "Two hash layers", "SHA-256 dies on re-encoding, so perceptual hashes run alongside it. pHash + dHash + aHash, combined threshold 0.78, survive the transcode that breaks the digest."],
    ["2", "Compression is not evidence", "Re-encoding artefacts look like editing artefacts. Five modules explicitly say so in their own output rather than cashing it in as suspicion."],
    ["3", "Then we measured it", "16 real ffmpeg transforms in 4 families: compression, resolution, re-upload, screen capture — plus chains, because forwarded evidence has been through several."],
  ];
  cols.forEach(([n, t, d], i) => {
    const x = M + i * 4.13;
    card(s, x, 1.58, 3.93, 2.16, "plain");
    disc(s, x + 0.22, 1.78, 0.42, n);
    s.addText(t, {
      x: x + 0.76, y: 1.82, w: 3.0, h: 0.34, margin: 0,
      fontFace: SANS, fontSize: 13.5, bold: true, color: NAVY,
    });
    s.addText(d, {
      x: x + 0.24, y: 2.3, w: 3.48, h: 1.32, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 11, color: INK, lineSpacing: 14,
    });
  });

  const chart = [{
    name: "Decisions preserved",
    labels: ["Screenshot\non 720p", "JPEG q75", "JPEG q40", "Messaging\nre-upload", "Double\nre-upload"],
    values: [1.0, 0.875, 0.875, 0.8125, 0.8125],
  }];
  s.addChart(pres.ChartType.bar, chart, {
    x: M, y: 3.92, w: 7.55, h: 2.42,
    barDir: "col", barGapWidthPct: 55,
    chartColors: [GREEN],
    showTitle: true, title: "Score stability per transform (visual, n = 16 each)",
    titleFontFace: SANS, titleFontSize: 12, titleColor: NAVY,
    showValue: true, dataLabelPosition: "outEnd", dataLabelFormatCode: "0%",
    dataLabelFontFace: SANS, dataLabelFontSize: 10, dataLabelColor: GREEN,
    showLegend: false,
    valAxisMinVal: 0, valAxisMaxVal: 1, valAxisLabelFormatCode: "0%",
    catAxisLabelColor: GREY, valAxisLabelColor: GREY,
    catAxisLabelFontFace: SANS, catAxisLabelFontSize: 9.5,
    valAxisLabelFontFace: SANS, valAxisLabelFontSize: 9.5,
    valGridLine: { color: "E4E9F2", size: 0.75 },
    catGridLine: { style: "none" },
  });

  card(s, M + 7.85, 3.92, 4.35, 2.42, "amber");
  s.addText("The finding worth saying out loud", {
    x: M + 8.1, y: 4.08, w: 3.9, h: 0.3, margin: 0,
    fontFace: SANS, fontSize: 12.5, bold: true, color: AMBER,
  });
  s.addText(
    "Four of five image transforms RAISE the manipulation score. Compression makes authentic media look " +
    "more manipulated — it is false-positive pressure, not noise. Our harness names the direction instead " +
    "of hiding it behind an absolute delta.\n\nAudio stability is 0.375 on 8 pairs. We publish that as a " +
    "known gap: the editing indicator uses a per-minute discontinuity rate, so clips under 10 s saturate it.",
    { x: M + 8.1, y: 4.42, w: 3.9, h: 1.8, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 10.5, color: INK, lineSpacing: 13.5 }
  );

  s.addText(
    "This is why identity carries the argument: perceptual hashes and face embeddings survive re-encoding — artefact detection is exactly what compression attacks.",
    { x: M, y: 6.5, w: W, h: 0.5, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "9:15-10:00 | Compression is the standard attack on any deepfake tool — get ahead of it. Three columns, " +
    "one clause each, then the chart. The amber card is the memorable part: compression pushes scores UP, " +
    "which means the real-world failure mode is false accusation, and we measured that rather than assumed it. " +
    "Volunteer the 0.375 audio number before anyone finds it."
  );
}

// ══ 11 · Evidence integrity ═══════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 4", "Evidence integrity, not just a score");
  rubric(s, "Criterion 4  ·  15 marks");

  const items = [
    ["Hashes computed server-side", "A client-supplied digest is never trusted. SHA-256 is calculated on the bytes as received."],
    ["Chain of custody, timestamped", "Every stage writes a timeline event: who submitted, what ran, when, and what it produced."],
    ["Integrity re-verification on demand", "A dedicated endpoint recomputes the hash and reports verified, mismatch or file missing."],
    ["Consent recorded before analysis", "The reference identity is enrolled with consent text and a submitter record on file."],
    ["23-section forensic report", "Full digests, per-module method and limitations, the measured figures, in an officer's reading order."],
  ];
  items.forEach(([t, d], i) => {
    const y = 1.6 + i * 0.98;
    card(s, M, y, 7.9, 0.86, "plain");
    disc(s, M + 0.2, y + 0.21, 0.44, String(i + 1));
    s.addText(t, {
      x: M + 0.8, y: y + 0.1, w: 6.9, h: 0.32, margin: 0,
      fontFace: SANS, fontSize: 13.5, bold: true, color: NAVY,
    });
    s.addText(d, {
      x: M + 0.8, y: y + 0.42, w: 6.9, h: 0.36, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: GREY,
    });
  });

  card(s, M + 8.2, 1.6, 4.0, 4.36, "amber");
  s.addText("What we do NOT claim", {
    x: M + 8.46, y: 1.8, w: 3.5, h: 0.3, margin: 0,
    fontFace: SANS, fontSize: 13.5, bold: true, color: AMBER,
  });
  bullets(s, [
    "Not third-party timestamping or notarisation.",
    "Does not by itself establish legal admissibility.",
    "Does not identify who created or uploaded the media.",
    "Not internet-wide search — one reverse-image index, named.",
    "Not 100% detection. Model outputs are indicators for expert review.",
  ], { x: M + 8.46, y: 2.2, w: 3.5, h: 3.6, fontSize: 11.5, color: INK });

  s.addText(
    "Hash-based preservation demonstrates the integrity of this local evidence store. Saying precisely that — and no more — is what makes the rest of the report credible.",
    { x: M, y: 6.5, w: W, h: 0.5, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "10:00-10:40 | This is the slide that separates DeepTrace from a classifier demo. Five integrity " +
    "guarantees on the left, and — critically — the amber list on the right. Read two or three of the " +
    "'do not claim' items aloud. Evaluators in a Defence domain are testing whether you know the " +
    "difference between evidence and a score."
  );
}

// ══ 12 · Innovation ═══════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 5", "What is genuinely different");
  rubric(s, "Criterion 5  ·  10 marks");

  s.addText("Typical deepfake tool", {
    x: M + 0.3, y: 1.6, w: 5.6, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 14, bold: true, color: AMBER,
  });
  s.addText("DeepTrace", {
    x: M + 6.55, y: 1.6, w: 5.6, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 14, bold: true, color: GREEN,
  });

  const pairs = [
    ["Answers “is this fake?”", "Answers “is this a named, consented identity?”"],
    ["One score, no provenance", "Located copies, each re-fetched and verified locally"],
    ["Screenshot as output", "SHA-256 evidence store with chain of custody"],
    ["Accuracy claimed, not shown", "Public-corpus benchmarks with confidence intervals published"],
    ["Silent under compression", "16 measured transforms; the direction of drift is reported"],
    ["Black-box verdict", "Weighted fusion that names every excluded signal and why"],
  ];
  pairs.forEach(([a, b], i) => {
    const y = 2.02 + i * 0.72;
    card(s, M, y, 5.9, 0.62, "amber");
    s.addText(a, {
      x: M + 0.26, y, w: 5.4, h: 0.62, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 12, color: INK,
    });
    card(s, M + 6.3, y, 5.9, 0.62, "green");
    s.addText(b, {
      x: M + 6.56, y, w: 5.4, h: 0.62, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 12, bold: true, color: GREEN,
    });
  });

  card(s, M, 6.42, W, 0.66, "navy");
  s.addText(
    "The innovation is not a new model. It is the insight that the victim's question is an identity " +
    "question, and that an answer is worthless unless it survives as evidence.",
    { x: M + 0.3, y: 6.42, w: W - 0.6, h: 0.66, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 13, color: ICE }
  );
  s.addNotes(
    "10:40-11:20 | Do not read all twelve cells. Read three left-right pairs — rows 1, 3 and 4 — then " +
    "the navy line, which is the whole pitch in one sentence. If you only have time for one row, use row 1."
  );
}

// ══ 13 · Feasibility & scale ══════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 5", "Feasibility and the path to scale");
  rubric(s, "Criterion 5  ·  10 marks");

  const now = [
    ["Runs today on one laptop", "CPU-only PyTorch 2.2.2, Python 3.11, SQLite. No GPU and no cloud account required."],
    ["Zero recurring cost", "All four models are local checkpoints. Nothing is billed per inference."],
    ["Offline-capable", "Only the reverse-image lookup needs a network; its absence is a reported state, not a failure."],
  ];
  const next = [
    ["Deployable at a cyber cell", "Same monolith, one box per unit. Evidence never leaves the custodian's machine."],
    ["Throughput scales by queueing", "Analysis is per-case and stateless after ingest — add workers, not architecture."],
    ["Accuracy scales with licensing", "scripts/import_eval_set.py already accepts FaceForensics++ or Celeb-DF for an in-distribution figure."],
    ["Indices are pluggable", "The provenance estimator is one named index behind an interface — add authorised sources without touching the pipeline."],
  ];

  s.addText("Feasible now — demonstrated on this machine", {
    x: M + 0.3, y: 1.6, w: 5.6, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 14, bold: true, color: GREEN,
  });
  now.forEach(([t, d], i) => {
    const y = 2.0 + i * 1.14;
    card(s, M, y, 5.9, 1.0, "green");
    s.addText(t, {
      x: M + 0.26, y: y + 0.12, w: 5.4, h: 0.3, margin: 0,
      fontFace: SANS, fontSize: 12.5, bold: true, color: GREEN,
    });
    s.addText(d, {
      x: M + 0.26, y: y + 0.42, w: 5.4, h: 0.5, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 11, color: INK, lineSpacing: 14,
    });
  });

  s.addText("Scales without redesign", {
    x: M + 6.56, y: 1.6, w: 5.6, h: 0.32, margin: 0,
    fontFace: SANS, fontSize: 14, bold: true, color: NAVY,
  });
  next.forEach(([t, d], i) => {
    const y = 2.0 + i * 1.14;
    card(s, M + 6.3, y, 5.9, 1.0, "plain");
    s.addText(t, {
      x: M + 6.56, y: y + 0.12, w: 5.4, h: 0.3, margin: 0,
      fontFace: SANS, fontSize: 12.5, bold: true, color: NAVY,
    });
    s.addText(d, {
      x: M + 6.56, y: y + 0.42, w: 5.4, h: 0.5, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 11, color: INK, lineSpacing: 14,
    });
  });

  s.addText(
    "The scale story is deliberately boring: the same process, more boxes. Nothing about the chain of custody has to change.",
    { x: M, y: 6.62, w: W, h: 0.4, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "11:20-12:00 | Two columns, three clauses each. The strongest single point is zero recurring cost with " +
    "local checkpoints — that is what makes a state cyber cell deployment realistic. Close on the italic line: " +
    "a boring scale story is a credible one."
  );
}

// ══ 14 · Limitations ══════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 7", "Limitations we state before you ask");
  rubric(s, "Criterion 7  ·  15 marks");

  const lims = [
    ["Manipulation detection generalises poorly out-of-distribution", "0.466 accuracy, AUC 0.417 on StyleGAN faces. The checkpoint was trained on face swaps. Published with the caveat attached."],
    ["Audio robustness under compression is weak", "0.375 decision stability on 8 pairs. AAC 64k flips both. The per-minute discontinuity rate saturates on short clips."],
    ["The robustness run covered images and audio, not video", "The video transforms exist in the harness; the stored run did not exercise them. We do not claim video robustness."],
    ["Identity figures are optimistic by construction", "Pairs where no face could be detected are skipped, not counted as errors — which excludes exactly the hard cases."],
    ["A/V consistency is a heuristic, and knows it", "Face-presence versus audio-energy. It withdraws itself from risk fusion on footage that is not a talking head."],
    ["Localization overlays are visualisations, not masks", "High-frequency residual, where blending and recompression artefacts concentrate. Stated in the payload, the UI and the PDF."],
  ];
  lims.forEach(([t, d], i) => {
    const col = i % 2, row = Math.floor(i / 2);
    const x = M + col * 6.25;
    const y = 1.56 + row * 1.62;
    card(s, x, y, 5.95, 1.46, "amber");
    disc(s, x + 0.22, y + 0.2, 0.38, String(i + 1), "amber");
    s.addText(t, {
      x: x + 0.72, y: y + 0.14, w: 5.0, h: 0.52, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 12, bold: true, color: AMBER, lineSpacing: 15,
    });
    s.addText(d, {
      x: x + 0.24, y: y + 0.7, w: 5.48, h: 0.68, margin: 0, valign: "top",
      fontFace: SANS, fontSize: 10.5, color: INK, lineSpacing: 13,
    });
  });

  card(s, M, 6.5, W, 0.62, "navy");
  s.addText(
    "Every one of these is printed in the report the investigating officer receives, beside the score it qualifies.",
    { x: M + 0.3, y: 6.5, w: W - 0.6, h: 0.62, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 12.5, color: ICE }
  );
  s.addNotes(
    "12:00-12:40 | Counter-intuitive but true: this slide gains marks. Naming six real weaknesses, with " +
    "figures, proves you understand your own system — and it disarms the entire hostile half of Q&A because " +
    "you said it first. Deliver it briskly and without apology. Close on the navy line."
  );
}

// ══ 15 · Q&A prep ═════════════════════════════════════════════════════════════
{
  const s = light();
  head(s, "Criterion 7", "Hard questions — and our answers");
  rubric(s, "Criterion 7  ·  15 marks");

  const qa = [
    ["“What is your detection accuracy?”",
     "91.5% on face identity against LFW, precision 1.00. Manipulation is 46.6% out-of-distribution and we publish that — which is why we report indicators, not verdicts."],
    ["“How is this different from any deepfake detector?”",
     "It is identity-first. We answer whether a named consented person is present, then preserve the answer as admissible-format evidence. A detector answers neither."],
    ["“What happens when the media is compressed?”",
     "87.5% of decisions survive 16 real ffmpeg transforms. Perceptual hashes still match copies. And compression pushes scores up, so the risk is false accusation — measured, not guessed."],
    ["“Can this be used to falsely accuse someone?”",
     "That is the failure mode we designed against. Zero false identity matches in 200 pairs, no verdict output, and every limitation printed beside its score."],
    ["“Why SQLite and a monolith instead of real infrastructure?”",
     "Chain of custody is easiest to prove when one process owns the file. A network hop adds attack surface, not integrity. We can scale by adding boxes, not layers."],
    ["“Is any of this mocked for the demo?”",
     "No. Demo input files are labelled as demo input; every score, hash, timestamp and finding comes from the pipeline. Unavailable modules print Unavailable, not a success screen."],
  ];
  qa.forEach(([q, a], i) => {
    const y = 1.54 + i * 0.86;
    card(s, M, y, W, 0.76, i % 2 === 0 ? "plain" : "plain");
    s.addText(q, {
      x: M + 0.26, y: y + 0.04, w: 4.5, h: 0.68, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 11.5, bold: true, italic: true, color: NAVY,
    });
    s.addText(a, {
      x: M + 4.92, y: y + 0.04, w: 7.0, h: 0.68, margin: 0, valign: "middle",
      fontFace: SANS, fontSize: 10.5, color: INK, lineSpacing: 13,
    });
  });

  s.addText(
    "Rule for Q&A: give the number, then the caveat, then stop. Never improvise a figure — if it is not measured, say it is not measured.",
    { x: M, y: 6.78, w: W, h: 0.4, margin: 0,
      fontFace: SANS, fontSize: 12.5, italic: true, color: GREY }
  );
  s.addNotes(
    "Reference slide — do not present it. Keep it up during Q&A. Split the six questions across the team " +
    "beforehand so nobody hesitates. The rule at the bottom is the one that actually wins marks: a " +
    "confident 'we have not measured that' beats an invented number, and an evaluator will test for exactly this."
  );
}

// ══ 16 · Close ════════════════════════════════════════════════════════════════
{
  const s = dark();
  s.addText("DeepTrace", {
    x: M, y: 1.9, w: W, h: 0.95, margin: 0,
    fontFace: SERIF, fontSize: 50, bold: true, color: WHITE,
  });
  s.addText("Match  ·  Analyze  ·  Localize  ·  Trace  ·  Preserve  ·  Respond", {
    x: M, y: 2.92, w: W, h: 0.44, margin: 0,
    fontFace: SANS, fontSize: 19, charSpacing: 0.6, color: ICE,
  });
  s.addText(
    "An impersonation victim needs more than a score. They need to show that the media is not them, " +
    "that a copy is circulating, and that the record will hold up after they hand it over.",
    { x: M, y: 3.7, w: 9.2, h: 1.0, margin: 0,
      fontFace: SANS, fontSize: 15, color: GREY_LT, lineSpacing: 22 }
  );

  const closing = [["91.5%", "identity accuracy"], ["0", "false matches / 200"], ["87.5%", "compression stability"], ["23", "report sections"]];
  closing.forEach(([v, l], i) => {
    const x = M + i * 3.05;
    s.addText(v, {
      x, y: 5.1, w: 2.8, h: 0.6, margin: 0,
      fontFace: SERIF, fontSize: 32, bold: true, color: ICE,
    });
    s.addText(l, {
      x, y: 5.68, w: 2.8, h: 0.3, margin: 0,
      fontFace: SANS, fontSize: 11.5, color: GREY_LT,
    });
  });

  s.addText("Team Algorythm  ·  SIH26_28  ·  Defence & National Security", {
    x: M, y: 6.62, w: W, h: 0.34, margin: 0,
    fontFace: SANS, fontSize: 13, bold: true, color: GREY_LT,
  });
  s.addNotes(
    "12:40-13:00 | Land it in two sentences, using the paragraph on screen. Do not add new information " +
    "here and do not thank the panel for a full minute — leave the four numbers on screen and take questions. " +
    "Slide 15 is your Q&A reference; switch to it if the questioning goes technical."
  );
}

pres.writeFile({ fileName: "DeepTrace_SIH_Round2.2.pptx" })
  .then((f) => console.log("Wrote " + f + " — " + pres.slides.length + " slides"));
