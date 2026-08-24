export type Decision =
  | "SAFE_TO_DRAFT"
  | "NEEDS_REVIEW"
  | "INSUFFICIENT_EVIDENCE";

export type EvidenceType =
  | "INVOICE"
  | "DELIVERY_PROOF"
  | "CUSTOMER_COMMUNICATION";

export type ReviewDecision = "APPROVED" | "REJECTED";

export interface CaseSummary {
  dispute_id: string;
  payment_id: string;
  order_id: string;
  reason: string;
  disputed_amount: string;
  currency: string;
  evidence_count: number;
  updated_at: string;
}

export interface PaymentRecord {
  payment_id: string;
  order_id: string;
  amount: string;
  currency: string;
  captured: boolean;
}

export interface EvidenceDocument {
  evidence_id: string;
  evidence_type: EvidenceType;
  source_file_id: string | null;
  source_name: string | null;
  source_sha256: string | null;
  reviewed_by_human: boolean;
  source_verified: boolean;
  order_id: string | null;
  payment_id: string | null;
  amount: string | null;
  issued_at: string | null;
  delivery_status: string | null;
  customer_acknowledged_delivery: boolean | null;
  text: string | null;
}

export interface DisputeCase {
  dispute_id: string;
  reason: string;
  payment_id: string;
  order_id: string;
  disputed_amount: string;
  currency: string;
  created_at: string;
  respond_by: string;
  payment: PaymentRecord;
  evidence: EvidenceDocument[];
}

export interface EvidenceFileMetadata {
  file_id: string;
  dispute_id: string;
  original_name: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  created_at: string;
}

export interface VerificationCheck {
  code: string;
  outcome: "PASS" | "WARNING" | "FAIL";
  message: string;
}

export interface Assessment {
  dispute_id: string;
  decision: Decision;
  evidence_score: number;
  summary: string;
  checks: VerificationCheck[];
  evaluated_at: string;
  human_approval_required: boolean;
}

export interface DraftCitation {
  label: string;
  evidence_id: string;
  evidence_type: EvidenceType;
  source_file_id: string;
  source_name: string;
  source_sha256: string;
  claim: string;
}

export interface ResponseDraft {
  draft_id: string;
  dispute_id: string;
  decision: Decision;
  status: "PENDING_HUMAN_APPROVAL";
  subject: string;
  body: string;
  citations: DraftCitation[];
  generator: string;
  input_sha256: string;
  content_sha256: string;
  created_at: string;
  human_approval_required: boolean;
}

export interface DraftReview {
  review_id: string;
  dispute_id: string;
  draft_id: string;
  decision: ReviewDecision;
  reviewer_label: string;
  note: string | null;
  request_sha256: string;
  created_at: string;
}

export interface CaseHistoryEntry {
  sequence: number;
  dispute_id: string;
  action:
    | "CASE_CREATED"
    | "FILE_UPLOADED"
    | "EVIDENCE_ADDED"
    | "ASSESSED"
    | "DRAFT_CREATED"
    | "DRAFT_APPROVED"
    | "DRAFT_REJECTED";
  reference_id: string | null;
  recorded_at: string;
  detail: string;
}

export interface CaseWorkspaceData {
  case: DisputeCase;
  files: EvidenceFileMetadata[];
  drafts: ResponseDraft[];
  history: CaseHistoryEntry[];
}

export interface EvidenceSubmission {
  evidence_id: string;
  evidence_type: EvidenceType;
  source_file_id?: string;
  human_confirmed_source: boolean;
  order_id?: string;
  payment_id?: string;
  amount?: string;
  delivery_status?: string;
  customer_acknowledged_delivery?: boolean;
  text?: string;
}
