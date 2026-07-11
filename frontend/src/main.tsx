import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import { Providers } from "./app/providers";

const root = document.getElementById("root");
if (!root) throw new Error("Root element not found");

console.log("MODE:", import.meta.env.MODE);
console.log("PROD:", import.meta.env.PROD);
console.log("VITE_API_BASE_URL:", import.meta.env.VITE_API_BASE_URL);

createRoot(root).render(
  <StrictMode>
    <Providers />
  </StrictMode>
);
