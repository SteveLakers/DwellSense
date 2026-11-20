import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      // Text tones (fg, fg-2, fg-3 and the severity DEFAULTs) pass WCAG AA (4.5:1) on canvas, surface,
      // surface-2 and their own soft fill. fg-3 drops below AA on surface-3, so avoid that pairing.
      colors: {
        canvas: "#F2F2EE",
        surface: { DEFAULT: "#FFFFFF", 2: "#E9E9E4", 3: "#DDDDD6" },
        line: { DEFAULT: "#D5D4CD", strong: "#151515" },
        fg: { DEFAULT: "#151515", 2: "#45453F", 3: "#63625B" },
        // Dark bands (navbar, footer, call-to-action strips).
        ink: { DEFAULT: "#151515", 2: "#24241F", line: "#3B3B35", muted: "#B4B3AA" },
        // Taxi yellow: fills, highlights and yellow-on-ink text only; never yellow text on a light surface.
        brand: { DEFAULT: "#FFCC00", deep: "#F2BE00", soft: "#FFF1B8" },
        good: { DEFAULT: "#16754A", fill: "#1E8C5A", soft: "#E2F0E8" },
        typical: { DEFAULT: "#5E5D56", fill: "#A3A29A", soft: "#EAEAE4" },
        bad: { DEFAULT: "#BE321A", fill: "#DD4527", soft: "#FAE6E0" },
        tip: { DEFAULT: "#1D5BC6", fill: "#2F6FE0", soft: "#E4ECFA" },
      },
      fontFamily: {
        sans: ["var(--font-archivo)", "Arial Narrow", "system-ui", "sans-serif"],
      },
      borderRadius: {
        DEFAULT: "4px",
        lg: "8px",
      },
      screens: {
        "min-1550": "1550px",
      },
    },
  },
  plugins: [],
};

export default config;
