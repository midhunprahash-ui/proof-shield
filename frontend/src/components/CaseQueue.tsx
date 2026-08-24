import { useDeferredValue, useState } from "react";

import { formatDateTime, formatMoney, shortId } from "../lib/format";
import type { CaseSummary } from "../types";
import { EmptyQueue } from "./Overview";
import { Icon } from "./Icon";
import { StatusBadge } from "./StatusBadge";

export function CaseQueue({
  cases,
  onOpenCase,
}: {
  cases: CaseSummary[];
  onOpenCase: (disputeId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const filtered = deferredQuery
    ? cases.filter((item) =>
        [item.dispute_id, item.order_id, item.payment_id].some((value) =>
          value.toLowerCase().includes(deferredQuery),
        ),
      )
    : cases;

  return (
    <section className="content-card queue-card">
      <div className="section-heading queue-heading">
        <div>
          <p className="eyebrow">Merchant operations</p>
          <h1>Dispute queue</h1>
          <p>Review evidence completeness before a response is drafted.</p>
        </div>
        <label className="search-box">
          <span className="sr-only">Search disputes</span>
          <Icon name="search" size={18} />
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search dispute, order or payment"
            type="search"
            value={query}
          />
        </label>
      </div>

      {cases.length === 0 ? (
        <EmptyQueue />
      ) : (
        <div className="table-scroll">
          <table className="case-table">
            <thead>
              <tr>
                <th scope="col">Dispute</th>
                <th scope="col">Order</th>
                <th scope="col">Evidence</th>
                <th scope="col">Updated</th>
                <th scope="col">Amount</th>
                <th aria-label="Open case" scope="col" />
              </tr>
            </thead>
            <tbody>
              {filtered.map((item) => (
                <tr key={item.dispute_id}>
                  <td>
                    <button
                      className="table-link"
                      onClick={() => onOpenCase(item.dispute_id)}
                      type="button"
                    >
                      <strong>{shortId(item.dispute_id)}</strong>
                      <span>{item.reason.replaceAll("_", " ").toLowerCase()}</span>
                    </button>
                  </td>
                  <td>
                    <strong>{shortId(item.order_id)}</strong>
                    <span>{shortId(item.payment_id)}</span>
                  </td>
                  <td>
                    <StatusBadge tone={item.evidence_count >= 2 ? "good" : "warning"}>
                      {item.evidence_count} {item.evidence_count === 1 ? "record" : "records"}
                    </StatusBadge>
                  </td>
                  <td>{formatDateTime(item.updated_at)}</td>
                  <td className="amount-cell">
                    {formatMoney(item.disputed_amount, item.currency)}
                  </td>
                  <td>
                    <button
                      aria-label={`Open dispute ${item.dispute_id}`}
                      className="icon-button subtle"
                      onClick={() => onOpenCase(item.dispute_id)}
                      type="button"
                    >
                      <Icon name="chevron" size={17} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 ? (
            <p className="no-results">No disputes match “{query}”.</p>
          ) : null}
        </div>
      )}
    </section>
  );
}
