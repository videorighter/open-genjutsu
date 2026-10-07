import "@fontsource-variable/dm-sans";
import "@fontsource-variable/space-grotesk";
import "@fontsource-variable/noto-sans-kr";
import React from "react";
import ReactDOM from "react-dom/client";
import "@xyflow/react/dist/style.css";
import App from "./App";
import ServiceApp from "./ServiceApp";
import "./styles.css";
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {import.meta.env.VITE_EDITOR_ONLY === "true" ? <App /> : <ServiceApp />}
  </React.StrictMode>,
);
