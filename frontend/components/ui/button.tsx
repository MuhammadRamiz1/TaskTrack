import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-xl text-sm font-semibold transition-[background-color,box-shadow,color,transform] duration-150 disabled:pointer-events-none disabled:opacity-55 [&_svg]:size-4 [&_svg]:shrink-0 active:scale-[0.98]",
  {
    variants: {
      variant: {
        primary:
          "bg-linear-to-br from-primary-500 to-primary-600 text-on-primary shadow-button hover:from-primary-600 hover:to-primary-700 dark:from-primary-600 dark:to-primary-600 dark:hover:to-primary-500",
        secondary: "bg-primary-100 text-primary-700 hover:bg-primary-200",
        outline: "border border-line bg-surface text-ink hover:bg-hover",
        ghost: "text-ink hover:bg-hover",
        danger: "bg-danger text-white hover:opacity-90 dark:text-[#2a0d10]",
        link: "h-auto px-0 text-link underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-9 px-3",
        md: "h-11 px-4 md:h-10",
        lg: "h-12 px-6 text-[15px]",
        icon: "size-11 md:size-10",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
  loading?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, loading = false, disabled, children, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        ref={ref}
        className={cn(buttonVariants({ variant, size }), className)}
        disabled={disabled || loading}
        aria-busy={loading || undefined}
        {...props}
      >
        {asChild ? (
          children
        ) : (
          <>
            {loading && <Loader2 className="animate-spin" aria-hidden />}
            {children}
          </>
        )}
      </Comp>
    );
  },
);
Button.displayName = "Button";

export { buttonVariants };
