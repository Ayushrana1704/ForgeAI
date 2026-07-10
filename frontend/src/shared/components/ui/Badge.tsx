import { cn, statusColor } from "@/shared/lib/utils";

interface BadgeProps {
  label: string;
  variant?: "status" | "default";
  className?: string;
}

export function Badge({ label, variant = "default", className }: BadgeProps) {
  const colorClass = variant === "status" ? statusColor(label) : "bg-gray-100 text-gray-700";
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium capitalize",
        colorClass,
        className
      )}
    >
      {label}
    </span>
  );
}
