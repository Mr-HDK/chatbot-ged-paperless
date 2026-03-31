import { useEffect, useMemo, useRef, useState } from "react";

const CHAT_ENDPOINT = import.meta.env.VITE_API_CHAT_ENDPOINT || "/api/chat";
const HEALTH_OLLAMA_ENDPOINT = import.meta.env.VITE_API_HEALTH_OLLAMA_ENDPOINT || "/api/health/ollama";
const MAX_SOURCES_DISPLAY = 3;

function renderInlineWithBold(text) {
  const normalized = text.replace(/\\\*/g, "*");
  const parts = [];
  const boldPattern = /\*\*(.+?)\*\*/g;
  let lastIndex = 0;
  let match = boldPattern.exec(normalized);

  while (match) {
    if (match.index > lastIndex) {
      parts.push(normalized.slice(lastIndex, match.index));
    }
    parts.push(<strong key={`strong-${match.index}`}>{match[1]}</strong>);
    lastIndex = match.index + match[0].length;
    match = boldPattern.exec(normalized);
  }

  if (lastIndex < normalized.length) {
    parts.push(normalized.slice(lastIndex));
  }

  return parts;
}

function FormattedMessage({ text }) {
  const lines = (text || "").split("\n");

  return (
    <div className="formatted-text">
      {lines.map((line, index) => {
        const trimmed = line.trim();
        if (!trimmed) {
          return <br key={`br-${index}`} />;
        }
        if (trimmed.startsWith(">")) {
          return <blockquote key={`quote-${index}`}>{renderInlineWithBold(trimmed.replace(/^>\s?/, ""))}</blockquote>;
        }
        return <p key={`line-${index}`}>{renderInlineWithBold(line)}</p>;
      })}
    </div>
  );
}

function SourceCard({ source, index }) {
  const [expanded, setExpanded] = useState(false);
  const text = source.snippet || "Aucun extrait fourni.";

  return (
    <article className="source-card">
      <header className="source-header">
        <h4>
          {index + 1}. {source.title}
        </h4>
        <span className="source-id">ID: {source.id}</span>
      </header>
      <p className={expanded ? "snippet expanded" : "snippet"}>{text}</p>
      {text.length > 170 && (
        <button
          type="button"
          className="link-button"
          onClick={() => setExpanded((value) => !value)}
        >
          {expanded ? "Reduire" : "Voir plus"}
        </button>
      )}
    </article>
  );
}

function ConfidenceBadge({ confidence }) {
  const label = confidence || "low";
  return <span className={`confidence ${label}`}>Confiance: {label}</span>;
}

export default function App() {
  const [question, setQuestion] = useState("");
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [activeModel, setActiveModel] = useState("");
  const messagesEndRef = useRef(null);

  const canSend = useMemo(() => question.trim().length > 0 && !loading, [question, loading]);

  useEffect(() => {
    const fetchModel = async () => {
      try {
        const response = await fetch(HEALTH_OLLAMA_ENDPOINT);
        if (!response.ok) return;
        const payload = await response.json();
        if (typeof payload.model === "string" && payload.model.trim()) {
          setActiveModel(payload.model.trim());
        }
      } catch {
        // Keep UI silent when endpoint is unavailable.
      }
    };

    fetchModel();
  }, []);

  const scrollToBottom = () => {
    setTimeout(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }, 40);
  };

  const sendQuestion = async () => {
    const cleanQuestion = question.trim();
    if (!cleanQuestion || loading) return;

    setError("");
    setLoading(true);
    setQuestion("");

    setMessages((current) => [
      ...current,
      {
        role: "user",
        content: cleanQuestion
      }
    ]);
    scrollToBottom();

    try {
      const response = await fetch(CHAT_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: cleanQuestion })
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || "Erreur serveur.");
      }

      const payload = await response.json();
      setMessages((current) => [
        ...current,
        {
          role: "assistant",
          content: payload.answer,
          sources: (payload.sources || []).slice(0, MAX_SOURCES_DISPLAY),
          confidence: payload.confidence || "low"
        }
      ]);
      scrollToBottom();
    } catch (err) {
      setError(err.message || "Une erreur inattendue est survenue.");
    } finally {
      setLoading(false);
    }
  };

  const onSubmit = (event) => {
    event.preventDefault();
    sendQuestion();
  };

  return (
    <main className="page">
      <section className="shell">
        <header className="header">
          <p className="eyebrow">Assistant documentaire interne</p>
          <h1>Meine_chatbot</h1>
          <p className="subtitle">
            Posez une question en francais. La reponse est generee uniquement a partir des documents
            Paperless retrouves.
          </p>
          {activeModel && (
            <p className="model-hint" title={activeModel}>
              Modele actif local: {activeModel}
            </p>
          )}
        </header>

        <section className="conversation" aria-live="polite">
          {messages.length === 0 && (
            <div className="empty-state">
              <h2>Commencez une conversation</h2>
              <p>Exemple: Quels sont les delais de validation des factures fournisseurs ?</p>
            </div>
          )}

          {messages.map((message, index) => (
            <div
              key={`${message.role}-${index}-${message.content.slice(0, 20)}`}
              className={message.role === "user" ? "bubble-row user" : "bubble-row bot"}
            >
              <article className={message.role === "user" ? "bubble user" : "bubble bot"}>
                <FormattedMessage text={message.content} />
                {message.role === "assistant" && (
                  <div className="bot-meta">
                    <ConfidenceBadge confidence={message.confidence} />
                    {message.sources?.length > 0 && (
                      <div className="sources">
                        <h3>Sources utilisees</h3>
                        {message.sources.map((source, sourceIndex) => (
                          <SourceCard key={`${source.id}-${sourceIndex}`} source={source} index={sourceIndex} />
                        ))}
                      </div>
                    )}
                  </div>
                )}
              </article>
            </div>
          ))}

          {loading && (
            <div className="bubble-row bot">
              <article className="bubble bot loading">
                <p>Analyse des documents en cours...</p>
              </article>
            </div>
          )}

          <div ref={messagesEndRef} />
        </section>

        {error && <p className="error-banner">{error}</p>}

        <form className="composer" onSubmit={onSubmit}>
          <label htmlFor="question" className="sr-only">
            Votre question
          </label>
          <textarea
            id="question"
            rows={3}
            placeholder="Ecrivez votre question en francais..."
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
          />
          <button type="submit" disabled={!canSend}>
            {loading ? "Envoi..." : "Envoyer"}
          </button>
        </form>
      </section>
    </main>
  );
}
