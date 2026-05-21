"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ChevronLeft, ChevronRight, Plus, Pencil, Trash2, Check, X, Loader2, Tag } from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetCategory {
  id: string;
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
  default_scope: "personal" | "household";
  sort_order: number;
}

// ── Preset palette ────────────────────────────────────────────────────────────

const COLORS = [
  "#ef4444", "#f97316", "#eab308", "#22c55e",
  "#14b8a6", "#3b82f6", "#8b5cf6", "#ec4899",
  "#64748b", "#0ea5e9", "#a3e635", "#f43f5e",
];

// ── Default categories with merchant keyword seeds ────────────────────────────
//
// Keywords use substring matching — "wegmans" catches "WEGMANS #91 BUFFALO NY".
// Keep entries lowercase; the auto-categorize engine lowercases before comparing.

const DEFAULT_CATEGORIES = [
  {
    name: "Income", icon: "💰", color: "#22c55e",
    keywords: [
      "payroll", "direct deposit", "salary", "wages", "irs treas",
      "tax refund", "venmo cashout", "stripe payout", "gusto", "adp",
    ],
  },
  {
    name: "Housing", icon: "🏠", color: "#64748b",
    keywords: [
      "rent", "mortgage", "property tax", "hoa", "homeowners assoc",
      "zillo", "zillow", "apartments.com", "lease",
    ],
  },
  {
    name: "Utilities", icon: "💡", color: "#eab308",
    keywords: [
      "electric", "gas utility", "water bill", "sewage", "con edison",
      "pge", "pg&e", "duke energy", "dominion energy", "national grid",
      "xcel energy", "centerpoint", "atmos energy",
      // Internet & phone
      "comcast", "xfinity", "spectrum", "cox communications",
      "at&t", "verizon wireless", "t-mobile", "sprint",
      "frontier", "centurylink", "lumen",
    ],
  },
  {
    name: "Groceries", icon: "🛒", color: "#3b82f6",
    keywords: [
      // National / large regional
      "wegmans", "kroger", "safeway", "whole foods", "trader joe",
      "aldi", "publix", "heb", "meijer", "jewel osco", "stop shop",
      "giant food", "harris teeter", "sprouts", "fresh market",
      "food lion", "winn dixie", "market basket", "price chopper",
      "hannaford", "shoprite", "albertsons", "vons", "ralphs",
      "stater bros", "winco", "save mart", "fresco",
      // Warehouse
      "costco", "sam's club", "bj's wholesale",
      // Online grocery
      "instacart", "shipt", "amazon fresh", "walmart grocery",
      // Generic
      "grocery", "supermarket", "food market",
    ],
  },
  {
    name: "Dining", icon: "🍽️", color: "#f97316",
    keywords: [
      // Fast food
      "mcdonald", "burger king", "wendy's", "taco bell", "chick-fil-a",
      "chick fil a", "five guys", "shake shack", "in-n-out", "sonic drive",
      "jack in the box", "whataburger", "culver", "raising cane",
      "popeyes", "kfc", "wingstop", "zaxby",
      // Fast casual
      "chipotle", "panera", "subway", "jimmy john", "jersey mike",
      "firehouse subs", "potbelly", "panda express", "noodles",
      "sweetgreen", "cava", "mod pizza",
      // Coffee & bakery
      "starbucks", "dunkin", "dutch bros", "caribou coffee",
      "tim hortons", "peet's coffee", "scooter's coffee",
      // Pizza
      "domino", "pizza hut", "papa john", "little caesars",
      // Delivery platforms
      "doordash", "grubhub", "ubereats", "uber eats", "seamless",
      "postmates", "caviar",
      // Sit-down chains
      "olive garden", "applebee's", "outback", "chili's",
      "cheesecake factory", "buffalo wild wings", "texas roadhouse",
      "red lobster", "red robin", "denny's", "ihop", "cracker barrel",
      "first watch", "perkins",
      // Generic
      "restaurant", "ristorante", "bistro", "cafe", "diner", "grill",
      "sushi", "ramen", "pizzeria", "taqueria", "brasserie",
    ],
  },
  {
    name: "Transportation", icon: "🚗", color: "#8b5cf6",
    keywords: [
      // Ride-share
      "uber", "lyft",
      // Gas stations
      "shell", "bp station", "exxon", "chevron", "sunoco",
      "speedway", "marathon", "circle k", "wawa", "sheetz",
      "casey's", "pilot travel", "flying j", "loves travel",
      "quiktrip", "kwik trip", "racetrac",
      // Parking
      "parking", "park plus", "spothero", "parkwhiz",
      // Tolls
      "e-zpass", "sunpass", "fastrak", "pikepass",
      // Auto
      "jiffy lube", "valvoline", "midas", "firestone", "goodyear",
      "pep boys", "autozone", "o'reilly auto", "advance auto",
      "napa auto", "car wash",
      // Transit
      "mbta", "mta", "septa", "bart", "wmata", "cta transit",
      "metro card", "clipper card", "ventra",
    ],
  },
  {
    name: "Travel", icon: "✈️", color: "#14b8a6",
    keywords: [
      // Airlines
      "delta air", "united air", "american air", "southwest air",
      "jetblue", "alaska air", "spirit air", "frontier air",
      "air canada", "british air", "lufthansa",
      // Hotels
      "marriott", "hilton", "hyatt", "ihg hotel", "wyndham",
      "best western", "holiday inn", "hampton inn", "courtyard",
      "fairfield inn", "sheraton", "westin", "doubletree",
      "four seasons", "ritz carlton", "kimpton",
      // Rail
      "amtrak",
      // Car rental
      "enterprise rent", "hertz", "avis car", "budget car", "alamo",
      "national car", "sixt car", "turo",
      // Booking platforms
      "expedia", "booking.com", "airbnb", "vrbo", "hotels.com",
      "kayak", "priceline", "orbitz",
    ],
  },
  {
    name: "Subscriptions", icon: "📱", color: "#a3e635",
    keywords: [
      // Streaming video
      "netflix", "hulu", "disney plus", "disney+", "hbo max",
      "peacock", "paramount+", "apple tv", "youtube premium",
      "amazon prime video", "espn+", "discovery+", "showtime",
      "sling", "fubo", "philo",
      // Streaming music
      "spotify", "apple music", "tidal", "pandora",
      "amazon music", "youtube music", "deezer",
      // Gaming
      "xbox game pass", "playstation plus", "nintendo switch online",
      "steam", "epic games",
      // Software / cloud
      "adobe", "microsoft 365", "google workspace", "google one",
      "dropbox", "icloud storage", "zoom", "slack",
      "notion", "figma", "github", "1password", "lastpass",
      "nordvpn", "expressvpn",
      // News & reading
      "new york times", "nyt", "washington post", "wall street journal",
      "wsj", "economist", "bloomberg", "spotify podcast",
      "audible", "kindle unlimited",
      // Health & fitness
      "peloton", "noom", "calm", "headspace", "whoop",
    ],
  },
  {
    name: "Shopping", icon: "🛍️", color: "#0ea5e9",
    keywords: [
      // Online
      "amazon", "walmart.com", "target.com", "wayfair", "chewy",
      "etsy", "ebay", "wish.com", "shein", "temu", "shopify",
      // Department / general
      "walmart", "target", "dollar general", "dollar tree",
      "five below", "big lots",
      // Electronics
      "best buy", "apple store", "apple.com", "microsoft store",
      "b&h photo", "adorama", "newegg",
      // Home
      "home depot", "lowe's", "ikea", "williams sonoma",
      "pottery barn", "restoration hardware", "crate barrel",
      "bed bath", "tuesday morning",
      // Clothing
      "tj maxx", "marshalls", "ross stores", "burlington coat",
      "nordstrom", "macy's", "jcpenney", "kohls", "gap", "old navy",
      "banana republic", "h&m", "zara", "uniqlo",
      // Pets
      "petsmart", "petco",
    ],
  },
  {
    name: "Healthcare", icon: "🏥", color: "#ef4444",
    keywords: [
      // Pharmacy
      "walgreens", "cvs pharmacy", "rite aid", "duane reade",
      "express scripts", "optum rx", "caremark",
      // Dental & vision
      "dental", "dentist", "orthodont", "vision", "lenscrafters",
      "pearle vision", "america's best",
      // Fitness (non-subscription)
      "planet fitness", "la fitness", "24 hour fitness", "equinox",
      "anytime fitness", "ymca", "crunch fitness",
      // Generic medical
      "hospital", "clinic", "medical", "urgent care", "labcorp",
      "quest diagnostics",
    ],
  },
  {
    name: "Insurance", icon: "🛡️", color: "#f43f5e",
    keywords: [
      "geico", "progressive ins", "state farm", "allstate",
      "liberty mutual", "nationwide ins", "farmers ins",
      "usaa insurance", "travelers ins", "hartford ins",
      "metlife", "aflac", "cigna", "aetna", "humana", "anthem",
      "blue cross", "blue shield", "oscar health",
      "insurance", "insur prem",
    ],
  },
  {
    name: "Personal Care", icon: "💆", color: "#ec4899",
    keywords: [
      "salon", "barbershop", "hair cut", "great clips", "supercuts",
      "massage envy", "hand & stone", "sephora", "ulta beauty",
      "bath body works", "lush", "spa",
    ],
  },
  {
    name: "Education", icon: "📚", color: "#6366f1",
    keywords: [
      "tuition", "student loan", "sallie mae", "navient", "fedloan",
      "udemy", "coursera", "skillshare", "linkedin learning",
      "masterclass", "duolingo", "chegg",
      "university", "college", "school fee",
    ],
  },
  {
    name: "Savings", icon: "📈", color: "#22c55e",
    keywords: [
      "vanguard", "fidelity", "schwab", "td ameritrade", "e*trade",
      "robinhood", "wealthfront", "betterment", "sofi invest",
      "savings transfer", "401k", "ira contribution",
    ],
  },
] as const;

