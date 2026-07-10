import { forwardRef, type InputHTMLAttributes } from "react";
import { cn } from "@/shared/lib/utils";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, className, id, ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, "-");
    return (
      <div className="w-full">
        {label && (
          <label htmlFor={inputId} className="form-label">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={cn(
            "w-full rounded-lg border px-3 py-2 text-sm shadow-sm outline-none",
            "placeholder:text-gray-400",
            "focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20",
            "disabled:cursor-not-allowed disabled:bg-gray-50 disabled:text-gray-500",
            "transition-colors duration-150",
            error
              ? "border-red-400 focus:border-red-500 focus:ring-red-200"
              : "border-gray-300",
            className
          )}
          aria-invalid={!!error}
          aria-describedby={error ? `${inputId}-error` : undefined}
          {...props}
        />
        {error && (
          <p id={`${inputId}-error`} className="form-error">
            {error}
          </p>
        )}
        {hint && !error && <p className="text-xs text-gray-500 mt-1">{hint}</p>}
      </div>
    );
  }
);

Input.displayName = "Input";
