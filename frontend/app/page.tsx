import Link from "next/link";

const capabilities = [
  { number: "01", icon: "✧", title: "Translation support", copy: "Turn source text into a strong first draft, ready for your expertise." },
  { number: "02", icon: "⌘", title: "Terminology that stays true", copy: "Keep names, meaning and approved language consistent." },
  { number: "03", icon: "◈", title: "Quality assistance", copy: "Spot issues, review changes and strengthen every segment." },
];

const steps = [
  { n: "1", title: "Ask HAN", copy: "Chat naturally. Share a text and HAN works out the language for you." },
  { n: "2", title: "Receive a draft", copy: "A first translation arrives with warnings for anything that needs care." },
  { n: "3", title: "Review and refine", copy: "Edit every segment with TNI terminology and approved knowledge beside you." },
  { n: "4", title: "Approve", copy: "Only a human reviewer can approve. TNI decides what is published." },
];

const facts = [
  { value: "400+", label: "languages in controlled testing" },
  { value: "100%", label: "human-approved output" },
  { value: "TNI", label: "approved terminology built in" },
];

function HanEmblem() {
  return (
    <svg className="landing-emblem" viewBox="0 0 200 200" role="img" aria-label="HAN logo">
      <defs>
        <linearGradient id="han-gold" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(var(--han-secondary-bright-rgb))" />
          <stop offset=".5" stopColor="rgb(var(--han-secondary-rgb))" />
          <stop offset="1" stopColor="rgb(var(--han-secondary-strong-rgb))" />
        </linearGradient>
        <linearGradient id="han-gold-fill" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="rgb(var(--han-secondary-rgb))" stopOpacity=".28" />
          <stop offset="1" stopColor="rgb(var(--han-primary-strong-rgb))" stopOpacity=".18" />
        </linearGradient>
      </defs>
      <path d="M52 14H148A38 38 0 0 1 186 52V148A38 38 0 0 1 148 186H14V52A38 38 0 0 1 52 14Z" fill="url(#han-gold-fill)" stroke="url(#han-gold)" strokeWidth="5" />
      <path d="M58 30H142A28 28 0 0 1 170 58V142A28 28 0 0 1 142 170H30V58A28 28 0 0 1 58 30Z" fill="none" stroke="url(#han-gold)" strokeWidth="1.6" strokeOpacity=".65" />
      <path d="M14 150L50 186" stroke="url(#han-gold)" strokeWidth="1.6" strokeOpacity=".7" />
      <path d="M70 62H92V90H108V62H130V138H108V110H92V138H70Z" fill="url(#han-gold)" />
      <path d="M62 62H78M122 62H138M62 138H78M122 138H138" stroke="url(#han-gold)" strokeWidth="5" strokeLinecap="square" />
    </svg>
  );
}

function Hologram() {
  return (
    <div className="landing-holo" aria-hidden="true">
      <div className="landing-holo-grid" />
      <div className="landing-orbit landing-orbit-a" />
      <div className="landing-orbit landing-orbit-b" />
      <div className="landing-orbit landing-orbit-c" />
      <div className="landing-holo-core">
        <span className="landing-core-scan" />
        <HanEmblem />
        <span className="landing-core-caption">LANGUAGE INTELLIGENCE</span>
      </div>
      <span className="landing-holo-node node-one">MEANING</span>
      <span className="landing-holo-node node-two">CONTEXT</span>
      <span className="landing-holo-node node-three">HUMAN REVIEW</span>
      <span className="landing-holo-cross cross-one" />
      <span className="landing-holo-cross cross-two" />
    </div>
  );
}

