import {
  startTransition,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import {
  ArrowUpRight,
  CheckCircle,
  Download,
  FileCode2,
  FileText,
  FileX2,
  LoaderCircle,
  Sparkles,
  UploadCloud,
  XCircle,
} from "lucide-react";

type ConvertMeta = {
  reportType: string;
  eventClassification: string;
  mfrRef: string;
  ncaReportNo: string;
  brandName: string;
  serviceId: string;
  payloadType: string;
};

type ConvertResponse = {
  filename: string;
  xml: string;
  meta: ConvertMeta;
};

const PREVIEW_LINES = 40;

function App() {
  const [file, setFile] = useState<File | null>(null);
  const [response, setResponse] = useState<ConvertResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState("");
  const [isSummaryOpen, setIsSummaryOpen] = useState(false);
  const [summaryHtml, setSummaryHtml] = useState("");
  const [summaryError, setSummaryError] = useState("");
  const [isSummaryLoading, setIsSummaryLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!file) {
      setErrorMessage("Select an EUDAMED XML file first.");
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    setResponse(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const fetchResponse = await fetch("/api/convert", {
        method: "POST",
        body: formData,
      });

      if (!fetchResponse.ok) {
        const detail = await fetchResponse.text();
        let message = detail;
        try {
          message = JSON.parse(detail)?.detail ?? detail;
        } catch {
          // keep raw text
        }
        throw new Error(message || "Conversion failed.");
      }

      const payload = (await fetchResponse.json()) as ConvertResponse;
      startTransition(() => setResponse(payload));
    } catch (error) {
      setErrorMessage(
        error instanceof Error
          ? error.message
          : "Unexpected error during conversion.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  function downloadXml() {
    if (!response) return;
    const blob = new Blob([response.xml], {
      type: "application/xml;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = response.filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  async function openSummaryModal() {
    setIsSummaryOpen(true);

    if (summaryHtml || isSummaryLoading) {
      return;
    }

    setSummaryError("");
    setIsSummaryLoading(true);

    try {
      const fetchResponse = await fetch("/api/summary");
      if (!fetchResponse.ok) {
        const detail = await fetchResponse.text();
        throw new Error(detail || "Unable to load summary.");
      }
      setSummaryHtml(await fetchResponse.text());
    } catch (error) {
      setSummaryError(
        error instanceof Error ? error.message : "Unable to load summary.",
      );
    } finally {
      setIsSummaryLoading(false);
    }
  }

  const previewLines =
    response?.xml.split("\n").slice(0, PREVIEW_LINES).join("\n") ?? "";

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.9),_rgba(240,244,250,0.85)_35%,_rgba(224,234,245,0.9)_100%)] text-stone-900">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 py-6 sm:px-8 lg:px-10">
        {/* ── Header ── */}
        <header className="relative overflow-hidden rounded-[2rem] border border-stone-900/10 bg-stone-950 px-6 py-8 text-stone-50 shadow-[0_24px_80px_rgba(28,25,23,0.18)] sm:px-8 lg:px-10">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(56,189,248,0.28),_transparent_28%),radial-gradient(circle_at_bottom_left,_rgba(99,102,241,0.18),_transparent_34%)]" />
          <div className="relative grid gap-8 lg:grid-cols-[1.4fr_0.85fr] lg:items-end">
            <div className="space-y-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/8 px-3 py-1 text-xs uppercase tracking-[0.3em] text-sky-300">
                <Sparkles className="h-3.5 w-3.5" />
                EUDAMED Converter
              </div>
              <div className="max-w-3xl space-y-3">
                <h1 className="text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">
                  Convert EUDAMED DTX to MIR 7.3.1
                </h1>
                <p className="max-w-2xl text-sm leading-6 text-stone-300 sm:text-base">
                  Upload an EUDAMED Vigilance XML file (serviceID&nbsp;
                  <code className="rounded bg-white/10 px-1 py-0.5 font-mono text-sky-200">
                    VIG_DOSSIER
                  </code>
                  , payload&nbsp;
                  <code className="rounded bg-white/10 px-1 py-0.5 font-mono text-sky-200">
                    vig:mir_2Type
                  </code>
                  ) and download the MIR 7.3.1 draft immediately.
                </p>
              </div>
            </div>
            <div className="grid gap-3 rounded-[1.5rem] border border-white/10 bg-white/6 p-4 backdrop-blur">
              <StatPill
                label="File"
                value={file?.name ?? "No file selected"}
                icon={<FileCode2 className="h-4 w-4" />}
              />
              <StatPill
                label="Output"
                value={response?.filename ?? "Not converted yet"}
                icon={<Download className="h-4 w-4" />}
              />
              <StatPill
                label="Report type"
                value={response?.meta.reportType || "–"}
                icon={<CheckCircle className="h-4 w-4" />}
              />
            </div>
          </div>
        </header>

        {/* ── Main ── */}
        <main className="mt-6 grid gap-6 lg:grid-cols-[0.88fr_1.12fr]">
          {/* Upload panel */}
          <section className="rounded-[2rem] border border-stone-900/10 bg-white/75 p-5 shadow-[0_18px_55px_rgba(120,113,108,0.12)] backdrop-blur sm:p-6">
            <div className="mb-5">
              <p className="text-xs uppercase tracking-[0.25em] text-stone-500">
                Step 1
              </p>
              <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                Upload &amp; Convert
              </h2>
            </div>

            <form className="space-y-5" onSubmit={handleSubmit}>
              <FileDrop file={file} onChange={setFile} />

              {errorMessage ? (
                <div className="flex items-start gap-3 rounded-2xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700">
                  <XCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{errorMessage}</span>
                </div>
              ) : null}

              <button
                type="submit"
                className="inline-flex w-full items-center justify-center gap-2 rounded-[1.25rem] bg-stone-950 px-5 py-4 text-sm font-medium text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-400"
                disabled={isSubmitting || !file}
              >
                {isSubmitting ? (
                  <LoaderCircle className="h-4 w-4 animate-spin" />
                ) : (
                  <Sparkles className="h-4 w-4" />
                )}
                {isSubmitting ? "Converting…" : "Convert to MIR 7.3.1"}
              </button>
            </form>
          </section>

          {/* Result panel */}
          <section className="space-y-5">
            {/* Meta cards */}
            {response ? (
              <div className="grid gap-4 sm:grid-cols-3">
                <MetaCard
                  label="Report type"
                  value={response.meta.reportType}
                  accent="sky"
                />
                <MetaCard
                  label="Classification"
                  value={response.meta.eventClassification}
                  accent="amber"
                />
                <MetaCard
                  label="Brand / trade name"
                  value={response.meta.brandName || "Not available in source"}
                  accent="stone"
                />
              </div>
            ) : (
              <div className="grid gap-4 sm:grid-cols-3">
                <MetaCard label="Report type" value="–" accent="sky" />
                <MetaCard label="Classification" value="–" accent="amber" />
                <MetaCard label="Brand / trade name" value="–" accent="stone" />
              </div>
            )}

            {/* XML preview + download */}
            <div className="rounded-[2rem] border border-stone-900/10 bg-white/75 p-5 shadow-[0_18px_55px_rgba(120,113,108,0.12)] backdrop-blur sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.25em] text-stone-500">
                    Step 2
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">
                    Review &amp; Download
                  </h2>
                </div>
                {response ? (
                  <button
                    type="button"
                    onClick={downloadXml}
                    className="inline-flex items-center justify-center gap-2 rounded-[1.1rem] bg-stone-950 px-5 py-3 text-sm font-medium text-white transition hover:bg-stone-800"
                  >
                    <Download className="h-4 w-4" />
                    Download {response.filename}
                  </button>
                ) : null}
              </div>

              {!response ? (
                <div className="mt-6 flex flex-col items-center gap-3 rounded-[1.5rem] border border-dashed border-stone-300 bg-stone-50/80 p-10 text-center text-stone-500">
                  <FileX2 className="h-8 w-8 opacity-30" />
                  <span className="text-sm">
                    Upload a file and click Convert to preview the MIR 7.3.1
                    output here.
                  </span>
                </div>
              ) : (
                <div className="mt-5 space-y-3">
                  {/* Info row */}
                  <div className="flex flex-wrap gap-3 text-xs text-stone-500">
                    <InfoBadge
                      label="NCA report no."
                      value={response.meta.ncaReportNo}
                    />
                    <InfoBadge label="MFR ref." value={response.meta.mfrRef} />
                    <InfoBadge
                      label="Service"
                      value={response.meta.serviceId}
                    />
                    <InfoBadge
                      label="Payload type"
                      value={response.meta.payloadType}
                    />
                  </div>
                  {/* XML preview */}
                  <div className="rounded-[1.5rem] border border-stone-900/10 bg-stone-950 p-4">
                    <p className="mb-2 text-[0.65rem] uppercase tracking-[0.22em] text-stone-500">
                      XML preview — first {PREVIEW_LINES} lines
                    </p>
                    <pre className="overflow-x-auto whitespace-pre font-mono text-[0.72rem] leading-5 text-stone-200 max-h-[26rem] overflow-y-auto">
                      {previewLines}
                    </pre>
                  </div>
                </div>
              )}
            </div>
          </section>
        </main>

        {/* ── Footer ── */}
        <footer className="mt-6 flex flex-col gap-3 rounded-[1.5rem] border border-stone-900/10 bg-white/60 px-5 py-4 text-sm text-stone-500 backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <span>
            Only{" "}
            <code className="rounded bg-stone-100 px-1 font-mono text-stone-700">
              VIG_DOSSIER
            </code>{" "}
            /{" "}
            <code className="rounded bg-stone-100 px-1 font-mono text-stone-700">
              vig:mir_2Type
            </code>{" "}
            files are supported. FSCA, FSN, MTR and other types will return an
            error.
          </span>
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={openSummaryModal}
              className="inline-flex items-center gap-2 rounded-[0.9rem] border border-stone-300 bg-white px-3 py-2 font-medium text-stone-900 transition hover:bg-stone-100"
            >
              <FileText className="h-4 w-4" />
              MIR Mapping Summary
            </button>
            <a
              className="inline-flex items-center gap-2 font-medium text-stone-900"
              href="https://www.eudamed.eu"
              target="_blank"
              rel="noreferrer"
            >
              EUDAMED Portal
              <ArrowUpRight className="h-4 w-4" />
            </a>
          </div>
        </footer>
      </div>

      {isSummaryOpen ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8">
          <button
            type="button"
            aria-label="Close summary"
            onClick={() => setIsSummaryOpen(false)}
            className="absolute inset-0 bg-stone-950/55"
          />
          <div className="relative z-10 h-[90vh] w-full max-w-6xl overflow-hidden rounded-[1.6rem] border border-stone-300 bg-white shadow-[0_30px_90px_rgba(0,0,0,0.35)]">
            <div className="flex items-center justify-between border-b border-stone-200 px-5 py-3 sm:px-6">
              <h3 className="text-base font-semibold tracking-[-0.02em] text-stone-900 sm:text-lg">
                EUDAMED to MIR 7.3.1 Summary
              </h3>
              <button
                type="button"
                onClick={() => setIsSummaryOpen(false)}
                className="rounded-lg border border-stone-300 px-3 py-1.5 text-sm font-medium text-stone-700 transition hover:bg-stone-100"
              >
                Close
              </button>
            </div>

            {isSummaryLoading ? (
              <div className="flex h-[calc(90vh-61px)] items-center justify-center gap-2 text-stone-600">
                <LoaderCircle className="h-4 w-4 animate-spin" />
                Loading summary...
              </div>
            ) : summaryError ? (
              <div className="m-5 rounded-xl border border-rose-300 bg-rose-50 p-4 text-sm text-rose-700 sm:m-6">
                {summaryError}
              </div>
            ) : (
              <iframe
                title="EUDAMED to MIR summary"
                className="h-[calc(90vh-61px)] w-full"
                srcDoc={summaryHtml}
              />
            )}
          </div>
        </div>
      ) : null}
    </div>
  );
}

