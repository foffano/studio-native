import React, { useEffect, useRef, useState } from "react";

/**
 * Vídeo que só busca dados quando chega perto da tela.
 *
 * O problema que ele resolve: os grids da Biblioteca e de Produzidos montam um
 * `<video preload="metadata">` por item. Com 86 vídeos, são 86 requisições de
 * metadados disparadas de uma vez no carregamento — e o resultado visível é a
 * miniatura preta, porque o navegador não dá conta e desiste de várias.
 *
 * A orientação de UX é parar o trabalho fora da tela e reservar o espaço para
 * não deslocar o layout. É o que este componente faz: `preload="none"` até o
 * elemento entrar no campo de visão, e a proporção fixada desde o início.
 *
 * Não é lazy-loading do arquivo inteiro — é dos metadados. O vídeo em si só é
 * baixado quando alguém dá play.
 */
export default function LazyVideo({
  src,
  controls = false,
  className = "",
  // Sem valor por padrao: o contentor de cada tela ja define a sua proporcao
  // (16/9 na Biblioteca, 9/16 em Produzidos). Impor uma aqui aninhava duas
  // razoes de aspecto e esticava os cartoes.
  proporcao = null,
  onError,
}) {
  const ref = useRef(null);
  const [visivel, setVisivel] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    // Sem IntersectionObserver (navegador antigo), carrega tudo: pior para a
    // rede, mas melhor do que uma grade de retângulos vazios.
    if (typeof IntersectionObserver === "undefined") {
      setVisivel(true);
      return;
    }

    const obs = new IntersectionObserver(
      (entradas) => {
        if (entradas.some((e) => e.isIntersecting)) {
          setVisivel(true);
          obs.disconnect(); // uma vez carregado, não precisa mais observar
        }
      },
      // 200px de antecedência: o vídeo já chega pronto quando entra na tela,
      // em vez de aparecer em branco e preencher depois.
      { rootMargin: "200px" }
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  return (
    <div
      ref={ref}
      className={className}
      // Espaço reservado desde o primeiro quadro: sem isto a grade pula quando
      // cada vídeo carrega, e o clique do usuário cai no item errado.
      // `position: absolute` preenchendo o pai, e nao `height: 100%`: o video
      // tem dimensao intrinseca, e com altura percentual ele ESTICA o pai em vez
      // de obedecer a proporcao dele. Medido na Biblioteca: o contentor
      // declarava 16/9 no CSS e renderizava 9/16 (238x423). Absoluto, o video
      // nao participa do calculo de altura do pai.
      style={{
        position: "absolute",
        inset: 0,
        background: "var(--surface-2)",
      }}
    >
      {visivel && (
        <video
          src={src}
          controls={controls}
          muted={!controls}
          preload="metadata"
          onError={onError}
          style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }}
        />
      )}
    </div>
  );
}
