import Markdown from "react-markdown";

export function AssistantMarkdown({ content }: { content: string }): JSX.Element {
  return (
    <div className="assistant-markdown">
      <Markdown
        components={{
          a: ({ children, href, title }) => (
            <a href={href} title={title} rel="noreferrer noopener" target="_blank">
              {children}
            </a>
          ),
        }}
      >
        {content}
      </Markdown>
    </div>
  );
}
