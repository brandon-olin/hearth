"use client";

import { Fragment, useRef, useState } from "react";
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
  LogOut,
  Shield,
} from "lucide-react";
import { VisibilitySettingsSection } from "@/components/settings/visibility-settings-section";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { cn } from "@/lib/utils";
import { getAccessToken } from "@/lib/auth/token";
import { useAuth } from "@/lib/auth/context";
import { useAppConfig } from "@/lib/app-config";
import { $api } from "@/lib/api/query";
import { apiBaseUrl } from "@/lib/api/client";
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
import { ROLE_LABEL } from "@/lib/roles";
import { type NavItem } from "@/lib/sidebar/nav-items";
import { useNavItems } from "@/lib/sidebar/use-nav-items";
import {
  FOLDER_ICON_GROUPS,
  resolveFolderIcon,
  DEFAULT_FOLDER_ICON,
} from "@/lib/sidebar/folder-icons";

// ── Left nav ──────────────────────────────────────────────────────────────────

type Section = "appearance" | "navigation" | "account" | "household" | "visibility" | "ai" | "templates" | "collections";

const SECTIONS: { id: Section; label: string; icon: React.ElementType }[] = [
  { id: "household",   label: "Household",   icon: Home          },
  { id: "visibility",  label: "Visibility",  icon: Shield        },
  { id: "account",     label: "Account",     icon: User          },
  { id: "navigation",  label: "Navigation",  icon: GripVertical  },
  { id: "appearance",  label: "Appearance",  icon: Palette       },
  { id: "templates",    label: "Templates",   icon: BookOpen      },
  { id: "collections", label: "Collections", icon: FolderKanban  },
  { id: "ai",          label: "AI",          icon: Bot           },
];

const ADMIN_ROLES = new Set(["owner", "admin"]);

const ADMIN_SECTION_IDS = new Set<Section>(["household", "visibility"]);

function NavItem({ id, label, icon: Icon, active, onChange }: {
  id: Section;
  label: string;
  icon: React.ElementType;
  active: Section;
  onChange: (s: Section) => void;
}) {
  return (
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
  );
}

