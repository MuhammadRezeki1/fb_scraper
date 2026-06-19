export default function LoadingSpinner({ size = 24, text }: { size?: number; text?: string }) {
  return (
    <div className="flex flex-col items-center gap-3">
      <div
        className="spinner"
        style={{ width: size, height: size, borderWidth: size > 30 ? 3 : 2 }}
      />
      {text && <p className="text-sm" style={{ color: "#8890aa" }}>{text}</p>}
    </div>
  );
}