function nextUnusedColor(existingCategories: BudgetCategory[]): string {
  const used = new Set(existingCategories.map((c) => c.color).filter(Boolean));
  return COLORS.find((c) => !used.has(c)) ?? COLORS[0];
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchCategories(): Promise<BudgetCategory[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories`);
  if (!res.ok) throw new Error("Failed to load categories");
  return res.json() as Promise<BudgetCategory[]>;
}

async function createCategory(body: {
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
}): Promise<BudgetCategory> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to create category");
  return res.json() as Promise<BudgetCategory>;
}

async function updateCategory(
  id: string,
  body: Partial<{ name: string; color: string | null; icon: string | null; keywords: string[] | null }>
): Promise<BudgetCategory> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update category");
  return res.json() as Promise<BudgetCategory>;
}

async function deleteCategory(id: string): Promise<void> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete category");
}

// ── Color swatch ──────────────────────────────────────────────────────────────

function ColorPicker({
  value,
  onChange,
}: {
  value: string | null;
  onChange: (c: string) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {COLORS.map((c) => (
        <button
          key={c}
          type="button"
          onClick={() => onChange(c)}
          className={cn(
            "w-5 h-5 rounded-full border-2 transition-transform",
            value === c ? "border-foreground scale-110" : "border-transparent hover:scale-105"
          )}
          style={{ backgroundColor: c }}
        />
      ))}
    </div>
  );
}

// ── Category row ──────────────────────────────────────────────────────────────

function CategoryRow({
  category,
  onDeleted,
  onUpdated,
  onNavigate,
}: {
  category: BudgetCategory;
  onDeleted: (id: string) => void;
  onUpdated: (cat: BudgetCategory) => void;
  onNavigate: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [color, setColor] = useState<string | null>(category.color);
  const [icon, setIcon] = useState(category.icon ?? "");
  const [keywordsRaw, setKeywordsRaw] = useState((category.keywords ?? []).join(", "));
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) nameRef.current?.focus();
  }, [editing]);

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const keywords = keywordsRaw
        .split(",")
        .map((k) => k.trim())
        .filter(Boolean);
      const updated = await updateCategory(category.id, {
        name: name.trim(),
        color: color || null,
        icon: icon.trim() || null,
        keywords: keywords.length > 0 ? keywords : null,
      });
      onUpdated(updated);
      setEditing(false);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteCategory(category.id);
      onDeleted(category.id);
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  };

  if (editing) {
    return (
      <div className="border rounded-lg p-4 flex flex-col gap-3">
        <div className="grid grid-cols-[1fr_auto] gap-3">
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground">Name</Label>
            <Input
              ref={nameRef}
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") void handleSave(); if (e.key === "Escape") setEditing(false); }}
              className="h-8 text-sm"
            />
          </div>
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground">Icon</Label>
            <Input
              value={icon}
              onChange={(e) => setIcon(e.target.value)}
              placeholder="🛒"
              className="h-8 text-sm w-16 text-center"
            />
          </div>
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Color</Label>
          <ColorPicker value={color} onChange={setColor} />
        </div>

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">
            Keywords <span className="text-muted-foreground/60">(comma-separated, used for auto-categorization)</span>
          </Label>
          <Input
            value={keywordsRaw}
            onChange={(e) => setKeywordsRaw(e.target.value)}
            placeholder="e.g. walmart, kroger, whole foods"
            className="h-8 text-sm"
          />
        </div>

        <div className="flex gap-2">
          <Button size="sm" onClick={() => void handleSave()} disabled={saving || !name.trim()}>
            {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Check className="w-3 h-3 mr-1" />}
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={() => {
            setName(category.name);
            setColor(category.color);
            setIcon(category.icon ?? "");
            setKeywordsRaw((category.keywords ?? []).join(", "));
            setEditing(false);
          }}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 border rounded-lg group overflow-hidden">
      {/* Clickable left area → navigate to detail page */}
      <button
        onClick={() => onNavigate(category.id)}
        className="flex items-center gap-3 flex-1 min-w-0 px-4 py-3 text-left hover:bg-muted/50 transition-colors"
      >
        {/* Color + icon */}
        <div
          className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-sm"
          style={{ backgroundColor: category.color ?? "#94a3b8" }}
        >
          {category.icon ?? ""}
        </div>

        {/* Name + keywords */}
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{category.name}</p>
          {category.keywords && category.keywords.length > 0 && (
            <p className="text-xs text-muted-foreground truncate">
              {category.keywords.slice(0, 5).join(", ")}
              {category.keywords.length > 5 ? ` +${category.keywords.length - 5} more` : ""}
            </p>
          )}
        </div>

        <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/40 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
      </button>

      {/* Edit / delete actions */}
      <div className="flex items-center gap-1 pr-3 opacity-0 group-hover:opacity-100 transition-opacity">
        {confirmDelete ? (
          <>
            <span className="text-xs text-muted-foreground mr-1">Delete?</span>
            <Button size="icon-xs" variant="destructive" onClick={() => void handleDelete()} disabled={deleting}>
              {deleting ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
            </Button>
            <Button size="icon-xs" variant="ghost" onClick={() => setConfirmDelete(false)}>
              <X className="w-3 h-3" />
            </Button>
          </>
        ) : (
          <>
            <Button size="icon-xs" variant="ghost" onClick={() => setEditing(true)}>
              <Pencil className="w-3 h-3" />
            </Button>
            <Button
              size="icon-xs"
              variant="ghost"
              className="text-muted-foreground hover:text-destructive"
              onClick={() => setConfirmDelete(true)}
            >
              <Trash2 className="w-3 h-3" />
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Create form ───────────────────────────────────────────────────────────────

function CreateCategoryForm({
  onCreated,
  existingCategories,
}: {
  onCreated: (cat: BudgetCategory) => void;
  existingCategories: BudgetCategory[];
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(COLORS[0]);
  const [icon, setIcon] = useState("");
  const [keywordsRaw, setKeywordsRaw] = useState("");
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) nameRef.current?.focus();
  }, [open]);

  const handleOpen = () => {
    setColor(nextUnusedColor(existingCategories));
    setOpen(true);
  };

  const handleCreate = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const keywords = keywordsRaw.split(",").map((k) => k.trim()).filter(Boolean);
      const cat = await createCategory({
        name: name.trim(),
        color: color || null,
        icon: icon.trim() || null,
        keywords: keywords.length > 0 ? keywords : null,
      });
      onCreated(cat);
      setName("");
      setIcon("");
      setKeywordsRaw("");
      setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  if (!open) {
    return (
      <button
        onClick={handleOpen}
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors py-2"
      >
        <Plus className="w-4 h-4" /> New category
      </button>
    );
  }

  return (
    <div className="border rounded-lg p-4 flex flex-col gap-3">
      <div className="grid grid-cols-[1fr_auto] gap-3">
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Name</Label>
          <Input
            ref={nameRef}
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void handleCreate(); if (e.key === "Escape") setOpen(false); }}
            placeholder="e.g. Groceries"
            className="h-8 text-sm"
          />
        </div>
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Icon</Label>
          <Input
            value={icon}
            onChange={(e) => setIcon(e.target.value)}
            placeholder="🛒"
            className="h-8 text-sm w-16 text-center"
          />
        </div>
      </div>

      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">Color</Label>
        <ColorPicker value={color} onChange={setColor} />
      </div>

      <div className="flex flex-col gap-1">
        <Label className="text-xs text-muted-foreground">
          Keywords <span className="text-muted-foreground/60">(comma-separated)</span>
        </Label>
        <Input
          value={keywordsRaw}
          onChange={(e) => setKeywordsRaw(e.target.value)}
          placeholder="e.g. walmart, kroger, whole foods"
          className="h-8 text-sm"
        />
      </div>

      <div className="flex gap-2">
        <Button size="sm" onClick={() => void handleCreate()} disabled={saving || !name.trim()}>
          {saving ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
          Create
        </Button>
        <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function BudgetCategoriesPage() {
  const router = useRouter();
  const qc = useQueryClient();

  const { data, isLoading } = useQuery<BudgetCategory[]>({
    queryKey: ["budget", "categories"],
    queryFn: fetchCategories,
  });

  const [categories, setCategories] = useState<BudgetCategory[] | null>(null);
  const [seedingDefaults, setSeedingDefaults] = useState(false);
  const display = categories ?? data ?? [];

  // Keep local state in sync with query data on first load
  useEffect(() => {
    if (data && categories === null) setCategories(data);
  }, [data, categories]);

  const handleCreated = (cat: BudgetCategory) => {
    setCategories((prev) => [...(prev ?? []), cat]);
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
  };

  const handleUpdated = (cat: BudgetCategory) => {
    setCategories((prev) => prev?.map((c) => (c.id === cat.id ? cat : c)) ?? null);
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
  };

  const handleDeleted = (id: string) => {
    setCategories((prev) => prev?.filter((c) => c.id !== id) ?? null);
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
  };

  const handleSeedDefaults = async () => {
    setSeedingDefaults(true);
    const existingNames = new Set(display.map((c) => c.name.toLowerCase()));
    const toCreate = DEFAULT_CATEGORIES.filter(
      (d) => !existingNames.has(d.name.toLowerCase())
    );
    try {
      for (const def of toCreate) {
        const cat = await createCategory({
          name: def.name,
          color: def.color,
          icon: def.icon,
          keywords: "keywords" in def ? [...def.keywords] : null,
        });
        setCategories((prev) => [...(prev ?? []), cat]);
      }
      void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
    } finally {
      setSeedingDefaults(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">
      <div className="flex items-center gap-3 mb-6">
        <Button size="icon-sm" variant="ghost" onClick={() => router.push("/budget")}>
          <ChevronLeft className="w-4 h-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold">Categories</h1>
          <p className="text-xs text-muted-foreground">
            Add keywords to auto-categorize imported transactions.
          </p>
        </div>
        <Button
          size="sm"
          variant="outline"
          onClick={() => void handleSeedDefaults()}
          disabled={seedingDefaults || isLoading}
          className="text-xs shrink-0"
        >
          {seedingDefaults ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
          Load defaults
        </Button>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : display.length === 0 && categories !== null ? (
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <Tag className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No categories yet.</p>
          <p className="text-xs text-muted-foreground">
            Use <strong>Load defaults</strong> to seed standard categories, or create one below.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2 mb-4">
          {display.map((cat) => (
            <CategoryRow
              key={cat.id}
              category={cat}
              onDeleted={handleDeleted}
              onUpdated={handleUpdated}
              onNavigate={(id) => router.push(`/budget/categories/${id}`)}
            />
          ))}

          {/* Uncategorized shortcut — always shown so users can find unassigned transactions */}
          <button
            onClick={() => router.push("/budget/categories/uncategorized")}
            className="flex items-center gap-3 border rounded-lg px-4 py-3 text-left hover:bg-muted/50 transition-colors group"
          >
            <div className="w-7 h-7 rounded-full flex items-center justify-center shrink-0 text-sm bg-muted">
              <Tag className="w-3.5 h-3.5 text-muted-foreground" />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-sm font-medium text-muted-foreground">Uncategorized</p>
              <p className="text-xs text-muted-foreground/70">View transactions without a category</p>
            </div>
            <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/40 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
          </button>
        </div>
      )}

      <CreateCategoryForm onCreated={handleCreated} existingCategories={display} />
    </div>
  );
}
