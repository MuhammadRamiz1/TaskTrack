"use client";

import { useState } from "react";

import { PeoplePicker, type Person } from "@/components/common/people-picker";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";

function PickerForm({
  label, single, confirmLabel, onCancel, onConfirm,
}: {
  label: string;
  single?: boolean;
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: (people: Person[]) => void;
}) {
  // Lives inside the dialog content, so the selection starts empty on every open.
  const [people, setPeople] = useState<Person[]>([]);
  return (
    <form onSubmit={(e) => { e.preventDefault(); if (people.length) onConfirm(people); }}>
      <PeoplePicker value={people} onChange={setPeople} single={single} label={label} />
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={!people.length}>{confirmLabel}</Button>
      </DialogFooter>
    </form>
  );
}

/** Pick who the task is assigned to; used when a card is dropped on Assigned. */
export function AssignDialog({
  taskKey, open, onCancel, onConfirm,
}: { taskKey: string; open: boolean; onCancel: () => void; onConfirm: (userIds: string[]) => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent title={`Assign ${taskKey}`} description="Choose who will work on this task.">
        <PickerForm label="Assignees" confirmLabel="Assign" onCancel={onCancel} onConfirm={(p) => onConfirm(p.map((x) => x.id))} />
      </DialogContent>
    </Dialog>
  );
}

/** Pick the reviewer when submitting a task that has none. */
export function ReviewerDialog({
  taskKey, open, onCancel, onConfirm,
}: { taskKey: string; open: boolean; onCancel: () => void; onConfirm: (reviewerId: string) => void }) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent title={`Choose a reviewer for ${taskKey}`} description="A reviewer is needed before the task can be submitted.">
        <PickerForm label="Reviewer" single confirmLabel="Submit for review" onCancel={onCancel} onConfirm={(p) => onConfirm(p[0].id)} />
      </DialogContent>
    </Dialog>
  );
}
