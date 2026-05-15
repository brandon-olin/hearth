// Server component — required to export generateStaticParams for output:'export'.
// Returns an empty array because recipe IDs are not known at build time;
// the Tauri app navigates to them client-side after fetching from the API.
export function generateStaticParams() {
  return [];
}

export default function RecipeLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
