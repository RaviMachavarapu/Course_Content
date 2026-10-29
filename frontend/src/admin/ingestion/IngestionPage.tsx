import { type FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Button, Card, CardBody, Icon, Input, Select } from "@/components";
import { ApiError } from "@/lib/api";
import { GenerationOptionsEditor } from "../GenerationOptionsEditor";
import {
  DEFAULT_OPTIONS,
  optionsProblem,
  type OptionsByType,
  type PromptsByType,
} from "../generationOptions";
import { ARTIFACT_LABELS, ARTIFACT_TYPES, type ArtifactType } from "../api";
import { StatusChip, StatusDot } from "../AdminStatus";
import { SourceSummary } from "../SourceSummary";
import { sourceUrlError } from "../sourceValidation";
import { PdfPicker, type PickedFile } from "./PdfPicker";
import { uploadPdf } from "./chunkedUpload";
import {
  ModuleCreateError,
  useCourses,
  useIngest,
  useMcpStatus,
  useRecentPipeline,
} from "../useAdminApi";

type Target = "new" | "existing";

export function IngestionPage(): JSX.Element {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const scopedCourseId = searchParams.get("course") ?? "";
  const mcp = useMcpStatus();
  const courses = useCourses();
  const pipeline = useRecentPipeline(5);
  const ingest = useIngest();
  const urlRef = useRef<HTMLInputElement>(null);
  const focusForm = searchParams.get("focus") === "form";

  // BTN-IG1 (left nav "New Artifact") scrolls to / focuses the form
  useEffect(() => {
    if (focusForm) {
      urlRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
      urlRef.current?.focus();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusForm]);

  const [sourceUrl, setSourceUrl] = useState("");
  const [moduleTitle, setModuleTitle] = useState("");
  const [target, setTarget] = useState<Target>(scopedCourseId ? "existing" : "new");
  const [courseTitle, setCourseTitle] = useState("");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [existingCourseId, setExistingCourseId] = useState(scopedCourseId);
  const [types, setTypes] = useState<Set<ArtifactType>>(new Set(ARTIFACT_TYPES));
  const [optionsByType, setOptionsByType] = useState<OptionsByType>({ ...DEFAULT_OPTIONS });
  const [promptsByType, setPromptsByType] = useState<PromptsByType>({});
  const [pdfs, setPdfs] = useState<PickedFile[]>([]);
  const aborts = useRef(new Map<string, AbortController>());
  const queue = useRef<Promise<void>>(Promise.resolve());
  const nextId = useRef(0);
  const [submitted, setSubmitted] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const patchPdf = useCallback((id: string, patch: Partial<PickedFile>) => {
    setPdfs((prev) => prev.map((f) => (f.id === id ? { ...f, ...patch } : f)));
  }, []);

  // Uploads run one at a time, in the order the files were added.
  const startUpload = useCallback(
    (id: string, file: File) => {
      const ctrl = new AbortController();
      aborts.current.set(id, ctrl);
      queue.current = queue.current.then(async () => {
        if (ctrl.signal.aborted) return;
        try {
          const uploadId = await uploadPdf(
            file,
            (sent, total) => patchPdf(id, { sent, total }),
            ctrl.signal,
          );
          if (!ctrl.signal.aborted) patchPdf(id, { state: "done", uploadId, error: undefined });
        } catch (err) {
          if (ctrl.signal.aborted) return;
          patchPdf(id, {
            state: "error",
            error: err instanceof Error ? err.message : "Upload failed",
          });
        } finally {
          aborts.current.delete(id);
        }
      });
    },
    [patchPdf],
  );

  const addPdfs = (files: File[]) => {
    const added: PickedFile[] = files.map((file) => ({
      id: `pdf-${nextId.current++}`,
      file,
      sent: 0,
      total: file.size,
      state: "uploading",
    }));
    setPdfs((prev) => [...prev, ...added]);
    added.forEach((a) => startUpload(a.id, a.file));
  };

  const removePdf = (id: string) => {
    aborts.current.get(id)?.abort();
    setPdfs((prev) => prev.filter((f) => f.id !== id));
  };

  const retryPdf = (id: string) => {
    const f = pdfs.find((x) => x.id === id);
    if (!f) return;
    patchPdf(id, { state: "uploading", sent: 0, error: undefined });
    startUpload(id, f.file);
  };

  useEffect(() => {
    const pending = aborts.current;
    return () => pending.forEach((c) => c.abort());
  }, []);

  const uploadedIds = pdfs.flatMap((f) => (f.state === "done" && f.uploadId ? [f.uploadId] : []));
  const uploading = pdfs.filter((f) => f.state === "uploading").length;
  const trackedPdfs = pdfs.filter((f) => f.state !== "error").length;
  const urlErr = sourceUrlError(sourceUrl);
  const sourceErr =
    !sourceUrl.trim() && uploadedIds.length === 0 ? "Add a link or at least one PDF" : null;
  // A failed PDF must not be dropped silently: the admin retries or removes it first.
  const failedPdf = pdfs.find((f) => f.state === "error");
  const pdfErr = failedPdf ? `Retry or remove ${failedPdf.file.name}` : null;
  const moduleTitleErr = moduleTitle.trim() ? null : "Module title is required";
  const courseTitleErr =
    target === "new" && !courseTitle.trim() ? "Course title is required" : null;
  const courseSelectErr = target === "existing" && !existingCourseId ? "Choose a course" : null;
  const typesErr = types.size === 0 ? "Select at least one artifact type" : null;

  const optionProblems = new Map(
    [...types]
      .map((t) => [t, optionsProblem(t, optionsByType[t] ?? DEFAULT_OPTIONS[t])] as const)
      .filter((entry): entry is readonly [ArtifactType, string] => entry[1] !== null),
  );
  const isValid =
    !urlErr &&
    !sourceErr &&
    !pdfErr &&
    !moduleTitleErr &&
    !courseTitleErr &&
    !courseSelectErr &&
    !typesErr &&
    optionProblems.size === 0;

  const toggleType = (t: ArtifactType) =>
    setTypes((prev) => {
      const next = new Set(prev);
      if (next.has(t)) next.delete(t);
      else next.add(t);
      return next;
    });

  function onSubmit(e: FormEvent): void {
    e.preventDefault();
    setSubmitted(true);
    setFormError(null);
    if (!isValid || uploading > 0) return;

    const selectedOptions: OptionsByType = {};
    const selectedPrompts: PromptsByType = {};
    for (const t of types) {
      selectedOptions[t] = optionsByType[t] ?? DEFAULT_OPTIONS[t];
      const text = promptsByType[t]?.trim();
      if (text) selectedPrompts[t] = text;
    }

    ingest.mutate(
      {
        sourceUrl,
        uploadIds: uploadedIds,
        moduleTitle,
        types: [...types],
        options: selectedOptions,
        prompts: selectedPrompts,
        target:
          target === "new"
            ? { kind: "new", title: courseTitle, description, category }
            : { kind: "existing", courseId: existingCourseId },
      },
      {
        onSuccess: ({ moduleId }) => navigate(`/admin/modules/${moduleId}/staging`),
        onError: (err) => {
          const cause = err instanceof ModuleCreateError ? err.cause : err;
          const message =
            cause instanceof ApiError ? cause.message : "Could not start generation. Try again.";
          if (err instanceof ModuleCreateError) {
            // The course exists now: retry adds the module to it instead of
            // creating another empty course.
            setTarget("existing");
            setExistingCourseId(err.createdCourseId);
            setFormError(
              `${message} The course “${courseTitle}” was created — fix the problem and retry to add this module to it.`,
            );
            return;
          }
          setFormError(message);
        },
      },
    );
  }

  const courseOptions = useMemo(
    () => (courses.data ?? []).map((c) => ({ value: c.id, label: c.title })),
    [courses.data],
  );
  const scopedCourseTitle = scopedCourseId
    ? (courses.data ?? []).find((c) => c.id === scopedCourseId)?.title
    : undefined;

  return (
    <div className="flex flex-1 flex-col gap-8 p-4 md:p-margin-desktop">
      <div>
        <h1 className="font-headline-lg text-headline-lg text-on-background">Ingestion Portal</h1>
        <p className="mt-1 text-body-md text-on-surface-variant">
          Paste a source link and generate a new course module.
        </p>
        {scopedCourseId && (
          <p
            data-testid="scoped-course-hint"
            className="mt-2 inline-flex items-center gap-1.5 rounded-lg bg-primary/5 px-3 py-1.5 font-label-md text-label-md text-primary"
          >
            <Icon name="link" className="text-[16px]" />
            Adding to “{scopedCourseTitle ?? "selected course"}”
          </p>
        )}
      </div>

      {mcp.data && !mcp.data.healthy && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-warning-outline bg-warning-container/60 px-3 py-2 font-label-md text-label-md text-warning"
        >
          <Icon name="cloud_off" className="mt-0.5 text-[18px]" />
          NotebookLM is disconnected. You can still submit — jobs will queue and run once it
          reconnects.
        </div>
      )}

      <Card>
        <CardBody className="p-5">
          <form className="flex flex-col gap-5" onSubmit={onSubmit} noValidate>
            <h2 className="font-headline-md text-headline-md">Create New AI Course Module</h2>

            <Input
              ref={urlRef}
              label="Link (optional)"
              placeholder="https://youtube.com/watch?v=…"
              value={sourceUrl}
              onChange={(e) => setSourceUrl(e.target.value)}
              error={submitted ? (urlErr ?? undefined) : undefined}
              hint="YouTube, Google Drive, a direct .pdf link, or a web page"
            />

            <div className="flex flex-col gap-1">
              <span className="font-label-md text-label-md text-on-surface-variant">
                PDF files (optional)
              </span>
              <PdfPicker files={pdfs} onAdd={addPdfs} onRemove={removePdf} onRetry={retryPdf} />
              {submitted && sourceErr && (
                <p role="alert" className="font-label-sm text-label-sm text-error">
                  {sourceErr}
                </p>
              )}
              {submitted && pdfErr && (
                <p role="alert" className="font-label-sm text-label-sm text-error">
                  {pdfErr}
                </p>
              )}
            </div>

            <fieldset className="flex flex-col gap-3">
              <legend className="font-label-md text-label-md text-on-surface-variant">
                Target
              </legend>
              <div className="flex gap-4">
                {(["new", "existing"] as Target[]).map((t) => (
                  <label key={t} className="flex items-center gap-2 text-body-md">
                    <input
                      type="radio"
                      name="target"
                      checked={target === t}
                      onChange={() => setTarget(t)}
                    />
                    {t === "new" ? "New course" : "Existing course"}
                  </label>
                ))}
              </div>

              {target === "new" ? (
                <div className="grid gap-3 sm:grid-cols-2">
                  <Input
                    label="Course title"
                    value={courseTitle}
                    onChange={(e) => setCourseTitle(e.target.value)}
                    error={submitted ? (courseTitleErr ?? undefined) : undefined}
                  />
                  <Input
                    label="Category"
                    value={category}
                    onChange={(e) => setCategory(e.target.value)}
                    hint="Free text"
                  />
                  <div className="sm:col-span-2">
                    <Input
                      label="Description"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                    />
                  </div>
                </div>
              ) : (
                <Select
                  label="Course"
                  placeholder={courseOptions.length ? "Select a course" : "No courses yet"}
                  options={courseOptions}
                  value={existingCourseId}
                  onChange={(e) => setExistingCourseId(e.target.value)}
                  error={submitted ? (courseSelectErr ?? undefined) : undefined}
                />
              )}
            </fieldset>

            <Input
              label="Module title"
              value={moduleTitle}
              onChange={(e) => setModuleTitle(e.target.value)}
              error={submitted ? (moduleTitleErr ?? undefined) : undefined}
            />

            <fieldset className="flex flex-col gap-2">
              <legend className="font-label-md text-label-md text-on-surface-variant">
                Artifacts to generate
              </legend>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {ARTIFACT_TYPES.map((t) => (
                  <label key={t} className="flex items-center gap-2 text-body-md">
                    <input
                      type="checkbox"
                      checked={types.has(t)}
                      onChange={() => toggleType(t)}
                      data-testid={`type-${t}`}
                    />
                    {ARTIFACT_LABELS[t]}
                  </label>
                ))}
              </div>
              {submitted && typesErr && (
                <p className="font-label-sm text-label-sm text-error">{typesErr}</p>
              )}
            </fieldset>

            {ARTIFACT_TYPES.filter((t) => types.has(t)).map((t) => (
              <fieldset
                key={t}
                className="flex flex-col gap-2 rounded-lg border border-outline-variant/60 p-3"
                data-testid={`options-${t}`}
              >
                <legend className="px-1 font-label-md text-label-md text-on-surface-variant">
                  {ARTIFACT_LABELS[t]} options
                </legend>
                <GenerationOptionsEditor
                  type={t}
                  values={optionsByType[t] ?? DEFAULT_OPTIONS[t]}
                  onChange={(next) => setOptionsByType((prev) => ({ ...prev, [t]: next }))}
                  prompt={promptsByType[t] ?? ""}
                  onPromptChange={(next) => setPromptsByType((prev) => ({ ...prev, [t]: next }))}
                />
                {submitted && optionProblems.get(t) && (
                  <p className="font-label-sm text-label-sm text-error">{optionProblems.get(t)}</p>
                )}
              </fieldset>
            ))}

            {formError && (
              <p
                role="alert"
                className="rounded-lg bg-error-container/50 px-3 py-2 font-label-md text-label-md text-on-error-container"
              >
                {formError}
              </p>
            )}

            <Button
              type="submit"
              iconLeft="auto_awesome"
              loading={ingest.isPending}
              disabled={uploading > 0 || (submitted && !isValid)}
              data-testid="btn-ig6"
              className="self-start"
            >
              {uploading > 0
                ? `Uploading ${trackedPdfs - uploading + 1} of ${trackedPdfs}…`
                : "Generate Course Material"}
            </Button>
          </form>
        </CardBody>
      </Card>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="font-headline-md text-headline-md">Recent Pipeline</h2>
          <Link
            to="/admin/pipeline"
            data-testid="btn-ig11"
            className="font-label-md text-label-md text-primary underline underline-offset-4"
          >
            View all
          </Link>
        </div>

        <Card>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-body-md">
              <thead className="border-b border-outline-variant font-label-sm text-label-sm text-on-surface-variant">
                <tr>
                  <th className="px-4 py-2">Source</th>
                  <th className="px-4 py-2">Date</th>
                  <th className="px-4 py-2">Artifacts</th>
                  <th className="px-4 py-2">Status</th>
                  <th className="px-4 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {(pipeline.data?.rows ?? []).map((row) => (
                  <tr key={row.module_id} className="border-b border-outline-variant/60">
                    <td className="px-4 py-3">
                      <div className="font-label-md text-label-md">{row.module_title}</div>
                      <SourceSummary sourceUrl={row.source_url} files={row.source_files} />
                    </td>
                    <td className="px-4 py-3 text-label-sm text-on-surface-variant">
                      {new Date(row.created_at).toLocaleDateString()}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex gap-1">
                        {row.dots.map((d) => (
                          <StatusDot
                            key={d.type}
                            status={d.status}
                            title={`${d.type}: ${d.status}`}
                          />
                        ))}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <StatusChip status={row.global_status} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        to={`/admin/modules/${row.module_id}/staging`}
                        data-testid="btn-ig10"
                        className="font-label-md text-label-md text-primary underline underline-offset-4"
                      >
                        Open staging
                      </Link>
                    </td>
                  </tr>
                ))}
                {pipeline.data && pipeline.data.rows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-on-surface-variant">
                      Nothing generated yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Card>
      </section>
    </div>
  );
}
