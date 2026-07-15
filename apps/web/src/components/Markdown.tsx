"use client";

import { Fragment, type ReactNode } from "react";

/**
 * Tiny, dependency-free Markdown renderer. It covers the subset the factory
 * produces: headings, bold/italic/`code`, links, fenced code blocks, ordered
 * and unordered lists, blockquotes, tables (pipe), horizontal rules and
 * paragraphs. It is intentionally small — no external libraries — so the notes,
 * lessons and slide bodies render as real notebook text instead of raw source.
 */

type Block =
  | { kind: "heading"; level: number; text: string }
  | { kind: "code"; lang: string; code: string }
  | { kind: "ul"; items: string[] }
  | { kind: "ol"; items: string[] }
  | { kind: "quote"; lines: string[] }
  | { kind: "table"; header: string[]; rows: string[][] }
  | { kind: "hr" }
  | { kind: "p"; text: string };

function splitTableRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((c) => c.trim());
}

function isTableDivider(line: string): boolean {
  return /^\s*\|?[\s:|-]+\|?\s*$/.test(line) && line.includes("-");
}

function parseBlocks(src: string): Block[] {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    // Fenced code block
    const fence = line.match(/^```(\w*)\s*$/);
    if (fence) {
      const lang = fence[1] || "";
      const code: string[] = [];
      i++;
      while (i < lines.length && !/^```\s*$/.test(lines[i])) {
        code.push(lines[i]);
        i++;
      }
      i++; // closing fence
      blocks.push({ kind: "code", lang, code: code.join("\n") });
      continue;
    }

    // Blank line
    if (line.trim() === "") {
      i++;
      continue;
    }

    // Horizontal rule
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) {
      blocks.push({ kind: "hr" });
      i++;
      continue;
    }

    // Heading
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2].trim() });
      i++;
      continue;
    }

    // Table
    if (line.includes("|") && i + 1 < lines.length && isTableDivider(lines[i + 1])) {
      const header = splitTableRow(line);
      const rows: string[][] = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim() !== "") {
        rows.push(splitTableRow(lines[i]));
        i++;
      }
      blocks.push({ kind: "table", header, rows });
      continue;
    }

    // Blockquote
    if (/^\s*>\s?/.test(line)) {
      const quote: string[] = [];
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^\s*>\s?/, ""));
        i++;
      }
      blocks.push({ kind: "quote", lines: quote });
      continue;
    }

    // Ordered list
    if (/^\s*\d+[.)]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*\d+[.)]\s+/, ""));
        i++;
      }
      blocks.push({ kind: "ol", items });
      continue;
    }

    // Unordered list
    if (/^\s*[-*+]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*+]\s+/, ""));
        i++;
      }
      blocks.push({ kind: "ul", items });
      continue;
    }

    // Paragraph (gather until blank line or next block starter)
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !/^```/.test(lines[i]) &&
      !/^(#{1,6})\s+/.test(lines[i]) &&
      !/^\s*[-*+]\s+/.test(lines[i]) &&
      !/^\s*\d+[.)]\s+/.test(lines[i]) &&
      !/^\s*>\s?/.test(lines[i])
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push({ kind: "p", text: para.join(" ") });
  }

  return blocks;
}

/** Render inline markdown (bold, italic, code, links) into React nodes. */
function renderInline(text: string, keyPrefix = ""): ReactNode[] {
  const nodes: ReactNode[] = [];
  // Order matters: code first (so ** inside code is literal), then link, bold, italic.
  const pattern =
    /(`[^`]+`)|(\[[^\]]+\]\([^)]+\))|(\*\*[^*]+\*\*)|(__[^_]+__)|(\*[^*]+\*)|(_[^_]+_)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let n = 0;

  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      nodes.push(<Fragment key={`${keyPrefix}t${n++}`}>{text.slice(last, match.index)}</Fragment>);
    }
    const token = match[0];
    const key = `${keyPrefix}m${n++}`;
    if (token.startsWith("`")) {
      nodes.push(
        <code key={key} className="md-code-inline">
          {token.slice(1, -1)}
        </code>,
      );
    } else if (token.startsWith("[")) {
      const linkMatch = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
      if (linkMatch) {
        nodes.push(
          <a key={key} href={linkMatch[2]} target="_blank" rel="noreferrer" className="md-link">
            {renderInline(linkMatch[1], key)}
          </a>,
        );
      }
    } else if (token.startsWith("**") || token.startsWith("__")) {
      nodes.push(
        <strong key={key} className="font-bold">
          {renderInline(token.slice(2, -2), key)}
        </strong>,
      );
    } else {
      nodes.push(
        <em key={key} className="italic">
          {renderInline(token.slice(1, -1), key)}
        </em>,
      );
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) {
    nodes.push(<Fragment key={`${keyPrefix}t${n++}`}>{text.slice(last)}</Fragment>);
  }
  return nodes;
}

function renderBlock(block: Block, key: string): ReactNode {
  switch (block.kind) {
    case "heading": {
      const cls = ["md-h1", "md-h2", "md-h3", "md-h4", "md-h5", "md-h6"][block.level - 1];
      const inner = renderInline(block.text, key);
      switch (block.level) {
        case 1:
          return <h1 key={key} className={cls}>{inner}</h1>;
        case 2:
          return <h2 key={key} className={cls}>{inner}</h2>;
        case 3:
          return <h3 key={key} className={cls}>{inner}</h3>;
        case 4:
          return <h4 key={key} className={cls}>{inner}</h4>;
        case 5:
          return <h5 key={key} className={cls}>{inner}</h5>;
        default:
          return <h6 key={key} className={cls}>{inner}</h6>;
      }
    }
    case "code":
      return (
        <pre key={key} className="md-pre">
          <code>{block.code}</code>
        </pre>
      );
    case "ul":
      return (
        <ul key={key} className="md-ul">
          {block.items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `${key}-${idx}`)}</li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={key} className="md-ol">
          {block.items.map((item, idx) => (
            <li key={idx}>{renderInline(item, `${key}-${idx}`)}</li>
          ))}
        </ol>
      );
    case "quote":
      return (
        <blockquote key={key} className="md-quote">
          {parseBlocks(block.lines.join("\n")).map((b, idx) => renderBlock(b, `${key}-${idx}`))}
        </blockquote>
      );
    case "table":
      return (
        <div key={key} className="md-table-wrap">
          <table className="md-table">
            <thead>
              <tr>
                {block.header.map((cell, idx) => (
                  <th key={idx}>{renderInline(cell, `${key}-h${idx}`)}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={r}>
                  {row.map((cell, c) => (
                    <td key={c}>{renderInline(cell, `${key}-${r}-${c}`)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "hr":
      return <hr key={key} className="md-hr" />;
    case "p":
      return (
        <p key={key} className="md-p">
          {renderInline(block.text, key)}
        </p>
      );
  }
}

export default function Markdown({
  children,
  className = "",
}: {
  children: string;
  className?: string;
}) {
  const blocks = parseBlocks(children || "");
  return (
    <div className={`md ${className}`.trim()}>
      {blocks.map((block, idx) => renderBlock(block, `b${idx}`))}
    </div>
  );
}