export default function Home() {
  return (
    <main className="han-landing">
      <div className="landing-atmosphere" aria-hidden="true">
        <div className="landing-stars" />
        <div className="landing-wall-grid" />
        <div className="landing-glow landing-glow-violet" />
        <div className="landing-glow landing-glow-gold" />
      </div>

      <header className="landing-nav">
        <Link href="/" className="landing-brand" aria-label="HAN home">
          <span className="landing-brand-mark">H</span>
          <span>HAN<span className="landing-brand-dot">.</span></span>
          <span className="landing-brand-divider" />
          <span className="landing-brand-by">TNI LANGUAGE INTELLIGENCE</span>
        </Link>
        <nav className="landing-nav-links" aria-label="Main navigation">
          <a href="#how-it-helps">How HAN helps</a>
          <a href="#how-it-works">How it works</a>
          <a href="#human-first">Human-first</a>
          <Link href="/login" className="landing-login-link">Translator sign in <span aria-hidden="true">↗</span></Link>
        </nav>
      </header>

      <section className="landing-hero" aria-labelledby="landing-title">
        <div className="landing-copy">
          <div className="landing-status"><span className="landing-status-dot" /> TNI TRANSLATION ASSISTANT <span className="landing-status-line" /></div>
          <p className="landing-kicker">A new intelligence for every language.</p>
          <h1 id="landing-title">I am HAN,<br /><span>the TNI Translation</span><br /><em>Assistant.</em></h1>
          <p className="landing-intro">I help translators move from first draft to confident, human-approved translations — with context, terminology and quality support at every step.</p>
          <div className="landing-actions">
            <Link href="/login" className="landing-primary-cta">Enter HAN <span aria-hidden="true">↗</span></Link>
            <a href="#how-it-helps" className="landing-secondary-cta"><span className="landing-play-icon">↓</span> Discover what I do</a>
          </div>
          <div className="landing-proof">
            <span className="landing-proof-mark">✦</span>
            <span>AI prepares the draft.</span>
            <span className="landing-proof-sep">/</span>
            <strong>You decide the meaning.</strong>
          </div>
        </div>
        <div className="landing-visual"><Hologram /><div className="landing-visual-caption"><span>HAN / CORE SYSTEM</span><span>HUMAN-IN-THE-LOOP <i /></span></div></div>
        <div className="landing-scroll-cue"><span /> SCROLL TO EXPLORE</div>
      </section>

      <section className="landing-capabilities" id="how-it-helps">
        <div className="landing-section-heading">
          <div><p className="landing-eyebrow">INTELLIGENCE IN SERVICE OF PEOPLE</p><h2>More than a first draft.</h2></div>
          <p>Practical support for the craft of translation.<br />Clear, focused, always under your control.</p>
        </div>
        <div className="landing-capability-grid">
          {capabilities.map((item) => (
            <article className="landing-capability" key={item.number}>
              <div className="landing-capability-top"><span>{item.number} / 03</span><span className="landing-capability-icon">{item.icon}</span></div>
              <h3>{item.title}</h3><p>{item.copy}</p><span className="landing-card-rule" />
            </article>
          ))}
        </div>
      </section>

      <section className="landing-steps" id="how-it-works" aria-labelledby="steps-title">
        <div className="landing-section-heading">
          <div><p className="landing-eyebrow">FROM FIRST WORD TO FINAL APPROVAL</p><h2 id="steps-title">How I work with you.</h2></div>
          <p>Four simple steps.<br />You stay in charge of every one.</p>
        </div>
        <ol className="landing-step-list">
          {steps.map((x) => (
            <li className="landing-step" key={x.n}><span className="landing-step-n">{x.n}</span><h3>{x.title}</h3><p>{x.copy}</p></li>
          ))}
        </ol>
        <div className="landing-facts">
          {facts.map((f) => <div key={f.label}><strong>{f.value}</strong><span>{f.label}</span></div>)}
        </div>
      </section>

      <section className="landing-human" id="human-first">
        <div className="landing-human-orbit" aria-hidden="true"><span /><span /><span /></div>
        <p className="landing-eyebrow">THE MOST IMPORTANT PART OF THE SYSTEM</p>
        <h2>Your intelligence.<br /><span>My assistance.</span></h2>
        <p className="landing-human-copy">HAN suggests. You review, refine and approve. The translator remains the final authority — because language belongs to people.</p>
        <div className="landing-human-stamp"><span>✦</span> HUMAN APPROVAL ALWAYS</div>
      </section>

      <footer className="landing-footer">
        <div className="landing-footer-brand"><span className="landing-brand-mark">H</span><span>HAN<span className="landing-brand-dot">.</span></span></div>
        <p>AI translates. Humans understand. TNI decides.</p>
        <Link href="/login" className="landing-footer-cta">Begin your session <span aria-hidden="true">↗</span></Link>
        <span className="landing-copyright">© TNI · TRANSLATORS NETWORK INTERNATIONAL</span>
      </footer>
    </main>
  );
}
