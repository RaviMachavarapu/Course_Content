import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, ErrorState, Icon, Skeleton } from "@/components";
import { cn } from "@/lib/cn";
import { MathText } from "@/components/math/MathText";
import { useArtifactProgress, useStudentArtifact } from "../useWorkspace";

interface Cue {
  t: number;
  text: string;
}

const SPEEDS = [1, 1.25, 1.5, 2] as const;

function fmt(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "0:00";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function AudioPlayer({
  artifactId,
  slug,
  nextHref,
  moduleTitle,
}: {
  artifactId: string;
  slug: string;
  nextHref: string;
  moduleTitle?: string;
}): JSX.Element {
  const { data, isPending, isError, refetch } = useStudentArtifact(artifactId);
  const progress = useArtifactProgress(artifactId, slug);
  const navigate = useNavigate();
  const audioRef = useRef<HTMLAudioElement>(null);

  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [speedIdx, setSpeedIdx] = useState(0);
  const [volume, setVolume] = useState(1);
  const [showTranscript, setShowTranscript] = useState(false);
  const seeked = useRef(false);

  // NotebookLM's Audio Overview is AAC (m4a); fixture content is mp3.
  const src = data?.media.find((m) => m.kind === "audio_mp3" || m.kind === "audio_m4a")?.url;
  const cues = (data?.content_json?.transcript ?? []) as Cue[];
  const fallbackDuration = Number(data?.content_json?.duration_seconds ?? 0);
  const totalDuration = duration || fallbackDuration;

  const save = useCallback(
    (extra: { completed?: boolean } = {}) => {
      const el = audioRef.current;
      if (!el) return;
      progress.mutate({ audio_position_seconds: Math.floor(el.currentTime), ...extra });
    },
    [progress],
  );

  // periodic position save while playing
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => save(), 5000);
    return () => window.clearInterval(id);
  }, [playing, save]);

  // Latest playback position, kept in a ref so the unmount save can read it:
  // `audioRef` is still null at mount (the Skeleton renders first) and is
  // detached again before a passive-effect cleanup runs.
  const positionRef = useRef(0);
  useEffect(() => {
    return () => {
      if (positionRef.current > 0) {
        // best-effort save on unmount
        progress.mutate({ audio_position_seconds: Math.floor(positionRef.current) });
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (isPending) return <Skeleton className="h-80" />;
  if (isError || !data || !src)
    return <ErrorState title="Audio isn’t ready" onRetry={() => void refetch()} />;

  const activeCue = cues.reduce((acc, c, i) => (c.t <= time ? i : acc), -1);

  const el = () => audioRef.current;
  const togglePlay = () => {
    const a = el();
    if (!a) return;
    if (a.paused) void a.play();
    else a.pause();
  };
  const nudge = (delta: number) => {
    const a = el();
    if (!a) return;
    a.currentTime = Math.max(0, Math.min(totalDuration || a.duration || 0, a.currentTime + delta));
  };
  const cycleSpeed = () => {
    const next = (speedIdx + 1) % SPEEDS.length;
    setSpeedIdx(next);
    if (el()) el()!.playbackRate = SPEEDS[next]!;
  };

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-4">
      <audio
        ref={audioRef}
        src={src}
        preload="metadata"
        onLoadedMetadata={(e) => {
          const a = e.currentTarget;
          setDuration(a.duration);
          a.volume = volume;
          a.playbackRate = SPEEDS[speedIdx]!;
          if (!seeked.current && data.audio_position_seconds) {
            a.currentTime = data.audio_position_seconds;
          }
          seeked.current = true;
        }}
        onTimeUpdate={(e) => {
          positionRef.current = e.currentTarget.currentTime;
          setTime(e.currentTarget.currentTime);
        }}
        onPlay={() => setPlaying(true)}
        onPause={() => {
          setPlaying(false);
          save();
        }}
        onEnded={() => {
          setPlaying(false);
          save({ completed: true });
        }}
      />

      <Card className="flex flex-col items-center gap-4 p-8">
        <div className="flex flex-col items-center gap-1 text-center">
          <p className="font-headline-md text-headline-md">Listen to Lesson</p>
          {moduleTitle && <p className="text-body-md text-on-surface-variant">{moduleTitle}</p>}
        </div>
        <button
          type="button"
          data-testid="btn-au1"
          aria-label={playing ? "Pause" : "Play"}
          onClick={togglePlay}
          className="flex h-16 w-16 items-center justify-center rounded-full bg-tertiary text-on-tertiary shadow-level-1 focus-visible:outline-none focus-visible:shadow-focus"
        >
          <Icon name={playing ? "pause" : "play_arrow"} filled className="text-[36px]" />
        </button>

        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" data-testid="btn-au2" onClick={() => nudge(-10)}>
            <Icon name="replay_10" />
          </Button>
          <Button variant="ghost" size="sm" data-testid="btn-au3" onClick={() => nudge(10)}>
            <Icon name="forward_10" />
          </Button>
        </div>

        <div className="flex w-full items-center gap-3">
          <span className="w-12 text-right font-label-sm text-label-sm tabular-nums">
            {fmt(time)}
          </span>
          <input
            type="range"
            data-testid="btn-au4"
            aria-label="Seek"
            min={0}
            max={Math.max(totalDuration, 1)}
            step={1}
            value={Math.min(time, totalDuration || time)}
            onChange={(e) => {
              const a = el();
              if (a) a.currentTime = Number(e.target.value);
            }}
            className="h-1.5 flex-1 accent-tertiary"
          />
          <span className="w-12 font-label-sm text-label-sm tabular-nums text-on-surface-variant">
            {fmt(totalDuration)}
          </span>
        </div>

        <div className="flex w-full items-center justify-between">
          <Button variant="secondary" size="sm" data-testid="btn-au5" onClick={cycleSpeed}>
            {SPEEDS[speedIdx]}x
          </Button>
          <label className="flex items-center gap-2">
            <Icon name={volume === 0 ? "volume_off" : "volume_up"} className="text-[18px]" />
            <input
              type="range"
              data-testid="btn-au6"
              aria-label="Volume"
              min={0}
              max={1}
              step={0.05}
              value={volume}
              onChange={(e) => {
                const v = Number(e.target.value);
                setVolume(v);
                if (el()) el()!.volume = v;
              }}
              className="h-1.5 w-24 accent-tertiary"
            />
          </label>
          {cues.length > 0 && (
            <Button
              variant="ghost"
              size="sm"
              iconLeft="subtitles"
              data-testid="btn-au7"
              aria-pressed={showTranscript}
              onClick={() => setShowTranscript((s) => !s)}
            >
              Transcript
            </Button>
          )}
        </div>
      </Card>

      {showTranscript && cues.length > 0 && (
        <Card className="max-h-80 overflow-y-auto p-4" data-testid="transcript-panel">
          <ol className="space-y-1">
            {cues.map((c, i) => (
              <li key={i}>
                <button
                  type="button"
                  onClick={() => {
                    const a = el();
                    if (a) a.currentTime = c.t;
                  }}
                  className={cn(
                    "flex w-full gap-3 rounded px-2 py-1 text-left text-body-md hover:bg-surface-container-high",
                    "focus-visible:outline-none focus-visible:shadow-focus",
                    i === activeCue && "bg-tertiary-container/30 font-medium",
                  )}
                >
                  <span className="shrink-0 tabular-nums text-label-sm text-on-surface-variant">
                    {fmt(c.t)}
                  </span>
                  <MathText text={c.text} />
                </button>
              </li>
            ))}
          </ol>
        </Card>
      )}

      <div className="flex justify-end">
        <Button
          iconRight="skip_next"
          data-testid="btn-au8"
          onClick={() => {
            save();
            navigate(nextHref);
          }}
        >
          Next Lesson
        </Button>
      </div>
    </div>
  );
}
