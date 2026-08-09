import {
  Bell,
  Boxes,
  Compass,
  Database,
  Eye,
  Gauge,
  GitBranch,
  History,
  LineChart,
  Network,
  Workflow,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

export interface NavItem {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Routes whose screens are not built yet are shown, but marked. */
  planned?: string;
}

export interface NavSection {
  heading: string;
  items: NavItem[];
}

/**
 * Primary navigation, ui_concept §3.
 *
 * The order is the argument. Discover, then Processes, then Capabilities, then
 * Assets: the product is Process-first and Asset-second (§2.1), and a sidebar
 * that led with Assets would be a screener with extra steps. Personal research
 * sits in its own section below the shared graph, because "my watchlist" is a
 * view over the same objects rather than a different kind of thing.
 *
 * Items whose screens arrive in later issues are listed rather than hidden. A
 * navigation that grows as features land gives no sense of the shape of the
 * product, and each one names the issue that will fill it.
 */
export const NAVIGATION: NavSection[] = [
  {
    heading: "Research",
    items: [
      { label: "Discover", href: "/", icon: Compass },
      { label: "Processes", href: "/processes", icon: Workflow },
      { label: "Bottlenecks", href: "/bottlenecks", icon: Gauge },
      { label: "Capabilities", href: "/capabilities", icon: Network },
      { label: "Assets", href: "/assets", icon: Boxes },
      { label: "Graph", href: "/graph", icon: GitBranch },
    ],
  },
  {
    heading: "My research",
    items: [
      { label: "Alerts", href: "/alerts", icon: Bell },
      { label: "Journal", href: "/journal", icon: LineChart },
      { label: "Watchlist", href: "/watchlist", icon: Eye, planned: "#19" },
    ],
  },
  {
    heading: "System",
    items: [
      { label: "Historical", href: "/historical", icon: History, planned: "Phase 2" },
      { label: "System stats", href: "/system", icon: Database },
    ],
  },
];

export const ALL_NAV_ITEMS = NAVIGATION.flatMap((section) => section.items);
