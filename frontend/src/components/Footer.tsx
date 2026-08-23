import { APP, EXTERNAL_LINKS } from "@/config/constants";

export function Footer() {
  return (
    <footer className="site-footer">
      <div className="page-shell footer-grid">
        <div>
          <strong>{APP.name}</strong>
          <p>Pre-reporting evidence preservation and analysis support for digital impersonation incidents.</p>
        </div>
        <div>
          <strong>Important</strong>
          <p>Analysis outputs are forensic signals and analytical aids, not proof of manipulation, identity, authorship, or criminal conduct.</p>
        </div>
        <div>
          <strong>Official reporting</strong>
          <p><a href={EXTERNAL_LINKS.cybercrimePortal} target="_blank" rel="noreferrer">National Cyber Crime Reporting Portal</a></p>
        </div>
      </div>
      <div className="footer-bottom">{APP.team} · {APP.prototypeNotice}</div>
    </footer>
  );
}
