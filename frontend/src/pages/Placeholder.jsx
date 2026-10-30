import Panel from '../components/Panel';

export default function Placeholder({ name }) {
  return (
    <Panel label={name} meta="not yet built">
      <div style={{ padding: 'var(--sp-6)', color: 'var(--c-text-faint)' }}>
        Pending build — awaiting Dashboard approval.
      </div>
    </Panel>
  );
}
