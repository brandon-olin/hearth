"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChevronLeft, Plus, Pencil, Trash2, Check, X, Loader2, Tag } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetCategory {
  id: string;
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
  default_scope: "personal" | "household";
  sort_order: number;
}

// ── Preset palette ────────────────────────────────────────────────────────────

const COLORS = [
  "#ef4444", "#f97316", "#eab308", "#22c55e",
  "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899",
  "#64748b", "#0ea5e9", "#a3e635", "#f43f5e",
];

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchCategories(): Promise<BudgetCategory[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories`);
  if (!res.ok) throw new Error("Failed to load categories");
  return res.json() as Promise<BudgetCategory[]>;
}

async function createCategory(body: {
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
}): Promise<BudgetCategory> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to create category");
  return res.json() as Promise<BudgetCategory>;
}

async function updateCategory(
  id: string,
  body: Partial<{ name: string; color: string | null; icon: string | null; keywords: string[] | null }>
): Promise<BudgetCategory> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update category");
  return res.json() as Promise<BudgetCategory>;
}

async function deleteCategory(id: string): Promise<void> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete category");
}

// ── Color swatch ──────────────────────────────────────────────────────────────

function ColorPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (c: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {COLORS.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={cn(
            "w-5 h-5 rounded-full border-2 transition-transform",
            value === c ? "border-foreground scale-110" : "border-transparent hover:scale-105"
          )}
          style={{ backgroundColor: c }}
        />
      ))}
    </div>
  );
}

// ── Category row ──────────────────────────────────────────────────────────────

function CategoryRow({
  category,
  onDeleted,
  onUpdated,
}: {
  category: BudgetCategory;
  onDeleted: (id: string) => void;
  onUpdated: (cat: BudgetCategory) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [color, setColor] = useState<string | null>(category.color);
  const [icon, setIcon] = useState(category.icon ?? "");
  const [keywordsRaw, setKeywordsRaw] = useState((category.keywords ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) nameRef.current?.focus();
  }, [editing]);

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const keywords = keywordsRaw
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean);
      const updated = await updateCategory(category.id, {
        name: name.trim(),
        color: color || null,
        icon: icon.trim() || null,
        keywords: keywords.length > 0 ? keywords : null,
      });
      onUpdated(updated);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteCategory(category.id);
      onDeleted(category.id);
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  if (editing) {
    return (
      <div className="border rounded-lg p-4 flex flex-col gap-3">
        <div className="grid grid-cols-[1fr_auto] gap-3">
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground">Name</Label>
            <Input
              ref={nameRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); if (e.key === "Escape") setEditing(false); }}
              className="h-8 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground">Icon</Label>
            <Input
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="🛒"
              className="h-8 text-sm w-16 text-center"
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Color</Label>
          <ColorPicker value={color} onChange={setColor} />
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">
            Keywords <span className="text-muted-foreground/60">(comma-separated, used for auto-categorization)</span>
          </Label>
          <Input
            value={keywordsRaw}
            onChange={(e) => setKeywordsRaw(e.target.value)}
            placeholder="e.g. walmart, kroger, whole foods"
            className="h-8 text-sm"
          />
        </div>

        <div className="flex gap-2">
          <Button size="sm" onClick={() => void handleSave()} disabled={saving || !name.trim()}>
            {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Check className="w-3 h-3 mr-1" />}
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => {
            setName(category.name);
            setColor(category.color);
            setIcon(category.icon ?? "");
            setKeywordsRaw((category.keywords ?? []).join(", "));
            setEditing(false);
          }}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 px-4 py-3 border rounded-lg group">
      {/* Color + icon */}
      <div
        className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-sm"
        style={{ backgroundColor: category.color ?? "#94a3b8" }}
      >
        {category.icon ?? ""}
      </div>

      {/* Name + keywords */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium">{category.name}</p>
        {category.keywords && category.keywords.length > 0 && (
          <p className="text-xs text-muted-foreground truncate">
            {category.keywords.slice(0, 5).join(", ")}
            {category.keywords.length > 5 ? ` +${category.keywords.length - 5} more` : ""}
          </p>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {confirmDelete ? (
          <>
            <span className="text-xs text-muted-foreground mr-1">Delete?</span>
            <Button size="icon-xs" variant="destructive" onClick={() => void handleDelete()} disabled={deleting}>
              {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
            </Button>
            <Button size="icon-xs" variant="ghost" onClick={() => setConfirmDelete(false)}>
              <X className="w-3 h-3" />
            </Button>
          </>
        ) : (
          <>
            <Button size="icon-xs" variant="ghost" onClick={() => setEditing(true)}>
              <Pencil className="w-3 h-3" />
            </Button>
            <Button
              size="icon-xs"
              variant="ghost"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="w-3 h-3" />
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateCategoryForm({ onCreated }: { onCreated: (cat: BudgetCategory) => void }) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(COLORS[0]);
  const [icon, setIcon] = useState("");
  const [keywordsRaw, setKeywordsRaw] = useState("");
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) nameRef.current?.focus();
  }, [open]);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const keywords = keywordsRaw.split(",").map((k) => k.trim()).filter(Boolean);
      const cat = await createCategory({
        name: name.trim(),
        color: color || null,
        icon: icon.trim() || null,
        keywords: keywords.length > 0 ? keywords : null,
      });
      onCreated(cat);
      setName("");
      setColor(COLORS[0]);
      setIcon("");
      setKeywordsRaw("");
      setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors py-2"
      >
        <Plus className="w-4 h-4" /> New category
      </button>
    );
  }

  return (
    <div className="border rounded-lg p-4 flex flex-col gap-3">
      <div className="grid grid-cols-[1fr_auto] gap-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Name</Label>
          <Input
            ref={nameRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); if (e.key === "Escape") setOpen(false); }}
            placeholder="e.g. Groceries"
            className="h-8 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Icon</Label>
          <Input
            value={icon}
            onChange={(e) => setIcon(e.target.value)}
            placeholder="🛒"
            className="h-8 text-sm w-16 text-center"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">Color</Label>
        <ColorPicker value={color} onChange={setColor} />
      </div>

      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">
          Keywords <span className="text-muted-foreground/60">(comma-separated)</span>
        </Label>
        <Input
          value={keywordsRaw}
          onChange={(e) => setKeywordsRaw(e.target.value)}
          placeholder="e.g. walmart, kroger, whole foods"
          className="h-8 text-sm"
        />
      </div>

      <div className="flex gap-2">
        <Button size="sm" onClick={() => void handleCreate()} disabled={saving || !name.trim()}>
          {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
          Create
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BudgetCategoriesPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const { data, isLoading } = useQuery<BudgetCategory[]>({
    queryKey: ["budget", "categories"],
    queryFn: fetchCategories,
  });

  const [categories, setCategories] = useState<BudgetCategory[] | null>(null);
  const display = categories ?? data ?? [];

  // Keep local state in sync with query data on first load
  useEffect(() => {
    if (data && categories === null) setCategories(data);
  }, [data, categories]);

  const handleCreated = (cat: BudgetCategory) => {
    setCategories((prev) => [...(prev ?? []), cat]);
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
  };

  const handleUpdated = (cat: BudgetCategory) => {
    setCategories((prev) => prev?.map((c) => (c.id === cat.id ? cat : c)) ?? null);
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
  };

  const handleDeleted = (id: string) => {
    setCategories((prev) => prev?.filter((c) => c.id !== id) ?? null);
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
  };

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">
      <div className="flex items-center gap-3 mb-6">
        <Button size="icon-sm" variant="ghost" onClick={() => router.push("/budget")}>
          <ChevronLeft className="w-4 h-4" />
        </Button>
        <div>
          <h1 className="text-lg font-semibold">Categories</h1>
          <p className="text-xs text-muted-foreground">
            Add keywords to auto-categorize imported transactions.
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : display.length === 0 && categories !== null ? (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <Tag className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No categories yet. Create one below.</p>
        </div>
      ) : (
        <div className="flex flex-col gap-2 mb-4">
          {display.map((cat) => (
            <CategoryRow
              key={cat.id}
              category={cat}
              onDeleted={handleDeleted}
              onUpdated={handleUpdated}
            />
          ))}
        </div>
      )}

      <CreateCategoryForm onCreated={handleCreated} />
    </div>
  );
}
