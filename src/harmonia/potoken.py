from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PoTokenResult:
    """BotGuard tokens used by a web InnerTube playback request.

    ``player_request_token`` is visitor-data-bound and belongs in
    ``serviceIntegrityDimensions.poToken``. ``streaming_data_token`` is
    video-id-bound and is appended to Googlevideo/HLS URLs as ``pot``.
    """

    player_request_token: str
    streaming_data_token: str
    visitor_data: str


class PoTokenProvider(Protocol):
    def get_po_token(
        self,
        video_id: str,
        visitor_data: str,
        cookie: str | None = None,
        *,
        timeout: float = 50.0,
    ) -> PoTokenResult | None: ...

    def close(self) -> None: ...


_PROVIDER: PoTokenProvider | None = None
_PROVIDER_LOCK = threading.Lock()


def install_potoken_provider(provider: PoTokenProvider | None) -> None:
    global _PROVIDER
    with _PROVIDER_LOCK:
        previous = _PROVIDER
        _PROVIDER = provider
    if previous is not None and previous is not provider:
        try:
            previous.close()
        except Exception:
            pass


def current_potoken_provider() -> PoTokenProvider | None:
    with _PROVIDER_LOCK:
        return _PROVIDER


def get_po_token(
    video_id: str,
    visitor_data: str,
    cookie: str | None = None,
    *,
    timeout: float = 50.0,
) -> PoTokenResult | None:
    provider = current_potoken_provider()
    if provider is None or not video_id or not visitor_data:
        return None
    return provider.get_po_token(video_id, visitor_data, cookie, timeout=timeout)