/* ── Sub-components ── */

function FileDrop({
  file,
  onChange,
}: {
  file: File | null;
  onChange: (f: File | null) => void;
}) {
  return (
    <label className="group grid cursor-pointer gap-3 rounded-[1.5rem] border border-stone-900/10 bg-stone-50 p-4 transition hover:border-stone-900/25 hover:bg-stone-100">
      <input
        type="file"
        accept=".xml,application/xml,text/xml"
        className="hidden"
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-medium text-stone-900">EUDAMED XML file</div>
          <div className="mt-1 text-sm text-stone-500">
            Vigilance DTX export from EUDAMED portal
          </div>
        </div>
        <div className="rounded-2xl bg-white p-3 text-stone-600 shadow-sm transition group-hover:-translate-y-0.5">
          <UploadCloud className="h-5 w-5" />
        </div>
      </div>
      <div className="rounded-[1rem] border border-dashed border-stone-300 bg-white px-4 py-5 text-sm text-stone-500">
        {file ? (
          <div className="space-y-1">
            <div className="font-medium text-stone-900">{file.name}</div>
            <div>{(file.size / 1024).toFixed(1)} KB</div>
          </div>
        ) : (
          <div>Choose an XML file…</div>
        )}
      </div>
    </label>
  );
}

function MetaCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent: "sky" | "amber" | "stone";
}) {
  const tone = {
    sky: "from-sky-200/80 to-cyan-50",
    amber: "from-amber-200/80 to-orange-50",
    stone: "from-stone-200/90 to-stone-50",
  }[accent];
  return (
    <div
      className={`rounded-[1.5rem] border border-stone-900/10 bg-gradient-to-br ${tone} p-5 shadow-[0_14px_32px_rgba(120,113,108,0.12)]`}
    >
      <div className="text-xs uppercase tracking-[0.25em] text-stone-500">
        {label}
      </div>
      <div className="mt-3 text-lg font-semibold tracking-[-0.03em] text-stone-950 break-words">
        {value || "–"}
      </div>
    </div>
  );
}

function InfoBadge({ label, value }: { label: string; value: string }) {
  if (!value) return null;
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-3 py-1">
      <span className="text-stone-400">{label}:</span>
      <span className="font-medium text-stone-700">{value}</span>
    </span>
  );
}

function StatPill({
  label,
  value,
  icon,
}: {
  label: string;
  value: string;
  icon: ReactNode;
}) {
  return (
    <div className="flex items-center gap-3 rounded-[1.15rem] bg-black/12 px-3 py-3">
      <div className="rounded-xl bg-white/12 p-2 text-sky-300">{icon}</div>
      <div className="min-w-0">
        <div className="text-[0.68rem] uppercase tracking-[0.22em] text-stone-400">
          {label}
        </div>
        <div className="truncate text-sm font-medium text-stone-100">
          {value}
        </div>
      </div>
    </div>
  );
}

export default App;
