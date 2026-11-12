/** Small line icons for the navigation (24×24, drawn with the current text colour). */
const PATHS = {
  today: "M12 3v2M12 19v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8",
  schedule: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  gpa: "M3 9l9-5l9 5l-9 5zM7 11.5V16c0 1.5 2.2 3 5 3s5-1.5 5-3v-4.5M21 9v5",
  mail: "M3 6h18v12H3zM3 7l9 6l9-6",
  digest: "M5 4h11l3 3v13H5zM8 9h8M8 13h8M8 17h5",
  course: "M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2zM4 21V5M9 8h6M9 12h6",
  tasks: "M9 6h11M9 12h11M9 18h11M4 6l1 1l2-2M4 12l1 1l2-2M4 18l1 1l2-2",
  memories: "M12 4a8 8 0 1 0 0 16a8 8 0 1 0 0-16M12 8v4l3 2",
  connections: "M9 7V3M15 7V3M7 7h10v4a5 5 0 0 1-10 0zM12 16v5",
} as const;

export type IconName = keyof typeof PATHS;

export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="18"
      height="18"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={PATHS[name]} />
    </svg>
  );
}
