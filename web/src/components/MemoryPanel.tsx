import { FormEvent, useState } from "react";
import { api, MemoryItem } from "../api";
import { timeAgo, useAsync } from "../hooks";
import { Badge, Collapsible, ErrorBox, Switch } from "./ui";

/** Per-repo reviewer memory: maintainer rules and dismissed findings. */
export function MemoryPanel({ repo }: { repo: string }) {
  const memory = useAsync(() => api.memory(repo), [repo]);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const items = memory.data ?? [];
  const rules = items.filter((m) => m.kind === "rule");
  const dismissed = items.filter((m) => m.kind === "suppress");

  const replace = (next: MemoryItem) => memory.setData((list) => list?.map((m) => (m.id === next.id ? next : m)));
  const act = async (fn: () => Promise<void>) => {
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const addRule = (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    void act(async () => {
      const item = await api.addRule(repo, text);
      memory.setData((list) => [item, ...(list ?? [])]);
      setText("");
    });
  };

  const row = (m: MemoryItem) => (
    <li key={m.id} className={`memory-row ${m.active ? "" : "inactive"}`}>
      <Switch checked={m.active} label="" onChange={(v) => act(async () => replace(await api.patchMemory(m.id, { active: v })))} />
      <div className="memory-main">
        <div className="memory-text">{m.text}</div>
        <div className="muted small">
          {m.kind === "suppress" && (m.path ? <span className="mono">{m.path}</span> : "tüm repo")}
          {m.rule_id && <> · <span className="mono">{m.rule_id}</span></>}
          {m.kind === "suppress" && " · "}
          {m.hits > 0 ? `${m.hits} kez uygulandı` : "henüz uygulanmadı"} · {timeAgo(m.created_at)}
        </div>
      </div>
      <button className="link-btn small" onClick={() => act(async () => {
        await api.deleteMemory(m.id);
        memory.setData((list) => list?.filter((x) => x.id !== m.id));
      })}>Sil</button>
    </li>
  );

  return (
    <Collapsible title="Repo hafızası" count={items.filter((m) => m.active).length}
                 hint="Review'lar bu kurallara uyar; susturulan yorumlar tekrarlanmaz">
      {error && <ErrorBox error={error} />}
      {memory.error && <ErrorBox error={memory.error} onRetry={memory.reload} />}
      <form className="memory-form" onSubmit={addRule}>
        <input className="input" value={text} onChange={(e) => setText(e.target.value)} maxLength={1000}
               placeholder="Yeni kural, ör. “Bu repoda state yönetimi için Riverpod kullanılıyor; Provider önerme.”" />
        <button className="btn btn-primary" type="submit" disabled={!text.trim()}>Kural ekle</button>
      </form>
      <div className="memory-cols">
        <section>
          <h3>Kurallar <Badge tone="muted">{rules.length}</Badge></h3>
          {rules.length ? <ul className="memory-list">{rules.map(row)}</ul>
            : <p className="muted small">Henüz kural yok. Reviewer'a bu repoya özel talimatlar verebilirsin.</p>}
        </section>
        <section>
          <h3>Susturulanlar <Badge tone="muted">{dismissed.length}</Badge></h3>
          {dismissed.length ? <ul className="memory-list">{dismissed.map(row)}</ul>
            : <p className="muted small">Yorumlardaki “Bunu bir daha söyleme” ile eklenir.</p>}
        </section>
      </div>
    </Collapsible>
  );
}
