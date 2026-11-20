import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}", "./lib/**/*.{ts,tsx}"],
  theme: {
    extend: {
      // Tailwind colours resolve to the CSS tokens in app/globals.css; never put a literal colour here.
      colors: {
        ink: { DEFAULT: "rgb(var(--han-text-rgb) / <alpha-value>)", soft: "rgb(var(--han-text-soft-rgb) / <alpha-value>)", muted: "rgb(var(--han-muted-rgb) / <alpha-value>)" },
        brand: { DEFAULT: "rgb(var(--han-primary-rgb) / <alpha-value>)", dark: "rgb(var(--han-primary-strong-rgb) / <alpha-value>)", light: "rgb(var(--han-primary-rgb) / 0.16)", bright: "rgb(var(--han-primary-bright-rgb) / <alpha-value>)" },
        surface: "rgb(var(--han-panel-rgb) / <alpha-value>)",
        overlay: "rgb(var(--han-overlay-rgb) / <alpha-value>)",
        "on-brand": "rgb(var(--han-on-primary-rgb) / <alpha-value>)",
        ok: { DEFAULT: "rgb(var(--han-ok-rgb) / <alpha-value>)", text: "rgb(var(--han-ok-text-rgb) / <alpha-value>)" },
        warn: { DEFAULT: "rgb(var(--han-warn-rgb) / <alpha-value>)", text: "rgb(var(--han-warn-text-rgb) / <alpha-value>)" },
        info: { DEFAULT: "rgb(var(--han-info-rgb) / <alpha-value>)", text: "rgb(var(--han-info-text-rgb) / <alpha-value>)" },
        danger: { DEFAULT: "rgb(var(--han-danger-rgb) / <alpha-value>)", text: "rgb(var(--han-danger-text-rgb) / <alpha-value>)" },
        wash: "rgb(var(--han-sunken-rgb) / <alpha-value>)",
        line: "rgb(var(--han-line-rgb) / 0.22)",
      },
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"] },
    },
  },
  plugins: [],
};
export default config;
