"use client";

import { Laptop, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dropdown, DropdownContent, DropdownItem, DropdownTrigger } from "@/components/ui/overlay";

export function ThemeToggle() {
  const { theme, setTheme, resolvedTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  // eslint-disable-next-line react-hooks/set-state-in-effect -- standard next-themes hydration guard
  useEffect(() => setMounted(true), []);
  const Icon = !mounted ? Sun : resolvedTheme === "dark" ? Moon : Sun;
  const options = [
    { value: "light", label: "Light", icon: Sun },
    { value: "dark", label: "Dark", icon: Moon },
    { value: "system", label: "System", icon: Laptop },
  ];
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <Button variant="ghost" size="icon" aria-label="Change theme">
          <Icon />
        </Button>
      </DropdownTrigger>
      <DropdownContent className="min-w-36">
        {options.map(({ value, label, icon: ItemIcon }) => (
          <DropdownItem key={value} onSelect={() => setTheme(value)} aria-checked={theme === value} role="menuitemradio">
            <ItemIcon />
            {label}
            {mounted && theme === value && <span className="ml-auto text-primary-600">•</span>}
          </DropdownItem>
        ))}
      </DropdownContent>
    </Dropdown>
  );
}
