"use client";

import { useState } from "react";
import { $api } from "@/lib/api/query";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";
import {
  Plus,
  Loader2,
  ShoppingCart,
  CheckCircle2,
  Circle,
  Trash2,
  ChevronDown,
  ChevronRight,
} from "lucide-react";
import type { components } from "@/lib/api/schema";

type GroceryList = components["schemas"]["GroceryListResponse"];
type GroceryItem = components["schemas"]["GroceryItemResponse"];
type GroceryItemData = components["schemas"]["GroceryItemData"];

// ── item row ──────────────────────────────────────────────────────────────────

function ItemRow({
  item,
  listId,
  allItems,
  onUpdate,
}: {
  item: GroceryItem;
  listId: string;
  allItems: GroceryItem[];
  onUpdate: () => void;
}) {
  const qc = useQueryClient();
  const [toggling, setToggling] = useState(false);

  const { mutateAsync: updateItem } = $api.useMutation(
    "patch",
    "/grocery-lists/{list_id}/items/{item_id}"
  );

  async function handleToggle() {
    setToggling(true);
    try {
      await updateItem({
        params: { path: { list_id: listId, item_id: item.id } },
        body: { is_checked: !item.is_checked },
      });
      qc.invalidateQueries({ queryKey: ["get", "/grocery-lists"] });
      onUpdate();
    } finally {
      setToggling(false);
    }
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 py-1.5 group",
        item.is_checked && "opacity-50"
      )}
    >
      <button
        type="button"
        onClick={handleToggle}
        disabled={toggling}
        className="shrink-0 text-muted-foreground hover:text-foreground disabled:cursor-wait"
      >
        {toggling ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : item.is_checked ? (
          <CheckCircle2 className="h-4 w-4 text-primary" />
        ) : (
          <Circle className="h-4 w-4" />
        )}
      </button>
      <span className={cn("text-sm flex-1", item.is_checked && "line-through text-muted-foreground")}>
        {item.name}
      </span>
      {(item.quantity || item.unit) && (
        <span className="text-xs text-muted-foreground shrink-0">
          {[item.quantity, item.unit].filter(Boolean).join(" ")}
        </span>
      )}
    </div>
  );
}

// ── grocery list card ─────────────────────────────────────────────────────────

function GroceryListCard({
  list,
  onEdit,
}: {
  list: GroceryList;
  onEdit: (l: GroceryList) => void;
}) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(true);
  const [newItem, setNewItem] = useState("");
  const [adding, setAdding] = useState(false);

  const { mutateAsync: updateList } = $api.useMutation(
    "patch",
    "/grocery-lists/{list_id}"
  );

  const items = list.items ?? [];
  const checked = items.filter((i) => i.is_checked).length;
  const isDone = list.status === "completed";

  async function handleAddItem() {
    const name = newItem.trim();
    if (!name) return;
    setAdding(true);
    try {
      const newItems: GroceryItemData[] = [
        ...items.map((i) => ({
          name: i.name,
          quantity: i.quantity ?? undefined,
          unit: i.unit ?? undefined,
          category: i.category ?? undefined,
          is_checked: i.is_checked,
          notes: i.notes ?? undefined,
        })),
        { name, is_checked: false },
      ];
      await updateList({
        params: { path: { list_id: list.id } },
        body: { items: newItems },
      });
      qc.invalidateQueries({ queryKey: ["get", "/grocery-lists"] });
      setNewItem("");
    } finally {
      setAdding(false);
    }
  }

  return (
    <div className={cn("border rounded-lg bg-card", isDone && "opacity-60")}>
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="text-muted-foreground hover:text-foreground"
        >
          {expanded ? (
            <ChevronDown className="h-4 w-4" />
          ) : (
            <ChevronRight className="h-4 w-4" />
          )}
        </button>

        <div className="flex-1 min-w-0">
          <button
            type="button"
            onClick={() => onEdit(list)}
            className="text-sm font-medium hover:underline text-left"
          >
            {list.name}
          </button>
          {list.store && (
            <p className="text-xs text-muted-foreground">{list.store}</p>
          )}
        </div>

        <span className="text-xs text-muted-foreground shrink-0">
          {checked}/{items.length}
        </span>
      </div>

      {/* Items */}
      {expanded && (
        <div className="px-4 pb-3 border-t pt-3 space-y-0">
          {items.length === 0 && (
            <p className="text-xs text-muted-foreground py-1">No items yet.</p>
          )}
          {items.map((item) => (
            <ItemRow
              key={item.id}
              item={item}
              listId={list.id}
              allItems={items}
              onUpdate={() => qc.invalidateQueries({ queryKey: ["get", "/grocery-lists"] })}
            />
          ))}

          {/* Add item inline */}
          {!isDone && (
            <form
              className="flex gap-2 mt-2"
              onSubmit={(e) => { e.preventDefault(); handleAddItem(); }}
            >
              <Input
                value={newItem}
                onChange={(e) => setNewItem(e.target.value)}
                placeholder="Add item…"
                className="h-8 text-sm"
                disabled={adding}
              />
              <Button type="submit" size="sm" variant="outline" className="h-8 shrink-0" disabled={adding || !newItem.trim()}>
                {adding ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              </Button>
            </form>
          )}
        </div>
      )}
    </div>
  );
}

// ── list sheet ────────────────────────────────────────────────────────────────

