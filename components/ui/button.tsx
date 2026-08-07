import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/utils";

type ButtonVariant = "default" | "secondary" | "ghost";
type ButtonSize = "default" | "sm" | "icon";

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
};

const variantClasses: Record<ButtonVariant, string> = {
  default: "bg-zippick-blue text-white hover:bg-blue-600",
  secondary:
    "border border-zippick-line bg-white text-zippick-ink hover:bg-slate-50",
  ghost: "bg-transparent text-zippick-body hover:bg-slate-100"
};

const sizeClasses: Record<ButtonSize, string> = {
  default: "h-11 px-4 text-[15px]",
  sm: "h-9 px-3 text-[14px]",
  icon: "h-10 w-10 p-0"
};

export function Button({
  className,
  variant = "default",
  size = "default",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        "inline-flex items-center justify-center rounded-md font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-300 disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      type={type}
      {...props}
    />
  );
}
