import { apiFetch } from "@/lib/api";

export interface Achievement {
  key: string;
  label: string;
  description: string;
  icon: string;
  earned: boolean;
  earned_at: string | null;
}

export const meApi = {
  achievements: () =>
    apiFetch<{ earned: Achievement[]; locked: Achievement[] }>("/api/student/me/achievements"),
};
