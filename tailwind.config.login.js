/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./templates/login.html'],
  theme: {
    extend: {
      colors: {
        'surface-dim': '#131313',
        'background': '#0f1419',
        'primary-green': '#0f5238',
        'primary-green-hover': '#0c412c',
        'line-green': '#06C755',
        'line-green-hover': '#05b34c',
        'text-main': '#181c20',
        'primary-fixed': '#c3f400'
      },
      fontFamily: {
        'body-md': ['Hanken Grotesk', 'Noto Sans TC', 'sans-serif'],
        'label-caps': ['JetBrains Mono', 'monospace'],
        'display-lg': ['Anybody', 'Noto Sans TC', 'sans-serif']
      }
    }
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')]
};
