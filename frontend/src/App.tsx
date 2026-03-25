import { startTransition, useDeferredValue, useState, type FormEvent, type ReactNode } from 'react'
import { ArrowUpRight, FileSpreadsheet, FileText, LoaderCircle, ScanSearch, Search, Sparkles, UploadCloud } from 'lucide-react'

type ExtractedValue = {
  search_value: string
  source_page: number | null
}

type MatchRow = {
  search_value: string
  found: string
  pages: string
  page_count: number
  source_page: number | ''
}

type MatchResponse = {
  summary: {
    extractedCount: number
    matchedCount: number
    unmatchedCount: number
  }
  extractedValues: ExtractedValue[]
  results: MatchRow[]
  csv: string
}

const defaultColumn = 'sales sku'

function App() {
  const [sourceFile, setSourceFile] = useState<File | null>(null)
  const [targetFile, setTargetFile] = useState<File | null>(null)
  const [columnIdentifier, setColumnIdentifier] = useState(defaultColumn)
  const [valuePattern, setValuePattern] = useState('')
  const [exactMatch, setExactMatch] = useState(true)
  const [searchTerm, setSearchTerm] = useState('')
  const [response, setResponse] = useState<MatchResponse | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [errorMessage, setErrorMessage] = useState('')

  const deferredSearchTerm = useDeferredValue(searchTerm)
  const filteredResults = response?.results.filter((row) => {
    const needle = deferredSearchTerm.trim().toLowerCase()
    if (!needle) {
      return true
    }
    return [row.search_value, row.pages, row.found].some((value) => String(value).toLowerCase().includes(needle))
  })

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()

    if (!sourceFile || !targetFile) {
      setErrorMessage('Select both PDFs before running the match.')
      return
    }

    if (!columnIdentifier.trim()) {
      setErrorMessage('Enter a source column identifier.')
      return
    }

    setIsSubmitting(true)
    setErrorMessage('')

    const formData = new FormData()
    formData.append('source_pdf', sourceFile)
    formData.append('target_pdf', targetFile)
    formData.append('column_identifier', columnIdentifier)
    formData.append('value_pattern', valuePattern)
    formData.append('exact_match', String(exactMatch))

    try {
      const fetchResponse = await fetch('/api/match', {
        method: 'POST',
        body: formData,
      })

      if (!fetchResponse.ok) {
        const detail = await fetchResponse.text()
        throw new Error(detail || 'Matching request failed.')
      }

      const payload = (await fetchResponse.json()) as MatchResponse
      startTransition(() => {
        setResponse(payload)
      })
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : 'Unexpected error while processing PDFs.')
    } finally {
      setIsSubmitting(false)
    }
  }

  function downloadCsv() {
    if (!response) {
      return
    }
    const blob = new Blob([response.csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = 'pdf_match_results.csv'
    anchor.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="min-h-screen bg-[radial-gradient(circle_at_top_left,_rgba(255,255,255,0.9),_rgba(245,241,232,0.82)_35%,_rgba(227,232,241,0.9)_100%)] text-stone-900">
      <div className="mx-auto flex min-h-screen w-full max-w-7xl flex-col px-5 py-6 sm:px-8 lg:px-10">
        <header className="relative overflow-hidden rounded-[2rem] border border-stone-900/10 bg-stone-950 px-6 py-8 text-stone-50 shadow-[0_24px_80px_rgba(28,25,23,0.18)] sm:px-8 lg:px-10">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_right,_rgba(251,191,36,0.28),_transparent_28%),radial-gradient(circle_at_bottom_left,_rgba(56,189,248,0.18),_transparent_34%)]" />
          <div className="relative grid gap-8 lg:grid-cols-[1.35fr_0.9fr] lg:items-end">
            <div className="space-y-5">
              <div className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/8 px-3 py-1 text-xs uppercase tracking-[0.3em] text-amber-200">
                <Sparkles className="h-3.5 w-3.5" />
                PDF Comparison Studio
              </div>
              <div className="max-w-3xl space-y-3">
                <h1 className="text-4xl font-semibold tracking-[-0.05em] sm:text-5xl">Upload two PDFs, extract a column, and map every hit to its page.</h1>
                <p className="max-w-2xl text-sm leading-6 text-stone-300 sm:text-base">
                  Built for generic document pairs. Point to the source column header, upload the target PDF, and export a clean CSV of matches.
                </p>
              </div>
            </div>
            <div className="grid gap-3 rounded-[1.5rem] border border-white/10 bg-white/6 p-4 backdrop-blur">
              <StatPill label="Source" value={sourceFile?.name ?? 'No file yet'} icon={<FileSpreadsheet className="h-4 w-4" />} subtle />
              <StatPill label="Target" value={targetFile?.name ?? 'No file yet'} icon={<FileText className="h-4 w-4" />} subtle />
              <StatPill label="Column" value={columnIdentifier || 'Not set'} icon={<ScanSearch className="h-4 w-4" />} subtle />
            </div>
          </div>
        </header>

        <main className="mt-6 grid gap-6 lg:grid-cols-[0.92fr_1.08fr]">
          <section className="rounded-[2rem] border border-stone-900/10 bg-white/75 p-5 shadow-[0_18px_55px_rgba(120,113,108,0.12)] backdrop-blur sm:p-6">
            <div className="mb-5 flex items-center justify-between gap-4">
              <div>
                <p className="text-xs uppercase tracking-[0.25em] text-stone-500">Matcher Setup</p>
                <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">Configure the extraction</h2>
              </div>
            </div>

            <form className="space-y-5" onSubmit={handleSubmit}>
              <div className="grid gap-4 sm:grid-cols-2">
                <FileDrop
                  label="Source PDF"
                  hint="Table or list containing the values to extract"
                  file={sourceFile}
                  onChange={(file) => setSourceFile(file)}
                />
                <FileDrop
                  label="Target PDF"
                  hint="Document where the extracted values will be searched"
                  file={targetFile}
                  onChange={(file) => setTargetFile(file)}
                />
              </div>

              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="Source column identifier">
                  <input
                    className="input"
                    value={columnIdentifier}
                    onChange={(event) => setColumnIdentifier(event.target.value)}
                    placeholder="sales sku"
                  />
                </Field>
                <Field label="Optional value regex">
                  <input
                    className="input"
                    value={valuePattern}
                    onChange={(event) => setValuePattern(event.target.value)}
                    placeholder="[A-Z0-9._-]+"
                  />
                </Field>
              </div>

              <label className="flex items-center justify-between rounded-[1.25rem] border border-stone-900/10 bg-stone-50 px-4 py-3 text-sm">
                <div>
                  <div className="font-medium text-stone-900">Boundary-aware exact matching</div>
                  <div className="text-stone-500">Turn off to switch to plain substring matching for noisy documents.</div>
                </div>
                <button
                  type="button"
                  className={`relative h-8 w-14 rounded-full transition ${exactMatch ? 'bg-stone-950' : 'bg-stone-300'}`}
                  onClick={() => setExactMatch((value) => !value)}
                  aria-pressed={exactMatch}
                >
                  <span
                    className={`absolute top-1 h-6 w-6 rounded-full bg-white transition ${exactMatch ? 'left-7' : 'left-1'}`}
                  />
                </button>
              </label>

              {errorMessage ? <div className="rounded-2xl border border-rose-300 bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</div> : null}

              <button
                type="submit"
                className="inline-flex w-full items-center justify-center gap-2 rounded-[1.25rem] bg-stone-950 px-5 py-4 text-sm font-medium text-white transition hover:bg-stone-800 disabled:cursor-not-allowed disabled:bg-stone-400"
                disabled={isSubmitting}
              >
                {isSubmitting ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <ScanSearch className="h-4 w-4" />}
                {isSubmitting ? 'Processing PDFs...' : 'Run Match'}
              </button>
            </form>
          </section>

          <section className="space-y-6">
            <div className="grid gap-4 sm:grid-cols-3">
              <SummaryCard label="Extracted" value={response?.summary.extractedCount ?? 0} accent="amber" />
              <SummaryCard label="Matched" value={response?.summary.matchedCount ?? 0} accent="sky" />
              <SummaryCard label="Unmatched" value={response?.summary.unmatchedCount ?? 0} accent="stone" />
            </div>

            <div className="rounded-[2rem] border border-stone-900/10 bg-white/75 p-5 shadow-[0_18px_55px_rgba(120,113,108,0.12)] backdrop-blur sm:p-6">
              <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <p className="text-xs uppercase tracking-[0.25em] text-stone-500">Results</p>
                  <h2 className="mt-2 text-2xl font-semibold tracking-[-0.04em]">Review and export</h2>
                </div>
                <div className="flex flex-col gap-3 sm:flex-row">
                  <label className="relative min-w-[16rem]">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-400" />
                    <input
                      className="input pl-10"
                      value={searchTerm}
                      onChange={(event) => setSearchTerm(event.target.value)}
                      placeholder="Filter current results"
                    />
                  </label>
                  <button
                    type="button"
                    onClick={downloadCsv}
                    disabled={!response}
                    className="inline-flex items-center justify-center gap-2 rounded-[1.1rem] border border-stone-900/10 bg-stone-100 px-4 py-3 text-sm font-medium text-stone-900 transition hover:bg-stone-200 disabled:cursor-not-allowed disabled:text-stone-400"
                  >
                    <FileSpreadsheet className="h-4 w-4" />
                    Download CSV
                  </button>
                </div>
              </div>

              {!response ? (
                <div className="mt-6 rounded-[1.5rem] border border-dashed border-stone-300 bg-stone-50/80 p-8 text-center text-stone-500">
                  Run a match to preview extracted values and page hits here.
                </div>
              ) : (
                <div className="mt-6 grid gap-6 xl:grid-cols-[0.72fr_1.28fr]">
                  <div className="rounded-[1.5rem] border border-stone-900/10 bg-stone-50 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-stone-500">Extracted Values</h3>
                      <span className="text-xs text-stone-400">{response.extractedValues.length} rows</span>
                    </div>
                    <div className="max-h-[28rem] overflow-auto rounded-2xl border border-stone-200 bg-white">
                      <table className="min-w-full text-left text-sm">
                        <thead className="sticky top-0 bg-stone-100 text-xs uppercase tracking-[0.18em] text-stone-500">
                          <tr>
                            <th className="px-4 py-3">Value</th>
                            <th className="px-4 py-3">Source Page</th>
                          </tr>
                        </thead>
                        <tbody>
                          {response.extractedValues.slice(0, 400).map((item) => (
                            <tr key={`${item.search_value}-${item.source_page}`} className="border-t border-stone-100">
                              <td className="px-4 py-3 font-medium text-stone-900">{item.search_value}</td>
                              <td className="px-4 py-3 text-stone-500">{item.source_page ?? '-'}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  <div className="rounded-[1.5rem] border border-stone-900/10 bg-stone-50 p-4">
                    <div className="mb-3 flex items-center justify-between">
                      <h3 className="text-sm font-semibold uppercase tracking-[0.2em] text-stone-500">Match Table</h3>
                      <span className="text-xs text-stone-400">{filteredResults?.length ?? 0} visible rows</span>
                    </div>
                    <div className="max-h-[28rem] overflow-auto rounded-2xl border border-stone-200 bg-white">
                      <table className="min-w-full text-left text-sm">
                        <thead className="sticky top-0 bg-stone-100 text-xs uppercase tracking-[0.18em] text-stone-500">
                          <tr>
                            <th className="px-4 py-3">Value</th>
                            <th className="px-4 py-3">Found</th>
                            <th className="px-4 py-3">Pages</th>
                            <th className="px-4 py-3">Hits</th>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredResults?.map((row) => (
                            <tr key={`${row.search_value}-${row.pages}`} className="border-t border-stone-100 align-top">
                              <td className="px-4 py-3 font-medium text-stone-900">{row.search_value}</td>
                              <td className="px-4 py-3">
                                <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${row.found === 'yes' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'}`}>
                                  {row.found}
                                </span>
                              </td>
                              <td className="px-4 py-3 text-stone-500">{row.pages || '-'}</td>
                              <td className="px-4 py-3 text-stone-500">{row.page_count}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </section>
        </main>

        <footer className="mt-6 flex flex-col gap-3 rounded-[1.5rem] border border-stone-900/10 bg-white/60 px-5 py-4 text-sm text-stone-500 backdrop-blur sm:flex-row sm:items-center sm:justify-between">
          <span>Works best when the source PDF contains a recognizable table header.</span>
          <a className="inline-flex items-center gap-2 font-medium text-stone-900" href="https://vite.dev" target="_blank" rel="noreferrer">
            Built with Vite and FastAPI
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </footer>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="grid gap-2 text-sm">
      <span className="font-medium text-stone-700">{label}</span>
      {children}
    </label>
  )
}

function FileDrop({
  label,
  hint,
  file,
  onChange,
}: {
  label: string
  hint: string
  file: File | null
  onChange: (file: File | null) => void
}) {
  return (
    <label className="group grid cursor-pointer gap-3 rounded-[1.5rem] border border-stone-900/10 bg-stone-50 p-4 transition hover:border-stone-900/25 hover:bg-stone-100">
      <input
        type="file"
        accept="application/pdf"
        className="hidden"
        onChange={(event) => onChange(event.target.files?.[0] ?? null)}
      />
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="font-medium text-stone-900">{label}</div>
          <div className="mt-1 text-sm text-stone-500">{hint}</div>
        </div>
        <div className="rounded-2xl bg-white p-3 text-stone-600 shadow-sm transition group-hover:translate-y-[-2px]">
          <UploadCloud className="h-5 w-5" />
        </div>
      </div>
      <div className="rounded-[1rem] border border-dashed border-stone-300 bg-white px-4 py-5 text-sm text-stone-500">
        {file ? (
          <div className="space-y-1">
            <div className="font-medium text-stone-900">{file.name}</div>
            <div>{(file.size / 1024 / 1024).toFixed(2)} MB</div>
          </div>
        ) : (
          <div>Choose a PDF file</div>
        )}
      </div>
    </label>
  )
}

function SummaryCard({ label, value, accent }: { label: string; value: number; accent: 'amber' | 'sky' | 'stone' }) {
  const tone = {
    amber: 'from-amber-200/80 to-orange-50',
    sky: 'from-sky-200/80 to-cyan-50',
    stone: 'from-stone-200/90 to-stone-50',
  }[accent]

  return (
    <div className={`rounded-[1.5rem] border border-stone-900/10 bg-gradient-to-br ${tone} p-5 shadow-[0_14px_32px_rgba(120,113,108,0.12)]`}>
      <div className="text-xs uppercase tracking-[0.25em] text-stone-500">{label}</div>
      <div className="mt-4 text-4xl font-semibold tracking-[-0.05em] text-stone-950">{value}</div>
    </div>
  )
}

function StatPill({
  label,
  value,
  icon,
  subtle,
}: {
  label: string
  value: string
  icon: ReactNode
  subtle?: boolean
}) {
  return (
    <div className={`flex items-center gap-3 rounded-[1.15rem] px-3 py-3 ${subtle ? 'bg-black/12' : 'bg-black/20'}`}>
      <div className="rounded-xl bg-white/12 p-2 text-amber-200">{icon}</div>
      <div className="min-w-0">
        <div className="text-[0.68rem] uppercase tracking-[0.22em] text-stone-400">{label}</div>
        <div className="truncate text-sm font-medium text-stone-100">{value}</div>
      </div>
    </div>
  )
}

export default App