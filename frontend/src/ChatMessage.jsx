import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

const components = {
  a({ href, children }) {
    return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
  },
  table({ children }) {
    return (
      <div className="chat-table-scroll" tabIndex={0} role="region" aria-label="Таблица в ответе помощника">
        <table>{children}</table>
      </div>
    );
  },
};

export default function ChatMessage({ text }) {
  return (
    <div className="chat-markdown">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components} skipHtml disallowedElements={['img']}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
