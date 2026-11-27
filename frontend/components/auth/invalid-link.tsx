import { LinkIcon } from "lucide-react";
import Link from "next/link";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";

/** Expired, used or revoked invite/reset link. The API message says "Ask HR for a new link". */
export function InvalidLink({ message }: { message: string }) {
  return (
    <EmptyState
      icon={<LinkIcon className="size-6" />}
      title="This link can't be used"
      description={message}
      action={
        <Button asChild variant="outline">
          <Link href="/login">Go to sign in</Link>
        </Button>
      }
    />
  );
}
