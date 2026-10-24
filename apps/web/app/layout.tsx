import type { Metadata, Viewport } from "next";
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Tento Resident OS",
    template: "%s | Tento Resident OS",
  },
  description: "One application for residents, maintenance teams, property owners and technical administrators, with an evidence-backed GenAI maintenance assistant.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f9fafb",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} font-sans`}
    >
      <body className="antialiased">{children}</body>
    </html>
  );
}
