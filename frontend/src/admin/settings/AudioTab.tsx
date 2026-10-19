import { useEffect, useState } from "react";
import { Button, Card, CardBody, ErrorState, Select, Skeleton } from "@/components";
import { ApiError } from "@/lib/api";
import { useToast } from "@/lib/store";
import { useAudioSettings, useSaveAudio } from "./useSettings";

const LABELS: Record<string, string> = {
  default: "Default",
  warm: "Warm",
  bright: "Bright",
  calm: "Calm",
  conversational: "Conversational",
  deep_dive: "Deep dive",
  brief: "Brief",
};
const opt = (v: string) => ({ value: v, label: LABELS[v] ?? v });

export function AudioTab(): JSX.Element {
  const { data, isPending, isError, refetch } = useAudioSettings();
  const saveAudio = useSaveAudio();
  const { toast } = useToast();

  const [voice, setVoice] = useState("default");
  const [style, setStyle] = useState("conversational");

  useEffect(() => {
    if (data) {
      setVoice(data.settings.voice);
      setStyle(data.settings.style);
    }
  }, [data]);

  if (isError) return <ErrorState title="Could not load audio settings" onRetry={() => void refetch()} />;
  if (isPending || !data) return <Skeleton className="h-48" />;

  const dirty = voice !== data.settings.voice || style !== data.settings.style;

  return (
    <Card>
      <CardBody className="flex flex-col gap-4 p-5">
        <div>
          <h3 className="font-headline-md text-headline-md">Audio Overview defaults</h3>
          <p className="mt-1 text-body-md text-on-surface-variant">
            Forwarded to NotebookLM’s <code className="font-mono">audio_overview_create</code> for
            every new audio artifact.
          </p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <Select
            label="Voice"
            options={data.voice_choices.map(opt)}
            value={voice}
            onChange={(e) => setVoice(e.target.value)}
          />
          <Select
            label="Style"
            options={data.style_choices.map(opt)}
            value={style}
            onChange={(e) => setStyle(e.target.value)}
          />
        </div>
        <div>
          <Button
            data-testid="btn-st4"
            loading={saveAudio.isPending}
            disabled={!dirty}
            onClick={() =>
              saveAudio.mutate(
                { voice, style },
                {
                  onSuccess: () => toast({ title: "Audio settings saved", tone: "success" }),
                  onError: (err) =>
                    toast({
                      title: "Save failed",
                      description: err instanceof ApiError ? err.message : undefined,
                      tone: "error",
                    }),
                },
              )
            }
          >
            Save
          </Button>
        </div>
      </CardBody>
    </Card>
  );
}
