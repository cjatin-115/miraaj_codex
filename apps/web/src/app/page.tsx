"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { durationChoices, durationWarning } from "@/lib/duration.mjs";

const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface DurationEstimate { estimated_min_duration: number; estimated_max_duration: number; recommended_duration: number; confidence: number }
interface ProjectAnalysis {
  status: string;
  content_hash?: string | null;
  video_metadata?: { width: number; height: number; fps: number; duration_seconds: number; video_codec?: string; bitrate: number; has_audio: boolean; audio_streams: Array<{ codec?: string; sample_rate?: string; channels?: number }> } | null;
  video_analysis?: { face_analysis: { detected_samples: number; total_samples: number; framing: string; approximate_framing: string; camera_stability: string }; scene_change_times: number[]; usable_segments: Array<{ start: number; end: number }> } | null;
  audio_analysis?: { audio_present: boolean; duration_seconds: number; speech_duration_seconds: number; silence_regions: Array<{ start: number; end: number }>; loudness_dbfs: number | null; peak_dbfs: number | null; speaking_rate_wpm: number | null } | null;
  transcript?: { status: string; language?: string; error?: string; segments?: Array<{ start: number; end: number; text: string }>; words?: Array<{ word: string; start: number; end: number; confidence?: number }> } | null;
  script_analysis: { word_count: number; sentence_count: number; paragraph_count: number; speaking_rate_wpm: number; likely_hooks: string[]; important_statements: string[]; candidate_visual_moments: Array<{ text: string; visual_hint: string }>; candidate_emphasis_words: string[] };
  duration_estimate: DurationEstimate;
  target_duration: number | null;
  duration_fit?: { status: string; message: string | null } | null;
  error?: string | null;
}
interface Project { id: string; name: string; status: string; analysis?: ProjectAnalysis }

