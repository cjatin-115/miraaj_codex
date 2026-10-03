"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Plan = { project_id: string; status: "queued" | "planning" | "ready" | "failed"; provider: string; error?: string | null; edit_plan?: { duration: number; scenes: Array<{ id: string; type: string; timeline_start: number; duration: number; text?: string; rationale?: string }> } | null; timeline?: { duration: number; scenes: Array<{ id: string; type: string; start?: number; timeline_start?: number; duration: number; text?: string; layer?: string }> } | null };
type Project = { id: string; name: string; script_text: string; analysis?: { status: string; target_duration: number; duration_estimate: { estimated_min_duration: number; estimated_max_duration: number } } };
type Render = { id: string; status: "queued" | "processing" | "rendering" | "encoding" | "quality_check" | "completed" | "failed"; stage: string; progress: number; profile: string; error?: string | null; source_width?: number | null; source_height?: number | null; output_width?: number | null; output_height?: number | null };

export default function PlanningPage() {
  const params = useParams<{ projectId: string }>();
  const [project, setProject] = useState<Project | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [render, setRender] = useState<Render | null>(null);
  const [renderError, setRenderError] = useState("");
  const [rendering, setRendering] = useState(false);
  const [assetMessage, setAssetMessage] = useState("");
  const [error, setError] = useState("");
  const [showJson, setShowJson] = useState(false);
  const startPlanning = useCallback(async () => {
    try {
      setError("");
      const projectResponse = await fetch(`${apiUrl}/api/projects/${params.projectId}`, { cache: "no-store" });
      if (!projectResponse.ok) throw new Error("Could not load this project.");
      const current = await projectResponse.json() as Project;
      setProject(current);
      if (current.analysis?.status !== "ready") { setError("Media analysis must finish before the Director can create a plan."); return; }
      const response = await fetch(`${apiUrl}/api/projects/${params.projectId}/plan`, { method: "POST" });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Could not start planning.");
      setPlan(await response.json() as Plan);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not start planning."); }
  }, [params.projectId]);

  const startRender = async (profile: "vertical_1080" | "vertical_4k") => {
    setRenderError(""); setRendering(true);
    try {
      const response = await fetch(`${apiUrl}/api/projects/${params.projectId}/renders`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile, volume: 1 }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Could not queue the render.");
      setRender(data as Render);
    } catch (reason) { setRenderError(reason instanceof Error ? reason.message : "Could not queue the render."); }
    finally { setRendering(false); }
  };
  const uploadAssets = async (files: FileList | null) => {
    if (!files?.length) return;
    setAssetMessage("Uploading and validating assets…");
    try {
      for (const file of Array.from(files)) {
        const body = new FormData(); body.append("file", file);
        const response = await fetch(`${apiUrl}/api/projects/${params.projectId}/assets`, { method: "POST", body });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail ?? `Could not upload ${file.name}.`);
      }
      setAssetMessage("Assets uploaded and checked. Recreate the plan to make them available to the Director.");
      setPlan(current => current ? { ...current, status: "failed", error: "Assets changed; create a new validated plan before rendering." } : current);
    } catch (reason) { setAssetMessage(reason instanceof Error ? reason.message : "Asset upload failed."); }
  };

  useEffect(() => { void startPlanning(); }, [startPlanning]);
  useEffect(() => {
    if (!plan || plan.status === "ready" || plan.status === "failed") return;
    const timer = window.setInterval(async () => {
      try { const response = await fetch(`${apiUrl}/api/projects/${params.projectId}/plan`, { cache: "no-store" }); if (response.ok) setPlan(await response.json() as Plan); }
      catch { /* transient polling failures are retried on the next interval */ }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [plan, params.projectId]);
  useEffect(() => {
    if (!render || ["completed", "failed"].includes(render.status)) return;
    const timer = window.setInterval(async () => {
      try { const response = await fetch(`${apiUrl}/api/renders/${render.id}`, { cache: "no-store" }); if (response.ok) setRender(await response.json() as Render); }
      catch { /* continue checking the persisted worker status */ }
    }, 1200);
    return () => window.clearInterval(timer);
  }, [render]);
  useEffect(() => {
    if (plan?.status !== "ready") return;
    fetch(`${apiUrl}/api/projects/${params.projectId}/renders/latest`, { cache: "no-store" })
      .then(async response => { if (response.ok) setRender(await response.json() as Render); })
      .catch(() => undefined);
  }, [plan?.status, params.projectId]);

  const scenes = plan?.timeline?.scenes ?? [];
  const baseScenes = scenes.filter(scene => (scene.layer ?? "base") === "base");
  const density = scenes.length && plan?.timeline?.duration ? (scenes.length / plan.timeline.duration) : 0;
  return <main className="min-h-screen">
    <header className="flex items-center justify-between border-b border-white/10 px-8 py-5 lg:px-16"><Link className="text-xl font-semibold tracking-[.2em]" href="/">MIRAAJ<span className="text-violet-400">.</span></Link><span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/50">VIDEO PLANNING</span></header>
    <section className="mx-auto max-w-4xl px-6 py-16 lg:py-24">
      {error && project && <div role="alert" className="mb-6 rounded-xl border border-rose-300/20 bg-rose-300/[.06] p-4 text-rose-200">{error}</div>}
      {!project ? error ? <div className="mt-8 rounded-2xl border border-rose-300/20 bg-[#111419] p-6"><h1 className="text-xl font-semibold">Could not load this project</h1><p className="mt-2 text-sm leading-6 text-white/60">{error}</p><button onClick={() => void startPlanning()} className="mt-5 rounded-lg bg-violet-300 px-4 py-2.5 text-sm font-semibold text-[#17131f]">Retry connection</button></div> : <p className="text-white/50">Loading project…</p> : <>
        <p className="mb-4 text-xs font-semibold tracking-[.25em] text-violet-300">{plan?.status === "ready" ? "DIRECTOR PLAN READY" : "MIRAAJ DIRECTOR"}</p>
        <h1 className="text-4xl font-semibold tracking-tight">{project.name}</h1>
        {plan?.status === "queued" && <div role="status" className="mt-5 rounded-xl border border-violet-300/15 bg-violet-300/[.04] p-4 text-sm leading-6 text-white/65">Your plan is queued and waiting for the local worker. If it stays here, check that PostgreSQL, Redis, and the Miraaj video worker are running.</div>}
        {plan?.status === "planning" && <p className="mt-5 text-white/60">The Director is building a plan from your analyzed transcript, framing, script, style, and selected duration…</p>}
        {!plan && error && project.analysis?.status === "ready" && <button onClick={() => void startPlanning()} className="mt-4 rounded-lg bg-violet-400 px-4 py-2 text-sm font-semibold text-black">Retry planning</button>}
        {plan?.status === "failed" && <div className="mt-6 rounded-xl border border-rose-300/20 p-5"><p className="text-rose-200">Planning failed: {plan.error}</p><button onClick={() => void startPlanning()} className="mt-4 rounded-lg bg-violet-400 px-4 py-2 text-sm font-semibold text-black">Retry planning</button></div>}
        {plan?.status === "ready" && plan.timeline && <>
          <div className="mt-8 grid gap-4 sm:grid-cols-4"><Info label="Estimated duration" value={`${plan.edit_plan?.duration.toFixed(1)} sec`} /><Info label="Selected duration" value={`${project.analysis?.target_duration ?? "—"} sec`} /><Info label="Scenes" value={`${scenes.length}`} /><Info label="Visual density" value={`${density.toFixed(2)} scenes/sec`} /></div>
          <section className="mt-6 rounded-2xl border border-white/10 bg-[#111419] p-5"><label className="text-sm font-medium" htmlFor="visual-assets">Add screenshots or b-roll</label><p className="mt-1 text-xs leading-5 text-white/45">Upload original PNG/JPEG/WebP screenshots or MP4/MOV/WebM footage. Miraaj validates each file before making it available to the Director.</p><input id="visual-assets" type="file" multiple accept="image/png,image/jpeg,image/webp,video/mp4,video/quicktime,video/webm" onChange={event => void uploadAssets(event.currentTarget.files)} className="mt-3 block w-full text-sm text-white/65 file:mr-4 file:rounded-lg file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-sm file:text-white" />{assetMessage && <p className="mt-3 text-sm text-violet-200">{assetMessage}</p>}</section>
          <section className="mt-8 rounded-2xl border border-white/10 bg-[#111419] p-6">
            <div className="flex flex-wrap items-center justify-between gap-4"><div><h2 className="font-medium">Render video</h2><p className="mt-1 text-sm text-white/50">Remotion composition · 30 fps · H.264</p></div>{(!render || ["failed", "completed"].includes(render.status)) && <div className="flex flex-wrap gap-2"><button onClick={() => void startRender("vertical_1080")} disabled={rendering} className="rounded-lg bg-violet-300 px-5 py-3 text-sm font-semibold text-[#17131f] disabled:opacity-50">{rendering ? "Queueing…" : "Render 1080p"}</button><button onClick={() => void startRender("vertical_4k")} disabled={rendering} className="rounded-lg border border-violet-200/30 px-5 py-3 text-sm font-semibold text-violet-100 disabled:opacity-50">Render 4K · Experimental</button></div>}</div>
            {renderError && <p role="alert" className="mt-4 text-sm text-rose-300">{renderError}</p>}
            {render && <><div className="mt-6 flex items-center justify-between text-sm"><span className="capitalize text-white/70">{render.stage.replaceAll("_", " ")}</span><span className="tabular-nums text-violet-200">{Math.round(render.progress * 100)}%</span></div><div className="mt-2 h-2 overflow-hidden rounded-full bg-white/10"><div className="h-full rounded-full bg-violet-300 transition-[width] duration-300" style={{ width: `${Math.round(render.progress * 100)}%` }} /></div>
              {render.status === "failed" && <p className="mt-4 text-sm text-rose-300">Render failed: {render.error}</p>}
              {render.status === "completed" && <div className="mt-5"><div className="flex flex-wrap items-center gap-4"><a href={`${apiUrl}/api/renders/${render.id}/file`} className="rounded-lg bg-violet-300 px-4 py-3 text-sm font-semibold text-[#17131f]">Download {render.profile === "vertical_4k" ? "4K" : "1080p"}</a><span className="text-xs text-white/50">{plan.timeline.duration.toFixed(1)} sec · {render.output_width} × {render.output_height} · 30 fps · H.264 · source {render.source_width} × {render.source_height}{(render.source_width ?? 0) < (render.output_width ?? 1080) ? " · source enlarged; output has no added source detail" : ""}</span></div><video key={render.id} controls playsInline preload="metadata" className="mt-5 aspect-[9/16] max-h-[70vh] w-auto rounded-xl bg-black" src={`${apiUrl}/api/renders/${render.id}/file`} /></div>}
              <div className="mt-6 grid gap-2 text-xs sm:grid-cols-4">{["uploading", "analyzing", "planning", "generating", "rendering", "encoding", "quality_check"].map((stage, index) => { const completedRendering = ["encoding", "quality_check", "completed"].includes(render.status); const done = index < 3 || stage === "generating" && completedRendering || stage === "rendering" && ["encoding", "quality_check", "completed"].includes(render.status) || stage === "encoding" && ["quality_check", "completed"].includes(render.status) || stage === "quality_check" && render.status === "completed"; const active = stage === "generating" && render.status === "processing" || stage === render.status; return <span key={stage} className={done ? "text-emerald-300" : active ? "text-violet-200" : "text-white/30"}>{done ? "✓" : active ? "•" : "○"} {stage.replaceAll("_", " ")}</span>; })}</div>
            </>}
          </section>
          <section className="mt-8 rounded-2xl border border-white/10 bg-[#111419] p-6"><div className="flex items-center justify-between"><h2 className="font-medium">Scene list</h2><span className="text-xs text-white/40">{baseScenes.length} talking-head segments</span></div><ol className="mt-5 space-y-3">{scenes.map(scene => <li key={scene.id} className="flex gap-4 rounded-xl bg-white/[.03] p-4"><span className="w-24 shrink-0 text-xs text-violet-200">{(scene.start ?? scene.timeline_start ?? 0).toFixed(1)}s · {scene.duration.toFixed(1)}s</span><div><p className="text-sm font-medium">{scene.type.replaceAll("_", " ")}</p>{scene.text && <p className="mt-1 text-sm text-white/70">{scene.text}</p>}</div></li>)}</ol><button onClick={() => setShowJson(!showJson)} className="mt-5 text-sm text-violet-200 underline">{showJson ? "Hide" : "Inspect"} generated plan JSON</button>{showJson && <pre className="mt-4 max-h-[32rem] overflow-auto rounded-xl bg-black/40 p-4 text-xs leading-5 text-white/70">{JSON.stringify({ edit_plan: plan.edit_plan, timeline: plan.timeline }, null, 2)}</pre>}</section>
        </>}
        <section className="mt-8 rounded-2xl border border-white/10 bg-[#111419] p-6"><h2 className="font-medium">Script</h2><p className="mt-4 whitespace-pre-wrap text-sm leading-7 text-white/65">{project.script_text}</p></section>
        <Link href="/" className="mt-8 inline-flex rounded-lg border border-white/15 px-4 py-3 text-sm text-white/70 hover:bg-white/5">← Back to project analysis</Link>
      </>}
    </section>
  </main>;
}

function Info({ label, value }: { label: string; value: string }) { return <div className="rounded-xl border border-white/10 bg-[#111419] p-5"><p className="text-xs uppercase tracking-wide text-white/40">{label}</p><p className="mt-2 text-lg font-medium text-violet-100">{value}</p></div>; }
