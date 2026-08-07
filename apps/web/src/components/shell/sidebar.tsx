"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAVIGATION } from "./navigation";
import { cn } from "@/lib/utils";

export function Sidebar() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="Primary"
      className="flex w-56 shrink-0 flex-col gap-6 border-r border-border bg-surface px-3 py-4"
    >
      {NAVIGATION.map((section) => (
        <div key={section.heading}>
          <h2 className="px-2 pb-2 text-[0.6875rem] font-medium uppercase tracking-wider text-ink-subtle">
            {section.heading}
          </h2>
          <ul className="flex flex-col gap-0.5">
            {section.items.map((item) => {
              // `/` would otherwise prefix-match every route.
              const active =
                item.href === "/"
                  ? pathname === "/"
                  : pathname.startsWith(item.href);
              const Icon = item.icon;
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    aria-current={active ? "page" : undefined}
                    className={cn(
                      "flex items-center gap-2.5 rounded px-2 py-1.5 text-sm transition-colors",
                      active
                        ? "bg-surface-raised text-ink"
                        : "text-ink-muted hover:bg-surface-raised hover:text-ink",
                    )}
                  >
                    <Icon aria-hidden className="size-4 shrink-0" />
                    <span className="truncate">{item.label}</span>
                    {item.planned ? (
                      <span
                        className="ml-auto rounded border border-border px-1 text-[0.625rem] text-ink-subtle"
                        title={`Screen arrives in ${item.planned}`}
                      >
                        {item.planned}
                      </span>
                    ) : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}
