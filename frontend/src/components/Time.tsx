import { formatTime } from "../chat/format";

export function Time({ iso }: { iso: string | null }) {
  if (!iso) return null;
  return (
    <time className="timestamp" dateTime={iso} title={new Date(iso).toLocaleString()}>
      {formatTime(iso)}
    </time>
  );
}
