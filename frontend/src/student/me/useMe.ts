import { useQuery } from "@tanstack/react-query";
import { meApi } from "./api";

export function useMyAchievements() {
  return useQuery({ queryKey: ["student", "me", "achievements"], queryFn: meApi.achievements });
}
