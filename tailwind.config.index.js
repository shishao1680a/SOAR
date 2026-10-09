/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: 'class',
  content: ['./templates/index.html'],
  theme: {
    extend: {
      colors: {
        'on-error': '#690005',
        'on-secondary-container': '#572000',
        'on-tertiary-container': '#006f7f',
        'surface-dim': '#131313',
        'tertiary': '#ffffff',
        'outline': '#8e9379',
        'error': '#ffb4ab',
        'secondary-fixed': '#ffdbcc',
        'on-secondary': '#561f00',
        'surface-container-lowest': '#0e0e0e',
        'on-primary-fixed-variant': '#3c4d00',
        'on-tertiary-fixed': '#001f25',
        'inverse-surface': '#e5e2e1',
        'on-surface-variant': '#c4c9ac',
        'surface-container': '#201f1f',
        'tertiary-fixed': '#a5eeff',
        'background': '#131313',
        'surface-bright': '#393939',
        'on-primary-container': '#556d00',
        'surface-container-high': '#2a2a2a',
        'tertiary-fixed-dim': '#00daf8',
        'error-container': '#93000a',
        'tertiary-container': '#a5eeff',
        'on-primary': '#283500',
        'primary-fixed': '#c3f400',
        'primary-fixed-dim': '#abd600',
        'secondary-container': '#fe6b00',
        'on-secondary-fixed': '#351000',
        'surface-tint': '#abd600',
        'on-primary-fixed': '#161e00',
        'on-error-container': '#ffdad6',
        'on-tertiary-fixed-variant': '#004e5a',
        'surface-variant': '#353534',
        'inverse-on-surface': '#313030',
        'inverse-primary': '#506600',
        'primary-container': '#c3f400',
        'on-background': '#e5e2e1',
        'secondary': '#ffb693',
        'surface': '#131313',
        'on-surface': '#e5e2e1',
        'on-secondary-fixed-variant': '#7a3000',
        'on-tertiary': '#00363f',
        'surface-container-highest': '#353534',
        'surface-container-low': '#1c1b1b',
        'secondary-fixed-dim': '#ffb693',
        'primary': '#ffffff',
        'outline-variant': '#444933',
        'line-green': '#06C755'
      },
      spacing: {
        'unit-4': '16px',
        'unit-2': '8px',
        'margin-desktop': '48px',
        'unit-1': '4px',
        'unit-16': '64px',
        'gutter': '24px',
        'unit-8': '32px',
        'unit-12': '48px',
        'unit-6': '24px',
        'base': '4px',
        'margin-mobile': '16px'
      },
      fontFamily: {
        'body-md': ['Hanken Grotesk', 'Noto Sans TC', 'sans-serif'],
        'body-lg': ['Hanken Grotesk', 'Noto Sans TC', 'sans-serif'],
        'label-caps': ['JetBrains Mono', 'monospace'],
        'display-lg': ['Anybody', 'Noto Sans TC', 'sans-serif'],
        'headline-md': ['Anybody', 'Noto Sans TC', 'sans-serif'],
        'headline-lg': ['Anybody', 'Noto Sans TC', 'sans-serif']
      },
      fontSize: {
        'body-md': ['16px', { lineHeight: '24px', fontWeight: '400' }],
        'label-caps': ['12px', { lineHeight: '16px', letterSpacing: '0.1em', fontWeight: '700' }],
        'display-lg': ['72px', { lineHeight: '72px', letterSpacing: '-0.04em', fontWeight: '800' }],
        'headline-md': ['24px', { lineHeight: '28px', fontWeight: '700' }],
        'headline-lg': ['48px', { lineHeight: '52px', letterSpacing: '-0.02em', fontWeight: '700' }],
        'body-lg': ['18px', { lineHeight: '28px', fontWeight: '400' }]
      }
    }
  },
  plugins: [require('@tailwindcss/forms'), require('@tailwindcss/container-queries')]
};

/* =============================================================
   2026-10-09 主人指定：全站統一成「後台 ADMIN CENTER」的深色賽博風。
   -------------------------------------------------------------
   原本 2026-09-26 的「明亮白底」覆蓋已移除；改成與
   tailwind.config.admin.js 對齊的色票。

   ⚠️ 改完一定要重新建置樣式，否則畫面不會變：
      npm run build:css
   ============================================================= */
const THEME_OVERRIDES = {
  // ---- 底層表面：深藍黑底、逐層提亮 ----
  background: '#0b0f17',
  surface: '#0b0f17',
  'surface-dim': '#0b0f17',
  'surface-bright': '#1a2232',
  'surface-container-lowest': '#0b0f17',
  'surface-container-low': '#101720',
  'surface-container': '#131924',
  'surface-container-high': '#222d42',
  'surface-container-highest': '#2b3852',
  'surface-variant': '#222d42',

  // ---- 文字 ----
  'on-surface': '#e6edf7',
  'on-background': '#e6edf7',
  'on-surface-variant': '#94a3b8',

  // ---- 框線 ----
  outline: '#3a4a68',
  'outline-variant': '#2d3b54',

  // ---- 主色：後台用的青藍 ----
  primary: '#ffffff',
  'primary-fixed': '#00F0FF',
  'primary-fixed-dim': '#00c2cf',
  'primary-container': '#00F0FF',
  'on-primary': '#00363a',
  'on-primary-fixed': '#00363a',
  'on-primary-container': '#00363a',
  'on-primary-fixed-variant': '#00565c',
  'inverse-primary': '#00c2cf',
  'surface-tint': '#00F0FF',

  // ---- 次要色（橘）----
  'secondary-container': '#fe6b00',
  'on-secondary-container': '#2a0f00',
  secondary: '#ffb693',
  'on-secondary': '#561f00',
  'secondary-fixed': '#ffdbcc',
  'secondary-fixed-dim': '#ffb693',
  'on-secondary-fixed': '#351000',
  'on-secondary-fixed-variant': '#7a3000',

  // ---- 第三色（青綠）----
  tertiary: '#00daf8',
  'on-tertiary': '#00363f',
  'tertiary-container': '#a5eeff',
  'on-tertiary-container': '#006f7f',
  'tertiary-fixed': '#a5eeff',
  'tertiary-fixed-dim': '#5fbccb',
  'on-tertiary-fixed': '#001f25',
  'on-tertiary-fixed-variant': '#004e5a',

  // ---- 錯誤 ----
  error: '#ff4655',
  'on-error': '#ffffff',
  'error-container': '#93000a',
  'on-error-container': '#ffdad6',

  // ---- 其他 ----
  'inverse-surface': '#e5e2e1',
  'inverse-on-surface': '#131313',
  'line-green': '#06C755',

  // ---- 給 static/css/index-input.css 用的自訂項（背景點陣／光暈／掃描線）----
  dot: '#1b2436',
  glow: 'rgba(0, 240, 255, 0.28)',
  scan: 'rgba(0, 240, 255, 0.12)'
};

module.exports.theme.extend.colors = Object.assign(
  {},
  module.exports.theme.extend.colors,
  THEME_OVERRIDES
);

// 2026-10-09：字體與後台一致（Chakra Petch 標題／標籤 + Noto Sans TC 內文）。
module.exports.theme.extend.fontFamily = Object.assign(
  {},
  module.exports.theme.extend.fontFamily,
  {
    'display-lg': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
    'headline-md': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
    'headline-lg': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
    'label-caps': ['Chakra Petch', 'Noto Sans TC', 'sans-serif'],
    'body-md': ['Noto Sans TC', 'sans-serif'],
    'body-lg': ['Noto Sans TC', 'sans-serif']
  }
);
