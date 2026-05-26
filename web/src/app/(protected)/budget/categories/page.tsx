"use client";

import { useState, useRef, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiBaseUrl } from "@/lib/api/client";
import { fetchWithAuth } from "@/lib/api/fetch-with-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  ChevronLeft, ChevronRight, ChevronDown, ChevronUp,
  Plus, Pencil, Trash2, Check, X, Loader2, Tag, Layers,
} from "lucide-react";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

interface BudgetCategoryGroup {
  id: string;
  name: string;
  sort_order: number;
  is_income: boolean;
}

interface BudgetCategory {
  id: string;
  name: string;
  color: string | null;
  icon: string | null;
  keywords: string[] | null;
  default_scope: "private" | "shared";
  sort_order: number;
  group_id: string | null;
  default_monthly_amount: number | null;
  rollover_enabled: boolean;
  notify_threshold_pct: number | null;
}

interface GroupWithCategories {
  id: string | null;   // null = implicit "Other" bucket
  name: string;
  sort_order: number;
  is_income: boolean;
  categories: BudgetCategory[];
}

// ── Preset palette ────────────────────────────────────────────────────────────

const COLORS = [
  // Reds / oranges / yellows
  "#ef4444", "#f97316", "#f59e0b", "#eab308", "#84cc16", "#22c55e",
  // Teals / blues / purples
  "#14b8a6", "#06b6d4", "#3b82f6", "#6366f1", "#8b5cf6", "#a855f7",
  // Pinks / roses / warm browns
  "#ec4899", "#f43f5e", "#db2777", "#b45309", "#92400e", "#78716c",
  // Extras
  "#059669", "#0d9488", "#0ea5e9", "#a3e635", "#64748b", "#475569",
];

