/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,jsx,ts,tsx}",
    "./public/index.html",
  ],
  darkMode: "class", // enable class-based dark mode
  theme: {
    extend: {
      colors: {
        primary: {
          light: "#3b82f6", // blue-500
          dark: "#2563eb", // blue-600
        },
        secondary: {
          light: "#10b981", // emerald-500
          dark: "#059669", // emerald-600
        },
        background: {
          light: "#ffffff",
          dark: "#1f2937",
        },
        surface: {
          light: "#f9fafb",
          dark: "#111827",
        },
        text: {
          light: "#111827",
          dark: "#f9fafb",
        },
      },
    },
  },
  plugins: [],
};
