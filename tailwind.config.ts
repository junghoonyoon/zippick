import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}"
  ],
  theme: {
    extend: {
      colors: {
        zippick: {
          ink: "#191f28",
          body: "#4e5968",
          muted: "#8b95a1",
          canvas: "#f6f8fb",
          line: "#e5e8eb",
          blue: "#3182f6"
        }
      },
      boxShadow: {
        panel: "0 18px 44px rgba(15, 23, 42, 0.08)"
      }
    }
  },
  plugins: []
};

export default config;
