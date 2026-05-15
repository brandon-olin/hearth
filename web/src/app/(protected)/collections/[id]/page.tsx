import Wrapper from "./_wrapper";

// output: 'export' requires at least one param to generate a shell HTML file.
// The actual content is always loaded client-side (ssr: false in _wrapper.tsx),
// so this placeholder entry is never meaningfully rendered.
export function generateStaticParams() {
  return [{ id: "index" }];
}

export default function Page() {
  return <Wrapper />;
}
