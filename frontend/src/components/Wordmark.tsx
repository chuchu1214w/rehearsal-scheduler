// 临时字标:用 Baloo 2 模拟 logo 的气泡字风格,正式 logo 由舞团提供矢量文件后替换。
const STAR = 'M0,-10 C1.5,-3 3,-1.5 10,0 C3,1.5 1.5,3 0,10 C-1.5,3 -3,1.5 -10,0 C-3,-1.5 -1.5,-3 0,-10 Z'

function Sparkle({ x, y, size }: { x: number; y: number; size: number }) {
  return (
    <path
      d={STAR}
      transform={`translate(${x} ${y}) scale(${size / 10})`}
      fill="#f7a0d1"
      stroke="#5369af"
      strokeWidth={1.6}
      strokeLinejoin="round"
    />
  )
}

export function Wordmark({ height = 48 }: { height?: number }) {
  const font = "'Baloo 2', 'Fredoka', 'Arial Rounded MT Bold', system-ui, sans-serif"
  return (
    <svg viewBox="0 0 300 100" height={height} role="img" aria-label="Season" className="rs-wordmark">
      <defs>
        <linearGradient id="rs-wm-fill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#f7a0d1" />
          <stop offset="100%" stopColor="#e59cc8" />
        </linearGradient>
      </defs>
      <g transform="rotate(-5 150 55)" fontFamily={font} fontWeight={800} fontSize={76}>
        <text x="22" y="78" fill="#5369af" stroke="#5369af" strokeWidth={10} strokeLinejoin="round" transform="translate(5 5)">
          Season
        </text>
        <text x="22" y="78" fill="url(#rs-wm-fill)" stroke="#5369af" strokeWidth={10} strokeLinejoin="round" paintOrder="stroke">
          Season
        </text>
      </g>
      <Sparkle x={266} y={20} size={12} />
      <Sparkle x={286} y={46} size={7} />
      <Sparkle x={16} y={22} size={8} />
    </svg>
  )
}
