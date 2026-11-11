import type { SVGProps } from "react";

const base: SVGProps<SVGSVGElement> = {
  viewBox: "0 0 16 16",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.5,
  strokeLinecap: "round",
  strokeLinejoin: "round",
  "aria-hidden": true,
};

export const Chevron = ({ open, className = "" }: { open?: boolean; className?: string }) => (
  <svg {...base} viewBox="0 0 12 12" className={`chev ${open ? "open" : ""} ${className}`}>
    <path d="M4.5 2.5 8 6l-3.5 3.5" />
  </svg>
);

export const Tick = ({ className = "" }: { className?: string }) => (
  <svg {...base} className={`mark pos ${className}`}>
    <path d="m3 8.5 3.2 3L13 4.5" />
  </svg>
);

export const Cross = ({ className = "" }: { className?: string }) => (
  <svg {...base} className={`mark neg ${className}`}>
    <path d="m4 4 8 8M12 4l-8 8" />
  </svg>
);

export const MenuIcon = () => (
  <svg {...base}>
    <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h11" />
  </svg>
);

export const CloseIcon = () => (
  <svg {...base}>
    <path d="m3.5 3.5 9 9M12.5 3.5l-9 9" />
  </svg>
);

/** The product mark: a B drawn as one line, the second bowl closing like a loop. */
export const BrandMark = () => (
  <svg viewBox="0 0 32 32" fill="none" stroke="var(--accent)" strokeWidth={3} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M9 5v22M9 5h7.5a5.5 5.5 0 0 1 0 11H9m0 0h9a5.5 5.5 0 0 1 0 11H9" />
  </svg>
);
