import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{js,ts,jsx,tsx,mdx}"],
  theme: {
    extend: {
      colors: {
        // SLUICE palette (ТЗ на дизайн)
        ink: {
          primary: "#0A0C0F", // основной фон
          secondary: "#11151A", // фон карточек/панелей
          tertiary: "#1A2027", // ховеры/активные
        },
        text: {
          primary: "#C7D0D9",
          secondary: "#6B7A89",
          muted: "#3A4551",
        },
        accent: {
          primary: "#FF4A1C", // оранжево-красный (кнопки, выделения)
          secondary: "#00A87E", // успех/онлайн
          danger: "#E5484D",
          warning: "#D9A404", // приватные, замки
        },
        line: {
          DEFAULT: "#222A33",
          hover: "#33404D",
        },
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        mono: ["var(--font-jetbrains)", "JetBrains Mono", "monospace"],
      },
      borderRadius: {
        DEFAULT: "4px",
      },
    },
  },
  plugins: [],
};

export default config;
