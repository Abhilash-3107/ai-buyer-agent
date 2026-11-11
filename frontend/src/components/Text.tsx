import { Fragment } from "react";

const ID = /\b((?:PO|SKU|SUP|ESC|REC|EVT|DS)-[A-Z0-9]+(?:-[A-Z0-9]+)*)\b/g;

/** Text with the ids it mentions set in the mono face. */
export function WithIds({ text }: { text: string }) {
  const parts = text.split(ID);
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? (
          <span key={i} className="mono">{p}</span>
        ) : (
          <Fragment key={i}>{p}</Fragment>
        ),
      )}
    </>
  );
}