# Browser-side BotGuard implementation based on the same public protocol used by
# Metrolist/Zemer. Network requests stay restricted to YouTube's JNN endpoints;
# the generated page is off-the-record and never receives the account cookie.
POTOKEN_HTML = r'''<!doctype html>
<meta charset="utf-8">
<script>
'use strict';
const HARMONIA_API_KEY = 'AIzaSyDyT5W0Jh49F30Pqqtyfdf7pDLFKLJoAnw';
const HARMONIA_REQUEST_KEY = 'O43z0dpjhgX20SCx4KAo';
window.harmoniaPoState = {
  ready: false, initializing: false, error: '', expiresAt: 0,
  results: Object.create(null), resultErrors: Object.create(null)
};
let bgVmFunctions = null;
let bgVm = null;
let bgProgram = null;
let poTokenMinter = null;

function hB64Bytes(value) {
  let text = String(value || '').replace(/-/g, '+').replace(/_/g, '/').replace(/\./g, '=');
  while (text.length % 4) text += '=';
  const raw = atob(text);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}
function hBytesB64(bytes) {
  let raw = '';
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  for (let i = 0; i < u8.length; i++) raw += String.fromCharCode(u8[i]);
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_');
}
function hStringBytes(value) { return new TextEncoder().encode(String(value)); }
function hDescramble(value) {
  const bytes = hB64Bytes(value);
  for (let i = 0; i < bytes.length; i++) bytes[i] = (bytes[i] + 97) & 255;
  return new TextDecoder().decode(bytes);
}
function hParseChallenge(raw) {
  const scrambled = JSON.parse(raw);
  const data = (scrambled.length > 1 && typeof scrambled[1] === 'string')
    ? JSON.parse(hDescramble(scrambled[1])) : scrambled[0];
  const firstString = (value) => Array.isArray(value) ? value.find(v => typeof v === 'string') : null;
  return {
    messageId: String(data[0]),
    interpreterJavascript: {
      privateDoNotAccessOrElseSafeScriptWrappedValue: firstString(data[1]),
      privateDoNotAccessOrElseTrustedResourceUrlWrappedValue: firstString(data[2])
    },
    interpreterHash: String(data[3]),
    program: String(data[4]),
    globalName: String(data[5]),
    clientExperimentsStateBlob: String(data[7])
  };
}
function loadBotGuard(challengeData) {
  bgVm = window[challengeData.globalName];
  bgProgram = challengeData.program;
  bgVmFunctions = null;
  if (!bgVm || !bgVm.a) throw new Error('BotGuard VM unavailable');
  const callback = function(asyncSnapshotFunction, shutdownFunction, passEventFunction, checkCameraFunction) {
    bgVmFunctions = {asyncSnapshotFunction, shutdownFunction, passEventFunction, checkCameraFunction};
  };
  bgVm.a(bgProgram, callback, true, undefined, function(){}, [[], []]);
  return new Promise((resolve, reject) => {
    let attempts = 0;
    const timer = setInterval(() => {
      if (bgVmFunctions && bgVmFunctions.asyncSnapshotFunction) {
        clearInterval(timer); resolve({vmFunctions: bgVmFunctions, vm: bgVm, program: bgProgram});
      } else if (++attempts >= 10000) {
        clearInterval(timer); reject(new Error('BotGuard snapshot timeout'));
      }
    }, 1);
  });
}
function snapshot(botguard) {
  return new Promise((resolve, reject) => {
    try {
      botguard.vmFunctions.asyncSnapshotFunction(response => resolve(response), [undefined, undefined, [], undefined]);
    } catch (error) { reject(error); }
  });
}
async function runBotGuard(challengeData) {
  const interpreter = challengeData.interpreterJavascript.privateDoNotAccessOrElseSafeScriptWrappedValue;
  if (!interpreter) throw new Error('BotGuard interpreter unavailable');
  new Function(interpreter)();
  const webPoSignalOutput = [];
  const botguard = await loadBotGuard(challengeData);
  const botguardResponse = await new Promise((resolve, reject) => {
    try {
      botguard.vmFunctions.asyncSnapshotFunction(response => resolve(response), [undefined, undefined, webPoSignalOutput, undefined]);
    } catch (error) { reject(error); }
  });
  return {webPoSignalOutput, botguardResponse};
}
async function createPoTokenMinter(webPoSignalOutput, integrityToken) {
  const factory = webPoSignalOutput && webPoSignalOutput[0];
  if (typeof factory !== 'function') throw new Error('PoToken minter factory unavailable');
  poTokenMinter = await factory(integrityToken);
  if (typeof poTokenMinter !== 'function') throw new Error('PoToken minter unavailable');
}
async function obtainPoToken(identifier) {
  if (typeof poTokenMinter !== 'function') throw new Error('PoToken minter not initialized');
  const result = await poTokenMinter(identifier);
  if (!(result instanceof Uint8Array)) throw new Error('PoToken result is not Uint8Array');
  return result;
}
async function hJnn(path, body) {
  const response = await fetch('https://www.youtube.com/api/jnn/v1/' + path, {
    method: 'POST',
    credentials: 'omit',
    cache: 'no-store',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json+protobuf',
      'x-goog-api-key': HARMONIA_API_KEY,
      'x-user-agent': 'grpc-web-javascript/0.1'
    },
    body
  });
  if (!response.ok) throw new Error('BotGuard HTTP ' + response.status);
  return await response.text();
}
async function harmoniaInitialize() {
  const state = window.harmoniaPoState;
  if (state.initializing) return;
  state.initializing = true; state.ready = false; state.error = '';
  try {
    const createRaw = await hJnn('Create', '["' + HARMONIA_REQUEST_KEY + '"]');
    const challenge = hParseChallenge(createRaw);
    const run = await runBotGuard(challenge);
    const integrityRaw = await hJnn('GenerateIT', JSON.stringify([HARMONIA_REQUEST_KEY, String(run.botguardResponse)]));
    const integrity = JSON.parse(integrityRaw);
    const tokenBytes = hB64Bytes(integrity[0]);
    const lifetime = Math.max(60, Number(integrity[1]) || 3600);
    await createPoTokenMinter(run.webPoSignalOutput, tokenBytes);
    state.expiresAt = Date.now() + Math.max(60, lifetime - 600) * 1000;
    state.ready = true;
  } catch (error) {
    state.error = String(error && (error.stack || error.message) || error);
    state.ready = false;
  } finally { state.initializing = false; }
}
async function harmoniaGenerate(identifier, requestId) {
  const state = window.harmoniaPoState;
  delete state.results[requestId]; delete state.resultErrors[requestId];
  try {
    if (!state.ready || Date.now() >= state.expiresAt) throw new Error('PoToken generator expired');
    const token = await obtainPoToken(hStringBytes(identifier));
    state.results[requestId] = hBytesB64(token);
  } catch (error) {
    state.resultErrors[requestId] = String(error && (error.stack || error.message) || error);
  }
}
</script>'''
