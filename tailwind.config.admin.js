/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./templates/admin.html', './templates/admin_components/**/*.html'],
  theme: {
    extend: {
      colors: {
        'surface': '#0b0f17',
        'surface-container': '#131924',
        'surface-container-low': '#1a2232',
        'surface-container-high': '#222d42',
        'surface-container-highest': '#2b3852',
        'primary-fixed': '#00F0FF',
        'on-primary-fixed': '#00363a',
        'secondary-container': '#fe6b00',
        'outline-variant': '#2d3b54',
        'on-surface-variant': '#94a3b8',
        'error': '#ff4655',
        'line-green': '#06C755',
        'line-green-hover': '#05b34c',
        'primary-green': '#06C755',
        'primary-green-hover': '#05b34c'
      },
      fontFamily: {
        'display-lg': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
        'headline-md': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
        'label-caps': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
        'body-md': ['Noto Sans TC', 'sans-serif']
      }
    }
  },
  plugins: []
};
