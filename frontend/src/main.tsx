// First, before any resource is declared: the views need their router and
// their dialect in place by the time `createViewResource` runs.
import "./lib/resource-view"

import { StrictMode } from "react"
import { createRoot } from "react-dom/client"

import App from "./App"
import "./index.css"

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>
)
