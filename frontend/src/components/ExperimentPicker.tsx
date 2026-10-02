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
      <span className="experiment-picker-label">历史快照</span>
      <select
        aria-label="选择历史实验快照"
        value={props.selected ?? props.experiments[0].id}
        onChange={(event) => props.onSelect(event.target.value)}
      >
        {props.experiments.map((experiment) => (
          <option key={experiment.id} value={experiment.id}>
            {experiment.title} · 当时状态 {experiment.status}
          </option>
        ))}
      </select>
      {selected && (
        <span className="snapshot-recorded-at">
          记录时间：<time dateTime={selected.updated_at}>{formatSnapshotTime(selected.updated_at)}</time>
        </span>
      )}
    </div>
  );
}
