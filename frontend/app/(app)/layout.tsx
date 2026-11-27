import { Guarded } from "@/components/layout/guards";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <Guarded area="app">{children}</Guarded>;
}
