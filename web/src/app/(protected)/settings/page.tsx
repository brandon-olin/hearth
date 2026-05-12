"use client";

import { useRef, useState } from "react";
import {
  Eye,
  EyeOff,
  GripVertical,
  Palette,
  User,
  Home,
  FolderPlus,
  Trash2,
  X,
  ChevronDown,
  Bot,
  Check,
  AlertCircle,
  Loader2,
  Plus,
  Pencil,
  BookOpen,
  FileText,
  RefreshCw,
  FolderKanban,
  Pin,
  PinOff,
  Lock,
} from "lucide-react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { getAccessToken } from "@/lib/auth/token";
import { $api } from "@/lib/api/query";
import { useThemeCustomizer } from "@/lib/theme/context";
import {
  BASE_THEMES,
  ACCENT_COLORS,
  RADIUS_OPTIONS,
  FONT_OPTIONS,
  CUSTOM_VAR_OPTIONS,
  type ThemeConfig,
} from "@/lib/theme/presets";
import { useSidebarConfig, newFolderId, type SidebarFolder } from "@/lib/sidebar/context";
import { type NavItem } from "@/lib/sidebar/nav-items";
import { useNavItems } from "@/lib/sidebar/use-nav-items";
import {
  FOLDER_ICON_GROUPS,
  resolveFolderIcon,
  DEFAULT_FOLDER_ICON,
} from "@/lib/sidebar/folder-icons";

// ── Left nav ──────────────────────────────────────────────────────────────────

type Section = "appearance" | "navigation" | "account" | "household" | "ai";

const SECTIONS: { id: Section; label: string; icon: React.ElementType }[] = [
  { id: "appearance",  label: "Appearance",  icon: Palette       },
  { id: "navigation",  label: "Navigation",  icon: GripVertical  },
  { id: "account",     label: "Account",     icon: User          },
  { id: "household",   label: "Household",   icon: Home          },
  { id: "ai",          label: "AI",          icon: Bot           },
];

function SettingsNav({
  active,
  onChange,
}: {
  active: Section;
  onChange: (s: Section) => void;
}) {
  return (
    <nav className="space-y-0.5">
      {SECTIONS.map(({ id, label, icon: Icon }) => (
        <button
          key={id}
          type="button"
          onClick={() => onChange(id)}
          className={cn(
            "flex items-center gap-2.5 w-full px-3 py-2 rounded-md text-sm font-medium transition-colors text-left",
            active === id
              ? "bg-primary/10 text-primary"
              : "text-muted-foreground hover:bg-muted hover:text-foreground"
          )}
        >
          <Icon className="h-4 w-4 shrink-0" />
          {label}
        </button>
      ))}
    </nav>
  );
}

// ── Shared helpers ────────────────────────────────────────────────────────────

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-4">
      {children}
    </h2>
  );
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border rounded-lg bg-card">
      <div className="px-5 py-3 border-b">
        <p className="text-sm font-semibold">{title}</p>
      </div>
      <div className="p-5">{children}</div>
    </div>
  );
}

function Label({ children }: { children: React.ReactNode }) {
  return (
    <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
      {children}
    </p>
  );
}

// ── Sidebar customizer ────────────────────────────────────────────────────────

// ── Icon picker ───────────────────────────────────────────────────────────────

