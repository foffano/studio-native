"""Conexao passiva de DevTools ao navegador do TikTok Seller.

Mesmo desenho do eco-native: o navegador e dirigido pelo Playwright numa thread
so (a automacao), e o painel olha por uma segunda conexao, crua, pelo protocolo
do DevTools. Uma segunda conexao do Playwright nao serve -- ela se prende a
todas as abas e brigaria com a automacao. Esta so tira foto da aba, le o estado
dela e repassa o mouse e o teclado de quem esta vendo.
"""
import base64
import itertools
import json
import time
import urllib.request

from websockets.sync.client import connect

BUTTON_MASKS = {"left": 1, "right": 2, "middle": 4}
MODIFIER_MASKS = {"Alt": 1, "Control": 2, "Meta": 4, "Shift": 8}
# tecla: (code, windowsVirtualKeyCode, texto)
SPECIAL_KEYS = {
    "Enter": ("Enter", 13, "\r"),
    "Tab": ("Tab", 9, ""),
    "Backspace": ("Backspace", 8, ""),
    "Delete": ("Delete", 46, ""),
    "Escape": ("Escape", 27, ""),
    "ArrowLeft": ("ArrowLeft", 37, ""),
    "ArrowUp": ("ArrowUp", 38, ""),
    "ArrowRight": ("ArrowRight", 39, ""),
    "ArrowDown": ("ArrowDown", 40, ""),
    "Home": ("Home", 36, ""),
    "End": ("End", 35, ""),
    "PageUp": ("PageUp", 33, ""),
    "PageDown": ("PageDown", 34, ""),
}


class CdpError(RuntimeError):
    pass


class CdpBrowser:
    """Uma aba por vez do navegador, pelo socket cru do DevTools."""

    def __init__(self, endpoint, timeout=10.0):
        with urllib.request.urlopen(f"{endpoint}/json/version", timeout=timeout) as resp:
            socket_url = json.load(resp)["webSocketDebuggerUrl"]
        self._socket = connect(socket_url, max_size=None, open_timeout=timeout)
        self._ids = itertools.count(1)
        self._session = None
        self.target = None
        self._x = 0.0
        self._y = 0.0
        self._pressed = None

    def close(self):
        try:
            self._socket.close()
        except Exception:  # noqa: BLE001
            pass

    def call(self, method, params=None, *, page=True, timeout=10.0):
        message_id = next(self._ids)
        message = {"id": message_id, "method": method, "params": params or {}}
        if page:
            if not self._session:
                raise CdpError("A aba foi fechada")
            message["sessionId"] = self._session
        self._socket.send(json.dumps(message))
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CdpError(f"{method}: tempo esgotado")
            reply = json.loads(self._socket.recv(timeout=remaining))
            if (
                reply.get("method") == "Target.detachedFromTarget"
                and reply["params"].get("sessionId") == self._session
            ):
                self._session = None
            if reply.get("id") == message_id:
                if "error" in reply:
                    raise CdpError(f"{method}: {reply['error'].get('message')}")
                return reply.get("result", {})

    # -- abas ---------------------------------------------------------------

    def tabs(self):
        """As abas de pagina abertas, na ordem em que o navegador as criou."""
        targets = self.call("Target.getTargets", page=False)["targetInfos"]
        return [
            {"id": t["targetId"], "url": t.get("url", ""), "title": t.get("title", "")}
            for t in targets
            if t["type"] == "page" and not t.get("url", "").startswith("devtools://")
        ]

    def attach(self, target_id):
        if target_id == self.target and self._session:
            return
        if self._session:
            try:
                self.call("Target.detachFromTarget", {"sessionId": self._session}, page=False)
            except CdpError:
                pass
            self._session = None
        self._session = self.call(
            "Target.attachToTarget", {"targetId": target_id, "flatten": True}, page=False
        )["sessionId"]
        self.target = target_id
        # Sob o Xvfb so a aba da frente pinta; sem trazer para frente, a foto
        # de uma aba de tras demora ate estourar o tempo.
        try:
            self.call("Target.activateTarget", {"targetId": target_id}, page=False)
        except CdpError:
            pass

    @property
    def attached(self):
        return self._session is not None

    # -- pagina -------------------------------------------------------------

    def evaluate(self, expression):
        result = self.call("Runtime.evaluate", {"expression": expression, "returnByValue": True})
        return result.get("result", {}).get("value")

    def screenshot(self, quality=68, timeout=5.0):
        data = self.call(
            "Page.captureScreenshot", {"format": "jpeg", "quality": quality}, timeout=timeout
        )["data"]
        return base64.b64decode(data)

    def navigate(self, url):
        self.call("Page.navigate", {"url": url})

    def reload(self):
        self.call("Page.reload", {})

    def back(self):
        self.evaluate("history.back()")

    # -- mouse --------------------------------------------------------------

    def _mouse(self, kind, **params):
        self.call("Input.dispatchMouseEvent", {"type": kind, "x": self._x, "y": self._y, **params})

    def move(self, x, y):
        self._x, self._y = float(x), float(y)
        # Arrasto precisa do botao em cada movimento, senao a pagina nao o ve
        # como arrasto (quebra-cabeca de deslizar).
        self._mouse(
            "mouseMoved",
            button=self._pressed or "none",
            buttons=BUTTON_MASKS.get(self._pressed, 0),
        )

    def down(self, button="left"):
        self._pressed = button
        self._mouse("mousePressed", button=button, buttons=BUTTON_MASKS[button], clickCount=1)

    def up(self, button="left"):
        self._pressed = None
        self._mouse("mouseReleased", button=button, buttons=0, clickCount=1)

    def click(self, x, y, button="left"):
        self.move(x, y)
        self.down(button)
        self.up(button)

    def wheel(self, delta_x, delta_y):
        self._mouse("mouseWheel", deltaX=float(delta_x), deltaY=float(delta_y))

    # -- teclado ------------------------------------------------------------

    def insert_text(self, text):
        self.call("Input.insertText", {"text": text})

    def press(self, combo):
        *modifiers, key = combo.split("+") if combo != "+" else ["+"]
        mask = sum(MODIFIER_MASKS.get(name, 0) for name in modifiers)
        if key in SPECIAL_KEYS:
            code, virtual_key, text = SPECIAL_KEYS[key]
        elif len(key) == 1:
            code = f"Key{key.upper()}" if key.isalpha() else ""
            virtual_key = ord(key.upper())
            # Com Control/Meta a tecla e atalho, nao texto digitado.
            text = "" if mask & (MODIFIER_MASKS["Control"] | MODIFIER_MASKS["Meta"]) else key
        else:
            return
        event = {"key": key, "code": code, "windowsVirtualKeyCode": virtual_key, "modifiers": mask}
        self.call(
            "Input.dispatchKeyEvent",
            {"type": "keyDown" if text else "rawKeyDown", "text": text, **event},
        )
        self.call("Input.dispatchKeyEvent", {"type": "keyUp", **event})
