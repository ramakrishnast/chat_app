import type { ModelInfo } from "../contract";

interface Props {
  models: ModelInfo[];
  value: string | null;
  thinking: boolean;
  disabled: boolean;
  onChange: (id: string) => void;
  onThinkingChange: (value: boolean) => void;
  onRefresh: () => void;
}

const PROVIDER_LABEL: Record<string, string> = {
  ollama: "Ollama (local)",
  openai: "OpenAI",
  anthropic: "Anthropic",
  fake: "Offline test model",
};

export function ModelPicker({
  models,
  value,
  thinking,
  disabled,
  onChange,
  onThinkingChange,
  onRefresh,
}: Props) {
  const current = models.find((m) => m.id === value);
  const providers = [...new Set(models.map((m) => m.provider))];

  return (
    <div className="model-picker">
      <select
        aria-label="Model"
        value={value ?? ""}
        disabled={disabled || (models.length === 0 && !value)}
        onChange={(e) => onChange(e.target.value)}
      >
        {!value && <option value="">No models</option>}
        {value && !current && <option value={value}>{value} (unavailable)</option>}
        {providers.map((provider) => (
          <optgroup key={provider} label={PROVIDER_LABEL[provider] ?? provider}>
            {models
              .filter((m) => m.provider === provider)
              .map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name}
                  {m.detail ? ` · ${m.detail}` : ""}
                </option>
              ))}
          </optgroup>
        ))}
      </select>
      <button
        type="button"
        className="icon-button"
        aria-label="Refresh model list"
        title="Refresh model list"
        disabled={disabled}
        onClick={onRefresh}
      >
        ↻
      </button>
      <label
        className={`think-toggle ${current && !current.thinking ? "unsupported" : ""}`}
        title={
          current && !current.thinking
            ? "This model doesn't support thinking"
            : "Let the model reason before answering (slower)"
        }
      >
        <input
          type="checkbox"
          checked={thinking}
          disabled={disabled}
          onChange={(e) => onThinkingChange(e.target.checked)}
        />
        Think
      </label>
    </div>
  );
}