function InlineIconPicker({
  currentIcon,
  onSelect,
  onClose,
}: {
  currentIcon: string;
  onSelect: (name: string) => void;
  onClose: () => void;
}) {
  const [search, setSearch] = useState("");

  const filteredGroups = search
    ? FOLDER_ICON_GROUPS
        .map((g) => ({
          ...g,
          icons: g.icons.filter((n) => n.toLowerCase().includes(search.toLowerCase())),
        }))
        .filter((g) => g.icons.length > 0)
    : FOLDER_ICON_GROUPS;

  return (
    <div className="border border-t-0 rounded-b-md bg-muted/20 px-3 pt-2 pb-3 space-y-2">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search icons…"
          autoFocus
          className="flex-1 text-xs bg-background border border-border rounded-md px-2 py-1.5 outline-none"
        />
        <button
          type="button"
          onClick={onClose}
          className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
      <div className="max-h-48 overflow-y-auto space-y-2.5 pr-1">
        {filteredGroups.length === 0 && (
          <p className="text-xs text-muted-foreground text-center py-4">No icons match</p>
        )}
        {filteredGroups.map((group) => (
          <div key={group.label}>
            <p className="text-[10px] font-semibold text-muted-foreground uppercase tracking-wide px-0.5 mb-1">
              {group.label}
            </p>
            <div className="flex flex-wrap gap-0.5">
              {group.icons.map((iconName) => {
                const IconComp = resolveFolderIcon(iconName);
                if (!IconComp) return null;
                return (
                  <button
                    key={iconName}
                    type="button"
                    title={iconName}
                    onClick={() => onSelect(iconName)}
                    className={cn(
                      "flex items-center justify-center w-7 h-7 rounded transition-colors cursor-pointer",
                      currentIcon === iconName
                        ? "bg-primary/10 text-primary"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground",
                    )}
                  >
                    <IconComp className="h-4 w-4" />
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SidebarCustomizer({
  onCreateProject,
  onCreatePage,
}: {
  onCreateProject?: () => void;
  onCreatePage?: () => void;
}) {
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
  const { items: allNavItems } = useNavItems();
  const qc = useQueryClient();
  const { mutateAsync: updateProject } = $api.useMutation("patch", "/projects/{project_id}");

  // Unified drag state — works for both nav item hrefs and folder IDs
  const dragIdRef = useRef<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  // Tracks what's being dragged so we can style folder drop zones correctly
  const [draggingId, setDraggingId] = useState<string | null>(null);

  // Drag state for reordering items within a folder's expanded contents panel
  const folderDragRef = useRef<string | null>(null);
  const [folderDragOverHref, setFolderDragOverHref] = useState<string | null>(null);

  // "Add nav item" picker
  const [navPickerOpen, setNavPickerOpen] = useState(false);

  // New-folder form state
  const [addingFolder, setAddingFolder] = useState(false);
  const [newFolderIcon, setNewFolderIcon] = useState(DEFAULT_FOLDER_ICON);
  const [newFolderLabel, setNewFolderLabel] = useState("");

  // Inline folder editing
  const [editingFolderId, setEditingFolderId] = useState<string | null>(null);
  const [editIcon, setEditIcon] = useState("");
  const [editLabel, setEditLabel] = useState("");

  // Icon picker — "new" targets the new-folder form; a folder ID targets that folder's edit row
  const [iconPickerTarget, setIconPickerTarget] = useState<"new" | string | null>(null);

  // Which folder's contents are expanded in the settings list
  const [expandedFolderId, setExpandedFolderId] = useState<string | null>(null);

  const { folders, hidden, order } = sidebarConfig;

  // ── Build unified ordered root list (nav items + folders interleaved) ───────
  // Uses allNavItems (dynamic) so projects + documents appear alongside builtins.
  const folderedHrefs = new Set(folders.flatMap((f) => f.hrefs));
  const allHrefs      = allNavItems.map((n) => n.href);
  const rootNavHrefs  = allHrefs.filter((h) => !folderedHrefs.has(h));
  const folderIds     = folders.map((f) => f.id);
  const allRootIds    = [...rootNavHrefs, ...folderIds];

  const orderedIds =
    order.length > 0
      ? [
          ...order.filter((id) => allRootIds.includes(id)),
          ...allRootIds.filter((id) => !order.includes(id)),
        ]
      : allRootIds;

  type RootEntry =
    | { kind: "nav";    item:   NavItem       }
    | { kind: "folder"; folder: SidebarFolder };

  const rootEntries: RootEntry[] = orderedIds.flatMap((id): RootEntry[] => {
    if (id.startsWith("/")) {
      const item = allNavItems.find((n) => n.href === id);
      return item ? [{ kind: "nav" as const, item }] : [];
    }
    const folder = folders.find((f) => f.id === id);
    return folder ? [{ kind: "folder" as const, folder }] : [];
  });

  // ── helpers ─────────────────────────────────────────────────────────────────

  /** Renders either a LucideIcon component or an emoji string */
  function ItemIcon({ icon, className }: { icon: NavItem["icon"]; className?: string }) {
    if (typeof icon === "string") {
      return <span className={cn("text-base leading-none w-4 text-center shrink-0", className)}>{icon}</span>;
    }
    const I = icon;
    return <I className={cn("h-4 w-4 shrink-0", className)} />;
  }

  function toggleHidden(href: string) {
    const nextHidden = hidden.includes(href)
      ? hidden.filter((h) => h !== href)
      : [...hidden, href];
    setSidebarConfig({ ...sidebarConfig, hidden: nextHidden });
  }

  /** Remove a project or document from the sidebar nav entirely */
  async function removeFromNav(item: NavItem) {
    if (item.isProject && item.projectId) {
      await updateProject({
        params: { path: { project_id: item.projectId } },
        body: { show_in_nav: false },
      });
      qc.invalidateQueries({ queryKey: ["get", "/projects"] });
      setSidebarConfig({
        ...sidebarConfig,
        order: order.filter((id) => id !== item.href),
        folders: folders.map((f) => ({ ...f, hrefs: f.hrefs.filter((h) => h !== item.href) })),
      });
    } else if (item.isDocument && item.documentId) {
      setSidebarConfig({
        ...sidebarConfig,
        pinnedDocumentIds: (sidebarConfig.pinnedDocumentIds ?? []).filter(
          (id) => id !== item.documentId,
        ),
        order: order.filter((id) => id !== item.href),
        folders: folders.map((f) => ({ ...f, hrefs: f.hrefs.filter((h) => h !== item.href) })),
      });
    }
  }

  function addFolder() {
    if (!newFolderLabel.trim()) return;
    const folder: SidebarFolder = {
      id: newFolderId(),
      label: newFolderLabel.trim(),
      icon: newFolderIcon || DEFAULT_FOLDER_ICON,
      hrefs: [],
    };
    setSidebarConfig({ ...sidebarConfig, folders: [...folders, folder] });
    setAddingFolder(false);
    setNewFolderLabel("");
    setNewFolderIcon(DEFAULT_FOLDER_ICON);
    setIconPickerTarget(null);
  }

  function deleteFolder(id: string) {
    setSidebarConfig({
      ...sidebarConfig,
      folders: folders.filter((f) => f.id !== id),
      order:   order.filter((o) => o !== id),
    });
  }

  function startEditFolder(folder: SidebarFolder) {
    setEditingFolderId(folder.id);
    setEditIcon(folder.icon);
    setEditLabel(folder.label);
  }

  function saveEditFolder(id: string) {
    setSidebarConfig({
      ...sidebarConfig,
      folders: folders.map((f) =>
        f.id === id
          ? { ...f, label: editLabel.trim() || f.label, icon: editIcon || f.icon }
          : f,
      ),
    });
    setEditingFolderId(null);
    setIconPickerTarget(null);
  }

  function removeFromFolder(folderId: string, href: string) {
    setSidebarConfig({
      ...sidebarConfig,
      folders: folders.map((f) =>
        f.id === folderId ? { ...f, hrefs: f.hrefs.filter((h) => h !== href) } : f,
      ),
    });
  }

  function reorderInFolder(folderId: string, fromHref: string, toHref: string) {
    setSidebarConfig({
      ...sidebarConfig,
      folders: folders.map((f) => {
        if (f.id !== folderId) return f;
        const next = [...f.hrefs];
        const fromIdx = next.indexOf(fromHref);
        const toIdx   = next.indexOf(toHref);
        if (fromIdx === -1 || toIdx === -1) return f;
        next.splice(fromIdx, 1);
        next.splice(toIdx, 0, fromHref);
        return { ...f, hrefs: next };
      }),
    });
  }

  function moveToFolder(href: string, targetFolderId: string) {
    const updatedFolders = folders
      .map((f) => ({ ...f, hrefs: f.hrefs.filter((h) => h !== href) }))
      .map((f) => f.id === targetFolderId ? { ...f, hrefs: [...f.hrefs, href] } : f);
    setSidebarConfig({
      ...sidebarConfig,
      folders: updatedFolders,
      order: order.filter((o) => o !== href), // remove from root order
    });
  }

  // ── unified drag-to-reorder + drag-into-folder ──────────────────────────────

  function handleDragStart(id: string) {
    dragIdRef.current = id;
    setDraggingId(id);
  }

  function handleDragOver(e: React.DragEvent, targetId: string) {
    e.preventDefault();
    if (dragIdRef.current !== targetId) setDragOverId(targetId);
  }

  function handleDrop(targetId: string) {
    const fromId = dragIdRef.current;
    if (!fromId || fromId === targetId) { setDragOverId(null); return; }

    // ── Drop onto a folder → move item into that folder ──────────────────────
    const targetIsFolder = !targetId.startsWith("/") && folders.some((f) => f.id === targetId);
    if (targetIsFolder && fromId.startsWith("/")) {
      moveToFolder(fromId, targetId);
      dragIdRef.current = null;
      setDragOverId(null);
      return;
    }

    // ── Drop onto another item → reorder ─────────────────────────────────────
    const next = [...orderedIds];
    const fromIdx = next.indexOf(fromId);
    const toIdx   = next.indexOf(targetId);
    if (fromIdx === -1 || toIdx === -1) { setDragOverId(null); return; }
    next.splice(fromIdx, 1);
    next.splice(toIdx, 0, fromId);
    setSidebarConfig({ ...sidebarConfig, order: next });
    dragIdRef.current = null;
    setDragOverId(null);
  }

  function handleDragEnd() {
    dragIdRef.current = null;
    setDraggingId(null);
    setDragOverId(null);
  }

  // ── render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Drag to reorder or drop onto a folder to nest. Projects and documents can be pinned here.
        </p>
        <div className="relative shrink-0 ml-3">
          <button
            type="button"
            onClick={() => setNavPickerOpen((v) => !v)}
            className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            Add nav item
          </button>
          {navPickerOpen && (
            <>
              {/* Backdrop to close picker */}
              <div
                className="fixed inset-0 z-10"
                onClick={() => setNavPickerOpen(false)}
              />
              <div className="absolute right-0 top-full mt-1.5 z-20 bg-background border rounded-lg shadow-lg py-1 min-w-[148px]">
                <button
                  type="button"
                  onClick={() => { setAddingFolder(true); setNavPickerOpen(false); }}
                  className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
                >
                  <FolderPlus className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  Folder
                </button>
                <button
                  type="button"
                  onClick={() => { onCreateProject?.(); setNavPickerOpen(false); }}
                  className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
                >
                  <FolderKanban className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  Project
                </button>
                <button
                  type="button"
                  onClick={() => { onCreatePage?.(); setNavPickerOpen(false); }}
                  className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
                >
                  <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  Document
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* New folder form */}
      {addingFolder && (
        <div className={cn(
          "border bg-muted/30",
          iconPickerTarget === "new" ? "rounded-t-lg" : "rounded-lg",
        )}>
          <div className="flex items-center gap-2 p-2.5">
            {/* Icon picker trigger */}
            <button
              type="button"
              title="Choose icon"
              onClick={() => setIconPickerTarget(iconPickerTarget === "new" ? null : "new")}
              className={cn(
                "w-8 h-8 flex items-center justify-center rounded-md border shrink-0 transition-colors cursor-pointer",
                iconPickerTarget === "new"
                  ? "border-primary bg-primary/10 text-primary"
                  : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
            >
              {(() => {
                const IconComp = resolveFolderIcon(newFolderIcon) ?? resolveFolderIcon(DEFAULT_FOLDER_ICON)!;
                return <IconComp className="h-4 w-4" />;
              })()}
            </button>
            <input
              type="text"
              value={newFolderLabel}
              onChange={(e) => setNewFolderLabel(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") addFolder();
                if (e.key === "Escape") { setAddingFolder(false); setIconPickerTarget(null); }
              }}
              placeholder="Folder name…"
              autoFocus
              className="flex-1 text-sm bg-transparent outline-none border-b border-border pb-0.5"
            />
            <button
              type="button"
              onClick={addFolder}
              disabled={!newFolderLabel.trim()}
              className="text-xs px-2.5 py-1 rounded-md bg-primary text-primary-foreground disabled:opacity-40 cursor-pointer disabled:cursor-default shrink-0"
            >
              Add
            </button>
            <button
              type="button"
              onClick={() => { setAddingFolder(false); setIconPickerTarget(null); }}
              className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
          {iconPickerTarget === "new" && (
            <InlineIconPicker
              currentIcon={newFolderIcon}
              onSelect={(name) => { setNewFolderIcon(name); setIconPickerTarget(null); }}
              onClose={() => setIconPickerTarget(null)}
            />
          )}
        </div>
      )}

      {/* Unified drag list */}
      <div className="space-y-1">
        {rootEntries.map((entry) => {
          const entryId    = entry.kind === "nav" ? entry.item.href : entry.folder.id;
          const isDragOver = dragOverId === entryId;
          // A folder becomes a drop zone (different highlight) when dragging a nav item over it
          const isFolderDropTarget = isDragOver && entry.kind === "folder" && draggingId?.startsWith("/");

          // ── nav item row ──────────────────────────────────────────────────
          if (entry.kind === "nav") {
            const { item } = entry;
            const isHidden   = hidden.includes(item.href);
            const isDynamic  = !!(item.isProject || item.isDocument); // user-added; has remove btn
            return (
              <div
                key={entryId}
                draggable
                onDragStart={() => handleDragStart(entryId)}
                onDragOver={(e) => handleDragOver(e, entryId)}
                onDrop={() => handleDrop(entryId)}
                onDragEnd={handleDragEnd}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md border bg-background transition-all select-none",
                  isHidden && "opacity-40",
                  isDragOver && "border-primary bg-primary/5 scale-[1.01]",
                )}
              >
                <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/50 cursor-grab active:cursor-grabbing" />
                <ItemIcon icon={item.icon} className="text-muted-foreground" />
                <span className="flex-1 text-sm font-medium">{item.label}</span>
                {/* Dynamic items (projects, docs): show remove button */}
                {isDynamic ? (
                  <button
                    type="button"
                    onClick={() => removeFromNav(item)}
                    className="text-muted-foreground hover:text-destructive cursor-pointer transition-colors"
                    title="Remove from sidebar"
                  >
                    <X className="h-4 w-4" />
                  </button>
                ) : (
                  /* Built-in items: show hide/show toggle */
                  <button
                    type="button"
                    onClick={() => toggleHidden(item.href)}
                    className="text-muted-foreground hover:text-foreground cursor-pointer"
                    aria-label={isHidden ? "Show in sidebar" : "Hide from sidebar"}
                  >
                    {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                )}
              </div>
            );
          }

          // ── folder row ────────────────────────────────────────────────────
          const { folder } = entry;
          const isEditing  = editingFolderId === folder.id;
          const isExpanded = expandedFolderId === folder.id;
          const folderItems = folder.hrefs
            .map((href) => allNavItems.find((n) => n.href === href))
            .filter((n): n is NavItem => !!n);
          // Items available to add: everything not already in this folder
          const available = allNavItems.filter((n) => !folder.hrefs.includes(n.href));

          return (
            <div key={entryId}>
              <div
                draggable={!isEditing}
                onDragStart={() => handleDragStart(entryId)}
                onDragOver={(e) => handleDragOver(e, entryId)}
                onDrop={() => handleDrop(entryId)}
                onDragEnd={handleDragEnd}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md border bg-background transition-all select-none",
                  // Folder drop zone: emerald highlight to signal "move into folder"
                  isFolderDropTarget && "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30 scale-[1.01]",
                  // Regular reorder highlight
                  isDragOver && !isFolderDropTarget && "border-primary bg-primary/5 scale-[1.01]",
                  (isExpanded || (isEditing && iconPickerTarget === folder.id)) && "rounded-b-none border-b-0",
                )}
              >
                <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/50 cursor-grab active:cursor-grabbing" />

                {isEditing ? (
                  <>
                    {/* Icon picker trigger for edit row */}
                    <button
                      type="button"
                      title="Choose icon"
                      onClick={() => setIconPickerTarget(iconPickerTarget === folder.id ? null : folder.id)}
                      className={cn(
                        "w-8 h-8 flex items-center justify-center rounded-md border shrink-0 transition-colors cursor-pointer",
                        iconPickerTarget === folder.id
                          ? "border-primary bg-primary/10 text-primary"
                          : "border-border text-muted-foreground hover:bg-muted hover:text-foreground",
                      )}
                    >
                      {(() => {
                        const IconComp = resolveFolderIcon(editIcon) ?? resolveFolderIcon(DEFAULT_FOLDER_ICON)!;
                        return <IconComp className="h-4 w-4" />;
                      })()}
                    </button>
                    <input
                      type="text"
                      value={editLabel}
                      onChange={(e) => setEditLabel(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") saveEditFolder(folder.id);
                        if (e.key === "Escape") { setEditingFolderId(null); setIconPickerTarget(null); }
                      }}
                      autoFocus
                      className="flex-1 text-sm bg-muted border border-border rounded px-2 py-0.5 outline-none"
                    />
                    <button
                      type="button"
                      onClick={() => saveEditFolder(folder.id)}
                      className="text-xs px-2 py-0.5 rounded bg-primary text-primary-foreground cursor-pointer shrink-0"
                    >
                      Save
                    </button>
                    <button
                      type="button"
                      onClick={() => { setEditingFolderId(null); setIconPickerTarget(null); }}
                      className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  </>
                ) : (
                  <>
                    {(() => {
                      const FolderIcon = resolveFolderIcon(folder.icon) ?? resolveFolderIcon(DEFAULT_FOLDER_ICON)!;
                      return <FolderIcon className="h-4 w-4 shrink-0 text-muted-foreground" />;
                    })()}
                    <span className="flex-1 text-sm font-medium">{folder.label}</span>
                    <span className="text-[10px] font-medium text-muted-foreground border rounded px-1.5 py-0.5 shrink-0">
                      FOLDER
                    </span>
                    <button
                      type="button"
                      onClick={() => startEditFolder(folder)}
                      className="text-xs text-muted-foreground hover:text-foreground cursor-pointer underline underline-offset-2 shrink-0"
                    >
                      Edit
                    </button>
                    <button
                      type="button"
                      onClick={() => deleteFolder(folder.id)}
                      className="text-muted-foreground hover:text-destructive cursor-pointer shrink-0"
                      title="Delete folder (items return to root)"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => setExpandedFolderId(isExpanded ? null : folder.id)}
                      className="text-muted-foreground hover:text-foreground cursor-pointer shrink-0"
                      title={isExpanded ? "Collapse" : "Manage contents"}
                    >
                      <ChevronDown
                        className={cn(
                          "h-4 w-4 transition-transform duration-150",
                          isExpanded && "rotate-180",
                        )}
                      />
                    </button>
                  </>
                )}
              </div>

              {/* Icon picker panel for edit row */}
              {isEditing && iconPickerTarget === folder.id && (
                <InlineIconPicker
                  currentIcon={editIcon}
                  onSelect={(name) => { setEditIcon(name); setIconPickerTarget(null); }}
                  onClose={() => setIconPickerTarget(null)}
                />
              )}

              {/* Folder contents panel */}
              {isExpanded && (
                <div className="border border-t-0 rounded-b-md bg-muted/20 px-3 py-2 space-y-1">
                  {folderItems.map((item) => {
                    const isHidden       = hidden.includes(item.href);
                    const isDynamic      = !!(item.isProject || item.isDocument);
                    const isFolderDragOver = folderDragOverHref === item.href;
                    return (
                      <div
                        key={item.href}
                        draggable
                        onDragStart={() => { folderDragRef.current = item.href; }}
                        onDragOver={(e) => { e.preventDefault(); if (folderDragRef.current !== item.href) setFolderDragOverHref(item.href); }}
                        onDrop={() => {
                          const from = folderDragRef.current;
                          if (from && from !== item.href) reorderInFolder(folder.id, from, item.href);
                          folderDragRef.current = null;
                          setFolderDragOverHref(null);
                        }}
                        onDragEnd={() => { folderDragRef.current = null; setFolderDragOverHref(null); }}
                        className={cn(
                          "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm",
                          "cursor-grab active:cursor-grabbing",
                          isHidden && "opacity-40",
                          isFolderDragOver && "ring-1 ring-primary bg-primary/5",
                        )}
                      >
                        <GripVertical className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0" />
                        <ItemIcon icon={item.icon} className="text-muted-foreground" />
                        <span className="flex-1 text-muted-foreground">{item.label}</span>
                        {isDynamic ? (
                          <button
                            type="button"
                            onClick={() => removeFromNav(item)}
                            className="text-muted-foreground hover:text-destructive cursor-pointer transition-colors"
                            title="Remove from sidebar"
                          >
                            <X className="h-3.5 w-3.5" />
                          </button>
                        ) : (
                          <button
                            type="button"
                            onClick={() => toggleHidden(item.href)}
                            className="text-muted-foreground hover:text-foreground cursor-pointer"
                            title={isHidden ? "Show in sidebar" : "Hide from sidebar"}
                          >
                            {isHidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                          </button>
                        )}
                        <button
                          type="button"
                          onClick={() => removeFromFolder(folder.id, item.href)}
                          className="text-muted-foreground hover:text-foreground cursor-pointer"
                          title="Remove from folder"
                        >
                          <X className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    );
                  })}

                  {available.length > 0 && (
                    <div className="relative mt-1">
                      <select
                        className="w-full text-xs text-muted-foreground bg-background border border-border rounded-md px-2 py-1.5 cursor-pointer appearance-none pr-6 outline-none hover:bg-muted/50 transition-colors"
                        value=""
                        onChange={(e) => {
                          if (e.target.value) moveToFolder(e.target.value, folder.id);
                        }}
                      >
                        <option value="">+ Add item to folder…</option>
                        {available.map((n) => (
                          <option key={n.href} value={n.href}>{n.label}</option>
                        ))}
                      </select>
                      <ChevronDown className="h-3 w-3 absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Theme picker ──────────────────────────────────────────────────────────────

function ThemePicker() {
  const { config, setConfig } = useThemeCustomizer();

  function update(partial: Partial<ThemeConfig>) {
    setConfig({ ...config, ...partial });
  }

  const lightThemes = BASE_THEMES.filter((t) => t.category === "light");
  const darkThemes  = BASE_THEMES.filter((t) => t.category === "dark");
  const activeBase  = BASE_THEMES.find((t) => t.id === config.baseThemeId);

  return (
    <div className="space-y-7">
      {/* Light */}
      <div>
        <Label>Light themes</Label>
        <div className="grid grid-cols-3 gap-2">
          {lightThemes.map((theme) => {
            const active = config.baseThemeId === theme.id;
            return (
              <button key={theme.id} type="button" onClick={() => update({ baseThemeId: theme.id })}
                className={cn(
                  "flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                <span className="w-full h-10 rounded-md border border-border/60 relative overflow-hidden"
                  style={{ background: theme.vars["--background"] }}>
                  <span className="absolute inset-x-2 top-2 h-1.5 rounded-full"
                    style={{ background: theme.vars["--foreground"], opacity: 0.5 }} />
                  <span className="absolute inset-x-2 bottom-2 h-1.5 rounded-full"
                    style={{ background: theme.vars["--muted"] }} />
                </span>
                <span className="text-xs text-muted-foreground">{theme.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Dark */}
      <div>
        <Label>Dark themes</Label>
        <div className="grid grid-cols-3 gap-2">
          {darkThemes.map((theme) => {
            const active = config.baseThemeId === theme.id;
            return (
              <button key={theme.id} type="button" onClick={() => update({ baseThemeId: theme.id })}
                className={cn(
                  "flex flex-col items-center gap-2 p-3 rounded-lg border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                <span className="w-full h-10 rounded-md border border-white/10 relative overflow-hidden"
                  style={{ background: theme.vars["--background"] }}>
                  <span className="absolute inset-x-2 top-2 h-1.5 rounded-full opacity-70"
                    style={{ background: theme.vars["--foreground"] }} />
                  <span className="absolute inset-x-2 bottom-2 h-1.5 rounded-full opacity-40"
                    style={{ background: theme.vars["--muted-foreground"] }} />
                </span>
                <span className="text-xs text-muted-foreground">{theme.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Accent */}
      <div>
        <Label>Accent color</Label>
        <div className="grid grid-cols-6 gap-2">
          {ACCENT_COLORS.map((accent) => {
            const active = config.accentId === accent.id;
            const isDark = activeBase?.category === "dark";
            const accentVars = isDark ? accent.dark : accent.light;
            return (
              <button key={accent.id} type="button" onClick={() => update({ accentId: accent.id })}
                className={cn(
                  "flex flex-col items-center gap-1.5 p-2 rounded-lg border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-transparent hover:border-muted-foreground/30"
                )}
              >
                <span className="w-8 h-8 rounded-full border border-border/40"
                  style={{ background: accentVars["--primary"] }} />
                <span className="text-[10px] text-muted-foreground leading-none">{accent.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Radius */}
      <div>
        <Label>Border radius</Label>
        <div className="flex gap-2">
          {RADIUS_OPTIONS.map((opt) => {
            const active = config.radius === opt.value;
            return (
              <button key={opt.value} type="button" onClick={() => update({ radius: opt.value })}
                className={cn(
                  "flex-1 flex flex-col items-center gap-2 py-3 px-2 border-2 transition-all cursor-pointer",
                  active ? "border-primary" : "border-border hover:border-muted-foreground/40"
                )}
                style={{ borderRadius: opt.value === "0rem" ? "0" : `calc(${opt.value} + 4px)` }}
              >
                <span className="w-8 h-8 border-2"
                  style={{
                    borderRadius: opt.value === "0rem" ? "0" : opt.value === "1rem" ? "9999px" : opt.value,
                    borderColor: active ? "var(--primary)" : "var(--muted-foreground)",
                    opacity: active ? 1 : 0.5,
                  }}
                />
                <span className="text-xs text-muted-foreground">{opt.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Font */}
      <div>
        <Label>Font</Label>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          {FONT_OPTIONS.map((opt) => {
            const active = config.fontFamily === opt.value;
            return (
              <button key={opt.value} type="button" onClick={() => update({ fontFamily: opt.value })}
                className={cn(
                  "flex flex-col items-center gap-1.5 py-3 px-3 border-2 rounded-lg transition-all cursor-pointer",
                  active ? "border-primary bg-primary/5" : "border-border hover:border-muted-foreground/40"
                )}
              >
                <span className="text-xl font-medium leading-none" style={{ fontFamily: opt.value }}>Aa</span>
                <span className="text-xs text-muted-foreground">{opt.label}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Preview */}
      <div>
        <Label>Preview</Label>
        <div className="border rounded-lg p-4 space-y-3">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center text-primary-foreground text-xs font-bold shrink-0">L</div>
            <div>
              <p className="text-sm font-semibold">Life Dashboard</p>
              <p className="text-xs text-muted-foreground">Your household OS</p>
            </div>
          </div>
          <div className="flex gap-2">
            <span className="px-3 py-1.5 text-xs font-medium rounded-md bg-primary text-primary-foreground">Primary</span>
            <span className="px-3 py-1.5 text-xs font-medium rounded-md border bg-card">Secondary</span>
            <span className="px-3 py-1.5 text-xs font-medium rounded-md bg-muted text-muted-foreground">Muted</span>
          </div>
          <p className="text-xs text-muted-foreground">The quick brown fox jumps over the lazy dog. 1234567890</p>
        </div>
      </div>

      {/* Reset */}
      <div>
        <button type="button"
          onClick={() => setConfig({
            baseThemeId: "clean",
            accentId: "neutral",
            radius: "0.625rem",
            fontFamily: "var(--font-geist-sans), sans-serif",
            customVars: {},
          })}
          className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 cursor-pointer"
        >
          Reset to defaults
        </button>
      </div>
    </div>
  );
}

// ── Per-variable color pickers ────────────────────────────────────────────────
// Reads the currently-computed value of a CSS variable by painting it onto a
// 1×1 canvas and reading back the RGB bytes. This works reliably for oklch()
// values since the browser does the conversion.

function resolveVarToHex(varName: string): string {
  if (typeof window === "undefined") return "#888888";
  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  if (!raw) return "#888888";
  try {
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = 1;
    const ctx = canvas.getContext("2d");
    if (!ctx) return "#888888";
    ctx.fillStyle = raw;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return `#${[r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("")}`;
  } catch {
    return "#888888";
  }
}

function CustomVarPickers() {
  const { config, setConfig } = useThemeCustomizer();
  const customVars = config.customVars ?? {};

  function handleChange(key: string, hex: string) {
    // Store as hex — the browser accepts it as an inline style value just fine.
    setConfig({ ...config, customVars: { ...customVars, [key]: hex } });
  }

  function handleReset(key: string) {
    const next = { ...customVars };
    delete next[key];
    setConfig({ ...config, customVars: next });
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground">
        Override individual color variables on top of the selected preset. Overridden variables are shown with a ring. Click <em>reset</em> to restore the preset value.
      </p>
      <div className="grid grid-cols-1 gap-2">
        {CUSTOM_VAR_OPTIONS.map(({ key, label }) => {
          const overridden = !!customVars[key];
          const currentHex = overridden ? customVars[key] : resolveVarToHex(key);
          return (
            <div key={key} className="flex items-center gap-3">
              {/* Native color picker — swatch acts as the visible trigger */}
              <label className="relative cursor-pointer shrink-0 group">
                <input
                  type="color"
                  value={currentHex}
                  onChange={(e) => handleChange(key, e.target.value)}
                  className="sr-only"
                />
                <span
                  className={cn(
                    "block w-7 h-7 rounded border-2 transition-all group-hover:scale-110",
                    overridden
                      ? "border-primary ring-2 ring-primary/30"
                      : "border-border"
                  )}
                  style={{ background: currentHex }}
                />
              </label>

              <span className={cn("flex-1 text-sm", overridden ? "font-medium text-foreground" : "text-muted-foreground")}>
                {label}
              </span>

              <span className="text-xs font-mono text-muted-foreground/50 hidden sm:block">{key}</span>

              {overridden && (
                <button
                  type="button"
                  onClick={() => handleReset(key)}
                  className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 shrink-0"
                >
                  reset
                </button>
              )}
            </div>
          );
        })}
      </div>

      {Object.keys(customVars).length > 0 && (
        <button
          type="button"
          onClick={() => setConfig({ ...config, customVars: {} })}
          className="text-xs text-muted-foreground hover:text-foreground underline underline-offset-2 mt-1 block"
        >
          Clear all overrides
        </button>
      )}
    </div>
  );
}

// ── Sections ──────────────────────────────────────────────────────────────────

function AppearanceSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>Appearance</SectionTitle>
      <SubSection title="Theme presets">
        <ThemePicker />
      </SubSection>
      <SubSection title="Custom color overrides">
        <CustomVarPickers />
      </SubSection>
    </div>
  );
}

// ── Pinned documents manager ──────────────────────────────────────────────────

function PinnedDocumentsManager() {
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
  const pinnedIds = sidebarConfig.pinnedDocumentIds ?? [];

  const { data: docsData, isLoading } = $api.useQuery(
    "get",
    "/documents",
    {},
    { enabled: pinnedIds.length > 0 },
  );

  function unpinDocument(docId: string) {
    setSidebarConfig({
      ...sidebarConfig,
      pinnedDocumentIds: pinnedIds.filter((id) => id !== docId),
      order: sidebarConfig.order.filter((id) => id !== `/documents/${docId}`),
    });
  }

  if (pinnedIds.length === 0) return null;

  const allDocs = docsData?.items ?? [];

  return (
    <div className="mt-4 pt-4 border-t space-y-1.5">
      <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
        Pinned documents
      </p>
      {isLoading ? (
        <div className="flex items-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" /> Loading…
        </div>
      ) : (
        pinnedIds.map((docId) => {
          const doc = allDocs.find((d) => d.id === docId);
          return (
            <div
              key={docId}
              className="flex items-center gap-2.5 px-3 py-2 rounded-md border bg-background text-sm"
            >
              <span className="text-base leading-none w-5 text-center shrink-0">
                {doc?.icon ?? "📄"}
              </span>
              <span className="flex-1 truncate text-sm font-medium">
                {doc ? doc.title : <span className="text-muted-foreground italic">Unknown document</span>}
              </span>
              <button
                type="button"
                onClick={() => unpinDocument(docId)}
                className="text-muted-foreground hover:text-destructive transition-colors cursor-pointer shrink-0"
                title="Remove from sidebar"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })
      )}
    </div>
  );
}

// ── Document pin dialog ───────────────────────────────────────────────────────

function PinDocumentDialog({
  onClose,
}: {
  onClose: () => void;
}) {
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
  const [search, setSearch] = useState("");

  const { data: docsData, isLoading } = $api.useQuery("get", "/documents", {});

  const alreadyPinned = new Set(sidebarConfig.pinnedDocumentIds ?? []);

  const filtered = (docsData?.items ?? [])
    .filter((d) => !d.archived_at)
    .filter((d) =>
      !search.trim() || d.title.toLowerCase().includes(search.trim().toLowerCase()),
    );

  function pinDocument(docId: string) {
    if (alreadyPinned.has(docId)) return;
    const href = `/documents/${docId}`;
    setSidebarConfig({
      ...sidebarConfig,
      pinnedDocumentIds: [...(sidebarConfig.pinnedDocumentIds ?? []), docId],
      // Add to order so it appears inline in the main drag list
      order: sidebarConfig.order.includes(href)
        ? sidebarConfig.order
        : [...sidebarConfig.order, href],
    });
    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background border rounded-lg shadow-xl w-full max-w-sm mx-4">
        <div className="flex items-center gap-3 px-4 pt-4 pb-3 border-b">
          <h2 className="text-base font-semibold flex-1">Pin a document</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <input
            autoFocus
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search documents…"
            className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <div className="max-h-64 overflow-y-auto space-y-0.5">
            {isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading…
              </div>
            )}
            {!isLoading && filtered.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">
                {search ? "No documents match." : "No documents yet."}
              </p>
            )}
            {filtered.map((doc) => {
              const isPinned = alreadyPinned.has(doc.id);
              return (
                <button
                  key={doc.id}
                  type="button"
                  disabled={isPinned}
                  onClick={() => pinDocument(doc.id)}
                  className={cn(
                    "flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-left text-sm transition-colors",
                    isPinned
                      ? "opacity-40 cursor-default"
                      : "hover:bg-muted cursor-pointer",
                  )}
                >
                  <span className="text-base leading-none w-5 text-center shrink-0">
                    {doc.icon ?? "📄"}
                  </span>
                  <span className="flex-1 truncate font-medium">{doc.title}</span>
                  {isPinned && (
                    <span className="text-[10px] text-muted-foreground font-medium border rounded px-1.5 py-0.5 shrink-0">
                      Pinned
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Select-project-to-pin dialog ─────────────────────────────────────────────

function SelectProjectDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
  const [search, setSearch] = useState("");

  const { data: projectsData, isLoading } = $api.useQuery("get", "/projects");
  const { mutateAsync: updateProject } = $api.useMutation("patch", "/projects/{project_id}");

  // All non-archived projects
  const allProjects = (projectsData?.items ?? []).filter((p) => !p.archived_at);

  const filtered = allProjects.filter((p) =>
    !search.trim() || p.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  async function selectProject(project: typeof allProjects[0]) {
    // Already pinned — do nothing
    if (project.show_in_nav) { onClose(); return; }

    // PATCH show_in_nav=true on the server
    await updateProject({
      params: { path: { project_id: project.id } },
      body: { show_in_nav: true },
    });
    qc.invalidateQueries({ queryKey: ["get", "/projects"] });

    // Add to SidebarConfig.order so it appears in the main drag list
    const href = `/projects/${project.id}`;
    setSidebarConfig({
      ...sidebarConfig,
      order: sidebarConfig.order.includes(href)
        ? sidebarConfig.order
        : [...sidebarConfig.order, href],
    });

    onClose();
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background border rounded-lg shadow-xl w-full max-w-sm mx-4">
        <div className="flex items-center gap-3 px-4 pt-4 pb-3 border-b">
          <h2 className="text-base font-semibold flex-1">Add project to nav</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground cursor-pointer"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <input
            autoFocus
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search projects…"
            className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <div className="max-h-64 overflow-y-auto space-y-0.5">
            {isLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-4 justify-center">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Loading…
              </div>
            )}
            {!isLoading && filtered.length === 0 && (
              <p className="text-sm text-muted-foreground text-center py-4">
                {search ? "No projects match." : "No projects yet."}
              </p>
            )}
            {filtered.map((project) => {
              const isAlreadyPinned = project.show_in_nav;
              return (
                <button
                  key={project.id}
                  type="button"
                  disabled={isAlreadyPinned}
                  onClick={() => selectProject(project)}
                  className={cn(
                    "flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-left text-sm transition-colors",
                    isAlreadyPinned
                      ? "opacity-40 cursor-default"
                      : "hover:bg-muted cursor-pointer",
                  )}
                >
                  <FolderKanban className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <span className="flex-1 truncate font-medium">{project.name}</span>
                  {isAlreadyPinned && (
                    <span className="text-[10px] text-muted-foreground font-medium border rounded px-1.5 py-0.5 shrink-0">
                      In nav
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}

function NavigationSection() {
  const [navCreateType, setNavCreateType] = useState<"project" | "document" | null>(null);

  return (
    <div className="space-y-5">
      <SectionTitle>Navigation</SectionTitle>
      <SubSection title="Sidebar layout">
        <SidebarCustomizer
          onCreateProject={() => setNavCreateType("project")}
          onCreatePage={() => setNavCreateType("document")}
        />
      </SubSection>

      {navCreateType === "project" && (
        <SelectProjectDialog onClose={() => setNavCreateType(null)} />
      )}

      {navCreateType === "document" && (
        <PinDocumentDialog onClose={() => setNavCreateType(null)} />
      )}
    </div>
  );
}

// ── Pages section ─────────────────────────────────────────────────────────────

type CollectionFormState = {
  name: string;
  icon: string;
  domain: "notes" | "documents";
  hasAutoCreate: boolean;
  titleTemplate: string;
};

const DEFAULT_COLLECTION_FORM: CollectionFormState = {
  name: "",
  icon: "",
  domain: "notes",
  hasAutoCreate: false,
  titleTemplate: "%B %d, %Y",
};

function CollectionDialog({
  mode,
  initial,
  onSave,
  onClose,
}: {
  mode: "create" | "edit";
  initial?: Partial<CollectionFormState>;
  onSave: (form: CollectionFormState) => Promise<void>;
  onClose: () => void;
}) {
  const [form, setForm] = useState<CollectionFormState>({
    ...DEFAULT_COLLECTION_FORM,
    ...initial,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(form);
      onClose();
    } catch {
      setError("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background border rounded-lg shadow-xl w-full max-w-sm mx-4 p-6">
        <h2 className="text-base font-semibold mb-4">
          {mode === "create" ? "New collection" : "Edit collection"}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input
              autoFocus
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Journal"
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>

          {/* Icon */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Icon <span className="font-normal opacity-60">(emoji, optional)</span>
            </label>
            <input
              type="text"
              value={form.icon}
              onChange={(e) => setForm((f) => ({ ...f, icon: e.target.value }))}
              placeholder="📓"
              maxLength={4}
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>

          {/* Domain */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Domain</label>
            <div className="flex gap-2">
              {(["notes", "documents"] as const).map((d) => {
                const Icon = d === "notes" ? BookOpen : FileText;
                return (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setForm((f) => ({ ...f, domain: d }))}
                    className={cn(
                      "flex-1 flex items-center justify-center gap-2 h-9 rounded-md border text-sm font-medium transition-colors",
                      form.domain === d
                        ? "bg-primary text-primary-foreground border-primary"
                        : "bg-background text-muted-foreground hover:bg-muted",
                    )}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {d === "notes" ? "Notes" : "Documents"}
                  </button>
                );
              })}
            </div>
          </div>

          {/* Auto-create rule */}
          <div className="space-y-2">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.hasAutoCreate}
                onChange={(e) => setForm((f) => ({ ...f, hasAutoCreate: e.target.checked }))}
                className="rounded"
              />
              <span className="text-xs font-medium text-muted-foreground">
                Auto-create a daily entry
              </span>
            </label>
            {form.hasAutoCreate && (
              <div className="ml-5 space-y-1.5">
                <label className="text-xs text-muted-foreground">
                  Title format{" "}
                  <a
                    href="https://strftime.org"
                    target="_blank"
                    rel="noreferrer"
                    className="underline opacity-60 hover:opacity-100"
                  >
                    (strftime)
                  </a>
                </label>
                <input
                  type="text"
                  value={form.titleTemplate}
                  onChange={(e) => setForm((f) => ({ ...f, titleTemplate: e.target.value }))}
                  placeholder="%B %d, %Y"
                  className="w-full h-8 px-2 rounded-md border bg-background text-xs focus:outline-none focus:ring-2 focus:ring-primary/50"
                />
                <p className="text-[11px] text-muted-foreground">
                  Example: <code>%B %d, %Y</code> → May 11, 2026
                </p>
              </div>
            )}
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-1.5 rounded-md text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!form.name.trim() || saving}
              className="px-4 py-1.5 rounded-md text-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin inline" /> : mode === "create" ? "Create" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function PagesSection() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<
    | { mode: "create" }
    | { mode: "edit"; id: string; initial: CollectionFormState }
    | null
  >(null);

  const { data, isLoading } = $api.useQuery("get", "/collections");
  const createCollection = $api.useMutation("post", "/collections");
  const updateCollection = $api.useMutation("patch", "/collections/{collection_id}");
  const deleteCollection = $api.useMutation("delete", "/collections/{collection_id}");

  const collections = data?.items ?? [];

  async function handleCreate(form: CollectionFormState) {
    await createCollection.mutateAsync({
      body: {
        name: form.name,
        icon: form.icon || null,
        domain: form.domain,
        auto_create_rule: form.hasAutoCreate
          ? { frequency: "daily", title_template: form.titleTemplate }
          : null,
        default_tags: [],
        sort_order: collections.length,
      },
    });
    qc.invalidateQueries({ queryKey: ["get", "/collections"] });
  }

  async function handleEdit(id: string, form: CollectionFormState) {
    await updateCollection.mutateAsync({
      params: { path: { collection_id: id } },
      body: {
        name: form.name,
        icon: form.icon || null,
        auto_create_rule: form.hasAutoCreate
          ? { frequency: "daily", title_template: form.titleTemplate }
          : null,
      },
    });
    qc.invalidateQueries({ queryKey: ["get", "/collections"] });
  }

  async function handleDelete(id: string, name: string) {
    if (!confirm(`Delete "${name}"? The entries inside will not be deleted, but they'll no longer be grouped under this collection.`)) return;
    await deleteCollection.mutateAsync({
      params: { path: { collection_id: id } },
    });
    qc.invalidateQueries({ queryKey: ["get", "/collections"] });
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Pages</SectionTitle>

      <SubSection title="Custom collections">
        <p className="text-sm text-muted-foreground mb-4">
          Collections are custom pages backed by Notes or Documents — like a Journal, Reading List, or Project Log. Each appears in your sidebar and can have a default template and optional daily auto-entry.
        </p>

        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        ) : (
          <div className="space-y-2">
            {collections.length === 0 && (
              <p className="text-sm text-muted-foreground py-2">No collections yet.</p>
            )}
            {collections.map((col) => {
              const DomainIcon = col.domain === "notes" ? BookOpen : FileText;
              return (
                <div
                  key={col.id}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg border bg-card"
                >
                  <span className="text-xl leading-none w-7 text-center shrink-0">
                    {col.icon ?? (col.domain === "notes" ? "📓" : "📄")}
                  </span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium truncate">{col.name}</p>
                    <div className="flex items-center gap-1.5 mt-0.5">
                      <DomainIcon className="h-3 w-3 text-muted-foreground" />
                      <span className="text-[11px] text-muted-foreground capitalize">
                        {col.domain}
                      </span>
                      {col.auto_create_rule && (
                        <>
                          <span className="text-muted-foreground opacity-40">·</span>
                          <RefreshCw className="h-3 w-3 text-muted-foreground" />
                          <span className="text-[11px] text-muted-foreground">Daily</span>
                        </>
                      )}
                    </div>
                  </div>
                  <button
                    type="button"
                    title="Edit"
                    onClick={() =>
                      setDialog({
                        mode: "edit",
                        id: col.id,
                        initial: {
                          name: col.name,
                          icon: col.icon ?? "",
                          domain: col.domain,
                          hasAutoCreate: !!col.auto_create_rule,
                          titleTemplate: col.auto_create_rule?.title_template ?? "%B %d, %Y",
                        },
                      })
                    }
                    className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors shrink-0"
                  >
                    <Pencil className="h-3.5 w-3.5" />
                  </button>
                  <button
                    type="button"
                    title="Delete collection"
                    onClick={() => handleDelete(col.id, col.name)}
                    className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors shrink-0"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              );
            })}
          </div>
        )}

        <button
          type="button"
          onClick={() => setDialog({ mode: "create" })}
          className="mt-3 flex items-center gap-2 px-3 py-2 rounded-md border border-dashed text-sm text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors w-full"
        >
          <Plus className="h-4 w-4" />
          New collection
        </button>
      </SubSection>

      {dialog?.mode === "create" && (
        <CollectionDialog
          mode="create"
          onSave={handleCreate}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.mode === "edit" && (
        <CollectionDialog
          mode="edit"
          initial={dialog.initial}
          onSave={(form) => handleEdit(dialog.id, form)}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

// ── Projects section ─────────────────────────────────────────────────────────

type ProjectStatus = "backlog" | "active" | "on_deck" | "in_progress" | "complete" | "archived";

const PROJECT_STATUSES: { value: ProjectStatus; label: string }[] = [
  { value: "backlog",     label: "Backlog"      },
  { value: "active",      label: "Active"       },
  { value: "on_deck",     label: "On deck"      },
  { value: "in_progress", label: "In progress"  },
  { value: "complete",    label: "Complete"     },
  { value: "archived",    label: "Archived"     },
];

const STATUS_BADGE: Record<ProjectStatus, string> = {
  backlog:     "bg-muted text-muted-foreground",
  active:      "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300",
  on_deck:     "bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300",
  in_progress: "bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300",
  complete:    "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300",
  archived:    "bg-muted text-muted-foreground opacity-60",
};

type ProjectFormState = {
  name: string;
  description: string;
  status: ProjectStatus;
  due_date: string;
  show_in_nav: boolean;
  parent_id: string;
};

const DEFAULT_PROJECT_FORM: ProjectFormState = {
  name: "",
  description: "",
  status: "active",
  due_date: "",
  show_in_nav: false,
  parent_id: "",
};

function ProjectDialog({
  mode,
  initial,
  parentOptions,
  onSave,
  onClose,
}: {
  mode: "create" | "edit";
  initial?: Partial<ProjectFormState>;
  parentOptions: { id: string; name: string }[];
  onSave: (form: ProjectFormState) => Promise<void>;
  onClose: () => void;
}) {
  const [form, setForm] = useState<ProjectFormState>({
    ...DEFAULT_PROJECT_FORM,
    ...initial,
  });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!form.name.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await onSave(form);
      onClose();
    } catch {
      setError("Failed to save. Please try again.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background border rounded-lg shadow-xl w-full max-w-sm mx-4 p-6">
        <h2 className="text-base font-semibold mb-4">
          {mode === "create" ? "New project" : "Edit project"}
        </h2>
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Name</label>
            <input
              autoFocus
              type="text"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              placeholder="e.g. Home Renovation"
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Description <span className="font-normal opacity-60">(optional)</span>
            </label>
            <textarea
              rows={2}
              value={form.description}
              onChange={(e) => setForm((f) => ({ ...f, description: e.target.value }))}
              placeholder="What is this project about?"
              className="w-full px-3 py-2 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 resize-none"
            />
          </div>

          {/* Status */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">Status</label>
            <div className="relative">
              <select
                value={form.status}
                onChange={(e) => setForm((f) => ({ ...f, status: e.target.value as ProjectStatus }))}
                className="w-full h-9 px-3 rounded-md border bg-background text-sm appearance-none focus:outline-none focus:ring-2 focus:ring-primary/50 pr-8"
              >
                {PROJECT_STATUSES.map((s) => (
                  <option key={s.value} value={s.value}>{s.label}</option>
                ))}
              </select>
              <ChevronDown className="h-4 w-4 absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
            </div>
          </div>

          {/* Parent project */}
          {parentOptions.length > 0 && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-muted-foreground">
                Parent project <span className="font-normal opacity-60">(optional)</span>
              </label>
              <div className="relative">
                <select
                  value={form.parent_id}
                  onChange={(e) => setForm((f) => ({ ...f, parent_id: e.target.value }))}
                  className="w-full h-9 px-3 rounded-md border bg-background text-sm appearance-none focus:outline-none focus:ring-2 focus:ring-primary/50 pr-8"
                >
                  <option value="">None (top-level)</option>
                  {parentOptions.map((p) => (
                    <option key={p.id} value={p.id}>{p.name}</option>
                  ))}
                </select>
                <ChevronDown className="h-4 w-4 absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
              </div>
            </div>
          )}

          {/* Due date */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Due date <span className="font-normal opacity-60">(optional)</span>
            </label>
            <input
              type="date"
              value={form.due_date}
              onChange={(e) => setForm((f) => ({ ...f, due_date: e.target.value }))}
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            />
          </div>

          {/* Pin to sidebar */}
          <label className="flex items-center gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={form.show_in_nav}
              onChange={(e) => setForm((f) => ({ ...f, show_in_nav: e.target.checked }))}
              className="rounded"
            />
            <span className="text-sm text-muted-foreground">Pin to sidebar</span>
          </label>

          {error && <p className="text-xs text-destructive">{error}</p>}

          <div className="flex justify-end gap-2 pt-1">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-1.5 rounded-md text-sm text-muted-foreground hover:bg-muted transition-colors"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!form.name.trim() || saving}
              className="px-4 py-1.5 rounded-md text-sm bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin inline" /> : mode === "create" ? "Create" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function ProjectsSection() {
  const qc = useQueryClient();
  const [dialog, setDialog] = useState<
    | { mode: "create" }
    | { mode: "edit"; id: string; initial: ProjectFormState }
    | null
  >(null);

  const { data, isLoading } = $api.useQuery("get", "/projects");
  const createProject = $api.useMutation("post", "/projects");
  const updateProject = $api.useMutation("patch", "/projects/{project_id}");
  const archiveProject = $api.useMutation("post", "/projects/{project_id}/archive");

  const allProjects = data?.items ?? [];
  // Show non-archived first, then archived at bottom; system projects first within each group
  const visible = allProjects.filter((p) => !p.archived_at);
  const archived = allProjects.filter((p) => !!p.archived_at);
  const [showArchived, setShowArchived] = useState(false);

  function invalidate() {
    qc.invalidateQueries({ queryKey: ["get", "/projects"] });
  }

  async function handleCreate(form: ProjectFormState) {
    await createProject.mutateAsync({
      body: {
        name: form.name,
        description: form.description || null,
        status: form.status,
        due_date: form.due_date || null,
        parent_id: form.parent_id || null,
        show_in_nav: form.show_in_nav,
      },
    });
    invalidate();
  }

  async function handleEdit(id: string, form: ProjectFormState) {
    await updateProject.mutateAsync({
      params: { path: { project_id: id } },
      body: {
        name: form.name,
        description: form.description || null,
        status: form.status,
        due_date: form.due_date || null,
        parent_id: form.parent_id || null,
        show_in_nav: form.show_in_nav,
      },
    });
    invalidate();
  }

  async function handlePinToggle(id: string, current: boolean) {
    await updateProject.mutateAsync({
      params: { path: { project_id: id } },
      body: { show_in_nav: !current },
    });
    invalidate();
  }

  async function handleArchive(id: string, name: string) {
    if (!confirm(`Archive "${name}"? You can restore it later.`)) return;
    await archiveProject.mutateAsync({ params: { path: { project_id: id } } });
    invalidate();
  }

  // Parent options for the dialog: non-system, non-archived projects
  const parentOptions = visible
    .filter((p) => !p.is_system)
    .map((p) => ({ id: p.id, name: p.name }));

  function ProjectRow({ project }: { project: typeof allProjects[0] }) {
    const statusMeta = PROJECT_STATUSES.find((s) => s.value === project.status);
    return (
      <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg border bg-card">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-medium truncate">{project.name}</p>
            {project.is_system && (
              <span className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground border rounded px-1.5 py-0.5 shrink-0">
                <Lock className="h-2.5 w-2.5" />
                System
              </span>
            )}
            <span
              className={cn(
                "text-[10px] font-medium rounded px-1.5 py-0.5 shrink-0",
                STATUS_BADGE[project.status as ProjectStatus] ?? "bg-muted text-muted-foreground",
              )}
            >
              {statusMeta?.label ?? project.status}
            </span>
          </div>
          {project.description && (
            <p className="text-xs text-muted-foreground truncate mt-0.5">{project.description}</p>
          )}
        </div>

        {/* Pin toggle */}
        <button
          type="button"
          title={project.show_in_nav ? "Unpin from sidebar" : "Pin to sidebar"}
          onClick={() => handlePinToggle(project.id, project.show_in_nav)}
          className={cn(
            "h-7 w-7 flex items-center justify-center rounded-md transition-colors shrink-0",
            project.show_in_nav
              ? "text-primary hover:text-primary hover:bg-primary/10"
              : "text-muted-foreground hover:text-foreground hover:bg-muted",
          )}
        >
          {project.show_in_nav
            ? <Pin className="h-3.5 w-3.5 fill-current" />
            : <PinOff className="h-3.5 w-3.5" />}
        </button>

        {/* Edit — only for non-system projects */}
        {!project.is_system && (
          <>
            <button
              type="button"
              title="Edit"
              onClick={() =>
                setDialog({
                  mode: "edit",
                  id: project.id,
                  initial: {
                    name: project.name,
                    description: project.description ?? "",
                    status: project.status as ProjectStatus,
                    due_date: project.due_date ?? "",
                    show_in_nav: project.show_in_nav,
                    parent_id: project.parent_id ?? "",
                  },
                })
              }
              className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-foreground hover:bg-muted transition-colors shrink-0"
            >
              <Pencil className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Archive project"
              onClick={() => handleArchive(project.id, project.name)}
              className="h-7 w-7 flex items-center justify-center rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors shrink-0"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Projects</SectionTitle>

      <SubSection title="All projects">
        <p className="text-sm text-muted-foreground mb-4">
          Projects group your to-dos and sub-projects. Pin a project to the sidebar for quick access. System projects (like To-dos) can be pinned but not deleted.
        </p>

        {isLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" />
            Loading…
          </div>
        ) : (
          <div className="space-y-2">
            {visible.length === 0 && (
              <p className="text-sm text-muted-foreground py-2">No projects yet.</p>
            )}
            {visible.map((proj) => (
              <ProjectRow key={proj.id} project={proj} />
            ))}

            {archived.length > 0 && (
              <div className="mt-2">
                <button
                  type="button"
                  onClick={() => setShowArchived((v) => !v)}
                  className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer mb-2"
                >
                  <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", showArchived && "rotate-180")} />
                  Archived ({archived.length})
                </button>
                {showArchived && (
                  <div className="space-y-2 opacity-60">
                    {archived.map((proj) => (
                      <ProjectRow key={proj.id} project={proj} />
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={() => setDialog({ mode: "create" })}
          className="mt-3 flex items-center gap-2 px-3 py-2 rounded-md border border-dashed text-sm text-muted-foreground hover:text-foreground hover:border-foreground/30 transition-colors w-full"
        >
          <Plus className="h-4 w-4" />
          New project
        </button>
      </SubSection>

      {dialog?.mode === "create" && (
        <ProjectDialog
          mode="create"
          parentOptions={parentOptions}
          onSave={handleCreate}
          onClose={() => setDialog(null)}
        />
      )}
      {dialog?.mode === "edit" && (
        <ProjectDialog
          mode="edit"
          initial={dialog.initial}
          parentOptions={parentOptions}
          onSave={(form) => handleEdit(dialog.id, form)}
          onClose={() => setDialog(null)}
        />
      )}
    </div>
  );
}

function AccountSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>Account</SectionTitle>
      <SubSection title="Profile">
        <div className="flex items-center gap-5 mb-5">
          {/* Avatar placeholder — upload will be wired up once the API supports it */}
          <div className="h-16 w-16 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xl font-semibold shrink-0">
            ?
          </div>
          <div>
            <p className="text-sm font-medium mb-1">Profile photo</p>
            <p className="text-xs text-muted-foreground">
              Avatar upload coming soon. Your initials are shown in the sidebar for now.
            </p>
          </div>
        </div>
        <p className="text-sm text-muted-foreground">
          Display name, email, and password changes — coming soon.
        </p>
      </SubSection>
    </div>
  );
}

function HouseholdSection() {
  return (
    <div className="space-y-5">
      <SectionTitle>Household</SectionTitle>
      <SubSection title="Members">
        <p className="text-sm text-muted-foreground">
          Household member management — invite, roles, and per-member views — coming soon.
        </p>
      </SubSection>
    </div>
  );
}

// ── AI section ───────────────────────────────────────────────────────────────

type AiSettings = {
  provider: "anthropic" | "openai" | "ollama";
  retention_days: number | null;
  has_custom_key: boolean;
};

const PROVIDER_OPTIONS: { value: AiSettings["provider"]; label: string; placeholder: string }[] = [
  { value: "anthropic", label: "Anthropic (Claude)",  placeholder: "sk-ant-api03-…" },
  { value: "openai",    label: "OpenAI",              placeholder: "sk-…"           },
  { value: "ollama",    label: "Ollama (local)",       placeholder: "http://localhost:11434" },
];

const RETENTION_OPTIONS: { value: number | null; label: string }[] = [
  { value: 30,   label: "30 days"     },
  { value: 60,   label: "60 days"     },
  { value: 90,   label: "90 days"     },
  { value: 180,  label: "6 months"    },
  { value: 365,  label: "1 year"      },
  { value: null, label: "Keep forever"},
];

async function fetchAiSettings(): Promise<AiSettings> {
  const token = getAccessToken();
  const res = await fetch("/api/ai/settings", {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to load AI settings");
  return res.json() as Promise<AiSettings>;
}

async function patchAiSettings(patch: Record<string, unknown>): Promise<AiSettings> {
  const token = getAccessToken();
  const res = await fetch("/api/ai/settings", {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(patch),
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || "Failed to save AI settings");
  }
  return res.json() as Promise<AiSettings>;
}

function AiSection() {
  const qc = useQueryClient();
  const { data: settings, isLoading, isError } = useQuery<AiSettings>({
    queryKey: ["ai", "settings"],
    queryFn: fetchAiSettings,
  });

  // Key editing state
  const [keyInput, setKeyInput]     = useState("");
  const [showKey, setShowKey]       = useState(false);
  const [editingKey, setEditingKey] = useState(false);
  const [keyError, setKeyError]     = useState<string | null>(null);
  const [keySaving, setKeySaving]   = useState(false);

  // Generic saving indicator (provider, retention)
  const [saving, setSaving] = useState(false);

  async function save(patch: Record<string, unknown>) {
    setSaving(true);
    try {
      await patchAiSettings(patch);
      await qc.invalidateQueries({ queryKey: ["ai", "settings"] });
    } catch {
      // Surface silently for now — individual fields can add error handling later
    } finally {
      setSaving(false);
    }
  }

  async function saveKey() {
    const trimmed = keyInput.trim();
    if (!trimmed) return;
    setKeySaving(true);
    setKeyError(null);
    try {
      await patchAiSettings({ api_key: trimmed });
      await qc.invalidateQueries({ queryKey: ["ai", "settings"] });
      setKeyInput("");
      setEditingKey(false);
    } catch (e) {
      setKeyError(e instanceof Error ? e.message : "Failed to save. Please try again.");
    } finally {
      setKeySaving(false);
    }
  }

  async function removeKey() {
    setSaving(true);
    try {
      await patchAiSettings({ clear_api_key: true });
      await qc.invalidateQueries({ queryKey: ["ai", "settings"] });
      setEditingKey(false);
      setKeyInput("");
    } finally {
      setSaving(false);
    }
  }

  if (isLoading) {
    return (
      <div className="space-y-5">
        <SectionTitle>AI</SectionTitle>
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-8">
          <Loader2 className="h-4 w-4 animate-spin" />
          Loading…
        </div>
      </div>
    );
  }

  if (isError || !settings) {
    return (
      <div className="space-y-5">
        <SectionTitle>AI</SectionTitle>
        <div className="flex items-center gap-2 text-sm text-destructive py-4">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to load AI settings. Reload the page to try again.
        </div>
      </div>
    );
  }

  const providerMeta = PROVIDER_OPTIONS.find((p) => p.value === settings.provider)!;
  const isOllama     = settings.provider === "ollama";
  const keyLabel     = isOllama ? "Server URL" : "API key";

  const showKeyForm  = !settings.has_custom_key || editingKey;

  return (
    <div className="space-y-5">
      <SectionTitle>AI</SectionTitle>

      {/* ── Provider ── */}
      <SubSection title="Provider">
        <div className="flex flex-col gap-2">
          {PROVIDER_OPTIONS.map((opt) => {
            const active = settings.provider === opt.value;
            return (
              <button
                key={opt.value}
                type="button"
                disabled={saving}
                onClick={() => !active && save({ provider: opt.value })}
                className={cn(
                  "flex items-center gap-3 px-4 py-3 rounded-lg border-2 text-left transition-all cursor-pointer disabled:cursor-default",
                  active
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-muted-foreground/40 hover:bg-muted/30",
                )}
              >
                <span
                  className={cn(
                    "h-4 w-4 rounded-full border-2 shrink-0 flex items-center justify-center",
                    active ? "border-primary" : "border-muted-foreground/40",
                  )}
                >
                  {active && <span className="h-2 w-2 rounded-full bg-primary" />}
                </span>
                <span className={cn("text-sm font-medium", active ? "text-foreground" : "text-muted-foreground")}>
                  {opt.label}
                </span>
                {opt.value === "ollama" && (
                  <span className="ml-auto text-[10px] font-medium uppercase tracking-wide text-muted-foreground border rounded px-1.5 py-0.5">
                    Self-hosted
                  </span>
                )}
              </button>
            );
          })}
        </div>
        {saving && (
          <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" /> Saving…
          </p>
        )}
      </SubSection>

      {/* ── API Key / Server URL ── */}
      <SubSection title={keyLabel}>
        {settings.has_custom_key && !editingKey ? (
          /* Key is saved — show status + action buttons */
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400 font-medium">
                <Check className="h-4 w-4" />
                {keyLabel} saved
              </span>
              <span className="text-muted-foreground text-sm">— stored encrypted, never displayed</span>
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => { setEditingKey(true); setKeyInput(""); }}
                className="text-xs px-3 py-1.5 rounded-md border border-border hover:bg-muted transition-colors cursor-pointer"
              >
                Update {keyLabel.toLowerCase()}
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={removeKey}
                className="text-xs px-3 py-1.5 rounded-md border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors cursor-pointer disabled:opacity-50"
              >
                Remove
              </button>
            </div>
          </div>
        ) : (
          /* No key saved, or updating — show input */
          <div className="space-y-3">
            {!settings.has_custom_key && (
              <p className="text-xs text-muted-foreground">
                {isOllama
                  ? "Enter the URL of your local Ollama server."
                  : `Enter your ${providerMeta.label} API key. It will be stored encrypted and never shown again.`}
              </p>
            )}
            <div className="flex gap-2">
              <div className="relative flex-1">
                <input
                  type={showKey ? "text" : "password"}
                  value={keyInput}
                  onChange={(e) => setKeyInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") saveKey(); if (e.key === "Escape") { setEditingKey(false); setKeyInput(""); }}}
                  placeholder={providerMeta.placeholder}
                  autoComplete="off"
                  spellCheck={false}
                  className="w-full text-sm font-mono bg-background border border-border rounded-md px-3 py-2 pr-9 outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
                />
                <button
                  type="button"
                  onClick={() => setShowKey((v) => !v)}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground cursor-pointer"
                  aria-label={showKey ? "Hide key" : "Show key"}
                >
                  {showKey ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
              <button
                type="button"
                disabled={keySaving || !keyInput.trim()}
                onClick={saveKey}
                className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40 cursor-pointer disabled:cursor-default shrink-0"
              >
                {keySaving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
              </button>
              {editingKey && (
                <button
                  type="button"
                  onClick={() => { setEditingKey(false); setKeyInput(""); setKeyError(null); }}
                  className="px-3 py-2 text-sm rounded-md border border-border hover:bg-muted transition-colors cursor-pointer shrink-0"
                >
                  Cancel
                </button>
              )}
            </div>
            {keyError && (
              <p className="text-xs text-destructive flex items-center gap-1.5">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {keyError}
              </p>
            )}
          </div>
        )}
      </SubSection>

      {/* ── Conversation history ── */}
      <SubSection title="Conversation history">
        <p className="text-xs text-muted-foreground mb-4">
          Conversations older than this limit are deleted automatically. Set to{" "}
          <em>Keep forever</em> to retain all history.
        </p>
        <div className="relative max-w-xs">
          <select
            value={settings.retention_days ?? ""}
            disabled={saving}
            onChange={(e) => {
              const raw = e.target.value;
              save({ retention_days: raw === "" ? null : Number(raw) });
            }}
            className="w-full text-sm bg-background border border-border rounded-md px-3 py-2 appearance-none outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary pr-8 cursor-pointer disabled:opacity-50"
          >
            {RETENTION_OPTIONS.map((opt) => (
              <option key={String(opt.value)} value={opt.value ?? ""}>
                {opt.label}
              </option>
            ))}
          </select>
          <ChevronDown className="h-4 w-4 absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
        </div>
        {saving && (
          <p className="text-xs text-muted-foreground mt-2 flex items-center gap-1.5">
            <Loader2 className="h-3 w-3 animate-spin" /> Saving…
          </p>
        )}
      </SubSection>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const [active, setActive] = useState<Section>("appearance");

  return (
    <div className="flex h-full">
      {/* Settings left-nav */}
      <div className="w-52 shrink-0 border-r bg-card p-4">
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-3 mb-3">
          Settings
        </p>
        <SettingsNav active={active} onChange={setActive} />
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto p-8 max-w-2xl">
        {active === "appearance"  && <AppearanceSection />}
        {active === "navigation"  && <NavigationSection />}
        {active === "account"     && <AccountSection />}
        {active === "household"   && <HouseholdSection />}
        {active === "ai"          && <AiSection />}
      </div>
    </div>
  );
}
