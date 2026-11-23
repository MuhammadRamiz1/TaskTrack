"use client";

import { useQueryClient } from "@tanstack/react-query";
import { FileSpreadsheet, Upload } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogFooter } from "@/components/ui/overlay";
import { Badge, type Tone } from "@/components/ui/primitives";
import { uploadFile } from "@/lib/api/client";
import { errorMessage } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

type ImportResult = components["schemas"]["EmployeeImportOutput"];
type RowStatus = ImportResult["rows"][number]["status"];

const PREVIEW_URL = "/api/v1/hr/employees/import/preview/";
const IMPORT_URL = "/api/v1/hr/employees/import/";
const STATUS: Record<RowStatus, { label: string; tone: Tone }> = {
  ready: { label: "Ready", tone: "info" },
  error: { label: "Skipped", tone: "danger" },
  created: { label: "Invited", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};

function Summary({ result, done }: { result: ImportResult; done: boolean }) {
  const s = result.summary;
  const tooMany = !done && s.ready > s.seats_available;
  return (
    <div className="flex flex-col gap-2 text-sm">
      <p className="text-ink">
        {done
          ? <><b>{s.created}</b> invited · <b>{s.error + s.failed}</b> skipped of {s.total} rows</>
          : <><b>{s.ready}</b> ready to invite · <b>{s.error}</b> with problems · {s.total} rows</>}
      </p>
      {tooMany && (
        <p className="rounded-lg bg-danger-soft px-3 py-2 text-danger">
          Only {s.seats_available} seats are free on your plan. Remove rows or raise the user limit before importing.
        </p>
      )}
    </div>
  );
}

function RowsTable({ rows }: { rows: ImportResult["rows"] }) {
  return (
    <div className="max-h-80 overflow-auto rounded-lg border border-line">
      <table className="w-full text-sm">
        <caption className="sr-only">Rows in the uploaded sheet</caption>
        <thead className="sticky top-0 bg-surface">
          <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
            <th scope="col" className="px-3 py-2">Row</th>
            <th scope="col" className="px-3 py-2">Email</th>
            <th scope="col" className="px-3 py-2">Name</th>
            <th scope="col" className="px-3 py-2">Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.row} className="border-b border-line align-top last:border-0">
              <td className="px-3 py-2 tabular-nums text-muted">{r.row}</td>
              <td className="px-3 py-2 text-ink">{r.email || "—"}</td>
              <td className="px-3 py-2">{[r.first_name, r.last_name].filter(Boolean).join(" ") || "—"}</td>
              <td className="px-3 py-2">
                <Badge tone={STATUS[r.status].tone}>{STATUS[r.status].label}</Badge>
                {r.errors.length > 0 && <p className="mt-1 text-xs text-danger">{r.errors.join(" ")}</p>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Upload a sheet of emails, preview every row, then create the valid ones. Each new
 * employee gets the normal invite email and sets their own password from the link.
 */
export function EmployeeImportDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<ImportResult | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [busy, setBusy] = useState(false);

  const check = async (f: File) => {
    setFile(f);
    setPreview(null);
    setBusy(true);
    try {
      setPreview(await uploadFile(PREVIEW_URL, f));
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!file) return;
    setBusy(true);
    try {
      const res: ImportResult = await uploadFile(IMPORT_URL, file);
      setResult(res);
      void qc.invalidateQueries({ queryKey: ["get", "/api/v1/hr/employees/"] });
      toast.success(`${res.summary.created} invite${res.summary.created === 1 ? "" : "s"} sent`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const shown = result ?? preview;
  const canImport = !!preview && !result && preview.summary.ready > 0
    && preview.summary.ready <= preview.summary.seats_available;

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent wide title="Import employees from a sheet"
                     description="Each new employee gets an invite email and sets their own password from the link.">
        <div className="flex flex-col gap-4">
          {!result && (
            <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-line p-6 text-center hover:bg-surface-2">
              <FileSpreadsheet className="size-6 text-muted" aria-hidden />
              <span className="text-sm font-semibold text-ink">{file ? file.name : "Choose a .xlsx or .csv file"}</span>
              <span className="text-xs text-muted">
                First row is the header. <b>email</b> is required; <b>first_name</b>, <b>last_name</b> and <b>job_title</b> are
                optional. Up to 500 rows.
              </span>
              <input type="file" className="sr-only" accept=".xlsx,.csv" disabled={busy}
                     onChange={(e) => { const f = e.target.files?.[0]; if (f) void check(f); e.target.value = ""; }} />
            </label>
          )}
          {busy && !shown && <p className="text-sm text-muted">Checking the sheet…</p>}
          {shown && (
            <>
              <Summary result={shown} done={!!result} />
              <RowsTable rows={shown.rows} />
            </>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>{result ? "Done" : "Cancel"}</Button>
          {!result && (
            <Button disabled={!canImport || busy} onClick={() => void run()}>
              <Upload /> {preview ? `Invite ${preview.summary.ready}` : "Invite"}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
