const map: Record<string, string> = {
  POSITIVE:   "badge badge-positive",
  NEGATIVE:   "badge badge-negative",
  NEUTRAL:    "badge badge-neutral",
  HATE_SPEECH:"badge badge-hate",
  TOXIC:      "badge badge-toxic",
  HUMOR:      "badge badge-humor",
  SARCASM:    "badge badge-sarcasm",
  positive:   "badge badge-positive",
  negative:   "badge badge-negative",
  neutral:    "badge badge-neutral",
};

export default function StatusBadge({ category }: { category: string }) {
  const cls = map[category] ?? "badge badge-neutral";
  return <span className={cls}>{category}</span>;
}
