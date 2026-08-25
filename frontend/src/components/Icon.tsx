export type IconName =
  | "activity"
  | "arrow"
  | "cases"
  | "check"
  | "chevron"
  | "clock"
  | "download"
  | "file"
  | "grid"
  | "lock"
  | "refresh"
  | "search"
  | "shield"
  | "upload"
  | "warning"
  | "x";

const paths: Record<IconName, string> = {
  activity: "M4 12h3l2-6 4 12 2-6h5",
  arrow: "M5 12h14m-6-6 6 6-6 6",
  cases: "M4 7h16v12H4zM8 7V5h8v2M4 11h16M10 14h4",
  check: "m5 12 4 4L19 6",
  chevron: "m9 18 6-6-6-6",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v5l3 2",
  download: "M12 3v12m-5-5 5 5 5-5M5 21h14",
  file: "M7 3h7l4 4v14H7zM14 3v5h5M10 13h5M10 17h5",
  grid: "M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4zM14 14h6v6h-6z",
  lock: "M7 11V8a5 5 0 0 1 10 0v3m-11 0h12v10H6zM12 15v2",
  refresh: "M20 7v5h-5M4 17v-5h5M6.1 9a7 7 0 0 1 11.7-2L20 12M4 12l2.2 5a7 7 0 0 0 11.7-2",
  search: "m20 20-4.4-4.4M10.8 18a7.2 7.2 0 1 1 0-14.4 7.2 7.2 0 0 1 0 14.4Z",
  shield: "M12 3 4.5 6v5.5c0 4.7 3.2 8 7.5 9.5 4.3-1.5 7.5-4.8 7.5-9.5V6zM8.5 12l2.2 2.2 4.8-5",
  upload: "M12 16V4m-5 5 5-5 5 5M5 20h14",
  warning: "M12 3 2.8 20h18.4zM12 9v4m0 3.5v.1",
  x: "m6 6 12 12M18 6 6 18",
};

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      aria-hidden="true"
      className="icon"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <path
        d={paths[name]}
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}
