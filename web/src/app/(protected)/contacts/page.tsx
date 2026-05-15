import { Users } from "lucide-react";

export default function ContactsPage() {
  return (
    <div className="page-content">
      <div className="flex items-center gap-2 mb-6">
        <Users className="h-5 w-5 text-muted-foreground" />
        <h1 className="text-xl font-semibold">Contacts</h1>
      </div>
      <div className="py-16 text-center border rounded-lg bg-card">
        <Users className="h-10 w-10 text-muted-foreground/30 mx-auto mb-3" />
        <p className="text-sm font-medium text-muted-foreground">Contacts coming soon</p>
        <p className="text-xs text-muted-foreground/70 mt-1 max-w-xs mx-auto">
          Google and Apple Contacts sync will be available in an upcoming release.
        </p>
      </div>
    </div>
  );
}
