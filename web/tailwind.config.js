/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        term: {
          bg: "#0B0E14",
          card: "#11151F",
          border: "#1E2638",
          hover: "#1A2030",
          text: "#E2E8F0",
          muted: "#64748B",
          accent: "#38BDF8",
          green: "#10B981",
          red: "#EF4444",
          yellow: "#F59E0B",
        }
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Monaco', 'Consolas', 'monospace'],
      }
    },
  },
  plugins: [],
}
