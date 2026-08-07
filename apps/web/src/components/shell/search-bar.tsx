"use client";

import { Command } from "cmdk";
import { Search } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ALL_NAV_ITEMS } from "./navigation";

/**
 * The research command bar (ui_concept §4).
 *
 * §4 wants ontology-aware natural language — "which Assets have exposure to
 * both AI and grid modernization?". That needs the grounded assistant (#33) and
 * the search index behind it, neither of which exists yet.
 *
 * What ships here is the *frame*: the bar, the ⌘K affordance, and navigation.
 * The one deliberate choice is what it does with a question it cannot answer —
 * it says so, and names the issue. The alternative is a bar that accepts a
 * sentence and returns nothing, which reads as a broken search rather than an
 * unbuilt one, and teaches people to stop typing questions before the feature
 * that answers them arrives.
 */
export function SearchBar() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "k" && (event.metaKey || event.ctrlKey)) {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  const looksLikeAQuestion = value.trim().split(/\s+/).length > 2;

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex w-full max-w-xl items-center gap-2 rounded border border-border bg-surface-raised px-3 py-1.5 text-sm text-ink-subtle hover:border-border-strong"
      >
        <Search aria-hidden className="size-4" />
        <span className="flex-1 text-left">Search or ask a research question</span>
        <kbd className="rounded border border-border px-1 font-mono text-[0.6875rem]">
          ⌘K
        </kbd>
      </button>

      <Command.Dialog
        open={open}
        onOpenChange={setOpen}
        label="Research command bar"
        className="fixed left-1/2 top-32 z-50 w-full max-w-xl -translate-x-1/2 overflow-hidden rounded-panel border border-border-strong bg-surface shadow-2xl"
      >
        <Command.Input
          value={value}
          onValueChange={setValue}
          placeholder="Go to a screen, or ask a research question"
          className="w-full border-b border-border bg-transparent px-4 py-3 text-sm text-ink outline-none placeholder:text-ink-subtle"
        />
        <Command.List className="max-h-80 overflow-y-auto p-2">
          <Command.Empty className="px-2 py-6 text-center text-sm text-ink-muted">
            {looksLikeAQuestion ? (
              <>
                Natural-language research questions need the grounded assistant,
                which arrives in <span className="text-ink">#33</span>. Until
                then this bar navigates.
              </>
            ) : (
              "No match."
            )}
          </Command.Empty>

          <Command.Group
            heading="Go to"
            className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:pb-1 [&_[cmdk-group-heading]]:text-[0.6875rem] [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-wider [&_[cmdk-group-heading]]:text-ink-subtle"
          >
            {ALL_NAV_ITEMS.map((item) => (
              <Command.Item
                key={item.href}
                value={item.label}
                onSelect={() => {
                  router.push(item.href);
                  setOpen(false);
                  setValue("");
                }}
                className="flex cursor-pointer items-center gap-2.5 rounded px-2 py-2 text-sm text-ink-muted data-[selected=true]:bg-surface-raised data-[selected=true]:text-ink"
              >
                <item.icon aria-hidden className="size-4" />
                {item.label}
                {item.planned ? (
                  <span className="ml-auto text-[0.6875rem] text-ink-subtle">
                    {item.planned}
                  </span>
                ) : null}
              </Command.Item>
            ))}
          </Command.Group>
        </Command.List>
      </Command.Dialog>
    </>
  );
}