function SettingsNav({
  active,
  onChange,
  visibleSections,
  isAdmin,
}: {
  active: Section;
  onChange: (s: Section) => void;
  visibleSections: Set<Section>;
  isAdmin: boolean;
}) {
  const adminSections = SECTIONS.filter((s) => visibleSections.has(s.id) && ADMIN_SECTION_IDS.has(s.id));
  const userSections  = SECTIONS.filter((s) => visibleSections.has(s.id) && !ADMIN_SECTION_IDS.has(s.id));

  return (
    <nav className="space-y-4">
      {isAdmin && adminSections.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-3 mb-1">
            Admin Settings
          </p>
          <div className="space-y-0.5">
            {adminSections.map(({ id, label, icon }) => (
              <NavItem key={id} id={id} label={label} icon={icon} active={active} onChange={onChange} />
            ))}
          </div>
        </div>
      )}
      <div>
        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide px-3 mb-1">
          {isAdmin ? "General Settings" : "Settings"}
        </p>
        <div className="space-y-0.5">
          {userSections.map(({ id, label, icon }) => (
            <NavItem key={id} id={id} label={label} icon={icon} active={active} onChange={onChange} />
          ))}
        </div>
      </div>
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
  onSelectCollection,
}: {
  onCreateProject?: () => void;
  onCreatePage?: () => void;
  onSelectCollection?: () => void;
}) {
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
  const { items: allNavItems } = useNavItems();
  const qc = useQueryClient();
  const { mutateAsync: updateProject } = $api.useMutation("patch", "/projects/{project_id}");
  const { mutateAsync: updateCollection } = $api.useMutation("patch", "/collections/{collection_id}");

  // Unified drag state — works for both nav item hrefs and folder IDs
  const dragIdRef = useRef<string | null>(null);
  // dropIndicator: where the dragged item will land
  //   "before"/"after" = reorder line above/below target
  //   "into"           = insert into folder (folder highlight)
  const [dropIndicator, setDropIndicator] = useState<{ id: string; action: "before" | "after" | "into" } | null>(null);

  // Drag state for reordering items within a folder's expanded contents panel
  const folderDragRef = useRef<string | null>(null);
  const [folderDropIndicator, setFolderDropIndicator] = useState<{ href: string; position: "before" | "after" } | null>(null);

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

  /** Remove a project, document, or collection from the sidebar nav */
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
    } else if (item.isCollection && item.collectionId) {
      await updateCollection({
        params: { path: { collection_id: item.collectionId } },
        body: { show_in_nav: false },
      });
      qc.invalidateQueries({ queryKey: ["get", "/collections"] });
      setSidebarConfig({
        ...sidebarConfig,
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

  function reorderInFolder(folderId: string, fromHref: string, toHref: string, position: "before" | "after") {
    setSidebarConfig({
      ...sidebarConfig,
      folders: folders.map((f) => {
        if (f.id !== folderId) return f;
        const next = [...f.hrefs];
        const fromIdx = next.indexOf(fromHref);
        const toIdx   = next.indexOf(toHref);
        if (fromIdx === -1 || toIdx === -1) return f;
        next.splice(fromIdx, 1);
        const adjustedToIdx = fromIdx < toIdx ? toIdx - 1 : toIdx;
        const insertAt = position === "after" ? adjustedToIdx + 1 : adjustedToIdx;
        next.splice(insertAt, 0, fromHref);
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
      order: order.filter((o) => o !== href),
    });
  }

  /** Insert href into a folder at a specific position relative to another item. */
  function moveToFolderAtPosition(href: string, targetFolderId: string, relativeToHref: string, position: "before" | "after") {
    const updatedFolders = folders
      .map((f) => ({ ...f, hrefs: f.hrefs.filter((h) => h !== href) }))
      .map((f) => {
        if (f.id !== targetFolderId) return f;
        const hrefs = [...f.hrefs];
        const relIdx = hrefs.indexOf(relativeToHref);
        const insertAt = relIdx === -1 ? hrefs.length : position === "after" ? relIdx + 1 : relIdx;
        hrefs.splice(insertAt, 0, href);
        return { ...f, hrefs };
      });
    setSidebarConfig({
      ...sidebarConfig,
      folders: updatedFolders,
      order: order.filter((o) => o !== href),
    });
  }

  // ── unified drag-to-reorder + drag-into-folder ──────────────────────────────

  function handleDragStart(id: string) {
    dragIdRef.current = id;
  }

  function handleDragOver(e: React.DragEvent, targetId: string) {
    e.preventDefault();
    if (dragIdRef.current === targetId) return;

    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const relY  = (e.clientY - rect.top) / rect.height;

    const targetIsFolder  = !targetId.startsWith("/") && folders.some((f) => f.id === targetId);
    const fromIsNavItem   = dragIdRef.current?.startsWith("/") ?? false;

    let action: "before" | "after" | "into";
    if (targetIsFolder && fromIsNavItem) {
      // Top 25% → line above folder, bottom 25% → line below, middle → insert into folder
      action = relY < 0.25 ? "before" : relY > 0.75 ? "after" : "into";
    } else {
      action = relY < 0.5 ? "before" : "after";
    }

    setDropIndicator({ id: targetId, action });
  }

  function handleDrop(targetId: string) {
    const fromId = dragIdRef.current;
    if (!fromId || fromId === targetId) { setDropIndicator(null); return; }

    const action = dropIndicator?.action ?? "after";

    if (action === "into") {
      moveToFolder(fromId, targetId);
      dragIdRef.current = null;
      setDropIndicator(null);
      return;
    }

    const toIdx = orderedIds.indexOf(targetId);
    if (toIdx === -1) { setDropIndicator(null); return; }

    // Check if the dragged item is coming from a folder (not in root orderedIds)
    const sourceFolder = folders.find((f) => f.hrefs.includes(fromId));

    if (sourceFolder) {
      // Folder item → root: remove from folder, insert at root position
      const newOrder = [...orderedIds];
      const insertAt = action === "after" ? toIdx + 1 : toIdx;
      newOrder.splice(insertAt, 0, fromId);
      const updatedFolders = folders.map((f) =>
        f.id === sourceFolder.id ? { ...f, hrefs: f.hrefs.filter((h) => h !== fromId) } : f,
      );
      setSidebarConfig({ ...sidebarConfig, order: newOrder, folders: updatedFolders });
    } else {
      // Root → root reorder
      const newOrder = [...orderedIds];
      const fromIdx = newOrder.indexOf(fromId);
      if (fromIdx === -1) { setDropIndicator(null); return; }
      newOrder.splice(fromIdx, 1);
      const adjustedToIdx = fromIdx < toIdx ? toIdx - 1 : toIdx;
      const insertAt = action === "after" ? adjustedToIdx + 1 : adjustedToIdx;
      newOrder.splice(insertAt, 0, fromId);
      setSidebarConfig({ ...sidebarConfig, order: newOrder });
    }

    dragIdRef.current = null;
    setDropIndicator(null);
  }

  function handleDragEnd() {
    dragIdRef.current = null;
    setDropIndicator(null);
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
                  onClick={() => { onSelectCollection?.(); setNavPickerOpen(false); }}
                  className="flex items-center gap-2.5 w-full px-3 py-2 text-sm text-left hover:bg-muted transition-colors"
                >
                  <FolderKanban className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                  Collection
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
          const entryId          = entry.kind === "nav" ? entry.item.href : entry.folder.id;
          const indicator        = dropIndicator?.id === entryId ? dropIndicator.action : null;
          const showLineBefore   = indicator === "before";
          const showLineAfter    = indicator === "after";
          const isFolderDropInto = indicator === "into" && entry.kind === "folder";

          // ── nav item row ──────────────────────────────────────────────────
          if (entry.kind === "nav") {
            const { item } = entry;
            const isHidden   = hidden.includes(item.href);
            const isDynamic  = !!(item.isProject || item.isDocument || item.isCollection); // user-added; has remove btn
            return (
              <Fragment key={entryId}>
                {showLineBefore && <div className="h-0.5 bg-primary rounded-full mx-1" />}
              <div
                draggable
                onDragStart={() => handleDragStart(entryId)}
                onDragOver={(e) => handleDragOver(e, entryId)}
                onDrop={() => handleDrop(entryId)}
                onDragEnd={handleDragEnd}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md border bg-background transition-all select-none",
                  isHidden && "opacity-40",
                )}
              >
                <GripVertical className="h-4 w-4 shrink-0 text-muted-foreground/50 cursor-grab active:cursor-grabbing" />
                <ItemIcon icon={item.icon} className="text-muted-foreground" />
                <span className="flex-1 text-sm font-medium">{item.label}</span>
                {/* Move to folder select — shown when there are folders */}
                {folders.length > 0 && (
                  <select
                    value=""
                    onChange={(e) => { if (e.target.value) moveToFolder(item.href, e.target.value); }}
                    onClick={(e) => e.stopPropagation()}
                    className="text-[11px] text-muted-foreground bg-transparent border-0 outline-none cursor-pointer hover:text-foreground py-0 pr-4 pl-0 appearance-none"
                    title="Move to folder"
                  >
                    <option value="">📂 Move…</option>
                    {folders.map((f) => (
                      <option key={f.id} value={f.id}>{f.label}</option>
                    ))}
                  </select>
                )}
                {/* Dynamic items (projects, docs, collections): show remove button */}
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
                {showLineAfter && <div className="h-0.5 bg-primary rounded-full mx-1" />}
              </Fragment>
            );
          }

          // ── folder row ────────────────────────────────────────────────────
          const { folder } = entry;
          const isEditing  = editingFolderId === folder.id;
          const isExpanded = expandedFolderId === folder.id;
          const folderItems = folder.hrefs
            .map((href) => allNavItems.find((n) => n.href === href))
            .filter((n): n is NavItem => !!n);

          return (
            <Fragment key={entryId}>
              {showLineBefore && <div className="h-0.5 bg-primary rounded-full mx-1" />}
            <div>
              <div
                draggable={!isEditing}
                onDragStart={() => handleDragStart(entryId)}
                onDragOver={(e) => handleDragOver(e, entryId)}
                onDrop={() => handleDrop(entryId)}
                onDragEnd={handleDragEnd}
                className={cn(
                  "flex items-center gap-3 px-3 py-2.5 rounded-md border bg-background transition-all select-none",
                  // Folder drop zone: emerald highlight when dragging an item into the folder
                  isFolderDropInto && "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/30",
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
                <div className="border border-t-0 rounded-b-md bg-muted/20 px-3 py-2 space-y-0">
                  {folderItems.map((item) => {
                    const isHidden    = hidden.includes(item.href);
                    const isDynamic   = !!(item.isProject || item.isDocument || item.isCollection);
                    const indBefore   = folderDropIndicator?.href === item.href && folderDropIndicator.position === "before";
                    const indAfter    = folderDropIndicator?.href === item.href && folderDropIndicator.position === "after";
                    return (
                      <Fragment key={item.href}>
                        {indBefore && <div className="h-0.5 bg-primary rounded-full mx-1 my-0.5" />}
                        <div
                          draggable
                          onDragStart={() => {
                            folderDragRef.current = item.href;
                            dragIdRef.current = item.href; // allow root-level drop handlers to see this drag
                          }}
                          onDragOver={(e) => {
                            e.preventDefault();
                            const activeDrag = folderDragRef.current ?? dragIdRef.current;
                            if (activeDrag === item.href) return;
                            const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
                            const position = (e.clientY - rect.top) / rect.height < 0.5 ? "before" : "after";
                            setFolderDropIndicator({ href: item.href, position });
                          }}
                          onDrop={() => {
                            const fromInFolder = folderDragRef.current;
                            const fromRoot     = dragIdRef.current;
                            const pos          = folderDropIndicator?.position ?? "after";
                            if (fromInFolder && fromInFolder !== item.href) {
                              // Within-folder reorder
                              reorderInFolder(folder.id, fromInFolder, item.href, pos);
                            } else if (fromRoot && fromRoot !== item.href && !folderDragRef.current) {
                              // Root item dropped into this folder at a specific position
                              moveToFolderAtPosition(fromRoot, folder.id, item.href, pos);
                            }
                            folderDragRef.current = null;
                            dragIdRef.current = null;
                            setFolderDropIndicator(null);
                            setDropIndicator(null);
                          }}
                          onDragEnd={() => {
                            folderDragRef.current = null;
                            dragIdRef.current = null;
                            setFolderDropIndicator(null);
                            setDropIndicator(null);
                          }}
                          className={cn(
                            "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm select-none",
                            "cursor-grab active:cursor-grabbing",
                            isHidden && "opacity-40",
                          )}
                        >
                          <GripVertical className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0" />
                          <ItemIcon icon={item.icon} className="text-muted-foreground" />
                          <span className="flex-1 text-muted-foreground">{item.label}</span>
                          {/* Consistent folder-action select: move to another folder or remove from this one */}
                          <select
                            value=""
                            onChange={(e) => {
                              const val = e.target.value;
                              if (val === "__remove__") removeFromFolder(folder.id, item.href);
                              else if (val) moveToFolder(item.href, val);
                            }}
                            onClick={(e) => e.stopPropagation()}
                            className="text-[11px] text-muted-foreground bg-transparent border-0 outline-none cursor-pointer hover:text-foreground py-0 pr-4 pl-0 appearance-none"
                            title="Move or remove from folder"
                          >
                            <option value="">📂 Move…</option>
                            <option value="__remove__">↑ Remove from folder</option>
                            {folders.filter((f) => f.id !== folder.id).map((f) => (
                              <option key={f.id} value={f.id}>{f.label}</option>
                            ))}
                          </select>
                          {/* Visibility / remove-from-nav control */}
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
                        </div>
                        {indAfter && <div className="h-0.5 bg-primary rounded-full mx-1 my-0.5" />}
                      </Fragment>
                    );
                  })}

                  {folderItems.length === 0 && (
                    <p className="text-xs text-muted-foreground px-2 py-1">
                      Drag items here from the list above.
                    </p>
                  )}
                </div>
              )}
            </div>
              {showLineAfter && <div className="h-0.5 bg-primary rounded-full mx-1" />}
            </Fragment>
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
              <p className="text-sm font-semibold">Hearth</p>
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

// ── Select-collection-for-nav dialog ────────────────────────────────────────

function SelectCollectionDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
  const [search, setSearch] = useState("");

  const { data: collectionsData, isLoading } = $api.useQuery("get", "/collections");
  const { mutateAsync: updateCollection } = $api.useMutation("patch", "/collections/{collection_id}");

  const allCollections = collectionsData?.items ?? [];

  const filtered = allCollections.filter((c) =>
    !search.trim() || c.name.toLowerCase().includes(search.trim().toLowerCase()),
  );

  async function selectCollection(col: typeof allCollections[0]) {
    if (col.show_in_nav) { onClose(); return; }

    await updateCollection({
      params: { path: { collection_id: col.id } },
      body: { show_in_nav: true },
    });
    qc.invalidateQueries({ queryKey: ["get", "/collections"] });

    const href = `/collections/${col.id}`;
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
          <h2 className="text-base font-semibold flex-1">Add collection to nav</h2>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4 space-y-3">
          <input
            autoFocus
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search collections…"
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
                {search ? "No collections match." : "No collections yet."}
              </p>
            )}
            {filtered.map((col) => {
              const isAlreadyInNav = col.show_in_nav;
              const ColIcon = col.icon ? resolveFolderIcon(col.icon) : null;
              return (
                <button
                  key={col.id}
                  type="button"
                  disabled={isAlreadyInNav}
                  onClick={() => selectCollection(col)}
                  className={cn(
                    "flex items-center gap-3 w-full px-3 py-2.5 rounded-md text-left text-sm transition-colors",
                    isAlreadyInNav
                      ? "opacity-40 cursor-default"
                      : "hover:bg-muted cursor-pointer",
                  )}
                >
                  <span className="text-base w-5 text-center shrink-0 flex items-center justify-center">
                    {ColIcon ? <ColIcon className="h-4 w-4" /> : (col.icon ?? "📁")}
                  </span>
                  <span className="flex-1 truncate font-medium">{col.name}</span>
                  {isAlreadyInNav && (
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
  const [navCreateType, setNavCreateType] = useState<"project" | "document" | "collection" | null>(null);

  return (
    <div className="space-y-5">
      <SectionTitle>Navigation</SectionTitle>
      <SubSection title="Sidebar layout">
        <SidebarCustomizer
          onCreateProject={() => setNavCreateType("project")}
          onCreatePage={() => setNavCreateType("document")}
          onSelectCollection={() => setNavCreateType("collection")}
        />
      </SubSection>

      {navCreateType === "project" && (
        <SelectProjectDialog onClose={() => setNavCreateType(null)} />
      )}

      {navCreateType === "document" && (
        <PinDocumentDialog onClose={() => setNavCreateType(null)} />
      )}

      {navCreateType === "collection" && (
        <SelectCollectionDialog onClose={() => setNavCreateType(null)} />
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
  default_template_id: string | null;
};

const DEFAULT_COLLECTION_FORM: CollectionFormState = {
  name: "",
  icon: "BookOpen",
  domain: "notes",
  hasAutoCreate: false,
  titleTemplate: "{{day_of_week}}, {{month}} {{day}}, {{year}}",
  default_template_id: null,
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
  const [iconPickerOpen, setIconPickerOpen] = useState(false);

  const { data: templatesData } = $api.useQuery("get", "/templates");
  const templates = (templatesData?.items ?? []).filter((t) => t.domain === form.domain);

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
            <label className="text-xs font-medium text-muted-foreground">Icon</label>
            <div className={cn("border rounded-lg", iconPickerOpen ? "rounded-b-none" : "")}>
              <button
                type="button"
                title="Choose icon"
                onClick={() => setIconPickerOpen((o) => !o)}
                className={cn(
                  "w-full h-9 flex items-center gap-2 px-3 rounded-lg text-sm transition-colors",
                  iconPickerOpen
                    ? "border-primary bg-primary/10 text-primary rounded-b-none"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground",
                )}
              >
                {(() => {
                  const IconComp = resolveFolderIcon(form.icon || "BookOpen") ?? resolveFolderIcon("BookOpen")!;
                  return <IconComp className="h-4 w-4 shrink-0" />;
                })()}
                <span className="text-xs">{form.icon || "BookOpen"}</span>
              </button>
              {iconPickerOpen && (
                <InlineIconPicker
                  currentIcon={form.icon || "BookOpen"}
                  onSelect={(name) => { setForm((f) => ({ ...f, icon: name })); setIconPickerOpen(false); }}
                  onClose={() => setIconPickerOpen(false)}
                />
              )}
            </div>
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

          {/* Default template */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-muted-foreground">
              Default template <span className="font-normal opacity-60">(optional)</span>
            </label>
            <select
              value={form.default_template_id ?? ""}
              onChange={(e) => setForm((f) => ({ ...f, default_template_id: e.target.value || null }))}
              className="w-full h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
            >
              <option value="">No template</option>
              {templates.map((t) => (
                <option key={t.id} value={t.id}>{t.name}</option>
              ))}
            </select>
            {templates.length === 0 && (
              <p className="text-[11px] text-muted-foreground">
                No {form.domain} templates yet — create one in Settings → Templates.
              </p>
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
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();
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

  /** Assign a default template to a collection via raw fetch (the typed client
   *  doesn't expose the POST /collections/{id}/templates body correctly). */
  async function applyTemplate(collectionId: string, templateId: string) {
    const token = getAccessToken();
    await fetch(`${apiBaseUrl}/collections/${collectionId}/templates`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ template_id: templateId, is_default: true }),
    });
  }

  async function handleCreate(form: CollectionFormState) {
    const newCol = await createCollection.mutateAsync({
      body: {
        name: form.name,
        icon: form.icon || null,
        domain: form.domain,
        auto_create_rule: form.hasAutoCreate
          ? { frequency: "daily", title_template: form.titleTemplate }
          : null,
        default_tags: [],
        show_in_nav: true,
        sort_order: collections.length,
      },
    });
    // Auto-add to sidebar order so it appears in nav immediately
    const href = `/collections/${newCol.id}`;
    setSidebarConfig({
      ...sidebarConfig,
      order: sidebarConfig.order.includes(href)
        ? sidebarConfig.order
        : [...sidebarConfig.order, href],
    });
    if (form.default_template_id) {
      await applyTemplate(newCol.id, form.default_template_id);
    }
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
    if (form.default_template_id) {
      await applyTemplate(id, form.default_template_id);
    }
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
              const ColIconComp = col.icon ? resolveFolderIcon(col.icon) : null;
              return (
                <div
                  key={col.id}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-lg border bg-card"
                >
                  <span className="text-xl leading-none w-7 text-center shrink-0 flex items-center justify-center">
                    {ColIconComp
                      ? <ColIconComp className="h-5 w-5" />
                      : (col.icon ?? (col.domain === "notes" ? "📓" : "📄"))}
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
                          default_template_id: null,
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
        sort_order: 0,
        visibility: "household",
        shared_with_user_ids: [],
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

// ── Common IANA timezone list ─────────────────────────────────────────────────
// We keep a concise subset covering all major regions; the user can type to filter.
const COMMON_TIMEZONES = [
  "Africa/Cairo", "Africa/Johannesburg", "Africa/Lagos", "Africa/Nairobi",
  "America/Anchorage", "America/Argentina/Buenos_Aires", "America/Bogota",
  "America/Chicago", "America/Denver", "America/Halifax", "America/Los_Angeles",
  "America/Mexico_City", "America/New_York", "America/Phoenix", "America/Sao_Paulo",
  "America/Toronto", "America/Vancouver",
  "Asia/Dhaka", "Asia/Dubai", "Asia/Ho_Chi_Minh", "Asia/Hong_Kong",
  "Asia/Jakarta", "Asia/Karachi", "Asia/Kolkata", "Asia/Seoul",
  "Asia/Shanghai", "Asia/Singapore", "Asia/Taipei", "Asia/Tehran",
  "Asia/Tokyo", "Asia/Yangon",
  "Atlantic/Reykjavik",
  "Australia/Melbourne", "Australia/Perth", "Australia/Sydney",
  "Europe/Amsterdam", "Europe/Athens", "Europe/Berlin", "Europe/Brussels",
  "Europe/Bucharest", "Europe/Dublin", "Europe/Helsinki", "Europe/Istanbul",
  "Europe/Kiev", "Europe/Lisbon", "Europe/London", "Europe/Madrid",
  "Europe/Moscow", "Europe/Oslo", "Europe/Paris", "Europe/Prague",
  "Europe/Rome", "Europe/Stockholm", "Europe/Vienna", "Europe/Warsaw",
  "Europe/Zurich",
  "Pacific/Auckland", "Pacific/Fiji", "Pacific/Honolulu",
  "UTC",
];

const DATE_FORMAT_OPTIONS = [
  { value: "MM/DD/YY",    label: "MM/DD/YY  (e.g. 05/14/26)" },
  { value: "DD/MM/YYYY",  label: "DD/MM/YYYY  (e.g. 14/05/2026)" },
  { value: "YYYY-MM-DD",  label: "YYYY-MM-DD  (e.g. 2026-05-14)" },
] as const;

const WEEK_START_OPTIONS = [
  { value: "sunday",  label: "Sunday" },
  { value: "monday",  label: "Monday" },
] as const;

// ── Change password modal ─────────────────────────────────────────────────────

function ChangePasswordModal({ onClose }: { onClose: () => void }) {
  const [current,  setCurrent]  = useState("");
  const [next,     setNext]     = useState("");
  const [confirm,  setConfirm]  = useState("");
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNext,    setShowNext]    = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [saving,   setSaving]   = useState(false);
  const [error,    setError]    = useState<string | null>(null);
  const [done,     setDone]     = useState(false);

  // Client-side validation
  const mismatch = next.length > 0 && confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < 8;
  const canSubmit = current.length > 0 && next.length >= 8 && next === confirm && !saving;

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    setSaving(true);
    setError(null);
    try {
      const token = getAccessToken();
      const res = await fetch(`${apiBaseUrl}/auth/me/password`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ current_password: current, new_password: next }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Failed to change password");
      }
      setDone(true);
      setTimeout(onClose, 1200);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change password");
    } finally {
      setSaving(false);
    }
  }

  function PasswordField({
    id, label, value, onChange, show, onToggle, autoFocus,
  }: {
    id: string; label: string; value: string;
    onChange: (v: string) => void;
    show: boolean; onToggle: () => void;
    autoFocus?: boolean;
  }) {
    return (
      <div className="space-y-1.5">
        <label htmlFor={id} className="text-xs font-medium text-muted-foreground">{label}</label>
        <div className="relative">
          <input
            id={id}
            type={show ? "text" : "password"}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            autoFocus={autoFocus}
            autoComplete={id === "cp-current" ? "current-password" : "new-password"}
            className="w-full h-9 pl-3 pr-9 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <button
            type="button"
            onClick={onToggle}
            className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            tabIndex={-1}
            aria-label={show ? "Hide password" : "Show password"}
          >
            {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-background border rounded-lg shadow-xl w-full max-w-sm mx-4">
        <div className="flex items-center gap-3 px-5 pt-5 pb-4 border-b">
          <Lock className="h-4 w-4 text-muted-foreground shrink-0" />
          <h2 className="text-base font-semibold flex-1">Change password</h2>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground cursor-pointer">
            <X className="h-4 w-4" />
          </button>
        </div>

        {done ? (
          <div className="px-5 py-8 flex flex-col items-center gap-2 text-center">
            <Check className="h-8 w-8 text-primary" />
            <p className="text-sm font-medium">Password updated</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="p-5 space-y-4">
            <PasswordField
              id="cp-current"
              label="Current password"
              value={current}
              onChange={(v) => { setCurrent(v); setError(null); }}
              show={showCurrent}
              onToggle={() => setShowCurrent((s) => !s)}
              autoFocus
            />

            <div className="border-t pt-4 space-y-4">
              <PasswordField
                id="cp-new"
                label="New password"
                value={next}
                onChange={(v) => { setNext(v); setError(null); }}
                show={showNext}
                onToggle={() => setShowNext((s) => !s)}
              />
              {tooShort && (
                <p className="text-xs text-destructive -mt-2">Must be at least 8 characters.</p>
              )}

              <PasswordField
                id="cp-confirm"
                label="Confirm new password"
                value={confirm}
                onChange={(v) => { setConfirm(v); setError(null); }}
                show={showConfirm}
                onToggle={() => setShowConfirm((s) => !s)}
              />
              {mismatch && (
                <p className="text-xs text-destructive -mt-2">Passwords don't match.</p>
              )}
            </div>

            {error && (
              <p className="text-xs text-destructive flex items-center gap-1.5">
                <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                {error}
              </p>
            )}

            <div className="flex gap-2 pt-1">
              <button
                type="submit"
                disabled={!canSubmit}
                className="flex-1 h-9 text-sm font-medium rounded-md bg-primary text-primary-foreground disabled:opacity-40 cursor-pointer disabled:cursor-default flex items-center justify-center gap-1.5 transition-opacity"
              >
                {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                Update password
              </button>
              <button
                type="button"
                onClick={onClose}
                className="h-9 px-4 text-sm text-muted-foreground hover:text-foreground cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}

function AccountSection() {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [changingPassword, setChangingPassword] = useState(false);

  // ── Locale state ─────────────────────────────────────────────────────────────
  const [timezone,   setTimezone]   = useState(user?.timezone   ?? "");
  const [dateFormat, setDateFormat] = useState(user?.date_format ?? "MM/DD/YY");
  const [weekStart,  setWeekStart]  = useState(user?.week_start  ?? "sunday");
  const [tzSearch,   setTzSearch]   = useState("");
  const [tzOpen,     setTzOpen]     = useState(false);
  const [localeSaving,  setLocaleSaving]  = useState(false);
  const [localeSaved,   setLocaleSaved]   = useState(false);
  const [localeError,   setLocaleError]   = useState<string | null>(null);

  const filteredTz = tzSearch.trim()
    ? COMMON_TIMEZONES.filter((tz) =>
        tz.toLowerCase().includes(tzSearch.trim().toLowerCase())
      )
    : COMMON_TIMEZONES;

  async function saveLocale() {
    setLocaleSaving(true);
    setLocaleError(null);
    try {
      const token = getAccessToken();
      const res = await fetch(`${apiBaseUrl}/auth/me`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ timezone, date_format: dateFormat, week_start: weekStart }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Failed to save");
      }
      // Invalidate /auth/me so the auth context picks up the fresh user object
      await qc.invalidateQueries({ queryKey: ["get", "/auth/me"] });
      setLocaleSaved(true);
      setTimeout(() => setLocaleSaved(false), 2000);
    } catch (e) {
      setLocaleError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setLocaleSaving(false);
    }
  }

  const localeChanged =
    timezone   !== (user?.timezone   ?? "") ||
    dateFormat !== (user?.date_format ?? "MM/DD/YY") ||
    weekStart  !== (user?.week_start  ?? "sunday");

  return (
    <div className="space-y-5">
      <SectionTitle>Account</SectionTitle>

      {/* ── Profile ─────────────────────────────────────────────────────────── */}
      <SubSection title="Profile">
        <div className="flex items-center gap-5 mb-5">
          <div className="h-16 w-16 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xl font-semibold shrink-0">
            {(user?.display_name ?? user?.email ?? "?")[0].toUpperCase()}
          </div>
          <div>
            <p className="text-sm font-medium mb-1">Profile photo</p>
            <p className="text-xs text-muted-foreground">
              Avatar upload coming soon. Your initials are shown in the sidebar for now.
            </p>
          </div>
        </div>
        <div className="flex items-center justify-between pt-1">
          <div>
            <p className="text-sm font-medium">Password</p>
            <p className="text-xs text-muted-foreground">Change your account password.</p>
          </div>
          <button
            type="button"
            onClick={() => setChangingPassword(true)}
            className="h-8 px-3 text-sm font-medium rounded-md border hover:bg-muted transition-colors cursor-pointer shrink-0"
          >
            Change password
          </button>
        </div>
      </SubSection>

      {changingPassword && (
        <ChangePasswordModal onClose={() => setChangingPassword(false)} />
      )}

      {/* ── Locale ──────────────────────────────────────────────────────────── */}
      <SubSection title="Locale & date preferences">
        <div className="space-y-4">

          {/* Timezone */}
          <div>
            <Label>Timezone</Label>
            <div className="relative">
              <button
                type="button"
                onClick={() => setTzOpen((v) => !v)}
                className="w-full h-9 px-3 rounded-md border bg-background text-sm text-left flex items-center justify-between hover:bg-muted/40 transition-colors focus:outline-none focus:ring-2 focus:ring-primary/50"
              >
                <span className={timezone ? "text-foreground" : "text-muted-foreground"}>
                  {timezone || "Select timezone…"}
                </span>
                <ChevronDown className={cn("h-4 w-4 text-muted-foreground transition-transform", tzOpen && "rotate-180")} />
              </button>
              {tzOpen && (
                <div className="absolute z-50 mt-1 w-full rounded-md border bg-popover shadow-md">
                  <div className="p-2 border-b">
                    <input
                      type="text"
                      value={tzSearch}
                      onChange={(e) => setTzSearch(e.target.value)}
                      placeholder="Search timezones…"
                      autoFocus
                      className="w-full h-7 px-2 text-xs rounded border bg-background focus:outline-none focus:ring-1 focus:ring-primary/50"
                    />
                  </div>
                  <div className="max-h-52 overflow-y-auto">
                    {filteredTz.length === 0 ? (
                      <p className="px-3 py-4 text-xs text-muted-foreground text-center">No matching timezone</p>
                    ) : (
                      filteredTz.map((tz) => (
                        <button
                          key={tz}
                          type="button"
                          onClick={() => { setTimezone(tz); setTzOpen(false); setTzSearch(""); }}
                          className={cn(
                            "w-full text-left px-3 py-1.5 text-sm hover:bg-muted/60 transition-colors",
                            tz === timezone && "bg-primary/10 text-primary font-medium",
                          )}
                        >
                          {tz}
                        </button>
                      ))
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Date format */}
          <div>
            <Label>Date format</Label>
            <div className="flex gap-2 flex-wrap">
              {DATE_FORMAT_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setDateFormat(value)}
                  className={cn(
                    "px-3 py-1.5 rounded-md border text-sm transition-colors",
                    dateFormat === value
                      ? "bg-primary/10 border-primary/40 text-primary font-medium"
                      : "bg-background hover:bg-muted/50 text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Week start */}
          <div>
            <Label>Week starts on</Label>
            <div className="flex gap-2">
              {WEEK_START_OPTIONS.map(({ value, label }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setWeekStart(value)}
                  className={cn(
                    "px-3 py-1.5 rounded-md border text-sm transition-colors",
                    weekStart === value
                      ? "bg-primary/10 border-primary/40 text-primary font-medium"
                      : "bg-background hover:bg-muted/50 text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Save row */}
          {localeError && (
            <p className="text-xs text-destructive flex items-center gap-1.5">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
              {localeError}
            </p>
          )}
          <button
            type="button"
            onClick={saveLocale}
            disabled={localeSaving || !localeChanged}
            className="h-9 px-4 text-sm font-medium rounded-md bg-primary text-primary-foreground disabled:opacity-40 cursor-pointer disabled:cursor-default transition-opacity flex items-center gap-1.5"
          >
            {localeSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : localeSaved ? (
              <Check className="h-3.5 w-3.5" />
            ) : null}
            {localeSaved ? "Saved" : "Save preferences"}
          </button>
        </div>
      </SubSection>

      {/* Sign out */}
      <SignOutSection />
    </div>
  );
}

function SignOutSection() {
  const { logout } = useAuth();
  const [confirming, setConfirming] = useState(false);

  async function handleLogout() {
    await logout();
  }

  return (
    <SubSection title="Session">
      <div className="px-4 pb-4">
        {!confirming ? (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            className="inline-flex items-center gap-2 rounded-md border border-border px-3 py-1.5 text-sm text-muted-foreground hover:border-destructive hover:text-destructive transition-colors cursor-pointer"
          >
            <LogOut className="h-3.5 w-3.5" />
            Sign out
          </button>
        ) : (
          <div className="flex items-center gap-3">
            <span className="text-sm text-muted-foreground">Sign out of this account?</span>
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-1.5 rounded-md bg-destructive px-3 py-1.5 text-sm font-medium text-destructive-foreground hover:opacity-90 transition-opacity cursor-pointer"
            >
              <LogOut className="h-3.5 w-3.5" />
              Sign out
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </SubSection>
  );
}

// ── Role display helpers ──────────────────────────────────────────────────────
// ROLE_LABEL imported from @/lib/roles — see that file for the full mapping.

const ROLE_OPTIONS = [
  { value: "admin",  label: "Admin"   },
  { value: "member", label: "Parent"  },
  { value: "viewer", label: "Child"   },
] as const;

const ROLE_BADGE: Record<string, string> = {
  owner:  "badge-primary",
  admin:  "badge-warning",
  member: "badge-neutral",
  viewer: "badge-neutral badge-faded",
  agent:  "badge-neutral badge-faded",
};

// ── ai-access-001: per-member AI features toggle ──────────────────────────────

function MemberRow({
  m,
  isCurrentUser,
  viewerIsAdmin,
}: {
  m: {
    user_id: string;
    display_name: string | null;
    email: string;
    role: string;
    ai_features_enabled?: boolean;
  };
  isCurrentUser: boolean;
  viewerIsAdmin: boolean;
}) {
  const qc = useQueryClient();
  // Treat undefined (older API response) as enabled, matching the
  // server-side default and the migration backfill.
  const [enabled, setEnabled] = useState<boolean>(m.ai_features_enabled ?? true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Admins see a real toggle for OTHER members. For their own row, the
  // toggle is shown but disabled — admins can't lock themselves out via
  // this control. Non-admins see a read-only status pill so they know
  // the state without being able to change it.
  const canToggle = viewerIsAdmin && !isCurrentUser;

  async function toggleAi(next: boolean) {
    if (!canToggle || saving) return;
    setSaving(true);
    setError(null);
    const previous = enabled;
    setEnabled(next); // optimistic
    try {
      const token = getAccessToken();
      const res = await fetch(`${apiBaseUrl}/households/members/${m.user_id}`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ ai_features_enabled: next }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Failed to update");
      }
      await qc.invalidateQueries({ queryKey: ["get", "/households/members"] });
    } catch (e) {
      setEnabled(previous); // rollback optimistic
      setError(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setSaving(false);
    }
  }

  const initials = (m.display_name ?? m.email)
    .trim()
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");

  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-md border bg-background">
      {/* Avatar */}
      <div className="h-7 w-7 rounded-full bg-primary/10 text-primary text-xs font-semibold flex items-center justify-center shrink-0">
        {initials}
      </div>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{m.display_name ?? m.email}</p>
        {m.display_name && (
          <p className="text-xs text-muted-foreground truncate">{m.email}</p>
        )}
        {error && (
          <p className="text-[11px] text-destructive mt-0.5 flex items-center gap-1">
            <AlertCircle className="h-3 w-3 shrink-0" />
            {error}
          </p>
        )}
      </div>
      <span className={cn("badge", ROLE_BADGE[m.role] ?? "badge-neutral")}>
        {ROLE_LABEL[m.role] ?? m.role}
      </span>

      {/* AI features toggle / status */}
      {viewerIsAdmin ? (
        <label
          className={cn(
            "flex items-center gap-1.5 text-xs whitespace-nowrap",
            canToggle ? "cursor-pointer text-muted-foreground" : "cursor-default text-muted-foreground/60",
          )}
          title={
            isCurrentUser
              ? "You can't change your own AI access from here. Clear your API key in Settings → AI to disable for yourself."
              : enabled
              ? "AI features ON for this member. Click to disable."
              : "AI features OFF for this member. Click to enable."
          }
        >
          <span>AI</span>
          <input
            type="checkbox"
            className="checkbox-themed h-4 w-4"
            checked={enabled}
            disabled={!canToggle || saving}
            onChange={(e) => toggleAi(e.target.checked)}
          />
        </label>
      ) : (
        <span
          className={cn(
            "text-[11px] uppercase tracking-wide font-medium",
            enabled ? "text-muted-foreground" : "text-muted-foreground/60",
          )}
          title={enabled ? "AI features are enabled for this member" : "AI features are disabled for this member"}
        >
          AI: {enabled ? "on" : "off"}
        </span>
      )}
    </div>
  );
}


function HouseholdSection() {
  const qc = useQueryClient();

  // ── Household name ───────────────────────────────────────────────────────────
  const { user } = useAuth();
  const appConfig = useAppConfig();
  const [householdName, setHouseholdName] = useState(user?.household_name ?? "");
  const [nameSaving, setNameSaving]       = useState(false);
  const [nameError, setNameError]         = useState<string | null>(null);
  const [nameSaved, setNameSaved]         = useState(false);

  async function saveHouseholdName() {
    const trimmed = householdName.trim();
    if (!trimmed || trimmed === user?.household_name) return;
    setNameSaving(true);
    setNameError(null);
    try {
      const token = getAccessToken();
      const res = await fetch(`${apiBaseUrl}/households/name`, {
        method: "PATCH",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ name: trimmed }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Failed to save");
      }
      // Refresh member list (household name is on the user object too)
      await qc.invalidateQueries({ queryKey: ["get", "/households/members"] });
      setNameSaved(true);
      setTimeout(() => setNameSaved(false), 2000);
    } catch (e) {
      setNameError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setNameSaving(false);
    }
  }

  // ── Members list ─────────────────────────────────────────────────────────────
  const { data: members, isLoading: membersLoading } = $api.useQuery(
    "get",
    "/households/members",
  );

  // ── Add member form ──────────────────────────────────────────────────────────
  const [addingMember, setAddingMember]   = useState(false);
  const [newEmail, setNewEmail]           = useState("");
  const [newRole, setNewRole]             = useState("member");
  const [addSaving, setAddSaving]         = useState(false);
  const [addError, setAddError]           = useState<string | null>(null);
  // self_hosted only: temp password returned by the API, shown once to the admin
  const [tempPassword, setTempPassword]   = useState<string | null>(null);

  async function submitAddMember(e: React.FormEvent) {
    e.preventDefault();
    const email = newEmail.trim();
    if (!email) return;
    setAddSaving(true);
    setAddError(null);
    setTempPassword(null);
    try {
      const token = getAccessToken();
      const res = await fetch(`${apiBaseUrl}/households/members`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ email, role: newRole }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error((body as { detail?: string }).detail ?? "Failed to add member");
      }
      const data = await res.json() as { temp_password?: string | null };
      await qc.invalidateQueries({ queryKey: ["get", "/households/members"] });
      setNewEmail("");
      setNewRole("member");
      setAddingMember(false);
      // self_hosted tier only — show the temp password once so the admin can share it
      if (data.temp_password) {
        setTempPassword(data.temp_password);
      }
    } catch (e) {
      setAddError(e instanceof Error ? e.message : "Failed to add member");
    } finally {
      setAddSaving(false);
    }
  }

  return (
    <div className="space-y-5">
      <SectionTitle>Household</SectionTitle>

      {/* ── Name ── */}
      <SubSection title="Household name">
        <div className="flex items-center gap-3">
          <input
            type="text"
            value={householdName}
            onChange={(e) => { setHouseholdName(e.target.value); setNameError(null); }}
            onKeyDown={(e) => { if (e.key === "Enter") saveHouseholdName(); }}
            placeholder="e.g. The Smith Household"
            className="flex-1 h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
          />
          <button
            type="button"
            disabled={nameSaving || !householdName.trim() || householdName.trim() === user?.household_name}
            onClick={saveHouseholdName}
            className="h-9 px-4 text-sm font-medium rounded-md bg-primary text-primary-foreground disabled:opacity-40 cursor-pointer disabled:cursor-default transition-opacity flex items-center gap-1.5"
          >
            {nameSaving ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : nameSaved ? (
              <Check className="h-3.5 w-3.5" />
            ) : null}
            {nameSaved ? "Saved" : "Save"}
          </button>
        </div>
        {nameError && (
          <p className="text-xs text-destructive mt-2 flex items-center gap-1.5">
            <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            {nameError}
          </p>
        )}
      </SubSection>

      {/* ── Members ── */}
      <SubSection title="Members">
        {membersLoading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground py-2">
            <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
          </div>
        ) : (
          <div className="space-y-2">
            {(members ?? []).map((m) => (
              <MemberRow
                key={m.user_id}
                m={m}
                isCurrentUser={m.user_id === user?.id}
                viewerIsAdmin={ADMIN_ROLES.has(user?.role ?? "")}
              />
            ))}

            {/* Temp password callout — shown once after a self_hosted invite */}
            {tempPassword && (
              <div className="border rounded-md p-3 bg-muted/40 space-y-2">
                <p className="text-xs font-semibold text-foreground flex items-center gap-1.5">
                  <Check className="h-3.5 w-3.5 text-green-600" />
                  Member added — share this temporary password
                </p>
                <p className="text-xs text-muted-foreground">
                  Share this with the new member. They&apos;ll be prompted to set their own
                  password after their first login.
                </p>
                <div className="flex items-center gap-2">
                  <code className="flex-1 font-mono text-sm bg-background border rounded px-3 py-1.5 select-all">
                    {tempPassword}
                  </code>
                  <button
                    type="button"
                    onClick={() => navigator.clipboard.writeText(tempPassword)}
                    className="h-8 px-3 text-xs rounded-md border bg-background hover:bg-muted transition-colors cursor-pointer"
                  >
                    Copy
                  </button>
                </div>
                <button
                  type="button"
                  onClick={() => setTempPassword(null)}
                  className="text-xs text-muted-foreground hover:text-foreground cursor-pointer"
                >
                  Dismiss
                </button>
              </div>
            )}

            {/* Add member button / form — hidden on local tier */}
            {appConfig.deployment_tier === "local" ? (
              <p className="text-xs text-muted-foreground px-1 py-2">
                Household invites are not available on local installs. To add members,
                deploy with Docker (self-hosted) or use cloud hosting.
              </p>
            ) : !addingMember ? (
              <button
                type="button"
                onClick={() => { setAddingMember(true); setTempPassword(null); }}
                className="flex items-center gap-2 w-full px-3 py-2 rounded-md border border-dashed text-sm text-muted-foreground hover:text-foreground hover:border-border transition-colors cursor-pointer"
              >
                <Plus className="h-4 w-4" />
                Add household member
              </button>
            ) : (
              <form
                onSubmit={submitAddMember}
                className="border rounded-md p-4 space-y-3 bg-muted/30"
              >
                <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                  New member
                </p>
                <div className="flex gap-2">
                  <input
                    autoFocus
                    type="email"
                    value={newEmail}
                    onChange={(e) => { setNewEmail(e.target.value); setAddError(null); }}
                    placeholder="Email address"
                    className="flex-1 h-9 px-3 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                    required
                  />
                  <select
                    value={newRole}
                    onChange={(e) => setNewRole(e.target.value)}
                    className="h-9 px-2 rounded-md border bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50 cursor-pointer"
                  >
                    {ROLE_OPTIONS.map((r) => (
                      <option key={r.value} value={r.value}>{r.label}</option>
                    ))}
                  </select>
                </div>
                <p className="text-xs text-muted-foreground">
                  {appConfig.deployment_tier === "cloud"
                    ? "An invite email will be sent. The new member will be prompted to set their own password after first login."
                    : "A temporary password will be generated and shown to you once. Share it with the new member — they'll set their own password on first login."}
                </p>
                {addError && (
                  <p className="text-xs text-destructive flex items-center gap-1.5">
                    <AlertCircle className="h-3.5 w-3.5 shrink-0" />
                    {addError}
                  </p>
                )}
                <div className="flex gap-2">
                  <button
                    type="submit"
                    disabled={addSaving || !newEmail.trim()}
                    className="h-8 px-4 text-sm font-medium rounded-md bg-primary text-primary-foreground disabled:opacity-40 cursor-pointer disabled:cursor-default flex items-center gap-1.5"
                  >
                    {addSaving && <Loader2 className="h-3 w-3 animate-spin" />}
                    {appConfig.deployment_tier === "cloud" ? "Send invite" : "Add member"}
                  </button>
                  <button
                    type="button"
                    onClick={() => { setAddingMember(false); setNewEmail(""); setNewRole("member"); setAddError(null); }}
                    className="h-8 px-3 text-sm text-muted-foreground hover:text-foreground cursor-pointer"
                  >
                    Cancel
                  </button>
                </div>
              </form>
            )}
          </div>
        )}
      </SubSection>
    </div>
  );
}

// ── AI section ───────────────────────────────────────────────────────────────

type AiSettings = {
  provider: "anthropic" | "openai" | "ollama";
  retention_days: number | null;
  has_custom_key: boolean;
  // Phase 2 of AI coach redesign — per-user opt-out for journal signal
  // extraction. Server defaults this to true; we treat undefined as true
  // for backward-compat with older API responses.
  ai_journal_extraction_enabled?: boolean;
};

type JournalSignalsBackfillResponse = {
  scanned: number;
  extracted: number;
  skipped_empty: number;
  skipped_current: number;
  errors: number;
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
  const res = await fetch(`${apiBaseUrl}/ai/settings`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error("Failed to load AI settings");
  return res.json() as Promise<AiSettings>;
}

async function patchAiSettings(patch: Record<string, unknown>): Promise<AiSettings> {
  const token = getAccessToken();
  const res = await fetch(`${apiBaseUrl}/ai/settings`, {
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

// ── AI profile (Phase 1 of AI coach redesign) ────────────────────────────────

type AiProfile = {
  content_md: string;
  last_updated_at: string;
  last_bootstrapped_at: string | null;
};

type AiProfileUpdate = {
  id: string;
  proposed_content_md: string;
  diff_summary: string | null;
  source: "bootstrap" | "incremental" | "manual";
  status: "pending" | "accepted" | "rejected" | "superseded";
  created_at: string;
  resolved_at: string | null;
};

type AiBootstrapResponse = {
  update: AiProfileUpdate | null;
  bootstrap_skipped: boolean;
  reason: string | null;
};

async function aiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const res = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(init?.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `Request failed (${res.status})`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

function ProfileSubSection() {
  const qc = useQueryClient();
  const { data: profile, isLoading: profileLoading, isError: profileError } =
    useQuery<AiProfile>({
      queryKey: ["ai", "profile"],
      queryFn: () => aiFetch<AiProfile>("/ai/profile"),
    });

  const { data: updatesData } = useQuery<{ items: AiProfileUpdate[] }>({
    queryKey: ["ai", "profile", "updates"],
    queryFn: () => aiFetch<{ items: AiProfileUpdate[] }>("/ai/profile/updates"),
  });
  const pendingUpdates = updatesData?.items ?? [];

  const [draft, setDraft] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [bootstrapping, setBootstrapping] = useState(false);
  const [bootstrapMsg, setBootstrapMsg] = useState<string | null>(null);
  const [resolvingId, setResolvingId] = useState<string | null>(null);

  const editing = draft !== null;
  const liveValue = draft ?? profile?.content_md ?? "";

  async function startEdit() {
    setDraft(profile?.content_md ?? "");
    setSaveError(null);
  }

  async function cancelEdit() {
    setDraft(null);
    setSaveError(null);
  }

  async function saveDraft() {
    if (draft === null) return;
    setSaving(true);
    setSaveError(null);
    try {
      await aiFetch<AiProfile>("/ai/profile", {
        method: "PATCH",
        body: JSON.stringify({ content_md: draft }),
      });
      await qc.invalidateQueries({ queryKey: ["ai", "profile"] });
      setDraft(null);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  async function runBootstrap() {
    setBootstrapping(true);
    setBootstrapMsg(null);
    try {
      const resp = await aiFetch<AiBootstrapResponse>("/ai/profile/bootstrap", {
        method: "POST",
      });
      if (resp.bootstrap_skipped) {
        setBootstrapMsg(resp.reason ?? "Bootstrap produced no proposal.");
      } else {
        setBootstrapMsg("New proposal ready for review below.");
      }
      await qc.invalidateQueries({ queryKey: ["ai", "profile"] });
      await qc.invalidateQueries({ queryKey: ["ai", "profile", "updates"] });
    } catch (e) {
      setBootstrapMsg(e instanceof Error ? e.message : "Bootstrap failed");
    } finally {
      setBootstrapping(false);
    }
  }

  async function acceptUpdate(id: string) {
    setResolvingId(id);
    try {
      await aiFetch<AiProfile>(`/ai/profile/updates/${id}/accept`, { method: "POST" });
      await qc.invalidateQueries({ queryKey: ["ai", "profile"] });
      await qc.invalidateQueries({ queryKey: ["ai", "profile", "updates"] });
    } finally {
      setResolvingId(null);
    }
  }

  async function rejectUpdate(id: string) {
    setResolvingId(id);
    try {
      await aiFetch<void>(`/ai/profile/updates/${id}/reject`, { method: "POST" });
      await qc.invalidateQueries({ queryKey: ["ai", "profile", "updates"] });
    } finally {
      setResolvingId(null);
    }
  }

  if (profileLoading) {
    return (
      <SubSection title="Profile">
        <div className="flex items-center gap-2 text-sm text-muted-foreground py-4">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      </SubSection>
    );
  }

  if (profileError || !profile) {
    return (
      <SubSection title="Profile">
        <div className="flex items-center gap-2 text-sm text-destructive py-2">
          <AlertCircle className="h-4 w-4 shrink-0" />
          Failed to load profile. Reload the page to try again.
        </div>
      </SubSection>
    );
  }

  const hasProfile = (profile.content_md ?? "").trim().length > 0;

  return (
    <SubSection title="Profile">
      <p className="text-xs text-muted-foreground mb-4">
        Long-term memory the coach and chatbot both read. The AI proposes
        changes — you accept or reject. You can also edit it directly any time.
      </p>

      {/* Current profile / editor */}
      {editing ? (
        <div className="space-y-3">
          <textarea
            value={liveValue}
            onChange={(e) => setDraft(e.target.value)}
            rows={14}
            spellCheck={false}
            className="w-full text-sm font-mono bg-background border border-border rounded-md px-3 py-2 outline-none focus:ring-2 focus:ring-primary/30 focus:border-primary"
            placeholder="## Current focuses&#10;&#10;## Values & non-negotiables&#10;…"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={saving}
              onClick={saveDraft}
              className="px-4 py-2 text-sm rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-40 cursor-pointer disabled:cursor-default"
            >
              {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : "Save"}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={cancelEdit}
              className="px-3 py-2 text-sm rounded-md border border-border hover:bg-muted transition-colors cursor-pointer disabled:opacity-50"
            >
              Cancel
            </button>
            <span className="text-xs text-muted-foreground ml-auto">
              {liveValue.length} / 8000
            </span>
          </div>
          {saveError && (
            <p className="text-xs text-destructive flex items-center gap-1.5">
              <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {saveError}
            </p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {hasProfile ? (
            <pre className="text-sm whitespace-pre-wrap font-sans bg-muted/30 border border-border rounded-md p-4 max-h-[28rem] overflow-y-auto">
              {profile.content_md}
            </pre>
          ) : (
            <div className="text-sm text-muted-foreground bg-muted/30 border border-dashed border-border rounded-md p-4">
              {profile.last_bootstrapped_at
                ? "Your profile is empty. Edit it directly, or run the bootstrap pass again after journaling more."
                : "Your profile is empty. Click “Build my profile” to draft one from your existing notes, documents, and recent activity."}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={startEdit}
              className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors cursor-pointer"
            >
              Edit
            </button>
            <button
              type="button"
              disabled={bootstrapping}
              onClick={runBootstrap}
              className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors cursor-pointer disabled:opacity-50 inline-flex items-center gap-1.5"
            >
              {bootstrapping && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              {hasProfile ? "Propose updates from my data" : "Build my profile"}
            </button>
            {profile.last_bootstrapped_at && (
              <span className="text-xs text-muted-foreground ml-auto">
                Last bootstrapped {new Date(profile.last_bootstrapped_at).toLocaleDateString()}
              </span>
            )}
          </div>
          {bootstrapMsg && (
            <p className="text-xs text-muted-foreground">{bootstrapMsg}</p>
          )}
        </div>
      )}

      {/* Pending updates */}
      {pendingUpdates.length > 0 && (
        <div className="mt-5 space-y-3">
          <Label>Pending proposed updates</Label>
          {pendingUpdates.map((u) => (
            <div key={u.id} className="border border-border rounded-md bg-muted/20">
              <div className="px-4 py-2.5 border-b border-border flex items-center gap-2">
                <span className="badge badge-warning">{u.source}</span>
                <span className="text-xs text-muted-foreground">
                  {new Date(u.created_at).toLocaleString()}
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <button
                    type="button"
                    disabled={resolvingId === u.id}
                    onClick={() => acceptUpdate(u.id)}
                    className="px-2.5 py-1 text-xs rounded-md bg-primary text-primary-foreground hover:opacity-90 transition-opacity disabled:opacity-50 cursor-pointer disabled:cursor-default inline-flex items-center gap-1"
                  >
                    {resolvingId === u.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Check className="h-3 w-3" />}
                    Accept
                  </button>
                  <button
                    type="button"
                    disabled={resolvingId === u.id}
                    onClick={() => rejectUpdate(u.id)}
                    className="px-2.5 py-1 text-xs rounded-md border border-border hover:bg-muted transition-colors cursor-pointer disabled:opacity-50"
                  >
                    Reject
                  </button>
                </div>
              </div>
              {u.diff_summary && (
                <p className="px-4 pt-3 text-xs text-muted-foreground italic">
                  {u.diff_summary}
                </p>
              )}
              <pre className="px-4 pb-3 pt-2 text-sm whitespace-pre-wrap font-sans max-h-72 overflow-y-auto">
                {u.proposed_content_md}
              </pre>
            </div>
          ))}
        </div>
      )}
    </SubSection>
  );
}

function JournalSignalsSubSection({
  enabled,
  onToggle,
  disabled,
}: {
  enabled: boolean;
  onToggle: (next: boolean) => void;
  disabled: boolean;
}) {
  const [backfilling, setBackfilling] = useState(false);
  const [backfillResult, setBackfillResult] = useState<JournalSignalsBackfillResponse | null>(null);
  const [backfillError, setBackfillError] = useState<string | null>(null);

  async function runBackfill() {
    setBackfilling(true);
    setBackfillError(null);
    setBackfillResult(null);
    try {
      const resp = await aiFetch<JournalSignalsBackfillResponse>(
        "/ai/journal-signals/backfill",
        { method: "POST" },
      );
      setBackfillResult(resp);
    } catch (e) {
      setBackfillError(e instanceof Error ? e.message : "Backfill failed");
    } finally {
      setBackfilling(false);
    }
  }

  return (
    <SubSection title="Journal signals">
      <p className="text-xs text-muted-foreground mb-4">
        When enabled, each journal entry you save is read by a small AI pass
        that extracts sentiment, themes, self-talk valence, and energy level.
        The coach uses these signals to spot patterns across days and weeks —
        not to quote you. Stored locally; opting out skips extraction entirely.
      </p>

      {/* Toggle */}
      <label className="flex items-center justify-between gap-4 px-4 py-3 rounded-md border border-border bg-card cursor-pointer">
        <div className="flex flex-col">
          <span className="text-sm font-medium">Extract signals on save</span>
          <span className="text-xs text-muted-foreground">
            {enabled ? "On — new journal entries are processed in the background." : "Off — no extraction runs."}
          </span>
        </div>
        <input
          type="checkbox"
          className="checkbox-themed h-5 w-5 shrink-0"
          checked={enabled}
          disabled={disabled}
          onChange={(e) => onToggle(e.target.checked)}
        />
      </label>

      {/* Backfill */}
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={!enabled || backfilling}
          onClick={runBackfill}
          className="px-3 py-1.5 text-xs rounded-md border border-border hover:bg-muted transition-colors cursor-pointer disabled:opacity-50 inline-flex items-center gap-1.5"
        >
          {backfilling && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Backfill existing entries
        </button>
        <p className="text-xs text-muted-foreground">
          Runs extraction across every journal entry you've already written. Safe to run repeatedly.
        </p>
      </div>
      {backfillResult && (
        <p className="mt-3 text-xs text-muted-foreground">
          Backfill complete: <strong>{backfillResult.extracted}</strong> extracted,{" "}
          {backfillResult.skipped_empty} empty, {backfillResult.skipped_current} already current
          {backfillResult.errors > 0 && (
            <>, <span className="text-destructive">{backfillResult.errors} errored</span></>
          )}.
        </p>
      )}
      {backfillError && (
        <p className="mt-3 text-xs text-destructive flex items-center gap-1.5">
          <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {backfillError}
        </p>
      )}
    </SubSection>
  );
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

      {/* Profile is intentionally hidden from end users — it's built
          automatically in the background once an API key is configured,
          and updated silently from journal activity. The backend
          /ai/profile/* endpoints remain available for debugging. */}

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

      {/* ── Journal signals (Phase 2 of AI coach redesign) ── */}
      <JournalSignalsSubSection
        enabled={settings.ai_journal_extraction_enabled ?? true}
        onToggle={(next) => save({ ai_journal_extraction_enabled: next })}
        disabled={saving}
      />

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

// ── Templates section ─────────────────────────────────────────────────────────

function TemplatesSection() {
  const qc = useQueryClient();
  const { user } = useAuth();

  const { data: templatesData, isLoading } = $api.useQuery("get", "/templates", {});
  const templates = templatesData?.items ?? [];

  // ── Create / edit form state ─────────────────────────────────────────────
  const [editing, setEditing]   = useState<string | null>(null); // null = new
  const [formOpen, setFormOpen] = useState(false);
  const [formName,        setFormName]        = useState("");
  const [formDomain,      setFormDomain]      = useState<"notes" | "documents">("notes");
  const [formScope,       setFormScope]       = useState<"household" | "user">("household");
  const [formDescription, setFormDescription] = useState("");
  const [formTitleTpl,    setFormTitleTpl]    = useState("");
  const [formContentMd,   setFormContentMd]   = useState("");
  const [formSaving,      setFormSaving]      = useState(false);
  const [formError,       setFormError]       = useState<string | null>(null);

  function openNew() {
    setEditing(null);
    setFormName(""); setFormDomain("notes"); setFormScope("household");
    setFormDescription(""); setFormTitleTpl(""); setFormContentMd("");
    setFormError(null);
    setFormOpen(true);
  }

  function openEdit(t: (typeof templates)[number]) {
    setEditing(t.id);
    setFormName(t.name);
    setFormDomain(t.domain);
    setFormScope(t.scope);
    setFormDescription(t.description ?? "");
    setFormTitleTpl(t.title_template ?? "");
    setFormContentMd(t.content_md ?? "");
    setFormError(null);
    setFormOpen(true);
  }

  async function submitForm(e: React.FormEvent) {
    e.preventDefault();
    if (!formName.trim()) return;
    setFormSaving(true);
    setFormError(null);
    try {
      const token = getAccessToken();
      const body = {
        name: formName.trim(),
        domain: formDomain,
        scope: formScope,
        description: formDescription.trim() || null,
        title_template: formTitleTpl.trim() || null,
        content_md: formContentMd.trim() || null,
      };
      const url = editing
        ? `${apiBaseUrl}/templates/${editing}`
        : `${apiBaseUrl}/templates`;
      const res = await fetch(url, {
        method: editing ? "PATCH" : "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const b = await res.json().catch(() => ({}));
        throw new Error((b as { detail?: string }).detail ?? "Failed to save");
      }
      await qc.invalidateQueries({ queryKey: ["get", "/templates"] });
      setFormOpen(false);
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setFormSaving(false);
    }
  }

  async function deleteTemplate(id: string) {
    const token = getAccessToken();
    await fetch(`${apiBaseUrl}/templates/${id}`, {
      method: "DELETE",
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    });
    await qc.invalidateQueries({ queryKey: ["get", "/templates"] });
  }

  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  return (
    <div className="space-y-5">
      <SectionTitle>Templates</SectionTitle>

      <SubSection title="Reusable templates">
        <div className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Templates let you pre-fill new notes with content and a title pattern.
            Assign a template to a collection to have it applied automatically.
          </p>
          <p className="text-xs text-muted-foreground">
            Title template variables: <code className="font-mono bg-muted px-1 rounded">{"{{day_of_week}}"}</code>,{" "}
            <code className="font-mono bg-muted px-1 rounded">{"{{month}}"}</code>,{" "}
            <code className="font-mono bg-muted px-1 rounded">{"{{day}}"}</code>,{" "}
            <code className="font-mono bg-muted px-1 rounded">{"{{year}}"}</code>,{" "}
            <code className="font-mono bg-muted px-1 rounded">{"{{date}}"}</code>,{" "}
            <code className="font-mono bg-muted px-1 rounded">{"{{user_name}}"}</code>
          </p>

          {/* Template list */}
          {isLoading ? (
            <div className="flex items-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading…
            </div>
          ) : templates.length === 0 ? (
            <p className="text-xs text-muted-foreground">No templates yet.</p>
          ) : (
            <div className="divide-y rounded-md border overflow-hidden">
              {templates.map((t) => (
                <div key={t.id} className="flex items-start gap-3 px-4 py-3 bg-card">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{t.name}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground font-mono uppercase tracking-wide">
                        {t.domain}
                      </span>
                      {t.scope === "user" && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-muted text-muted-foreground flex items-center gap-0.5">
                          <Lock className="h-2.5 w-2.5" /> Private
                        </span>
                      )}
                    </div>
                    {t.description && (
                      <p className="text-xs text-muted-foreground mt-0.5 truncate">{t.description}</p>
                    )}
                    {t.title_template && (
                      <p className="text-xs text-muted-foreground mt-0.5 font-mono truncate">
                        Title: {t.title_template}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1 shrink-0">
                    <button
                      type="button"
                      onClick={() => openEdit(t)}
                      className="h-7 w-7 flex items-center justify-center rounded text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                      title="Edit"
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </button>
                    {confirmDeleteId === t.id ? (
                      <div className="flex items-center gap-1">
                        <span className="text-[10px] text-muted-foreground">Delete?</span>
                        <button
                          type="button"
                          onClick={() => { deleteTemplate(t.id); setConfirmDeleteId(null); }}
                          className="text-[10px] px-2 py-1 rounded bg-destructive text-destructive-foreground"
                        >
                          Yes
                        </button>
                        <button
                          type="button"
                          onClick={() => setConfirmDeleteId(null)}
                          className="text-[10px] px-2 py-1 rounded bg-muted text-muted-foreground"
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => setConfirmDeleteId(t.id)}
                        className="h-7 w-7 flex items-center justify-center rounded text-muted-foreground hover:text-destructive hover:bg-muted transition-colors"
                        title="Delete"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}

          <button
            type="button"
            onClick={openNew}
            className="flex items-center gap-1.5 h-9 px-4 text-sm font-medium rounded-md bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
          >
            <Plus className="h-4 w-4" />
            New template
          </button>

          {/* Create/edit form */}
          {formOpen && (
            <form onSubmit={submitForm} className="border rounded-lg bg-muted/20 p-4 space-y-3 mt-2">
              <p className="text-sm font-semibold">{editing ? "Edit template" : "New template"}</p>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Name *</label>
                  <input
                    type="text"
                    value={formName}
                    onChange={(e) => setFormName(e.target.value)}
                    placeholder="e.g. Daily Journal"
                    autoFocus
                    className="w-full h-8 px-3 rounded border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
                  />
                </div>
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Domain</label>
                  <div className="flex gap-2">
                    {(["notes", "documents"] as const).map((d) => (
                      <button
                        key={d}
                        type="button"
                        onClick={() => setFormDomain(d)}
                        className={cn(
                          "flex-1 h-8 text-xs rounded border transition-colors",
                          formDomain === d
                            ? "bg-primary/10 border-primary/40 text-primary font-medium"
                            : "bg-background hover:bg-muted/50",
                        )}
                      >
                        {d === "notes" ? "📓 Notes" : "📄 Docs"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Description</label>
                <input
                  type="text"
                  value={formDescription}
                  onChange={(e) => setFormDescription(e.target.value)}
                  placeholder="Optional description"
                  className="w-full h-8 px-3 rounded border bg-background text-sm focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
              </div>

              <div>
                <label className="text-xs text-muted-foreground mb-1 block">
                  Title template{" "}
                  <span className="font-normal opacity-70">
                    (used for auto-created entries, e.g. <code className="font-mono">{"{{day_of_week}}, {{month}} {{day}}, {{year}}"}</code>)
                  </span>
                </label>
                <input
                  type="text"
                  value={formTitleTpl}
                  onChange={(e) => setFormTitleTpl(e.target.value)}
                  placeholder={`{{day_of_week}}, {{month}} {{day}}, {{year}}`}
                  className="w-full h-8 px-3 rounded border bg-background text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary/50"
                />
              </div>

              {formDomain === "notes" && (
                <div>
                  <label className="text-xs text-muted-foreground mb-1 block">Default content (Markdown)</label>
                  <textarea
                    value={formContentMd}
                    onChange={(e) => setFormContentMd(e.target.value)}
                    placeholder="## {{day_of_week}} check-in&#10;&#10;**Mood:** &#10;**Focus today:** "
                    rows={5}
                    className="w-full px-3 py-2 rounded border bg-background text-sm font-mono resize-y focus:outline-none focus:ring-1 focus:ring-primary/50"
                  />
                </div>
              )}

              <div>
                <label className="text-xs text-muted-foreground mb-1 block">Visibility</label>
                <div className="flex gap-2">
                  {([
                    { value: "household", label: "🏠 Household (shared)" },
                    { value: "user",      label: "🔒 Private to me" },
                  ] as const).map(({ value, label }) => (
                    <button
                      key={value}
                      type="button"
                      onClick={() => setFormScope(value)}
                      className={cn(
                        "flex-1 h-8 text-xs rounded border transition-colors",
                        formScope === value
                          ? "bg-primary/10 border-primary/40 text-primary font-medium"
                          : "bg-background hover:bg-muted/50",
                      )}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>

              {formError && (
                <p className="text-xs text-destructive flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5 shrink-0" /> {formError}
                </p>
              )}

              <div className="flex gap-2 pt-1">
                <button
                  type="submit"
                  disabled={formSaving || !formName.trim()}
                  className="h-8 px-4 text-sm font-medium rounded-md bg-primary text-primary-foreground disabled:opacity-40 flex items-center gap-1.5"
                >
                  {formSaving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
                  {editing ? "Save changes" : "Create template"}
                </button>
                <button
                  type="button"
                  onClick={() => setFormOpen(false)}
                  className="h-8 px-4 text-sm rounded-md border hover:bg-muted/50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </form>
          )}
        </div>
      </SubSection>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = ADMIN_ROLES.has(user?.role ?? "");
  // ai-access-001: hide the AI settings section entirely when the current
  // member's AI features are disabled by their household admin.
  const aiEnabled = user?.ai_features_enabled !== false;

  // Non-admins skip the Household tab entirely; start them on Account instead.
  const [active, setActive] = useState<Section>(isAdmin ? "household" : "account");

  const ADMIN_ONLY_SECTIONS = new Set<Section>(["household", "visibility"]);
  const visibleSections = new Set<Section>(
    SECTIONS.map((s) => s.id).filter(
      (id) =>
        (!ADMIN_ONLY_SECTIONS.has(id) || isAdmin) &&
        // Hide the AI tab when this member has AI disabled.
        (id !== "ai" || aiEnabled),
    ),
  );

  return (
    <div className="flex h-full">
      {/* Settings left-nav */}
      <div className="w-52 shrink-0 border-r bg-card p-4">
        <SettingsNav active={active} onChange={setActive} visibleSections={visibleSections} isAdmin={isAdmin} />
      </div>

      {/* Content area */}
      <div className="flex-1 overflow-y-auto p-8">
        {active === "appearance"  && <AppearanceSection />}
        {active === "navigation"  && <NavigationSection />}
        {active === "account"     && <AccountSection />}
        {active === "household"   && isAdmin && <HouseholdSection />}
        {active === "visibility"  && isAdmin && <VisibilitySettingsSection />}
        {active === "templates"   && <TemplatesSection />}
        {active === "collections" && <PagesSection />}
        {active === "ai"          && aiEnabled && <AiSection />}
      </div>
    </div>
  );
}
