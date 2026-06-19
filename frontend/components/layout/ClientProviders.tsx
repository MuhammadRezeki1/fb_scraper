"use client";

import { ScrapeProvider } from "@/contexts/ScrapeContext";
import ScrapeFloatingBadge from "./ScrapeFloatingBadge";

export default function ClientProviders({ children }: { children: React.ReactNode }) {
  return (
    <ScrapeProvider>
      {children}
      <ScrapeFloatingBadge />
    </ScrapeProvider>
  );
}
