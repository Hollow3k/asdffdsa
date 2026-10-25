const REPO_URL = "https://github.com/Hollow3k/asdffdsa";

export function LandingPage({ onStart }: { onStart: () => void }) {
  return (
    <div className="landing-root">
      <style>{LANDING_CSS}</style>
      <div className="landing-backdrop" aria-hidden="true" />
      <div className="landing-wash" aria-hidden="true" />

      <div className="landing-shell">
        <header className="landing-header">
          <a className="landing-brand" href="/" aria-label="Wind Procurement home">
            <span className="landing-mark" aria-hidden="true">
              <svg width="19" height="19" viewBox="0 0 32 32">
                <path d="M6 19c4-8 8 4 12-4s6 2 8-2" stroke="currentColor" strokeWidth="2.8" fill="none" strokeLinecap="round" />
              </svg>
            </span>
            <span>Wind Procurement</span>
          </a>
          <a className="landing-repo" href={REPO_URL} target="_blank" rel="noopener noreferrer" aria-label="GitHub repo">
            View on GitHub <span aria-hidden="true">↗</span>
          </a>
        </header>

        <main className="landing-main">
          <section className="landing-card" aria-labelledby="landing-title">
            <p className="landing-kicker">
              <span className="landing-kicker-dot" aria-hidden="true" />
              Day-ahead wind procurement
            </p>
            <h1 id="landing-title">
              Buy with
              <br />
              <em>the wind behind you.</em>
            </h1>
            <p className="landing-sub">
              See tomorrow’s wind forecast, understand its uncertainty, and choose a defensible volume before the market opens.
            </p>
            <div className="landing-actions">
              <button type="button" className="landing-btn landing-btn-primary" onClick={onStart} aria-label="Get started">
                Get started <span aria-hidden="true">→</span>
              </button>
              <span className="landing-note">Powered by Elexon data</span>
            </div>
            <div className="landing-signal" aria-label="Forecast signal">
              <span className="landing-signal-label">Tomorrow’s signal</span>
              <span className="landing-signal-line" aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
                <i />
              </span>
              <span className="landing-signal-value">Wind forecast ready</span>
            </div>
          </section>
        </main>

        <footer className="landing-footer">
          <span>Decision support for a changing sky.</span>
          <span className="landing-footer-rule" aria-hidden="true" />
          <span>Not a trading recommendation</span>
        </footer>
      </div>
    </div>
  );
}

