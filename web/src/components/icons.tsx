import { SVGProps } from "react";

type IconProps = SVGProps<SVGSVGElement> & { size?: number };

function Icon({ size = 16, children, ...props }: IconProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
         strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" aria-hidden {...props}>
      {children}
    </svg>
  );
}

export const ShieldIcon = (p: IconProps) => (
  <Icon {...p}><path d="M12 3l7 3v5c0 4.6-3 8.4-7 10-4-1.6-7-5.4-7-10V6l7-3z" /><path d="M9 12l2 2 4-4" /></Icon>
);
export const RepoIcon = (p: IconProps) => (
  <Icon {...p}><path d="M5 4.5A1.5 1.5 0 016.5 3H19v15H6.5A1.5 1.5 0 005 19.5v-15z" /><path d="M5 19.5A1.5 1.5 0 006.5 21H19v-3" /></Icon>
);
export const PullIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="18" r="2.2" /><path d="M6 8.2v7.6" /><path d="M18 15.8V9a3 3 0 00-3-3h-4" /><path d="M13 3.5L10.5 6 13 8.5" /></Icon>
);
export const MergeIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="6" cy="6" r="2.2" /><circle cx="6" cy="18" r="2.2" /><circle cx="18" cy="12" r="2.2" /><path d="M6 8.2v7.6" /><path d="M6 8c0 3 3 4 9.8 4" /></Icon>
);
export const IssueIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="9" /><circle cx="12" cy="12" r="1.5" fill="currentColor" /></Icon>
);
export const DraftIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="9" strokeDasharray="3.5 2.5" /><path d="M12 8v5" /><circle cx="12" cy="16" r=".6" fill="currentColor" /></Icon>
);
export const StarIcon = (p: IconProps) => (
  <Icon {...p}><path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.8l-5.2 2.8 1-5.8-4.3-4.1 5.9-.9L12 3.5z" /></Icon>
);
export const ForkIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="6" cy="5" r="2" /><circle cx="18" cy="5" r="2" /><circle cx="12" cy="19" r="2" /><path d="M6 7v2a3 3 0 003 3h6a3 3 0 003-3V7" /><path d="M12 12v5" /></Icon>
);
export const CommitIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="3.5" /><path d="M3 12h5.5M15.5 12H21" /></Icon>
);
export const RefreshIcon = (p: IconProps) => (
  <Icon {...p}><path d="M20 11a8 8 0 00-14.6-4.5L4 8" /><path d="M4 4v4h4" /><path d="M4 13a8 8 0 0014.6 4.5L20 16" /><path d="M20 20v-4h-4" /></Icon>
);
export const SunIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" /></Icon>
);
export const MoonIcon = (p: IconProps) => (
  <Icon {...p}><path d="M20 14.5A8 8 0 019.5 4a8 8 0 1010.5 10.5z" /></Icon>
);
export const MonitorIcon = (p: IconProps) => (
  <Icon {...p}><rect x="3" y="4" width="18" height="12" rx="2" /><path d="M8 20h8M12 16v4" /></Icon>
);
export const ExternalIcon = (p: IconProps) => (
  <Icon {...p}><path d="M14 4h6v6" /><path d="M20 4l-9 9" /><path d="M18 14v5a1 1 0 01-1 1H5a1 1 0 01-1-1V7a1 1 0 011-1h5" /></Icon>
);
export const SearchIcon = (p: IconProps) => (
  <Icon {...p}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></Icon>
);
export const LockIcon = (p: IconProps) => (
  <Icon {...p}><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 018 0v3" /></Icon>
);
export const PulseIcon = (p: IconProps) => (
  <Icon {...p}><path d="M3 12h4l2.5-6 5 12L17 12h4" /></Icon>
);
