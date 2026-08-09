import { clerkMiddleware } from "@clerk/nextjs/server";

/**
 * Clerk session handling (issue #19).
 *
 * Deliberately **not** `createRouteMatcher` with a protected list. PRD §23 makes
 * the canonical Process graph system-wide, so every research screen stays
 * readable signed out; the only thing a session gates is the workspace data
 * behind it, and the API enforces that rather than this file. Protecting routes
 * here would put the access-control decision in two places and let them drift.
 */
export default clerkMiddleware();

export const config = {
  matcher: [
    // Skip Next internals and static files.
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
  ],
};
