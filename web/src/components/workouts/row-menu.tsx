"use client";

import type { DraggableAttributes } from "@dnd-kit/core";
import type { SyntheticListenerMap } from "@dnd-kit/core/dist/hooks/utilities";
import { Menu } from "@base-ui/react/menu";
import { MoreVertical } from "lucide-react";
import { cn } from "@/lib/utils";

export interface RowMenuAction {
  label: string;
  onSelect: () => void;
  danger?: boolean;
  hidden?: boolean;
}

/** dnd-kit activator props so the same 3-dot handle is tap=menu, hold=drag. */
export interface DragHandle {
  attributes?: DraggableAttributes;
  listeners?: SyntheticListenerMap;
  setActivatorNodeRef?: (el: HTMLElement | null) => void;
}

/**
 * The 3-dot handle for a template-exercise row. A quick tap opens this context
 * menu; a press-and-hold starts drag-to-reorder — the two are separated by the
 * DndContext's delay-activation sensor (a tap never crosses the delay, so it
 * falls through to the menu's click). The dnd activator props are forwarded onto
 * the trigger button so both behaviours live on one control, as specified.
 */
export function RowMenu({
  actions,
  dragHandle,
  label = "Row actions",
}: {
  actions: RowMenuAction[];
  dragHandle?: DragHandle;
  label?: string;
}) {
  const visible = actions.filter((a) => !a.hidden);
  return (
    <Menu.Root>
      <Menu.Trigger
        {...(dragHandle?.attributes ?? {})}
        {...(dragHandle?.listeners ?? {})}
        ref={dragHandle?.setActivatorNodeRef}
        aria-label={label}
        className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded-md shrink-0 cursor-grab active:cursor-grabbing touch-none"
      >
        <MoreVertical className="h-4 w-4" />
      </Menu.Trigger>
      <Menu.Portal>
        <Menu.Positioner sideOffset={4} align="end" className="z-50">
          <Menu.Popup className="min-w-44 rounded-lg border border-border bg-popover text-popover-foreground p-1 shadow-md outline-none">
            {visible.map((a) => (
              <Menu.Item
                key={a.label}
                onClick={a.onSelect}
                className={cn(
                  "flex items-center rounded-md px-2.5 py-1.5 text-sm cursor-pointer outline-none select-none",
                  "data-[highlighted]:bg-muted",
                  a.danger && "text-destructive data-[highlighted]:bg-destructive/10",
                )}
              >
                {a.label}
              </Menu.Item>
            ))}
          </Menu.Popup>
        </Menu.Positioner>
      </Menu.Portal>
    </Menu.Root>
  );
}
