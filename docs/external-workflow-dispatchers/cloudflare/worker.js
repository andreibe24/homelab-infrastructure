const concatBytes = (...arrays) => {
  const result = new Uint8Array(arrays.reduce((length, array) => length + array.length, 0));
  let offset = 0;
  for (const array of arrays) {
    result.set(array, offset);
    offset += array.length;
  }
  return result;
};

const encodeDerLength = (length) => {
  if (length < 0x80) return Uint8Array.of(length);
  const bytes = [];
  for (let value = length; value > 0; value >>>= 8) {
    bytes.unshift(value & 0xff);
  }
  return Uint8Array.of(0x80 | bytes.length, ...bytes);
};

const base64url = (data) => {
  let binary = "";
  for (const byte of data) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};

const importPrivateKey = async (pem) => {
  const match = pem.trim().match(
    /^-----BEGIN (RSA )?PRIVATE KEY-----([\s\S]+?)-----END (?:RSA )?PRIVATE KEY-----$/,
  );
  if (!match) throw new Error("GITHUB_APP_PRIVATE_KEY must contain a PEM private key");

  const der = Uint8Array.from(atob(match[2].replace(/\s/g, "")), (char) => char.charCodeAt(0));
  let pkcs8 = der;
  if (match[1]) {
    const algorithm = Uint8Array.of(
      0x30, 0x0d, 0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x01, 0x01, 0x05, 0x00,
    );
    const privateKey = concatBytes(Uint8Array.of(0x04), encodeDerLength(der.length), der);
    const contents = concatBytes(Uint8Array.of(0x02, 0x01, 0x00), algorithm, privateKey);
    pkcs8 = concatBytes(Uint8Array.of(0x30), encodeDerLength(contents.length), contents);
  }

  return crypto.subtle.importKey(
    "pkcs8",
    pkcs8,
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["sign"],
  );
};

const githubRequest = async (url, token, options = {}) => {
  const response = await fetch(url, {
    ...options,
    headers: {
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "cloudflare-renovate-dispatch",
      ...options.headers,
      Authorization: `Bearer ${token}`,
    },
  });

  if (!response.ok) {
    throw new Error(`GitHub API request failed: ${response.status} ${await response.text()}`);
  }
  return response;
};

export default {
  async scheduled(_event, env) {
    if (!env.GITHUB_APP_ID || !env.GITHUB_INSTALLATION_ID || !env.GITHUB_APP_PRIVATE_KEY) {
      throw new Error("Configure GITHUB_APP_ID, GITHUB_INSTALLATION_ID, and GITHUB_APP_PRIVATE_KEY");
    }

    const targetRepository = env.TARGET_REPOSITORY || "andreibe24/homelab-infrastructure";
    const targetWorkflow = env.TARGET_WORKFLOW || "renovate.yaml";
    const targetRef = env.TARGET_REF || "main";
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(targetRepository)) {
      throw new Error("TARGET_REPOSITORY must be in owner/repository format");
    }
    if (!/^[A-Za-z0-9_.-]+$/.test(targetWorkflow)) {
      throw new Error("TARGET_WORKFLOW must be a workflow filename or numeric ID");
    }

    let inputs = {};
    if (env.TARGET_INPUTS_JSON) {
      try {
        inputs = JSON.parse(env.TARGET_INPUTS_JSON);
      } catch {
        throw new Error("TARGET_INPUTS_JSON must contain a JSON object");
      }
      if (inputs === null || typeof inputs !== "object" || Array.isArray(inputs)) {
        throw new Error("TARGET_INPUTS_JSON must contain a JSON object");
      }
    }

    const now = Math.floor(Date.now() / 1000);
    const header = base64url(new TextEncoder().encode(JSON.stringify({ alg: "RS256", typ: "JWT" })));
    const payload = base64url(
      new TextEncoder().encode(
        JSON.stringify({ iat: now - 60, exp: now + 540, iss: env.GITHUB_APP_ID }),
      ),
    );
    const unsigned = `${header}.${payload}`;
    const key = await importPrivateKey(env.GITHUB_APP_PRIVATE_KEY);
    const signature = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5",
      key,
      new TextEncoder().encode(unsigned),
    );
    const jwt = `${unsigned}.${base64url(new Uint8Array(signature))}`;

    const tokenResponse = await githubRequest(
      `https://api.github.com/app/installations/${encodeURIComponent(env.GITHUB_INSTALLATION_ID)}/access_tokens`,
      jwt,
      { method: "POST" },
    );
    const { token } = await tokenResponse.json();
    if (typeof token !== "string" || token.length === 0) {
      throw new Error("GitHub did not return an installation access token");
    }

    const [owner, repository] = targetRepository.split("/");
    const dispatchBody = { ref: targetRef };
    if (Object.keys(inputs).length > 0) dispatchBody.inputs = inputs;

    await githubRequest(
      `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repository)}/actions/workflows/${encodeURIComponent(targetWorkflow)}/dispatches`,
      token,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(dispatchBody),
      },
    );
  },
};
