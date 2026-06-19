"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard, FileText, User,
  BarChart3, Shield, Activity, Globe,
  FolderOpen, Zap, Search, Layers,
} from "lucide-react";

const NAV_GROUPS = [
  {
    label: "Overview",
    items: [
      { href: "/",        label: "Dashboard",     icon: LayoutDashboard },
    ],
  },
  {
    label: "Scraping",
    items: [
      { href: "/scrape/posts",    label: "Scrape Post",    icon: FileText },
      { href: "/scrape/profiles", label: "Scrape Profil",  icon: User },
    ],
  },
  {
    label: "Monitoring",
    items: [
      { href: "/monitor/keyword", label: "Keyword Monitoring", icon: Search },
    ],
  },
  {
    label: "Deep Search",
    items: [
      { href: "/monitor/deep", label: "Deep Search", icon: Layers },
    ],
  },
  {
    label: "Data & Analytics",
    items: [
      { href: "/results",   label: "Hasil Scrape",  icon: FolderOpen },
      { href: "/analytics", label: "Analitik",      icon: BarChart3 },
    ],
  },
  {
    label: "Sistem",
    items: [
      { href: "/auth", label: "Autentikasi", icon: Shield },
    ],
  },
];

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8003";

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside
      className="fixed left-0 top-0 h-full w-64 flex flex-col z-40"
      style={{
        background: "rgba(255,255,255,0.85)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderRight: "1px solid rgba(0,0,0,0.07)",
        boxShadow: "4px 0 20px rgba(0,0,0,0.05)",
      }}
    >
      {/* Logo */}
      <div className="p-5 flex items-center gap-3" style={{ borderBottom: "1px solid rgba(0,0,0,0.06)" }}>
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
          style={{ background: "linear-gradient(135deg, #6b5ec7, #3b6dce)" }}
        >
          <Zap size={18} color="white" />
        </div>
        <div className="min-w-0">
          <p className="font-bold text-lg leading-tight" style={{ color: "#1a1c23", fontFamily: "var(--font-sora)" }}>
            FB Scraper
          </p>
          <p className="text-xs truncate" style={{ color: "#8890aa" }}>
            Engine Dashboard
          </p>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-3 flex flex-col gap-0.5 overflow-y-auto">
        {NAV_GROUPS.map(group => (
          <div key={group.label} className="mb-2">
            <p
              className="px-3 pt-3 pb-1.5 text-xs font-semibold uppercase tracking-widest"
              style={{ color: "#8890aa" }}
            >
              {group.label}
            </p>
            {group.items.map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
              return (
                <Link key={href} href={href} className={`nav-item ${active ? "active" : ""}`}>
                  <Icon size={16} />
                  {label}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="p-3" style={{ borderTop: "1px solid rgba(0,0,0,0.06)" }}>
        <div
          className="rounded-xl p-3 flex items-center gap-2.5"
          style={{ background: "rgba(107,94,199,0.06)", border: "1px solid rgba(107,94,199,0.1)" }}
        >
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: "rgba(107,94,199,0.12)" }}
          >
            <Activity size={13} style={{ color: "#6b5ec7" }} />
          </div>
          <div className="min-w-0">
            <p className="text-xs font-semibold leading-tight" style={{ color: "#1a1c23" }}>Backend API</p>
            <p className="text-xs truncate" style={{ color: "#8890aa", fontFamily: "monospace" }}>
              {API_URL.replace("http://", "")}
            </p>
          </div>
          <div className="w-1.5 h-1.5 rounded-full shrink-0" style={{ background: "#1d7a47" }} />
        </div>
      </div>
    </aside>
  );
}