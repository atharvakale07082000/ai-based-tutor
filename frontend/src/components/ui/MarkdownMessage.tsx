import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

function StreamCursor() {
  return (
    <span
      aria-hidden="true"
      style={{
        display: 'inline-block',
        width: 7,
        height: 14,
        background: 'var(--ink-0)',
        verticalAlign: 'middle',
        marginLeft: 3,
        borderRadius: 1,
        animation: 'blink 1s steps(1) infinite',
      }}
    />
  )
}

interface MarkdownMessageProps {
  content: string
  streaming?: boolean
  /** Extra className applied to the prose wrapper */
  className?: string
}

export function MarkdownMessage({ content, streaming, className }: MarkdownMessageProps) {
  return (
    <div
      className={['prose-atelier', className].filter(Boolean).join(' ')}
      style={{ fontSize: 14, lineHeight: 1.7, color: 'var(--ink-1)' }}
    >
      {streaming && !content ? (
        <span className="t-sm fg-3" style={{ fontStyle: 'italic' }}>
          Thinking<span style={{ animation: 'pulse-soft 1.4s ease-in-out infinite' }}>…</span>
        </span>
      ) : (
        <ReactMarkdown
          components={{
            /* Strip the default <pre> wrapper so SyntaxHighlighter owns its own container */
            pre({ children }) {
              return <div className="prose-pre-wrapper">{children}</div>
            },
            code({ className: cls, children, ...props }) {
              const match = /language-(\w+)/.exec(cls || '')
              if (match) {
                return (
                  <SyntaxHighlighter
                    language={match[1]}
                    style={oneDark}
                    PreTag="div"
                    customStyle={{
                      borderRadius: 'var(--r-3)',
                      fontSize: '13px',
                      lineHeight: 1.55,
                      padding: '14px 16px',
                      margin: 0,
                      fontFamily: 'var(--font-mono)',
                      overflowX: 'auto',
                    }}
                    codeTagProps={{ style: { fontFamily: 'var(--font-mono)' } }}
                  >
                    {String(children).replace(/\n$/, '')}
                  </SyntaxHighlighter>
                )
              }
              /* Inline code */
              return (
                <code
                  style={{
                    fontFamily: 'var(--font-mono)',
                    background: 'var(--paper-2)',
                    padding: '2px 6px',
                    borderRadius: 'var(--r-1)',
                    fontSize: '0.875em',
                    color: 'var(--accent)',
                    border: '1px solid var(--line-1)',
                  }}
                  {...props}
                >
                  {children}
                </code>
              )
            },
            /* Normalize blockquote */
            blockquote({ children }) {
              return (
                <blockquote
                  style={{
                    borderLeft: '3px solid var(--accent)',
                    paddingLeft: '1rem',
                    margin: '0.6em 0',
                    color: 'var(--ink-2)',
                    fontStyle: 'italic',
                  }}
                >
                  {children}
                </blockquote>
              )
            },
            /* Table with border */
            table({ children }) {
              return (
                <div style={{ overflowX: 'auto', margin: '0.7em 0' }}>
                  <table
                    style={{
                      width: '100%',
                      borderCollapse: 'collapse',
                      fontSize: 'var(--t-sm)',
                      border: '1px solid var(--line-1)',
                      borderRadius: 'var(--r-2)',
                    }}
                  >
                    {children}
                  </table>
                </div>
              )
            },
            th({ children }) {
              return (
                <th
                  style={{
                    background: 'var(--paper-2)',
                    padding: '6px 10px',
                    textAlign: 'left',
                    fontWeight: 600,
                    color: 'var(--ink-0)',
                    borderBottom: '1px solid var(--line-2)',
                  }}
                >
                  {children}
                </th>
              )
            },
            td({ children }) {
              return (
                <td
                  style={{
                    padding: '6px 10px',
                    borderBottom: '1px solid var(--line-1)',
                    color: 'var(--ink-1)',
                  }}
                >
                  {children}
                </td>
              )
            },
            /* Anchor */
            a({ children, href }) {
              return (
                <a
                  href={href}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{
                    color: 'var(--accent)',
                    textDecoration: 'underline',
                    textDecorationThickness: '1px',
                    textUnderlineOffset: '2px',
                  }}
                >
                  {children}
                </a>
              )
            },
          }}
        >
          {content}
        </ReactMarkdown>
      )}
      {streaming && content && <StreamCursor />}
    </div>
  )
}
