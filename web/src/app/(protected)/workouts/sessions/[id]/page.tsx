import SessionLogger from "./session-logger";

export function generateStaticParams() {
  return [{ id: "index" }];
}

export default function Page() {
  return <SessionLogger />;
}
