(function () {
  "use strict";

  const decoder = new TextDecoder();
  const encoder = new TextEncoder();

  function fromBase64(value) {
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);
    for (let index = 0; index < binary.length; index += 1) {
      bytes[index] = binary.charCodeAt(index);
    }
    return bytes;
  }

  async function deriveKey(password, salt, iterations) {
    const baseKey = await crypto.subtle.importKey(
      "raw",
      encoder.encode(password),
      "PBKDF2",
      false,
      ["deriveKey"],
    );
    return crypto.subtle.deriveKey(
      { name: "PBKDF2", salt, iterations, hash: "SHA-256" },
      baseKey,
      { name: "AES-GCM", length: 256 },
      false,
      ["decrypt"],
    );
  }

  async function decryptPayload(payload, password) {
    if (payload.version !== 1 || payload.kdf !== "PBKDF2" || payload.hash !== "SHA-256") {
      throw new Error("Unsupported encrypted chapter format.");
    }
    const key = await deriveKey(password, fromBase64(payload.salt), payload.iterations);
    const plaintext = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv: fromBase64(payload.iv) },
      key,
      fromBase64(payload.ciphertext),
    );
    return decoder.decode(plaintext);
  }

  function escapeHtml(value) {
    return value
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function inlineMarkdown(value) {
    let html = escapeHtml(value);
    html = html.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, '<img src="$2" alt="$1">');
    html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2">$1</a>');
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    html = html.replace(/\*([^*]+)\*/g, "<em>$1</em>");
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    return html;
  }

  function isRule(line) {
    return /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/.test(line);
  }

  function isList(line) {
    return /^ {0,3}[-*+]\s+/.test(line);
  }

  function renderParagraph(lines) {
    return `<p>${inlineMarkdown(lines.join(" ").trim())}</p>`;
  }

  function renderList(lines) {
    const items = [];
    let current = [];
    lines.forEach((line) => {
      if (isList(line)) {
        if (current.length) {
          items.push(current.join(" "));
        }
        current = [line.replace(/^ {0,3}[-*+]\s+/, "")];
      } else if (current.length) {
        current.push(line.trim());
      }
    });
    if (current.length) {
      items.push(current.join(" "));
    }
    return `<ul>${items.map((item) => `<li>${inlineMarkdown(item.trim())}</li>`).join("")}</ul>`;
  }

  function renderBlockquote(lines) {
    const quote = lines.map((line) => line.replace(/^ {0,3}>\s?/, "")).join("\n");
    return `<blockquote>${renderMarkdown(quote)}</blockquote>`;
  }

  function renderMarkdown(markdown) {
    const cleaned = markdown
      .replace(/<!--[\s\S]*?-->/g, "")
      .replace(/\r\n?/g, "\n")
      .trim();
    if (!cleaned) {
      return "";
    }
    const blocks = cleaned.split(/\n{2,}/);
    return blocks.map((block) => {
      const lines = block.trim().split("\n").filter((line) => line.trim());
      const heading = /^(#{1,6})\s+(.+)$/.exec(lines[0] || "");
      if (heading && lines.length === 1) {
        const level = heading[1].length;
        return `<h${level}>${inlineMarkdown(heading[2])}</h${level}>`;
      }
      if (lines.length === 1 && isRule(lines[0])) {
        return "<hr>";
      }
      if (lines.some(isList)) {
        return renderList(lines);
      }
      if (lines.every((line) => /^ {0,3}>\s?/.test(line))) {
        return renderBlockquote(lines);
      }
      return renderParagraph(lines);
    }).join("\n");
  }

  function payloadFor(block) {
    const payloadNode = block.querySelector(".encrypted-block__payload");
    const raw = payloadNode
      ? (payloadNode.content ? payloadNode.content.textContent : payloadNode.textContent)
      : "{}";
    const parsed = JSON.parse(raw);
    return typeof parsed === "string" ? JSON.parse(parsed) : parsed;
  }

  function initBlock(block) {
    const form = block.querySelector(".encrypted-block__form");
    const input = block.querySelector(".encrypted-block__input");
    const message = block.querySelector(".encrypted-block__message");

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      message.textContent = "Unlocking...";
      try {
        const plaintext = await decryptPayload(payloadFor(block), input.value);
        const unlocked = document.createElement("div");
        unlocked.className = "encrypted-block__unlocked";
        unlocked.innerHTML = renderMarkdown(plaintext);
        block.replaceWith(...Array.from(unlocked.childNodes));
      } catch (error) {
        message.textContent = "That password did not unlock this chapter.";
        input.select();
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!window.crypto || !crypto.subtle) {
      document.querySelectorAll(".encrypted-block__message").forEach((message) => {
        message.textContent = "This browser does not support Web Crypto.";
      });
      return;
    }
    document.querySelectorAll(".encrypted-block").forEach(initBlock);
  });
}());
