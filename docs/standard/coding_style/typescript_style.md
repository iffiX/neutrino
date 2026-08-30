# TypeScript style

The frontend (`hub/frontend/`) is React + TypeScript + Vite. These rules keep it
consistent with the rest of the repo and reviewer-legible. The Python rules in
[python_style.md](python_style.md) and the naming rules in [naming_style.md](naming_style.md)
still set the shared intent; this file is the TypeScript-specific surface.

## Example

```tsx
// BAD — PascalCase file, `any`, inline lambda soup, bool named as noun
// NodesPage.tsx
export function NodesPage(props: any) {
  const [nodes, setNodes] = useState<any>([]);
  const active = nodes.filter((n: any) => n.enabled);   // `enabled` not is_
  return <div>{active.map((n: any) => <span>{n.name}</span>)}</div>;
}

// GOOD — under_score file, explicit types, is_ bool, named handler
// nodes_page.tsx
interface NodesPageProps {
  onApply: () => void;
}

export function NodesPage({ onApply }: NodesPageProps) {
  const [nodes, setNodes] = useState<XrayNode[]>([]);
  const activeNodes = nodes.filter((node) => node.is_enabled);
  return (
    <div>
      {activeNodes.map((node) => (
        <NodeCard key={node.id} node={node} />
      ))}
    </div>
  );
}
```

## Formatting and linting

- Prettier is the formatter; `prettier --check` must pass on every change.
- ESLint with `typescript-eslint` must pass with no errors. Do not disable a
  rule inline to silence a real problem.

## Files and directories

- Files and directories use `under_score`, exactly like the Python side:
  `nodes_page.tsx`, `use_stats_socket.ts`, `api_client.ts`. This is the one
  place React convention (PascalCase files) is overridden — the *identifier*
  stays PascalCase, only the *filename* is under_score.
- One component or one hook per file, named after the file's one concept.

## Naming

- Components, types, and interfaces are `PascalCase` (`NodesPage`, `XrayNode`,
  `NodesPageProps`). Variables, functions, and hooks are `camelCase`
  (`activeNodes`, `useStatsSocket`).
- Booleans use `is_` / `has_` on data fields that mirror the backend
  (`is_enabled`, `has_reality`) and `isX` / `hasX` on local React state where
  camelCase reads more naturally. Keep a field that crosses the API boundary
  spelled the same on both sides.
- A hook file is `use_<thing>.ts` exporting `use<Thing>`.

## Types

- No `any`. Reach for `unknown` and narrow, or write the real type.
- `import type { ... }` for type-only imports, separate from value imports.
- API request and response types live in one `hub/frontend/src/api_types.ts`,
  kept field-for-field in sync with the backend Pydantic models. The frontend
  never invents a shape the backend does not send.

## Component internal order

Inside a component: the props interface (above the component), then hooks
(`useState`, `useEffect`, custom hooks), then event handlers and derived values,
then the returned JSX. Helpers that do not use component state are named module
functions outside the component, never inline lambdas assigned to variables.