const LANDING_CSS = `
.landing-root {
  position: fixed;
  inset: 0;
  overflow: hidden;
  color: #17334a;
  font-family: "Inter", "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  background: #a9cee0;
}
.landing-backdrop {
  position: absolute;
  inset: -2%;
  background: url("/clouds.jpg") center center / cover no-repeat;
  transform: scale(1.03);
}
.landing-wash {
  position: absolute;
  inset: 0;
  background:
    linear-gradient(90deg, rgba(245, 250, 250, 0.6) 0%, rgba(245, 250, 250, 0.2) 44%, rgba(30, 76, 104, 0.08) 100%),
    linear-gradient(180deg, rgba(255,255,255,0.22) 0%, rgba(227, 242, 245, 0.08) 55%, rgba(18, 50, 70, 0.25) 100%);
}
.landing-shell {
  position: relative;
  z-index: 1;
  display: flex;
  flex-direction: column;
  height: 100%;
  padding: 30px clamp(24px, 5vw, 76px) 24px;
}
.landing-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.landing-brand, .landing-repo {
  display: inline-flex;
  align-items: center;
  color: inherit;
  text-decoration: none;
}
.landing-brand {
  gap: 11px;
  font-size: 14px;
  font-weight: 700;
  letter-spacing: -0.1px;
}
.landing-mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  border: 1px solid rgba(255,255,255,0.7);
  border-radius: 11px;
  color: #fff;
  background: rgba(25, 72, 97, 0.72);
  box-shadow: 0 4px 18px rgba(41, 78, 99, 0.12);
}
.landing-repo {
  gap: 7px;
  padding: 9px 14px;
  border: 1px solid rgba(23, 51, 74, 0.22);
  border-radius: 999px;
  color: #294a60;
  font-size: 12px;
  font-weight: 600;
  transition: background 0.2s ease, border-color 0.2s ease;
}
.landing-repo:hover {
  border-color: rgba(23, 51, 74, 0.42);
  background: rgba(255,255,255,0.28);
}
.landing-main {
  display: flex;
  flex: 1;
  align-items: center;
  padding: 40px 0 60px;
}
.landing-card {
  width: min(100%, 590px);
  padding: clamp(28px, 5vw, 58px);
  border: 1px solid rgba(255,255,255,0.62);
  border-radius: 28px;
  background: rgba(244, 250, 251, 0.68);
  box-shadow: 0 24px 70px rgba(33, 67, 88, 0.14);
  backdrop-filter: blur(12px);
}
.landing-kicker {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 25px;
  color: #4d7184;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.8px;
  text-transform: uppercase;
}
.landing-kicker-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #ee8f56;
  box-shadow: 0 0 0 5px rgba(238, 143, 86, 0.14);
}
.landing-card h1 {
  margin: 0;
  color: #17334a;
  font-size: clamp(44px, 6vw, 78px);
  font-weight: 500;
  letter-spacing: -4px;
  line-height: 0.98;
}
.landing-card h1 em {
  color: #2f6d83;
  font-family: Georgia, "Times New Roman", serif;
  font-weight: 400;
}
.landing-sub {
  max-width: 455px;
  margin: 28px 0 0;
  color: #4d6878;
  font-size: 16px;
  line-height: 1.65;
}
.landing-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 18px;
  margin-top: 36px;
}
.landing-btn {
  display: inline-flex;
  align-items: center;
  gap: 12px;
  padding: 14px 19px 14px 22px;
  border: 0;
  border-radius: 999px;
  font: inherit;
  font-size: 13px;
  font-weight: 700;
  cursor: pointer;
  transition: transform 0.2s ease, box-shadow 0.2s ease, background 0.2s ease;
}
.landing-btn:hover {
  transform: translateY(-2px);
}
.landing-btn-primary {
  color: #fff;
  background: #214e69;
  box-shadow: 0 10px 22px rgba(33, 78, 105, 0.22);
}
.landing-btn-primary:hover {
  background: #173e57;
  box-shadow: 0 13px 25px rgba(33, 78, 105, 0.3);
}
.landing-btn-primary span {
  font-size: 18px;
  font-weight: 400;
  line-height: 0;
}
.landing-note {
  color: #648092;
  font-size: 11px;
  font-weight: 600;
}
.landing-signal {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 14px;
  max-width: 460px;
  margin-top: 42px;
  padding-top: 18px;
  border-top: 1px solid rgba(45, 91, 111, 0.18);
  color: #557486;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.landing-signal-line {
  display: flex;
  align-items: center;
  gap: 4px;
  height: 19px;
}
.landing-signal-line i {
  display: block;
  width: 3px;
  height: 8px;
  border-radius: 4px;
  background: #5f9caf;
  transform: rotate(-24deg);
}
.landing-signal-line i:nth-child(2) { height: 13px; }
.landing-signal-line i:nth-child(3) { height: 17px; background: #ee8f56; }
.landing-signal-line i:nth-child(4) { height: 11px; }
.landing-signal-line i:nth-child(5) { height: 15px; background: #ee8f56; }
.landing-signal-line i:nth-child(6) { height: 8px; }
.landing-signal-line i:nth-child(7) { height: 12px; }
.landing-signal-value {
  color: #2f6d83;
  white-space: nowrap;
}
.landing-footer {
  display: flex;
  align-items: center;
  gap: 13px;
  color: rgba(31, 65, 84, 0.7);
  font-size: 11px;
  font-weight: 600;
}
.landing-footer-rule {
  width: 26px;
  height: 1px;
  background: currentColor;
  opacity: 0.5;
}
.landing-root :focus-visible {
  outline: 3px solid #ee8f56;
  outline-offset: 4px;
}
@media (max-width: 600px) {
  .landing-shell { padding-top: 22px; }
  .landing-repo { padding: 7px 10px; font-size: 11px; }
  .landing-card { border-radius: 22px; }
  .landing-card h1 { letter-spacing: -2.5px; }
  .landing-signal { grid-template-columns: 1fr auto; }
  .landing-signal-line { grid-column: 1 / -1; grid-row: 2; }
  .landing-footer { justify-content: center; text-align: center; }
  .landing-footer span:first-child, .landing-footer-rule { display: none; }
}
@media (prefers-reduced-motion: reduce) {
  .landing-btn { transition: none; }
}
`;