function ListSheet({
  open,
  list,
  onClose,
}: {
  open: boolean;
  list: GroceryList | null;
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isEdit = list !== null;
  const [name, setName] = useState("");
  const [store, setStore] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [lastOpen, setLastOpen] = useState(false);
  if (open !== lastOpen) {
    setLastOpen(open);
    if (open) {
      setName(list?.name ?? "");
      setStore(list?.store ?? "");
      setError(null);
    }
  }

  const { mutateAsync: createList } = $api.useMutation("post", "/grocery-lists");
  const { mutateAsync: updateList } = $api.useMutation("patch", "/grocery-lists/{list_id}");
  const { mutateAsync: deleteList } = $api.useMutation("delete", "/grocery-lists/{list_id}");

  async function handleSave() {
    if (!name.trim()) { setError("Name is required."); return; }
    setSaving(true); setError(null);
    try {
      if (isEdit) {
        await updateList({ params: { path: { list_id: list.id } }, body: { name: name.trim(), store: store.trim() || null } });
      } else {
        await createList({ body: { name: name.trim(), store: store.trim() || null, status: "active", items: [] } });
      }
      qc.invalidateQueries({ queryKey: ["get", "/grocery-lists"] });
      onClose();
    } catch { setError("Something went wrong."); }
    finally { setSaving(false); }
  }

  async function handleArchive() {
    if (!list) return;
    setSaving(true);
    try {
      await updateList({ params: { path: { list_id: list.id } }, body: { status: "archived" } });
      qc.invalidateQueries({ queryKey: ["get", "/grocery-lists"] });
      onClose();
    } finally { setSaving(false); }
  }

  return (
    <Sheet open={open} onOpenChange={(o) => !o && onClose()}>
      <SheetContent className="w-full sm:max-w-sm flex flex-col gap-0 p-0">
        <SheetHeader className="px-6 pt-6 pb-4 border-b">
          <SheetTitle>{isEdit ? "Edit list" : "New grocery list"}</SheetTitle>
          <SheetDescription className="sr-only">
            {isEdit ? "Update this grocery list" : "Create a new grocery list"}
          </SheetDescription>
        </SheetHeader>
        <div className="flex-1 px-6 py-5 space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="gl-name">Name</Label>
            <Input id="gl-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Weekly shop" autoFocus />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="gl-store">Store (optional)</Label>
            <Input id="gl-store" value={store} onChange={(e) => setStore(e.target.value)} placeholder="Trader Joe's" />
          </div>
        </div>
        <div className="px-6 py-4 border-t flex items-center gap-2">
          {error ? <p className="flex-1 text-sm text-destructive">{error}</p> : <span className="flex-1" />}
          {isEdit && (
            <Button variant="ghost" size="sm" className="text-muted-foreground" onClick={handleArchive} disabled={saving}>
              Archive
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancel</Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            {saving && <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />}
            {isEdit ? "Save" : "Create"}
          </Button>
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── page ──────────────────────────────────────────────────────────────────────

export default function GroceryListsPage() {
  const [sheetOpen, setSheetOpen] = useState(false);
  const [editing, setEditing] = useState<GroceryList | null>(null);
  const [showArchived, setShowArchived] = useState(false);

  const { data, isLoading, isError } = $api.useQuery("get", "/grocery-lists", {
    params: { query: { limit: 100 } },
  });

  const allLists = data?.items ?? [];
  const active = allLists.filter((l) => l.status !== "archived");
  const archived = allLists.filter((l) => l.status === "archived");
  const displayed = showArchived ? allLists : active;

  function openCreate() { setEditing(null); setSheetOpen(true); }
  function openEdit(l: GroceryList) { setEditing(l); setSheetOpen(true); }
  function handleClose() { setSheetOpen(false); setTimeout(() => setEditing(null), 300); }

  return (
    <div className="p-6 max-w-2xl">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-2">
          <ShoppingCart className="h-5 w-5 text-muted-foreground" />
          <h1 className="text-xl font-semibold">Grocery Lists</h1>
        </div>
        <Button size="sm" onClick={openCreate}>
          <Plus className="h-4 w-4 mr-1" />New
        </Button>
      </div>

      {isLoading && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />Loading…
        </div>
      )}
      {isError && <p className="py-8 text-sm text-destructive">Failed to load lists.</p>}

      {!isLoading && !isError && displayed.length === 0 && (
        <div className="py-12 text-center">
          <ShoppingCart className="h-8 w-8 text-muted-foreground/30 mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">No grocery lists yet.</p>
          <Button variant="outline" size="sm" className="mt-4" onClick={openCreate}>
            <Plus className="h-4 w-4 mr-1" />Create one
          </Button>
        </div>
      )}

      {displayed.length > 0 && (
        <div className="space-y-3">
          {displayed.map((l) => (
            <GroceryListCard key={l.id} list={l} onEdit={openEdit} />
          ))}
        </div>
      )}

      {archived.length > 0 && (
        <button
          type="button"
          onClick={() => setShowArchived((v) => !v)}
          className="mt-4 text-xs text-muted-foreground hover:text-foreground cursor-pointer"
        >
          {showArchived ? "Hide" : "Show"} {archived.length} archived list{archived.length !== 1 ? "s" : ""}
        </button>
      )}

      <ListSheet open={sheetOpen} list={editing} onClose={handleClose} />
    </div>
  );
}
