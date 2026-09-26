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
   2026-09-26 主人指定：改成「明亮白底」風格（A 版）
   -------------------------------------------------------------
   這裡用「附加覆蓋」而不是去改上面那 50 幾個色票，
   所以要還原成原本的深色版，只要把下面這一整段刪掉即可。

   ⚠️ 改完一定要重新建置樣式，否則畫面不會變：
      npm run build:css
   ============================================================= */
const LIGHT_THEME_OVERRIDES = {
  // ---- 底層表面：白底、淺灰分層 ----
  background: '#f5f7fa',
  surface: '#f5f7fa',
  'surface-dim': '#e9edf3',
  'surface-bright': '#ffffff',
  'surface-container-lowest': '#ffffff',
  'surface-container-low': '#eef2f8',
  'surface-container': '#ffffff',
  'surface-container-high': '#e8edf5',
  'surface-container-highest': '#dee5ef',
  'surface-variant': '#dee5ef',

  // ---- 文字 ----
  'on-surface': '#1b2130',
  'on-background': '#1b2130',
  'on-surface-variant': '#586074',

  // ---- 框線 ----
  outline: '#b3bccb',
  'outline-variant': '#dbe1ea',

  // ---- 主色：品牌檸檬綠在白底上讀不到，改成深綠色（當底色時配白字）----
  primary: '#1b2130',
  'primary-fixed': '#2f7d32',
  'primary-fixed-dim': '#256628',
  'primary-container': '#2f7d32',
  'on-primary': '#ffffff',
  'on-primary-fixed': '#ffffff',
  'on-primary-container': '#ffffff',
  'on-primary-fixed-variant': '#c8e6c9',
  'inverse-primary': '#9ad14e',
  'surface-tint': '#2f7d32',

  // ---- 次要色（橘）：加深以提高白底對比 ----
  'secondary-container': '#c94f00',
  'on-secondary-container': '#ffffff',
  secondary: '#a84100',
  'on-secondary': '#ffffff',
  'secondary-fixed': '#ffdcc9',
  'secondary-fixed-dim': '#ffb693',
  'on-secondary-fixed': '#3a1500',
  'on-secondary-fixed-variant': '#8a3300',

  // ---- 第三色（青）----
  tertiary: '#0b6b7a',
  'on-tertiary': '#ffffff',
  'tertiary-container': '#cdeef4',
  'on-tertiary-container': '#084f5b',
  'tertiary-fixed': '#cdeef4',
  'tertiary-fixed-dim': '#5fbccb',
  'on-tertiary-fixed': '#00363f',
  'on-tertiary-fixed-variant': '#00505c',

  // ---- 錯誤 ----
  error: '#b3261e',
  'on-error': '#ffffff',
  'error-container': '#ffdad6',
  'on-error-container': '#7a1c12',

  // ---- 其他 ----
  'inverse-surface': '#2b3240',
  'inverse-on-surface': '#eef2f7',
  'line-green': '#06C755',

  // ---- 給 static/css/index-input.css 用的自訂項（背景點陣／光暈／掃描線）----
  dot: '#e2e8f1',
  glow: 'rgba(47, 125, 50, 0.20)',
  scan: 'rgba(47, 125, 50, 0.10)'
};

module.exports.theme.extend.colors = Object.assign(
  {},
  module.exports.theme.extend.colors,
  LIGHT_THEME_OVERRIDES
);
