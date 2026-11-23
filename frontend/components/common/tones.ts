import type { Tone } from "@/components/ui/primitives";

export const COMPANY_TONE: Record<string, Tone> = { ACTIVE: "success", SUSPENDED: "warning", DELETED: "danger" };
export const USER_TONE: Record<string, Tone> = { ACTIVE: "success", INVITED: "info", DEACTIVATED: "neutral" };
export const INVITE_TONE: Record<string, Tone> = {
  pending: "info",
  expired: "warning",
  used: "success",
  revoked: "neutral",
  none: "neutral",
};
export const TIMESHEET_TONE: Record<string, Tone> = {
  OPEN: "neutral",
  SUBMITTED: "info",
  APPROVED: "success",
  REJECTED: "danger",
};
