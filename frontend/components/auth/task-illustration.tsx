/**
 * Original illustration: a person sitting at a desk working on a computer,
 * with a floating task-list card. All colors come from the global theme tokens.
 */
export default function TaskIllustration({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 520 440" fill="none" xmlns="http://www.w3.org/2000/svg">
      {/* Background blobs */}
      <circle cx="270" cy="230" r="170" fill="var(--tt-primary-200)" opacity="0.55" />
      <circle cx="430" cy="90" r="34" fill="var(--tt-sun)" opacity="0.8" />
      <circle cx="70" cy="330" r="18" fill="var(--tt-blush)" opacity="0.8" />

      {/* Floating task list card */}
      <g className="animate-float motion-reduce:animate-none">
        <rect x="290" y="40" width="190" height="178" rx="18" fill="var(--tt-surface)" />
        <rect x="290" y="40" width="190" height="178" rx="18" stroke="var(--tt-primary-200)" strokeWidth="2" />
        <text x="310" y="72" fontFamily="inherit" fontSize="15" fontWeight="700" fill="var(--tt-ink)">Today&apos;s Tasks</text>
        <rect x="430" y="60" width="32" height="18" rx="9" fill="var(--tt-primary-100)" />
        <text x="446" y="73" textAnchor="middle" fontFamily="inherit" fontSize="10" fontWeight="700" fill="var(--tt-primary-600)">3/4</text>

        {[
          { y: 92, done: true, w: 100 },
          { y: 122, done: true, w: 120 },
          { y: 152, done: true, w: 84 },
          { y: 182, done: false, w: 110 },
        ].map((t, i) => (
          <g key={i}>
            <rect x="310" y={t.y} width="18" height="18" rx="5"
              fill={t.done ? "var(--tt-primary-500)" : "var(--tt-surface)"}
              stroke="var(--tt-primary-500)" strokeWidth="2" />
            {t.done && (
              <path d={`M314 ${t.y + 9.5}l3.5 3.5 6.5-7`} stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            )}
            <rect x="338" y={t.y + 5} width={t.w} height="8" rx="4"
              fill={t.done ? "var(--tt-primary-200)" : "var(--tt-primary-300)"} />
          </g>
        ))}
      </g>

      {/* Plant */}
      <path d="M78 318c-8-30 6-58 22-66-4 22 0 44-10 66" fill="var(--tt-primary-400)" />
      <path d="M92 318c10-26 34-36 50-34-14 12-24 26-34 34" fill="var(--tt-primary-300)" />
      <path d="M72 316h46l-6 44H78z" fill="var(--tt-primary-600)" />

      {/* Desk */}
      <rect x="140" y="300" width="330" height="14" rx="7" fill="var(--tt-primary-600)" />
      <rect x="160" y="314" width="10" height="100" rx="5" fill="var(--tt-primary-700)" />
      <rect x="440" y="314" width="10" height="100" rx="5" fill="var(--tt-primary-700)" />

      {/* Monitor */}
      <rect x="300" y="200" width="150" height="96" rx="10" fill="var(--tt-hair)" />
      <rect x="308" y="208" width="134" height="80" rx="6" fill="var(--tt-primary-100)" />
      <rect x="318" y="220" width="60" height="7" rx="3.5" fill="var(--tt-primary-400)" />
      <rect x="318" y="236" width="104" height="6" rx="3" fill="var(--tt-primary-300)" />
      <rect x="318" y="250" width="86" height="6" rx="3" fill="var(--tt-primary-300)" />
      <rect x="318" y="264" width="40" height="14" rx="7" fill="var(--tt-primary-500)" />
      <rect x="366" y="292" width="18" height="10" fill="var(--tt-hair)" />

      {/* Mug */}
      <rect x="430" y="276" width="20" height="24" rx="4" fill="var(--tt-sun)" />
      <path d="M450 282h4a5 5 0 010 10h-4" stroke="var(--tt-sun)" strokeWidth="3" />

      {/* Chair */}
      <rect x="180" y="214" width="16" height="110" rx="8" fill="var(--tt-primary-400)" transform="rotate(-8 188 270)" />
      <rect x="186" y="318" width="96" height="14" rx="7" fill="var(--tt-primary-400)" />
      <rect x="228" y="332" width="10" height="56" fill="var(--tt-primary-500)" />
      <path d="M200 400h66" stroke="var(--tt-primary-500)" strokeWidth="8" strokeLinecap="round" />

      {/* Person — legs */}
      <path d="M220 318h76c10 0 16 8 14 18l-8 56" stroke="var(--tt-hair)" strokeWidth="24" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M296 398h22" stroke="var(--tt-ink)" strokeWidth="12" strokeLinecap="round" />

      {/* Person — torso */}
      <path d="M206 236c4-26 24-38 42-36 20 2 30 18 30 40v78h-70z" fill="var(--tt-primary-500)" />

      {/* Arm reaching to keyboard */}
      <path d="M252 236c14 22 30 40 58 52" stroke="var(--tt-primary-600)" strokeWidth="20" strokeLinecap="round" />
      <circle cx="314" cy="290" r="9" fill="var(--tt-skin)" />

      {/* Keyboard */}
      <rect x="306" y="294" width="70" height="6" rx="3" fill="var(--tt-primary-300)" />

      {/* Neck & head */}
      <rect x="236" y="182" width="18" height="24" rx="8" fill="var(--tt-skin)" />
      <circle cx="248" cy="164" r="28" fill="var(--tt-skin)" />
      <path d="M220 160c-2-22 14-38 34-36 18 2 26 14 24 26-10-6-22-6-30 2-8 6-14 6-20 2 0 6-2 10-8 6z" fill="var(--tt-hair)" />
      <circle cx="268" cy="166" r="2.6" fill="var(--tt-hair)" />
      <path d="M266 180c3 2 6 2 8 0" stroke="var(--tt-hair)" strokeWidth="2" strokeLinecap="round" />

      {/* Sparkles */}
      <path d="M140 120l4 10 10 4-10 4-4 10-4-10-10-4 10-4z" fill="var(--tt-primary-400)" />
      <path d="M470 250l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" fill="var(--tt-blush)" />
    </svg>
  );
}
