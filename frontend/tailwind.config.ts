import type { Config } from "tailwindcss";

/**
 * Academic Modernist design system.
 *
 * Tokens are the canonical set from the `tailwind.config` blocks in
 * ai_course_content_suite/(screen)/code.html, cross-checked against
 * academic_modernist/DESIGN.md. Where the two disagree, code.html wins
 * (it is what rendered the reference screens) — notably the radius scale.
 * Elevation tokens come from DESIGN.md "Elevation & Depth".
 */
const fontStack = (primary: string): string[] => [primary, "system-ui", "sans-serif"];

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        surface: "#f7f9fb",
        "surface-dim": "#d8dadc",
        "surface-bright": "#f7f9fb",
        "surface-container-lowest": "#ffffff",
        "surface-container-low": "#f2f4f6",
        "surface-container": "#eceef0",
        "surface-container-high": "#e6e8ea",
        "surface-container-highest": "#e0e3e5",
        "surface-variant": "#e0e3e5",
        "surface-tint": "#465c9b",
        "on-surface": "#191c1e",
        "on-surface-variant": "#444650",
        "inverse-surface": "#2d3133",
        "inverse-on-surface": "#eff1f3",
        outline: "#757681",
        "outline-variant": "#c5c6d2",
        primary: "#142d6a",
        "on-primary": "#ffffff",
        "primary-container": "#2e4482",
        "on-primary-container": "#9eb3f9",
        "inverse-primary": "#b4c5ff",
        "primary-fixed": "#dbe1ff",
        "primary-fixed-dim": "#b4c5ff",
        "on-primary-fixed": "#00174b",
        "on-primary-fixed-variant": "#2d4381",
        secondary: "#006c49",
        "on-secondary": "#ffffff",
        "secondary-container": "#6cf8bb",
        "on-secondary-container": "#00714d",
        "secondary-fixed": "#6ffbbe",
        "secondary-fixed-dim": "#4edea3",
        "on-secondary-fixed": "#002113",
        "on-secondary-fixed-variant": "#005236",
        tertiary: "#3c0092",
        "on-tertiary": "#ffffff",
        "tertiary-container": "#5517bf",
        "on-tertiary-container": "#c1a8ff",
        "tertiary-fixed": "#e9ddff",
        "tertiary-fixed-dim": "#d0bcff",
        "on-tertiary-fixed": "#23005c",
        "on-tertiary-fixed-variant": "#5516be",
        error: "#ba1a1a",
        "on-error": "#ffffff",
        "error-container": "#ffdad6",
        "on-error-container": "#93000a",
        background: "#f7f9fb",
        "on-background": "#191c1e",
        // Status accents (amber has no MD token; from code.html "Pending Review")
        warning: "#92400e",
        "warning-container": "#fef3c7",
        "warning-outline": "#fcd34d",
      },
      fontFamily: {
        "display-lg": fontStack("Public Sans"),
        "headline-lg": fontStack("Public Sans"),
        "headline-lg-mobile": fontStack("Public Sans"),
        "headline-md": fontStack("Public Sans"),
        "body-lg": fontStack("Inter"),
        "body-md": fontStack("Inter"),
        "label-md": fontStack("Inter"),
        "label-sm": fontStack("Inter"),
        display: fontStack("Public Sans"),
        sans: fontStack("Inter"),
      },
      fontSize: {
        "display-lg": ["48px", { lineHeight: "56px", letterSpacing: "-0.02em", fontWeight: "700" }],
        "headline-lg": [
          "32px",
          { lineHeight: "40px", letterSpacing: "-0.01em", fontWeight: "600" },
        ],
        "headline-lg-mobile": ["24px", { lineHeight: "32px", fontWeight: "600" }],
        "headline-md": ["24px", { lineHeight: "32px", fontWeight: "600" }],
        "body-lg": ["18px", { lineHeight: "28px", fontWeight: "400" }],
        "body-md": ["16px", { lineHeight: "24px", fontWeight: "400" }],
        "label-md": ["14px", { lineHeight: "20px", letterSpacing: "0.01em", fontWeight: "500" }],
        "label-sm": ["12px", { lineHeight: "16px", fontWeight: "600" }],
      },
      borderRadius: {
        DEFAULT: "0.25rem",
        sm: "0.125rem",
        md: "0.375rem",
        lg: "0.5rem",
        xl: "0.75rem",
        "2xl": "1rem",
        full: "9999px",
      },
      spacing: {
        base: "4px",
        xs: "4px",
        sm: "8px",
        md: "16px",
        lg: "24px",
        xl: "40px",
        gutter: "24px",
        "margin-mobile": "16px",
        "margin-desktop": "48px",
      },
      boxShadow: {
        // DESIGN.md: Level 1 = faint; Level 2 = active elements / modals.
        "level-1": "0 1px 2px rgba(46, 68, 130, 0.06)",
        "level-2": "0 4px 12px rgba(46, 68, 130, 0.08)",
        focus: "0 0 0 2px rgba(20, 45, 106, 0.35)",
      },
    },
  },
  plugins: [],
} satisfies Config;
