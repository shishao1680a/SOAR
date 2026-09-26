/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./templates/login.html'],
  theme: {
    extend: {
      colors: {
        'surface-dim': '#e9edf3',
        'background': '#f5f7fa',
        'primary-green': '#0f5238',
        'primary-green-hover': '#0c412c',
        'line-green': '#06C755',
        'line-green-hover': '#05b34c',
        'text-main': '#181c20',
        'primary-fixed': '#2f7d32'
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
