/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./templates/login.html'],
  theme: {
    extend: {
      colors: {
        // 2026-10-09 主人指定：登入頁統一成後台 ADMIN CENTER 深色賽博風。
        'surface-dim': '#0b0f17',
        'background': '#0b0f17',
        'surface-container': '#131924',
        'surface-container-high': '#222d42',
        'on-surface': '#e6edf7',
        'on-surface-variant': '#94a3b8',
        'outline-variant': '#2d3b54',
        'primary-green': '#00F0FF',
        'primary-green-hover': '#00c2cf',
        'line-green': '#06C755',
        'line-green-hover': '#05b34c',
        'text-main': '#e6edf7',
        'primary-fixed': '#00F0FF',
        'on-primary-fixed': '#00363a'
      },
      fontFamily: {
        'body-md': ['Noto Sans TC', 'sans-serif'],
        'label-caps': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
        'display-lg': ['Chakra Petch', 'Noto Sans TC', 'sans-serif']
      }
    }
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')]
};
