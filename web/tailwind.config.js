/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#0e1420",
        panel: "#161e2d",
        panel2: "#1c2637",
        line: "#28324a",
        ink: "#e6ebf2",
        muted: "#8a97ab",
        accent: "#4d9fff",
        transport: "#f0763c",
        ran: "#4d9fff",
        shared: "#a679e8",
        good: "#3fbf87",
        warn: "#e7b53f",
        bad: "#e35d6a",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
    },
  },
  plugins: [],
};
