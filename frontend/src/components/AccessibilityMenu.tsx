"use client";

import { Accessibility, Contrast, RotateCcw, Snowflake, Underline, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";

/**
 * Display preferences this page actually applies, rather than merely announces.
 *
 * Every control here maps to one class or inline style on the document root, so
 * the effect is immediate and survives a reload. None of it is decorative: the
 * primary user is someone reading a distressing forensic finding, and larger
 * text, stronger contrast or no motion may be what makes the page readable at
 * all. Browser zoom can do some of this, but it is not discoverable to everyone,
 * and it does not carry the contrast and motion settings.
 */

const STORAGE_KEY = "deeptrace.display-preferences";

/** Root zoom rather than a root font-size: see applyPreferences. */
const TEXT_STEPS = [
  { key: "normal", label: "Normal", zoom: 1 },
  { key: "large", label: "Large", zoom: 1.15 },
  { key: "largest", label: "Largest", zoom: 1.3 },
] as const;

type TextSize = (typeof TEXT_STEPS)[number]["key"];

type Preferences = {
  textSize: TextSize;
  highContrast: boolean;
  underlineLinks: boolean;
  reduceMotion: boolean;
};

const DEFAULTS: Preferences = {
  textSize: "normal",
  highContrast: false,
  underlineLinks: false,
  reduceMotion: false,
};

function applyPreferences(preferences: Preferences) {
  const root = document.documentElement;
  const step = TEXT_STEPS.find((item) => item.key === preferences.textSize) ?? TEXT_STEPS[0];
  // This stylesheet sizes in pixels, so raising the root font size alone would
  // enlarge the text and leave every box around it unchanged. Zooming the root
  // scales the layout with the text and lets the existing media queries reflow.
  root.style.zoom = step.zoom === 1 ? "" : String(step.zoom);
  root.classList.toggle("a11y-contrast", preferences.highContrast);
  root.classList.toggle("a11y-underline", preferences.underlineLinks);
  root.classList.toggle("a11y-still", preferences.reduceMotion);
}

/** Stored choices, falling back to what the operating system already says. */
function readStored(): Preferences {
  let stored: Partial<Preferences> = {};
  try {
    stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || "{}") as Partial<Preferences>;
  } catch {
    // A corrupt or blocked store is not an error worth surfacing; defaults apply.
  }
  const systemReduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches === true;
  return {
    textSize: TEXT_STEPS.some((step) => step.key === stored.textSize)
      ? (stored.textSize as TextSize)
      : DEFAULTS.textSize,
    highContrast: stored.highContrast === true,
    underlineLinks: stored.underlineLinks === true,
    // The operating system's setting is the default until this menu overrides it.
    reduceMotion: typeof stored.reduceMotion === "boolean" ? stored.reduceMotion : systemReduceMotion,
  };
}

/*
 * localStorage is an external store, so it is read through useSyncExternalStore
 * rather than copied into state on mount. That keeps the server's render (which
 * has no storage and no media queries) from disagreeing with the browser's, and
 * it means a change made in one tab reaches the others.
 */
const listeners = new Set<() => void>();
let cached: Preferences | null = null;

function notify() {
  for (const listener of listeners) listener();
}

function onStorageEvent(event: StorageEvent) {
  if (event.key !== null && event.key !== STORAGE_KEY) return;
  cached = null;
  notify();
}

function subscribe(onChange: () => void) {
  listeners.add(onChange);
  if (listeners.size === 1) window.addEventListener("storage", onStorageEvent);
  return () => {
    listeners.delete(onChange);
    if (listeners.size === 0) window.removeEventListener("storage", onStorageEvent);
  };
}

/** Must return a stable reference between calls, hence the cache. */
function getSnapshot(): Preferences {
  if (!cached) cached = readStored();
  return cached;
}

function getServerSnapshot(): Preferences {
  return DEFAULTS;
}

function writePreferences(next: Preferences) {
  cached = next;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Preferences still apply for this visit even when storage is unavailable.
  }
  notify();
}

export function AccessibilityMenu() {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const preferences = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);

  // The document root is the external system these preferences drive; keeping it
  // in step with the stored value is exactly an effect's job.
  useEffect(() => { applyPreferences(preferences); }, [preferences]);

  const update = useCallback(
    (change: Partial<Preferences>) => writePreferences({ ...getSnapshot(), ...change }),
    [],
  );

  // Escape closes, and a click outside closes: a panel that traps the pointer is
  // its own accessibility problem.
  useEffect(() => {
    if (!open) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === "Escape") setOpen(false); };
    const onPointerDown = (event: PointerEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, [open]);

  const changed =
    preferences.textSize !== DEFAULTS.textSize ||
    preferences.highContrast ||
    preferences.underlineLinks ||
    preferences.reduceMotion;

  return (
    <div className="a11y-menu" ref={containerRef}>
      <button
        type="button"
        className="a11y-trigger"
        aria-expanded={open}
        aria-controls="a11y-panel"
        onClick={() => setOpen((value) => !value)}
      >
        <Accessibility size={17} aria-hidden="true" />
        <span>Accessibility</span>
        {changed && <em className="a11y-dot" aria-label="display settings changed" />}
      </button>

      {open && (
        <div className="a11y-panel" id="a11y-panel" role="dialog" aria-label="Display preferences">
          <div className="a11y-panel-head">
            <div>
              <h2>Display preferences</h2>
              <p>Applied straight away and remembered on this device.</p>
            </div>
            <button type="button" className="icon-button" onClick={() => setOpen(false)} aria-label="Close display preferences">
              <X size={16} />
            </button>
          </div>

          <div className="a11y-group">
            <span id="a11y-text-size">Text and layout size</span>
            <div className="a11y-sizes" role="group" aria-labelledby="a11y-text-size">
              {TEXT_STEPS.map((step) => (
                <button
                  key={step.key}
                  type="button"
                  aria-pressed={preferences.textSize === step.key}
                  onClick={() => update({ textSize: step.key })}
                >
                  {step.label}
                </button>
              ))}
            </div>
          </div>

          <Toggle
            icon={<Contrast size={16} aria-hidden="true" />}
            label="Higher contrast"
            on={preferences.highContrast}
            onChange={(on) => update({ highContrast: on })}
          />
          <Toggle
            icon={<Underline size={16} aria-hidden="true" />}
            label="Underline every link"
            on={preferences.underlineLinks}
            onChange={(on) => update({ underlineLinks: on })}
          />
          <Toggle
            icon={<Snowflake size={16} aria-hidden="true" />}
            label="Reduce motion"
            on={preferences.reduceMotion}
            onChange={(on) => update({ reduceMotion: on })}
          />

          <button type="button" className="a11y-reset" onClick={() => update(DEFAULTS)} disabled={!changed}>
            <RotateCcw size={13} aria-hidden="true" /> Reset to standard display
          </button>

          <p className="a11y-foot">
            These settings change how this page looks on your device only. They do not alter any
            case, hash, finding or report.
          </p>
        </div>
      )}
    </div>
  );
}

function Toggle({ icon, label, on, onChange }: {
  icon: React.ReactNode;
  label: string;
  on: boolean;
  onChange: (on: boolean) => void;
}) {
  return (
    <button type="button" className="a11y-toggle" aria-pressed={on} onClick={() => onChange(!on)}>
      {icon}
      <span>{label}</span>
      <em className="a11y-state">{on ? "ON" : "OFF"}</em>
    </button>
  );
}
