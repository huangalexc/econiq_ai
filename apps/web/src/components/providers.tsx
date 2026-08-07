"use client";

import { QueryClientProvider } from "@tanstack/react-query";
import { Suspense, useState } from "react";

import { AsOfProvider } from "@/lib/as-of";
import { createQueryClient } from "@/lib/query";

export function Providers({ children }: { children: React.ReactNode }) {
  // Created in state, not at module scope: a client shared across server
  // renders would leak one user's data into another's first paint.
  const [queryClient] = useState(createQueryClient);

  return (
    <QueryClientProvider client={queryClient}>
      {/* AsOfProvider reads search params, which suspends during prerender. */}
      <Suspense fallback={null}>
        <AsOfProvider>{children}</AsOfProvider>
      </Suspense>
    </QueryClientProvider>
  );
}
