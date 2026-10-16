const paths = {
  menu: "M4 7h16M4 12h16M4 17h16",
  plus: "M12 5v14M5 12h14",
  chat: "M4 5h16v11H8l-4 4V5z",
  check: "M5 12l4 4L19 6",
  rules: "M5 6h14M5 12h14M5 18h14",
  settings:
    "M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1",
  close: "M6 6l12 12M18 6L6 18",
  chevron: "M6 9l6 6 6-6",
  calendar: "M4 10h16M9 3v4M15 3v4",
  bulb: "M9 18h6M10 21h4M12 3a6 6 0 0 0-4 10.5c.6.6 1 1.4 1 2.5h6c0-1.1.4-1.9 1-2.5A6 6 0 0 0 12 3z",
  invoice: "M7 3h10v18l-3-2-2 2-2-2-3 2V3zM10 8h4M10 12h4",
  chart: "M4 4v16h16M8 15v-4M12 15V7M16 15V9",
  tools: "M4 7h10M18 7h2M4 17h2M10 17h10",
  mic: "M5 11a7 7 0 0 0 14 0M12 18v3",
  arrow: "M12 19V5M6 11l6-6 6 6",
  up: "M7 10v10H4V10h3zm0 0l4-7c1.5 0 2.5 1 2.2 2.6L12.6 9H19a2 2 0 0 1 2 2.4l-1.4 7A2 2 0 0 1 17.6 20H7",
  down: "M17 14V4h3v10h-3zm0 0l-4 7c-1.5 0-2.5-1-2.2-2.6L11.4 15H5a2 2 0 0 1-2-2.4l1.4-7A2 2 0 0 1 6.4 4H17",
  refresh: "M20 12a8 8 0 1 1-2.3-5.7M20 4v5h-5",
  copy: "M5 15V6a2 2 0 0 1 2-2h8",
} as const;

export type ChatIconName = keyof typeof paths;

export function ChatIcon({ name }: { name: ChatIconName }) {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
      {name === "settings" && <circle cx="12" cy="12" r="3" />}
      {name === "calendar" && (
        <rect x="4" y="5" width="16" height="15" rx="2" />
      )}
      {name === "mic" && <rect x="9" y="3" width="6" height="11" rx="3" />}
      {name === "copy" && <rect x="9" y="9" width="11" height="11" rx="2" />}
      {name === "tools" && (
        <>
          <circle cx="16" cy="7" r="2" />
          <circle cx="8" cy="17" r="2" />
        </>
      )}
    </svg>
  );
}
