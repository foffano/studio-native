/**
 * Troca de tokens do TikTok — Cloudflare Worker.
 *
 * Existe por um motivo só: o `client_secret` do TikTok não pode viajar dentro
 * do .exe do Studio Native (qualquer pessoa abre o pacote do Electron e lê).
 * Este Worker guarda o segredo e faz a troca do `code` por token em nome do
 * app.
 *
 * O que ele deliberadamente NÃO faz:
 *   - não armazena tokens (repassa a resposta e esquece);
 *   - não recebe, guarda nem vê nenhum vídeo — o MP4 vai direto do computador
 *     do usuário para o TikTok. É isso que mantém o serviço no plano gratuito
 *     para sempre: armazenamento e tráfego de vídeo é que custariam caro;
 *   - não registra corpo de requisição nem token em log.
 *
 * Rotas:
 *   GET  /tiktok/client-key                                     -> client_key
 *   POST /tiktok/token     { code, code_verifier, redirect_uri } -> tokens
 *   POST /tiktok/refresh   { refresh_token }                     -> tokens
 *   GET  /tiktok/callback  (fallback) devolve o code ao loopback do app
 *   GET  /health
 */

const TIKTOK_TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/";

// Só estes destinos são aceitos. O TikTok já valida o redirect_uri contra o
// que está registrado no portal; isto é a segunda tranca, para o Worker não
// poder ser usado como peça de um fluxo de terceiros.
const ALLOWED_REDIRECTS = [
  "http://127.0.0.1:43117/api/tiktok/callback",
  "http://localhost:43117/api/tiktok/callback",
];

// Porta fixa que o backend do app escuta para receber o callback.
const LOOPBACK_PORT = 43117;

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      // Sem CORS permissivo de propósito: quem chama é o app desktop, não um
      // navegador. Liberar origens só aumentaria a superfície de abuso.
      "cache-control": "no-store",
      "referrer-policy": "no-referrer",
    },
  });
}

async function readJson(request) {
  try {
    const body = await request.json();
    return body && typeof body === "object" ? body : {};
  } catch (_) {
    return {};
  }
}

/** Repassa a troca ao TikTok e devolve a resposta crua ao app. */
async function exchange(env, params) {
  const form = new URLSearchParams({
    client_key: env.TIKTOK_CLIENT_KEY,
    client_secret: env.TIKTOK_CLIENT_SECRET,
    ...params,
  });

  const res = await fetch(TIKTOK_TOKEN_URL, {
    method: "POST",
    headers: {
      "content-type": "application/x-www-form-urlencoded",
      "cache-control": "no-cache",
    },
    body: form,
  });

  const text = await res.text();
  let data;
  try {
    data = JSON.parse(text);
  } catch (_) {
    // O TikTok devolveu algo que não é JSON (página de erro, manutenção).
    return json(
      { error: "resposta_invalida", message: text.slice(0, 300) },
      502
    );
  }

  // Repassa o status para o app conseguir distinguir erro do TikTok de erro
  // nosso. Nada é registrado em log.
  return json(data, res.ok ? 200 : res.status);
}

/**
 * Devolve o `client_key` ao app.
 *
 * O client_key não é segredo — ele aparece na URL de autorização, qualquer um
 * lê. Mora aqui mesmo assim para que as credenciais do TikTok existam em um
 * lugar só: embutido no .exe, rotacionar a chave exigiria liberar uma versão
 * nova para todos os usuários. O app já precisa falar com este Worker para
 * trocar o code por token, então não há requisição de rede nova no caminho.
 */
function handleClientKey(env) {
  return json({
    client_key: env.TIKTOK_CLIENT_KEY,
    scopes: "user.info.basic,video.upload",
    redirect_uri: ALLOWED_REDIRECTS[0],
  });
}

async function handleToken(request, env) {
  const { code, code_verifier, redirect_uri } = await readJson(request);

  if (!code) return json({ error: "code_ausente" }, 400);
  if (!redirect_uri || !ALLOWED_REDIRECTS.includes(redirect_uri)) {
    return json({ error: "redirect_uri_nao_permitido" }, 400);
  }

  return exchange(env, {
    code,
    grant_type: "authorization_code",
    redirect_uri,
    ...(code_verifier ? { code_verifier } : {}),
  });
}

async function handleRefresh(request, env) {
  const { refresh_token } = await readJson(request);
  if (!refresh_token) return json({ error: "refresh_token_ausente" }, 400);

  return exchange(env, {
    grant_type: "refresh_token",
    refresh_token,
  });
}

/**
 * Fallback: só é usado se o portal do TikTok recusar o redirect em loopback.
 * Recebe o callback em HTTPS e devolve o usuário ao app, que escuta em
 * 127.0.0.1. O code passa pelo navegador do próprio usuário, nunca pelo
 * armazenamento do Worker.
 */
function handleCallback(url) {
  const code = url.searchParams.get("code") || "";
  const state = url.searchParams.get("state") || "";
  const error = url.searchParams.get("error") || "";

  const target = new URL(`http://127.0.0.1:${LOOPBACK_PORT}/api/tiktok/callback`);
  if (code) target.searchParams.set("code", code);
  if (state) target.searchParams.set("state", state);
  if (error) target.searchParams.set("error", error);

  return new Response(null, {
    status: 302,
    headers: { location: target.toString(), "cache-control": "no-store" },
  });
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") {
      return json({ ok: true, service: "studio-native-tiktok-auth" });
    }

    if (!env.TIKTOK_CLIENT_KEY || !env.TIKTOK_CLIENT_SECRET) {
      return json({ error: "servico_nao_configurado" }, 500);
    }

    if (request.method === "GET" && url.pathname === "/tiktok/client-key") {
      return handleClientKey(env);
    }

    if (request.method === "POST" && url.pathname === "/tiktok/token") {
      return handleToken(request, env);
    }

    if (request.method === "POST" && url.pathname === "/tiktok/refresh") {
      return handleRefresh(request, env);
    }

    if (request.method === "GET" && url.pathname === "/tiktok/callback") {
      return handleCallback(url);
    }

    return json({ error: "nao_encontrado" }, 404);
  },
};