export default function Home() {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [script, setScript] = useState("");
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [analysis, setAnalysis] = useState<ProjectAnalysis | null>(null);
  const [target, setTarget] = useState(0);
  const [customMode, setCustomMode] = useState(false);
  const [customTarget, setCustomTarget] = useState(60);
  const [continuing, setContinuing] = useState(false);
  const [retryingAnalysis, setRetryingAnalysis] = useState(false);
  const estimate = analysis?.duration_estimate;
  const analysisStatus = analysis?.status;
  const localWarning = useMemo(() => estimate && target ? durationWarning(estimate, target) : null, [estimate, target]);

  useEffect(() => {
    if (!projectId || !analysisStatus || !["queued", "analyzing"].includes(analysisStatus)) return;
    let active = true;
    const timer = window.setInterval(async () => {
      try {
        const response = await fetch(`${apiUrl}/api/projects/${projectId}/analysis`, { cache: "no-store" });
        if (!response.ok) throw new Error("Could not refresh project analysis.");
        const updated: ProjectAnalysis = await response.json();
        if (!active) return;
        setAnalysis(updated);
      } catch (error) {
        if (active) setMessage(error instanceof Error ? error.message : "Could not refresh analysis.");
      }
    }, 2000);
    return () => { active = false; window.clearInterval(timer); };
  }, [projectId, analysisStatus]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!file) return setMessage("Choose a video recording to continue.");
    setBusy(true); setMessage("");
    const data = new FormData();
    data.set("name", name.trim() || file.name.replace(/\.[^.]+$/, ""));
    data.set("script_text", script);
    data.set("video", file);
    try {
      const response = await fetch(`${apiUrl}/api/projects`, { method: "POST", body: data });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Could not create project.");
      const project: Project = await response.json();
      if (!project.analysis) throw new Error("Project was created without its script analysis.");
      setProjectId(project.id);
      setProjectName(project.name);
      setAnalysis(project.analysis);
      setTarget(project.analysis.target_duration ?? project.analysis.duration_estimate.recommended_duration);
      setCustomTarget(project.analysis.target_duration ?? project.analysis.duration_estimate.recommended_duration);
      setFile(null);
      setMessage("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "API is unavailable. Start the local API and worker.");
    } finally { setBusy(false); }
  }

  async function continueToPlanning() {
    if (!projectId || !analysis || !target) return;
    setContinuing(true); setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/projects/${projectId}/target-duration`, {
        method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ seconds: target }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Could not save the target duration.");
      setAnalysis(await response.json());
      router.push(`/planning/${projectId}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not save the target duration.");
    } finally { setContinuing(false); }
  }

  async function retryAnalysis() {
    if (!projectId) return;
    setRetryingAnalysis(true); setMessage("");
    try {
      const response = await fetch(`${apiUrl}/api/projects/${projectId}/analysis/retry`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "Could not retry media analysis.");
      const updated = data as Project;
      if (!updated.analysis) throw new Error("The retry was queued without an analysis record.");
      setAnalysis(updated.analysis);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Could not retry media analysis.");
    } finally { setRetryingAnalysis(false); }
  }

  function startAnother() {
    setProjectId(null); setProjectName(""); setAnalysis(null); setScript(""); setName(""); setMessage(""); setTarget(0); setCustomMode(false);
  }

  const chooseTarget = (seconds: number) => { setTarget(seconds); setCustomTarget(seconds); setCustomMode(false); };
  const isAnalyzing = analysis && ["queued", "analyzing"].includes(analysis.status);
  const video = analysis?.video_metadata;
  const audio = analysis?.audio_analysis;
  const scriptInfo = analysis?.script_analysis;

  return <main className="min-h-screen">
    <header className="flex items-center justify-between border-b border-white/10 px-8 py-5 lg:px-16">
      <a className="text-xl font-semibold tracking-[.2em]" href="#">MIRAAJ<span className="text-violet-400">.</span></a>
      <span className="rounded-full border border-white/10 px-3 py-1 text-xs text-white/50">PERSONAL STUDIO · V1</span>
    </header>
    <section className="mx-auto max-w-6xl px-6 py-12 lg:px-10 lg:py-16">
      {!analysis ? <div className="grid gap-16 lg:grid-cols-[1fr_.85fr]">
        <div className="pt-4"><p className="mb-5 text-xs font-semibold tracking-[.25em] text-violet-300">FROM RAW TAKE TO REFINED STORY</p>
          <h1 className="max-w-xl text-5xl font-semibold leading-[1.08] tracking-tight sm:text-6xl">Your words.<br/>A whole new <span className="text-violet-300">frame.</span></h1>
          <p className="mt-6 max-w-md text-base leading-7 text-white/55">Bring your script and a simple camera recording. Miraaj will analyze the footage and estimate a natural target length.</p>
          <div className="mt-12 grid max-w-md grid-cols-3 border-t border-white/10 pt-5 text-xs text-white/45"><span>01&nbsp; UPLOAD</span><span>02&nbsp; ANALYZE</span><span>03&nbsp; PLAN</span></div>
        </div>
        <form onSubmit={submit} className="rounded-2xl border border-white/10 bg-[#111419] p-6 shadow-2xl shadow-black/30 sm:p-8">
          <div className="mb-7"><h2 className="text-xl font-medium">Start a project</h2><p className="mt-1 text-sm text-white/45">Your original recording is preserved locally.</p></div>
          <label className="mb-2 block text-sm text-white/75" htmlFor="name">Project name <span className="text-white/35">(optional)</span></label>
          <input id="name" value={name} onChange={e=>setName(e.target.value)} placeholder="e.g. The future of design" className="mb-6 w-full rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm outline-none transition focus:border-violet-400" />
          <label htmlFor="video" className="group mb-6 flex cursor-pointer flex-col items-center rounded-xl border border-dashed border-white/20 bg-white/[.02] px-5 py-7 text-center transition hover:border-violet-300/70 hover:bg-violet-300/[.04]">
            <span className="mb-3 grid h-10 w-10 place-items-center rounded-full bg-white/5 text-xl text-violet-200">↑</span>
            <span className="text-sm font-medium">{file ? file.name : "Choose your talking-head video"}</span>
            <span className="mt-1 text-xs text-white/40">MP4, MOV or WebM · up to 500 MB</span>
            <input id="video" type="file" accept="video/*" required className="sr-only" onChange={e=>setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label htmlFor="script" className="mb-2 block text-sm text-white/75">Your script</label>
          <textarea id="script" required value={script} onChange={e=>setScript(e.target.value)} rows={6} placeholder="Paste the words you want to bring to life…" className="w-full resize-y rounded-lg border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 outline-none transition placeholder:text-white/25 focus:border-violet-400" />
          {message && <p role="alert" className="mt-4 text-sm text-rose-300">{message}</p>}
          <button disabled={busy || !script.trim() || !file} className="mt-5 w-full rounded-lg bg-violet-300 px-5 py-3.5 text-sm font-semibold text-[#17131f] transition hover:bg-violet-200 disabled:cursor-not-allowed disabled:opacity-40">{busy ? "Creating project…" : "Analyze recording  →"}</button>
          <p className="mt-4 text-center text-xs text-white/35">Analysis runs on your local machine.</p>
        </form>
      </div> : <div>
        <div className="mb-8 flex flex-wrap items-end justify-between gap-4">
          <div><p className="mb-3 text-xs font-semibold tracking-[.25em] text-violet-300">PROJECT ANALYSIS</p><h1 className="text-4xl font-semibold tracking-tight">{projectName}</h1><p className="mt-2 text-sm text-white/45">{isAnalyzing ? "Media analysis is running in the local worker…" : analysis.status === "failed" ? "Media analysis needs attention." : "Review your source and choose a target duration."}</p></div>
          <button onClick={startAnother} className="rounded-lg border border-white/15 px-4 py-2 text-sm text-white/70 hover:bg-white/5">New project</button>
        </div>
        <div className="grid gap-5 lg:grid-cols-3">
          <Panel title="Video information" status={isAnalyzing ? "Analyzing" : analysis.status === "ready" ? "Ready" : analysis.status}>
            {video ? <div className="grid grid-cols-2 gap-x-3 gap-y-4 text-sm">
              <Metric label="Resolution" value={`${video.width} × ${video.height}`} /><Metric label="Frame rate" value={`${video.fps} fps`} />
              <Metric label="Duration" value={`${video.duration_seconds.toFixed(1)} sec`} /><Metric label="Video codec" value={video.video_codec ?? "Unknown"} />
              <Metric label="Bitrate" value={video.bitrate ? `${(video.bitrate / 1_000_000).toFixed(1)} Mbps` : "Unknown"} /><Metric label="Audio" value={video.has_audio ? "Present" : "No audio track"} />
              {analysis.video_analysis && <><Metric label="Framing" value={`${analysis.video_analysis.face_analysis.approximate_framing} · ${analysis.video_analysis.face_analysis.framing}`} /><Metric label="Camera" value={analysis.video_analysis.face_analysis.camera_stability.replaceAll("_", " ")} /></>}
              {analysis.video_analysis && <p className="col-span-2 text-xs text-white/45">{analysis.video_analysis.face_analysis.detected_samples}/{analysis.video_analysis.face_analysis.total_samples} sampled frames contained a face · {analysis.video_analysis.scene_change_times.length} possible scene changes · {analysis.video_analysis.usable_segments.length} usable segments</p>}
              {analysis.content_hash && <p className="col-span-2 text-xs text-emerald-300/80">Content-addressed cache {analysis.status === "ready" ? "checked" : "key ready"}: {analysis.content_hash.slice(0, 12)}…</p>}
            </div> : <p className="text-sm text-white/45">{isAnalyzing ? "Probing the original and extracting representative frames…" : analysis.error ?? "Video metadata is not available."}</p>}
          </Panel>
          <Panel title="Script statistics" status="Local analysis">
            {scriptInfo && <><div className="grid grid-cols-3 gap-2"><Metric label="Words" value={scriptInfo.word_count} /><Metric label="Sentences" value={scriptInfo.sentence_count} /><Metric label="Paragraphs" value={scriptInfo.paragraph_count} /></div>
              <p className="mt-5 text-xs uppercase tracking-wider text-white/40">Likely hook</p><p className="mt-1 text-sm leading-6">{scriptInfo.likely_hooks[0]}</p>
              <p className="mt-4 text-xs uppercase tracking-wider text-white/40">Emphasis words</p><div className="mt-2 flex flex-wrap gap-2">{scriptInfo.candidate_emphasis_words.slice(0, 6).map(word=><span key={word} className="rounded-full bg-violet-300/10 px-2.5 py-1 text-xs text-violet-200">{word}</span>)}</div>
            </>}
            {audio && <p className="mt-5 border-t border-white/10 pt-4 text-xs text-white/45">{audio.audio_present ? `${audio.silence_regions.length} silence regions · ${audio.speech_duration_seconds.toFixed(1)} sec active audio · peak ${audio.peak_dbfs?.toFixed(1) ?? "—"} dBFS` : "No audio track found; transcription skipped."}</p>}
            {analysis.transcript?.status === "failed" && <p className="mt-3 text-xs text-amber-300">Transcription unavailable: {analysis.transcript.error}</p>}
          </Panel>
          <Panel title="Estimated video length" status={estimate ? `${Math.round(estimate.confidence * 100)}% confidence` : "Waiting"}>
            {estimate && <><p className="text-3xl font-semibold tracking-tight">{estimate.estimated_min_duration}–{estimate.estimated_max_duration}<span className="ml-2 text-base font-normal text-white/45">seconds</span></p>
              <p className="mt-4 text-sm text-white/50">Recommended duration</p><p className="mt-1 text-2xl font-medium text-violet-200">{estimate.recommended_duration} seconds</p>
              <p className="mt-2 text-xs text-white/40">Estimated from {scriptInfo?.word_count} words at natural speech rates (125–165 wpm).</p>
            </>}
          </Panel>
        </div>
        <Panel title="Target duration" status="Used by the next planning stage">
          <p className="mb-4 text-sm text-white/50">Choose the length the director should aim for. A longer target will not stretch the recording automatically.</p>
          <div className="flex flex-wrap gap-2">
            {estimate && durationChoices(estimate).map(choice=><button key={choice.seconds} type="button" onClick={()=>chooseTarget(choice.seconds)} className={`rounded-lg border px-4 py-2.5 text-sm transition ${!customMode && target === choice.seconds ? "border-violet-300 bg-violet-300 text-[#17131f]" : "border-white/15 bg-white/[.02] text-white/75 hover:border-white/35"}`}>{choice.recommended ? `Recommended · ${choice.seconds} sec` : `${choice.seconds} sec`}</button>)}
            <button type="button" onClick={()=>{setCustomMode(true); setTarget(customTarget);}} className={`rounded-lg border px-4 py-2.5 text-sm ${customMode ? "border-violet-300 bg-violet-300 text-[#17131f]" : "border-white/15 text-white/75 hover:border-white/35"}`}>Custom</button>
          </div>
          {customMode && <label className="mt-4 block max-w-xs text-sm text-white/60">Custom seconds<input type="number" min="1" max="600" value={customTarget} onChange={e=>{const next=Number(e.target.value);setCustomTarget(next);setTarget(next);}} className="mt-2 block w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-white outline-none focus:border-violet-300" /></label>}
          {(localWarning || analysis.duration_fit?.message) && <p role="alert" className="mt-4 rounded-lg border border-amber-300/20 bg-amber-300/[.06] px-4 py-3 text-sm leading-6 text-amber-200">{localWarning ?? analysis.duration_fit?.message} Script expansion is not available yet.</p>}
          {analysis.status === "failed" && <div role="alert" className="mt-4 rounded-lg border border-rose-300/20 bg-rose-300/[.06] px-4 py-3 text-sm leading-6 text-rose-200"><p>{analysis.error ?? "Media analysis failed."}</p><button type="button" onClick={() => void retryAnalysis()} disabled={retryingAnalysis} className="mt-3 rounded-lg border border-rose-200/30 px-3 py-2 text-xs font-medium text-rose-100 disabled:opacity-50">{retryingAnalysis ? "Queueing retry…" : "Retry media analysis"}</button></div>}
          {message && <p role="alert" className="mt-4 text-sm text-rose-300">{message}</p>}
          <div className="mt-6 flex flex-wrap items-center justify-between gap-4 border-t border-white/10 pt-5">
            <span className="text-xs text-white/40">{analysis.transcript?.status === "complete" ? `${analysis.transcript.words?.length ?? 0} word timestamps ready` : isAnalyzing ? "Transcript and audio metrics are processing" : "No rendered video will be produced at this step"}</span>
            <button disabled={continuing || analysis.status !== "ready" || !target || target > 600} onClick={continueToPlanning} className="rounded-lg bg-violet-300 px-5 py-3 text-sm font-semibold text-[#17131f] transition hover:bg-violet-200 disabled:cursor-not-allowed disabled:opacity-40">{continuing ? "Saving target…" : "Continue to Video Planning  →"}</button>
          </div>
        </Panel>
        {analysis.transcript?.status === "complete" && <Panel title="Timestamped transcript" status={`${analysis.transcript.words?.length ?? 0} words`}>
          <div className="max-h-72 space-y-3 overflow-y-auto pr-2">
            {(analysis.transcript.segments ?? []).map((segment, index)=><p key={`${segment.start}-${index}`} className="text-sm leading-6 text-white/75"><span className="mr-3 font-mono text-xs text-violet-300">{segment.start.toFixed(1)}–{segment.end.toFixed(1)}s</span>{segment.text}</p>)}
          </div>
          <details className="mt-5 border-t border-white/10 pt-4">
            <summary className="cursor-pointer text-xs text-white/50">Show word timestamps</summary>
            <div className="mt-3 flex max-h-44 flex-wrap content-start gap-2 overflow-y-auto">{(analysis.transcript.words ?? []).map((word, index)=><span key={`${word.start}-${index}`} className="rounded bg-white/[.04] px-2 py-1 text-xs text-white/65"><span className="font-mono text-violet-300">{word.start.toFixed(2)}s</span>&nbsp;{word.word}</span>)}</div>
          </details>
        </Panel>}
      </div>}
    </section>
  </main>;
}

function Panel({ title, status, children }: { title: string; status?: string; children: React.ReactNode }) {
  return <section className="rounded-2xl border border-white/10 bg-[#111419] p-5 sm:p-6"><div className="mb-5 flex items-start justify-between gap-3"><h2 className="font-medium">{title}</h2>{status && <span className="rounded-full bg-white/[.05] px-2.5 py-1 text-[10px] uppercase tracking-wide text-white/45">{status}</span>}</div>{children}</section>;
}

function Metric({ label, value }: { label: string; value: React.ReactNode }) {
  return <div><p className="text-[11px] uppercase tracking-wide text-white/40">{label}</p><p className="mt-1 truncate text-sm text-white/85">{value}</p></div>;
}
