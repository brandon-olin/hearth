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
} from "lucide-react";
import { cn } from "@/lib/utils";
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
import { ALL_NAV_ITEMS, type NavItem } from "@/lib/sidebar/nav-items";
import {
  FOLDER_ICON_GROUPS,
  resolveFolderIcon,
  DEFAULT_FOLDER_ICON,
} from "@/lib/sidebar/folder-icons";

// ── Left nav ──────────────────────────────────────────────────────────────────

type Section = "appearance" | "account" | "household";

const SECTIONS: { id: Section; label: string; icon: React.ElementType }[] = [
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "account",    label: "Account",    icon: User    },
  { id: "household",  label: "Household",  icon: Home    },
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

function SidebarCustomizer() {
  const { sidebarConfig, setSidebarConfig } = useSidebarConfig();

  // Unified drag state — works for both nav item hrefs and folder IDs
  const dragIdRef = useRef<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

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
  const folderedHrefs = new Set(folders.flatMap((f) => f.hrefs));
  const allHrefs      = ALL_NAV_ITEMS.map((n) => n.href);
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
      const item = ALL_NAV_ITEMS.find((n) => n.href === id);
      return item ? [{ kind: "nav" as const, item }] : [];
    }
    const folder = folders.find((f) => f.id === id);
    return folder ? [{ kind: "folder" as const, folder }] : [];
  });

  // ── mutations ───────────────────────────────────────────────────────────────

  function toggleHidden(href: string) {
    const nextHidden = hidden.includes(href)
      ? hidden.filter((h) => h !== href)
      : [...hidden, href];
    setSidebarConfig({ ...sidebarConfig, hidden: nextHidden });
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

  // ── unified drag-to-reorder ─────────────────────────────────────────────────

  function handleDragStart(id: string) { dragIdRef.current = id; }

  function handleDragOver(e: React.DragEvent, targetId: string) {
    e.preventDefault();
    if (dragIdRef.current !== targetId) setDragOverId(targetId);
  }

  function handleDrop(targetId: string) {
    const fromId = dragIdRef.current;
    if (!fromId || fromId === targetId) { setDragOverId(null); return; }
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

  function handleDragEnd() { dragIdRef.current = null; setDragOverId(null); }

  // ── render ──────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Drag to reorder. Folders are collapsible groups in the sidebar.
        </p>
        <button
          type="button"
          onClick={() => setAddingFolder(true)}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors cursor-pointer shrink-0 ml-3"
        >
          <FolderPlus className="h-3.5 w-3.5" />
          Add folder
        </button>
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

          // ── nav item row ──────────────────────────────────────────────────
          if (entry.kind === "nav") {
            const { item } = entry;
            const isHidden = hidden.includes(item.href);
            const Icon     = item.icon;
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
                <Icon className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="flex-1 text-sm font-medium">{item.label}</span>
                <button
                  type="button"
                  onClick={() => toggleHidden(item.href)}
                  className="text-muted-foreground hover:text-foreground cursor-pointer"
                  aria-label={isHidden ? "Show in sidebar" : "Hide from sidebar"}
                >
                  {isHidden ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                </button>
              </div>
            );
          }

          // ── folder row ────────────────────────────────────────────────────
          const { folder } = entry;
          const isEditing  = editingFolderId === folder.id;
          const isExpanded = expandedFolderId === folder.id;
          const folderItems = folder.hrefs
            .map((href) => ALL_NAV_ITEMS.find((n) => n.href === href))
            .filter((n): n is NavItem => !!n);
          const available = ALL_NAV_ITEMS.filter((n) => !folder.hrefs.includes(n.href));

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
                  isDragOver && "border-primary bg-primary/5 scale-[1.01]",
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
                    const Icon     = item.icon;
                    const isHidden = hidden.includes(item.href);
                    return (
                      <div
                        key={item.href}
                        className={cn(
                          "flex items-center gap-2 px-2 py-1.5 rounded-md text-sm",
                          isHidden && "opacity-40",
                        )}
                      >
                        <Icon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        <span className="flex-1 text-muted-foreground">{item.label}</span>
                        <button
                          type="button"
                          onClick={() => toggleHidden(item.href)}
                          className="text-muted-foreground hover:text-foreground cursor-pointer"
                          title={isHidden ? "Show in sidebar" : "Hide from sidebar"}
                        >
                          {isHidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                        </button>
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
      <SubSection title="Sidebar layout">
        <SidebarCustomizer />
      </SubSection>
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
        {active === "appearance" && <AppearanceSection />}
        {active === "account"    && <AccountSection />}
        {active === "household"  && <HouseholdSection />}
      </div>
    </div>
  );
}
