import { ReactNode } from "react";

interface CardProps {
  children: ReactNode;
  className?: string;
}

export default function Card({ children, className = "" }: CardProps) {
  return (
    <div
      className={`rounded-xl border border-border bg-surface p-6 ${className}`}
      style={{ boxShadow: "var(--fc-shadow-sm)" }}
    >
      {children}
    </div>
  );
}
