"use client";

import {
  FaExternalLinkAlt as ExternalLink,
  FaBars as Menu,
  FaShieldAlt as ShieldCheck,
  FaTimes as X,
  FaCircle as SeparatorDot,
} from "react-icons/fa";
import { useState } from "react";
import { AccessibilityMenu } from "@/components/AccessibilityMenu";
import { APP, EXTERNAL_LINKS, NAV_ITEMS } from "@/config/constants";
import type { ViewKey } from "@/types";

export function Header({ current, onNavigate }: { current: ViewKey; onNavigate: (view: ViewKey) => void }) {
  const [open, setOpen] = useState(false);

  return (
    <>
      {/* First focusable element on the page: keyboard and screen-reader users
          should not have to walk the whole header to reach the content. */}
      <a className="skip-link" href="#main-content">Skip to main content</a>
      <div className="gov-strip" aria-hidden="true" />
      <div className="official-note">
        <div className="page-shell official-note-inner">
          <span>भारत सरकार शैली से प्रेरित नागरिक सहायता इंटरफ़ेस</span>
          <SeparatorDot className="official-note-dot" size={5} aria-hidden="true" />
          <span>{APP.prototypeNotice}</span>
        </div>
      </div>
      <header className="site-header">
        <div className="page-shell header-main">
          <button className="brand" onClick={() => onNavigate("home")} aria-label="DeepTrace home">
            <span className="brand-mark"><ShieldCheck size={26} /></span>
            <span>
              <strong>{APP.name}</strong>
              <small>{APP.descriptor}</small>
            </span>
          </button>

          <div className="header-actions">
            <a className="header-link" href={EXTERNAL_LINKS.cybercrimePortal} target="_blank" rel="noreferrer">
              Official Cybercrime Portal <ExternalLink size={14} />
            </a>
            <AccessibilityMenu />
            <button className="mobile-menu" onClick={() => setOpen((value) => !value)} aria-label="Toggle navigation">
              {open ? <X /> : <Menu />}
            </button>
          </div>
        </div>
        <nav className={`primary-nav ${open ? "open" : ""}`} aria-label="Primary navigation">
          <div className="page-shell nav-inner">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                onClick={() => {
                  onNavigate(item.key);
                  setOpen(false);
                }}
                className={current === item.key || (current === "case" && item.key === "cases") ? "active" : ""}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>
      </header>
    </>
  );
}
