/** Big number with a label (review queue summary). */
export function StatCard({ value, label }: { value: string; label: string }) {
  return (
    <div className="flex-1 rounded-lg border border-default bg-surface p-4 shadow-card">
      <p className="font-display text-[22px] font-medium leading-7 text-primary">{value}</p>
      <p className="text-[13px] text-secondary">{label}</p>
    </div>
  );
}
