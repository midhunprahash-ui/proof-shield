import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { OperatorAuthGate } from "./components/OperatorAuthGate";

const root = document.getElementById("root");

if (!root) throw new Error("ProofShield root element is missing.");

createRoot(root).render(
  <StrictMode>
    <OperatorAuthGate>
      {({ api, operator, signOut }) => (
        <App api={api} onSignOut={signOut} operator={operator} />
      )}
    </OperatorAuthGate>
  </StrictMode>,
);
