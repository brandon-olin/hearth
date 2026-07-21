import TemplateDetail from "./template-detail";

export function generateStaticParams() {
  return [{ id: "index" }];
}

export default function Page() {
  return <TemplateDetail />;
}
