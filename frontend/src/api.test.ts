import { describe, expect, test } from "bun:test";

import { apiUrlFromDocument, ApiError, ProofShieldApi } from "./api";

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
    status,
  });
}

describe("ProofShieldApi", () => {
  test("loads the six case workspace resources in parallel", async () => {
    const requested: string[] = [];
    const fetcher = (async (input: RequestInfo | URL) => {
      const url = String(input);
      requested.push(url);
      if (url.endsWith("/consistency")) {
        return jsonResponse({ dispute_id: "dp_123", status: "INCOMPLETE" });
      }
      if (url.endsWith("/files")) return jsonResponse([]);
      if (url.endsWith("/resolutions")) return jsonResponse([]);
      if (url.endsWith("/drafts")) return jsonResponse([]);
      if (url.endsWith("/history")) return jsonResponse([]);
      return jsonResponse({ dispute_id: "dp_123" });
    }) as typeof fetch;
    const api = new ProofShieldApi("http://api.local", fetcher);

    const workspace = await api.getWorkspace("dp_123");

    expect(workspace.case.dispute_id).toBe("dp_123");
    expect(workspace.consistency.status).toBe("INCOMPLETE");
    expect(workspace.resolutions).toEqual([]);
    expect(requested).toHaveLength(6);
    expect(new Set(requested)).toEqual(
      new Set([
        "http://api.local/v1/cases/dp_123",
        "http://api.local/v1/cases/dp_123/consistency",
        "http://api.local/v1/cases/dp_123/files",
        "http://api.local/v1/cases/dp_123/resolutions",
        "http://api.local/v1/cases/dp_123/drafts",
        "http://api.local/v1/cases/dp_123/history",
      ]),
    );
  });

  test("records a resolution without sending caller-controlled identity", async () => {
    let requestedUrl = "";
    let requestedBody = "";
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestedUrl = String(input);
      requestedBody = String(init?.body ?? "");
      return jsonResponse({ resolution_id: "resolution_1" }, 201);
    }) as typeof fetch;
    const api = new ProofShieldApi("http://api.local", fetcher, () => "token");

    await api.resolveEvidence("dp_1", {
      evidence_id: "invoice_bad",
      action: "EXCLUDED_INCORRECT",
      reason: "Checked against the original order and found it was unrelated.",
    });

    expect(requestedUrl).toBe("http://api.local/v1/cases/dp_1/resolutions");
    expect(JSON.parse(requestedBody)).toEqual({
      evidence_id: "invoice_bad",
      action: "EXCLUDED_INCORRECT",
      reason: "Checked against the original order and found it was unrelated.",
    });
    expect(requestedBody.includes("resolved_by")).toBe(false);
  });

  test("sends the Supabase bearer token and not a reviewer identity in the body", async () => {
    let captured: RequestInit | undefined;
    const fetcher = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      captured = init;
      return jsonResponse({
        review_id: "review_1",
        decision: "APPROVED",
      });
    }) as typeof fetch;
    const api = new ProofShieldApi(
      "http://api.local",
      fetcher,
      () => "verified-access-token",
    );

    await api.getReview("dp_1", "draft_1");

    expect(new Headers(captured?.headers).get("Authorization")).toBe(
      "Bearer verified-access-token",
    );
    expect(captured?.body).toBeUndefined();
  });

  test("review decisions contain no caller-controlled reviewer label", async () => {
    let body = "";
    const fetcher = (async (_input: RequestInfo | URL, init?: RequestInit) => {
      body = String(init?.body ?? "");
      return jsonResponse({ review_id: "review_1", decision: "APPROVED" });
    }) as typeof fetch;
    const api = new ProofShieldApi(
      "http://api.local",
      fetcher,
      () => "verified-access-token",
    );

    await api.reviewDraft("dp_1", "draft_1", {
      decision: "APPROVED",
      note: "Checked against source files.",
    });

    expect(JSON.parse(body)).toEqual({
      decision: "APPROVED",
      note: "Checked against source files.",
    });
    expect(body.includes("reviewer_label")).toBe(false);
  });

  test("lists and claims unassigned webhook cases with bearer auth", async () => {
    const requested: Array<{ url: string; method: string; authorization: string | null }> = [];
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requested.push({
        url: String(input),
        method: init?.method ?? "GET",
        authorization: new Headers(init?.headers).get("Authorization"),
      });
      return String(input).endsWith("/claim")
        ? jsonResponse({ dispute_id: "dp_claim" })
        : jsonResponse([{ dispute_id: "dp_claim" }]);
    }) as typeof fetch;
    const api = new ProofShieldApi(
      "http://api.local",
      fetcher,
      () => "verified-access-token",
    );

    await api.listUnassignedCases();
    await api.claimCase("dp_claim");

    expect(requested).toEqual([
      {
        url: "http://api.local/v1/cases/unassigned",
        method: "GET",
        authorization: "Bearer verified-access-token",
      },
      {
        url: "http://api.local/v1/cases/dp_claim/claim",
        method: "POST",
        authorization: "Bearer verified-access-token",
      },
    ]);
  });

  test("requests an extraction proposal without claiming it is verified", async () => {
    let requestedUrl = "";
    let requestedBody = "";
    const fetcher = (async (input: RequestInfo | URL, init?: RequestInit) => {
      requestedUrl = String(input);
      requestedBody = String(init?.body ?? "");
      return jsonResponse({
        proposal_id: "extract_test",
        human_confirmation_required: true,
        claims: [],
      });
    }) as typeof fetch;
    const api = new ProofShieldApi("http://api.local", fetcher, () => "token");

    const proposal = await api.extractEvidence("dp_1", "file_1", "INVOICE");

    expect(requestedUrl).toBe(
      "http://api.local/v1/cases/dp_1/files/file_1/extract",
    );
    expect(JSON.parse(requestedBody)).toEqual({ evidence_type: "INVOICE" });
    expect(proposal.human_confirmation_required).toBe(true);
    expect("source_verified" in proposal).toBe(false);
  });

  test("surfaces FastAPI validation detail as a readable error", async () => {
    const fetcher = (async () =>
      jsonResponse(
        { detail: [{ msg: "Field required" }, { msg: "Invalid amount" }] },
        422,
      )) as unknown as typeof fetch;
    const api = new ProofShieldApi("http://api.local", fetcher);

    let caught: unknown;
    try {
      await api.listCases();
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    expect((caught as ApiError).status).toBe(422);
    expect((caught as ApiError).message).toBe("Field required; Invalid amount");
  });

  test("reads and normalizes the backend URL from document metadata", () => {
    const fakeDocument = {
      querySelector: () => ({ content: "http://127.0.0.1:8000/" }),
    } as unknown as Document;

    expect(apiUrlFromDocument(fakeDocument)).toBe("http://127.0.0.1:8000");
  });
});
