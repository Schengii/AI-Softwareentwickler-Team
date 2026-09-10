/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        slate: {
          50: '#F8FAFC',
          400: '#94A3B8',
          800: '#1E293B',
          900: '#0F172A',
        },
        sky: {
          400: '#38BDF8',
        }
      }
    },
  },
  plugins: [],
}
