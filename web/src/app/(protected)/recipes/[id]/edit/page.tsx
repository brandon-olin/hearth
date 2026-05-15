import Wrapper from "./_wrapper";

export function generateStaticParams() {
  return [{ id: "index" }];
}

export default function Page() {
  return <Wrapper />;
}
