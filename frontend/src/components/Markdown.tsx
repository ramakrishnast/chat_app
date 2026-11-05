import { isValidElement, memo, useRef, useState, type ComponentPropsWithoutRef } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import { copyText } from "./copy";

type WithNode<T> = T & { node?: unknown };

/** react-markdown passes its AST `node` to custom components; keep it off the DOM element. */
function withoutNode<T extends object>(props: WithNode<T>): T {
  const copy: WithNode<T> = { ...props };
  delete copy.node;
  return copy;
}

function CodeBlock(props: WithNode<ComponentPropsWithoutRef<"pre">>) {
  const { children, ...rest } = withoutNode(props);
  const ref = useRef<HTMLPreElement>(null);
  const [copied, setCopied] = useState(false);
  const className = isValidElement<{ className?: string }>(children)
    ? (children.props.className ?? "")
    : "";
  const language = /language-([\w+#-]+)/.exec(className)?.[1] ?? "text";

  const copy = async () => {
    if (await copyText(ref.current?.innerText ?? "")) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    }
  };

  return (
    <div className="code-block">
      <div className="code-header">
        <span>{language}</span>
        <button type="button" onClick={copy}>
          {copied ? "Copied" : "Copy code"}
        </button>
      </div>
      <pre ref={ref} {...rest}>
        {children}
      </pre>
    </div>
  );
}

const components: Components = {
  pre: CodeBlock,
  a: (props) => <a {...withoutNode(props)} target="_blank" rel="noopener noreferrer" />,
};

/** Model output rendered as GitHub-flavoured Markdown. Raw HTML in the text is not rendered. */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="markdown">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeHighlight]}
        components={components}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
