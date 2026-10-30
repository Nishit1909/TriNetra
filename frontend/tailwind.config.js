/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      colors: {
        obsidian: {
          950: '#05070d',
          900: '#0a0f1c',
          800: '#111827',
        },
        accent: {
          crimson: '#ff3b5c',
          amber: '#ffb020',
          cyan: '#22d3ee',
          violet: '#a78bfa',
          emerald: '#34d399',
          slate: '#94a3b8',
        },
      },
      boxShadow: {
        glass: '0 20px 50px rgba(0, 0, 0, 0.55), inset 0 1px 0 rgba(255, 255, 255, 0.15)',
        'glass-sm': '0 10px 28px rgba(0, 0, 0, 0.4), inset 0 1px 0 rgba(255, 255, 255, 0.12)',
        'glow-crimson': '0 0 24px rgba(255, 59, 92, 0.38)',
        'glow-cyan': '0 0 20px rgba(34, 211, 238, 0.35)',
        'glow-amber': '0 0 20px rgba(255, 176, 32, 0.3)',
      },
    },
  },
  plugins: [],
};
