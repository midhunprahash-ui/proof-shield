import type {
  Assessment,
  CaseHistoryEntry,
  CaseSummary,
  CaseWorkspaceData,
  DisputeCase,
  DraftReview,
  EvidenceDocument,
  EvidenceFileMetadata,
  EvidenceSubmission,
  OperatorIdentity,
  ResponseDraft,
  ReviewDecision,
} from "./types";

type Fetcher = typeof fetch;

interface RequestOptions extends RequestInit {
}

interface ReviewInput {
  decision: ReviewDecision;
  note?: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ProofShieldApi {
  constructor(
    private readonly baseUrl: string,
    private readonly fetcher: Fetcher = fetch,
    private readonly accessToken: () => string | null = () => null,
  ) {}

  getOperator(signal?: AbortSignal): Promise<OperatorIdentity> {
    return this.request<OperatorIdentity>(
      "/v1/auth/me",
      signal ? { signal } : {},
    );
  }

  listCases(signal?: AbortSignal): Promise<CaseSummary[]> {
    return this.request<CaseSummary[]>(
      "/v1/cases",
      signal ? { signal } : {},
    );
  }

  listUnassignedCases(signal?: AbortSignal): Promise<CaseSummary[]> {
    return this.request<CaseSummary[]>(
      "/v1/cases/unassigned",
      signal ? { signal } : {},
    );
  }

  claimCase(disputeId: string): Promise<DisputeCase> {
    return this.request<DisputeCase>(
      `/v1/cases/${encodeURIComponent(disputeId)}/claim`,
      { method: "POST" },
    );
  }

  async getWorkspace(
    disputeId: string,
    signal?: AbortSignal,
  ): Promise<CaseWorkspaceData> {
    const path = `/v1/cases/${encodeURIComponent(disputeId)}`;
    const requestOptions = signal ? { signal } : {};
    const [caseData, files, drafts, history] = await Promise.all([
      this.request<DisputeCase>(path, requestOptions),
      this.request<EvidenceFileMetadata[]>(`${path}/files`, requestOptions),
      this.request<ResponseDraft[]>(`${path}/drafts`, requestOptions),
      this.request<CaseHistoryEntry[]>(`${path}/history`, requestOptions),
    ]);
    return { case: caseData, files, drafts, history };
  }

  assess(disputeId: string): Promise<Assessment> {
    return this.request<Assessment>(
      `/v1/cases/${encodeURIComponent(disputeId)}/assessment`,
      { method: "POST" },
    );
  }

  createDraft(disputeId: string): Promise<ResponseDraft> {
    return this.request<ResponseDraft>(
      `/v1/cases/${encodeURIComponent(disputeId)}/drafts`,
      { method: "POST" },
    );
  }

  getReview(
    disputeId: string,
    draftId: string,
    signal?: AbortSignal,
  ): Promise<DraftReview> {
    return this.request<DraftReview>(
      this.draftPath(disputeId, draftId, "/review"),
      signal ? { signal } : {},
    );
  }

  reviewDraft(
    disputeId: string,
    draftId: string,
    input: ReviewInput,
  ): Promise<DraftReview> {
    return this.request<DraftReview>(
      this.draftPath(disputeId, draftId, "/reviews"),
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          decision: input.decision,
          note: input.note || null,
        }),
      },
    );
  }

  async downloadPacket(
    disputeId: string,
    draftId: string,
  ): Promise<{ blob: Blob; packetSha256: string; manifestSha256: string }> {
    const token = this.accessToken();
    const headers = new Headers();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await this.fetcher.call(
      globalThis,
      `${this.baseUrl}${this.draftPath(disputeId, draftId, "/packet")}`,
      {
        headers,
      },
    );
    if (!response.ok) throw await this.toApiError(response);
    return {
      blob: await response.blob(),
      packetSha256: response.headers.get("X-ProofShield-Packet-SHA256") ?? "",
      manifestSha256:
        response.headers.get("X-ProofShield-Manifest-SHA256") ?? "",
    };
  }

  async uploadFile(disputeId: string, file: File): Promise<EvidenceFileMetadata> {
    const body = new FormData();
    body.append("file", file);
    return this.request<EvidenceFileMetadata>(
      `/v1/cases/${encodeURIComponent(disputeId)}/files`,
      { method: "POST", body },
    );
  }

  addEvidence(
    disputeId: string,
    submission: EvidenceSubmission,
  ): Promise<EvidenceDocument> {
    return this.request<EvidenceDocument>(
      `/v1/cases/${encodeURIComponent(disputeId)}/evidence`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(submission),
      },
    );
  }

  private draftPath(disputeId: string, draftId: string, suffix: string): string {
    return `/v1/cases/${encodeURIComponent(disputeId)}/drafts/${encodeURIComponent(draftId)}${suffix}`;
  }

  private async request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    const headers = new Headers(options.headers);
    const token = this.accessToken();
    if (token) headers.set("Authorization", `Bearer ${token}`);
    const response = await this.fetcher.call(globalThis, `${this.baseUrl}${path}`, {
      ...options,
      headers,
    });
    if (!response.ok) throw await this.toApiError(response);
    return (await response.json()) as T;
  }

  private async toApiError(response: Response): Promise<ApiError> {
    let message = `Request failed with HTTP ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") message = payload.detail;
      if (Array.isArray(payload.detail)) {
        message = payload.detail
          .map((item) => {
            if (typeof item === "object" && item !== null && "msg" in item) {
              return String(item.msg);
            }
            return String(item);
          })
          .join("; ");
      }
    } catch {
      // Preserve the HTTP fallback when the response is not JSON.
    }
    return new ApiError(message, response.status);
  }
}

export function apiUrlFromDocument(documentValue: Document = document): string {
  const configured = documentValue
    .querySelector<HTMLMetaElement>('meta[name="proofshield-api-url"]')
    ?.content.trim();
  return (configured || "http://127.0.0.1:8000").replace(/\/$/, "");
}
