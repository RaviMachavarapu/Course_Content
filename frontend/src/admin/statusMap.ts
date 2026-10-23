import type { ChipStatus } from "@/components";

/** Map any backend status string to a UI-kit chip status. */
export function toChipStatus(status: string): ChipStatus {
  switch (status) {
    case "ready":
    case "succeeded":
      return "ready";
    case "processing":
    case "running":
    case "queued":
      return "processing";
    case "error":
    case "failed":
      return "error";
    case "published":
      return "published";
    default:
      return "pending"; // pending, pending_review, partially_published, draft, cancelled
  }
}

export const STATUS_LABELS: Record<string, string> = {
  outline_review: "Outline review",
  pending_review: "Pending Review",
  partially_published: "Partially Published",
  draft: "Draft",
};
