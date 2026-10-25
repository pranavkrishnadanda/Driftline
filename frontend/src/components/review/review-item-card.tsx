"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import type { ResolveRequest, ReviewItem } from "@/lib/api/client";
import { describeItem, editBody } from "@/lib/review/queue";
import { cn } from "@/lib/utils";

export type Resolution = Pick<ResolveRequest, "action" | "edit">;

export interface ReviewItemCardProps {
  item: ReviewItem;
  highlighted?: boolean;
  onResolve: (item: ReviewItem, resolution: Resolution) => void;
}

const DATE_FORMAT = new Intl.DateTimeFormat("en-GB", {
  day: "numeric",
  month: "short",
  year: "numeric",
  timeZone: "UTC",
});

function formatDay(iso: string): string {
  const at = Date.parse(iso);
  return Number.isNaN(at) ? iso : DATE_FORMAT.format(at);
}

const TONE: Record<"changed" | "broken" | "brand", string> = {
  changed: "bg-changed-soft text-changed",
  broken: "bg-broken-soft text-broken",
  brand: "bg-brand-soft text-brand",
};

export function ReviewItemCard({ item, highlighted = false, onResolve }: ReviewItemCardProps) {
  const view = describeItem(item);
  const headingId = useId();
  const editorId = useId();
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(view.edit?.initial ?? "");
  const editButton = useRef<HTMLButtonElement>(null);
  const textEditor = useRef<HTMLTextAreaElement>(null);
  const kindEditor = useRef<HTMLSelectElement>(null);

  /** Return focus to the Edit button once a cancelled editor has closed. */
  const refocusEdit = useRef(false);

  useEffect(() => {
    if (editing) {
      (textEditor.current ?? kindEditor.current)?.focus();
    } else if (refocusEdit.current) {
      refocusEdit.current = false;
      editButton.current?.focus();
    }
  }, [editing]);

  const startEdit = () => {
    setValue(view.edit?.initial ?? "");
    setEditing(true);
  };
  const cancelEdit = () => {
    refocusEdit.current = true;
    setEditing(false);
  };
  const onEditorKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape") {
      event.preventDefault();
      cancelEdit();
    }
  };

  const canSave = value.trim().length > 0;
  const save = () => {
    if (!canSave) return;
    onResolve(item, { action: "edit", edit: editBody(item, value) });
  };

  return (
    <article
      aria-labelledby={headingId}
      data-item-id={item.id}
      tabIndex={-1}
      className={cn(
        "flex flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-xs outline-none",
        "focus-visible:ring-2 focus-visible:ring-ring",
        highlighted && "ring-2 ring-primary/60",
      )}
    >
      <header className="flex flex-col gap-1.5">
        <span
          className={cn(
            "inline-flex w-fit items-center rounded-full px-2 py-0.5 text-xs font-medium",
            TONE[view.status.tone],
          )}
        >
          {view.status.label}
        </span>
        <h3 id={headingId} className="font-heading text-base font-semibold">
          {view.title}
        </h3>
        <p className="text-xs text-muted-foreground">
          Added <time dateTime={item.created_at}>{formatDay(item.created_at)}</time>
        </p>
      </header>

      <p className="text-sm text-muted-foreground">{view.status.next}</p>

      {view.body ? (
        <p className="rounded-md bg-muted/50 p-3 text-sm whitespace-pre-wrap">{view.body}</p>
      ) : null}

      {view.facts.length ? (
        <dl className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
          {view.facts.map((fact) => (
            <div key={fact.label} className="flex gap-1">
              <dt className="text-muted-foreground">{fact.label}</dt>
              <dd className="font-medium">{fact.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}

      {editing && view.edit ? (
        <form
          className="flex flex-col gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            save();
          }}
        >
          <label htmlFor={editorId} className="text-sm font-medium">
            {view.edit.field === "kind" ? "Relation kind" : "Corrected answer"}
          </label>
          {view.edit.field === "kind" ? (
            <select
              id={editorId}
              ref={kindEditor}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={onEditorKeyDown}
              className="h-8 w-fit rounded-lg border border-input bg-transparent px-2 text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {view.edit.options.map((kind) => (
                <option key={kind} value={kind}>
                  {kind}
                </option>
              ))}
            </select>
          ) : (
            <Textarea
              id={editorId}
              ref={textEditor}
              value={value}
              onChange={(event) => setValue(event.target.value)}
              onKeyDown={onEditorKeyDown}
              rows={4}
            />
          )}
          <div className="flex gap-2">
            <Button type="submit" size="sm" disabled={!canSave}>
              Save edit
            </Button>
            <Button type="button" variant="ghost" size="sm" onClick={cancelEdit}>
              Cancel
            </Button>
          </div>
        </form>
      ) : (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onResolve(item, { action: "approve" })}>
            Approve
          </Button>
          {view.edit ? (
            <Button ref={editButton} variant="outline" size="sm" onClick={startEdit}>
              Edit
            </Button>
          ) : null}
          <Button
            variant="destructive"
            size="sm"
            onClick={() => onResolve(item, { action: "reject" })}
          >
            Reject
          </Button>
        </div>
      )}
    </article>
  );
}
