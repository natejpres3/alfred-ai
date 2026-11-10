"use client";

import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { cn } from "@/lib/utils";

/** Markdown + GFM tables + $LaTeX$ (KaTeX) + highlighted code. Raw HTML is not rendered. */
export function Markdown({ children, className, compact = false }: { children: string; className?: string; compact?: boolean }) {
  return (
    <div className={cn("lesson-prose prose max-w-none dark:prose-invert", compact && "prose-sm text-[0.95rem]", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[[rehypeKatex, { throwOnError: false, strict: "ignore" }], [rehypeHighlight, { detect: false, ignoreMissing: true }]]}
        components={{
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}

export function MathBlock({ latex, caption }: { latex: string; caption?: string }) {
  return (
    <figure className="my-5">
      <Markdown>{`$$\n${latex}\n$$`}</Markdown>
      {caption && <figcaption className="-mt-2 text-center text-sm text-muted-foreground">{caption}</figcaption>}
    </figure>
  );
}
