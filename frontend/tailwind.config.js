/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Instrument panel, not war room: deep desaturated slate, bone-white
        // foreground, one restrained signal color. Saturation is reserved for
        // encoding reliability, never decoration.
        base: "#14181d",
        panel: "#1b2027",
        edge: "#2a313b",
        bone: "#e7e3d8",
        muted: "#8b93a0",
        faint: "#5a6270",
        signal: "#d98e32",
        thermal: "#8a5a4a",
      },
      fontFamily: {
        ui: [
          "Inter",
          "SF Pro Text",
          "Segoe UI",
          "system-ui",
          "sans-serif",
        ],
        mono: [
          "JetBrains Mono",
          "SFMono-Regular",
          "Menlo",
          "Consolas",
          "monospace",
        ],
      },
    },
  },
  plugins: [],
};
