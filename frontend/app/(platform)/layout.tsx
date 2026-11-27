import { Guarded } from "@/components/layout/guards";

export default function PlatformLayout({ children }: { children: React.ReactNode }) {
  return <Guarded area="platform">{children}</Guarded>;
}
