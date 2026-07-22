import type { Metadata } from "next";
import "./globals.css";
import { FreshProviders } from "@/components/platform/FreshProviders";

export const metadata: Metadata = {
  title: "Fresh Collective",
  description: "A membership-based transformation platform for women.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased" data-scroll-behavior="smooth">
      <body className="flex min-h-full flex-col">
        <FreshProviders>{children}</FreshProviders>
      </body>
    </html>
  );
}
