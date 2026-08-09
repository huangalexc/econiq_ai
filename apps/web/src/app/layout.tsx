import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { ClerkProvider } from "@clerk/nextjs";

import { Providers } from "@/components/providers";
import { AppShell } from "@/components/shell/app-shell";
import { THEME_INIT_SCRIPT } from "@/lib/theme";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "econiq — research terminal",
  description: "Evidence-backed, Process-first investment research",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      // Dark is the base; the toggle overwrites this before paint from
      // localStorage. Set here so the first frame is not light.
      data-theme="dark"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        {/* Before first paint, so a light-theme user never sees a dark frame. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="h-full">
        {/* Clerk outermost so the token hook is available to the API client. */}
        <ClerkProvider>
          <Providers>
            <AppShell>{children}</AppShell>
          </Providers>
        </ClerkProvider>
      </body>
    </html>
  );
}
