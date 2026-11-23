"use client";

import * as DialogPrimitive from "@radix-ui/react-dialog";
import * as DropdownPrimitive from "@radix-ui/react-dropdown-menu";
import { X } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

import { Button } from "./button";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

/** Centered dialog on tablet/desktop, full-height sheet on phones. */
export function DialogContent({
  title,
  description,
  children,
  className,
  wide,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
  className?: string;
  wide?: boolean;
}) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[#120c26]/45 backdrop-blur-[2px] data-[state=open]:animate-in" />
      <DialogPrimitive.Content
        className={cn(
          "fixed z-50 flex flex-col bg-surface shadow-card focus:outline-none",
          "inset-x-0 bottom-0 max-h-[92dvh] rounded-t-3xl md:inset-auto md:top-1/2 md:left-1/2 md:max-h-[88dvh] md:w-full md:-translate-x-1/2 md:-translate-y-1/2 md:rounded-3xl",
          wide ? "md:max-w-2xl" : "md:max-w-lg",
          className,
        )}
      >
        <div className="flex items-start justify-between gap-3 border-b border-line px-5 py-4">
          <div>
            <DialogPrimitive.Title className="text-lg font-bold text-ink">{title}</DialogPrimitive.Title>
            {description ? (
              <DialogPrimitive.Description className="mt-0.5 text-sm text-muted">{description}</DialogPrimitive.Description>
            ) : (
              <DialogPrimitive.Description className="sr-only">{title}</DialogPrimitive.Description>
            )}
          </div>
          <DialogPrimitive.Close asChild>
            <Button variant="ghost" size="icon" aria-label="Close">
              <X />
            </Button>
          </DialogPrimitive.Close>
        </div>
        <div className="overflow-y-auto px-5 py-4">{children}</div>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogFooter({ children }: { children: React.ReactNode }) {
  return (
    <div className="mt-5 flex flex-col-reverse gap-2 border-t border-line pt-4 sm:flex-row sm:justify-end">
      {children}
    </div>
  );
}

export const Dropdown = DropdownPrimitive.Root;
export const DropdownTrigger = DropdownPrimitive.Trigger;

export function DropdownContent({
  children,
  align = "end",
  className,
}: {
  children: React.ReactNode;
  align?: "start" | "end" | "center";
  className?: string;
}) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        align={align}
        sideOffset={6}
        className={cn("z-50 min-w-48 rounded-xl border border-line bg-surface p-1.5 shadow-card", className)}
      >
        {children}
      </DropdownPrimitive.Content>
    </DropdownPrimitive.Portal>
  );
}

export function DropdownItem({
  className,
  danger,
  ...props
}: React.ComponentPropsWithoutRef<typeof DropdownPrimitive.Item> & { danger?: boolean }) {
  return (
    <DropdownPrimitive.Item
      className={cn(
        "flex min-h-10 cursor-pointer select-none items-center gap-2 rounded-lg px-2.5 text-sm font-medium outline-none data-[highlighted]:bg-hover data-[disabled]:pointer-events-none data-[disabled]:opacity-50 [&_svg]:size-4",
        danger ? "text-danger" : "text-ink",
        className,
      )}
      {...props}
    />
  );
}

export function DropdownLabel({ children }: { children: React.ReactNode }) {
  return <DropdownPrimitive.Label className="px-2.5 py-1.5 text-xs font-semibold text-muted">{children}</DropdownPrimitive.Label>;
}

export function DropdownSeparator() {
  return <DropdownPrimitive.Separator className="my-1 h-px bg-line" />;
}

type ConfirmProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  confirmLabel?: string;
  danger?: boolean;
  reasonLabel?: string;
  reasonRequired?: boolean;
  loading?: boolean;
  onConfirm: (reason: string) => void;
};

function ConfirmForm({ confirmLabel = "Confirm", danger, reasonLabel, reasonRequired, loading, onConfirm }: ConfirmProps) {
  // Lives inside the dialog content, so it starts empty every time the dialog opens.
  const [reason, setReason] = React.useState("");
  const blocked = reasonRequired && !reason.trim();
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (!blocked) onConfirm(reason.trim());
      }}
    >
      {reasonLabel && (
        <div className="flex flex-col gap-1.5">
          <label htmlFor="confirm-reason" className="text-sm font-semibold text-ink">
            {reasonLabel}
            {reasonRequired && <span className="text-danger"> *</span>}
          </label>
          <textarea
            id="confirm-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            className="min-h-24 w-full rounded-xl border border-line bg-surface px-3.5 py-2.5 text-ink focus:border-primary-400 focus:shadow-focus focus:outline-none"
          />
        </div>
      )}
      <DialogFooter>
        <DialogClose asChild>
          <Button type="button" variant="outline">
            Cancel
          </Button>
        </DialogClose>
        <Button type="submit" variant={danger ? "danger" : "primary"} loading={loading} disabled={blocked}>
          {confirmLabel}
        </Button>
      </DialogFooter>
    </form>
  );
}

/** Confirmation dialog with optional required reason/comment. */
export function ConfirmDialog(props: ConfirmProps) {
  return (
    <Dialog open={props.open} onOpenChange={props.onOpenChange}>
      <DialogContent title={props.title} description={props.description}>
        <ConfirmForm {...props} />
      </DialogContent>
    </Dialog>
  );
}
