/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        background: "#09090b",
        card: "#18181b",
        border: "#27272a",
        primary: {
          DEFAULT: "#3b82f6",
          dark: "#2563eb"
        },
        accent: "#ef4444",
        muted: "#71717a",
      },
      fontFamily: {
        sans: ['Outfit', 'Inter', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
