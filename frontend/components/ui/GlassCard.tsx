"use client";

import { ReactNode } from "react";

interface Props {
  children: ReactNode;
  glow?: "purple" | "blue" | "cyan" | "pink" | "green";
  padding?: string;
  className?: string;
}

export default function GlassCard({ children, glow, padding, className = "" }: Props) {
  return (
    <div
      className={`glass-card ${glow ? `glow-${glow}` : ""} ${className}`}
      style={{ padding: padding ?? "20px" }}
    >
      {children}
    </div>
  );
}