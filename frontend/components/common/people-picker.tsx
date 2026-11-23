"use client";

import { Check, Search, X } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { Input } from "@/components/ui/form";
import { Avatar } from "@/components/ui/primitives";
import { $api } from "@/lib/api/client";
import { cn } from "@/lib/utils";

export type Person = { id: string; full_name: string; email: string };

/** Searchable multi-select over the company directory. */
export function PeoplePicker({
  value,
  onChange,
  single,
  label = "People",
  exclude = [],
}: {
  value: Person[];
  onChange: (people: Person[]) => void;
  single?: boolean;
  label?: string;
  exclude?: string[];
}) {
  const [search, setSearch] = useState("");
  const query = useDeferredValue(search);
  const directory = $api.useQuery("get", "/api/v1/org/directory/", {
    params: { query: { search: query || undefined, page_size: 8 } },
  });
  const selected = new Set(value.map((p) => p.id));
  const toggle = (p: Person) => {
    if (single) return onChange(selected.has(p.id) ? [] : [p]);
    onChange(selected.has(p.id) ? value.filter((v) => v.id !== p.id) : [...value, p]);
  };
  const options = (directory.data?.results ?? []).filter((p) => !exclude.includes(p.id) && p.status === "ACTIVE");
  return (
    <div className="flex flex-col gap-2">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label={`Selected ${label.toLowerCase()}`}>
          {value.map((p) => (
            <li key={p.id} className="flex items-center gap-1 rounded-full bg-primary-100 py-0.5 pr-1 pl-2.5 text-sm font-semibold text-primary-700">
              {p.full_name}
              <button
                type="button"
                className="grid size-6 place-items-center rounded-full hover:bg-primary-200"
                aria-label={`Remove ${p.full_name}`}
                onClick={() => toggle(p)}
              >
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-placeholder" aria-hidden />
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search by name or email"
          className="pl-9"
          aria-label={`Search ${label.toLowerCase()}`}
        />
      </div>
      <ul className="max-h-52 overflow-y-auto rounded-xl border border-line" role="listbox" aria-multiselectable={!single}>
        {options.length === 0 && <li className="px-3 py-3 text-sm text-muted">No matches.</li>}
        {options.map((p) => (
          <li key={p.id} role="option" aria-selected={selected.has(p.id)}>
            <button
              type="button"
              onClick={() => toggle(p)}
              className={cn("flex min-h-11 w-full items-center gap-3 px-3 text-left hover:bg-hover", selected.has(p.id) && "bg-primary-50")}
            >
              <Avatar name={p.full_name} className="size-7" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-semibold text-ink">{p.full_name}</span>
                <span className="block truncate text-xs text-muted">{p.email}</span>
              </span>
              {selected.has(p.id) && <Check className="size-4 text-primary-600" />}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
