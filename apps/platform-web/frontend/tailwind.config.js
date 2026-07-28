/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ['class'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        dal: {
          petrol: '#192B2F',
          deep:   '#21393F',
          copper: '#B57548',
          sand:   '#E8E3DB',
          ink:    '#0E1415',
        },
        success:'#20C997', warning:'#F59E0B', danger:'#EF4444',
      },
      fontFamily: { sans: ['Inter','ui-sans-serif','system-ui'] },
      borderRadius: { '2xl':'1.25rem' },
      boxShadow: { soft:'0 8px 30px rgba(0,0,0,.25)', card:'0 12px 40px rgba(0,0,0,.30)' },
    },
  },
  plugins: [],
}
