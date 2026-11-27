import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CommentBody } from "@/components/tasks/detail-panels";

describe("CommentBody", () => {
  it("highlights mentions without showing the raw token", () => {
    render(<CommentBody body="Hi @[Mia Test](user:0b6c3c55-58e5-4a0d-9f2d-111111111111) please check" />);
    expect(screen.getByText("@Mia Test")).toBeInTheDocument();
    expect(screen.queryByText(/user:/)).not.toBeInTheDocument();
  });

  it("never interprets HTML in comments", () => {
    const payload = "<img src=x onerror=alert(1)><b>bold</b>";
    const { container } = render(<CommentBody body={payload} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(container.textContent).toContain("<img");
  });
});
