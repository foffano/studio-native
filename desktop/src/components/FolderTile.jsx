import React from "react";
import LazyVideo from "./LazyVideo.jsx";
import { libraryThumbnailUrl, libraryVideoUrl } from "../api.js";

/**
 * Uma pasta na grade da Biblioteca, com uma amostra do que tem dentro.
 *
 * Mostra até quatro miniaturas em mosaico. Quatro porque é o que cabe num
 * quadrado sem virar confete — a amostra serve para reconhecer a pasta de
 * relance, não para inventariar o conteúdo.
 */
export default function FolderTile({ pasta, amostra = [], total = 0, onAbrir, arrastandoSobre, ...dnd }) {
  return (
    <div
      className={"pastile" + (arrastandoSobre ? " pastile--alvo" : "")}
      {...dnd}
    >
      <button className="pastile__abrir" onClick={onAbrir} title={`Abrir ${pasta.name}`}>
        <div className="pastile__mosaico">
          {amostra.slice(0, 4).map((i) => (
            <div className="pastile__celula" key={i.id}>
              {i.file && (
                <LazyVideo
                  src={libraryVideoUrl(i.file)}
                  poster={libraryThumbnailUrl(i.id)}
                />
              )}
            </div>
          ))}
          {amostra.length === 0 && <div className="pastile__vazia">pasta vazia</div>}
        </div>
        <div className="pastile__nome" title={pasta.name}>
          {pasta.name}
        </div>
        <div className="pastile__conta">
          {total} {total === 1 ? "vídeo" : "vídeos"}
        </div>
      </button>
    </div>
  );
}
