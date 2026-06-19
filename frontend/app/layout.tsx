import type { Metadata } from "next";
import { Sora, Outfit } from "next/font/google";
import "./globals.css";
import Sidebar from "@/components/layout/Sidebar";
import ClientProviders from "@/components/layout/ClientProviders";

const sora = Sora({
  variable: "--font-sora",
  subsets: ["latin"],
  display: "swap",
});

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "FB Scraper Dashboard",
  description: "Facebook Scraper Engine — Dashboard & Analytics",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="id" className={`${sora.variable} ${outfit.variable}`}>
      <body className="min-h-screen flex">
        {/* Light theme background orbs */}
        <div className="orb w-96 h-96" style={{ background: "radial-gradient(circle, rgba(59,109,206,0.13) 0%, transparent 70%)", top: "-20%", left: "-15%" }} />
        <div className="orb w-80 h-80" style={{ background: "radial-gradient(circle, rgba(107,94,199,0.13) 0%, transparent 70%)", bottom: "10%", right: "5%" }} />
        <div className="orb w-64 h-64" style={{ background: "radial-gradient(circle, rgba(33,147,176,0.13) 0%, transparent 70%)", top: "40%", right: "25%", animationDelay: "6s" }} />

        <ClientProviders>
          <Sidebar />
          <main className="flex-1 ml-64 min-h-screen overflow-auto">
            <div className="p-6 max-w-7xl mx-auto">
              {children}
            </div>
          </main>
        </ClientProviders>
      </body>
    </html>
  );
}