import { useQuery } from "@tanstack/react-query";
import { catalogApi } from "./api";

export function useCatalog() {
  return useQuery({ queryKey: ["student", "catalog"], queryFn: catalogApi.list });
}
