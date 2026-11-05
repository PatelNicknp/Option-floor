/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        paper: "#f3ecdf",
        ink: "#221c16",
        card: "#fffaf3",
        line: "#e4d7c4",
        copper: "#b85c38",
        call: "#1b7a49",
        put: "#a33b32",
        muted: "#6e6458",
      },
      fontFamily: {
        serif: ["Fraunces", "Georgia", "serif"],
        sans: ["Outfit", "Segoe UI", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(34, 28, 22, 0.04)",
      },
    },
  },
  plugins: [],
}