// ── Default categories (for the "Load defaults" seed button) ──────────────────

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
      "comcast", "xfinity", "spectrum", "cox communications",
      "at&t", "verizon wireless", "t-mobile", "sprint",
      "frontier", "centurylink", "lumen",
    ],
  },
  {
    name: "Groceries", icon: "🛒", color: "#3b82f6",
    keywords: [
      "wegmans", "kroger", "safeway", "whole foods", "trader joe",
      "aldi", "publix", "heb", "meijer", "jewel osco", "stop shop",
      "giant food", "harris teeter", "sprouts", "fresh market",
      "food lion", "winn dixie", "market basket", "price chopper",
      "hannaford", "shoprite", "albertsons", "vons", "ralphs",
      "stater bros", "winco", "save mart", "fresco",
      "costco", "sam's club", "bj's wholesale",
      "instacart", "shipt", "amazon fresh", "walmart grocery",
      "grocery", "supermarket", "food market",
    ],
  },
  {
    name: "Dining", icon: "🍽️", color: "#f97316",
    keywords: [
      "mcdonald", "burger king", "wendy's", "taco bell", "chick-fil-a",
      "chick fil a", "five guys", "shake shack", "in-n-out", "sonic drive",
      "jack in the box", "whataburger", "culver", "raising cane",
      "popeyes", "kfc", "wingstop", "zaxby",
      "chipotle", "panera", "subway", "jimmy john", "jersey mike",
      "firehouse subs", "potbelly", "panda express", "noodles",
      "sweetgreen", "cava", "mod pizza",
      "starbucks", "dunkin", "dutch bros", "caribou coffee",
      "tim hortons", "peet's coffee", "scooter's coffee",
      "domino", "pizza hut", "papa john", "little caesars",
      "doordash", "grubhub", "ubereats", "uber eats", "seamless",
      "postmates", "caviar",
      "olive garden", "applebee's", "outback", "chili's",
      "cheesecake factory", "buffalo wild wings", "texas roadhouse",
      "red lobster", "red robin", "denny's", "ihop", "cracker barrel",
      "first watch", "perkins",
      "restaurant", "ristorante", "bistro", "cafe", "diner", "grill",
      "sushi", "ramen", "pizzeria", "taqueria", "brasserie",
    ],
  },
  {
    name: "Transportation", icon: "🚗", color: "#8b5cf6",
    keywords: [
      "uber", "lyft",
      "shell", "bp station", "exxon", "chevron", "sunoco",
      "speedway", "marathon", "circle k", "wawa", "sheetz",
      "casey's", "pilot travel", "flying j", "loves travel",
      "quiktrip", "kwik trip", "racetrac",
      "parking", "park plus", "spothero", "parkwhiz",
      "e-zpass", "sunpass", "fastrak", "pikepass",
      "jiffy lube", "valvoline", "midas", "firestone", "goodyear",
      "pep boys", "autozone", "o'reilly auto", "advance auto",
      "napa auto", "car wash",
      "mbta", "mta", "septa", "bart", "wmata", "cta transit",
      "metro card", "clipper card", "ventra",
    ],
  },
  {
    name: "Travel", icon: "✈️", color: "#14b8a6",
    keywords: [
      "delta air", "united air", "american air", "southwest air",
      "jetblue", "alaska air", "spirit air", "frontier air",
      "air canada", "british air", "lufthansa",
      "marriott", "hilton", "hyatt", "ihg hotel", "wyndham",
      "best western", "holiday inn", "hampton inn", "courtyard",
      "fairfield inn", "sheraton", "westin", "doubletree",
      "four seasons", "ritz carlton", "kimpton",
      "amtrak",
      "enterprise rent", "hertz", "avis car", "budget car", "alamo",
      "national car", "sixt car", "turo",
      "expedia", "booking.com", "airbnb", "vrbo", "hotels.com",
      "kayak", "priceline", "orbitz",
    ],
  },
  {
    name: "Subscriptions", icon: "📱", color: "#a3e635",
    keywords: [
      "netflix", "hulu", "disney plus", "disney+", "hbo max",
      "peacock", "paramount+", "apple tv", "youtube premium",
      "amazon prime video", "espn+", "discovery+", "showtime",
      "sling", "fubo", "philo",
      "spotify", "apple music", "tidal", "pandora",
      "amazon music", "youtube music", "deezer",
      "xbox game pass", "playstation plus", "nintendo switch online",
      "steam", "epic games",
      "adobe", "microsoft 365", "google workspace", "google one",
      "dropbox", "icloud storage", "zoom", "slack",
      "notion", "figma", "github", "1password", "lastpass",
      "nordvpn", "expressvpn",
      "new york times", "nyt", "washington post", "wall street journal",
      "wsj", "economist", "bloomberg", "spotify podcast",
      "audible", "kindle unlimited",
      "peloton", "noom", "calm", "headspace", "whoop",
    ],
  },
  {
    name: "Shopping", icon: "🛍️", color: "#0ea5e9",
    keywords: [
      "amazon", "walmart.com", "target.com", "wayfair", "chewy",
      "etsy", "ebay", "wish.com", "shein", "temu", "shopify",
      "walmart", "target", "dollar general", "dollar tree",
      "five below", "big lots",
      "best buy", "apple store", "apple.com", "microsoft store",
      "b&h photo", "adorama", "newegg",
      "home depot", "lowe's", "ikea", "williams sonoma",
      "pottery barn", "restoration hardware", "crate barrel",
      "bed bath", "tuesday morning",
      "tj maxx", "marshalls", "ross stores", "burlington coat",
      "nordstrom", "macy's", "jcpenney", "kohls", "gap", "old navy",
      "banana republic", "h&m", "zara", "uniqlo",
      "petsmart", "petco",
    ],
  },
  {
    name: "Healthcare", icon: "🏥", color: "#ef4444",
    keywords: [
      "walgreens", "cvs pharmacy", "rite aid", "duane reade",
      "express scripts", "optum rx", "caremark",
      "dental", "dentist", "orthodont", "vision", "lenscrafters",
      "pearle vision", "america's best",
      "planet fitness", "la fitness", "24 hour fitness", "equinox",
      "anytime fitness", "ymca", "crunch fitness",
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
  {
    name: "Household", icon: "🛋️", color: "#b45309",
    keywords: [
      "home depot", "lowe's", "ikea", "wayfair", "target", "bed bath",
      "furniture", "hardware store", "paint", "home improvement",
    ],
  },
  {
    name: "Gifts", icon: "🎁", color: "#db2777",
    keywords: [
      "gift", "amazon gift", "etsy", "1-800-flowers", "hallmark",
      "birthday", "anniversary", "holiday", "donation", "charity",
    ],
  },
] as const;

// ── Helpers ───────────────────────────────────────────────────────────────────

function nextUnusedColor(existingCategories: BudgetCategory[]): string {
  const used = new Set(existingCategories.map((c) => c.color).filter(Boolean));
  return COLORS.find((c) => !used.has(c)) ?? COLORS[0];
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function fetchGrouped(): Promise<GroupWithCategories[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories/grouped`);
  if (!res.ok) throw new Error("Failed to load categories");
  return res.json() as Promise<GroupWithCategories[]>;
}

async function fetchGroups(): Promise<BudgetCategoryGroup[]> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/category-groups`);
  if (!res.ok) throw new Error("Failed to load groups");
  return res.json() as Promise<BudgetCategoryGroup[]>;
}

async function createGroup(name: string): Promise<BudgetCategoryGroup> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/category-groups`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, sort_order: 999 }),
  });
  if (!res.ok) throw new Error("Failed to create group");
  return res.json() as Promise<BudgetCategoryGroup>;
}

async function updateGroup(id: string, body: { name?: string; sort_order?: number; is_income?: boolean }): Promise<BudgetCategoryGroup> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/category-groups/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error("Failed to update group");
  return res.json() as Promise<BudgetCategoryGroup>;
}

async function deleteGroup(id: string): Promise<void> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/category-groups/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete group");
}

async function seedDefaultGroups(): Promise<{ groups_created: number; categories_assigned: number }> {
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/category-groups/seed-defaults`, { method: "POST" });
  if (!res.ok) throw new Error("Failed to seed groups");
  return res.json();
}

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
  group_id?: string | null;
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
  body: Partial<{ name: string; color: string | null; icon: string | null; keywords: string[] | null; group_id: string | null; default_monthly_amount: number | null; rollover_enabled: boolean; notify_threshold_pct: number | null }>
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
  const res = await fetchWithAuth(`${apiBaseUrl}/budget/categories/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete category");
}

// ── ColorPicker ───────────────────────────────────────────────────────────────

function ColorPicker({ value, onChange }: { value: string | null; onChange: (c: string) => void }) {
  const isCustom = value != null && !COLORS.includes(value);
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
      {/* Custom color picker — native input styled as a swatch */}
      <label
        title="Custom color"
        className={cn(
          "w-5 h-5 rounded-full border-2 cursor-pointer transition-transform overflow-hidden flex items-center justify-center",
          isCustom ? "border-foreground scale-110" : "border-dashed border-muted-foreground hover:scale-105"
        )}
        style={isCustom ? { backgroundColor: value! } : undefined}
      >
        {!isCustom && (
          <span className="text-[9px] text-muted-foreground leading-none">+</span>
        )}
        <input
          type="color"
          value={value ?? "#000000"}
          onChange={(e) => onChange(e.target.value)}
          className="sr-only"
        />
      </label>
    </div>
  );
}

// ── CategoryRow ───────────────────────────────────────────────────────────────

function CategoryRow({
  category,
  groups,
  onDeleted,
  onUpdated,
  onNavigate,
}: {
  category: BudgetCategory;
  groups: BudgetCategoryGroup[];
  onDeleted: (id: string) => void;
  onUpdated: (cat: BudgetCategory) => void;
  onNavigate: (id: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [color, setColor] = useState<string | null>(category.color);
  const [icon, setIcon] = useState(category.icon ?? "");
  const [keywordsRaw, setKeywordsRaw] = useState((category.keywords ?? []).join(", "));
  const [groupId, setGroupId] = useState<string | null>(category.group_id);
  const [monthlyAmount, setMonthlyAmount] = useState(
    category.default_monthly_amount != null ? String(category.default_monthly_amount) : ""
  );
  const [rolloverEnabled, setRolloverEnabled] = useState(category.rollover_enabled);
  const [alertsEnabled, setAlertsEnabled] = useState(category.notify_threshold_pct != null);
  const [alertThreshold, setAlertThreshold] = useState(
    category.notify_threshold_pct != null ? String(category.notify_threshold_pct) : "80"
  );
  const [saving, setSaving] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editing) nameRef.current?.focus(); }, [editing]);

  const handleSave = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const keywords = keywordsRaw.split(",").map((k) => k.trim()).filter(Boolean);
      const parsedAmount = monthlyAmount.trim() !== "" ? parseFloat(monthlyAmount) : null;
      const parsedThreshold = parseInt(alertThreshold, 10);
      const updated = await updateCategory(category.id, {
        name: name.trim(),
        color: color || null,
        icon: icon.trim() || null,
        keywords: keywords.length > 0 ? keywords : null,
        group_id: groupId,
        default_monthly_amount: parsedAmount != null && !isNaN(parsedAmount) ? parsedAmount : null,
        rollover_enabled: rolloverEnabled,
        notify_threshold_pct: alertsEnabled && !isNaN(parsedThreshold) && parsedThreshold > 0 && parsedThreshold < 100
          ? parsedThreshold
          : alertsEnabled ? 80 : null,
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
      <div className="border rounded-lg p-4 flex flex-col gap-3 ml-4">
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

        {groups.length > 0 && (
          <div className="flex flex-col gap-1">
            <Label className="text-xs text-muted-foreground">Group</Label>
            <select
              value={groupId ?? ""}
              onChange={(e) => setGroupId(e.target.value || null)}
              className="h-8 text-sm rounded-md border border-input bg-background px-2 text-foreground"
            >
              <option value="">— No group —</option>
              {groups.map((g) => (
                <option key={g.id} value={g.id}>{g.name}</option>
              ))}
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">
            Monthly budget <span className="text-muted-foreground/60">(optional — leave blank for no target)</span>
          </Label>
          <div className="relative w-36">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">$</span>
            <Input
              type="number"
              min="0"
              step="1"
              value={monthlyAmount}
              onChange={(e) => setMonthlyAmount(e.target.value)}
              placeholder="0"
              className="h-8 text-sm pl-6"
            />
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="button"
            role="switch"
            aria-checked={rolloverEnabled}
            onClick={() => setRolloverEnabled(!rolloverEnabled)}
            className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
              rolloverEnabled ? "bg-primary" : "bg-input"
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg transition-transform ${
                rolloverEnabled ? "translate-x-4" : "translate-x-0"
              }`}
            />
          </button>
          <div className="flex flex-col">
            <Label className="text-xs font-medium">Roll over balance</Label>
            <span className="text-xs text-muted-foreground">Carry unspent or overspent amount to next month</span>
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-3">
            <button
              type="button"
              role="switch"
              aria-checked={alertsEnabled}
              onClick={() => setAlertsEnabled(!alertsEnabled)}
              className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none ${
                alertsEnabled ? "bg-primary" : "bg-input"
              }`}
            >
              <span
                className={`pointer-events-none inline-block h-4 w-4 rounded-full bg-white shadow-lg transition-transform ${
                  alertsEnabled ? "translate-x-4" : "translate-x-0"
                }`}
              />
            </button>
            <div className="flex flex-col">
              <Label className="text-xs font-medium">Budget alerts</Label>
              <span className="text-xs text-muted-foreground">Notify when spending approaches the monthly target</span>
            </div>
          </div>
          {alertsEnabled && (
            <div className="flex items-center gap-2 ml-12">
              <span className="text-xs text-muted-foreground">Alert at</span>
              <div className="relative w-20">
                <Input
                  type="number"
                  min="1"
                  max="99"
                  step="1"
                  value={alertThreshold}
                  onChange={(e) => setAlertThreshold(e.target.value)}
                  className="h-7 text-sm pr-6 text-center"
                />
                <span className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">%</span>
              </div>
              <span className="text-xs text-muted-foreground">of budget (always again at 100%)</span>
            </div>
          )}
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
            setGroupId(category.group_id);
            setMonthlyAmount(category.default_monthly_amount != null ? String(category.default_monthly_amount) : "");
            setRolloverEnabled(category.rollover_enabled);
            setAlertsEnabled(category.notify_threshold_pct != null);
            setAlertThreshold(category.notify_threshold_pct != null ? String(category.notify_threshold_pct) : "80");
            setEditing(false);
          }}>
            Cancel
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 border rounded-lg group overflow-hidden ml-4">
      <button
        onClick={() => onNavigate(category.id)}
        className="flex items-center gap-3 flex-1 min-w-0 px-4 py-3 text-left hover:bg-muted/50 transition-colors"
      >
        <div
          className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-sm"
          style={{ backgroundColor: category.color ?? "#94a3b8" }}
        >
          {category.icon ?? ""}
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium">{category.name}</p>
          {category.keywords && category.keywords.length > 0 && (
            <p className="text-xs text-muted-foreground truncate">
              {category.keywords.slice(0, 5).join(", ")}
              {category.keywords.length > 5 ? ` +${category.keywords.length - 5} more` : ""}
            </p>
          )}
        </div>
        {category.default_monthly_amount != null && (
          <span className="text-xs tabular-nums text-muted-foreground shrink-0 mr-1">
            ${category.default_monthly_amount.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 })}/mo
          </span>
        )}
        {category.rollover_enabled && (
          <span className="text-xs text-muted-foreground shrink-0 mr-1" title="Balance rolls over each month">↩</span>
        )}
        <ChevronRight className="w-3.5 h-3.5 text-muted-foreground/40 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity" />
      </button>

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

// ── GroupSection ──────────────────────────────────────────────────────────────

function GroupSection({
  group,
  groups,
  allCategories,
  onCategoryDeleted,
  onCategoryUpdated,
  onNavigate,
  onGroupRenamed,
  onGroupIsIncomeToggled,
  onGroupDeleted,
}: {
  group: GroupWithCategories;
  groups: BudgetCategoryGroup[];
  allCategories: BudgetCategory[];
  onCategoryDeleted: (id: string) => void;
  onCategoryUpdated: (cat: BudgetCategory) => void;
  onNavigate: (id: string) => void;
  onGroupRenamed: (id: string, name: string) => void;
  onGroupIsIncomeToggled: (id: string, is_income: boolean) => void;
  onGroupDeleted: (id: string) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const [editingName, setEditingName] = useState(false);
  const [nameValue, setNameValue] = useState(group.name);
  const [savingName, setSavingName] = useState(false);
  const [confirmDeleteGroup, setConfirmDeleteGroup] = useState(false);
  const [deletingGroup, setDeletingGroup] = useState(false);
  const [togglingIncome, setTogglingIncome] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (editingName) nameRef.current?.focus(); }, [editingName]);

  const isOther = group.id === null;

  const handleSaveName = async () => {
    if (!nameValue.trim() || isOther || !group.id) return;
    setSavingName(true);
    try {
      await updateGroup(group.id, { name: nameValue.trim() });
      onGroupRenamed(group.id, nameValue.trim());
      setEditingName(false);
    } finally {
      setSavingName(false);
    }
  };

  const handleToggleIncome = async () => {
    if (isOther || !group.id) return;
    setTogglingIncome(true);
    try {
      await updateGroup(group.id, { is_income: !group.is_income });
      onGroupIsIncomeToggled(group.id, !group.is_income);
    } finally {
      setTogglingIncome(false);
    }
  };

  const handleDeleteGroup = async () => {
    if (!group.id) return;
    setDeletingGroup(true);
    try {
      await deleteGroup(group.id);
      onGroupDeleted(group.id);
    } finally {
      setDeletingGroup(false);
      setConfirmDeleteGroup(false);
    }
  };

  return (
    <div className="flex flex-col gap-1">
      {/* Group header */}
      <div className="flex items-center gap-2 group/grp py-1">
        <button
          onClick={() => setCollapsed((v) => !v)}
          className="flex items-center gap-1.5 flex-1 min-w-0 text-left"
        >
          {collapsed
            ? <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
            : <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
          }

          {editingName && !isOther ? (
            <Input
              ref={nameRef}
              value={nameValue}
              onChange={(e) => setNameValue(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") void handleSaveName();
                if (e.key === "Escape") { setNameValue(group.name); setEditingName(false); }
              }}
              className="h-6 text-sm font-semibold py-0 px-1 max-w-[180px]"
              onClick={(e) => e.stopPropagation()}
            />
          ) : (
            <span className="text-sm font-semibold text-muted-foreground uppercase tracking-wide">
              {group.name}
            </span>
          )}

          <span className="text-xs text-muted-foreground/60 ml-1">
            ({group.categories.length})
          </span>
        </button>

        {/* Group actions — only for real groups, not "Other" */}
        {!isOther && (
          <div className="flex items-center gap-1 opacity-0 group-hover/grp:opacity-100 transition-opacity">
            {editingName ? (
              <>
                <Button size="icon-xs" variant="ghost" onClick={() => void handleSaveName()} disabled={savingName}>
                  {savingName ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                </Button>
                <Button size="icon-xs" variant="ghost" onClick={() => { setNameValue(group.name); setEditingName(false); }}>
                  <X className="w-3 h-3" />
                </Button>
              </>
            ) : confirmDeleteGroup ? (
              <>
                <span className="text-xs text-muted-foreground">Delete group?</span>
                <Button size="icon-xs" variant="destructive" onClick={() => void handleDeleteGroup()} disabled={deletingGroup}>
                  {deletingGroup ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
                </Button>
                <Button size="icon-xs" variant="ghost" onClick={() => setConfirmDeleteGroup(false)}>
                  <X className="w-3 h-3" />
                </Button>
              </>
            ) : (
              <>
                <button
                  title={group.is_income ? "Marked as income group — click to unmark" : "Mark as income group"}
                  onClick={() => void handleToggleIncome()}
                  disabled={togglingIncome}
                  className={`text-xs px-1.5 py-0.5 rounded font-medium transition-colors ${
                    group.is_income
                      ? "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-400"
                      : "text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {togglingIncome ? <Loader2 className="w-3 h-3 animate-spin inline" /> : "Income"}
                </button>
                <Button size="icon-xs" variant="ghost" onClick={() => setEditingName(true)}>
                  <Pencil className="w-3 h-3" />
                </Button>
                <Button
                  size="icon-xs"
                  variant="ghost"
                  className="text-muted-foreground hover:text-destructive"
                  onClick={() => setConfirmDeleteGroup(true)}
                >
                  <Trash2 className="w-3 h-3" />
                </Button>
              </>
            )}
          </div>
        )}
      </div>

      {/* Categories */}
      {!collapsed && (
        <div className="flex flex-col gap-1.5 mb-2">
          {group.categories.length === 0 ? (
            <p className="text-xs text-muted-foreground/50 ml-5 italic py-1">No categories in this group</p>
          ) : (
            group.categories.map((cat) => (
              <CategoryRow
                key={cat.id}
                category={cat}
                groups={groups}
                onDeleted={onCategoryDeleted}
                onUpdated={onCategoryUpdated}
                onNavigate={onNavigate}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}

// ── CreateCategoryForm ────────────────────────────────────────────────────────

function CreateCategoryForm({
  onCreated,
  allCategories,
  groups,
  defaultGroupId,
}: {
  onCreated: (cat: BudgetCategory) => void;
  allCategories: BudgetCategory[];
  groups: BudgetCategoryGroup[];
  defaultGroupId?: string | null;
}) {
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(COLORS[0]);
  const [icon, setIcon] = useState("");
  const [keywordsRaw, setKeywordsRaw] = useState("");
  const [groupId, setGroupId] = useState<string | null>(defaultGroupId ?? null);
  const [saving, setSaving] = useState(false);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => { if (open) nameRef.current?.focus(); }, [open]);

  const handleOpen = () => {
    setColor(nextUnusedColor(allCategories));
    setGroupId(defaultGroupId ?? null);
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
        group_id: groupId,
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
        className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors py-2 ml-5"
      >
        <Plus className="w-4 h-4" /> New category
      </button>
    );
  }

  return (
    <div className="border rounded-lg p-4 flex flex-col gap-3 ml-4">
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

      {groups.length > 0 && (
        <div className="flex flex-col gap-1">
          <Label className="text-xs text-muted-foreground">Group</Label>
          <select
            value={groupId ?? ""}
            onChange={(e) => setGroupId(e.target.value || null)}
            className="h-8 text-sm rounded-md border border-input bg-background px-2 text-foreground"
          >
            <option value="">— No group —</option>
            {groups.map((g) => (
              <option key={g.id} value={g.id}>{g.name}</option>
            ))}
          </select>
        </div>
      )}

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

  // Flat categories list (for flat category operations & "Load defaults" seeding)
  const { data: flatData, isLoading: flatLoading } = useQuery<BudgetCategory[]>({
    queryKey: ["budget", "categories"],
    queryFn: fetchCategories,
  });

  // Grouped view
  const { data: groupedData, isLoading: groupedLoading } = useQuery<GroupWithCategories[]>({
    queryKey: ["budget", "categories", "grouped"],
    queryFn: fetchGrouped,
  });

  // Flat group list (for the group picker dropdowns)
  const { data: groupsData } = useQuery<BudgetCategoryGroup[]>({
    queryKey: ["budget", "category-groups"],
    queryFn: fetchGroups,
  });

  const isLoading = flatLoading || groupedLoading;
  const allCategories = flatData ?? [];
  const groups = groupsData ?? [];
  const [grouped, setGrouped] = useState<GroupWithCategories[] | null>(null);
  const display = grouped ?? groupedData ?? [];
  const hasGroups = display.some((g) => g.id !== null);

  useEffect(() => {
    if (groupedData && grouped === null) setGrouped(groupedData);
  }, [groupedData, grouped]);

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["budget", "categories"] });
    void qc.invalidateQueries({ queryKey: ["budget", "category-groups"] });
  };

  const handleCategoryUpdated = (cat: BudgetCategory) => {
    setGrouped(null);  // trigger re-fetch to re-group
    invalidate();
  };

  const handleCategoryDeleted = (id: string) => {
    setGrouped(null);
    invalidate();
  };

  const handleGroupRenamed = (id: string, name: string) => {
    setGrouped((prev) =>
      prev?.map((g) => (g.id === id ? { ...g, name } : g)) ?? null
    );
  };

  const handleGroupIsIncomeToggled = (id: string, is_income: boolean) => {
    setGrouped((prev) =>
      prev?.map((g) => (g.id === id ? { ...g, is_income } : g)) ?? null
    );
  };

  const handleGroupDeleted = (id: string) => {
    setGrouped(null);
    invalidate();
  };

  const handleCategoryCreated = () => {
    setGrouped(null);
    invalidate();
  };

  // "Load defaults" — seeds categories only (legacy behaviour)
  const [seedingDefaults, setSeedingDefaults] = useState(false);
  const handleSeedDefaults = async () => {
    setSeedingDefaults(true);
    const existingNames = new Set(allCategories.map((c) => c.name.toLowerCase()));
    const toCreate = DEFAULT_CATEGORIES.filter(
      (d) => !existingNames.has(d.name.toLowerCase())
    );
    try {
      for (const def of toCreate) {
        await createCategory({
          name: def.name,
          color: def.color,
          icon: def.icon,
          keywords: [...def.keywords],
          group_id: null,
        });
      }
      setGrouped(null);
      invalidate();
    } finally {
      setSeedingDefaults(false);
    }
  };

  // "Set up groups" — creates default groups + assigns matching categories
  const [seedingGroups, setSeedingGroups] = useState(false);
  const handleSeedGroups = async () => {
    setSeedingGroups(true);
    try {
      await seedDefaultGroups();
      setGrouped(null);
      invalidate();
    } finally {
      setSeedingGroups(false);
    }
  };

  // Create new group inline
  const [addingGroup, setAddingGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [savingGroup, setSavingGroup] = useState(false);
  const newGroupRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (addingGroup) newGroupRef.current?.focus(); }, [addingGroup]);

  const handleCreateGroup = async () => {
    if (!newGroupName.trim()) return;
    setSavingGroup(true);
    try {
      await createGroup(newGroupName.trim());
      setNewGroupName("");
      setAddingGroup(false);
      setGrouped(null);
      invalidate();
    } finally {
      setSavingGroup(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto py-6 px-4">
      {/* Header */}
      <div className="flex items-center gap-3 mb-6">
        <Button size="icon-sm" variant="ghost" onClick={() => router.push("/budget")}>
          <ChevronLeft className="w-4 h-4" />
        </Button>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-semibold">Categories</h1>
          <p className="text-xs text-muted-foreground">
            Organise spending categories into groups for zero-based budgeting.
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {!hasGroups && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => void handleSeedGroups()}
              disabled={seedingGroups || isLoading}
              className="text-xs"
            >
              {seedingGroups ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : <Layers className="w-3 h-3 mr-1" />}
              Set up groups
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => void handleSeedDefaults()}
            disabled={seedingDefaults || isLoading}
            className="text-xs"
          >
            {seedingDefaults ? <Loader2 className="w-3 h-3 animate-spin mr-1" /> : null}
            Load defaults
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> Loading…
        </div>
      ) : display.length === 0 && !hasGroups && allCategories.length === 0 ? (
        /* Truly empty state */
        <div className="flex flex-col items-center gap-3 py-12 text-center">
          <Tag className="w-8 h-8 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">No categories yet.</p>
          <p className="text-xs text-muted-foreground">
            Use <strong>Set up groups</strong> to scaffold the default YNAB-style layout,
            or <strong>Load defaults</strong> to seed categories without groups.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-2 mb-4">
          {/* Grouped sections */}
          {display.map((group) => (
            <GroupSection
              key={group.id ?? "__other__"}
              group={group}
              groups={groups}
              allCategories={allCategories}
              onCategoryDeleted={handleCategoryDeleted}
              onCategoryUpdated={handleCategoryUpdated}
              onNavigate={(id) => router.push(`/budget/categories/${id}`)}
              onGroupRenamed={handleGroupRenamed}
              onGroupIsIncomeToggled={handleGroupIsIncomeToggled}
              onGroupDeleted={handleGroupDeleted}
            />
          ))}

          {/* Add new group inline */}
          {addingGroup ? (
            <div className="flex items-center gap-2 py-1">
              <Input
                ref={newGroupRef}
                value={newGroupName}
                onChange={(e) => setNewGroupName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void handleCreateGroup();
                  if (e.key === "Escape") { setAddingGroup(false); setNewGroupName(""); }
                }}
                placeholder="Group name…"
                className="h-7 text-sm max-w-[200px]"
              />
              <Button size="sm" onClick={() => void handleCreateGroup()} disabled={savingGroup || !newGroupName.trim()}>
                {savingGroup ? <Loader2 className="w-3 h-3 animate-spin" /> : <Check className="w-3 h-3" />}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => { setAddingGroup(false); setNewGroupName(""); }}>
                <X className="w-3 h-3" />
              </Button>
            </div>
          ) : (
            <button
              onClick={() => setAddingGroup(true)}
              className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors py-1 mt-1"
            >
              <Plus className="w-3.5 h-3.5" /> New group
            </button>
          )}

          {/* Uncategorized shortcut */}
          <button
            onClick={() => router.push("/budget/categories/uncategorized")}
            className="flex items-center gap-3 border rounded-lg px-4 py-3 text-left hover:bg-muted/50 transition-colors group mt-2"
          >
            <div className="w-6 h-6 rounded-full flex items-center justify-center shrink-0 text-sm bg-muted">
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

      {/* New category form — floated outside groups; users can also use the edit pencil to move to a group */}
      {!isLoading && (
        <CreateCategoryForm
          onCreated={handleCategoryCreated}
          allCategories={allCategories}
          groups={groups}
        />
      )}
    </div>
  );
}
