import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import CaptionPage from "./components/CaptionPage.jsx";
import "./styles.css";

/**
 * `/?legenda=<id>` monta so a pagina da legenda -- e o destino do QR code, uma
 * tela de leitura rapida no celular. A decisao fica aqui, e nao dentro do App,
 * porque um return condicional antes dos hooks do App quebraria as regras dos
 * hooks assim que alguem adicionasse navegacao no cliente.
 */
function raiz() {
  let legendaId = "";
  try {
    legendaId = new URLSearchParams(window.location.search).get("legenda") || "";
  } catch (_) {
    legendaId = "";
  }
  return legendaId ? <CaptionPage outputId={legendaId} /> : <App />;
}

createRoot(document.getElementById("root")).render(
  <React.StrictMode>{raiz()}</React.StrictMode>
);
