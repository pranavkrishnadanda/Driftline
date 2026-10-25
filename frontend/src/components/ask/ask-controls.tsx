"use client";

import { CalendarIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Calendar } from "@/components/ui/calendar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatDate, toAsOfParam } from "@/lib/ask/format";

export function TenantSelect({
  tenants,
  value,
  onChange,
}: {
  tenants: string[];
  value: string;
  onChange: (tenant: string) => void;
}) {
  return (
    <Select
      value={value}
      onValueChange={(next) => {
        if (typeof next === "string") onChange(next);
      }}
    >
      <SelectTrigger aria-label="Tenant" size="sm" className="rounded-full">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {tenants.map((tenant) => (
          <SelectItem key={tenant} value={tenant}>
            {tenant}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

/** The as-of date picker. `null` means "today" (the gateway's default). */
export function AsOfPicker({
  value,
  onChange,
}: {
  value: Date | null;
  onChange: (date: Date | null) => void;
}) {
  const [open, setOpen] = useState(false);
  // Read the clock when the picker opens, never during render (prerendering forbids it).
  const [today, setToday] = useState<Date | null>(null);
  const label = value ? formatDate(toAsOfParam(value)!) : "Today";
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        if (next) setToday(new Date());
        setOpen(next);
      }}
    >
      <PopoverTrigger
        render={
          <Button variant="outline" size="sm" className="rounded-full font-normal">
            <CalendarIcon aria-hidden="true" />
            <span>
              <span className="text-muted-foreground">As of </span>
              {label}
            </span>
          </Button>
        }
      />
      <PopoverContent align="start" side="top" className="w-auto p-0">
        <Calendar
          mode="single"
          selected={value ?? undefined}
          defaultMonth={value ?? undefined}
          captionLayout="dropdown"
          disabled={today ? { after: today } : undefined}
          onSelect={(date) => {
            onChange(date ?? null);
            setOpen(false);
          }}
        />
        <div className="border-t border-border p-2">
          <Button
            variant="ghost"
            size="sm"
            className="w-full"
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
          >
            Use today
          </Button>
        </div>
      </PopoverContent>
    </Popover>
  );
}
