/**
 * As páginas são servidas direto do CDN pelos assets estáticos. Este Worker
 * existe para um caso só: com `html_handling = "none"` — necessário para que
 * `/termos.html` responda 200 no caminho exato que o portal do TikTok verifica
 * — a raiz `/` deixa de encontrar `index.html` e cairia em 404.
 *
 * Qualquer outro caminho nem chega aqui: se casa com um arquivo, o CDN
 * responde antes; se não casa, vira 404, como deve ser.
 */
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === "/") {
      return env.ASSETS.fetch(new Request(new URL("/index.html", url), request));
    }
    return env.ASSETS.fetch(request);
  },
};
