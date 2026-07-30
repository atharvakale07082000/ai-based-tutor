import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { PrismLight as SyntaxHighlighter } from 'react-syntax-highlighter'
import oneDark from 'react-syntax-highlighter/dist/esm/styles/prism/one-dark'

import bash from 'react-syntax-highlighter/dist/esm/languages/prism/bash'
import c from 'react-syntax-highlighter/dist/esm/languages/prism/c'
import cpp from 'react-syntax-highlighter/dist/esm/languages/prism/cpp'
import csharp from 'react-syntax-highlighter/dist/esm/languages/prism/csharp'
import css from 'react-syntax-highlighter/dist/esm/languages/prism/css'
import cssExtras from 'react-syntax-highlighter/dist/esm/languages/prism/css-extras'
import docker from 'react-syntax-highlighter/dist/esm/languages/prism/docker'
import go from 'react-syntax-highlighter/dist/esm/languages/prism/go'
import hcl from 'react-syntax-highlighter/dist/esm/languages/prism/hcl'
import java from 'react-syntax-highlighter/dist/esm/languages/prism/java'
import javascript from 'react-syntax-highlighter/dist/esm/languages/prism/javascript'
import jsExtras from 'react-syntax-highlighter/dist/esm/languages/prism/js-extras'
import jsTemplates from 'react-syntax-highlighter/dist/esm/languages/prism/js-templates'
import json from 'react-syntax-highlighter/dist/esm/languages/prism/json'
import jsx from 'react-syntax-highlighter/dist/esm/languages/prism/jsx'
import kotlin from 'react-syntax-highlighter/dist/esm/languages/prism/kotlin'
import markup from 'react-syntax-highlighter/dist/esm/languages/prism/markup'
import php from 'react-syntax-highlighter/dist/esm/languages/prism/php'
import python from 'react-syntax-highlighter/dist/esm/languages/prism/python'
import ruby from 'react-syntax-highlighter/dist/esm/languages/prism/ruby'
import rust from 'react-syntax-highlighter/dist/esm/languages/prism/rust'
import sql from 'react-syntax-highlighter/dist/esm/languages/prism/sql'
import swift from 'react-syntax-highlighter/dist/esm/languages/prism/swift'
import tsx from 'react-syntax-highlighter/dist/esm/languages/prism/tsx'
import typescript from 'react-syntax-highlighter/dist/esm/languages/prism/typescript'
import yaml from 'react-syntax-highlighter/dist/esm/languages/prism/yaml'

/*
 * Syntax highlighting — explicit grammar registration.
 *
 * The full `Prism` build statically pulls in every refractor grammar (~557
 * modules) plus highlight.js (~384): a single ~685 kB / 242 kB gzip chunk that
 * `/atelier` and `/doubts` both wait on. `PrismLight` ships the same renderer
 * with no grammars, so we register exactly the languages this product emits:
 *
 *   · Everything the code runner / interview editor accepts — backend
 *     `services/code_runner.py::SUPPORTED_LANGUAGES` and its mirror
 *     `CODE_LANGUAGES` in ModuleInterviewPage (python, sql, javascript,
 *     typescript, java, c, cpp, csharp, go, rust, ruby, php, kotlin, swift, bash).
 *   · The markup/config languages the curriculum's own domains produce in tutor
 *     answers — `backend/app/prompts/curriculum.yaml` topic_graph: Web
 *     Development (HTML, CSS, React → jsx/tsx, REST APIs → json), DevOps and
 *     Cloud Computing (Kubernetes/Helm/CI → yaml, Docker, Terraform → hcl).
 *
 * Each grammar registers its own dependencies (cpp→c, php→markup-templating)
 * and its own aliases (py, js, ts, html, xml, yml, sh/shell, cs, dockerfile),
 * so only the top-level id needs listing here. `refractor/core` already ships
 * markup, css, clike and javascript; they are listed anyway so the supported
 * set is readable in one place, at no extra bytes.
 *
 * Keep this list in refractor's own registration order (alphabetical, see
 * `refractor/index.js`) — the *-extras grammars patch a base grammar in place,
 * so `js-extras`/`js-templates` must be registered before `jsx`/`tsx` copy
 * `javascript`. Registering them is what keeps output byte-identical to the
 * old full-Prism build (they add the `class`, `maybe-class-name`, `arrow` and
 * `property-access` tokens).
 *
 * An UNREGISTERED language is not an error path: refractor throws "Unknown
 * language", react-syntax-highlighter catches it internally (see `getCodeTree`)
 * and renders the source as one plain-text node inside the same oneDark <pre>.
 * So ```elixir degrades to a readable, correctly-framed but unhighlighted block.
 * Add a language here only when it becomes first-class in the product.
 */
const GRAMMARS = {
  bash, c, cpp, csharp, css, 'css-extras': cssExtras, docker, go, hcl, java,
  javascript, 'js-extras': jsExtras, 'js-templates': jsTemplates, json, jsx,
  kotlin, markup, php, python, ruby, rust, sql, swift, tsx, typescript, yaml,
}
for (const [name, grammar] of Object.entries(GRAMMARS)) {
  SyntaxHighlighter.registerLanguage(name, grammar)
}
// Ids the product itself uses that refractor has no alias for.
SyntaxHighlighter.alias({ python: ['python3'], cpp: ['c++'] })

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
          remarkPlugins={[remarkGfm]}
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
