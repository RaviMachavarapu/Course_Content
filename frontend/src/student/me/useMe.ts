import { useQuery } from "@tanstack/react-query";
import { meApi } from "./api";

export function useMyProgress() {
  return useQuery({ queryKey: ["student", "me", "progress"], queryFn: meApi.progress });
}

export function useMyListening() {
  return useQuery({ queryKey: ["student", "me", "listening"], queryFn: meApi.listening });
}

export function useMyAchievements() {
  return useQuery({ queryKey: ["student", "me", "achievements"], queryFn: meApi.achievements });
}
