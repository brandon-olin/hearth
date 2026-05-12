"use client";

/**
 * useNavItems — single source of truth for the sidebar navigation list.
 *
 * Combines:
 *   1. BUILTIN_NAV_ITEMS     — static, code-defined pages (Todos, Habits, etc.)
 *   2. User collections      — fetched from the API, each with its own sidebar entry
 *   3. Pinned projects       — projects with show_in_nav=true, e.g. To-dos, Chores
 *   4. Pinned documents      — individual document IDs stored in SidebarConfig
 *
 * All four types go through the same SidebarConfig ordering/visibility/folder
 * system — there is no "injected after the fact" tier. The compositing
 * happens once here; everything downstream sees one uniform list.
 *
 * Built-ins can be hidden/reordered but not deleted.
 * Collections can be hidden, reordered, or deleted from Settings > Pages.
 * Projects can be pinned/unpinned from Settings > Projects or their project page.
 * Documents can be pinned/unpinned from Settings > Navigation.
 */

import { useMemo } from "react";
import { CheckSquare, FolderKanban, FileText } from "lucide-react";
import { $api } from "@/lib/api/query";
import { useSidebarConfig } from "./context";
import { BUILTIN_NAV_ITEMS, type NavItem } from "./nav-items";

export type { NavItem };

/**
 * Returns a stable combined list of nav items
 * (builtins + collections + pinned projects + pinned documents).
 * All types are mapped to the same NavItem shape so the shell and sidebar
 * customizer require no changes to their rendering logic.
 */
export function useNavItems(): { items: NavItem[]; isLoading: boolean } {
  const { sidebarConfig } = useSidebarConfig();
  const pinnedDocumentIds = sidebarConfig.pinnedDocumentIds ?? [];

  const { data: collectionsData, isLoading: collectionsLoading } =
    $api.useQuery("get", "/collections");

  const { data: projectsData, isLoading: projectsLoading } =
    $api.useQuery("get", "/projects", {
      params: { query: { show_in_nav: true } },
    });

  // Only fetch documents if there are pinned ones
  const { data: documentsData, isLoading: documentsLoading } =
    $api.useQuery(
      "get",
      "/documents",
      {},
      { enabled: pinnedDocumentIds.length > 0 },
    );

  const isLoading = collectionsLoading || projectsLoading || (pinnedDocumentIds.length > 0 && documentsLoading);

  const items = useMemo<NavItem[]>(() => {
    const collectionItems: NavItem[] = (collectionsData?.items ?? []).map((col) => ({
      href: `/collections/${col.id}`,
      label: col.name,
      icon: col.icon ?? "📁",
      isCollection: true,
      collectionId: col.id,
      collectionDomain: col.domain,
    }));

    const projectItems: NavItem[] = (projectsData?.items ?? []).map((proj) => ({
      href: `/projects/${proj.id}`,
      label: proj.name,
      // System projects get a check-square icon; user projects get a folder icon
      icon: proj.is_system ? CheckSquare : FolderKanban,
      isProject: true,
      projectId: proj.id,
    }));

    // Only emit nav items for document IDs that are still pinned
    const allDocs = documentsData?.items ?? [];
    const documentItems: NavItem[] = pinnedDocumentIds
      .map((docId) => allDocs.find((d) => d.id === docId))
      .filter((d): d is NonNullable<typeof d> => !!d && !d.archived_at)
      .map((d) => ({
        href: `/documents/${d.id}`,
        label: d.title,
        icon: d.icon ?? FileText,
        isDocument: true,
        documentId: d.id,
      }));

    return [...BUILTIN_NAV_ITEMS, ...collectionItems, ...projectItems, ...documentItems];
  }, [collectionsData, projectsData, documentsData, pinnedDocumentIds]);

  return { items, isLoading };
}
