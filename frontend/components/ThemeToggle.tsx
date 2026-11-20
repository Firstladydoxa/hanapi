"use client";

import { useEffect, useState } from "react";

export const THEME_KEY = "han.theme";
export type Theme = "dark" | "light";

/** Dark is the default; only an explicit saved choice switches to light. Runs before first paint (see app/layout.tsx) so a returning visitor never sees a flash of the wrong theme. */
export const THEME_INIT_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t!=="light"&&t!=="dark"){t="dark"}document.documentElement.setAttribute("data-theme",t)}catch(e){document.documentElement.setAttribute("data-theme","dark")}})();`;

function current(): Theme {
  return document.documentElement.getAttribute("data-theme") === "light" ? "light" : "dark";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>("dark");

  useEffect(() => { setTheme(current()); }, []);

  const toggle = () => {
    const next: Theme = current() === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", next);
    try { window.localStorage.setItem(THEME_KEY, next); } catch { /* ignore: the choice still applies for this visit */ }
    setTheme(next);
  };

  const toLight = theme === "dark";
  return (
    <button type="button" className="han-menu-toggle han-theme-toggle" onClick={toggle} aria-pressed={!toLight}
      aria-label={toLight ? "Switch to light mode" : "Switch to dark mode"} title={toLight ? "Light mode" : "Dark mode"}>
      <span aria-hidden>{toLight ? "☀" : "☾"}</span>
    </button>
  );
}
