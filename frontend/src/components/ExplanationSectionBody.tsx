import type { ReactNode } from 'react';

const URL_PATTERN = /(https:\/\/[^\s;,)]+)/g;
const NUMBERED = /^\d+\.\s+/;

/** Render text with https URLs as links. Everything else stays escaped plain text. */
function linkify(text: string): ReactNode {
  const parts = text.split(URL_PATTERN);
  if (parts.length === 1) return text;
  return parts.map((part, index) => (index % 2 === 1
    ? <a key={`${part}-${index}`} href={part} target="_blank" rel="noreferrer">{part}</a>
    : part));
}

/**
 * Knowledge-base section bodies use one item per line. A single line renders
 * as a paragraph; several lines render as a list (numbered when the source is).
 */
export default function ExplanationSectionBody({ body }: { body: string }) {
  const lines = body.split('\n').map((line) => line.trim()).filter(Boolean);
  if (lines.length <= 1) return <p>{linkify(lines[0] ?? body)}</p>;
  if (lines.every((line) => NUMBERED.test(line))) {
    return <ol className="explanation-list">{lines.map((line, index) => <li key={index}>{linkify(line.replace(NUMBERED, ''))}</li>)}</ol>;
  }
  return <ul className="explanation-list">{lines.map((line, index) => <li key={index}>{linkify(line)}</li>)}</ul>;
}
