import { formatSnapshotTime, type ExperimentSummary } from "../api";

export function ExperimentPicker(props: {
  experiments: ExperimentSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (props.experiments.length === 0) return null;
  const selected = props.experiments.find((item) => item.id === props.selected)
    ?? (props.selected ? undefined : props.experiments[0]);
  return (
    <div className="experiment-picker">
      <span className="experiment-picker-label">Historical snapshot</span>
      <select
        aria-label="Select historical experiment snapshot"
        value={props.selected ?? props.experiments[0].id}
        onChange={(event) => props.onSelect(event.target.value)}
      >
        {props.experiments.map((experiment) => (
          <option key={experiment.id} value={experiment.id}>
            {experiment.title} · Recorded state {experiment.status}
          </option>
        ))}
      </select>
      {selected && (
        <span className="snapshot-recorded-at">
          Recorded time: <time dateTime={selected.updated_at}>{formatSnapshotTime(selected.updated_at)}</time>
        </span>
      )}
    </div>
  );
}
