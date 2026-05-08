"use client";

/**
 * Custom BlockNote side menu that adds a "Turn into" submenu to the drag
 * handle, letting users switch block types without leaving the keyboard.
 *
 * Wired into BlockNoteView as a child with sideMenu={false} on the view itself.
 */

import { SideMenuExtension } from "@blocknote/core/extensions";
import {
  AddBlockButton,
  BlockColorsItem,
  DragHandleButton,
  DragHandleMenu,
  RemoveBlockItem,
  SideMenu,
  SideMenuController,
  blockTypeSelectItems,
  useBlockNoteEditor,
  useComponentsContext,
  useExtensionState,
} from "@blocknote/react";
import { useMemo } from "react";

// Subset of block types to show in "Turn into" — keeps the menu scannable.
const ALLOWED_TYPES = new Set([
  "paragraph",
  "heading",
  "toggleListItem",
  "bulletListItem",
  "numberedListItem",
  "checkListItem",
]);

function TurnIntoItem() {
  const Components = useComponentsContext()!;
  const editor = useBlockNoteEditor<any, any, any>();

  const block = useExtensionState(SideMenuExtension, {
    editor,
    selector: (state) => state?.block,
  });

  const items = useMemo(() => {
    if (!block) return [];
    return blockTypeSelectItems(editor.dictionary).filter((item) => {
      if (!ALLOWED_TYPES.has(item.type)) return false;
      // Only headings 1–3, non-toggleable
      if (item.type === "heading") {
        const level = (item.props?.level as number) ?? 99;
        const toggleable = (item.props?.isToggleable as boolean) ?? false;
        return level <= 3 && !toggleable;
      }
      return true;
    });
  }, [editor, block]);

  if (!block) return null;

  // Only show for blocks with inline content (text-based blocks)
  const spec = editor.schema.blockSpecs[block.type];
  if (!spec || (spec as any).config?.content !== "inline") return null;

  return (
    <Components.Generic.Menu.Root position="right" sub={true}>
      <Components.Generic.Menu.Trigger sub={true}>
        <Components.Generic.Menu.Item
          className="bn-menu-item"
          subTrigger={true}
        >
          Turn into
        </Components.Generic.Menu.Item>
      </Components.Generic.Menu.Trigger>

      <Components.Generic.Menu.Dropdown
        sub={true}
        className="bn-menu-dropdown"
      >
        {items.map((item) => {
          const Icon = item.icon;
          const isActive =
            block.type === item.type &&
            Object.entries(item.props ?? {}).every(
              ([k, v]) => (block.props as Record<string, unknown>)[k] === v,
            );

          return (
            <Components.Generic.Menu.Item
              key={`${item.type}-${JSON.stringify(item.props ?? {})}`}
              className="bn-menu-item"
              onClick={() => {
                editor.focus();
                editor.updateBlock(block, {
                  type: item.type as any,
                  props: (item.props ?? {}) as any,
                });
              }}
            >
              <span
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  fontWeight: isActive ? 600 : undefined,
                }}
              >
                <Icon size={16} />
                {item.name}
              </span>
            </Components.Generic.Menu.Item>
          );
        })}
      </Components.Generic.Menu.Dropdown>
    </Components.Generic.Menu.Root>
  );
}

function CustomDragHandleMenu() {
  return (
    <DragHandleMenu>
      <TurnIntoItem />
      <RemoveBlockItem>Delete</RemoveBlockItem>
      <BlockColorsItem>Colors</BlockColorsItem>
    </DragHandleMenu>
  );
}

function CustomSideMenu() {
  return (
    <SideMenu>
      <AddBlockButton />
      <DragHandleButton dragHandleMenu={CustomDragHandleMenu} />
    </SideMenu>
  );
}

/**
 * Drop this inside <BlockNoteView sideMenu={false}> to get the custom side
 * menu with "Turn into" functionality.
 */
export function DocumentSideMenuController() {
  return <SideMenuController sideMenu={CustomSideMenu} />;
}
