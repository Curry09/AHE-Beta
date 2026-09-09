import type { ExperimentSummary } from "../api";

export function ExperimentPicker(props: {
  experiments: ExperimentSummary[];
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  if (props.experiments.length === 0) return null;
  return (
    <div className="experiment-picker">
      <span className="experiment-picker-label">实验</span>
      <select
        aria-label="选择实验"
        value={props.selected ?? props.experiments[0].id}
        onChange={(event) => props.onSelect(event.target.value)}
      >
        {props.experiments.map((experiment) => (
          <option key={experiment.id} value={experiment.id}>
            {experiment.title} · {experiment.status}
          </option>
        ))}
      </select>
    </div>
  );
}
