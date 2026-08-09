"use client";

import { Command } from "cmdk";
import { Search } from "lucide-react";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api/client";
import { useAsOf } from "@/lib/as-of";
import { keyFor } from "@/lib/query";

import { ALL_NAV_ITEMS } from "./navigation";

/**
 * The research command bar (ui_concept §4).
 *
 * Two things behind one input: navigation, and the grounded assistant (#33).
 * Anything that matches a screen navigates; anything that reads like a question
 * is offered to the assistant, which translates it into a read of the graph.
 *
 * The assistant never writes the answer. It picks which stored read answers the
 * question, code runs that read, and what appears below is the rows — §4 says
 * "the LLM should not invent the underlying data", and the reliable way to
 * guarantee that is for the prose path not to exist.
 *
 * The page path travels with the question, because §22 makes the assistant
 * context-aware: "why did confidence increase this week?" means something
 * different on a Process screen than on Discover.
 */
export function SearchBar() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  const [asking, setAsking] = useState<string | null>(null);

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
              <button
                type="button"
                onClick={() => setAsking(value)}
                className="text-accent underline underline-offset-2"
              >
                Ask the graph: &ldquo;{value}&rdquo;
              </button>
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
        {asking ? <Answer question={asking} onClose={() => setAsking(null)} /> : null}
      </Command.Dialog>
    </>
  );
}

/**
 * The assistant's reply (#33; PRD §18).
 *
 * Renders the *rows the plan returned*, plus the reason the plan was chosen.
 * There is no narration, because the API has no field to put one in: the model
 * decides which read answers the question and code runs it, so everything on
 * screen came out of the graph.
 */
function Answer({ question, onClose }: { question: string; onClose: () => void }) {
  const { asOf } = useAsOf();
  const pathname = usePathname();
  const answer = useQuery({
    queryKey: keyFor(["ask", question, pathname], { asOf }),
    queryFn: ({ signal }) =>
      api.ask({ asOf, query: { question, page: pathname }, signal }),
  });

  return (
    <div className="border-t border-border px-4 py-3">
      <div className="flex items-start justify-between gap-3">
        <p className="text-xs text-ink-subtle">{question}</p>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 text-xs text-ink-subtle hover:text-ink"
        >
          close
        </button>
      </div>

      {answer.isPending ? (
        <p className="mt-2 text-sm text-ink-muted">Working out which read answers that…</p>
      ) : answer.isError ? (
        <p className="mt-2 text-sm text-contradicts">Could not reach the assistant.</p>
      ) : answer.data.unsupported_reason ? (
        <p className="mt-2 text-sm text-needs-review">
          {answer.data.unsupported_reason}
        </p>
      ) : (
        <div className="mt-2">
          <p className="text-xs text-ink-muted">
            Read <span className="font-mono text-ink">{answer.data.resource}</span> —{" "}
            {answer.data.reasoning}
          </p>
          {(answer.data.results ?? []).length === 0 ? (
            <p className="mt-2 text-sm text-ink-subtle">
              That read returned nothing. The question is answerable; the graph
              has no rows for it yet.
            </p>
          ) : (
            <ul className="mt-2 max-h-56 space-y-1 overflow-y-auto text-sm">
              {answer.data.results?.slice(0, 20).map((row, index) => (
                <li key={index} className="text-ink-muted">
                  {String(
                    (row as Record<string, unknown>).headline ??
                      (row as Record<string, unknown>).summary ??
                      (row as Record<string, unknown>).challenged_assumption ??
                      JSON.stringify(row).slice(0, 120),
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}
