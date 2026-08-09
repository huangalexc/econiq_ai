import Link from "next/link";

/**
 * A screen that has not been built yet, saying so precisely.
 *
 * The shell (#18) is the frame; the screens are #21–#34. An unbuilt route that
 * renders an empty list is indistinguishable from a working screen with no
 * data, and the difference matters a great deal when the thing being displayed
 * is "Processes we have discovered". Each stub names the issue that fills it.
 */
export function Placeholder({
  title,
  issue,
  children,
}: {
  title: string;
  issue: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto max-w-2xl px-8 py-16">
      <p className="text-xs uppercase tracking-wider text-ink-subtle">{issue}</p>
      <h1 className="mt-2 text-2xl font-semibold text-ink">{title}</h1>
      <div className="mt-4 space-y-3 text-sm leading-relaxed text-ink-muted">
        {children}
      </div>
      <p className="mt-8 text-sm text-ink-subtle">
        The application shell, the typed API client and the point-in-time control
        are in place, so this screen is the only thing missing.{" "}
        <Link href="/system" className="text-accent underline underline-offset-2">
          System stats
        </Link>{" "}
        reads live data through the same client.
      </p>
    </div>
  );
}
