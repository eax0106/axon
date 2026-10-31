import * as Dialog from "@radix-ui/react-dialog";
import { type ReactNode, useState } from "react";

import { btn } from "./buttons";

/** Wraps a trigger; the action runs only after the owner confirms in a dialog that says what it costs. */
export function Confirm(props: {
  trigger: ReactNode;
  title: string;
  body: ReactNode;
  action: string;
  danger?: boolean;
  onConfirm: () => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>{props.trigger}</Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-bg-deep/70 backdrop-blur-sm" />
        <Dialog.Content className="pop-in fixed top-1/2 left-1/2 z-50 w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-card border border-line-accent bg-surface p-6">
          <Dialog.Title className="display text-xl">{props.title}</Dialog.Title>
          <Dialog.Description asChild>
            <div className="mt-2 text-sm text-ink-muted">{props.body}</div>
          </Dialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <Dialog.Close className={btn.quiet}>Cancel</Dialog.Close>
            <button
              type="button"
              className={props.danger ? btn.danger : btn.primary}
              onClick={() => {
                setOpen(false);
                props.onConfirm();
              }}
            >
              {props.action}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
