import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApiError } from "../lib/api";
import { ErrorState } from "./states";

describe("ErrorState", () => {
  it("shows a missing vendor key as a connect state, naming the key", () => {
    const err = new ApiError(503, {
      error: "provider_not_configured",
      kind: "telephony",
      provider: "vobiz",
      missing_keys: ["VOBIZ_AUTH_ID", "VOBIZ_AUTH_TOKEN"],
      detail: "Vobiz is not configured",
    });
    render(<ErrorState error={err} />);
    expect(screen.getByRole("status").textContent).toContain("Connect Vobiz to use this");
    expect(screen.getByText("VOBIZ_AUTH_TOKEN")).toBeTruthy();
  });

  it("shows any other failure as an alert with the API's message", () => {
    render(<ErrorState error={new ApiError(409, { detail: "Number already taken" })} />);
    expect(screen.getByRole("alert").textContent).toContain("Number already taken");
  });
});
